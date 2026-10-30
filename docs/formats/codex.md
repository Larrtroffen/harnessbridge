# Codex Session 格式逆向规格（~/.codex, CLI 0.165.0）

> 目标：让转换器把 Codex 的一次 thread 还原成完整对话序列（用户/助手/推理/工具调用/工具结果/压缩点/分支），并可映射到通用中间表示（IR）。
> 本机实测：`~/.codex/version.json` = `0.165.0`；rollout 文件 283 个，`state_5.sqlite` threads 206 行，`thread_history_1.sqlite` thread_items 176,394 行 / thread_turns 1,669 行。
> 所有分析均只读（`sqlite3 "file:...?mode=ro"` / Python 读取），未改动 `~/.codex` 任何文件。

---

## 1. 权威源结论（先看这节）

| 来源 | 实际角色 | 结论 |
|---|---|---|
| `sessions/YYYY/MM/DD/rollout-*.jsonl` | **完整 append-only 转录（权威内容）** | 唯一的"全量事件流"：session_meta / response_item / event_msg / token_usage_record / turn_context / compacted / world_state 都在这里，按 `ordinal` 单调递增。 |
| `state_5.sqlite` → `threads` | **thread 目录索引** | 206 行，`rollout_path` 全部指向存在的 JSONL（0 缺失）；含 cwd/model/provider/title/archived/timestamps 等元数据。 |
| `thread_history_1.sqlite` → `thread_items` / `thread_turns` | **分页 UI 投影（派生库）** | `thread_items` 176,394 行与**全部 rollout 中 `event_msg.item_completed` 总数 176,394 完全一致**（逐条同构，`rollout_ordinal` 指回 rollout 行号）；`thread_turns` 是 turn 边界投影。可当只读缓存用，但不是数据源头。 |
| `session_index.jsonl` | 命名 thread 索引 | 67 行：`{id, thread_name, updated_at}`；仅含被命名/有标题的 thread，**不是** thread 全集。 |
| `history.jsonl` | 用户 prompt 输入历史 | 1,403 行：`{session_id, ts, text}`；只是输入框历史，不含助手回复，不能还原对话。 |

**关键证据**

- 版本 0.165 已全面切到 "paginated" 历史：`threads.history_mode` 全为 `paginated`（206/206），rollout 内 `session_meta.history_mode` 全为 `paginated`（393 条 session_meta）。
- 迁移表：`rollout_migration_state`、`rollout_migration_skipped_rollouts` 均 0 行；`backfill_state.status='complete'`。即 JSONL→SQLite 回填已完成。
- 同一 thread 可能有多个 rollout 文件：283 个文件只有 **207 个不同的 `payload.id`、75 个不同 `session_id`**，其中 **132 个文件的 session_meta 带 `forked_from_id`/`parent_thread_id`**（fork/子代理副本），32 个 thread id 出现在多个文件（续写/分叉副本）。**`state_5.threads.rollout_path` 指向的就是该 thread 当前最新那个文件**（实测重复 id 组均指向时间最新的文件）。
- 因此转换器的取数顺序：**先查 `threads.rollout_path` 拿文件 → 按 `ordinal` 读 JSONL**；若只有裸 JSONL 目录，则按 `session_meta.payload.id` 分组，取 `timestamp`/文件 mtime 最新、且 ordinal 覆盖最长的那个文件，并对 fork 文件去重（见 §6）。
- `thread_realtime_items` 表当前 0 行（直播缓冲，非持久历史，可忽略）。

---

## 2. 文件与目录布局

```
~/.codex/
├── sessions/2026/10/29/rollout-2026-10-29T02-34-26-<thread-id>.jsonl      # 主转录
├── sessions/2026/10/29/rollout-2026-10-29T02-34-26-<base-id>_<fork-id>.jsonl  # fork/续写副本（文件名两个 uuid）
├── session_index.jsonl        # 命名 thread 索引
├── history.jsonl              # 用户输入历史（非对话）
├── state_5.sqlite             # threads / thread_sections / projects / attachments / spawn_edges
└── thread_history_1.sqlite    # thread_items / thread_turns（分页投影, ~1.0 GB）
```

