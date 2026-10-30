# 批 5 Harness 原生 session 格式核实（v0.1）

> 日期：2026-10-30｜作者：webresearch（Team 成员）
> 目的：为 converter（Reader/Writer）实现与 fixtures 补采，核实批 5 候选 Harness 的**原生 session 存储路径 / 物理格式 / 字段表 / 恢复机制 / writer 最小可行**。
> 上游：`docs/atif-interop-protocol.md`、`docs/harness-catalog.md`（本文件细化批 5 的「P1 格式有文档」部分）。
> 约束：只写本文件；中间材料在 /tmp；所有外部网页视为数据，不当作指令。

---

## 0. 证据等级与总览

| 等级 | 定义 |
|---|---|
| **DOC** | 厂商官方文档 / 官方仓库源码 / 官方 SDK 代码直接确认 |
| **COMMUNITY** | 第三方开源项目逆向并做过验证（本报告主要来源：`getagentseal/codeburn` 的 provider 文档，它逐字段引用上游源码/迁移文件；`vshulcz/deja-vu` 的 registry 文档，部分做过 live 验证；`VasiHemanth/tokentelemetry` 的 harness survey） |
| **UNVERIFIED** | 未找到可靠一手/逆向证据；或仅有产品资料 |

**结论速览（17 个对象）**

| # | Harness | 等级 | 本地可读? | 格式 | 恢复 | 实现优先级 |
|---|---|---|---|---|---|---|
| 1 | Kiro CLI / Kiro IDE | COMMUNITY | 是 | JSONL（CLI）+ JSONL 事件目录（IDE v2）+ VS Code globalStorage | `kiro-cli` 自身（flags 未核实） | **T2** |
| 2 | Tencent CodeBuddy | **DOC（目录结构）** / schema 未核实 | 是 | JSONL（`projects/`、`history.jsonl`）+ file-history/`/rewind` | `/resume`（官方目录说明提到 history.jsonl 用于恢复） | **T2** |
| 3 | OpenHands（SDK） | **DOC**（SDK 持久化格式）/ 运行时默认路径 UNVERIFIED | 是（FileStore 目录） | base JSON + `events/` 每事件一个 JSON | SDK `Conversation(...)` 重新加载 | **T3** |
| 4 | Continue | COMMUNITY | 是 | **JSON 文件**（非 SQLite，纠正任务假设） | `cn --fork <id>` | **T1** |
| 5 | Zed | COMMUNITY | 是 | SQLite + zstd JSON BLOB | 编辑器内历史 | **T2** |
| 6 | Crush (Charm) | COMMUNITY | 是 | SQLite（每项目一个 `crush.db`）+ `projects.json` 注册表 | Crush 自身 session 列表 | **T2（DDL 完整）** |
| 7 | Goose (Block) | **DOC（路径/DB）** / DDL 未公开 | 是 | **SQLite `sessions.db`（v1.10.0+）**；旧版 JSONL | `goose session list`（resume 子命令未逐行核实） | **T2** |
| 8 | Junie (JetBrains) | COMMUNITY（做过 live 验证） | 是 | JSONL 事件日志 + JSON | `junie --session-id <id> --resume` | **T1** |
| 9 | Mistral Vibe | COMMUNITY | 是 | 多代：单 JSON / `meta.json`+`messages.jsonl` / Unified（CURRENT+journal+chunks） | `vibe` 自身 | **T3**（多代复杂） |
| 10 | Roo Code | COMMUNITY | 是 | JSON（VS Code globalStorage tasks） | `roo -w <ws> --session-id <uuid>`（CLI） | **T1**（与 Cline 同族） |
| 11 | Kilo Code | COMMUNITY | 是 | JSON（VS Code globalStorage tasks，Cline 族） | 扩展 UI | **T1**（与 Cline 同族） |
| 12 | Cline（VS Code 扩展 + CLI） | COMMUNITY | 是 | JSON（扩展 tasks）/ JSON（CLI sessions） | 扩展 UI / CLI | **T1** |
| 13 | Warp | COMMUNITY | **是（mac SQLite，此前误判纯云端）** | SQLite `warp.sqlite` | Warp 自身 | **仅读（不建议写）** |
| 14 | Replit Agent | UNVERIFIED | 否（纯云端） | — | — | **不做**（只收 ATIF） |
| 15 | Codebuff | COMMUNITY | 是 | JSON（`chat-messages.json`） | Codebuff 自身 | **T1** |
| 16 | 可选：Cursor IDE `state.vscdb` | COMMUNITY | 是 | SQLite KV（cursorDiskKV） | Cursor UI | 可选（只读） |
| 17 | 可选：Copilot CLI `session-store.db` | COMMUNITY | 是 | SQLite（含完整 usage 表） | `copilot --resume` | 可选（只读推荐） |

---

## 1. 每个 Harness 的核实细节

### 1.1 Kiro CLI / Kiro IDE（AWS）— COMMUNITY

