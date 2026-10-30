# 批 5 样本侦察：新 Harness 原生 fixtures 与 adapter 方案（27→31+ 去重覆盖）

> 版本：v0.1（2026-10-30）｜执行：batch3-recon（shared task-22）
> 上游：[`docs/coverage-ledger.md`](../coverage-ledger.md)（v0.2：协议覆盖 27/40、分层 37/40、真实 19/40）、[`docs/formats/batch3-fixtures.md`](batch3-fixtures.md)、[`batch4-fixtures.md`](batch4-fixtures.md)、[`docs/harness-catalog.md`](../harness-catalog.md)
> 素材：**本批新建 [`samples/batch5/`](../../samples/batch5/)**（102 文件 / ≈600 KB；来源/commit/license/派生标注见 [`samples/batch5/SOURCE.md`](../../samples/batch5/SOURCE.md)）
> 任务边界：只做样本侦察 + schema 判定 + Reader/Writer/测试计划；不写转换代码；不改其他成员文件与用户数据。

> **证据等级（沿用前批）**：**FIXTURE**（上游/派生 fixture 可支撑原生 schema，仅格式级）/ **FIXTURE-LOW**（部分证据/reader-only）/ **FIXTURE-CONSTRUCTED**（按源码 schema 自构，必须标注）/ **BLOCKED**（无样本或无许可）。**本轮不新增 NATIVE**；`samples/batch5/SOURCE.md` 中标注 derived 的文件不得当上游原文件引用。

---

## 0. 结论摘要（TL;DR）

### 0.1 批 5 收获

| 类别 | Harness | 证据等级 | 新增去重？ |
|---|---|---|---|
| **新 Harness（有原生 fixture/派生 fixture）** | **Kiro CLI**（Codeg 测试中捕获的 2.24.1 真实记录） | FIXTURE | ✅ +1 |
| | **CodeBuddy**（Codeg 测试记录的两种原生 JSONL 形态） | FIXTURE | ✅ +1 |
| | **OpenHands**（Harbor RFC §V 真实轨迹样例，62.8 KB） | FIXTURE（真实轨迹示例） | ✅ +1 |
| | **FX**（agent-sessions `fx/schema4`：events.jsonl schema 3 记录 18 条 + session.json schema 4） | FIXTURE（补齐批 4 缺口） | ✅ +1（此前为扩展计划） |
| | **Mistral Vibe**（无上游 fixture；按仓库源码布局构造） | FIXTURE-CONSTRUCTED | ✅ +1（若计构造层） |
| | **Mini-SWE-agent**（Harbor 样例，`mini-swe-agent-1`） | FIXTURE（外部框架，catalog 未收录） | ⚠ 需 Lead 决定是否计入 |
| **现有 harness 证据升级** | Cline（messages 补全）、OpenCode（v2 SQLite data blob + storage_v2 树）、Antigravity（原生 SQLite + protobuf payload）、OpenClaw（SQLite schema）、Kimi/Gemini/Qwen/Devin/Hermes/Droid/Copilot/Cursor/Grok/Claude/Codex（schema_drift/large/subagent） | 见 §2 | ❌（不新增去重） |
| **无样本/阻塞** | Crush（FSL license，仅记录 schema）、Goose、Continue、Roo、Zed、Junie、Windsurf、Kilo、Codebuff、Warp/Replit | CANDIDATE/BLOCKED | ❌ |

### 0.2 覆盖增量（与账本 v0.2 对齐）

| 口径 | v0.2 当前 | 批 5 后（可实施） | 说明 |
|---|---|---|---|
| **协议覆盖（去重 Harness）** | **27/40** | **31/40**（FIXTURE：Kiro/CodeBuddy/OpenHands/FX） | 若接受 Vibe 构造 → 32；若再接受 Mini-SWE → 33 |
| 分层账本累计 | 37/40 | 41（37+4）→ 超 40 上限 | 分层口径已接近上限，后续应改用去重口径汇报 |
| 真实会话覆盖（REAL） | 19/40 | **19（不变）** | OpenHands 样例是真实轨迹示例，但**不是用户真实会话上传**，不计 REAL；其余全 FIXTURE |
| 批 5 目标 | ≥30（最好 33-35） | **31 可达；32-33 视构造/外部分支** | 33-35 需批 6（Goose/Continue/Crush/Roo/Zed 中 2-4 个构造化） |

**结论**：批 5 可把去重覆盖从 **27 推到 31（4 个新 FIXTURE，全部有实样）**；Vibe/Mini-SWE 是把 31 推到 32-33 的备选（构造/需确认）；**31 已达标**（≥30）。

### 0.3 批 5 建议先做哪 8 个（按难度/价值）

