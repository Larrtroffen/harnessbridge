# Claude Code 会话格式与 CLI 恢复机制逆向规格（供 5 路互转 / ATIF→Claude Code 导入实现）

- 被测对象：本机 Claude Code CLI **2.1.308**（`/opt/homebrew/bin/claude` → `/opt/homebrew/Caskroom/claude-code/2.1.308/claude`）
- transcript 写入版本：**2.1.285**（大/小两个会话）与 **2.1.295**（桌面端会话）
- 数据根：`~/.claude/`（`CLAUDE_CONFIG_DIR` 可整体改根）；全局 app 状态：`~/.claude.json`
- 本机样本量：**3 个主 transcript、4984 行**（另 3 个子代理 transcript）；扫描快照 2026-10-30 02:40
- 方法：只读解析 + 隔离环境（`HOME`/`CLAUDE_CONFIG_DIR` 指向 `/tmp`、伪造 API key、未提交 prompt）实测 CLI 发现/恢复；**未发真实模型请求**
- 官方文档：[Sessions](https://code.claude.com/docs/en/sessions) · [.claude directory](https://code.claude.com/docs/en/claude-directory) · [CLI reference](https://code.claude.com/docs/en/cli-reference) · [Env vars](https://code.claude.com/docs/en/env-vars) · [Agent SDK session storage](https://code.claude.com/docs/en/agent-sdk/session-storage)

> 与 Qoder 的对照见 §11（两者同源，Qoder 是 2.1 早期格式的衍生；本机 CC 2.1.285 已比 Qoder 多出 8 种记录类型，并**用 `last-prompt.leafUuid` 取代了 Qoder 的 `active-leaf` 分支日志**）。

---

## 1. 文件定位与目录布局

### 1.1 主 transcript

```
~/.claude/projects/<project-slug>/<session-uuid>.jsonl          # 会话正文（append-only JSONL）
~/.claude/projects/<project-slug>/<session-uuid>/               # 该会话的附属数据
├── subagents/agent-<agentType>-<agentId>.jsonl  + .meta.json   # 子代理（sidechain）transcript
├── tool-results/<id>.txt                                       # 大工具输出落盘（toolUseResult.persistedOutputPath）
├── mcp-tasks/                                                  # 运行中 MCP 任务状态（本机未出现）
└── custom-title.json / auto-mode-classifier-error.txt          # 会话级附属文件
```

- `<session-uuid>` = 会话 id = 文件名去 `.jsonl` = 行内 `sessionId`；**必须是合法 UUID**（`--session-id` 校验实测：`Error: Invalid session ID. Must be a valid UUID.`）。
- 本机：`-Users-larr`（1 会话）、`-Users-larr-Downloads`（1 会话）、`-Users-larr-Research-Assistant--1014-------`（1 会话，78 MB）。
- 官方说明（[claude-directory](https://code.claude.com/docs/en/claude-directory)）：
  - 同目录下 `<session>.orphaned-<timestamp>-<suffix>.jsonl` / `<session>.jsonl.superseded-<timestamp>` 是被弃置/覆盖的旧 transcript，**不出现在 session picker**；
  - `subagents/` 与主 transcript 同格式；`tool-results/` 存大输出与 MCP 图片；
  - `cleanupPeriodDays`（默认 30 天，最小 1）到期自动删除 transcript。

### 1.2 project-slug 编码（官方 + 实测一致）

```
project-slug = cwd 中每个非字母数字字符 → '-'      # 例：~/Downloads → -Users-larr-Downloads
```
- 依据官方文档原文：“`<project>` is your working directory path with every character other than letters and digits replaced by `-`, such as `-Users-you-my-project`”。
- **用 cwd 的真实路径**（realpath）计算：实测把文件放在 `-tmp-cc-test-work`（cwd=`/tmp/...` 的字面值）时 `--resume` 报 not-found；放到 `-private-tmp-cc-test-work`（`/private/tmp/...` 的真实路径）后成功。macOS 上 `/tmp`→`/private/tmp` 这类符号链接是常见坑。
- 可用 `CLAUDE_CONFIG_DIR=<dir> CLAUDE_CODE_PROJECT_DIR_NAME=<name> claude` 强制指定 project 目录名（官方 env-vars 文档，v2.1.234+）——导入工具若想固定目录名可用它。
- 一个会话的 `cwd` 记录可能随会话中途变化（本机 c81 会话出现过 4 个 cwd 子目录），但 project-slug 固定取会话起始工作目录。

### 1.3 `~/.claude/` 其他目录（官方语义）

| 路径 | 内容 | 是否与对话相关 |
|---|---|---|
| `projects/<slug>/<sid>.jsonl` | 会话正文 | **是（唯一权威）** |
| `projects/<slug>/<sid>/subagents/` | 子代理 transcript | 可选 |
| `projects/<slug>/<sid>/tool-results/` | 落盘的大工具输出 | 结果正文可能被截断到 `tool-results/<id>.txt` |
| `projects/<slug>/memory/` | auto memory（跨会话记忆 md） | 否 |
| `history.jsonl` | 提示词历史（↑ 召回 / Ctrl+R / `!` 补全）；字段 `display,pastedContents,timestamp(epoch ms),project,sessionId` | 否（可还原用户输入历史） |
| `file-history/<sid>/<hash>@vN` | checkpoint 文件快照（编辑前内容），供 rewind/恢复 | 否 |
| `sessions/` | **每个运行中会话一个小文件**，用于并发/崩溃检测；退出即删 | 运行时状态，不是 transcript |
| `session-env/<sid>/` | 每会话环境元数据 | 否 |
| `tasks/session-<id>/`、`teams/session-<id>/` | 会话级任务/团队状态 | 可选 |
| `plans/<slug>.md` | plan mode 产出的计划文件 | 可选 |
| `shell-snapshots/`、`backups/`、`cache/`、`telemetry/`、`plugins/` | 运行辅助 | 否 |
| `~/.claude.json` | 全局 app 状态：`projects{cwd→{hasTrustDialogAccepted,lastSessionId,lastCost,lastModelUsage,…}}`、`customApiKeyResponses`、onboarding/迁移标记 | **不是 session 索引**（见 §9） |

---

## 2. 写入模型与时序

1. **append-only JSONL**，一行一个记录对象；会话恢复后继续追加到同一文件。
2. **assistant 按 content block 拆行**：一条模型响应写成 N 行，每行 `message.content` **通常恰含 1 个 block**（本机 1190/1191 行；有 1 行含 2 个 block 的例外，见 §11-1），共享同一 `message.id`，`apiBlockIndex` 给出块序号（0-based）；每行都带完整 `message`（含 `usage`/`model`/`stop_reason`）。本机：1191 条 assistant 行 → **437 个逻辑消息**（`message.id` 去重；每消息 1–5 块，3 块最常见）。
3. **每条记录都携带会话状态元数据**，并在**每轮开始时重写一遍**（这是文件行数膨胀的主因，也是转换器必须过滤的对象）：
   ```
   last-prompt  mode  permission-mode  atis-latch  [ai-title] [agent-name]  attachment×N  user(prompt)  attachment×N
   assistant(thinking) assistant(text) assistant(tool_use)…   attachment  user(tool_result)  attachment …
   …  cost-state（会话结束时一条）
   ```
   本机大会话：`last-prompt` 244 条、`mode` 243、`permission-mode` 243、`atis-latch` 243、`ai-title` 242、`agent-name` 219——全部是状态重写，不是对话。
4. **时间戳**：消息类记录全部为 **ISO 8601 UTC 毫秒字符串**（本机 3409 条 ISO，0 条 epoch ms 记录级时间戳）。例外：`cost-state.startTime`、`history.jsonl.timestamp` 是 epoch ms；attachment 内容里的 `<task-notification>` 等文本内嵌时间无关。
5. 读取方需容错：会话运行中文件持续增长，最后一行可能不完整（本机快照 4984 行 0 解析失败，转换器仍应跳过坏行）。

---

## 3. 记录类型总表（本机 3 会话 / 4984 行实测，Claude Code 2.1.285/2.1.295）

| type | 行数 | 作用 | 进对话？ |
|---|---:|---|---|
| `user` | 604 | 人类 prompt（字符串）/ tool_result / 注入文本 / 图片 | **部分** |
| `assistant` | 1191 | 模型响应（每行 1 block） | **是**（按 `message.id` 合并） |
| `attachment` | 1545 | 上下文注入（hook 输出、token 提醒、skill 清单…），部分带 `rendered/renderedRole` 供 UI 渲染 | 否 |
| `last-prompt` | 276 | 最近一条用户输入 + **当前分支末端 `leafUuid`** | 否（分支判定/标题） |
| `ai-title` | 242 | AI 生成的会话标题（重写） | 否（标题来源） |
| `custom-title` | 30 | 用户命名的会话标题 | 否（标题来源） |
| `agent-name` | 248 | 会话显示名/agent 名（resume 名称句柄） | 否（标题来源） |
| `mode` | 245 | 会话模式（`normal`） | 否 |
| `permission-mode` | 245 | 权限模式（`bypassPermissions`/`plan`…） | 否（可还原 turn 权限） |
| `atis-latch` | 274 | 内部状态（`atis:""`） | 否 |
| `queue-operation` | 22 | 输入队列事件：`enqueue`/`dequeue`/`remove`（含排队 prompt、任务通知、`reason:absorbed_mid_turn`） | 否（排队用户输入可还原） |
| `file-history-snapshot` | 12 | 文件快照备份登记 | 否 |
| `file-history-delta` | 20 | 单文件备份增量（`trackingPath`/`backup`） | 否 |
| `system` | 27 | 子类型：`stop_hook_summary`/`aws`/`api_error`/`compact_boundary`/`turn_duration`/`away_summary` | 部分（压缩边界） |
| `cost-state` | 3 | 会话累计成本/时长/模型用量（会话结束写 1 条） | 否 |

> **没有 `summary` 记录**（2.1.285+）；会话摘要/标题由 `ai-title`/`custom-title` 承担；压缩信息在 `system/compact_boundary` + `user/isCompactSummary`。
> 状态类记录（attachment/last-prompt/mode/permission-mode/atis-latch/ai-title/agent-name/cost-state/file-history-*）合计约 3075 行，占 62%——转换器必须先按类型过滤。

---

## 4. 字段表

### 4.1 公共字段（`user`/`assistant`/`attachment`/`system`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 记录类型 |
| `uuid` | string | 树节点 id（`last-prompt.leafUuid` 即指向某条记录的 uuid） |
| `parentUuid` | string\|null | 树父节点；会话首条/压缩边界后为 `null` |
| `isSidechain` | bool | 主 transcript **全部 false**；`subagents/*.jsonl` **全部 true** |
| `timestamp` | ISO 字符串 | UTC 毫秒 |
| `cwd` / `sessionId` / `version` / `gitBranch` | string | 当前 cwd / 会话 id / CC 版本 / git 分支（本机 `main`、`HEAD`） |
| `userType` | string | `external` |
| `entrypoint` | string | `cli` 或 `claude-desktop-3p`（桌面端） |
| `session_id` | string | 与 `sessionId` 重复，**所有同时出现的记录都相等**（本机 0 不一致） |
| `slug` | string | plan-mode 的 plan 文件名 slug（如 `fluttering-watching-marshmallow`），与 project-slug 无关 |
| 渲染提示（attachment 特有） | — | `rendered`（渲染用 content 数组）、`renderedRole`（`system`/`user`）、`renderedBesideToolResult`、`renderedInHumanTurn` |

### 4.2 `user` 行

| 子类 | 判定 | 关键字段 | 本机量 |
|---|---|---|---|
| 人类输入 | `message.content` 字符串（或 text block）+ `origin.kind=="human"`（或 `promptSource`） | `promptId`、`origin:{kind:human}`、`promptSource:"typed"|"sdk"`、`turnOrigin:"human"`、`turnPosition:{promptIndex,turnIndex}`、`permissionMode` | 91 字符串 + 3 text block（human 总 ~12 条，其余为注入） |
| tool_result | `message.content[0].type=="tool_result"` | `tool_use_id`、`content`（str 或 `[{type:image,source:{type:base64,media_type,data}}]`）、`is_error`（可选）；同行 `sourceToolAssistantUUID` + `toolUseResult` | 510 |
| 注入文本 | `isMeta:true`、`isCompactSummary:true`、或内容为系统提示 | `isMeta`（75，全部同时 `turnCompanion:true`）、`isCompactSummary`（1）、`isVisibleInTranscriptOnly`（1） | 75+1 |
| 图片 | content 含 `{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"..."}}`（**内联 base64，不是 URL**） | `imagePasteIds` | 1 条消息（1 image block） |
| 权限/拒绝 | 同行 `permissionDecision`/`classifierBoundary`/`toolDenialKind` | — | 53/32/9 |

### 4.3 `assistant` 行

| 字段 | 说明 |
|---|---|
| `message.id` | 逻辑消息 id（**合并键**）；`msg_...` |
| `message.model` | 本机：`claude-opus-5-5`（1058 行）、`claude-haiku-5-5`（131）、`<synthetic>`（2，错误占位） |
| `message.content` | 通常单元素（本机 1190/1191 行），偶发 2 个 block（如 `thinking`+`tool_use`，桌面端 2.1.295）。逐块遍历：`{type:"thinking",thinking,signature}`（367）/ `{type:"text",text,citations?}`（315）/ `{type:"tool_use",id,name,input}`（510） |
| `message.stop_reason` / `stop_sequence` / `stop_details` | 每行都带；tool_use 调用时 `stop_reason:"tool_use"` |
| `message.usage` | **每条 assistant 行都有**。字段：`input_tokens,cache_creation_input_tokens,cache_read_input_tokens,output_tokens,output_tokens_details{thinking_tokens},server_tool_use{web_search_requests,web_fetch_requests},service_tier,cache_creation{ephemeral_1h_input_tokens,ephemeral_5m_input_tokens},inference_geo,iterations,speed,fallback_credit`。样例：`{"input_tokens":9703,"cache_creation_input_tokens":110400,"cache_read_input_tokens":0,"output_tokens":543,…}` |
| `message.context_management` / `diagnostics` / `container` / `input_transformations` | 可选诊断字段（本机部分行为 null/缺失，转换可丢弃） |
| `apiBlockIndex` | 该行 block 在消息内的序号（0..N，本机 1058 行有） |
| `effort` / `perTurnEffort` | 推理强度（本机均 `high`） |
| `requestedModel` | 请求模型（131 行，桌面端会话） |
| `thinkingDurationMs` | thinking 耗时（42 行） |
| `truncatedAfterOutput` / `isApiErrorMessage` / `apiErrorStatus` / `error` | 异常行标记（本机 2 条 API 错误） |

### 4.4 `system` 子类型

| subtype | 关键字段 | 说明 |
|---|---|---|
| `compact_boundary` | `content:"Conversation compacted"`, `compactMetadata:{trigger,preTokens,postTokens,cumulativeDroppedTokens,durationMs,preservedSegment{headUuid,anchorUuid,tailUuid},preservedMessages{anchorUuid,uuids[]}}`，`parentUuid:null`，`logicalParentUuid:<压缩前末端>` | 压缩分割事件 |
| `stop_hook_summary` | `hookCount,hookInfos[{command,toolUseID,durationMs}],hookErrors,preventedContinuation,stopReason,hasOutput,toolUseID` | Stop hook 汇总 |
| `api_error` | `error,retryInMs,retryAttempt,maxRetries,source` | API 重试 |
| `turn_duration` | `durationMs,messageCount` | 回合耗时 |
| `away_summary` | `content`（自然语言 recap） | 离开后回归摘要 |

### 4.5 状态/元数据行

```json
{"type":"last-prompt","lastPrompt":"帮我整理一下我的下载文件夹","leafUuid":"05ec8e11-…","sessionId":"2222d085-…"}
{"type":"mode","mode":"normal","sessionId":"…"}
{"type":"permission-mode","permissionMode":"bypassPermissions","sessionId":"…"}
{"type":"atis-latch","atis":"","sessionId":"…"}
{"type":"ai-title","aiTitle":"2026年报告HTML端到端制作","sessionId":"…"}
{"type":"custom-title","customTitle":"帮我整理一下我的下载文件夹","sessionId":"…"}
{"type":"agent-name","agentName":"digital-government-report-2026","sessionId":"…"}
{"type":"queue-operation","operation":"enqueue","timestamp":"2026-10-15T11:58:16.298Z","sessionId":"…","content":"注意文字要有辨识度，现在文字和背景颜色太过贴近了。"}
{"type":"file-history-snapshot","messageId":"<user行uuid>","isSnapshotUpdate":false,"snapshot":{"messageId":"…","trackedFileBackups":{},"timestamp":"…"}}
{"type":"file-history-delta","messageId":"…","snapshotMessageId":"…","trackingPath":"/tmp/organize_downloads.sh","backup":{"backupFileName":null,"version":1,"backupTime":"…","realParentDir":"/private/tmp"},"timestamp":"…"}
{"type":"cost-state","sessionId":"…","totalCostUSD":1.6875,"totalAPIDuration":2380566,"totalToolDuration":23605,"totalLinesAdded":676,"totalLinesRemoved":0,"totalDuration":71224900,"startTime":1791963924301,"modelUsage":{"claude-haiku-5-5":{"inputTokens":17107,"outputTokens":183418,"thinkingTokens":85796,"costUSD":1.68755995}},"hasUnknownModelCost":false}
```

### 4.6 子代理 transcript（`subagents/agent-*.jsonl`）

- 记录类型只有 `user` / `assistant` / `attachment`（本机 3 个文件：119/605/374 行），全部 `isSidechain:true`。
- 额外字段：`agentId`（如 `acover-agent-823a5693d317eda2`）、`promptId`、`slug`；首条 user 是 `<teammate-message teammate_id="team-lead" summary="…">` 形式的任务 prompt。
- 同目录 `agent-*.meta.json`：`{"agentType":"cover-agent","description":"…","name":"cover-agent","spawnDepth":0,"requestShape":"background","requestNonInteractive":true,"model":"apikey-fan-claude/claude-opus-5-5[1m]","taskKind":"in_process_teammate","teamName":"session-c81f99ae","color":"blue","permissionMode":"bypassPermissions"}`
- 主 transcript 里 `Agent` tool_use 的结果 `toolUseResult`：`{"status":"teammate_spawned","prompt":"…"}`（含内部提示 “never quote…”）；`ListAgents` 结果含 `listing` 文本。

---

## 5. 截断示例（均 ≤400 字符，来自真实样本）

**(a) 人类 user prompt（字符串 content）**
```json
{"parentUuid":"4c28793d-…","isSidechain":false,"promptId":"b1fa4b15-…","type":"user","message":{"role":"user","content":"帮我整理一下我的下载文件夹"},"uuid":"a095a866-…","timestamp":"2026-10-14T07:45:24.612Z","permissionMode":"auto","origin":{"kind":"human"},"promptSource":"sdk","turnOrigin":"human","turnPosition":{"promptIndex":1,"turnIndex":1},"userType":"external","entrypoint":"claude-desktop-3p","cwd":"~/Downloads","sessionId":"2222d085-…","version":"2.1.295","gitBranch":"HEAD"}
```

**(b) assistant thinking block（一行一块，带 usage/apiBlockIndex）**
```json
{"parentUuid":"59c61f37-…","isSidechain":false,"message":{"content":[{"type":"thinking","thinking":"…","signature":"CAQSngYKEAgR…"}],"id":"msg_011Cg1l1lvzq…","model":"claude-haiku-5-5","role":"assistant","stop_details":null,"stop_reason":"tool_use","stop_sequence":null,"type":"message","usage":{"input_tokens":9703,"cache_creation_input_tokens":110400,"cache_read_input_tokens":0,"output_tokens":543,"output_tokens_details":{"thinking_tokens":111},"service_tier":"standard","speed":"standard"}},"type":"assistant","uuid":"…","timestamp":"…","apiBlockIndex":0,"effort":"high","perTurnEffort":"high","cwd":"~/Downloads","sessionId":"…","version":"2.1.295"}
```

**(c) assistant tool_use / text block**
```json
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_010mw5Lb2ZUMiQL8kkqpUZBT","name":"Bash","input":{"command":"ls -la ~/Downloads | head","description":"List Downloads"}}],"id":"msg_x","model":"claude-opus-5-5","role":"assistant","stop_reason":"tool_use"},"uuid":"…","parentUuid":"…","apiBlockIndex":2,"cwd":"~/Downloads","sessionId":"…"}
{"type":"assistant","message":{"content":[{"type":"text","text":"我先看一下下载目录的整体结构。","citations":[]}],"id":"msg_y","model":"claude-opus-5-5","role":"assistant","stop_reason":"end_turn"},"uuid":"…"}
```

**(d) user tool_result + 结构化 `toolUseResult`**
```json
{"type":"user","uuid":"…","timestamp":"…","message":{"role":"user","content":[{"tool_use_id":"toolu_010mw5Lb2ZUMiQL8kkqpUZBT","type":"tool_result","content":"total 5612816\ndrwx------@ 110 larr  staff …"}]},"sourceToolAssistantUUID":"0cc11701-…","toolUseResult":{"stdout":"total 5612816\n…","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false},"parentUuid":"0cc11701-…","sessionId":"…"}
```
> Edit 的 `toolUseResult`：`{"filePath":"…","oldString":"…","newString":"…","originalFile":"…","structuredPatch":[…],"userModified":false}`；Write：`{"type":"create","filePath":"…","content":"…"}`；Read 图片：`{"type":"image","file":{"base64":"/9j/4AAQ…"}}`。

**(e) 图片附件（内联 base64，非 URL）**
```json
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"图表风格能不能多样一点？…[Image #1]"},{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"/9j/4AAQSkZJRgABAQAAAQABAAD…"}}]},"imagePasteIds":[1],"uuid":"…","parentUuid":"…","sessionId":"…"}
```

**(f) 压缩边界 + 压缩摘要**（`samples/claude/04-*`）
```json
{"parentUuid":null,"logicalParentUuid":"0f04f2be-…","isSidechain":false,"type":"system","subtype":"compact_boundary","content":"Conversation compacted","level":"info","compactMetadata":{"trigger":"auto","preTokens":970191,"postTokens":8355,"cumulativeDroppedTokens":961836,"durationMs":100449,"preservedSegment":{"headUuid":"…","anchorUuid":"…","tailUuid":"0f04f2be-…"}},"timestamp":"…","sessionId":"c81f99ae-…"}
{"parentUuid":"4565e377-…","isSidechain":false,"promptId":"e80ba464-…","type":"user","message":{"role":"user","content":"This session is being continued from a previous conversation that ran out of context.\n\nThe summary below covers the earlier portion…"},"isVisibleInTranscriptOnly":true,"isCompactSummary":true,"uuid":"…","timestamp":"…","sessionId":"c81f99ae-…"}
```

**(g) attachment 示例（hook_success / total_tokens_reminder，带渲染提示）**
```json
{"type":"attachment","attachment":{"type":"hook_success","hookName":"SessionStart:startup","toolUseID":"e110679a-…","hookEvent":"SessionStart","content":"","stdout":"{}\n","stderr":"","exitCode":0,"command":"if [ -z \"${HOME-}\" ]…"},"uuid":"…","parentUuid":null,"isSidechain":false,"timestamp":"2026-10-14T07:45:24.5Z","cwd":"~/Downloads","sessionId":"2222d085-…"}
{"type":"attachment","rendered":"[{\"content\":\"<system-reminder>\\n<total_tokens>15000000 tokens left</total_tokens>\\n</system-reminder>\"}]","renderedRole":"system","attachment":{"type":"total_tokens_reminder","text":"…"},"uuid":"…","sessionId":"…"}
```
> 本机 attachment 类型分布：`hook_success` 1027、`total_tokens_reminder` 432、`environment` 25、`edited_text_file` 8、`queued_command` 7、`prompt_snapshot` 7、`date` 5、`model` 4、`agent_listing_delta` 4、`session_context` 4、`remote_session_change` 4、`skill_listing` 3、`auto_mode` 3、`silent_turn_reminder` 3、`compact_file_reference` 2、`plan_mode`/`plan_mode_exit`/`plan_file_reference`/`file`/`thinking_drop` 各 1~3。

**(h) 状态记录：last-prompt / ai-title / agent-name / mode**
```json
{"type":"last-prompt","lastPrompt":"继续","leafUuid":"1d3f3972-…","sessionId":"b59c58e1-…"}
{"type":"ai-title","aiTitle":"2026年报告HTML端到端制作","sessionId":"c81f99ae-…"}
{"type":"agent-name","agentName":"digital-government-report-2026","sessionId":"c81f99ae-…"}
{"type":"mode","mode":"normal","sessionId":"c81f99ae-…"}
{"type":"permission-mode","permissionMode":"plan","sessionId":"c81f99ae-…"}
```

**(i) queue-operation（排队输入/任务通知）**
```json
{"type":"queue-operation","operation":"enqueue","timestamp":"2026-10-15T15:08:19.965Z","sessionId":"c81f99ae-…","content":"注意文字要有辨识度，现在文字和背景颜色太过贴近了。"}
{"type":"queue-operation","operation":"remove","timestamp":"2026-10-15T15:09:41.048Z","sessionId":"c81f99ae-…","content":"注意文字要有辨识度…","reason":"absorbed_mid_turn","commandUuid":"7593b372-…"}
{"type":"queue-operation","operation":"enqueue","timestamp":"2026-10-15T11:58:16.298Z","sessionId":"…","content":"<task-notification>\n<task-id>b6onnucfj</task-id>\n<tool-use-id>toolu_0146…"}
```

**(j) 错误 assistant 行**
```json
{"type":"assistant","message":{"content":[{"type":"text","text":"API Error: 503 …"}],"id":"…","model":"<synthetic>","stop_reason":"stop_sequence"},"error":"…","isApiErrorMessage":true,"apiErrorStatus":503,"uuid":"…","sessionId":"…"}
```

---

## 6. 工具调用表示

- **调用**：assistant 行 `message.content[0] = {type:"tool_use", id, name, input}`；`id` 形如 `toolu_01…`（Anthropic 风格）。
- **结果**：user 行 `message.content[0] = {type:"tool_result", tool_use_id, content, is_error?}` + 同行 `toolUseResult`（结构化）+ `sourceToolAssistantUUID`（= 携带该 tool_use 的 assistant 行 uuid；本机 510/510 一致）。
- **配对键**：`tool_use.id == tool_result.tool_use_id`；**不要只沿 `parentUuid` 链**——一次 assistant 消息多个 tool_use 时，每个 result 行的 `parentUuid` 指向自己的 tool_use block 行，是链上旁支。
- 本机 `tool_use` 总数 **510**；工具分布：`Bash` 292、`Read` 95、`Edit` 67、`Write` 30、`ListAgents` 19、`Agent` 3、`AskUserQuestion` 2、`EnterPlanMode` 1、`ExitPlanMode` 1。
  - Bash input：`{command, description, timeout?, run_in_background?}`；结果 `toolUseResult` 有 `stdout/stderr/interrupted/isImage/noOutputExpected`（含被后台化时的 `backgroundTaskId`/`timedOutAfterMs`）。
  - Read：`{file_path, offset?, limit?}`；结果文本/图片。
  - Edit：`{file_path, old_string, new_string, replace_all?}`；结果带 `structuredPatch`/`originalFile`。
  - Write：`{file_path, content}`；结果 `{type:"create", filePath, content}`。
  - Agent：`{description, prompt, subagent_type?, run_in_background?, name?}`；结果 `{status:"teammate_spawned"/…, prompt}`；子代理轨迹在 `subagents/`。
  - ListAgents：结果 `{listing:"This session is <name> [id] — … Teammates (N): …"}`。
  - AskUserQuestion：input `{questions:[{question,header,options,multiSelect}]}`；结果 `{questions, answers}`。
  - ExitPlanMode：结果 `{plan:"<plan markdown>"}`（同时写 `~/.claude/plans/<slug>.md`）。

---

## 7. 分支、父子、时间

- 每条 user/assistant/attachment/system 有 `uuid`+`parentUuid`，构成树；主 transcript 线性追加，`/branch`、`--fork-session` 会生成**新的 session 文件**（原文件不动），rewind/编辑可能让同一文件内出现旁支。
- **最终分支判定**：取文件中**最后一条 `last-prompt`**的 `leafUuid`，沿 `parentUuid` 回溯到根即当前活动链（本机 276 条 last-prompt 的 leafUuid 指向：attachment 152、user 字符串 40、assistant tool_use 47、system 3 等——即链上最后一个节点，可能不是消息而是 attachment；转换时按类型过滤即可）。无 last-prompt 时按文件行序处理。
- `system/compact_boundary` 的 `parentUuid:null` + `logicalParentUuid`：压缩后新链从 null 开始，逻辑父链靠 `logicalParentUuid` 连接；`compactMetadata.preservedSegment` 指明保留段（head/anchor/tail uuid）。
- 时间戳：消息记录 ISO 字符串；`cost-state.startTime`、`history.jsonl.timestamp` 为 epoch ms。`timestamp` 缺失的记录（last-prompt/mode/…）用相邻记录近似。

---

## 8. 会话标题 / 命名（供导入时写 title）

| 记录 | 含义 | 是否 resume 句柄 |
|---|---|---|
| `custom-title` | 用户在桌面端/CLI 命名的标题 | 推测是（picker 展示） |
| `ai-title` | 首条 prompt 由 Haiku 类模型生成的标题（`-p` 直跑不生成） | 是（官方：generated title 可作 resume handle） |
| `agent-name` | 会话显示名（`ListAgents` 输出 “This session is digital-government-report-2026” 同值） | 是（`claude --resume <name>`） |
| `last-prompt` | 最后一条用户输入 | 否（picker 展示/兜底标题） |

导入时建议：`title = custom-title ?? ai-title ?? agent-name ?? 首条 human prompt 截断 80 字`。

---

## 9. CLI session 发现 / 恢复机制（ATIF→Claude Code 的关键）

### 9.1 发现与恢复规则（官方文档 + 本机实测）

1. **没有 session 索引文件**。会话发现 = 扫描 `~/.claude/projects/<slug>/*.jsonl` 并解析 JSONL；`~/.claude.json` 只存 app 状态/`lastSessionId`（便利字段），**不是**索引。→ 手写 JSONL 放入正确目录即可被识别。
2. **slug 必须由 cwd 真实路径按 §1.2 规则生成**；放错 slug 目录时 `--resume <id>` 报 `No conversation found`（实测；即使跨项目查找也未命中）。
3. `claude --resume <session-id>`：先查**当前项目目录及其 git worktrees**，再查**本机其他所有项目**；跨项目解析仅在“恰好一个其他项目持有该 id 的 transcript”时生效（官方；手抄重复副本会导致 not-found）。
4. `claude --resume <transcript-path>`：直接加载**任意绝对路径的 .jsonl**（实测 `/tmp/cc-test/minimal-path.jsonl` 成功），适合一次性导入/审阅；是否会写回该路径未验证（加载后文件未被修改）。
5. `claude --continue`（`-c`）：恢复**当前目录**最近一次会话；`-p`/Agent SDK/`/loop` 创建的会话默认不出现在 picker 且被 `-c` 跳过（但可 `--resume <id>`；`claude -p --continue` 会包含 `-p` 会话）。
6. 会话选择器（`claude --resume` 无参 / `/resume`）：默认显示当前 worktree 会话，`Ctrl+W` 扩大到仓库全部 worktree，`Ctrl+A` 扩大到本机所有项目；行内容 = 名称/AI 标题/摘要/首条 prompt + 最近活跃时间 + git 分支 + 文件大小。
7. `-n/--name`、`/rename` 设置会话名；`--fork-session` 恢复时生成新 session id（`/branch` 同理，旧文件不变）。
8. `--session-id <uuid>`：新建会话时指定 id，必须是合法 UUID；与 `--resume/--continue` 同用必须加 `--fork-session`（实测报错）。
9. `claude -p --resume <id> "prompt"`：非交互续跑，适合脚本；会调用模型。
10. 保留期：`cleanupPeriodDays` 默认 30 天、最小 1，到期 transcript 会被清理；导入历史会话时注意（可能被当作旧文件自动删除，需调整设置或刷新 mtime/时间戳）。`*.orphaned-*` / `*.superseded-*` 不出现在 picker。

### 9.2 实测记录（隔离环境，无模型请求）

| # | 实验 | 结果 |
|---|---|---|
| A | 恢复不存在的 id（`-p --resume`） | `No conversation found with session ID: 1111…` |
| B | 复制真实会话到 `CLAUDE_CONFIG_DIR=/tmp/cc-test/config/projects/project/` 后 `--resume b59c58e1-…`（cwd=~） | **成功加载**历史对话 → 无需索引 |
| C | **手写 3 行 JSONL**（user+assistant+last-prompt，新 UUID）放 `projects/<sanitized-realpath-cwd>/<uuid>.jsonl` | **成功加载** → 手写 transcript 可 resume |
| C' | 同一文件放错 slug 目录（`-tmp-cc-test-work`，真实路径是 `/private/tmp/...`） | `No conversation found` → slug 必须匹配 realpath |
| D | `--resume /tmp/cc-test/minimal-path.jsonl`（路径形式） | **成功加载**；加载后文件未被改写 |
| E | `--session-id not-a-uuid` | `Error: Invalid session ID. Must be a valid UUID.` |
| F | `--session-id` + `--resume` 同时 | `Error: --session-id can only be used with --continue or --resume if --fork-session is also specified.` |

恢复副作用：真实 transcript **加载时不被修改**；CLI 向文件追加 4 条状态记录（`atis-latch`/`mode`/`permission-mode`/`cost-state`）；配置目录写入 `.claude.json`、`backups/.claude.json.backup.<epochms>`、`plugins/known_marketplaces.json`、`sessions/`（运行期临时、退出清空）。启动时若 `.claude.json` 未记录工作区信任，会先弹 “Quick safety check: Is this a project you created or one you trust?” 对话框（无 `--bare` 时）；设置了 `ANTHROPIC_API_KEY` 环境变量会先问 “Do you want to use this API key?”（批准记录写入 `customApiKeyResponses.approved`，值为 key 末 20 位）。

### 9.3 写入配方（ATIF → Claude Code，实测最小可行）

```
<CLAUDE_CONFIG_DIR> 或 ~/.claude
└── projects/<slug>/<session-uuid>.jsonl     # slug = realpath(cwd) 非字母数字→'-'
```
每行一个 JSON 对象；最小可行集合（本机实测 B/C）：
1. `user` 行：`type:"user"`、`uuid`、`parentUuid:null`、`promptId`、`message:{role:"user",content:"<文本>"}`、`timestamp`、`sessionId`(= 文件名)、`cwd`、`isSidechain:false`、`userType:"external"`、`entrypoint:"cli"`、`version:"2.1.308"`、`gitBranch:"HEAD"`。
2. `assistant` 行：`type:"assistant"`、`uuid`、`parentUuid:<user uuid>`、`message:{id,type:"message",role:"assistant",model,stop_reason:"end_turn",stop_sequence:null,content:[{type:"text",text:"…"}]}`、`timestamp`、同上公共字段。
3. （建议）`last-prompt` 行：`{"type":"last-prompt","lastPrompt":"…","leafUuid":"<最后一条消息 uuid>","sessionId":"…"}`。
4. 工具调用需要追加 `tool_use` block 行 + 对应 `user/tool_result` 行（`tool_use_id` 配对、`sourceToolAssistantUUID` 指向 tool_use 所在行）。多 block 消息按 1 行 1 block 写，共享 `message.id`，`apiBlockIndex` 递增。
5. 写完即可：`claude --resume <uuid>`（或会话选择器）→ CLI 会追加 `mode/permission-mode/atis-latch/cost-state` 等状态行并正常续聊。
6. **隔离/验收方法**：`HOME=/tmp/cc-home CLAUDE_CONFIG_DIR=/tmp/cc-config` + 预写 `.claude.json`（`hasCompletedOnboarding:true`、`projects[realpath(cwd)].hasTrustDialogAccepted:true`、可选 `customApiKeyResponses.approved:["<key 末20位>"]`）+ 伪造 `ANTHROPIC_API_KEY=sk-ant-api03-fake`、`DISABLE_TELEMETRY=1 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`，然后 `claude --bare --resume <id>`；看到历史对话即通过，**不要输入 prompt**（避免模型请求），Ctrl-C 两次退出。
7. 不要做的事：不要手抄同一 transcript 到两个 project 目录（跨项目解析会 not-found）；不要改 `<slug>` 里的中文/符号编码（无法反推）；不要写 `sessions/`（运行时文件，CLI 自管）；导入后若文件时间戳很旧，注意 `cleanupPeriodDays` 清理。

---

## 10. 映射到通用中间表示（IR）

### 10.1 会话级

| IR | 规则 |
|---|---|
| `session_id` | 文件名去 `.jsonl` = `sessionId` |
| `source` | `"claude-code"`；`project_slug`；`version`（2.1.285/2.1.295）；`entrypoint` |
| `cwd` | 首条带 `cwd` 的记录；中途 cwd 变化记录到 message.metadata |
| `created_at/updated_at` | 首/末条 ISO timestamp → epoch ms |
| `title` | `custom-title` ?? `ai-title` ?? `agent-name` ?? 首条 human prompt 前 80 字 ?? `last-prompt.lastPrompt` |
| `git_branch` | 任一记录 `gitBranch` |
| `model` | 首条 assistant `message.model`（本机主用 `claude-opus-5-5`） |
| `stats` | 行数、逻辑消息数（distinct message.id）、human prompt 数（origin.kind=human）、tool 调用数、token 合计（每行 usage 相加，注意 cache 字段） |
| `cost` | 最后一条 `cost-state`（totalCostUSD/modelUsage/totalDuration） |

### 10.2 消息映射

- **过滤**：只转 `user`/`assistant`。丢弃 `last-prompt`/`mode`/`permission-mode`/`atis-latch`/`ai-title`/`custom-title`/`agent-name`/`cost-state`/`file-history-*`/`queue-operation`/`attachment`。
  - `attachment` 一律不进正文；`queued_command` 若需要可转 user 消息（内容在 `attachment.prompt`，`source_uuid` 与已有 user 行去重）；`hook_success` 等为环境注入。
  - `queue-operation` 的 `enqueue` 若 content 是用户文本且随后没有对应 user 行，可作排队输入（默认丢弃）。
- **assistant 合并**：连续同 `message.id` 的行合并，按 `apiBlockIndex` 排序；`thinking`→reasoning（signature 丢弃）、`text`→assistant text、`tool_use`→tool_call；`usage` 保留到消息级 stats。
- **user 分类**：`tool_result` → role=tool；`isMeta`/`isCompactSummary`/注入文本 → system 或丢弃；其余字符串/text + `origin.kind=human` → 真正 user prompt（`promptId` 保留作回合 id；`turnPosition.promptIndex/turnIndex` 可还原回合序号）。
- **tool 配对**：`tool_use.id` ↔ `tool_result.tool_use_id`；缺失结果（中断/压缩/后台）→ 生成 `status:"missing"` 占位；`toolUseResult` 原样存 metadata（含 `structuredPatch`/`originalFile` 等）。
- **图片**：user content 的 `image.source.type=="base64"` 内联 base64（需解码落盘或保留占位）；`tool_result` 的 content 可能是 `[{type:"image",source:{...base64}}]`；大输出可能只留在 `tool-results/<id>.txt`（`toolUseResult.persistedOutputPath`）。
- **分支**：取最后一条 `last-prompt.leafUuid` 沿父链回溯（§7）；tool_result 旁支按 id 补回。无 last-prompt 时用行序。
- **压缩**：`system/compact_boundary` 映射为 `event:"compaction"`（保留 compactMetadata）；紧随其后的 `user/isCompactSummary` 映射为 `system/summary`（**不能当 user prompt**）；压缩前历史仍在文件中（append-only），按最终分支导入时会被自动去掉重复——若导全量需按 boundary 分段。
- **子代理**：`Agent` tool_use → 可选加载 `subagents/agent-*.jsonl`（`isSidechain:true`、`agentId`）作为 sub_trace；meta.json 补充 agentType/model/name；任务通知类 `queue-operation` 可作后台任务事件。
- **时间**：ISO → epoch ms；回合时间用 human prompt 时间。

### 10.3 可丢弃字段

`apiBlockIndex`（合并后）、`effort`/`perTurnEffort`/`requestedModel`/`thinkingDurationMs`（可留 metadata）、`message.*_details/context_management/diagnostics/container/input_transformations`、`signature`、`citations`、`session_id`（重复）、`slug`、`rendered`/`renderedRole`、`atis`、`hookInfos` 明细、`classifierBoundary`、`permissionDecision`（可留审计）、`lastGracefulShutdown` 等 app 状态。

### 10.4 与 Qoder（同源）的差异清单

| 维度 | Claude Code 2.1.285+ | Qoder 1.1.75 | 转换注意 |
|---|---|---|---|
| 父格式 | 基线 | 2.1 早期衍生 | 大部分语义相同 |
| 记录类型 | 15 种（多 `queue-operation/mode/permission-mode/atis-latch/ai-title/custom-title/agent-name/cost-state/file-history-delta`） | 9 种（多 `active-leaf/runtime-config/workspace-directories/last-prompt/attachment` 但无标题类） | 各自过滤 |
| 分支日志 | `last-prompt.leafUuid`（每轮重写） | `active-leaf` 独立记录 | 取最后一条回溯即可 |
| 标题 | `ai-title`/`custom-title`/`agent-name` | **无**（需从首条 prompt 推导） | CC 导入 Qoder 时丢掉标题字段 |
| assistant 拆行 | 是（1 行 1 block，`apiBlockIndex` 显式） | 是（1 行 1 block，无 apiBlockIndex） | 都必须按 `message.id` 合并 |
| tool 结果 | `toolUseResult` + `sourceToolAssistantUUID`（同 Qoder） | 同 | 同规则 |
| 时间戳 | 全部 ISO 字符串 | 消息 ISO + `active-leaf/runtime-config` epoch ms | — |
| 压缩 | `system/compact_boundary`（含 preservedSegment/preservedMessages）+ user isCompactSummary | `system/compact_boundary` + user isCompactSummary（字段少） | — |
| 图片 | user content 内联 base64 | tool_result/attachment URL 到 OSS（会过期） | 存储策略不同 |
| 子代理 | `<sid>/subagents/agent-*.jsonl` + meta.json | `<sid>/subagents/agent-*.jsonl` + meta.json + task-*.json | 同构 |
| 工具名 | 多 `ListAgents/EnterPlanMode/ExitPlanMode/Agent` 等 | `mcp_call/mcp_list/mcp_get/TaskCreate/TaskUpdate/UpdateGoal/present_visualization` 等 | 两套工具名需映射 |
| 模型 | `claude-opus-5-5`/`claude-haiku-5-5` | 内部 UUID key / custom provider 串 | — |
| 标题/成本 | 有 title/cost-state | 无 cost（有 usage 部分） | — |

---

## 11. 坑（按踩坑概率排序）

1. **assistant 按 block 拆行**：不按 `message.id` 合并会把一条回复拆成 thinking/text/tool_use 多条；`apiBlockIndex` 给顺序。注意**不要假设每行只有 1 个 block**（本机 1190/1191 单块，1 行含 thinking+tool_use 两块）。
2. **tool_result 不在父链上**：多工具时仅沿 `last-prompt.leafUuid` 回溯会丢前 N-1 个结果；必须 `tool_use_id`/`sourceToolAssistantUUID` 配对。
3. **状态记录数量巨大**：本机 1545 attachment + 276 last-prompt + 245 mode + 245 permission-mode + 274 atis-latch + 242 ai-title + 248 agent-name ≈ 3075/4984 行（62%）不是对话；不过滤会严重污染导入。
4. **slug 用真实路径**：`/tmp` → `/private/tmp` 这类 realpath 差异会让 `--resume` not-found（实测）；中文/符号全变 `-` 不可逆。
5. **标题来源多且互相覆盖**：ai-title 每轮重写、custom-title 可能后设、agent-name 是会话名；取优先级见 §8。
6. **压缩 append-only**：压缩前的消息仍在文件里；按行序全导会重复（摘要+原文）。按最终分支或 compact_boundary 分段。
7. **图片是内联 base64**：一条消息可带上 MB 级 base64；转录文件因此巨大（本机 78 MB / 4453 行）。导入需决定解码落盘或占位（别塞回文本）。
8. **大工具输出被落盘**：`tool_result.content` 可能被截断，完整内容在 `tool-results/<id>.txt` 或 `toolUseResult.persistedOutputPath`；丢失会影响保真。
9. **不要复制会话到多个 project 目录**：跨项目 `--resume <id>` 只在唯一匹配时生效，重复副本会 not-found（官方文档）。
10. **清理期**：`cleanupPeriodDays` 默认 30 天会删 transcript；导入历史会话需防被清理（设置、或刷新文件 mtime）。
11. **恢复会追加状态行**：resume 后文件多出 `mode/permission-mode/atis-latch/cost-state` 等行，导入方按类型过滤不要报错；会话文件在恢复时不被重写。
12. **隔离时注意弹窗**：首次用伪造 `ANTHROPIC_API_KEY` 会问是否使用；工作区未信任会弹 Quick safety check；验收脚本可用 `.claude.json` 预置 `hasTrustDialogAccepted`/`customApiKeyResponses.approved` 跳过。
13. **`-p`/SDK 会话隐身**：默认不进 picker 也不被 `-c` 选中，但 `--resume <id>` 可用；`claude -p --continue` 才包含它们。
14. **敏感数据**：transcript 含完整 shell 输出、文件内容、内联图片，可能有 AK/SK/token；导入需脱敏（本机 78MB 会话即含云账号操作输出）。
15. **坏尾行**：会话运行中文件可能正在被追加；逐行 `try/except`。

---

## 12. 复现与验证命令

```bash
# 0) 定位（本机）
ls ~/.claude/projects/*/ | head
find ~/.claude/projects -maxdepth 2 -name '*.jsonl' | wc -l          # 3
du -sh ~/.claude/projects                                             # 105M
claude --version                                                      # 2.1.308

# 1) 参考实现（本仓库，只读）
python3 samples/claude/repro_scan.py stats --root ~/.claude/projects   # 类型/工具/模型/attachment 统计
python3 samples/claude/repro_scan.py list  --root ~/.claude/projects   # sid | slug | 起止时间 | cwd | 标题
python3 samples/claude/repro_scan.py dump ~/.claude/projects/-Users-larr-Research-Assistant--1014-------/c81f99ae-fb79-4c73-89d8-56d8a0ca1e8d.jsonl

# 2) slug 编码校验（官方规则）
python3 - <<'PY'
import json,glob,os,re
for p in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
    slug=os.path.basename(os.path.dirname(p))
    cwd=None
    for l in open(p):
        o=json.loads(l)
        if 'cwd' in o: cwd=o['cwd']; break
    calc=re.sub(r'[^A-Za-z0-9]','-',cwd or '')
    print(p, "slug_ok" if calc==slug else f"MISMATCH {calc} != {slug}")
PY

# 3) 隔离环境 resume 实测（不写 ~/.claude，不发模型请求）
rm -rf /tmp/cc-test && mkdir -p /tmp/cc-test/config/projects/-Users-larr /tmp/cc-test/home
cp ~/.claude/projects/-Users-larr/b59c58e1-17c5-4758-8d69-2a0e98bd8bee.jsonl /tmp/cc-test/config/projects/project/
printf '{"numStartups":1,"hasCompletedOnboarding":true,"projects":{"~":{"hasTrustDialogAccepted":true}}}' \
  > /tmp/cc-test/config/.claude.json
cd ~ && HOME=/tmp/cc-test/home CLAUDE_CONFIG_DIR=/tmp/cc-test/config \
  ANTHROPIC_API_KEY=sk-ant-api03-fake DISABLE_TELEMETRY=1 DISABLE_AUTOUPDATER=1 \
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 NO_COLOR=1 \
  claude --bare --resume b59c58e1-17c5-4758-8d69-2a0e98bd8bee
# 显示历史对话即成功；Ctrl-C 两次退出（全程未提交 prompt）

# 4) 手写 transcript 最小验证
SID=$(uuidgen | tr A-Z a-z); CWD=/tmp/cc-test/work; mkdir -p "/tmp/cc-test/config/projects/$(python3 -c "import re,sys;print(re.sub(r'[^A-Za-z0-9]','-',sys.argv[1]))" "/private$CWD")" 
# 写入 user+assistant+last-prompt 三行后：
cd $CWD && HOME=/tmp/cc-test/home CLAUDE_CONFIG_DIR=/tmp/cc-test/config claude --bare --resume "$SID"

# 5) 官方文档
#   https://code.claude.com/docs/en/sessions
#   https://code.claude.com/docs/en/claude-directory
#   https://code.claude.com/docs/en/cli-reference
#   https://code.claude.com/docs/en/env-vars        (CLAUDE_CONFIG_DIR / CLAUDE_CODE_PROJECT_DIR_NAME)
#   https://code.claude.com/docs/en/agent-sdk/session-storage
```

### 本机实测规模

| 指标 | 值 |
|---|---|
| 主 transcript / 子代理 transcript | 3 / 3 |
| 总行数 / 解析失败行 | 4984 / 0 |
| 最大会话 | `c81f99ae-…` 78 MB、4453 行 |
| 逻辑 assistant 消息（message.id 去重） | 437（1191 行，平均 2.7 block/行） |
| 人类 prompt | ~12（`origin.kind=="human"`；另有 75 条 `isMeta` 注入） |
| tool_use / tool_result | 510 / 510 |
| 含 usage 的 assistant 行 | 1191（100%） |
| 压缩边界 | 1（大会话，`preTokens:970191`） |
| 记录类型 | 15 种（含 7 种纯状态/标题记录） |

样本：`samples/claude/`（截断/脱敏副本 + `README.md` + `repro_scan.py`）。