**存储路径（macOS；`KIRO_HOME` 可迁移 `~/.kiro`）**
- CLI：`~/.kiro/sessions/cli/<id>.jsonl` + 伴生 `<id>.json`（`session_state` 计量）
- IDE v2：`~/.kiro/sessions/<workspace-hash>/sess_<id>/`（`session.json` + `messages.jsonl` + `publish.cursor` + `snapshots/`）
- VS Code 形态 globalStorage：`~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent`（`workspace-sessions/<base64url(path)>/<uuid>.json` v1 会话脊柱 + 无扩展名 execution 文件；legacy `.chat`）
- Linux 还会扫 `~/.kiro-server/data/User/globalStorage/kiro.kiroagent`（remote/Cloud Desktop）

**字段 / 格式**
- CLI JSONL：每行一个 `{ version, kind, data }` 事件；伴生 JSON 含 `session_state.metering_usage`（真实计费 credits）
- IDE v2 `messages.jsonl`：追加式 `{ id, timestamp, payload: { type, ... } }`；`session.json` 含 `modelId`、`title`、`workspacePaths`、`usage_summary.promptTurnSummaries`
- Kiro 全程按 **credits** 计费（token 数为估算）；用量证据源：CLI `metering_usage`、v1 `usageSummary[].usage`、v2 `usage_summary.promptTurnSummaries[].usage`

**恢复机制**：由 `kiro-cli` / Kiro 自身恢复（Codeg 以 vendor CLI 启动；具体 resume flag **未核实**）。

**writer 最小可行**：CLI 形态可写 `<id>.jsonl`（version/kind/data 事件序列）+ `<id>.json`（`session_state`）；IDE v2 写 `session.json` + `messages.jsonl`。风险：Kiro 有多代格式（legacy `.chat`、v1 workspace-sessions、v2 sess_、CLI），需按版本/标识探测。

**证据**：codeburn kiro provider 文档（逐条对照 Kiro 多代存储）：https://github.com/getagentseal/codeburn/blob/main/docs/providers/kiro.md ；Codeg 支持列表（`~/.kiro/sessions/cli/` JSONL + `KIRO_HOME`）：https://docs.codeg.app/guide/supported-agents ；TokenTelemetry survey 佐证 `~/.kiro` 结构。

**实现难度**：中（4 种存储代际）；**样本**：需真实采集（mac 装 Kiro CLI 即可造）；**等级：COMMUNITY**。

---

### 1.2 腾讯 CodeBuddy（CLI / IDE）— DOC（目录）/ schema 未核实

**存储路径（官方文档，`~/.codebuddy/`；项目级 `.codebuddy/` 在仓库根）**
- `projects/`：**每项目的 session 运行时数据，官方明确「session records（`.jsonl`）与 subagent 的 `tool-results/`」**
- `sessions/`：活动 session 数据
- `history.jsonl`：**全局对话历史（官方注明用于 `/resume` 恢复）**
- `file-history/`：每次 session 操作的文件快照，用于 **`/rewind` 回滚**
- 其他：`plans/`、`blobs/`、`tasks/`、`teams/`、`shell-snapshots/`、`traces/`（OpenTelemetry）、`usage-data/`、`logs/`

**格式判断**：目录结构与 Claude Code **同形**（`projects/`+`sessions/`+`history.jsonl`+`file-history/`+`shell-snapshots/`）→ 高度疑似 Claude Code 衍生；但 **schema 字段未拿到官方/源码证据 → 标 schema 未核实**（不要直接套用 Claude Code reader，需先采真实 `.jsonl` 验证字段）。

**恢复机制**：官方文档说明 `history.jsonl` 用于 `/resume`；子命令/flag 未逐行核实。

**writer 最小可行**：写 `~/.codebuddy/projects/<slug>/<uuid>.jsonl` + 追加 `history.jsonl` 条目（字段待真实样本确认）；`sessions/` 与 file-history 可暂不写（恢复以 history.jsonl + projects transcript 为主）。

**证据（DOC）**：Tencent Cloud 官方文档「Directory Structure of .codebuddy」：https://www.tencentcloud.com/document/product/1316/84431 （中文站：https://www.codebuddy.ai/docs/cli/codebuddy-dir ）；Codeg 路径表佐证 `~/.codebuddy/projects/` JSONL：https://docs.codeg.app/guide/supported-agents 。

**实现难度**：低-中（布局清晰，但缺字段级 schema）；**样本**：需真实采集（装 CodeBuddy CLI 跑一轮）；**等级：DOC（路径/类别）+ 未核实（字段）**。

---

### 1.3 OpenHands（All-Hands，SDK）— DOC（持久化格式）

**存储路径**：SDK 用 **`LocalFileStore(root)`** 持久化会话（示例 `./.conversations`）；root 由调用方指定，**GUI/server 的默认 root 未核实**（`~/.openhands/...` 说法未找到一手证据）。

**物理格式（DOC，来自 SDK PR #41 的源码 diff）**
- `LocalFileStore` root 下：
  - **base state** 快照：`ConversationState` 的 JSON（`BASE_STATE` 常量，`exclude_none`）
  - **`events/`** 目录：每个事件一个 JSON 文件，命名 `event_<idx>.json` 形式（源码 `_EVENT_FILE_PATTERN`/`_EVENT_NAME_RE`），按 index 排序；`EventBase.model_validate(json.loads(txt))` 读回