1. **FX**（★★，补齐批 4 缺口，fixture 完整：18 事件 9 种 kind）
2. **Cline（messages 补齐）**（★★，3 个会话 messages 文件，双文件 writer 立即完整）
3. **Kiro CLI**（★★，新增去重 +1；JSONL 事件 + metadata 双文件，schema 清晰）
4. **OpenHands**（★★，新增去重 +1；真实轨迹 JSON 数组，结构简单）
5. **CodeBuddy**（★★☆，新增去重 +1；两种记录形态需兼容）
6. **OpenCode v2**（★★☆，from CONSTRUCTED→FIXTURE；storage_v2 树 + sqlite data blob）
7. **Mistral Vibe**（★，FIXTURE-CONSTRUCTED +1；JSONL 布局简单）
8. **Antigravity（原生 SQLite/protobuf）**（★★★，reader 需移植 Codeg 的 prost 子集；fixture 有 8 步原生 DB）

> 备选第 9/10：OpenClaw SQLite（schema 有但无 .db 文件 → CONSTRUCTED DB）、Mini-SWE-agent（外部框架，需 Lead 确认是否计入 40）。

---

## 1. 本批样本清单（实测）

> 全部文件已用 `python3` 实测解析（JSON/JSONL/SQLite 只读）；单文件最大 72,139 B（`kimi/assistant_tools.jsonl`），总 102 文件 ≈600 KB，均 ≤ 限额。

| # | Harness/对象 | 本批样本（samples/batch5/…） | 大小 | 实测 | S 类 | 判定 |
|---|---|---|---|---|---|---|
| 1 | **Kiro CLI** | `kiro/sessions/7787f985-…/session.jsonl` + `session.json` | 1,597+1,158 B | 8 行 / 8 条事件 / 6 kinds；metadata 7 键、2 个 user turn | S1（captured-trimmed，derived） | **FIXTURE** |
| 2 | **CodeBuddy** | `codebuddy/item-format.jsonl`、`tool-format.jsonl` | 926+1,168 B | 4+4 行；2 种记录形态 | S1（derived） | **FIXTURE** |
| 3 | **OpenHands** | `harbor/openhands_trajectory.json` | 62,847 B | 7 条轨迹记录；source `[agent,user,user,environment,agent,agent,agent]`；5 条带 action、2 条带 observation | S1（真实样例） | **FIXTURE** |
| 4 | **FX** | `agent-sessions/fx/schema4/{events.jsonl,session.json,recovery.json,tool-results/*.txt}` | 6,706+384+1,311+129 B | 18 事件 / 9 种 kind；session schema 4 | S1 | **FIXTURE**（补齐批 4） |
| 5 | **Mistral Vibe** | `vibe/constructed-session/{meta.json,messages.jsonl}` | 346+522 B | 4 条消息（user/assistant/tool/assistant） | S3 构造 | **FIXTURE-CONSTRUCTED** |
| 6 | Mini-SWE-agent | `harbor/mini-swe-agent-trajectory.json` | 15,173 B | dict：`info/messages/trajectory_format=mini-swe-agent-1`；8 条 messages | S1 | FIXTURE（外部框架） |
| 7 | Cline（升级） | `agent-sessions/cline/{cli_tool,desktop_continued,desktop_tool}/*.messages.json` | 1,820+2,041+4,072 B | 3 会话 = 3/5/7 条消息；schema v1 | S1 | FIXTURE（原 CONSTRUCTED） |
| 8 | OpenCode（升级） | `agent-sessions/opencode/sqlite_v2/**`（11 个 data blob）、`storage_v2/**`、`storage_legacy/**` | 合计 ≈15 KB | `session_v2` 行 35 字段；11 种 message data 类型；storage_v2/legacy 多文件树 | S1 | FIXTURE（原 CONSTRUCTED） |
| 9 | OpenClaw（升级） | `agent-sessions/openclaw/sqlite/openclaw-agent.sql` | 18,468 B | 7 张表（`schema_meta/session_windows/transcript_events/…`）；注释称 schema 逐字复制真实库（schema_version 25） | S1（schema） | FIXTURE（SQLite 变体） |
| 10 | Antigravity（升级） | `codeg/antigravity/agy-fixture-001.db` + `.meta`；`agent-sessions/antigravity/{cli_small.jsonl,small.md}` | 8,192+50+4,346+224 B | SQLite `steps(idx,step_payload)` 8 行；payload 为 `gemini_coder.Step` protobuf；meta `{cwd,mode_id}` | S1（原生 SQLite） | FIXTURE（reader 可做；writer 仍难） |
| 11 | Cursor IDE（检查） | `agent-sessions/cursor-ide/test-store.db` | 20,480 B | 表 `blobs`(0 行)/`meta`(1 行 `0`) → **空 store** | S3 | **BLOCKED**（无 cursorDiskKV 内容） |
| 12 | Kimi（升级） | `agent-sessions/kimi/{assistant_tools.jsonl,assistant_tools.state.json,state.json,subagent_agent-0.jsonl}` | 72,139+731+448+10,015 B | assistant_tools 200 行事件流；subagent 10 KB | S1 | FIXTURE（批 4 加固） |
| 13 | Gemini（升级） | `agent-sessions/gemini/{jsonl_v040.jsonl,schema_drift.json,large.json}` | 1,368+396+3,153 B | 新增 **JSONL 存储变体**（首行 session 头 `kind/lastUpdated/projectHash/sessionId/startTime`） | S1 | FIXTURE（schema drift） |
| 14 | Qwen（升级） | `agent-sessions/qwen/019f…{001,004,005,006,007}.jsonl`、`system_telemetry.jsonl` | 2.8-6.6 KB / 4,971 B | 0007 文件 13 行：system/user/assistant/tool_result 混合（此前仅 user 单行） | S1 | FIXTURE（批 3 加固） |
| 15 | Devin/Hermes/Droid/Copilot/Cursor/Grok/Claude/Codex（升级） | 各自 `schema_drift`/`large`/`subagent` 文件（见目录） | 各 <4 KB | 版本漂移/大样本/子代理覆盖 | S1 | FIXTURE（回归加固） |
| 16 | Crush（仅 schema 事实） | （**未复制文件**：FSL license） | — | SQL migrations：`sessions(id,parent_session_id,title,message_count,prompt_tokens,completion_tokens,cost,updated_at,created_at)`、`messages(id,session_id,role,parts JSON,model,created_at,updated_at,finished_at)` | S3 | **FIXTURE-CONSTRUCTED 候选**（license 需 Lead 审视） |