- 文件名时间 = **session_meta.timestamp**（UTC，`-` 分隔）；`<uuid>` 为 thread id（UUIDv7 风格 `01a...`），`_<uuid>` 后缀表示 fork 出来的新分支。
- 一层 thread 的 rollout 文件即完整会话；`source.subagent.thread_spawn` 会记录父 thread / depth / agent_path / nickname（可还原代理树）。

真实路径示例（本机）：
`~/.codex/sessions/2026/10/29/rollout-2026-10-29T02-34-26-01a183ca-c72e-7740-bcbf-27f9daedee43.jsonl`

---

## 3. 行级信封（所有行共有的外层字段）

```json
{"timestamp":"2026-10-21T18:47:44.422Z","ordinal":0,"type":"session_meta","payload":{...}}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `timestamp` | string | 行写入时间，ISO-8601 UTC（毫秒）。文件内通常递增，但同一毫秒多行很常见。 |
| `ordinal` | int | **该 rollout 内的全局行序号，从 0 递增**。恢复顺序以它为准；SQLite 的 `rollout_ordinal` 就是它。 |
| `type` | string | 顶层记录类型：`session_meta`/`response_item`/`event_msg`/`token_usage_record`/`turn_context`/`world_state`/`compacted`/`inter_agent_communication_metadata`。 |
| `payload` | object | 按 `type` 不同；多数还有内部 `payload.type` 二级类型。 |
| `metadata` | object? | 仅部分 `response_item` 有：`{"client_authored":false,"user_input_order":2,...}`。 |

**全库类型统计**（283 文件）：`event_msg` 263,467 / `response_item` 253,150 / `token_usage_record` 73,858 / `inter_agent_communication_metadata` 10,858 / `turn_context` 2,945 / `world_state` 1,661 / `compacted` 1,011 / `session_meta` 393。

---

## 4. 各记录类型字段与示例

### 4.1 `session_meta`（线程头，ordinal=0，每文件 1 条）

字段：`session_id`（根会话 id，fork 时保持不变）、`id`（当前 thread id）、`timestamp`、`cwd`、`runtime_workspace_roots`、`originator`（codex-tui 等）、`cli_version`、`source`（`"cli"`/`"vscode"`/`{subagent:{thread_spawn:{parent_thread_id,depth,agent_path,agent_nickname}}}`/`"exec"`）、`thread_source`（`user`/`subagent`）、`agent_nickname`、`agent_path`、`model_provider`、`base_instructions.text`（长系统提示）、`context_window`、`forked_from_id`、`parent_thread_id`、`subagent_history_start_ordinal`、`history_base`、`history_mode`、`git`、`multi_agent_version`。

```json
{"timestamp":"2026-10-21T18:47:44.422Z","ordinal":0,"type":"session_meta","payload":{"session_id":"01a15fc9-...","id":"01a15fc9-...","timestamp":"2026-10-21T18:46:45.937Z","cwd":"~","originator":"codex-tui","cli_version":"0.163.0","source":"vscode","thread_source":"user","model_provider":"magpie","history_mode":"paginated"}}
```
（示例截断；真实 `base_instructions.text` 常达 10–40 KB，转换时应丢弃或单独存为 system prompt。）

### 4.2 `turn_context`（每个 turn 开始时一条，模型/cwd/沙箱快照）

字段：`turn_id`、`root_turn_id`、`cwd`、`workspace_roots`、`current_date`、`timezone`、`approval_policy`、`approvals_reviewer`、`sandbox_policy`、`permission_profile`、`model`、`effort`、`collaboration_mode`（含 `settings.model` / `reasoning_effort` / `developer_instructions`）、`summary`、`disabled_plugin_ids`、`multi_agent_version`、`realtime_active`。

```json
{"timestamp":"2026-10-21T18:47:44.428Z","ordinal":7,"type":"turn_context","payload":{"turn_id":"01a15fca-6e23-7621-bd96-abbf251ea8e1","root_turn_id":"01a15fca-6e23-7621-bd96-abbf251ea8e1","cwd":"~","approval_policy":"never","sandbox_policy":{"type":"danger-full-access"},"model":"apikey-fan/gpt-6-astra","effort":"xhigh"}}
```

### 4.3 `event_msg`（UI/生命周期事件；turn 边界与"呈现层 item"）

`payload.type` 取值与全库计数：
| payload.type | 数量 | 后缀（本机） | 说明 |
|---|---|---|---|
| `item_completed` | 176,394 | — | **每个可显示 item 的完成快照**（用户消息/助手消息/工具执行/文件变更/推理/压缩…），`item.type` 为驼峰枚举，是 UI 与 SQLite 投影的来源。字段：`thread_id`,`turn_id`,`item`,`started_at_ms`,`completed_at_ms`。 |
| `token_count` | 81,043 | — | 每次模型响应后的用量：`info.total_token_usage` / `last_token_usage` / `model_context_window` + `rate_limits`。 |
| `task_started` | 1,959 | — | **turn 开始**：`turn_id`,`root_turn_id`,`started_at`(unix 秒),`model_context_window`,`turn_attribution{turn_trigger,parent_turn_id}`。 |
| `task_complete` | 1,725 | — | **turn 正常结束**：`turn_id`,`last_agent_message`(最终助手文本),`started_at`,`completed_at`,`duration_ms`,`time_to_first_token_ms`,`error`。 |
| `turn_aborted` | 192 | — | **turn 中止**：`reason`(如 `interrupted`),`started_at`,`completed_at`,`duration_ms`。 |
| `thread_settings_applied` | 2,115 | — | thread 级设置快照：`thread_settings{model,model_provider_id,service_tier,approval_policy,cwd,reasoning_effort,collaboration_mode,...}`。 |
| `thread_goal_updated` | 39 | — | Codex Goal 模式：`goal{threadId,objective,status,tokensUsed,timeUsedSeconds,...}`。 |

`item_completed.item.type` 全库分布（即"展示层 item 枚举"，与 response_item 互为镜像）：

`CommandExecution` 69,462 / `Reasoning` 66,913 / `AgentMessage` 14,199 / `SubAgentActivity` 10,924 / `FileChange` 7,960 / `McpToolCall` 1,646 / `FunctionCallOutput` 1,503 / `UserMessage` 1,343 / `ContextCompaction` 940 / `CollabAgentToolCall` 639 / `Extension` 408 / `WebSearch` 320 / `ImageView` 137。

```json
{"timestamp":"2026-10-21T18:47:44.462Z","ordinal":10,"type":"event_msg","payload":{"type":"item_completed","thread_id":"01a15fc9-...","turn_id":"01a15fca-...","item":{"type":"UserMessage","id":"01a15fca-...","client_id":"a1ee0777-...","content":[{"type":"text","text":"你可以理解一下目前剩下三个Codex实例在做什么……"}],"text_elements":[]},"started_at_ms":1792608464462,"completed_at_ms":1792608464462}}
```

### 4.4 `response_item`（模型原始消息流 —— 转换的**主数据**）

`payload.type` 全库分布：`reasoning` 70,283 / `function_call_output` 45,555 / `function_call` 43,930 / `custom_tool_call` 31,681 / `custom_tool_call_output` 31,681 / `message` 18,620 / `agent_message` 10,884 / `web_search_call` 320 / `tool_search_call` 97 / `tool_search_output` 97 / `image_generation_call` 2。

| payload.type | 关键字段 | 含义 |
|---|---|---|
| `message` | `role`(`user`/`assistant`/`developer`)、`content[{type,input_text\|output_text, text}]`、`id` | 真正的对话消息。`developer` 是注入的开发者/系统上下文（技能说明、协作模式等），转换时应默认过滤。角色分布：assistant 15,614 / user 2,135 / developer 871。 |
| `reasoning` | `id`、`summary[{type:"summary_text",text}]`、`encrypted_content`(base64 密文，可丢) | 模型推理摘要。**明文只有 `summary[].text`**（常有空数组），完整思维链为加密内容不可读。 |
| `function_call` | `name`、`arguments`(JSON **字符串**)、`call_id`、`status`、`id`、`internal_chat_message_metadata_passthrough.turn_id` | 工具调用。`name` 如 `exec_command`、`apply_patch`、`mcp__<ns>__<tool>`。 |
| `function_call_output` | `call_id`、`output`(string)、`id` | 工具结果，靠 `call_id` 与调用配对。输出常含 `Chunk ID/Wall time/Process exited with code/Original token count/Output:` 头。 |
| `custom_tool_call` | `name`(如 `apply_patch`)、`input`(string)、`call_id` | 自定义工具（自由文本输入而非 JSON）。 |
| `custom_tool_call_output` | `call_id`、`output` | 对应结果。 |
| `tool_search_call` / `tool_search_output` | `call_id`、`arguments{query}` / `tools[]` | 动态工具发现，一般可折叠忽略。 |
| `web_search_call` | `action{type:"search",query,queries}` | 内置联网搜索调用（无输出行，结果在后续 message/reasoning）。 |
| `agent_message` | `author`、`recipient`、`content[{input_text/encrypted_content}]` | 多代理通信（子代理 ↔ 主代理），常伴 `inter_agent_communication_metadata{trigger_turn}`。 |
| `image_generation_call` | `revised_prompt`、`result`(base64 PNG) | 图片生成。 |

```json
{"timestamp":"2026-10-21T18:47:48.647Z","ordinal":13,"type":"response_item","payload":{"type":"function_call","status":"completed","id":"fc_18e09fe76da12ed800009b98","name":"exec_command","arguments":"{\"cmd\":\"cat .../SKILL.md\",\"max_output_tokens\":12000}","call_id":"call_df4b981a696e43b78acb7257333cb3e3"},"metadata":{"client_authored":false,"user_input_order":2}}
```

```json
{"timestamp":"2026-10-21T18:47:48.726Z","ordinal":16,"type":"response_item","payload":{"type":"function_call_output","id":"fco_...","call_id":"call_df4b981a696e43b78acb7257333cb3e3","output":"Chunk ID: bb4676\nWall time: 0.0000 seconds\nProcess exited with code 0\n...\nOutput:\n---\nname: orca-cli\n..."}}
```

```json
{"timestamp":"2026-10-21T18:48:05.340Z","ordinal":40,"type":"response_item","payload":{"type":"reasoning","id":"rs_0f9a18...","summary":[{"type":"summary_text","text":"**Checking for active sessions**"}],"encrypted_content":"gAAAAABq2Qjl..."}}
```

### 4.5 其它记录

- `token_usage_record`（73,858）：`{thread_id,turn_id,session_id,root_turn_id,response_id,usage{input_tokens,cached_input_tokens,cache_write_input_tokens,output_tokens,reasoning_output_tokens,total_tokens},turn_token_usage,thread_token_usage}`。用于给消息补 token 用量。
- `world_state`（1,661）：`{full:true,state{...}}` 环境快照（git/AGENTS.md/技能/时区/权限），对对话还原无用。
- `inter_agent_communication_metadata`（10,858）：`{"trigger_turn":true}`，标记下一条是代理间消息。
- `compacted`（1,011）：上下文压缩事件，见 §6。

---

## 5. Turn 边界与时间戳

- 一个 turn = `event_msg.task_started` → 若干 `response_item` / `event_msg.item_completed`（同 `turn_id`）→ `event_msg.task_complete`（或 `turn_aborted`）。
- `turn_id`/`root_turn_id` 在 `turn_context`、`task_started`、`item_completed`、`function_call.internal_chat_message_metadata_passthrough.turn_id`、`token_usage_record` 中一致，可用于归属。
- **排序用 `ordinal`**，不要用外层 `timestamp`（同毫秒多行、写入顺序才是权威）；`event_msg.task_started.started_at` 等是 unix 秒级的另一套时间。
- 助手最终答复：优先取 `task_complete.last_agent_message`；逐条消息则取 `response_item.message(role=assistant)`。
- `turn_aborted.reason` 有价值（`interrupted` = 用户中断）。

---

## 6. 分支、fork 与 compaction

### fork / 子代理
- 新文件 `rollout-...-<base-id>_<new-id>.jsonl`；`session_meta` 里 `id` = 新 thread（当前文件头所代表），`session_id` = 根会话，`forked_from_id`/`parent_thread_id` = 来源 thread。
- 子代理：`source.subagent.thread_spawn{parent_thread_id,depth,agent_path,agent_nickname}`、`thread_source="subagent"`、`agent_path`、`subagent_history_start_ordinal`。
- 同 id 多文件（32 组）是 fork/续写副本：**不要把它们当成多轮拼接**；取 `threads.rollout_path` 或最新文件，其余用 `forked_from_id`/`parent_thread_id` 建树。

### compaction（`compacted` 行）
字段：`payload.message`（给模型看的交接摘要文本）、`replacement_history`（替换后的历史数组）、`replacement_history_metadata`、`retained_context`、`window_number`、`first_window_id`/`previous_window_id`/`window_id`、`compaction_response_id`、`latest_token_usage_record`、`resume_metadata`。
语义：从这里开始**后续请求携带的是 replacement_history，而不是之前的完整历史**；但**rollout 文件仍保留压缩前的全部行**。转换策略：保留全部原始消息，把 compaction 标记为"上下文窗口切分点"（`thread_items` 中对应 `contextCompaction` 940 条）；重建"模型当时看到的历史"时以 `replacement_history` 为准。

```json
{"timestamp":"2026-10-03T13:07:21.045Z","ordinal":204,"type":"compacted","payload":{"message":"Another language model started to solve this problem and produced a summary ...","replacement_history":[...],"window_number":1,"first_window_id":"...","previous_window_id":"...","window_id":"..."}}
```

---

## 7. 如何还原一个 thread 的完整对话序列

### 方式 A（推荐，有 SQLite 时）
```bash
# 1) thread 索引：最新的 thread
sqlite3 -header "file:$HOME/.codex/state_5.sqlite?mode=ro" \
  "select id, rollout_path, datetime(updated_at,'unixepoch') updated, cwd, model, model_provider, title
   from threads where archived=0 order by updated_at desc limit 5;"