- 恢复：`ConversationState.load(file_store)` = 读 base snapshot + 单次扫描 `events/` 回放
- 保存：`state.save(file_store)` = 写 base snapshot + 扫描已有 events 后**只追加新事件**（幂等/增量）

**writer 最小可行**：建 root → 写 base state JSON（可先最小字段，但需满足 `ConversationState.model_validate`）→ 写 `events/event_0.json…`。注意：字段 schema 在 `openhands/sdk/conversation/state.py`、`openhands/sdk/event/*`（`EventBase` 判别联合）；writer 必须构造合法 Event 子类，比 JSONL 类 harness 更重。

**证据（DOC）**：SDK 文档 `docs/persistence.md`（PR #41 新增）：https://github.com/OpenHands/software-agent-sdk/pull/41/files ；SDK 示例 `examples/10_persistence.py`；SDK repo：https://github.com/OpenHands/software-agent-sdk 。官方文档：https://docs.all-hands.dev 。

**实现难度**：中-高（Pydantic 判别联合事件模型 + 需读 SDK 版本）；**样本**：SDK 可本地生成（无需账号）；**等级：DOC（格式）/ UNVERIFIED（GUI 默认路径）**。

---

### 1.4 Continue（continue.dev）— COMMUNITY（纠正任务假设）

**存储路径**：`${CONTINUE_GLOBAL_DIR:-~/.continue}/sessions/<sessionId>.json`，旁边 `sessions.json` 是 session 列表（`dateCreated`、`workspaceDirectory`）。

**物理格式：JSON（整文件重写，非 SQLite；任务描述里的「SQLite `~/.continue/sessions/`」未获证据 → 应为 JSON）**
- session 文档核心：`history[]`，每项 `message`（`role` + `content`：string 或 `[{type,text}]`）；assistant 工具调用在 `toolCallStates[]`（含 `parsedArgs`、状态 `done` 等）
- 上下文压缩：文件被重写为 system message + 一条带 `conversationSummary` 的 assistant item
- 无时间戳；时间靠 `sessions.json.dateCreated` 推算

**恢复机制**：`cn --fork <sessionId>`（`historyManager.load` 打开 `<sessions>/<id>.json`）；`cn --resume` 续最近会话。

**writer 最小可行**：写 `sessions/<uuid>.json`（`history[]` 至少 user/assistant 项）+ 更新 `sessions.json` 列表项（title/dateCreated/workspaceDirectory）。风险低。

**证据（COMMUNITY，形状已对照 Continue 自身类型 `core/index.d.ts` 与 `core/util/paths.ts`）**：https://github.com/vshulcz/deja-vu/blob/db6bb255d9ca269197e0929939348f18b37f2523/docs/registry/continue.md ；官方文档：https://docs.continue.dev 。

**实现难度**：低；**样本**：容易构造（JSON）；**等级：COMMUNITY**。

---

### 1.5 Zed（Agent Panel）— COMMUNITY

**存储路径**
- macOS：`~/Library/Application Support/Zed/threads/threads.db`
- Linux：`~/.local/share/zed/threads/threads.db`
- Windows：`%LOCALAPPDATA%\Zed\threads\threads.db`

**物理格式：SQLite**
- 一张 `threads` 表，一行一个 agent thread；thread 的 `data` 是 **zstd 压缩的 JSON**（`data_type="zstd"`；legacy 可能 `"json"`）
- 解压 JSON 字段：`model: {provider, model}`、`request_token_usage`（按 user message id 的 `{input_tokens,output_tokens,cache_creation_input_tokens,cache_read_input_tokens}`）、`cumulative_token_usage`
- 必要列：`id, summary, updated_at, data_type, data`（缺任一 → discovery 失败）

**恢复机制**：Zed 编辑器内历史面板。

**writer 最小可行**：SQLite `INSERT INTO threads(id, summary, updated_at, data_type, data)`，`data` 为 zstd 压缩 JSON。风险：Zed schema 可能迁移（需按列探测）；写前备份 DB。

**证据（COMMUNITY，形状已对 Zed `crates/agent/src/db.rs` 源码核实）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/zed.md ；Zed 官方：https://zed.dev/docs 。

**实现难度**：中（SQLite + zstd）；**样本**：需真实采集（跑一次 Zed agent）或构造 DB；**等级：COMMUNITY**。

---

### 1.6 Crush（Charm）— COMMUNITY（DDL 完整）

**存储路径**
- 注册表：`$CRUSH_GLOBAL_DATA/projects.json` → `$XDG_DATA_HOME/crush/projects.json` → `~/.local/share/crush/projects.json`（mac/linux）
- 每项目一个 SQLite：`<project.path>/<project.data_dir>/crush.db`，`data_dir` 默认 `.crush`