---

## 2. 逐 Harness 方案

### 2.1 Kiro CLI（新增去重 +1｜FIXTURE｜难度 ★★）

**原生存储事实**（证据：Codeg `src-tauri/src/parsers/kiro.rs` 模块文档 + 测试，Apache-2.0；catalog **B** 路径表一致）：`<KIRO_HOME>/sessions/cli/`（默认 `~/.kiro`）下**每会话两个文件**：
- `<id>.jsonl`：append-only 事件日志，每行 `{"version":"v1","kind":…,"data":…}`；2.24.1 的 kind：`Prompt`、`AssistantMessage`、`ToolResults`、`Compaction`、`Clear`、`ResetTo`、`CancelledPrompt`。
- `<id>.json`：会话 metadata（每轮结束时重写）：`cwd`、`title`、`created_at/updated_at`、`session_state.conversation_metadata.user_turn_metadatas[]`（每轮 `message_ids`/`end_timestamp`）、`session_state.rts_model_state`（model/context window）。

**fixture 实测**（derived：记录来自 Codeg 测试中「captured from a real kiro-cli acp 2.24.1 session，signatures/digests trimmed」）：

| 元素 | 实测 | IR 用途 |
|---|---|---|
| `session.jsonl` | 8 行；kinds=`[Prompt,AssistantMessage,ToolResults,AssistantMessage,Prompt,AssistantMessage,Clear,Compaction]` | 事件流 |
| `Prompt.data` | `message_id,content[{kind:"text",data}],meta.timestamp`（**唯一带时间戳的 kind**，epoch 秒） | user_message + ts |
| `AssistantMessage.data` | `message_id,content[{kind:"thinking",data{text,redactedContent,modelId,toolsDigest}},{kind:"text",data},{kind:"toolUse",data{toolUseId,name,input}}]` | assistant + reasoning + tool-call |
| `ToolResults.data` | `message_id,content[{kind:"toolResult",data{toolUseId,content[{kind:"text",data}],status:"error"/"ok"}}]` | tool_result（is_error=status!=ok） |
| `Compaction.data` | `summary,strategy{messages_pairs_to_exclude},messages_snapshot` | compaction |
| `Clear`/`ResetTo`/`CancelledPrompt` | 边界事件 | turn_abort/分段 |
| `session.json` | 7 键：session_id/cwd/created_at/updated_at/title/session_created_reason/session_state；`user_turn_metadatas` 2 条 | cwd/标题/时间/turn 边界/usage |

**截断示例（Prompt + ToolResults，各 ≤300 字符）**

```json
{"version":"v1","kind":"Prompt","data":{"message_id":"p1","content":[{"kind":"text","data":"Run the shell command `echo kiro-probe` and then reply DONE."}],"meta":{"timestamp":1790509942}}}
```
```json
{"version":"v1","kind":"ToolResults","data":{"message_id":"r1","content":[{"kind":"toolResult","data":{"toolUseId":"tooluse_1","content":[{"kind":"text","data":"User denied tool execution"}],"status":"error"}}],"results":{}}}
```

