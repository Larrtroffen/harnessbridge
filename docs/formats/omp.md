# OMP (Oh My Pi) Session 格式逆向规格（~/.omp/agent, omp 18.12.6）

> 目标：让转换器把 OMP 的一次 session 还原成完整对话序列（用户/助手/thinking/工具调用/工具结果/压缩点/分支），并可映射到通用中间表示（IR）。
> 本机实测：`omp --version` = `omp/18.12.6`；`~/.omp/agent/sessions/` 下 **1,730 个 `.jsonl`**（43 个项目目录 + 1 个空的 `-` 目录；含同名伴生目录与子代理嵌套文件），全部 `session.version = 3`。
> 所有分析只读，未改动 `~/.omp` 任何文件。

---

## 1. 格式定位

OMP 的 transcript 是 **"树状事件流"（tree-based session）**，比 Codex 的线性 rollout 更接近 pi 系编码 agent 的做法：

- 每行一个 entry，`type` + 自增语义的 `id` + **`parentId`**（上一 entry 的 id）；**对话分支 = 树的分叉**，不是另起文件。
- 文件是**追加写**（append-only），但对 `title` 等元数据行做**原位重写**（用 `pad` 字段补空格保证行宽固定），所以**不能假设行序 = 事件时间序**（第一行恒为 `title`，第二行恒为 `session`）。
- 主 transcript 与工具日志**分文件存**：`sessions/<project-slug>/<ISO>_<uuid>.jsonl` + 同名目录 `sessions/<project-slug>/<ISO>_<uuid>/`；后者放 `<序号>.<tool>.log` 工具原始日志、`local/` 图片、以及**子代理 transcript**（嵌套 `.jsonl`）。

真实路径示例（本机）：
`~/.omp/agent/sessions/-Research_Assistant-【0804】专报绘图/2026-09-21T03-09-23-611Z_01a0c1f0-911b-7015-8732-eb4d209e1d9a.jsonl`
伴生目录：`.../2026-09-21T03-09-23-611Z_01a0c1f0-911b-7015-8732-eb4d209e1d9a/`（内含 `17.bash.log`、`41.hub.log`、`local/image-*.png` 等）

---

## 2. 目录与命名规则

```
~/.omp/agent/
├── sessions/
│   ├── <project-slug>/
│   │   ├── 2026-09-21T03-09-23-611Z_<session-uuid>.jsonl     # 主 transcript（树）
│   │   ├── 2026-09-21T03-09-23-611Z_<session-uuid>/          # 伴生目录
│   │   │   ├── 17.bash.log  41.hub.log  1001.bash.log ...    # 工具日志（按调用序号）
│   │   │   ├── 27.bash-original.log                          # 原始输出（未截断/未处理版）
│   │   │   ├── local/image-<hash>.png                        # 本地图片/附件
│   │   │   └── <ChildName>.jsonl                             # 子代理 transcript（嵌套）
│   │   └── ...（同项目其它 session）
│   └── ...（其它项目 slug）
├── history.db      # history / session_titles / session_recaps（+ FTS5）
├── agent.db        # threads（44 行索引）/ jobs / model_usage / client_usage / settings
├── config.yml      # modelRoles、compaction.methodOrder（shake/handoff/soft/snapcompact）、thinking 等
└── sessions/...    # 无其它 transcript 存储；history.db 不存正文
```

### 项目 slug 编码（经验规则，勿反解）

实测 43 个顶层项目目录，规则可概括为：**cwd 相对 `$HOME` 的路径，把 `/` 换成 `-`，并保留开头一个 `-`**。

| cwd | slug |
|---|---|
| `~/Downloads` | `-Downloads` |
| `~/Projects/infrastructure` | `-Entropyorder-Infrastructure` |
| `~/Projects/research` | `-Academic-gonggong-guanli-xuebao-fanxiu-2026.8` |
| `~/Projects/example-project` | `-Research_Assistant-【0804】专报绘图` |
| `~`（home 本身） | `-`（目录存在但已空） |
| `/tmp`（macOS 上实为 `/private/tmp`） | `--private-tmp--`（**例外，不可严格反推**） |

