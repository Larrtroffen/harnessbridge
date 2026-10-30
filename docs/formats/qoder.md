# Qoder 会话格式逆向规格（供 DSH 导入转换器实现）

- 被测对象：本机 Qoder（阿里 Qoder IDE / `qoder` CLI），版本 **`1.1.75-hotfix.1`**、`entrypoint=cli`、`userType=external`
- 数据根：`~/.qoder/`
- 扫描快照：2026-10-30 02:05（Qoder 进程仍在运行并追加写，个别计数会小幅漂移；结构结论稳定）
- 方法：**只读**读取 `~/.qoder`，样本复制到 `samples/qoder/` 后再解析；未修改/删除任何用户数据
- 结论：Qoder 的 transcript 是 **Claude Code transcript 的同源衍生格式**，但有三处硬差异必须特殊处理：**assistant 按 content block 拆行写入、每行恰好 1 个 block（共享 `message.id`）**；**tool_result 不在 `parentUuid` 线性链上（是兄弟分支，必须用 `tool_use_id`/`sourceToolAssistantUUID` 配对）**；**混入 5 类 Qoder 自有状态记录**（`active-leaf`/`runtime-config`/`workspace-directories`/`last-prompt`/`attachment`）。

---

## 1. 文件定位与目录布局

### 1.1 主 transcript（唯一权威对话数据）

```
~/.qoder/projects/<project-slug>/<session-uuid>.jsonl
~/.qoder/projects/<project-slug>/<session-uuid>/
├── state.json               # 会话状态快照（revision + 加密 items）
├── compression-v2/state.json# 上下文压缩去重状态
└── subagents/               # 子代理（sidechain）轨迹
    ├── agent-<agentType>-<16hex>.jsonl     # 子代理 transcript，同源 JSONL 格式
    ├── agent-<agentType>-<16hex>.meta.json # 子代理元信息
    └── task-<19hex>.json                   # 子代理任务运行记录（含 result 全文）
```

- `<session-uuid>`：会话 id，即文件名去掉 `.jsonl`；与行内 `sessionId` 完全一致。本机 44 个主 transcript、37 个 project-slug 目录、合计 368 MB。
- 一个 project-slug 目录下可有多会话：本机 `-Users-larr-Entropyorder-projects-tb4-pipeline` 有 6 个、`...-projects--1025------` 有 3 个。
- 实测一对一会话目录（`<sid>/`）总是存在；唯一例外是 `projects/-/goals/<sid>.json`（无 cwd 的 goal 状态，不属于会话目录）。
- **无** 会话级 title / summary 索引文件；标题只能从正文推导（见 §10.1）。

### 1.2 project-slug 编码规则（已验证 44/44 匹配）

```
project-slug = re.sub(r'[^A-Za-z0-9]', '-', cwd)
```
即：把 cwd 中**所有非 ASCII 字母数字字符**（`/`、`_`、`.`、中文、全角括号、空格等）逐个替换成 `-`，保留开头的 `-`。

| cwd | project-slug |
|---|---|
| `~/Documents/Qoder/2026-10-24/1433b77a` | `-Users-larr-Documents-Qoder-2026-10-24-1433b77a` |
| `~/Research_Assistant/projects/【1025】知识库来源` | `-Users-larr-Research-Assistant-projects--1025------` |
| `~/Library/Application Support/com.qoder.app.stable/remote-control/sessions/5fde…/4611…` | `-Users-larr-Library-Application-Support-com-qoder-app-stable-remote-control-sessions-…` |

> **编码不可逆**：中文、下划线、括号都变成 `-`，无法从 slug 反推 cwd。cwd 只能从 transcript 记录里的 `cwd` 字段取（每条 user/assistant/attachment/system 都有）。
> 校验方法：`find ~/.qoder/projects -maxdepth 2 -name '*.jsonl' -not -path '*/subagents/*'` 得到文件，从其首条带 `cwd` 的记录反算 slug 对比。

### 1.3 cwd 的两种来源（重要业务特征）

1. **普通项目目录**：用户在 Qoder 里打开的真实项目，如 `~/Entropyorder/projects/tb4-pipeline`。
2. **Qoder 自动创建的"每会话工作目录"**：`~/Documents/Qoder/<date>/<session-uuid 前 8 位>/`（本机 26 个）。这类 cwd 往往是空临时目录，导入后不要当作有意义的项目根；真实项目路径通常出现在首条 prompt 里。
3. 远程控制（Qoder 桌面 App 的 remote-control）会话的 cwd 是 `~/Library/Application Support/com.qoder.app.stable/remote-control/sessions/<hash>/<hash>`（只有空目录，**transcript 仍在 `~/.qoder/projects`**）。

### 1.4 新版是否会换位置？（已排查，本机没有）

- `~/Library/Application Support/com.qoder.app.stable/` 下只有 App 缓存/日志，唯一的 `*.jsonl` 是 crash metrics 和 knowledge 插件日志，**不是会话**。
- `~/Library/Application Support/Qoder/qodercli/cache/` 只有 `id` 缓存，无 transcript。
- `~/.qoder/sites/sessions/*.json` 是 Qoder **Sites 功能**的会话元数据（`location.sessionId/projectRoot`），不是 chat transcript。
- 结论：本机会话 transcript **仍集中**在 `~/.qoder/projects/`。若未来版本迁移，用 §12 的第 4 条命令重新定位；Qoder 的 `state.json`/`last-prompt` 等状态文件会跟随 transcript 一起迁移。

### 1.5 辅助数据目录（可选用，非对话正文）