# 2) 直接读该 thread 的 rollout（按 ordinal 天然有序）
sqlite3 "file:$HOME/.codex/state_5.sqlite?mode=ro" \
  "select rollout_path from threads where id='<thread-id>';"
```

### 方式 B（只有 JSONL 时）
1. `grep '"type":"session_meta"'` 提取每个文件的 `payload.id` / `session_id` / `forked_from_id` / `timestamp`；
2. 按 `payload.id` 分组，同组保留 **mtime 最新 + 行数（max ordinal）最大** 的文件；
3. 对目标 thread 按 `ordinal` 升序处理（文件本身即按 ordinal 追加）。

### 统一的 Python 还原伪代码
```python
import json, collections
rows = [json.loads(l) for l in open(rollout_path) if l.strip()]
rows.sort(key=lambda r: r["ordinal"])
items, calls, out = [], {}, []
for r in rows:
    t, p = r["type"], r.get("payload") or {}
    if t == "session_meta":
        meta = p                       # thread id / cwd / model_provider / base_instructions
    elif t == "response_item":
        pt = p.get("type")
        if pt == "message" and p.get("role") != "developer":   # 过滤注入上下文
            out.append({"role": p["role"], "text": "".join(
                b.get("text","") for b in p.get("content",[]))})
        elif pt == "reasoning":
            out.append({"role": "assistant", "type": "reasoning",
                        "text": "".join(s.get("text","") for s in p.get("summary",[]))})
        elif pt in ("function_call", "custom_tool_call"):
            calls[p["call_id"]] = p
            out.append({"role": "assistant", "type": "tool_call",
                        "call_id": p["call_id"], "name": p["name"],
                        "args": p.get("arguments") or p.get("input")})
        elif pt in ("function_call_output", "custom_tool_call_output"):
            out.append({"role": "tool", "call_id": p["call_id"],
                        "name": calls.get(p["call_id"], {}).get("name"),
                        "content": p.get("output")})
    elif t == "event_msg":
        pt = p.get("type")
        if pt == "task_started":
            out.append({"type": "turn_start", "turn_id": p["turn_id"]})
        elif pt == "item_completed":      # 备选：用展示层 item 补 UI 语义
            it = p["item"]
            if it.get("type") == "ContextCompaction":
                out.append({"type": "compaction", "text": it.get("content", "")})
            elif it["type"] == "AgentMessage" and it.get("text"):
                pass                      # 与 response_item.message 去重，别重复加
        elif pt == "task_complete":
            out.append({"type": "turn_end", "turn_id": p["turn_id"],
                        "final_text": p.get("last_agent_message")})
        elif pt == "turn_aborted":
            out.append({"type": "turn_abort", "turn_id": p["turn_id"],
                        "reason": p.get("reason")})
    elif t == "compacted":
        out.append({"type": "context_compaction", "summary": p.get("message"),
                    "replacement_history": p.get("replacement_history")})