**结论**：slug 只用于定位，**权威 cwd 在 transcript 第一/二行的 `session.cwd` 里**；转换器应 `jsonl 内的 session.cwd` 优先，slug 仅兜底。`sessions/<slug>/<session-id>/`、`.../<session-id>/<Child>/` 这类更深目录是**伴生/子代理目录，不是项目 slug**。

### 文件与 id

- 文件名：`<ISO8601 去冒号>` + `_` + `<uuid>`。session uuid 与 Codex 同样呈 UUIDv7 风格（如 `01a0c1f0-911b-...`）。
- `history.db.session_titles.session_id` 与 `agent.db.threads.id` 都指向同一 session uuid。
- `agent.db.threads` 仅 44 行（近期索引，含 `rollout_path`/`cwd`/`source_kind`）；**session 全集以 sessions 目录为准**。

---

## 3. 行级 schema（公共信封 + 17 种 type）

**公共字段**（除 `session`、`title` 两种特殊行外）：
| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | entry 类型 |
| `id` | string | 8 位 hex entry id（`title` 没有；`session` 用 uuid 作 id） |
| `parentId` | string \| null | 父 entry id；根节点为 `null`（首条 `model_change` 的 `parentId=null`）。**还原顺序靠它，不靠行号** |
| `timestamp` | string | ISO-8601 UTC 毫秒，entry 创建时间 |
| 其它 | — | 按 type 扩展，见下 |

**全库 type 统计（1,730 个 jsonl）**：

| type | 数量 | 作用 |
|---|---|---|
| `message` | 206,697 | 真正的对话条目（user / assistant / toolResult / developer / custom） |
| `custom` | 114,261 | 工具执行开始、会话退出、todo HUD 等扩展事件（`customType` 区分） |
| `custom_message` | 3,786 | 注入给模型的"自定义消息"（如后台任务完成通知 `async-result`） |
| `model_usage` | 3,778 | 旁路模型调用用量（judge/batch 等） |
| `model_change` | 1,765 | 模型切换 |
| `title` | 1,730 | 文件第一行：标题元数据（可原位重写，带 `pad`） |
| `session` | 1,730 | 文件第二行：session 头（id/version/cwd/timestamp/title） |
| `session_init` | 1,615 | 系统提示词 + 工具集/代理配置快照（`systemPrompt` 可达 32 KB） |
| `mode_change` | 1,504 | 运行模式切换（如 `goal` 模式携带 goal 对象） |
| `thinking_level_change` | 729 | thinking 档位变更 |
| `title_change` | 182 | 标题变更事件 |
| `compaction` | 32 | 上下文压缩：summary + 保留边界 |
| `service_tier_change` | 9 | 服务等级变更 |
| `ttsr_injection` | 6 | 规则注入（`injectedRules`） |
| `reset_boundary` | 1 | 历史重置边界 |

> 实测：**所有 1,730 个文件的第 1 行都是 `title`、第 2 行都是 `session`**。`title` 行字段 `{type:"title", v:1, title, source:"auto"|"user", updatedAt, pad:"<空格填充>"}`；`pad` 用于让该行宽度固定、可原地改写——所以 `updatedAt` 可能晚于下面所有 entry，**不要按行号判断先后**。

---

## 4. 各类型字段与示例（≤400 字符）

### 4.1 `session`（头）
```json
{"type":"session","version":3,"id":"01a0c1f0-911b-7015-8732-eb4d209e1d9a","timestamp":"2026-09-21T03:09:23.611Z","cwd":"~/Projects/example-project","title":"Review omp session records for project context","titleSource":"auto"}
```
字段：`version`(3)、`id`、`timestamp`、`cwd`、`title`、`titleSource`。**没有 model** —— 模型见 4.3/4.4。

### 4.2 `message`（主数据）
公共结构：`{type:"message", id, parentId, timestamp, message:{...}}`。