| 路径 | 内容 | 对导入的用处 |
|---|---|---|
| `~/.qoder/tasks/<sid>/<N>.json` + `.highwatermark` | TaskCreate/TaskUpdate 任务板持久化（`subject/description/activeForm/status/blocks/blockedBy` + `businessInfo`） | 可还原为 DSH todo |
| `~/.qoder/file-history/<sid>/<uuid>@vN` | Write/Edit 的文件版本备份（被 `file-history-snapshot` 引用） | 可还原每次写文件前的旧内容 |
| `~/.qoder/memory/*.md` + `MEMORY.md` | 全局跨会话记忆 | 可导入为记忆库 |
| `~/.qoder/projects/<slug>/memory/*.md` | 项目级记忆 | 同上 |
| `~/.qoder/projects/-/goals/<sid>.json` | goal 模式状态（objective/status/turnsUsed/createdAt，epoch ms） | 可映射为 goal |
| `~/.qoder/shell-snapshots/*.sh` | Bash 工具用的 shell 环境快照 | 忽略 |
| `~/.qoder/tmp/chat-attachment-staging/*.png` | 用户粘贴图片的暂存 | 图片附件的本地原件 |
| `~/.qoder/settings.json` | `model`/`providers`/`mcpServers`/`enabledPlugins` | 模型 key 可能在此有 display 映射 |

---

## 2. 写入模型与时序

1. **append-only JSONL**：一行一条 record，按发生顺序追加；会话恢复后继续追加到同一文件，不重写。本机最大 30.6 MB / 16466 行。
2. **assistant 拆行**：一次模型响应 = 若干 assistant 行，**每行 `content` 恰好 1 个 block**，共享同一个 `message.id`，`parentUuid` 串成链（thinking → text → tool_use…）。`stop_reason`/`usage` 只可靠地出现在该消息的**最后一个** block 行（前面的行 `stop_reason: null`）。
   - 实测：24382 条 assistant 行 → 10096 个逻辑消息；`content` 数组长度 100% 为 1。
3. **一轮交互的行序**（典型）：
   ```
   [workspace-directories] [runtime-config] user(prompt) [attachment ×N] active-leaf
   assistant(thinking) assistant(text) assistant(tool_use) … active-leaf
   user(tool_result) active-leaf  user(tool_result) active-leaf …
   [file-history-snapshot] …
   ```
   - `active-leaf` 在"当前分支末端提交"后追加（一次 assistant 消息的最后一块之后、每条 tool_result 之后）；
   - `runtime-config`/`workspace-directories`/`last-prompt` 在每轮开始时重写一次最新状态（同文件内可重复出现）。
4. **并发/截断风险**：Qoder 运行时会持续写文件，读取方可能读到**不完整的尾行**。本机快照 69402 行全部可解析，但转换器必须逐行 `try/except` 跳过坏行，或先 `stat` 取 size 后只读到该 offset。

---

## 3. 记录类型总表（9 类，本机 44 会话 / 69402 行实测）

| type | 行数 | 角色 | 是否进对话 |
|---|---:|---|---|
| `user` | 13186 | 用户 prompt / tool_result / 系统注入文本 / 图片 | **部分**（见 §4.1） |
| `assistant` | 24382 | 模型响应，每行 1 个 content block | **是**（需按 `message.id` 合并） |
| `attachment` | 2849 | 上下文注入（技能清单、hook 输出、任务提醒、排队输入…） | 否（`queued_command` 例外） |
| `active-leaf` | 26207 | 当前分支指针（树形对话的"已提交 leaf"日志） | 否（仅用于分支判定） |
| `file-history-snapshot` | 1250 | 文件快照备份登记 | 否 |
| `runtime-config` | 583 | 每轮模型/推理强度/上下文窗口 | 否（可作模型时间线） |
| `workspace-directories` | 491 | 工作区根目录列表（支持多根） | 否（多根时可取） |
| `last-prompt` | 447 | 会话"最后一条用户输入"（会话列表用） | 否（标题兜底） |
| `system` | 7 | 压缩边界；子代理文件里另有 `api_retry` | 否（压缩分割事件） |

> **没有** Claude Code 的 `summary` 行、也没有 `queue-operation`；压缩摘要以 `user` 行 + `isCompactSummary` 表示。

---

## 4. 字段表

### 4.1 公共字段（`user`/`assistant`/`attachment`/`system` 共有）

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 记录类型 |
| `uuid` | string | 本记录唯一 id（树节点 id） |
| `timestamp` | **ISO 字符串** | UTC 毫秒，如 `"2026-10-24T15:32:16.648Z"`（4 类消息记录均为 ISO；`active-leaf`/`runtime-config` 为 **epoch ms 整数**，见 §8） |
| `parentUuid` | string \| null | 树父节点；会话首条为 `null`；压缩后 system 记录为 `null` 且另有 `logicalParentUuid` |
| `isSidechain` | bool | 主 transcript **全部 false**；`subagents/*.jsonl` **全部 true** |
| `cwd` | string | 该记录发生时的 cwd |
| `sessionId` | string | 会话 uuid |
| `userType` | string | 本机全为 `external` |
| `entrypoint` | string | 本机全为 `cli` |
| `version` | string | Qoder 版本 `1.1.75-hotfix.1` |
| `gitBranch` | string | 本机值：`HEAD` 39820 / `main` 498 / `feat/extension` 133。无 git repo 时可能缺省 |

### 4.2 `user` 行的 4 种形态

| 形态 | 判定 | 关键字段 | 数量级（本机） |
|---|---|---|---|
| ① 人类输入 | `humanInput != null` 且 `origin.kind == "human"`；`message.content=[{type:"text"}]` | `promptId`、`requestSetId`、`permissionMode`、`humanInput:{text,mode:"prompt"}` | 434 |
| ② 工具结果 | `message.content[0].type=="tool_result"` | `sourceToolAssistantUUID`、`toolUseResult`、`promptId`、`is_error`（在块内） | 12659 |
| ③ 系统注入文本 | 有 `isMeta` 或 `isCompactSummary`，或 `origin.kind=="task-notification"`，或正文是 `[Request interrupted by user]` | `isMeta`、`isCompactSummary`、`isVisibleInTranscriptOnly`、`origin` | 42 + 7 + 5 + 17 |
| ④ 图片附件 | `message.content[0].type=="image"`（`source.type=="url"` 指向 Qoder OSS 预签名 URL） | `source.url`（带 `Expires`，会过期） | 6 |