```

### SQL 侧（若想直接用投影库）
```sql
-- turn 列表 + 边界 ordinal
select turn_id, status, rollout_ordinal, rollout_end_ordinal, started_at, completed_at
from thread_turns where thread_id = ? order by rollout_ordinal;
-- 展示层 item（item_json 为 UserMessage/AgentMessage/CommandExecution 等快照）
select rollout_ordinal, item_type, item_json from thread_items
where thread_id = ? order by rollout_ordinal;
```
注意：**`thread_items` 只有 item 级快照，没有 reasoning encrypted_content、message 的完整 response_item 元数据**；要完整还原仍读 rollout。

---

## 8. 映射到通用中间表示（IR）建议

建议 IR 事件：`session_start` / `turn_start` / `user_message` / `assistant_message` / `reasoning` / `tool_call` / `tool_result` / `compaction` / `turn_end`。

| 通用 IR 字段 | Codex 来源 | 规则 |
|---|---|---|
| `session.id` | `session_meta.payload.id`（当前 thread）；父/根用 `session_id` | fork 用 `parent_thread_id` 建 `parent_id` |
| `session.cwd` / `model` / `provider` / `created_at` | `session_meta.payload.{cwd, model_provider}`、`turn_context.payload.model`、`session_meta.timestamp` | model 取 `turn_context.model` 更准 |
| `event.seq` | `ordinal` | 全局稳定 |
| `event.ts` | 行 `timestamp` | ISO-8601 |
| `user_message.text` | `response_item.message(role=user).content[].text`（或 `item_completed(UserMessage)`） | 过滤 `developer` 角色 |
| `assistant_message.text` | `response_item.message(role=assistant)`；turn 末可用 `task_complete.last_agent_message` | 优先 response_item |
| `reasoning.text` | `response_item.reasoning.summary[].text` | 空 summary 就丢弃（不要解密） |
| `tool_call.{call_id,name,args}` | `function_call` / `custom_tool_call` | `arguments` 是 JSON 字符串需二次 parse；`apply_patch` 是文本 |
| `tool_result.{call_id,content,is_error}` | `function_call_output` / `custom_tool_call_output` | `output` 里 `Process exited with code N` 可提取退出码 → `is_error`；输出头可剥离 |
| `turn.id` | `task_started.turn_id` / `turn_context.turn_id` | `task_complete`/`turn_aborted` 收尾 |
| `compaction` | `compacted.payload.message` + `replacement_history` | 保留为窗口切分事件 |
| `metadata.subagent` | `session_meta.source.subagent.thread_spawn` | 建 child session 关系 |
| token 用量 | `token_usage_record.usage.*` / `event_msg.token_count.info.last_token_usage` | 按 `response_id`/turn 归属 |

---

## 9. 坑清单

1. **同 id 多文件**：283 文件 ≠ 283 thread。按 `payload.id` 去重；fork 副本文件名有两个 uuid，别把副本拼进主对话。
2. **`event_msg.item_completed` 与 `response_item` 是同一事实的两份表示**：合并时二选一（建议 response_item 为主、item_completed 只补 UI 语义/压缩），否则助手消息会翻倍。
3. **`arguments` 是 JSON 字符串**（`function_call`），`custom_tool_call.input` 是纯文本；解析失败时保留原文。
4. **`reasoning` 明文只有 summary**，`encrypted_content` 无法还原（不要尝试 base64 解码当文本）。
5. **`developer` 角色消息**含大量技能/协作模式注入（单条可达数十 KB），过滤后对话才干净；它也是 `turn_context.collaboration_mode.settings.developer_instructions` 的来源。
6. **`session_meta.base_instructions.text` 极大**（10–40KB/文件），转换时丢弃或单列。
7. **compaction 不删历史**：`compacted` 行之后文件仍是全量；但"模型当时上下文"只剩 `replacement_history`。二者语义不同。
8. **时间戳有 3 套**：行外层 ISO；`event_msg.*_at` unix 秒；`*_at_ms` 毫秒。排序统一用 `ordinal`。
9. **`history.jsonl` / `session_index.jsonl` 不是对话**，只用于补标题/输入历史。
10. **SQLite 为派生库**：`thread_items.item_json` 是展示层 item（驼峰枚举），不是 response_item 原样；`thread_history_1.sqlite` 1 GB 且含 `-wal/-shm`，务必只读打开（`file:...?mode=ro`），不要复制整库。
11. **`world_state` / `tool_search_*` / `token_usage_record` 对"对话"无用**，转换时忽略以免噪声。
12. 子代理 thread 的 `thread_source="subagent"` 与 `source.subagent` 必看，否则会把代理树拍平成普通对话。

---

## 10. 复现命令

```bash
# 类型统计
python3 - <<'PY'
import glob,json,collections
c=collections.Counter()
for f in glob.glob('~/.codex/sessions/**/*.jsonl', recursive=True):
    for line in open(f, errors='replace'):
        try: o=json.loads(line)
        except: continue
        p=o.get('payload') or {}
        c[(o['type'], p.get('type'))]+=1