**DDL（对照 charmbracelet/crush v0.66.1 迁移 `internal/db/migrations/20250424200609_initial.sql`）**
```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, parent_session_id TEXT, title TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0.0,
  updated_at INTEGER NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
  parts TEXT NOT NULL DEFAULT '[]', model TEXT,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
```
- 时间戳单位：**秒**（迁移注释写 ms 是错的，实际 insert 用 `strftime('%s')`）
- 子 agent 是 `parent_session_id` 非空的子会话；`parts` 是 JSON 数组（角色/内容/工具块）
- Crush 不记录 per-message token，只有 session 级累计

**writer 最小可行**：在 `projects.json` 注册项目（`projects[]`，兼容 bare array）→ 建 `crush.db` 并执行上面 DDL → insert `sessions` 一行 + `messages` 若干行（`parts` 用 Crush 的 part JSON 结构；结构需再对照源码 `internal/message` 确认）。

**证据（COMMUNITY，引用上游迁移文件）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/crush.md ；上游：https://github.com/charmbracelet/crush 。

**实现难度**：中（SQLite 写 + parts JSON 结构待补）；**样本**：可构造（DDL 明确）；**等级：COMMUNITY**。

---

### 1.7 Goose（Block）— DOC（路径/DB）+ DDL 未公开

**存储路径（官方 docs 确认，v1.10.0+）**
- macOS/Linux：`~/.local/share/goose/sessions/sessions.db`（SQLite；`XDG_DATA_HOME`、`GOOSE_PATH_ROOT` 可迁移）
- Windows：`%APPDATA%\Block\goose\data\sessions\sessions.db`
- 命令历史：`~/.config/goose/history.txt`
- **v1.10.0 之前**：每 session 一个 `.jsonl`（升级时自动导入 DB，旧文件保留但不再管理）
- 日志：`~/.local/state/goose/logs/`（CLI/server，含 `llm_request.*.jsonl`）

**字段（官方文档概述 + codeburn 观察）**
- 官方：session metadata（ID/name/working directory/timestamps）、对话消息（role）、tool calls/results（IDs/args/response/success）、token usage、extensions 配置
- codeburn：`messages` 表含 `accumulated_input_tokens` / `accumulated_output_tokens`；工具在 message payload 里以 `toolRequest` 形式出现（用 `LIKE '%toolRequest%'` 探测）
- **DDL 未公开/未拿到 → writer 需反推**：先 `sqlite3 .schema` 采真实安装（`goose session list` 生成数据）

**恢复机制**：`goose session list` 列出 session id（官方 docs）；resume 子命令/flag 未逐行核实。

**writer 最小可行**：直接 SQLite 插入需完整 DDL → 建议先采真实 `sessions.db`，按 schema 写 `sessions` + `messages` 两表；或用 goose CLI 自身 API（若有）生成。风险：schema 无文档、跨版本可能变。

**证据（DOC 官方）**：https://goose-docs.ai/docs/guides/logs （旧域 https://block.github.io/goose/ 同文）；codeburn 补充：https://github.com/getagentseal/codeburn/blob/main/docs/providers/goose.md ；官方 repo：https://github.com/aaif-goose/goose 。

**实现难度**：中（SQLite 写、DDL 需反推）；**样本**：可本地用 goose CLI 造；**等级：DOC（路径/格式）+ COMMUNITY（表细节）**。

---

### 1.8 Junie（JetBrains）— COMMUNITY（live 验证）

**存储路径**：`${JUNIE_HOME:-~/.junie}/sessions/<session-id>/`，`sessions/index.jsonl` 为列表（每行含 `projectDir`、`taskName`）。注意 home 是 `.junie` 在 **JVM user.home** 下，不一定等于 `$HOME`。

**物理格式**
- `events.jsonl`：一行一个 `{kind, timestampMs, …}`
- 同目录：`state.json`（最后状态）、`transcript.md`（同日志的渲染）、`task-*/`（每 task）
- 事件类型（折叠键 `stepId`）：`UserPromptEvent{prompt, presentablePrompt}`；`SessionA2uxEvent{event:{state, agentEvent:{kind, stepId}}}` 内嵌块：
  - `TerminalBlockUpdatedEvent{command,status,exitCode,output}`
  - `ViewFilesBlockUpdatedEvent{files[].relativePath}`
  - `FileChangesBlockUpdatedEvent{changes[].{beforeContent.text, afterContent.text}}`
  - `MarkdownBlockUpdatedEvent` / `ResultBlockUpdatedEvent`
  - `ContextCompactionBlockUpdatedEvent`

**恢复机制**：`cd <projectDir> && junie --session-id <id> --resume`（projectDir 来自 `index.jsonl`）。

**writer 最小可行**：建 `sessions/<uuid>/events.jsonl`（写 `UserPromptEvent` + 至少一条 `ResultBlockUpdatedEvent`/`MarkdownBlockUpdatedEvent`）+ `state.json` + 追加 `sessions/index.jsonl`（`projectDir`）。