补充：`message.content` 为**纯字符串**的 user 行有 22 条（goal 续跑/系统通知类注入），无 `message.content[].type`。

### 4.3 `assistant` 行

| 字段 | 说明 |
|---|---|
| `message.id` | 逻辑消息 id（**合并键**）；同一次响应所有 block 行共享 |
| `message.model` | 模型：内部 key `eb7e9f84-3471-4014-bf41-f8092a8f56c7`（默认中转模型）/ custom provider 串 `magpie/deepseek/deepseek-flash` / `<synthetic>`（错误占位） |
| `message.stop_reason` | `null`（非最后块）/ `tool_use` / `end_turn` / `stop_sequence` / `max_tokens` |
| `message.usage` | **仅 custom provider 会话有**（9/44 文件，共 1121 行，且只出现在消息最后一块）：`input_tokens/cache_*/output_tokens/request_id/context_usage_ratio/...` |
| `message.content[0]` | 三种 block：`{type:"thinking",thinking,signature}`、`{type:"text",text,citations}`、`{type:"tool_use",id,name,input}` |
| 附加 | `requestTokenAnchor:{request,response,requestId}`（请求/响应 hash，可丢弃）；custom 模型行另有 `modelSource:"custom"` + `customProviderId:"magpie"` |
| 错误行 | `isApiErrorMessage:true` + `message.model="<synthetic>"` + `error`/`errorDetails`/`displayErrorCode`/`errorFallbackMessage`（本机 18 条，如 `billing_error` 402） |

### 4.4 `attachment` 行（`attachment.type` 全清单，本机）

| 子类型 | 条数 | 含义 |
|---|---:|---|
| `task_reminder` | 1310 | 任务板提醒（`content`/`itemCount`） |
| `goal_state` | 730 | goal 模式状态注入（objective/turnsUsed/maxTurns/timeUsedSeconds/currentTime） |
| `queued_command` | 352 | 用户在生成中排队的输入（`prompt` 数组、`source_uuid`、`commandMode`、`origin`）——**可选转为 user 消息** |
| `edited_text_file` | 173 | 外部编辑器改了被跟踪文件（filename/snippet/content/mtime） |
| `skill_listing` | 69 | 技能清单注入（content/names/skillCount/isInitial） |
| `mcp_lazy_tools_delta` | 61 | MCP 工具增量注入 |
| `agent_listing_delta` | 51 | 子代理类型清单增量 |
| `hook_output` | 50 | SessionStart 等 hook 输出 |
| `hook_error_during_execution` | 32 | hook 执行错误 |
| `date_change` | 10 | 日期跨天提醒 |
| `post_compact_restored_files` | 7 | 压缩后恢复的文件清单（files） |
| `hook_non_blocking_error` | 7 | hook 非阻塞错误 |

### 4.5 `active-leaf`

```json
{"type":"active-leaf","sessionId":"1433b77a-…","leafUuid":"a7342e7e-…",
 "explicit":false,"timestamp":1792855936648,"rewound":true,"compactBoundaryUuid":"…"}
```
- `leafUuid`：提交后当前分支末端节点 uuid；`explicit:true` + `rewound:true` 表示用户**显式 rewind**（本机 8 条，全部 explicit）。
- 无 `rewound` 的 99.9% 是正常提交。转换时取**文件中最后一条** `active-leaf.leafUuid` 作为最终分支末端。

### 4.6 `file-history-snapshot`

```json
{"type":"file-history-snapshot","messageId":"<user 行 uuid>","isSnapshotUpdate":false,
 "snapshot":{"messageId":"…","timestamp":"…","cwd":"…",
   "trackedFileBackups":{"~/.qoder/memory/MEMORY.md":
     {"backupFileName":null,"version":1,"backupTime":"2026-10-24T15:43:25.170Z"}}}}
```
备份实体在 `~/.qoder/file-history/<sid>/<file-uuid>@v<version>`。

### 4.7 `runtime-config` / `workspace-directories` / `last-prompt` / `system`

```json
{"type":"runtime-config","sessionId":"…","model":"eb7e9f84-3471-4014-bf41-f8092a8f56c7",
 "reasoningEffort":null,"contextWindow":null,"generation":null,"timestamp":1792855936550}
{"type":"workspace-directories","sessionId":"…","directories":["~/Documents/Qoder/2026-10-24/1433b77a"]}
{"type":"last-prompt","sessionId":"…","lastPrompt":"来盘点一下我的文件夹、文件结构……"}
{"type":"system","uuid":"…","timestamp":"2026-10-25T12:48:14.409Z","subtype":"compact_boundary",
 "content":"Conversation compacted","level":"info","isCompactSummary":true,
 "compactMetadata":{"trigger":"auto","preTokens":105966,"messagesSummarized":118,
 "postTokens":3176,"durationMs":33525},"parentUuid":null,"logicalParentUuid":"93ce9218-…",
 "isSidechain":false,"cwd":"…","sessionId":"…","version":"1.1.75-hotfix.1",
 "requiresActiveLeafCommit":true}
```

### 4.8 子代理 transcript 的额外字段（`subagents/*.jsonl`）

- 全是 `isSidechain:true`，行内额外：`agentId`（如 `aExplore-29943601436ebef1`）、`parent_tool_use_id`（父 Agent 调用的 tool_use id）、`session_id`（assistant 行）、`businessModelKey`（仅首条 user 行）。
- 记录类型只有 `user` / `assistant` / `last-prompt` / `system`（无 active-leaf/attachment/runtime-config…）。
- `system` 子类型除 `compact_boundary` 外有 **`api_retry`**：`attempt/max_retries/retry_delay_ms/error_status/error`（本机子代理文件共 590 条 system）。
- 本机 351 个子代理 transcript：`general-purpose` 317、`Explore` 32、`Plan` 2；单会话最多 165 个（`43c29110`）。