print(c)
PY

# 权威源一致性：rollout 中 item_completed 总数 == thread_items 行数
sqlite3 "file:$HOME/.codex/thread_history_1.sqlite?mode=ro" "select count(*) from thread_items;"

# 最新 thread 的 rollout 路径
sqlite3 "file:$HOME/.codex/state_5.sqlite?mode=ro" \
  "select id, rollout_path from threads order by updated_at desc limit 1;"
```

样本（均 ≤50 KB，已在 `samples/codex/`）：
- `rollout-small-full.jsonl` —— 一个完整小 rollout（49 KB / 28 行：session_meta + 1 个 task_started + turn_context + 4 条 message + 2 组 function_call/output + 2 条 reasoning + 1 个 turn_aborted，未截断）。
- `rollout-compacted-window-excerpt.jsonl` —— 含 `compacted` 行的窗口（ordinal 195–215，每行截断至 2000 字符）。
- `rollout-header-only.jsonl` —— 只有 `session_meta` 的"空 rollout"边界样本（8.3 KB，thread 建立但无事件，转换时应跳过）。
- `session_index-excerpt.jsonl` / `history-excerpt.jsonl` —— 前 20/15 行（截断）。
- `sqlite-schemas.sql` —— state_5 与 thread_history_1 的 `.schema` 全量。
- `thread_items-excerpt.json` / `thread_turns-excerpt.json` —— 单个 thread 的投影行（item_json 截断至 400 字符）。