| `message.role` | 全库数量 | 关键字段 |
|---|---|---|
| `assistant` | 89,741 | `content[]`（`thinking`/`text`/`toolCall`）、`api`、`provider`、`model`、`usage`、`stopReason`、`timestamp`(epoch ms)、`responseId`、`duration`、`ttft`、`completedAt`、`contextSnapshot` |
| `toolResult` | 112,315 | `toolCallId`、`toolName`、`content[]`（`text`/`image`）、`details`（结构化结果，工具特定，如 `cwd`/`truncated`/`files`）、`isError`、`useless`、`timestamp` |
| `user` | 4,345 | `content[]`（`text`/`image`）、`attribution:"user"`、`timestamp` |
| `developer` | 292 | `content[]`（`text`）；会话中途注入的开发者/系统指令 |
| `custom` | 4 | 自定义角色（少见） |

assistant content block 统计：`toolCall` 112,331 / `thinking` 77,161 / `text` 61,920；toolResult 以 `text` 为主（112,380）+ `image` 1,539。

**assistant 示例**（截断）：
```json
{"type":"message","id":"216f3259","parentId":"188220a6","timestamp":"2026-09-21T03:15:13.787Z","message":{"role":"assistant","content":[{"type":"thinking","thinking":"The user wants me to understand the context...","thinkingSignature":"reasoning_content"},{"type":"toolCall","id":"call_00_GVDqMEuoIY3xKqmvLCsw2890","name":"read","arguments":{"i":"Listing working directory","path":"."},"partialArgs":"{\"i\": \"Listing working directory\", \"path\": \".\"}","streamIndex":0,"intent":"Listing working directory"}],"api":"openai-completions","provider":"deepseek","model":"deepseek-v4-flash","usage":{"input":20938,"output":207,"cacheRead":1408,"cacheWrite":0,"totalTokens":22553,"reasoningTokens":49,"cost":{"input":0.00293,"output":5.8e-05,"cacheRead":3.9e-06,"cacheWrite":0,"total":0.00299}},"stopReason":"toolUse","timestamp":1789960512244,"responseId":"54506..."}}
```

**toolResult 示例**：
```json
{"type":"message","id":"4714c28a","parentId":"216f3259","timestamp":"2026-09-21T03:15:13.798Z","message":{"role":"toolResult","toolCallId":"call_01_TXj4JPkCX6IjtzgYHJSB0940","toolName":"glob","content":[{"type":"text","text":"No files found matching pattern\nSkipped missing paths: .omp/**"}],"details":{"scopePath":".","fileCount":0,"files":[],"truncated":false,"cwd":"~/Projects/example-project","missingPaths":[".omp/**"]},"isError":false,"useless":true,"timestamp":1789960513797}}
```

**user 示例**：
```json
{"type":"message","id":"54f6f147","parentId":"4fcc386f","timestamp":"2026-09-21T03:15:12.248Z","message":{"role":"user","content":[{"type":"text","text":"了解一下这个项目的context。可以去读取本工作目录下的omp的session记录"}],"attribution":"user","timestamp":1789960512196}}
```

### 4.3 `custom`（工具执行开始 / 其它扩展事件）
`customType` 统计：`tool_execution_start` 112,331 / `session_exit` 1,752 / `system-prompt-digest` 126 / `todo_hud_state` 50 / `goal-completed` 2。
```json
{"type":"custom","customType":"tool_execution_start","data":{"toolCallId":"call_00_GVDqMEuoIY3xKqmvLCsw2890","toolName":"read","startedAt":"2026-09-21T03:15:13.785Z","args":{"path":"."},"intent":"Listing working directory"},"id":"f8fdbc11","parentId":"db018c39","timestamp":"2026-09-21T03:15:13.785Z"}
```
`tool_execution_start` 与 assistant `toolCall` 是同一调用的两份记录（`data.toolCallId` = `toolCall.id`），可作为"工具开始时间"来源；若会话中断可能只有 start 没有 toolResult。