---

## 5. 各类记录截断示例（均 ≤400 字符，来自真实样本）

**(a) 人类 user prompt**（`samples/qoder/01-*`）
```json
{"type":"user","uuid":"d2fcd5eb-…","timestamp":"2026-10-24T15:32:16.648Z","message":{"role":"user","content":[{"type":"text","text":"来盘点一下我的文件夹、文件结构……"}]},"permissionMode":"yolo","origin":{"kind":"human"},"promptId":"f4fa1cba-…","humanInput":{"text":"来盘点一下…","mode":"prompt"},"requestSetId":"d2fcd5eb-…","parentUuid":null,"isSidechain":false,"cwd":"~/Documents/Qoder/2026-10-24/1433b77a","sessionId":"1433b77a-…","userType":"external","entrypoint":"cli","version":"1.1.75-hotfix.1","gitBranch":"HEAD"}
```

**(b) assistant thinking block**（一行一块）
```json
{"type":"assistant","uuid":"f456f874-…","timestamp":"2026-10-24T15:32:19.206Z","message":{"id":"dd25ace8-…","type":"message","role":"assistant","model":"eb7e9f84-3471-4014-bf41-f8092a8f56c7","stop_reason":null,"stop_sequence":null,"content":[{"type":"thinking","thinking":"The user wants me to first survey their folder structure…","signature":""}]},"requestTokenAnchor":{"request":"d6ae50…","response":"8594d5…","requestId":"821b172a-…"},"parentUuid":"a7342e7e-…","isSidechain":false,"cwd":"~/Documents/Qoder/2026-10-24/1433b77a","sessionId":"1433b77a-…","version":"1.1.75-hotfix.1","gitBranch":"HEAD"}
```

**(c) assistant tool_use block**（同一 `message.id` 的后续行）
```json
{"type":"assistant","uuid":"8c8579ad-…","message":{"id":"dd25ace8-…","content":[{"type":"tool_use","id":"call_00_vLPSoGkodGm2X8UpflZ59516","name":"Bash","input":{"command":"cd ~/Documents/Qoder/2026-10-24/1433b77a && pwd && ls -la","description":"List current working directory"}}],"stop_reason":null},"parentUuid":"208f0346-…","cwd":"…","sessionId":"…"}
```

**(d) assistant text block（带 citations 字段）**
```json
{"type":"assistant","message":{"id":"…","content":[{"type":"text","text":"我先快速看一下整体目录骨架，再分派子代理去深挖每个大目录。","citations":null}],"stop_reason":null},"parentUuid":"f456f874-…"}
```

**(e) user tool_result 行（`toolUseResult` 结构化结果 + `sourceToolAssistantUUID` 指向 tool_use 所在行）**
```json
{"type":"user","uuid":"a35008e8-…","timestamp":"2026-10-24T15:32:29.629Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"call_00_vLPSoGkodGm2X8UpflZ59516","content":"~/Documents/Qoder/2026-10-24/1433b77a\ntotal 0\n…","is_error":false}]},"sourceToolAssistantUUID":"8c8579ad-…","promptId":"f4fa1cba-…","toolUseResult":{"kind":"completed","telemetryExecutionId":"2eb7e70a-…","stdout":"…","stderr":"","exitCode":0,"signal":null,"interrupted":false,"isImage":false,"noOutputExpected":false,"processStarted":true},"parentUuid":"8c8579ad-…"}
```

**(f) 压缩边界 system + 压缩摘要 user**（`samples/qoder/03-*`，连续两行）
```json
{"type":"system","subtype":"compact_boundary","content":"Conversation compacted","level":"info","isCompactSummary":true,"compactMetadata":{"trigger":"auto","preTokens":931093,"messagesSummarized":3461,"postTokens":4301,"durationMs":44033},"parentUuid":null,"logicalParentUuid":"85421cb4-…","requiresActiveLeafCommit":true,"timestamp":"2026-10-25T21:19:50.330Z"}
{"type":"user","uuid":"0174521e-…","timestamp":"2026-10-25T21:19:50.330Z","message":{"role":"user","content":[{"type":"text","text":"This session is being continued from a previous conversation that ran out of context.\n\nThe summary below covers the earlier portion…"}]},"isVisibleInTranscriptOnly":true,"isCompactSummary":true,"parentUuid":"ba7f5be9-…"}
```

**(g) 系统注入 user（不是人类输入）**
```json
{"type":"user","uuid":"94d32cda-…","message":{"role":"user","content":[{"type":"text","text":"[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event, NOT a message from the user…"}]},"isMeta":true,"origin":{"kind":"task-notification"}}
```
（同形态还有：goal 续跑的 `"Continue working toward the active thread goal."`、`"A goal has been set."`、`"[Request interrupted by user]"`）

**(h) attachment: task_reminder / edited_text_file / queued_command**
```json
{"type":"attachment","attachment":{"type":"task_reminder","content":"…","itemCount":3},"uuid":"…","timestamp":"…","parentUuid":"…","isSidechain":false,"cwd":"…","sessionId":"…"}
{"type":"attachment","attachment":{"type":"edited_text_file","filename":"~/.qoder/memory/MEMORY.md","snippet":"…","content":"…","mtime":"…"},"uuid":"…"}
{"type":"attachment","attachment":{"prompt":[{"type":"text","text":"不要造软链，直接迁移。"}],"source_uuid":"527a9c86-…","commandMode":"prompt","origin":{"kind":"bridge","sessionId":"…"},"type":"queued_command"},"uuid":"…"}
```

**(i) active-leaf（正常 / rewind）**
```json
{"type":"active-leaf","sessionId":"…","leafUuid":"a7342e7e-…","explicit":false,"timestamp":1792855936648}
{"type":"active-leaf","sessionId":"…","leafUuid":"8de3bf8e-…","explicit":true,"rewound":true,"timestamp":1792851115649}
```