**Reader 映射规则**：按行序处理；`Prompt`→user_message（text；`meta.timestamp`→ts）；`AssistantMessage` content：`thinking`→reasoning（`redactedContent` 保留 extra）、`text`→text、`toolUse`→tool-call（id=toolUseId，`__tool_use_purpose` 进 extra）；`ToolResults`→tool_result（配对 toolUseId）；`Compaction`→compaction；`Clear/ResetTo`→分段/`turn_abort`；metadata 提供 cwd/title/created/updated、model（`rts_model_state.model_info.model_id`）、turn 结束时间（AssistantMessage 无时间戳时用 `end_timestamp` 回填并标 `lossy:kiro:timestamp-from-metadata`）。
**Writer 最小可行**：`<out>/sessions/cli/<sid>.jsonl` + `<sid>.json`（metadata 含 session_state 骨架）；格式级（B5-F3 自往返）；不写 `<sid>.lock/.history/<sid>/`。
**测试计划**：KIR-F1 8 行解析、kinds 序列断言；KIR-F2 tool-call=1（`toolUseId=tooluse_1`、name=shell、input.command）与 tool_result=1 配对、is_error=true；KIR-F3 metadata→cwd=`/tmp/kprobe/cwd`、created/updated、user_turns=2、title 空→派生；KIR-F4 writer 自往返。证据 **FIXTURE**。

### 2.2 CodeBuddy（新增去重 +1｜FIXTURE｜难度 ★★☆）

**原生存储事实**（证据：Codeg `parsers/codebuddy.rs` 模块文档 + 测试；catalog **B**：`~/.codebuddy/projects/`，`CODEBUDDY_CONFIG_DIR`）：目录布局同 Claude Code（`projects/<encoded-cwd>/<session-id>.jsonl`），但记录是 **OpenAI Agents-SDK item 记录 schema**（不是 Claude schema）。Codeg 测试覆盖**两种形态**：
- **item-format**：`type ∈ message/reasoning/ai-title`；`content[{type:"input_text"|"output_text",text}]`；`providerData.requestModelName/model/rawUsage{prompt_tokens,completion_tokens,prompt_tokens_details.cached_tokens}`。
- **tool/function-format**：`type ∈ message/function_call/function_call_result/session-meta/file-history-snapshot/summary`；`function_call{callId,name,arguments(str)}`；`function_call_result{callId,status,output{type,text}}`；`parentId` 链。

**fixture 实测**：`item-format.jsonl` 4 行（message/ai-title/reasoning/message），user 文本 `你会做什么`、title `能力询问`、reasoning `thinking about it`、assistant `我是 CodeBuddy`、model `GLM-5.1`、usage prompt 24049/completion 267/cached 12800；`tool-format.jsonl` 4 行（message/function_call/function_call_result/message），tool `Read`（`callId=call_1`，arguments JSON 字符串 `{"file_path":…}`）与 result `# demo` 配对。

**截断示例（tool-format 的 function_call + result，各 ≤300 字符）**

```json
{"type":"function_call","timestamp":1781821845000,"cwd":"/Users/demo/app","sessionId":"sess-tool","name":"Read","callId":"call_1","arguments":"{\"file_path\":\"/Users/demo/app/README.md\"}","providerData":{"messageId":"m1"}}
```
```json
{"type":"function_call_result","timestamp":1781821846000,"cwd":"/Users/demo/app","sessionId":"sess-tool","name":"Read","callId":"call_1","status":"completed","output":{"type":"text","text":"# demo"},"providerData":{"messageId":"m1"}}
```

**Reader 映射规则**：逐行按 `type` 分派；`message` role user/assistant→对应消息（content input_text/output_text→text）；`reasoning.rawContent[].reasoning_text`→reasoning；`ai-title.aiTitle`→title；`function_call`→tool-call（`callId`、`arguments` 字符串→JSON 对象，失败 `{"_raw":…}`）；`function_call_result`→tool_result（call_id=callId，`status!="completed"`→is_error）；`session-meta`（`meta` 键值）→extra；`summary.summary`→title 兜底；`file-history-snapshot` 忽略进 extra；usage 从 `providerData.rawUsage` 累加（cached→cache_read）。PTC 模式：`function_call.name=="REPL"` 时 `arguments.code` 为一个 tool card（Codeg 语义），IR 侧保留为 tool-call 的 input（不展开内部调用）。
**Writer 最小可行**：`<out>/projects/<enc-cwd>/<sid>.jsonl`，item-format 为主（message/reasoning/ai-title/function_call/function_call_result），格式级。
**测试计划**：CB-F1 item 4 行、角色序 user→assistant、title/model/usage（24049/267/12800）；CB-F2 tool 4 行、tool-call=1/result=1 配对、arguments 解析出 file_path；CB-F3 PTC 模式 `REPL` 记录（derived 样本未含，需构造）标 extra；CB-F4 writer 自往返。证据 **FIXTURE**。

### 2.3 OpenHands（新增去重 +1｜FIXTURE，真实轨迹示例｜难度 ★★）

**原生存储事实**（证据：Harbor RFC 0001 §V 真实轨迹样例 `rfcs/0001-trajectory-format/openhands_trajectory.json`，Apache-2.0；catalog **H**）：OpenHands 轨迹是**顶层 JSON 数组**，每条记录含 `id/timestamp/source/message/action?/args?/observation?/cause?/content?/extras?`。

**fixture 实测**：7 条记录；`source` 序列 `[agent,user,user,environment,agent,agent,agent]`；5 条带 `action`、2 条带 `observation`；keys=`[id,timestamp,source,message,action,args]`（environment 记录另有 `observation/content/cause/extras`）。