### 4.4 会话级配置/元数据
- `model_change`：`{"type":"model_change","id":"9138fb28","parentId":null,"timestamp":"...","model":"deepseek/deepseek-v4-flash","resolvedModelIsFallback":false}`（首条通常为根节点）。
- `thinking_level_change`：`{"thinkingLevel":"max","configured":null}`。
- `mode_change`：`{"mode":"goal","data":{"goal":{...}},"runtime":{...}}`。
- `session_init`：`{systemPrompt(约 32 KB), task, tools, agent, resolvedModel, readOnly, spawns, outputSchema, outputSchemaMode}` —— **系统提示词与子代理配置的唯一持久化处**。
- `model_usage`：旁路模型调用，`{"purpose":"judge_batch","role":"judge","provider","model","usage":{...,"cost":{...}},"stopReason"}`。
- `custom_message`：`{"customType":"async-result","content":"<system-notice>Background job bg_1 has completed...","display":true,"details":{"jobs":[{jobId,type,label,durationMs}]},"attribution":"agent"}` —— 后台任务完成等注入消息。
- `title_change` / `title` / `reset_boundary` / `service_tier_change` / `ttsr_injection`：见 §3 统计表。

### 4.5 `compaction`（上下文压缩）
```json
{"type":"compaction","id":"a4bd42f4","parentId":"2b6b99a2","timestamp":"2026-10-02T06:42:58.261Z","summary":"Resume prior conversation. Earlier turns archived under HISTORY below, oldest→newest...","shortSummary":"Archived 90,025 chars of history onto 5 snapcompact frames (+27,833 chars as text)","firstKeptEntryId":"e2baa030","tokensBefore":850571,"tokensAfter":40536,"method":"snapcompact","details":{"readFiles":[...],"snapcompact":{...}},"fromExtension":false,"preserveData":{...}}
```
- `summary` = 给模型的交接摘要（handoff 文本），`shortSummary` 简短描述；
- `firstKeptEntryId` = 压缩后仍原样保留的**第一条 entry**，之前的被归档进 summary；
- `method` 来自 `config.yml.compaction.methodOrder`（`snapcompact`/`shake`/`handoff`/`soft`）；
- 压缩**不删文件**：tokensBefore 850,571 → tokensAfter 40,536 只影响模型上下文。

---

## 5. 工具调用链与工具日志

同一个工具调用在 3 处出现：

```
assistant.message.content[i].toolCall {id, name, arguments, partialArgs, intent}
        │  (toolCall.id)
        ├── custom(customType="tool_execution_start").data {toolCallId, toolName, startedAt, args, intent}
        └── message(role="toolResult") {toolCallId, toolName, content, details, isError, useless}
                        │  (按调用序号)
                        └── 伴生目录 <序号>.<tool>.log（原始 stdout/stderr / 结构化输出）
```

- 工具名分布（本机）：`bash` 55,769 / `read` 21,221 / `eval` 8,429 / `edit` 6,669 / `grep` 4,865 / `write` 4,839 / `hub` 2,453 / `web_search` 1,995 / `yield` 1,695 / `wait` 1,433 / `glob` 1,388 / `todo` 711 / `browser` 448 / `task` 311 / `ask` 58。
- `arguments` 是**已解析的 JSON 对象**；`partialArgs` 是流式增量原始字符串（转换时用 `arguments`）。
- toolResult.content 通常含 `text`（可含 `image`）；`details` 是工具定制结构（如 `read` 的 `cwd/fileCount/truncated`、`bash` 的退出码等），**比 content 更结构化**，建议优先取 `details` 再回退 `content`。
- `details.useless=true` 表示该结果被判定为无信息量（可保留但标记）。
- 工具日志：文件名 `<调用序号>.<tool>.log`，`.bash-original.log` 为未处理原始输出；`local/` 放图片附件。工具日志**不在 transcript 内**，需要时按序号与工具名关联（`custom.tool_execution_start.startedAt` 可辅助对齐）。
- 伴生目录中的 `<ChildName>.jsonl`（如 `DomCleanC.jsonl`、`Git5_C2/Git5_C2.ServerStore.jsonl`）= **子代理独立 transcript**（`task` 工具 spawn），其路径编码了父 session 目录；子代理有自己的 `session`/`title` 头。

---

## 6. Turn 边界、时间戳与分支