**(j) 图片 user 行 / tool_result 中的 image**
```json
{"type":"user","message":{"role":"user","content":[{"type":"image","source":{"type":"url","url":"https://qoder-vl-global.oss-ap-southeast-1.aliyuncs.com/cloud/…png?Expires=1795623146&OSSAccessKeyId=…&Signature=…"}}]},"uuid":"…","cwd":"…"}
```

**(k) API 错误 assistant 行**
```json
{"type":"assistant","uuid":"40af130b-…","message":{"id":"03fb276b-…","model":"<synthetic>","stop_reason":"stop_sequence","content":[{"type":"text","text":"The request could not be completed. Please try again."}]},"isApiErrorMessage":true,"error":"billing_error","errorDetails":"ModelTransportError: Custom provider request failed: 402 DeepSeek: Insufficient Balance…"}
```

**(l) 子代理 transcript 首行 + sidechain 字段**（`samples/qoder/04-*`）
```json
{"type":"user","uuid":"5aac481f-…","timestamp":"2026-10-24T15:32:57.400Z","message":{"role":"user","content":"You are doing READ-ONLY reconnaissance for a file-organization audit on macOS…"},"sessionId":"1433b77a-…","isSidechain":true,"agentId":"aExplore-29943601436ebef1","parent_tool_use_id":"call_01_EJVOmZC33Kn8yey0dvGp2226","cwd":"~/Documents/Qoder/2026-10-24/1433b77a","version":"1.1.75-hotfix.1"}
```

---

## 6. 工具调用表示

### 6.1 调用与结果的三元组

- **调用**：assistant 行 `message.content[0] = {type:"tool_use", id, name, input}`；`id` 形如 `call_00_<hash>`（custom provider 风格，本机 `call_00`×9668、`call_01`×1618…；偶见 `call_00_ET_…`）。
- **结果（给模型看）**：user 行 `message.content[0] = {type:"tool_result", tool_use_id, content, is_error}`；`content` 通常是字符串，图片结果是 `[{type:"image"}]` 数组（本机 233 条）。
- **结果（结构化给 UI）**：同一 user 行的 `toolUseResult` 字段（dict/list/str），另有 `sourceToolAssistantUUID` = **携带该 `tool_use` 的 assistant 行 uuid**。
- **配对键**：`tool_use.id == tool_result.tool_use_id`；`user.parentUuid == sourceToolAssistantUUID`（本机 12667 条 tool_result **100% 一致**）。同一 assistant 消息有多个 tool_use 时，**每个结果行 parent 指向各自的 tool_use block 行**，因此结果是父链之外的**兄弟分支**——这是转换器最容易踩的坑（见 §11-2）。

### 6.2 工具名清单（本机 44 会话，`tool_use.name`）

| 工具 | 次数 | 主要 input keys |
|---|---:|---|
| `Bash` | 8242 | `command`, `description`, `timeout`?, `run_in_background`? |
| `Edit` | 1559 | `file_path`, `old_string`, `new_string`, `allow_multiple`? |
| `Write` | 810 | `file_path`, `content` |
| `Read` | 771 | `file_path`, `offset`?, `limit`? |
| `Agent` | 352 | `description`, `subagent_type`, `prompt`, `run_in_background`?, `name`?, `mode`? |
| `WebSearch` | 267 | `query` |
| `TaskUpdate` | 224 | `taskId`, `status`?, `subject`?, `description`?, `activeForm`? |
| `TaskCreate` | 156 | `subject`, `description`, `activeForm` |
| `WebFetch` | 99 | `url`, `prompt` |
| `mcp_call` | 75 | `toolName`, `arguments` |
| `TaskStop` | 42 | `task_id` |
| `Grep` | 17 | `pattern`, `path`, `output_mode`, `-n`?, `head_limit`?, `glob`? |
| `AskUserQuestion` | 15 | `questions`（`{question,header,options,multiSelect}`） |
| `mcp_get` | 9 | `toolName` |
| `mcp_list` | 8 | `keyword`?, `includeDescription`? |
| `Skill` | 4 | `skill`, `args`? |
| `UpdateGoal` | 3 | `status` |
| `TaskList` / `Glob` / `present_visualization` | 1 各 | — |

### 6.3 `toolUseResult` 结构分类（转换时建议整体保留为 metadata）

| 工具 | `toolUseResult` 关键字段 |
|---|---|
| Bash | `kind:"completed"|"backgrounded"|"cancelled"`,`stdout`,`stderr`,`exitCode`,`signal`,`interrupted`,`isImage`,`noOutputExpected`,`processStarted`,`returnCodeInterpretation`?,`persistedOutput`?,`totalLines/totalBytes`?；后台还有 `taskId`,`pid`,`outputFile`,`initialOutput` |
| Read | `{type:"text", file:{filePath, content}}`；图片为 `{type:"image", ...}` |
| Write | `{success, file_path, bytesWritten, additions, deletions}` |
| Edit | `{success, file_path, additions, deletions, diff}` |
| Grep/Glob | `{mode:"content"|"files_with_matches", numFiles, filenames, content, numLines, totalLines, appliedLimit?, truncated?}` |
| WebSearch | `{query, results:[{title,link,snippet,publishedTime,hostname}], durationSeconds}` |
| WebFetch | `{url, code, codeText, bytes, result, durationMs}` |
| Agent | `{kind:"agent-result", agentId, agentType, state, terminateReason, content, transcriptPath, outputPath, apiError?}`；异步启动：`{isAsync:true,status:"async_launched",agentId,description,prompt,resolvedModel,outputFile}` |
| AskUserQuestion | `{questions, answers}` |
| TaskCreate/Update/List | `{task:{id,subject}}` / `{success,taskId,updatedFields,statusChange}` / `{tasks:[…]}` |
| mcp_call | 依工具而定：文本结果（str）、`{"type":"text","text":...}` 列表、或 `{content, filenames, mode,…}` |
| 取消/错误 | `{kind:"tool-status",status,summary,isHardFailure}`、`{tool_error_stage,tool_error_subtype,tool_error_details_json}`、`{errorType,isHardFailure}`、`{isHardFailure:false}` |
| 用户拒绝 | 结果文本 `"The user doesn't want to proceed with this tool use…"`，行上有 `userFeedback` / `toolDenialKind` 字段（本机 28 条 denial） |