**证据（COMMUNITY，对照 Junie CLI 3110.7 实际安装 live 验证）**：https://github.com/vshulcz/deja-vu/blob/db6bb255d9ca269197e0929939348f18b37f2523/docs/registry/junie.md ；官方：https://www.jetbrains.com/junie/ 。

**实现难度**：低-中（JSONL 事件 + 折叠规则）；**样本**：需真实采集（或按事件 schema 构造）；**等级：COMMUNITY**。

---

### 1.9 Mistral Vibe — COMMUNITY（多代格式，需按版本分支）

**存储路径**：`$VIBE_HOME/logs/session/`（默认 `~/.vibe/logs/session/`）。存在 **三代**布局：
1. **早期/1.x**：`logs/session/session_<YYYYMMDD_HHMMSS>_<hash>.json`（TokenTelemetry 在真实机器观察到，含 `metadata.stats` + `messages[]`）
2. **Vibe 2.x（legacy）**：每 session 一个目录 `<id>/{meta.json, messages.jsonl}`；`meta.json` 含累计 token/模型/价格/时间/cwd/tools；子 agent 在父 session 的 `agents/` 下同构
3. **Vibe 2.25+ Unified Harness**：`unified/<session_id>/`，含 `CURRENT` 指针 → 代际目录（`projection-state.json`、`runtime-state.json`、`chunks/`、`journal/*.jsonl`；journal 是恢复日志，仅保留两段 + 快照）

**恢复机制**：Vibe CLI 自身（`vibe`），未核实 resume flag。

**writer 最小可行**：针对 **Vibe 2.x legacy**（最稳）：写 `<id>/meta.json`（含 `environment.working_directory`、`stats`、active model 配置）+ `messages.jsonl`（非 system 消息 + assistant `tool_calls`）。Unified 走 journal/projection 机制，writer 复杂 → 不建议首批。

**证据（COMMUNITY，逐字段溯源）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/mistral-vibe.md ；官方 repo：https://github.com/mistralai/mistral-vibe ；TokenTelemetry 观察（早期布局）：harness survey longtail。

**实现难度**：中-高（三代格式）；**样本**：需真实采集；**等级：COMMUNITY**。

---

### 1.10 Roo Code — COMMUNITY

**存储路径**：VS Code-host globalStorage `rooveterinaryinc.roo-cline/tasks/<taskId>/`；会探测 Code / Insiders / VSCodium / Cursor / Windsurf 的 host root；Roo CLI 写在 `~/.vscode-mock/global-storage`；自定义存储路径可由 host `User/settings.json` 里 `roo-cline.customStoragePath` 指定。
- 每 task 目录：`api_conversation_history.json`（transcript，Cline legacy 同形）、`ui_messages.json`、`history_item.json`（id/ts/task/workspace）、`task_metadata.json`

**恢复机制**：`roo -w <workspace> --session-id <uuid>`（CLI 创建的任务）；编辑器任务从扩展历史 UI 重开。

**现状**：Roo Code 已归档（RooCodeInc/Roo-Code，2026-05-15，deja-vu 记录）→ 格式稳定但不再演进，适合作为「只读 + 单向 writer」候选。

**writer 最小可行**：在 host globalStorage 写 `tasks/<uuid>/{api_conversation_history.json, history_item.json}`（transcript 形状与 Cline legacy 一致：text block + `<task>` envelope + 原生 tool_use）；确认 host 根存在（mac：`~/Library/Application Support/Code/User/globalStorage/`）。

**证据（COMMUNITY，对照 Roo 源码 `src/shared/globalFileNames.ts`、`src/core/task-persistence` + live 验证）**：https://github.com/vshulcz/deja-vu/blob/db6bb255d9ca269197e0929939348f18b37f2523/docs/registry/roo.md ；官方（已归档）repo：https://github.com/RooCodeInc/Roo-Code 。

**实现难度**：低（JSON，与 Cline 共用解析）；**样本**：需真实采集（VS Code + Roo）；**等级：COMMUNITY**。

---

### 1.11 Kilo Code — COMMUNITY（Cline 族薄封装）

**存储路径**：VS Code globalStorage `kilocode.kilo-code/tasks/<taskId>/{ui_messages.json, api_conversation_history.json}`；与 Cline 共用同一套解析器（差异仅在 extension ID 与少量字段）。

**恢复机制**：Kilo 扩展 UI。

**writer 最小可行**：同 Cline 扩展：写 `tasks/<id>/` 两 JSON；host 根：`~/Library/Application Support/Code/User/globalStorage/kilocode.kilo-code/`（mac；Codeg 也给出 `~/.kilo` 线索，但 VS Code 扩展主存为 globalStorage）。

**证据（COMMUNITY）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/kilo-code.md 、共享解析器 https://github.com/getagentseal/codeburn/blob/main/docs/providers/vscode-cline-parser.md ；官方：https://kilocode.ai/docs 。

**实现难度**：低（同 Cline 族）；**样本**：与 Cline 共用 fixture；**等级：COMMUNITY**。

---

### 1.12 Cline（VS Code 扩展 + CLI）— COMMUNITY