**截断示例（user action + environment observation，各 ≤300 字符）**

```json
{"id":1,"timestamp":"2025-10-10T06:10:15.159489","source":"user","message":"Create a file called hello.txt with \"Hello, world!\" as the content.\n","action":"message","args":{"content":"Create a file called hello.txt with \"Hello, world!\" as the content.\n","file_urls":[]}}
```
```json
{"id":4,"timestamp":"2025-10-10T06:10:15.203046","source":"environment","message":"Added workspace context","cause":2,"observation":"recall","content":"Added workspace context","extras":{"recall_type":"workspace_context"}}
```

**Reader 映射规则**：`source=="user"` 且 `action=="message"`→user_message；`source=="agent"`：`action=="message"`→assistant text，`action` 为工具类（`run`/`execute_bash`/`str_replace_editor` 等）→tool-call（call_id 用记录 `id`）；`source=="environment"`：`observation`（`run`/`recall`/`edit`…）→对应 tool_result（配对 `cause` 指向的 action id），`message/content` 为结果文本；`source=="agent"` 的 system prompt（id=0）→system_message（默认丢）；时间戳 ISO→ms；`extras`→extra。
**Writer 最小可行**：`<out>/<sid>/trajectory.json`（数组，user/agent/environment 记录；action+observation 配对）；格式级。
**测试计划**：OH-F1 7 条记录、source 序列、5 action/2 observation；OH-F2 action/observation 按 `cause` 配对（1 组 run + 1 组 recall）；OH-F3 文本精确（含 hello world 任务/系统 prompt）；OH-F4 writer 自往返。证据 **FIXTURE**（真实轨迹示例；不冒充用户真实会话）。

### 2.4 FX（新增去重 +1；补齐批 4 缺口｜FIXTURE｜难度 ★★）

**原生存储事实**（agent-sessions `fx/schema4`，MIT；catalog 附录 A1 **E**）：`~/.fx/sessions/<id>/{session.json,events.jsonl,recovery.json,tool-results/}`；0.0.8+ 事件日志 schema 3/4。批 4 只有 metadata 缺 events；本批补齐。
**fixture 实测**：`session.json` schema 4（id/origin_workspace_root/workspace_root/created_at_ms/updated_at_ms/conversation_language/provider/model/effort/fast_mode/title/subagent_child）；`events.jsonl` 18 条 `{schema_version:3,seq,timestamp_ms,event:{kind…}}`，kind 序列 `user,assistant,tool_call,tool_result,assistant,turn_completed,user,tool_call,tool_result,steering,tool_call,tool_result,assistant,turn_completed,context_checkpoint,user,tool_call,interrupted`；`tool-results/*.txt` 3 个工具原始输出；`recovery.json` 1,311 B。
**截断示例（user 事件 + tool_call，≤300 字符）**

```json
{"schema_version":3,"seq":1,"timestamp_ms":1789000020000,"event":{"user":{"text":"List the files in this project","images":[{"id":1,"path":"…/screenshot.png","media_type":"image/png","snapshot_path":"images/0001-screenshot.png"}]}}}
```
```json
{"schema_version":3,"seq":3,"timestamp_ms":1789000020000,"event":{"tool_call":{"call_id":"call_fx4_glob_001","tool_name":"glob_files","arguments_json":"{\"pattern\":\"**/*\"}","argument_integrity":"valid","provenance":"fx_local"}}}
```
**Reader/Writer**：按 `seq` 排序；`user`→user_message（images→image/lossy）；`assistant`→assistant_message；`tool_call`→tool-call（`call_id`，arguments_json 字符串→对象）；`tool_result`→tool_result（call_id 配对，结果文本可从 `tool-results/` 文件补齐）；`steering`/`context_checkpoint`/`interrupted`/`turn_completed`→extra/turn_abort；writer：`session.json`+`events.jsonl`（+tool-results 可选）；格式级。
**测试计划**：FX-F1 18 事件/9 kind 序列；FX-F2 tool_call=4、tool_result=3（第 4 个 call 被 interrupted 截断→占位 result + lossy）；FX-F3 session.json schema 4 元数据（title/cwd/model/provider）；FX-F4 tool-results 文件与 call_id 关联；FX-F5 writer 自往返。证据 **FIXTURE**。

### 2.5 Mistral Vibe（新增去重 +1 若接受构造｜FIXTURE-CONSTRUCTED｜难度 ★）