---

## 7. 分支 / 父子 / rewind / compaction

### 7.1 树结构

- 每条 user/assistant/attachment/system 有 `uuid` + `parentUuid`，构成树（会话首条 `parentUuid:null`）。
- 正常情况下父链是线性的；**一次 assistant 消息含多个 tool_use 时**：`block1→block2→…→blockN` 线性串联，而每个 tool_result 行的 `parentUuid` 指向**对应的 block 行**，是父链的**旁支**。
- **主 transcript `isSidechain` 全 false**；subagent transcript 全 true（独立文件）。
- rewind：`active-leaf` 带 `explicit:true, rewound:true`（本机 8 条，`5648ef6d`、`8796e213` 等长会话）。被放弃的分支记录**仍保留在文件里**，只是不再是最新 leaf。

### 7.2 线性化正确算法（转换器建议实现）

```
1. 读全文件（流式），按行序建：
   - by_uuid: uuid → record
   - assistant 分组: 连续且 message.id 相同的行 → 一个逻辑 assistant 消息（blocks 按行序追加）
2. 找最终分支：取最后一条 active-leaf 的 leafUuid，沿 parentUuid 回溯到根 → final_path 集合。
   （若文件尾部刚被截断没有 active-leaf：退化用最后一条 user/assistant 记录回溯）
3. 对 final_path 上的每个逻辑 assistant 消息：输出 thinking/text/tool_use blocks。
4. tool_result：不要靠父链找；建立 tool_use_id → (assistant 消息, block)；
   扫所有 user/tool_result 行，用 tool_use_id 配到消息上；最终分支上的 assistant 消息对应的结果全部保留
   （即使 result 行本身不在 final_path 上——它们本来就在旁支）。
5. user 文本行：只保留 final_path 上的；按 humanInput/isMeta/isCompactSummary 分类（§10.3）。
6. 顺序：按 assistant 消息的行号（首次出现位置）与 user 行号排序即可得到时间线；
   一个 turn 内顺序 = assistant blocks → 其全部 tool_results。
```

---

## 8. 时间戳

| 记录 | 格式 | 示例 |
|---|---|---|
| `user` / `assistant` / `attachment` / `system` | **ISO 8601 UTC 毫秒字符串** | `"2026-10-24T15:32:16.648Z"` |
| `active-leaf` / `runtime-config` | **epoch 毫秒整数** | `1792855936648` |
| `file-history-snapshot.snapshot.timestamp` / `trackedFileBackups.*.backupTime` | ISO 字符串 | — |
| `last-prompt` / `workspace-directories` | 无 timestamp | — |
| `tasks/*.json` `businessInfo.begin_at`、`goals/*.json` `createdAt` | epoch 毫秒 | — |

本机统计：ISO 字符串 40451 条、epoch ms 26822 条（active-leaf 26239 + runtime-config 583）。两天区混用是本格式与 CC 的一个差异点。

---

## 9. 与 Claude Code (CC) transcript 对比

| 维度 | Claude Code | Qoder | 转换影响 |
|---|---|---|---|
| 行类型 | `user`/`assistant`/`system`/`summary`/`file-history-snapshot`/`queue-operation` | `user`/`assistant`/`system`/`attachment`/`active-leaf`/`runtime-config`/`workspace-directories`/`last-prompt`/`file-history-snapshot` | 需过滤 Qoder 专有 5 类 |
| assistant 粒度 | 一条消息 = 一行（content 数组含全部 block） | **一条消息 = N 行，每行 1 block，共享 message.id** | 必须按 `message.id` 合并，否则一条回复被拆成 N 条 |
| user 内容 | 字符串或 block 数组；attachments 内嵌 | block 数组/字符串；`attachment` 为独立记录行 | 过滤 attachment |
| tool_result | 在 user content 内，`tool_use_id` 配对 | 同，但**额外** `toolUseResult` 结构化字段 + `sourceToolAssistantUUID` | 可保留结构化 metadata |
| tool_use id | `toolu_…`（Anthropic） | `call_00_…`（自定义 provider 序号风格） | 仅当作不透明 id |
| 时间戳 | ISO 字符串 | 消息记录 ISO + `active-leaf/runtime-config` **epoch ms** | 统一转 epoch ms |
| 压缩 | `system` compact_boundary + user isCompactSummary | 同构，Qoder 额外 `logicalParentUuid`、`requiresActiveLeafCommit` | 同策略处理 |
| summary | 有 `summary` 行（会话标题/摘要） | **无** summary 行；无标题索引 | 标题需从首条 prompt 推导 |
| 分支 | parentUuid 树；rewind 用 active-leaf 类似 | 同，但 `active-leaf` 是显式记录类型 | 取最后 leaf 回溯 |
| 模型字段 | `claude-…` | 内部 UUID key / custom provider 串 / `<synthetic>` | 需映射，未知 key 保留原值 |
| 子代理 | sidechain 文件 | `subagents/agent-*.jsonl`，字段 `agentId`/`parent_tool_use_id` | 可选一并导入 |
| 版本/入口 | 有 version、userType 等 | 同，且 `entrypoint` 固定 `cli` | 可丢弃 |

---

## 10. 映射到 DSH 通用中间表示（IM）

### 10.1 会话级元数据