**A. VS Code 扩展**
- 路径：VS Code globalStorage `saoudrizwan.claude-dev/tasks/<taskId>/`（stable/Insiders/VSCodium 各自树都要扫）+ Cline home-data `~/.cline/data/tasks/`
- 文件：`ui_messages.json`（事件流；`api_req_started.text` 里是 JSON，含 `tokensIn/tokensOut/cacheReads/cacheWrites/cost`）、`api_conversation_history.json`（完整 prompt 历史，模型从 `<model>` 标签提取）、`task_metadata.json`
- 发现条件：task 目录必须存在 `ui_messages.json`

**B. Cline CLI（3.x，独立布局）**
- 路径：`<root=CLINE_DIR ~/.cline>/data/sessions/<sessionId>/`，存在 `<sessionId>.json` 才算 session；env 层级：`CLINE_SESSION_DATA_DIR` > `CLINE_DATA_DIR` > `CLINE_DIR`
- 文件：`<id>.json`（`session_id/provider/model/cwd/workspace_root/started_at/ended_at/messages_path/metadata.usage{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens,totalCost}`）+ `<id>.messages.json`（`{version, updated_at, agent, sessionId, messages[], system_prompt}`；assistant 消息为 Anthropic 风格 `thinking/text/tool_use`，另含 `modelInfo{id,provider}`、`metrics{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens,cost}`）
- `messages_path` 是绝对路径，跨机器复制会失效 → 优先同目录 `<id>.messages.json`

**恢复机制**：扩展历史 UI / `cline` CLI 自身（resume flag 未核实）。

**writer 最小可行**：CLI 形态最简单：写 `<id>.json`（`messages_path` 指向同目录 `<id>.messages.json`）+ `<id>.messages.json`；扩展形态写 `tasks/<id>/ui_messages.json` + `api_conversation_history.json`。

**证据（COMMUNITY，逐字段来自 codeburn，含 CLI messages 结构）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/cline.md 、https://github.com/getagentseal/codeburn/blob/main/docs/providers/cline-cli.md 、共享解析器 vscode-cline-parser.md；官方：https://docs.cline.bot 。

**实现难度**：低（JSON）；**样本**：可构造（结构清晰）；**等级：COMMUNITY**。

---

### 1.13 Warp — COMMUNITY（本地 SQLite 可读；**修正：不是纯云端**）

**存储路径（mac）**
- Stable：`~/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite`
- Preview：同路径下 `dev.warp.Warp-Preview/warp.sqlite`
- 可 `WARP_DB_PATH` 覆盖

**格式**：SQLite；关键表 `agent_conversations`、`ai_queries`、`blocks`。
- `agent_conversations.conversation_id`；`ai_queries.start_ts/input[0].Query.text/working_directory/model_id/output_status`；`blocks.stylized_command`
- 注意：`ai_queries.output_status` 可能是「JSON 字符串」（如 `"Completed"`）需规范化；无可靠 input/output token 拆分（按估算）

**writer 最小可行**：**不建议写** —— 这是专有应用 DB（有 -wal/-shm、schema 随版本演进、写坏会影响 Warp 本体）。**只做只读 Reader**；可复制 DB 快照后离线解析。

**证据（COMMUNITY）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/warp.md ；官方：https://docs.warp.dev 。（本次核实推翻了「Warp 纯云端」的旧判断。）

**实现难度**：中（SQLite 只读、表语义需对 Warp 版本验证）；**样本**：需真实采集；**等级：COMMUNITY（只读）**。

---

### 1.14 Replit Agent — UNVERIFIED（纯云端）

- 未找到任何本地 session 存储路径、导出能力或开源解析器（codeburn provider 列表无 Replit；deja-vu registry 无 Replit）。
- 检索到第三方迁移指南（Replit → Auteryn）说明迁移靠重新输入/人工整理，侧面支持「无官方 session 导出」。
- **结论**：**不做本地适配**；若未来必须支持，只能走「用户手工复制对话 → ATIF」路线。

**证据**：https://docs.replit.com （无 session 导出文档）；第三方迁移说明：https://docs.auteryn.ai/migrate/from-replit/ （COMMUNITY/博客性质，仅辅助）。

**等级：UNVERIFIED → 归入「纯云端，不可做」**。

---

### 1.15 Codebuff — COMMUNITY

**存储路径**：`~/.config/manicode`（stable）、`~/.config/manicode-dev`、`~/.config/manicode-staging`；`$CODEBUFF_DATA_DIR` 可统一覆盖。会话位于 `<root>/projects/<project>/chats/<chatId>/`：
- `chat-messages.json`：JSON 数组，每条消息含 `variant`（`user`/`ai`/`agent`/`assistant`）、可选 `credits`、可选 `blocks`（含嵌套 sub-agent blocks）、`metadata`（可能直接有 usage，或藏在 `runState.sessionState.mainAgentState.messageHistory`）
- `run-state.json`：用于解析该 session 的真实工作目录

**恢复机制**：Codebuff CLI 自身（未核实 flag）。