**Turn 边界没有显式事件**，按语义切：
- 一条 `message(role=user)` 开始一个新 turn；
- 之后 `assistant(stopReason="toolUse")` → `toolResult` → 再 `assistant` … 循环；
- `assistant(stopReason="stop")` = 最终答复，turn 结束；`error` / `aborted` / `length` 也是终止态。
- 全库 stopReason：`toolUse` 86,685 / `stop` 2,246 / `error` 462 / `aborted` 346 / `length` 2。
- 注：`developer` 消息可能插在 turn 中间，不算用户 turn。

**时间戳 3 套**：entry 外层 `timestamp`（ISO-8601 毫秒）；`message.timestamp`（epoch 毫秒）与 `completedAt`；`custom.data.startedAt`（ISO）。排序/切 turn 建议：**先按 `parentId` 树定位，再在兄弟/单链上用 `timestamp` 排序**。

**分支**：`parentId` 构成树；用户在历史处重试/编辑会产生分叉。当前活跃路径 = 从"最新叶子节点"沿 `parentId` 回溯到根。判断最新叶子：所有节点中**没有任何子节点**且 `timestamp` 最大者（若用户回退过，可能有多个叶子，取最新者即当前路径；被弃分支仍留在文件里）。

---

## 7. 如何还原一个 session 的完整对话序列

### 步骤
1. **定位文件**：`sessions/<slug>/<ISO>_<uuid>.jsonl`；`agent.db.threads.rollout_path` 可作辅助索引（44 条），或 `history.db.session_titles` 查标题 → session_id → 文件名。
2. **读全部行** → `json.loads`；跳过 `title`（行 1）与 `session`（行 2）里的元数据，记录 `session.cwd/timestamp/title`。
3. **建树**：`by_id = {e["id"]: e}`；`children[parentId].append(id)`。注意 `model_change`/`session_init` 等也可能参与 `parentId` 链。
4. **选当前叶子**：`leafs = [e for e in entries if e["id"] not in children]`，取 `timestamp` 最大者；沿 `parentId` 回溯 → 反转得到 `path`。
5. **转换 path 上的 entry**：
   - `message(role=user/developer)` → 用户消息 / 系统注入；
   - `message(role=assistant)`：`content` 里 `thinking`→推理、`text`→助手文本、`toolCall`→工具调用事件；
   - `message(role=toolResult)` → 工具结果（按 `toolCallId` 与调用配对）；
   - `custom(tool_execution_start)` → 可选，补工具开始时间；
   - `custom_message` → 系统/异步通知（默认折叠或作为 system 消息）；
   - `compaction` → 压缩事件（保留 summary + `firstKeptEntryId`）；
   - 其余 `model_change`/`mode_change`/`title_change`/… → session 元数据变更事件。
6. **子代理**：伴生目录里的 `<ChildName>.jsonl` 递归同样处理，按目录关系挂到父 session 下。
7. **token/cost**：用每条 assistant 的 `message.usage` 汇总；`model_usage` 另计（旁路调用，不要混入主对话成本）。