| IM 字段 | 取值规则 |
|---|---|
| `session_id` | 文件名去 `.jsonl`（= 行内 `sessionId`） |
| `source` | `"qoder"`；`project-slug` 原样保留 |
| `cwd` | 首条带 `cwd` 的记录；另用最后一条 `workspace-directories.directories` 还原多根工作区 |
| `created_at` | 首条 user/assistant 记录时间（ISO→epoch ms） |
| `updated_at` | 最后一条带时间戳记录（含 `active-leaf` 的 epoch ms） |
| `title` | **transcript 无 title 字段**。规则：首条 `user.humanInput.text` 的第一行，截断 60–80 字；退化用最后一条 `last-prompt.lastPrompt`；再退化 `"<project-slug> / <sid8>"` |
| `model` | 首条 assistant 的 `message.model`；内部 UUID key 与 `.models/` 加密 catalog 不可解，保留原值并标 `unknown`（本机默认模型见 §1.5 settings：`magpie/deepseek/deepseek-flash`） |
| `git_branch` | 任一记录的 `gitBranch`（可能为 `HEAD`） |
| `version` | 记录的 `version` 字段 |
| `source_app` | `entrypoint`（`cli`） |
| `stats` | 行数、逻辑消息数（distinct message.id）、human prompt 数、tool 调用数、token 总量（有 usage 时） |

### 10.2 消息映射规则

- **R1 过滤**：只转 `type ∈ {user, assistant}`。丢弃 `active-leaf`/`runtime-config`/`workspace-directories`/`last-prompt`/`file-history-snapshot`/`attachment`（`queued_command` 可选转 user 消息：取 `attachment.prompt` 文本，`source_uuid` 用于与已有 user 消息去重）。
- **R2 assistant 合并**：连续同 `message.id` 的行合并；blocks 顺序即行序。`thinking` → `assistant.reasoning`（`signature` 丢弃）；`text` → `assistant.text`（`citations` 丢弃）；`tool_use` → `tool_call {id, name, input}`。丢弃 `requestTokenAnchor`。`message.usage`（若有）→ `assistant.usage`。
- **R3 user 分类**：
  - `content[0].type=="tool_result"` → `role:"tool"`，`tool_call_id=tool_use_id`，`content` 取块文本/图片，`is_error` → error 状态；`toolUseResult` 原样存 `metadata.tool_use_result`（可选）。
  - `isCompactSummary==true` → `role:"system"`, `subtype:"compaction_summary"`（**不可当 user prompt**）。
  - `isMeta==true` 或 `origin.kind=="task-notification"` 或正文 `[Request interrupted by user]` → `role:"system"`/`subtype:"injected"` 或直接丢弃（建议丢弃，只把中断记为事件）。
  - 其余 text/string 且 `humanInput != null` → 真正 user prompt；`promptId`/`requestSetId` 保留为 metadata 便于分回合。
  - 图片 block → user message 的 attachment（URL 会过期，见 §11-7）。
- **R4 tool 序列**：每个 `tool_use` 生成一条 tool_call；用 `tool_use_id`/`sourceToolAssistantUUID` 配 result；缺失结果（中断/压缩/rewind/后台未完成）→ 生成 `status:"missing"` 占位，不要跳过，否则序列错位。
- **R5 时间**：ISO 字符串 `datetime.fromisoformat` → epoch ms；整数直接视为 epoch ms。回合时间用 user prompt 时间。
- **R6 分支**：默认只导**最终分支**（最后一条 `active-leaf.leafUuid` 回溯 + 旁支 tool_result 配对，§7.2）。若需要全量（含废弃分支）：按行序全导，`active-leaf` 之后被 rewind 掉的记录标 `abandoned:true`。
- **R7 压缩**：`system/compact_boundary` 映射为 `event:"compaction"`（保留 `compactMetadata`）；其后的 `isCompactSummary` user 行作为 `system/summary` 保留一次；不要把压缩摘要当普通 user 输入，也不要因压缩而只导后半段（原文件仍保留全部历史）。
- **R8 附件/图片**：`source.type=="url"` 是**带过期时间的 OSS 预签名 URL**；转换时选：(a) 仅保留 URL 并标 `expired_unverified`；(b) 立即下载到会话附件目录；(c) 用 `~/.qoder/tmp/chat-attachment-staging/` 本地原件匹配。不要默认请求该 URL（可能已 403）。
- **R9 子代理**：主 transcript 的 Agent tool_use 结果 `toolUseResult.transcriptPath` 指向 `subagents/agent-*.jsonl`；如需完整子代理轨迹，按同规则二次解析该文件（`isSidechain:true`，字段见 §4.8），作为 tool_call 的 `sub_trace` 挂载。`task-*.json` 的 `result/summary/status` 可直接作为 Agent 调用的输出摘要。
- **R10 标题/回合**：`requestSetId` 每次人类提交唯一（本机 440/440），`promptId` 覆盖一条人类 prompt 及其派生的 tool_result 行（462 个 distinct）；assistant 行不带这两个字段，回合切分用"human user 行 + 其后的 assistant/tool 行直到下一条 human user 行"。`origin.kind=="bridge"` 的 queued_command 也算人类输入。

### 10.3 可丢弃字段清单

`requestTokenAnchor`、`thinking.signature`、`text.citations`、`active-leaf.*`、`runtime-config.*`、`workspace-directories.*`（多根已另取）、`last-prompt.*`、`file-history-snapshot.*`、`promptId`/`requestSetId`（可作为 metadata 保留）、`isSidechain`（全常量）、`userType`、`entrypoint`、`message.type`、`message.id`（合并后可留存）、`partialStreamIndex`、`aborted`、`rewound`。

---

## 11. 坑（按踩坑概率排序）