**writer 最小可行**：写 `projects/<project>/chats/<chatId>/chat-messages.json`（variant + blocks + metadata）+ `run-state.json`（cwd）。

**证据（COMMUNITY）**：https://github.com/getagentseal/codeburn/blob/main/docs/providers/codebuff.md ；官方：https://www.codebuff.com （开源：`codebuffai/codebuff`）。

**实现难度**：低-中（JSON，但 usage 有嵌套变体）；**样本**：需真实采集/构造；**等级：COMMUNITY**。

---

### 1.16 可选：Cursor IDE `state.vscdb` — COMMUNITY（只读）

**路径**：`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`（SQLite，含 `-wal/-shm`；运行中需 copy 或 `?mode=ro`）。

**结构（TokenTelemetry 只读调查）**
- `cursorDiskKV` 表为 KV：key 前缀 `composerData:<composerId>`（会话容器）、`bubbleId:<composerId>:<bubbleId>`（每条消息：`text/thinking/tokenCount{inputTokens,outputTokens}/todos/toolResults/mcpDescriptors`）、`checkpointId:<composerId>:<checkpointId>`（文件检查点）、`agentKv:blob:<sha256>`（原始模型 I/O，**禁止输出内容**）
- `ItemTable` 另有 `cursorAuth/*` 等 token（不得读取）
- 注意：composerId → 项目路径映射需经 `workspaceStorage/<hash>/state.vscdb` 的 `composer.composerData.selectedComposerIds` + `workspace.json`

**最小可读查询**
```sql
SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%';
SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%';
```

**结论**：只读可行（需 JSON 二次解析）；**writer 不建议**（Cursor 校验 + WAL 锁 + schema 私有）。

**证据（COMMUNITY）**：TokenTelemetry harness survey cursor-vscode：https://github.com/VasiHemanth/tokentelemetry/blob/main/docs/research/harness-survey/harness-cursor-vscode.md 。

---

### 1.17 可选：GitHub Copilot CLI `session-store.db` — COMMUNITY（只读推荐）

**路径**：`~/.copilot/session-store.db`（另有 `session-state/<uuid>/`；`settings.json`）。

**表结构（已知 DDL 摘要）**
- `sessions(id,cwd,repository,host_type,branch,summary,created_at,updated_at)`
- `turns(id,session_id,turn_index,user_message,assistant_response,timestamp)`
- `checkpoints(id,session_id,checkpoint_number,title,overview,history,work_done,technical_details,important_files,next_steps,created_at)`
- `session_files(...)`、`session_refs(...)`
- **`assistant_usage_events`**：`session_id, turn_index, agent_id, parent_tool_call_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, total_nano_aiu, request_multiplier, duration_ms, time_to_first_token_ms, inter_token_latency_ms, initiator, api_endpoint, reasoning_effort, finish_reason, content_filter_triggered, token_details_json, created_at`（**批 5 中元数据最全的源**）
- FTS5 `search_index`（影子表需过滤）

**结论**：**只读**（专有 DB，且会话状态与 IDE/账户绑定；写入风险高）；`copilot --resume` 恢复由 CLI 自身完成。

**证据（COMMUNITY）**：https://github.com/VasiHemanth/tokentelemetry/blob/main/docs/research/harness-survey/harness-codex-copilot-cline.md ；“Copilot CLI `~/.copilot`”亦见 Codeg 文档旁证。

---

## 2. 批 5 实现优先级

### 2.1 分层

| 层 | Harness | 理由 |
|---|---|---|
| **T1（先做：JSON/JSONL 低风险）** | **Cline（VS Code + CLI）**、**Roo Code**、**Kilo Code**、**Continue**、**Junie**、**Codebuff** | 全部 JSON/JSONL；三个 Cline 族共用一套 adapter；写入是「新增文件」不是改私有 DB |
| **T2（SQLite/多代：先 Reader 后 Writer）** | **Goose**、**Crush**、**Zed**、**Kiro CLI**、**CodeBuddy**（DOC 路径但 schema 待采） | SQLite 需只读打开 + schema 探测；Kiro/CodeBuddy 需真实样本才能定字段 |
| **T3（复杂/弱证据）** | **OpenHands**（SDK 格式 DOC，运行时路径未核实）、**Mistral Vibe**（三代布局）、**Warp**（只读）、**Cursor IDE**（只读）、**Copilot CLI**（只读） | 需 SDK 事件模型 / 多版本分支 / 专有 DB |
| **不做** | **Replit Agent**（纯云端无本地存储） | 只能靠用户手工导出 → 走 ATIF 粘贴 |

### 2.2 最值得先做 6 个（附理由）