### Python 还原伪代码
```python
import json, os
def load_session(path):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    header = next(r for r in rows if r["type"] == "session")
    ents = [r for r in rows if r["type"] not in ("session", "title")]
    by_id = {e["id"]: e for e in ents if "id" in e}
    child = {e["id"]: e.get("parentId") for e in ents if "id" in e}
    has_child = {p for p in child.values() if p}
    leafs = [e for e in ents if "id" in e and e["id"] not in has_child]
    leaf = max(leafs, key=lambda e: e.get("timestamp", ""))
    path, cur = [], leaf
    while cur:
        path.append(cur)
        cur = by_id.get(cur.get("parentId"))
    path.reverse()
    convo = []
    for e in path:
        t = e["type"]
        if t == "message":
            m = e["message"]; role = m["role"]
            if role in ("user", "developer"):
                convo.append({"role": "user" if role == "user" else "system",
                              "blocks": m.get("content", [])})
            elif role == "assistant":
                for b in m.get("content", []):
                    if b["type"] == "text":
                        convo.append({"role": "assistant", "type": "text", "text": b["text"]})
                    elif b["type"] == "thinking":
                        convo.append({"role": "assistant", "type": "reasoning", "text": b["thinking"]})
                    elif b["type"] == "toolCall":
                        convo.append({"role": "assistant", "type": "tool_call",
                                      "call_id": b["id"], "name": b["name"], "args": b.get("arguments")})
            elif role == "toolResult":
                convo.append({"role": "tool", "call_id": m["toolCallId"], "name": m["toolName"],
                              "is_error": m.get("isError"), "content": m.get("content"),
                              "details": m.get("details")})
        elif t == "compaction":
            convo.append({"type": "compaction", "summary": e.get("summary"),
                          "first_kept_entry": e.get("firstKeptEntryId"),
                          "tokens_before": e.get("tokensBefore"), "tokens_after": e.get("tokensAfter")})
        elif t == "custom" and e.get("customType") == "tool_execution_start":
            convo.append({"type": "tool_start", "call_id": e["data"].get("toolCallId"),
                          "name": e["data"].get("toolName"), "ts": e["data"].get("startedAt")})
    return header, convo
```

### SQLite 辅助
```sql
-- history.db：标题 / 输入历史 / recap（都只有元数据，没有正文）
select session_id, title, updated_at from session_titles order by updated_at desc limit 20;
select session_id, cwd, recap from session_recaps order by created_at desc limit 20;
-- agent.db：近期 thread 索引
select id, rollout_path, cwd, source_kind from threads order by updated_at desc limit 20;
```

---

## 8. 映射到通用中间表示（IR）建议

| 通用 IR | OMP 来源 | 规则 |
|---|---|---|
| `session.id` | `session.id` | = 文件名 uuid |
| `session.cwd` | `session.cwd` | 权威；不要反解 slug |
| `session.title` | `title.title` / `title_change.title` / `history.db.session_titles` | 取最新 |
| `session.created_at` | `session.timestamp` | ISO |
| `event.seq` | 树遍历顺序（path 下标） | 用 `id`/`parentId` 保稳定 |
| `event.ts` | entry `timestamp` | ISO |
| `user_message` | `message(role=user)` content `text`/`image` | 过滤 `developer` 到 system |
| `assistant_message` | `message(role=assistant)` content `text` | 同条消息可含多个 block，按 block 拆事件 |
| `reasoning` | `message(role=assistant).content[type=thinking].thinking` | 明文可用（与 Codex 不同，OMP thinking 是明文） |
| `tool_call` | content `toolCall{id,name,arguments}`（+ custom `tool_execution_start`） | 用 `arguments` 对象，忽略 `partialArgs` |
| `tool_result` | `message(role=toolResult){toolCallId,toolName,content,details,isError}` | 优先 `details`，保留 `isError`/`useless` |
| `model/provider/thinking` | `model_change` / `thinking_level_change` / `message.model/provider` | 按事件时序更新 |
| `usage` | `message.usage{input,output,cacheRead,cacheWrite,reasoningTokens,cost.*}` | 逐条汇总；`model_usage` 旁路单列 |
| `turn` | 用户消息 → … → `stopReason != toolUse` | 无显式 turn id，可在 IR 层生成 |
| `compaction` | `compaction{summary,shortSummary,firstKeptEntryId,tokensBefore,tokensAfter,method}` | 保留为上下文窗口事件 |
| `branch` | `parentId` 树 | 只输出当前路径；可选输出被弃分支 |
| `subagent` | 伴生目录 `<ChildName>.jsonl` | 递归，路径关系挂父 |
| `system_prompt` | `session_init.systemPrompt` | 大文本，单独存 |

---

## 9. 坑清单