**原生存储事实**（证据：mistral-vibe 源码 `tests/stubs/historical_session.py` + `vibe/core/types.py::LLMMessage`，Apache-2.0；catalog 附录 A2 **C**）：session log 目录 `<save_dir>/<session_prefix>_<YYYYmmdd_HHMMSS>_<sid8>/`，含 `meta.json`（session_id/parent_session_id/start_time/end_time/git_commit/git_branch/username/environment.working_directory/config.active_model）与 `messages.jsonl`（每行 `LLMMessage`：role/content/images/injected/reasoning_content/reasoning_payloads/tool_calls/name/tool_call_id/tool_result/message_id/user_display_content/input_text/resources/manual_shell/context_boundary）。
**本批样本**：`vibe/constructed-session/`（**constructed，非上游 fixture**）：4 条消息 roles=[user,assistant,tool,assistant]。
**Reader/Writer**：meta→cwd/model/时间；messages→IR（content 字符串或 blocks；tool_calls→tool-call、tool_call_id→tool_result、reasoning_content→reasoning）；writer `<out>/logs/session/<prefix>_<ts>_<sid8>/{meta.json,messages.jsonl}`；格式级。
**测试计划**：VIBE-F1 constructed 4 条消息角色序/配对（1 tool call/result）；VIBE-F2 meta→cwd/时间/model；VIBE-F3 writer 自往返；证据 **FIXTURE-CONSTRUCTED**。

### 2.6 现有 harness 证据升级（不新增去重）

| Harness | 本批新增证据 | 升级内容 | 证据等级 |
|---|---|---|---|
| **Cline** | 3 个 `*.messages.json`（3/5/7 条消息，schema v1：`version/sessionId/updated_at/origin/system_prompt/messages[]`；message 含 `id/role/ts/content/modelInfo/metrics`） | 批 4 只有 metadata+缺 messages 的 CONSTRUCTED → **FIXTURE**：Reader 可完整还原消息/工具/usage（metrics.inputTokens 等）；Writer 双文件完整 | FIXTURE（升） |
| **OpenCode** | `sqlite_v2/session_message/*.json`（11 种 data 类型：user/assistant/idle/idle-failed/assistant-failed/compaction/shell/model-switched/system/synthetic/synthetic-job）+ `session_v2`（35 字段：tokens_input/output/reasoning、time_created/updated、directory/title/model/version…）+ `storage_v2`/`storage_legacy` 树 | CONSTRUCTED → **FIXTURE**：v2 SQLite data blob schema 与 legacy 树均有实样；writer 仍建议 legacy 树 + 标注 experimental | FIXTURE（升） |
| **Antigravity** | 原生 SQLite `agy-fixture-001.db`：`steps(idx,step_payload)` 8 行，payload = `gemini_coder.Step` protobuf（Codeg parser 有 prost 子集 tag 定义：`Step{1:idx,2:…}`，payload 前 16 字节 `2a080a060880e2cfaa069a0115…`）；`.meta {cwd,mode_id}`；另有 `cli_small.jsonl` 转录 + `small.md` artifact | FIXTURE-LOW（JSONL 转录）→ **FIXTURE（reader 可做）**：Python reader 可用 protobuf 库按 Codeg tag 子集解码 `step_payload`；writer 仍难（需构造 protobuf/或只写 JSONL 非原生） | FIXTURE（reader） |
| **OpenClaw** | `openclaw-agent.sql`（7 表：schema_meta/session_windows/transcript_events/transcript_event_identities/session_transcript_active_events/session_transcript_archives/session_transcript_cold_archives；注释称逐字复制真实库 schema v25） | 批 4 已有 JSONL 树 → 增 SQLite 变体（`events` 含 zstd 压缩事件列）；需构造 golden DB（无 .db 文件） | FIXTURE（JSONL）+ CONSTRUCTED（SQLite） |
| **Cursor IDE** | `cursor-ide/test-store.db`（20 KB） | 实测 `blobs` 0 行 / `meta` 1 行 → **空 store，BLOCKED**（无 cursorDiskKV 内容）；Cursor CLI 已覆盖 | BLOCKED |
| Kimi | `assistant_tools.jsonl` 200 行（含 20+ 激活工具/assistant 工具卡）+ `assistant_tools.state.json`/`state.json`/`subagent_agent-0.jsonl` | 批 4 加固（工具卡/子代理/状态） | FIXTURE（加固） |
| Gemini | `jsonl_v040.jsonl`（JSONL 存储变体，首行 session 头）+ `schema_drift.json` + `large.json` | 批 3 单 JSON → 增 JSONL 变体（0.4.0 存储）+ drift 覆盖 | FIXTURE（加固） |
| Qwen | 5 个新会话（0007：13 行含 system/user/assistant/tool_result）+ `system_telemetry.jsonl`（8 行） | 批 3 仅 1 行 user → 真实记录形态更完整 | FIXTURE（加固） |
| Devin/Hermes/Droid/Copilot/Cursor/Grok/Claude/Codex | 各自 `schema_drift`/`large`/`subagent` | 版本漂移/大样本/子代理回归覆盖 | FIXTURE（加固） |
| Mini-SWE-agent | `mini-swe-agent-trajectory.json`（`trajectory_format=mini-swe-agent-1`；`info{exit_status,submission,model_stats,mini_version,config}` + `messages` 8 条） | 外部 agent 框架轨迹格式（catalog 未收录）；可作第 12 个候选，是否计入 40 由 Lead 定 | FIXTURE（可选） |

### 2.7 缺失/阻塞（批 5 不实施）