1. **assistant 按 block 拆行**：不做 `message.id` 合并，会把一条回复拆成 thinking/text/tool_use 多条，tool_use 与文本顺序/配对全乱。合并时用**行序**而非 `stop_reason`。
2. **tool_result 是旁支，不在父链上**：一次 assistant 消息多个工具时，只沿最后 `active-leaf` 的 `parentUuid` 回溯会**丢掉前 N-1 个工具结果**。必须用 `tool_use_id` / `sourceToolAssistantUUID` 显式配对。
3. **`user` 行不都是用户输入**：本机 505 条 user text 中只有 434 条 `humanInput`；其余是压缩摘要（7）、`isMeta` 注入（44）、`[Request interrupted by user]`（5）、`task-notification`（17）、goal 续跑等。判定顺序：`tool_result` → `isCompactSummary` → `isMeta`/`origin` → `humanInput`。
4. **时间戳混用**：`active-leaf`/`runtime-config` 是 epoch ms，其余是 ISO 字符串；混用同一解析器会得到 1970 年或 None。
5. **文件可能正在被写**：Qoder 运行中会继续 append，可能读到半行；逐行容错，或先 `stat` 固定 size 再读。
6. **slug 不可逆**：中文/下划线都变 `-`，绝不能从目录名反推 cwd；cwd 从记录内取。`projects/-/goals/` 不是会话。
7. **图片 URL 会过期**：`source.type:"url"` 是 Qoder OSS 预签名 URL（含 `Expires`），导入时可能已 403；优先用 `tmp/chat-attachment-staging` 原件或标注过期。
8. **压缩不删旧数据**：append-only，压缩前的消息仍在文件前部；按行序全导会把压缩摘要和前文都导一遍（重复）。先按最终 leaf 回溯或用 compact_boundary 分段。
9. **rewind 分支残留**：被 rewind 的消息仍在文件里；不按 active-leaf 选分支会导出用户已放弃的内容。
10. **会话 cwd 常是临时目录**：`~/Documents/Qoder/<date>/<sid8>` 多为空目录，别当项目根；真实项目路径通常在 prompt 文本或 workspace-directories 里。
11. **模型 key 不可读**：默认模型是内部 UUID `eb7e9f84-3471-4014-bf41-f8092a8f56c7`，映射表在 `~/.qoder/.models/.../catalog-v7`（加密）；不要猜，保留原值。`usage` 只在 custom provider 会话存在。
12. **敏感数据**：Bash 的 `stdout`、`toolUseResult`、prompt 里可能有 AK/SK、token、内网地址、签名 URL；导入前需脱敏。`state.json` 的 `p`/`t` 是加密数据，不要尝试解密或展示。
13. **子代理轨迹在另一目录**：主 transcript 只有 Agent 调用的 summary；完整子代理对话在 `subagents/agent-*.jsonl`（`isSidechain:true`），需要单独读。
14. **坏行容错**：`json.loads` 失败不要中断整个导入；统计坏行数并在结果中报告。

---

## 12. 复现与验证命令

```bash
# 0) 只读定位（本机路径）
ls ~/.qoder/projects | head
find ~/.qoder/projects -maxdepth 2 -name '*.jsonl' -not -path '*/subagents/*' | wc -l   # 44
du -sh ~/.qoder/projects                                                                 # 368M

# 1) 样本目录里的参考实现（本仓库内，只读原目录）
python3 samples/qoder/repro_scan.py stats --root ~/.qoder/projects   # 类型/工具/模型统计
python3 samples/qoder/repro_scan.py list  --root ~/.qoder/projects   # sid | slug | 起始时间 | cwd | 首条 prompt
python3 samples/qoder/repro_scan.py dump  ~/.qoder/projects/-Users-larr-Documents-Qoder-2026-10-24-1433b77a/1433b77a-6e0b-465f-a533-8b8070478edb.jsonl

# 2) 手工统计某会话记录类型
python3 - <<'PY'
import json,sys,collections
p=sys.argv[1] if len(sys.argv)>1 else '~/.qoder/projects/-Users-larr-Documents-Qoder-2026-10-24-1433b77a/1433b77a-6e0b-465f-a533-8b8070478edb.jsonl'
c=collections.Counter(json.loads(l).get('type') for l in open(p) if l.strip())
print(c)
PY

# 3) 校验 project-slug 编码
python3 - <<'PY'
import json,glob,os,re
for p in glob.glob(os.path.expanduser('~/.qoder/projects/*/*.jsonl')):
    sid=os.path.basename(p)[:-6]; slug=os.path.basename(os.path.dirname(p))
    cwd=None
    for l in open(p):
        o=json.loads(l)
        if 'cwd' in o: cwd=o['cwd']; break
    enc=re.sub(r'[^A-Za-z0-9]','-',cwd or '')
    if enc!=slug: print("MISMATCH",sid,slug,cwd)
print("slug check done")
PY

# 4) 确认是否有其他 transcript 位置（新版迁移时）
find ~/.qoder -maxdepth 3 -name '*.jsonl' -not -path '*/projects/*' 2>/dev/null | head
find ~/Library -path '*qoder*' -name '*.jsonl' 2>/dev/null | head

# 5) 查看 state.json / compression-v2 / tasks / goals（结构，不解密）
cat ~/.qoder/projects/-Users-larr-Documents-Qoder-2026-10-24-1433b77a/1433b77a-6e0b-465f-a533-8b8070478edb/state.json | head -c 2000
head -c 1000 ~/.qoder/projects/-Users-larr-Documents-Qoder-2026-10-24-1433b77a/1433b77a-6e0b-465f-a533-8b8070478edb/compression-v2/state.json
ls ~/.qoder/tasks/1433b77a-6e0b-465f-a533-8b8070478edb/
```

### 本机实测规模（供转换器压测）

| 指标 | 值 |
|---|---|
| 主 transcript / project-slug / 总大小 | 44 个 / 37 个 / 368 MB |
| 最大会话 | `5648ef6d-…` 30.6 MB，16466 行 |
| 总行数 / 解析失败行 | 69402 / 0 |
| 逻辑 assistant 消息（distinct message.id） | 10096（24382 行） |
| human prompt（`humanInput`） | 440 |
| tool_result 行 / tool_use block | 12659 / 12660 |
| 含 usage 的会话 / usage 行 | 9 / 1121（全部 custom provider） |
| 子代理 transcript | 351（general-purpose 317 / Explore 32 / Plan 2） |
| 有压缩边界的会话 | 7 |

样本：`samples/qoder/`（截断/脱敏副本 + `README.md` 说明 + `repro_scan.py` 参考实现）。