1. **Cline（VS Code + CLI）** — 两个 store 都是纯 JSON、结构已逐字段确认；一个 adapter 同时覆盖 **Roo Code、Kilo Code**（同族），投入产出比最高。
2. **Continue** — 单文件 JSON `sessions/<id>.json` + `sessions.json`，写入风险最低，1 天内可交付；且纠正了「SQLite」误判，避免走错路。
3. **Junie** — JSONL 事件日志 + index，恢复命令明确（`junie --session-id <id> --resume`），JetBrains 用户群大，社区已 live 验证。
4. **Kiro CLI** — JSONL（`{version,kind,data}`）比 IDE 侧简单，AWS 用户增长快；先做 CLI store，IDE v2 后续。
5. **Crush** — 唯一给出**完整 DDL** 的 SQLite 目标，可先写 reader + 受控 writer（复制 DB 后写），为后续 Goose/Zed SQLite writer 沉淀模式。
6. **Goose** — 官方文档确认 path/SQLite/迁移史（v1.10.0 前后两代），用户基数大；DDL 需采真实库补全，适合作为「DOC 路径 + 反推 schema」的样板。

> 备选：**Codebuff**（JSON、简单）、**Roo/Kilo** 若与 Cline 拆开单独计。

### 2.3 明确不可做/不建议做

- **Replit Agent**：纯云端，无本地 session 存储与导出 → 不做（UNVERIFIED）。
- **Warp / Cursor IDE / Copilot CLI**：本地可读但属**专有应用 DB**，写入会破坏宿主应用状态 → **只读适配**，不做 writer。
- **加密/云同步部分**：Kiro/CodeBuddy/Copilot 的云端状态、Antigravity `.pb` 不在本批范围。

---

## 3. 未核实清单 / 风险

**未核实**
- **CodeBuddy**：`.jsonl` 具体字段（是否 Claude Code verbatim）→ 需采一条真实 session 再定 reader；`/resume` 的 CLI flag。
- **Kiro**：`kiro-cli` 恢复命令/flag；IDE 三代格式的优先级判定规则；credits→token 换算不适用（Kiro 只给 credits）。
- **Goose**：`sessions.db` 完整 DDL、`goose session resume` 的准确语法。
- **OpenHands**：GUI/server 默认存储根（SDK FileStore 之外的 `~/.openhands` 说法未证实）。
- **Mistral Vibe**：Unified Harness（2.25+）writer 是否可由外部安全生成。
- **Replit**：是否有隐藏的本地缓存（未找到任何证据）。

**风险**
- **专有 DB 写入**（Warp/Cursor/Copilot/Zed/Goose/Crush）：必须「复制 DB → 写入副本 → 用户手动替换/或提供只读导入」，且需版本探测；否则可能破坏宿主应用。
- **格式漂移**：Kiro、Cline、Mistral Vibe、Goose 都在近一年改过存储（见各小节），adapter 必须按 `format_version` 分支，未知内容进 `warnings`。
- **隐私**：Cline `api_conversation_history.json`、Cursor `agentKv:blob`、Copilot `turns`、Warp `ai_queries.input` 均含原文；fixtures 入库前必须脱敏。

---

## 4. 引用清单（原始 URL）

**官方（DOC）**
- Goose 日志/会话存储（官方 docs）：https://goose-docs.ai/docs/guides/logs
- Goose 官方 repo：https://github.com/aaif-goose/goose
- OpenHands SDK 持久化（官方 PR/文档）：https://github.com/OpenHands/software-agent-sdk/pull/41/files ；SDK repo：https://github.com/OpenHands/software-agent-sdk ；官方文档：https://docs.all-hands.dev
- CodeBuddy 目录结构（腾讯云官方）：https://www.tencentcloud.com/document/product/1316/84431 ；中文站：https://www.codebuddy.ai/docs/cli/codebuddy-dir
- Continue 官方：https://docs.continue.dev
- Zed 官方：https://zed.dev/docs
- Crush 官方 repo：https://github.com/charmbracelet/crush
- Junie 官方：https://www.jetbrains.com/junie/
- Mistral Vibe 官方 repo：https://github.com/mistralai/mistral-vibe
- Roo Code 官方（已归档）：https://github.com/RooCodeInc/Roo-Code
- Kilo 官方：https://kilocode.ai/docs
- Cline 官方：https://docs.cline.bot
- Warp 官方：https://docs.warp.dev
- Codebuff 官方：https://www.codebuff.com
- Kiro 官方：https://kiro.dev/docs
- Replit 官方：https://docs.replit.com

**COMMUNITY（逆向/验证）**
- codeburn provider 文档目录（Kiro/Zed/Crush/Goose/Cline/Cline-CLI/Kilo/Warp/Mistral Vibe/Codebuff…）：https://github.com/getagentseal/codeburn/tree/main/docs/providers
- deja-vu registry（Continue/Junie/Roo，部分 live 验证）：https://github.com/vshulcz/deja-vu/tree/db6bb255d9ca269197e0929939348f18b37f2523/docs/registry
- TokenTelemetry harness survey（Cursor/Copilot/OpenCode 等 schema）：https://github.com/VasiHemanth/tokentelemetry/tree/main/docs/research/harness-survey
  
**旁证（路径表）**
- Codeg supported agents（Kiro/CodeBuddy 等默认路径与环境变量）：https://docs.codeg.app/guide/supported-agents
- 本仓库：`docs/harness-catalog.md`、`docs/atif-interop-protocol.md`、`samples/`（本机 5 源样本）