1. **行序 ≠ 时间序**：第 1 行恒为 `title`（可被原地重写，`updatedAt` 可能最新），第 2 行恒为 `session`；从第 3 行起才是追加的事件。**必须用 `parentId` 树还原**。
2. **`title` 行的 `pad` 是固定宽度填充**，用于原位置改写；不要把它当内容。
3. **不要反解 project slug**：`-Research_Assistant-...` 看似规则清晰，但 `/tmp` → `--private-tmp--` 因符号链接（`/private/tmp`）不可逆；一律读 `session.cwd`。
4. **session 文件没有 model 字段**：模型要从 `model_change` / 每条 assistant 的 `message.model` 取；首条 `model_change` 通常是根（`parentId=null`），其后有切换事件。
5. **thinking 是明文**（`content[type=thinking].thinking`），但另有 `thinkingSignature`（`reasoning_content`）；不要输出签名。
6. **toolCall 有两个参数副本**：`arguments`（对象，规范）与 `partialArgs`（流式字符串，残缺）；只用前者。
7. **工具日志与 transcript 分离**：`<序号>.<tool>.log` 按调用顺序编号，`bash-original.log` 是原始版；转工具结果时优先 transcript 内的 `details`/`content`，日志仅在需要完整输出时补。
8. **子代理嵌套**：伴生目录内的 `.jsonl`（含多层子目录如 `Git5_C2/...`）是子代理 transcript，不是主会话的一部分；不处理会漏掉 fork 结构，错误处理会重复拼接。
9. **compaction 不删数据**：`firstKeptEntryId` 之前的 entry 仍在文件里；重建"模型当时看到的历史"= summary + `firstKeptEntryId` 之后的 entry；重建"完整历史"= 全部 entry + 压缩标记。
10. **当前分支判定无显式指针**：只能取"无子节点且 timestamp 最大"的叶子回溯；用户回退/重试会产生多叶子，被弃分支仍在文件中。
11. **`model_usage` 是旁路调用**（judge/batch，`purpose`/`role` 字段），不要混进主对话 token/cost。
12. **`custom_message` 的 `content` 是字符串**（非 content block 数组），如 `<system-notice>Background job ...</system-notice>`；`attribution:"agent"`，应作为 system/异步通知处理，不要当作用户消息。
13. **`history.db` / `agent.db` 不含正文**：history 只是 prompt 去重历史（`prompt` 唯一 + `use_count`），session_titles 是 LLM 自动标题，recaps 是摘要；**正文只在 sessions/*.jsonl**。
14. **每个 session 可能有多份同名伴生文件与空 lock 文件**（`.jsonl.lock.os`/`.owner.lock`），跳过隐藏文件。

---

## 10. 复现命令

```bash
# 全库类型统计
python3 - <<'PY'
import glob, json, collections
c = collections.Counter()
for f in glob.glob('~/.omp/agent/sessions/**/*.jsonl', recursive=True):
    for line in open(f, errors='replace'):
        try: c[json.loads(line).get('type')] += 1
        except: pass
print(c)
PY

# 一个 session 的 cwd / title
head -2 "sessions/-Downloads/<ts>_<uuid>.jsonl"

# 标题索引
sqlite3 "file:$HOME/.omp/agent/history.db?mode=ro" \
  "select session_id, title from session_titles order by updated_at desc limit 10;"
```

样本（均 ≤50 KB，已在 `samples/omp/`）：
- `session-small-full.jsonl` —— 完整小 session（42 KB / 42 行：title+session+配置行，23 条 message（1 user/10 assistant/12 toolResult）+ 14 条 custom，未截断）。
- `session-long-head-excerpt.jsonl` —— 长 session 前 30 行（每行截断至 1500 字符）。
- `session-compaction-excerpt.jsonl` —— 含 `compaction` 的窗口（头部 + 压缩前后各若干行，每行截断至 1500 字符）。
- `special-entries-excerpt.jsonl` —— `session_init`/`model_usage`/`mode_change`/`custom_message`/`model_change` 等特殊类型各 1–2 条（截断至 800 字符）。
- `tool-logs/17.bash.log`（完整 4 KB）、`tool-logs/41.hub.log.excerpt`、`tool-logs/1001.bash.log.excerpt`（各截断至 20 KB）。
- `sqlite-schemas.sql` —— history.db + agent.db 的 `.schema` 全量。
- `history-excerpt.json` / `session_titles-excerpt.json` / `agent_threads-excerpt.json` —— 各表前 10/10/5 行。