| Harness | 检查结果 | 判定/补采建议 |
|---|---|---|
| **Crush** | 源码有 SQLite migrations（sessions/messages 表结构，见 §1#16）；**License=FSL v1.1（非 MIT/Apache）** | **CANDIDATE（构造）**：表结构足够构造 golden DB（`FIXTURE-CONSTRUCTED`），但**不 vendor 源文件**，需 Lead 审视许可 |
| **Goose** | 2,529 文件扫描无 session fixture；源码定义存储 | CANDIDATE：需真实安装采样或按源码构造 |
| **Continue** | 3,058 文件扫描无 session fixture | CANDIDATE：同上 |
| **Roo Code** | 3,022 文件扫描无会话历史 fixture；Cline 族 | CANDIDATE：Cline 族扩展，需真实 store 样本 |
| **Zed** | 4,389 文件扫描无 agent 会话 fixture；SQLite 线程库 | CANDIDATE：需真实 DB 或源码构造（工作量高） |
| **Kilo Code** | 51 MB 源码：fixtures 为 UI/provider recordings | BLOCKED：Cline 族真实 store 需安装采集 |
| **Junie / Windsurf** | 无公开 session fixture/仓库 | BLOCKED：需安装采集 |
| **Warp / Replit** | 纯云端 | 仅 ATIF 导出，不排期 |
| **Codebuff** | 有 session-state 类型定义，无落盘 fixture | CANDIDATE（源码级构造，未验证） |

---

## 3. 批 5 可实施清单与难度排序

| 顺位 | Harness | 难度 | 新增去重 | Reader 关键点 | Writer 最小可行 | 证据上限 |
|---|---|---|---|---|---|---|
| 1 | **FX** | ★★ | +1（补齐） | seq 事件 + tool-results 文件 | session.json+events.jsonl | FIXTURE |
| 2 | **Cline（messages）** | ★★ | —（已 COLLECTED） | 双文件：metadata+messages | 双文件 | FIXTURE（升） |
| 3 | **Kiro CLI** | ★★ | +1 | JSONL 事件 + metadata 双文件 | `<id>.jsonl`+`<id>.json` | FIXTURE |
| 4 | **OpenHands** | ★★ | +1 | trajectory 数组 + cause 配对 | trajectory.json | FIXTURE |
| 5 | **CodeBuddy** | ★★☆ | +1 | 两种记录形态 + function_call 配对 | `projects/<enc>/<sid>.jsonl` | FIXTURE |
| 6 | **OpenCode v2** | ★★☆ | —（已 COLLECTED） | storage_v2 树/SQLite data blob | legacy 树（experimental） | FIXTURE（升） |
| 7 | **Mistral Vibe** | ★ | +1 | meta+messages.jsonl | 同布局 | FIXTURE-CONSTRUCTED |
| 8 | **Antigravity（原生）** | ★★★ | —（批 4 已有） | SQLite+protobuf（移植 Codeg tag 子集） | 暂不写（writer BLOCKED） | FIXTURE（reader） |
| 9 | OpenClaw SQLite | ★★☆ | — | SQL schema → 构造 golden DB | JSONL 仍为主 | CONSTRUCTED（DB） |
| 10 | Mini-SWE-agent | ★★ | ⚠ 待定 | info+messages 数组 | trajectory JSON | FIXTURE（可选） |
| 11 | Kimi/Gemini/Qwen/Devin/… drift | ★ | — | 现有 reader 加 variant/allowlist | 现有 writer 回归 | FIXTURE（加固） |
| 12 | Crush（构造） | ★★★ | +1 | SQLite schema（FSL 需审视） | 构造 golden DB | CONSTRUCTED（候选） |

**预计新增去重**：27 → **31**（顺位 1/3/4/5 = FX/Kiro/OpenHands/CodeBuddy 四个有真实/派生 fixture 的新 Harness；Cline/OpenCode/Antigravity/OpenClaw 是既有标签升级）；接受 Vibe → **32**；接受 Mini-SWE → **33**；批 6 再补 2-4 个构造候选（Goose/Continue/Crush/Roo/Zed）可到 35-37。

---

## 4. 测试计划汇总（精确断言来自本批实测）

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| KIR-F1..F4 | `kiro/…/session.jsonl`+`session.json` | 8 行/kinds 序列/tool 配对/user_turns=2/metadata cwd/时间；writer 自往返 | FIXTURE |
| CB-F1..F4 | `codebuddy/item-format.jsonl`、`tool-format.jsonl` | 4+4 行/角色序/title=`能力询问`/usage 24049-267-12800/tool `Read`+`call_1` 配对；writer 自往返 | FIXTURE |
| OH-F1..F4 | `harbor/openhands_trajectory.json` | 7 记录、source 序列、5 action/2 observation、cause 配对、文本断言；writer 自往返 | FIXTURE |
| FX-F1..F5 | `agent-sessions/fx/schema4/**` | 18 事件/9 kind/tool_call=4 与 result=3（1 个 interrupted 占位）/session schema 4；writer 自往返 | FIXTURE |
| VIBE-F1..F3 | `vibe/constructed-session/**` | 4 消息角色序/1 组 tool 配对/meta→cwd 时间；writer 自往返 | FIXTURE-CONSTRUCTED |
| CLN-F1..F3 | cline 3 个 messages | 3/5/7 条消息数、role 序、metrics usage、双文件组装；writer 自往返 | FIXTURE（升） |
| OPC-F1..F3 | opencode sqlite_v2 + storage_v2 | 11 种 data 类型、session 35 字段、storage 树组装、tokens/time；legacy 树 writer 自往返 | FIXTURE（升） |
| ANT-F1..F2 | codeg antigravity db | `steps` 8 行、protobuf 解码可出 step 文本/工具（按 Codeg tag 子集）、meta cwd；writer N/A | FIXTURE（reader） |
| GEM/QWEN/KIMI-F1 | 升级样本 | JSONL 变体/多记录会话/assistant 工具卡可解析不崩溃 | FIXTURE（加固） |

---

## 5. 有损项、风险与限制

**有损项**：Kiro（metadata 才有 turn 结束时间；`Clear/ResetTo` 边界；`redactedContent` 二进制保留 extra；`session_created_reason` extra）；CodeBuddy（PTC `REPL` 内部调用不展开；两种形态互转；`file-history-snapshot` 丢弃）；OpenHands（`environment` 记录语义取决于 action 类型；system prompt 默认丢）；FX（`interrupted` 的工具调用占位；images 只留路径；steering/context_checkpoint 进 extra）；Vibe（构造样本，字段集合以源码为据需真实样本验证）；Cline（error/partial 行折叠；images）；OpenCode（SQLite v2 列名以 fixture data blob 反推，非完整 DDL）。

**风险/限制**：
1. **许可证**：Crush 为 **FSL（非 MIT/Apache）**，本批已**不复制**其文件，仅记录 schema 事实；后续如需 vendor 须 Lead 审视。
2. **派生样本**：Kiro/CodeBuddy/Vibe 三类为 derived/constructed（见 SOURCE.md），报告与矩阵中必须标注，不得写成「上游原文件」。
3. **真实会话**：OpenHands 样例是真实的**轨迹示例**（Harbor RFC），但不是用户上传会话，**REAL 覆盖不增加**；其余仍是合成/裁剪。
4. **Antigravity**：reader 依赖 Codeg 的 `gemini_coder.Step` protobuf 子集 tag（Apache-2.0），Python 侧需 protobuf 解码；writer 仍 BLOCKED（无 protobuf 编码器）。
5. **无 SQLite 真实样本**：除 Antigravity 8KB 原生 DB 与 Cursor 空 store 外，OpenCode/OpenClaw/Hermes/Devin 仍只能构造 golden DB（`FIXTURE-CONSTRUCTED`，列名部分未核实）。

---

## 6. 与覆盖账本的对应关系（批 5 增量）

| 口径 | v0.2（批 4 定稿） | 批 5 可实施后 | 说明 |
|---|---|---|---|
| 协议覆盖（去重） | 27/40 | **31/40** | +Kiro/+CodeBuddy/+OpenHands/+FX；接受 Vibe→32；Mini-SWE→33 |
| 分层账本 | 37/40 | 41（超上限） | 分层口径已达 40 附近，**后续只报去重口径** |
| 真实会话覆盖（REAL） | 19/40 | 19（不变） | 批 5 无真实用户会话上传 |
| FIXTURE 级新 Harness | — | 4（Kiro/CodeBuddy/OpenHands/FX）+1 构造（Vibe） | 全部 FIXTURE/ CONSTRUCTED，不升 NATIVE |

**批 6 建议**（追 33-35）：Crush/Goose/Continue/Roo/Zed 中选 2-4 个做源码级构造（`FIXTURE-CONSTRUCTED`）+ 补真实样本；Junie/Windsurf/Kilo 需安装采集。

---

## 7. 索引与复现

| 内容 | 路径 |
|---|---|
| 本批样本与来源/commit/license/派生标注 | [`samples/batch5/SOURCE.md`](../../samples/batch5/SOURCE.md) |
| 样本解析（本文件所有「实测」） | `cd samples/batch5 && python3 -`（json.loads / sqlite3 只读；见各节断言） |
| 批 5 实施任务生成的构造样本（非本侦察） | `samples/batch5/constructed/**`（由批 5 adapter 实施任务生成；本文件不据此计数） |
| 前批 fixtures 与分类 | [`samples/batch2/public-fixtures/SOURCE.md`](../../samples/batch2/public-fixtures/SOURCE.md)、[`docs/formats/batch3-fixtures.md`](batch3-fixtures.md)、[`batch4-fixtures.md`](batch4-fixtures.md) |
| 覆盖账本（批 5 数字待刷新） | [`docs/coverage-ledger.md`](../coverage-ledger.md)（v0.2；批 5 定稿后升 v0.3） |
