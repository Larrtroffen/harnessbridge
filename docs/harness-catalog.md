# Harness 目录与适配优先级（ATIF 互转协议地基）

> 版本：v0.1（2026-10-30）｜作者：webresearch（Team 成员）
> 上游协议：`docs/atif-interop-protocol.md`（ATIF v1.8 统一中转，Reader → IR → ATIF → IR → Writer）
> 本目录作用：为「30-40 种 Harness 两两互转」确定候选清单、每个 Harness 的 session 落盘事实、样本可得性、适配优先级与批次。
> 约束：本报告只写本文件；所有结论标注证据等级，**未核实一律写「未核实」**，不臆造路径/格式。

---

## 0. 证据等级图例

| 代号 | 证据类型 | 说明 |
|---|---|---|
| **A** | 本机真实样本 | 本机 `~/.claude`、`~/.codex`、`~/.omp`、`~/.qoder`、`~/.dsh` 有真实数据；`samples/` 有只读副本 |
| **B** | Codeg 一手路径表 | https://docs.codeg.app/guide/supported-agents 明确给出默认路径/格式/迁移环境变量（2026-10） |
| **C** | TokenTelemetry Harness Survey | https://github.com/VasiHemanth/tokentelemetry/tree/main/docs/research/harness-survey 逐个 harness 的只读文件系统调查（2026-08，含 schema） |
| **D** | sessionport fixture | https://github.com/Reality-Shifting-Tech/sessionport `tests/fixtures/` 有该 harness 的合成/截断样本 |
| **E** | Agent Sessions steward | https://github.com/jazzyalex/agent-sessions `docs/agent-support/*` 有格式验证记录与版本 |
| **F** | 官方文档/仓库 | 厂商一手文档或官方 repo |
| **I** | OSS 解析实现 | Codeg（Rust）、Agent Sessions（Swift）、atiifact（TS）、atif 等公开代码可参考 |
| **G** | 未核实 | 仅产品资料/推断，未拿到路径或格式证据 |
| **H** | ATIF/Harbor 附带样例 | Harbor RFC 0001 §V 附带真实轨迹样例 |

**P0 / P1 / P2 定义（对齐 Lead 口径）**
- **P0**：本机已有真实样本（A），**或**公开 OSS 仓库自带该格式的 fixture/样例（D/E/H），可直接写 golden test 开工；
- **P1**：格式有一手文档或只读调查给出确切路径/格式（B/C/F），可先写 reader、样本后补；
- **P2**：只有云端/IDE 内部存储、protobuf/加密/需逆向客户端，短期不做。

统计（主表 42）：**P0 = 17，P1 = 7，P2 = 18**；附录 A 扩展候选 7 个（P0 2 / P1 1 / P2 4）。合计 **49 个候选**。

---

## 1. 主表：42 个 Harness

> 路径默认 macOS/Linux 约定（Windows 对应 `%APPDATA%`/`%LOCALAPPDATA%`）；`<slug>`=cwd 转义；`<sid>`=session id。
> 「可导出」= 厂商是否提供 session/transcript 导出能力；「样本」= 可用于开发的真实/合成样本来源。

| # | Harness | 形态 | session 存储位置（默认） | 物理格式 | 可导出 | 官方文档 | 样本/证据 | 优先级 | 家族/类别 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Claude Code** | CLI Agent（npm；Codeg/AgentSessions 也以它为基础） | `~/.claude/projects/<slug>/<uuid>.jsonl`；另有 `history.jsonl`、`session-env/`、`file-history/`、`plugins/` | JSONL（`uuid/parentUuid/sessionId/message/usage/toolUse`） | 有 `/export`（版本相关） | https://docs.claude.com/en/docs/claude-code | **A** 本机真实数据；`samples/claude/`（采集中）；**D** fixture；**I** atifact/sessionport | **P0** | Claude Code 原型 |
| 2 | **Claude Desktop / Cowork** | 桌面 App（Electron） | `~/Library/Application Support/Claude/`（会话数据在本地；具体文件未核实） | 未核实（Electron 内部存储，可能加密） | 未核实 | https://claude.com/download | **G** 无公开样本 | **P2** | 桌面/云端类 |
| 3 | **OpenAI Codex CLI** | CLI（与桌面/IDE 共用 store） | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` + `state_5.sqlite`（threads）/`thread_history_1.sqlite`/`session_index.jsonl`/`history.jsonl` | JSONL rollout（`session_meta`/`task_started`/`turn_context`/`response_item`/`event_msg`/`compacted`）+ SQLite 索引 | 无官方导出；rollout 即完整轨迹 | https://github.com/openai/codex | **A** 本机 + `samples/codex/`（8 文件）+ `docs/formats/codex.md`；**D**；**I** | **P0** | 自有（未发现 Codex 衍生） |
| 4 | **Codex Desktop（App）** | 桌面 App | 同一 `~/.codex`（7 天不活跃 session 打包 `.jsonl.zst` 并删原文件） | JSONL / zstd | 无 | https://github.com/openai/codex | **E** Agent Sessions v5.7 记录（读 `.jsonl.zst`）；同 #3 解析器 | **P1** | Codex 同族 |
| 5 | **Qoder**（阿里） | CLI + IDE | `~/.qoder/projects/<slug>/<uuid>.jsonl` + `<uuid>/state.json`（加密）+ `compression-v2/` + `subagents/` | JSONL（**Claude Code schema 衍生**）+ 加密 state | 有 `/export`（官方文档确认） | https://docs.qoder.com/cli/sessions | **A** 本机 + `samples/qoder/`（8 文件）+ `docs/formats/qoder.md`；**C**；**D** relayhistory fixtures | **P0** | **Claude Code 衍生（已验证）** |
| 6 | **OMP（oh-my-pi）** | TUI CLI（pi 系，Stencil Labs） | `~/.omp/agent/sessions/<slug>/<ISO>_<uuid>.jsonl` + 同名伴生目录（工具日志/子代理）+ `history.db`/`agent.db`（SQLite） | JSONL **树状事件流**（`type`+`id`+`parentId`，`session.version=3`）；伴生 `.log` 工具原始输出 | 未核实（有 export/share/fork 文档） | https://omp.sh/docs ；https://github.com/can1357/oh-my-pi | **A** 本机 + `samples/omp/`（9 文件）+ `docs/formats/omp.md`（1,730 个真实 session 分析） | **P0** | **pi 系**（树状） |
| 7 | **DeepSeek Harness（DSH）** | Desktop App + CLI（DeepSeek） | `~/.dsh/sessions/<projectKey>/<sessionId>/session.v4.jsonl.zstd`；`~/.dsh/storages/workspace.json`；`session_projcache/` | **zstd 双帧 + JSONL** 事件流（60+ 事件类型，`seq` 连续） | 本地文件即导出 | https://deepseek-harness.github.io/deepseek-harness/ | **A** 本机 + `samples/dsh/`（含已验证可加载的最小模板）；`docs/formats/dsh.md` | **P0** | 自有（zstd 压缩，非加密） |
| 8 | **Pi**（pi.dev） | 自扩展 TUI Agent | `~/.pi/agent/sessions/<cwd-slug>/<ts>_<uuid>.jsonl`（`PI_CODING_AGENT_SESSION_DIR`） | JSONL（`session`/`model_change`/`thinking_level_change`/`message`，`id`+`parentId`） | 未核实 | https://pi.dev | **C** 完整 schema；**B** 路径；**I** Codeg/Agent Sessions 解析器 | **P1** | **pi 系**（OMP 同格式族） |
| 9 | **Gemini CLI**（Google） | CLI（2026-06-18 后由 Antigravity 承接，见 C） | `~/.gemini/tmp/<sha256(project)>/chats/session-<ISO>-<short>.json`；`~/.gemini/history/<slug>/.project_root`（hash→路径解析） | JSON（`{sessionId,projectHash,startTime,messages[]}`） | 未核实 | https://github.com/google-gemini/gemini-cli | **C** 完整 schema；**D** fixture；**H** ATIF RFC 附真实 gemini-cli 轨迹 | **P0** | **Gemini 系**（Qwen Code 上游） |
| 10 | **Google Antigravity** | 桌面 App + IDE + `agy` CLI（VS Code fork） | `~/.gemini/antigravity{,-ide,-cli}/…`：`brain/<conversation-uuid>/*.md`、`conversations/<uuid>.pb`、`antigravity-cli/conversation_summaries.db` | protobuf（`.pb`，无公开 schema）+ SQLite summaries（131 行，含 `battle_id`/`nesting_depth`）+ Markdown artifacts | 未核实 | https://antigravity.google | **C** 完整目录与 DB schema；**I** TokenTelemetry 解析 | **P2**（`.pb` 需逆向；可先用 summaries.db 只读） | 桌面类（protobuf） |
| 11 | **Cursor**（IDE + CLI） | IDE + CLI Agent | CLI：`~/.cursor/projects/<slug>/agent-transcripts/<sid>/<sid>.jsonl`；IDE：`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`（`cursorDiskKV`: composerData/bubbleId/checkpointId） | JSONL / **SQLite KV（JSON blob）** | 未核实（无公开导出） | https://docs.cursor.com | **C** 两侧完整 schema；**D** fixture；**B**（`~/.cursor/chats/` SQLite，与 C 有版本差异）；**I** | **P0** | 自有（SQLite 类） |
| 12 | **Windsurf**（Codeium） | IDE | `~/.windsurf`（JSONL sessions；具体层级未核实） | JSONL（据 **D**） | 未核实 | https://docs.windsurf.com | **D** fixture | **P0**（仅 fixture，非真实） | 自有 |
| 13 | **Cline**（CLI + VS Code 扩展） | CLI + 扩展 | CLI：`~/.cline/data/sessions/<epochms>_<slug>/{<id>.json,<id>.messages.json}`；扩展：VS Code globalStorage `saoudrizwan.claude-dev/tasks/` | JSON | 未核实 | https://docs.cline.bot | **C** 完整 schema（含 exit_code/status）；**D** fixture；**B** | **P0** | 自有 |
| 14 | **Roo Code** | VS Code 扩展（Cline 族） | VS Code globalStorage `rooveterinaryinc.roo-cline/tasks/<id>/`（**未核实**） | JSON（推断，同 Cline 族） | 未核实 | https://docs.roocode.com | **G** 无样本 | **P2** | Cline 族 |
| 15 | **Kilo Code** | VS Code 扩展（Cline/Roo 族） | 无确定默认路径；**D** 暗示 `~/.kilo/sessions/*.jsonl` | JSONL（据 **D**） | 未核实 | https://kilocode.ai/docs | **D** fixture | **P0**（仅 fixture） | Cline 族 |
| 16 | **TRAE**（字节） | IDE + CLI | 未核实（Codeg 仅读其原生记录补用量，不支持导入） | 未核实 | 未核实 | https://www.trae.ai | **B**（明确「无原生导入」） | **P2** | 自有 |
| 17 | **Kiro CLI**（AWS） | CLI | `~/.kiro/sessions/cli/`（JSONL 事件日志 + 每 session JSON metadata；`KIRO_HOME`） | JSONL + JSON | 未核实 | https://kiro.dev/docs | **B** 一手路径表 | **P1** | 自有 |
| 18 | **GitHub Copilot**（CLI + VS Code Chat） | CLI + VS Code 扩展 | CLI：`~/.copilot/session-store.db` + `session-state/<uuid>/`；VS Code：`~/Library/Application Support/Code/User/globalStorage/github.copilot-chat/session-store.db` | **SQLite**（sessions/turns/checkpoints/`assistant_usage_events` + FTS5） | CLI 有 `--resume`；无导出 | https://docs.github.com/en/copilot | **C** 完整 schema；**D** fixture；**I** atifact 支持 Copilot CLI→ATIF；**E** | **P0** | SQLite 类 |
| 19 | **Qwen Code**（阿里） | CLI（**Gemini CLI fork**） | `~/.qwen/projects/<enc-cwd>/chats/<uuid>.jsonl`；另有旧存储 `tmp/<sha256>/logs.json`、`todos/<sid>.json` | JSONL | 未核实 | https://github.com/QwenLM/qwen-code | **C** 完整 schema；**E** 验证过 0.14.3 | **P1** | **Gemini CLI 衍生（已验证）** |
| 20 | **Kimi CLI / Kimi Code**（Moonshot） | CLI | Kimi CLI：`~/.kimi/{sessions/<id>/,user-history/<id>.jsonl,kimi.json}`；Kimi Code：`~/.kimi-code/sessions/*.jsonl`（**B**） | 未核实（本机 `sessions/` 为空；Kimi Code 称 JSONL） | 未核实 | https://github.com/MoonshotAI/kimi-cli（未核实） | **C**（Kimi CLI 目录）+ **B**（Kimi Code 路径） | **P2**（真实 transcript 待采） | 疑似 Claude Code 系（未核实） |
| 21 | **iFlow CLI**（心流） | CLI | 未核实（社区/任务描述称疑似 Claude Code 衍生） | 未核实 | 未核实 | https://iflow.cn | **G** 无样本 | **P2** | 疑似 Claude Code 衍生（未核实） |
| 22 | **OpenCode**（sst） | 开源 CLI | `~/.local/share/opencode/opencode.db`（+ `storage/session_diff/`、`snapshot/`、`tool-output/`；`XDG_DATA_HOME`/`OPENCODE_DB`） | **SQLite**（session/message/part，`data` 为 JSON blob） | 未核实 | https://opencode.ai/docs | **C** 真实 51 sessions schema；**D** fixture；**B**；**I** | **P0** | SQLite 类 |
| 23 | **Aider** | CLI | `~/.aider.chat/history/<hash>.md`（+ 配置/缓存） | **Markdown** 历史 | 文件即导出 | https://aider.chat/docs | **D** fixture（markdown 小样本） | **P0** | 自有（非结构化） |
| 24 | **Goose**（Block） | CLI/桌面 | 未核实（**D** fixture 为 `sessions/*.jsonl`） | JSONL（据 **D**） | 未核实 | https://github.com/block/goose | **D** fixture | **P0**（仅 fixture） | 自有 |
| 25 | **Continue** | IDE 扩展/CLI | `~/.continue/sessions/*.json`（未核实） | JSON（推断） | 未核实 | https://docs.continue.dev | **G** | **P2** | 自有 |
| 26 | **Sourcegraph Cody** | IDE 扩展/CLI（云端） | 云端为主；本地 cache 未核实 | 未核实 | 未核实 | https://sourcegraph.com/cody | **G** | **P2** | 云端类 |
| 27 | **Augment Code** | IDE 扩展（云端） | 云端为主；本地 cache 未核实 | 未核实 | 未核实 | https://www.augmentcode.com | **G** | **P2** | 云端类 |
| 28 | **Amp**（Sourcegraph） | CLI/IDE Agent | 未核实（可能 `~/.amp`） | 未核实 | 未核实 | https://ampcode.com/manual | **G** | **P2** | 自有/云端 |
| 29 | **Factory Droid** | CLI | 未核实（Agent Sessions 有 legacy 支持） | 未核实 | 未核实 | https://factory.ai | **E**（legacy-only，不再做格式校验） | **P2** | 自有 |
| 30 | **Crush**（Charm） | TUI CLI | 未核实（可能 `~/.config/crush`/`~/.local/share/crush`） | 未核实 | 未核实 | https://github.com/charmbracelet/crush | **G** | **P2** | 自有 |
| 31 | **Zed**（Agent Panel） | 编辑器（ACP 客户端） | 未核实（`~/.local/share/zed`，SQLite 线程库待确认） | 未核实 | 未核实 | https://zed.dev/docs | **G** | **P2** | 编辑器类 |
| 32 | **OpenHands**（All-Hands） | OSS Agent 平台（Docker/CLI） | 未核实本地路径（运行在 sandbox 内，trajectory 可导出） | JSON 事件日志（trajectory/replay） | 有 trajectory/replay 导出 | https://docs.all-hands.dev | **H** ATIF RFC §V 附真实 `openhands_trajectory.json` | **P1** | 自有（可导出 trajectory） |
| 33 | **Devin CLI**（Cognition） | CLI | `~/.local/share/devin/cli/sessions.db`（SQLite） | **SQLite** | 有 `devin --resume <slug>`；无导出 | https://docs.devin.ai | **E** 253 sessions 审计 + 9 点验证；**C** 明细 | **P1** | 云端+本地混合 |
| 34 | **Warp** | 终端 + Agent | 云端 Warp Drive 为主；本地 SQLite 未核实 | 未核实/云端 | 未核实 | https://docs.warp.dev | **G** | **P2** | 云端类 |
| 35 | **Replit Agent** | 云端 IDE/Agent | 云端 | — | 未核实 | https://docs.replit.com | **G** | **P2** | 云端类 |
| 36 | **Codebuff** | 开源 CLI | 未核实（OSS 可查源码） | 未核实 | 未核实 | https://www.codebuff.com | **I**（开源可读源码，未核实存储） | **P2** | 自有/OSS |
| 37 | **Google Jules** | 云端异步 Agent | 云端 | — | 未核实 | https://jules.google | **G** | **P2** | 云端类 |
| 38 | **Sculptor**（Imbue） | 桌面/云端 | 云端/桌面内部，未核实 | 未核实 | 未核实 | https://sculptor.sh | **G** | **P2** | 云端类 |
| 39 | **Grok Build**（xAI） | CLI | `~/.grok/sessions/<url-encoded-cwd>/<uuid>/`（`summary.json`/`events.jsonl`/`chat_history.jsonl`/`updates.jsonl`/`plan.json`/`subagents/`/`compaction/`…）+ `session_search.sqlite` | JSONL 多文件 + SQLite 索引 | 未核实 | https://x.ai/cli | **C** 完整目录/schema；**D** fixture；**B**；**I** | **P0** | 自有 |
| 40 | **Hermes**（Nous Research） | 自托管 Agent（CLI/desktop） | `~/.hermes/state.db`（SQLite：sessions/messages/`session_model_usage`/cron）+ `sessions/`、`kanban.db`、`projects.db`（`HERMES_HOME`） | **SQLite** | 未核实 | https://hermes-agent.nousresearch.com | **C** 真实 schema；**D** fixture；**B** | **P0** | SQLite 类 |
| 41 | **OpenClaw** | 自托管 AI assistant/CLI | `~/.openclaw/agents/`（JSONL；Codeg 表） | JSONL（据 **B**） | 未核实 | https://openclaw.ai | **B**；**D** fixture；**I** | **P0**（仅 fixture/路径） | 自有 |
| 42 | **CodeBuddy**（腾讯） | CLI + IDE | `~/.codebuddy/projects/`（JSONL；`CODEBUDDY_CONFIG_DIR`） | JSONL（schema 未核实，布局与 Claude Code 同形） | 未核实 | https://www.codebuddy.ai | **B** 路径 | **P1** | 疑似 Claude Code 系（未核实） |

---

## 2. 附录 A：扩展候选（7 个，暂不入主表）

| # | Harness | 形态 | 存储位置 | 格式 | 可导出 | 文档 | 样本/证据 | 优先级 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| A1 | **fx**（vercel-labs） | CLI | `~/.fx/sessions/<id>/{checkpoint.json,session.json,display.json}`；0.0.8+ 改为 `events.jsonl`（schema 4） | JSON/JSONL | 有 `fx --resume <id>` | https://github.com/vercel-labs/fx | **E** 逐字段验证（0.0.5→0.0.7；0.0.8 变化已记录） | **P1** | 格式年轻易漂移 |
| A2 | **Mistral Vibe** | CLI | `~/.vibe/logs/session/session_<ts>_<hash>.json`；`config.toml`；`vibehistory` | JSON | 未核实 | https://github.com/mistralai/mistral-vibe | **C** 完整 schema；**D** fixture | **P0**（fixture） | 单文件含 `stats`/`messages`，易解析 |
| A3 | **Junie**（JetBrains） | IDE/CLI Agent | JVM/IDE 内部为主；**D** fixture 为 `sessions/*.jsonl` | JSONL（据 **D**） | 未核实 | https://www.jetbrains.com/junie/ | **D** fixture | **P0**（仅 fixture） | 实际默认路径未核实 |
| A4 | **MiniMax Code** | CLI（MiniMax） | 未核实；Codeg 自记 transcript，无原生导入 | 未核实 | 未核实 | https://www.minimax.io | **B**（明确无原生导入） | **P2** | 需逆向 |
| A5 | **ZCode**（Z.ai） | CLI（经社区 ACP bridge） | `~/.zcode` 等未核实；Codeg 自记 transcript | 未核实 | 未核实 | https://z.ai | **B** | **P2** | 需逆向 |
| A6 | **Command Code** | CLI | 未核实；Codeg 自记 transcript | 未核实 | 未核实 | https://commandcode.ai | **B** | **P2** | 需逆向 |
| A7 | **Tabnine / Tabby / Refact.ai** | IDE 插件/自托管 | 云端或本地 DB，未核实 | 未核实 | 未核实 | https://www.tabnine.com ；https://tabby.tabbyml.com ；https://refact.ai | **G** | **P2** | 企业/自托管，非核心 coding agent |

---

## 3. 家族与类别标注（协议实现要按家族复用 adapter）

### 3.1 Claude Code 衍生 schema 家族
- **Qoder**：**已验证**。第三方只读调查确认 `~/.qoder` 布局与 `~/.claude` 相同、记录字段（`cwd/gitBranch/isSidechain/parentUuid/sessionId/version/userType/entrypoint`）为 Claude Code schema verbatim；额外类型 `workspace-directories/runtime-config/last-prompt/active-leaf/attachment`（见 **C** harness-qoder.md）。
- **CodeBuddy**：布局同形（`<vendor>/projects/` JSONL），schema 未核实（**G**）。
- **Kimi Code**：`~/.kimi-code/sessions/*.jsonl` 布局同形，schema 未核实（**G**）。
- **iFlow CLI**：社区/任务描述疑似，完全未核实（**G**）。
- 实现建议：**一个 Claude-Code reader + 若干 profile/allowlist**（过滤 vendor 私有记录类型），即可覆盖整个家族；这是协议「家族复用」的第一优先。

### 3.2 Gemini CLI 衍生家族
- **Qwen Code**：**已验证**为 Gemini CLI fork（**C** 明确 "Qwen Code, a Gemini-CLI fork"），存储结构同源（`projects/<enc>/chats/*.jsonl` vs Gemini 的 `tmp/<hash>/chats/*.json`，字段同为 `uuid/parentUuid/sessionId/message.parts`）。
- **iFlow CLI**：疑似 Gemini/Claude 系二维不确定（**G**）。

### 3.3 pi 系（树状事件流）
- **Pi（pi.dev）** 与 **OMP（oh-my-pi）** 同格式族：entry 带 `id/parentId`，分支即树分叉；OMP 本地 1,730 个 session 已验证 `session.version=3`（`docs/formats/omp.md`）。
- 实现建议：**一个 tree-walker 主体**，两个 profile（字段名/伴生目录差异）。

### 3.4 Codex 衍生家族
- **未发现**明确的 Codex 衍生 harness；**Codex Desktop 与 Codex CLI 共用 `~/.codex`**（同一解析器，额外处理 `.jsonl.zst` 压缩）。

### 3.5 SQLite / 加密 / 压缩类（需要额外工作）
| 类型 | Harness | 说明 |
|---|---|---|
| SQLite | OpenCode、Hermes、GitHub Copilot（CLI+VS Code）、Cursor IDE、Codex（索引库）、Devin CLI、Grok（搜索索引） | 只读打开（`?mode=ro`/copy），注意 WAL 锁；JSON blob 需二次解析 |
| protobuf / 无公开 schema | Google Antigravity（`conversations/*.pb`） | 可先用 `conversation_summaries.db` 只读索引，`.pb` 需逆向 |
| 加密 | Qoder `state.json`（`{c,u,n,p,t}` 密文）、Antigravity `.pb`、Claude Desktop（未核实） | 只读「已解密可见」的部分；加密状态不承诺迁移 |
| 压缩非加密 | DSH（zstd 双帧 JSONL）、Codex Desktop（`.jsonl.zst`） | 解压后即普通 JSONL |

### 3.6 云端 / 无法本地取
Cody、Augment、Amp（部分）、Warp、Replit、Jules、Sculptor、Tabnine/Tabby/Refact.ai、Claude Desktop/Cowork；**Devin** 为混合（CLI 有本地 SQLite，agent 侧在云）。→ 统一列 **P2**，ATIF 协议只接收其用户手导出的 JSON/CSV（如果存在），不做本地扫描。

---

## 4. 下一步适配批次建议

| 批次 | 范围 | 数量 | 依据 |
|---|---|---|---|
| **批 1（已完成）** | Claude Code、Codex、OMP、Qoder、DSH | 5 | 本机真实样本（**A**）+ `docs/formats/*` + `asi` 双向矩阵 |
| **批 2** | Gemini CLI、OpenCode、Cursor、Cline、GitHub Copilot CLI、Grok Build、Aider、Hermes | 8 | 有 OSS fixture 或一手 schema 调查（**C/D**），格式为 JSON/JSONL/SQLite，且用户基数大 |
| **批 3** | Pi、Kiro CLI、Qwen Code、CodeBuddy、Devin CLI、OpenHands、fx、Mistral Vibe、Junie | 9 | 格式有文档/验证记录但样本需补采（**B/C/E**） |
| **批 4** | Antigravity（先只读 summaries.db）、Kimi、Windsurf、Goose、OpenClaw、Roo/Kilo 真实路径、Continue 等 P2 澄清后再定 | 8-12 | 需逆向或需样本补采（**G**） |
| 不做（v1） | 纯云端：Cody/Augment/Amp/Warp/Replit/Jules/Sculptor/Tabnine 等 | — | 无本地 store 或需登录云端 API |

> 「批 2 完成」= 8 个 Reader + 8 个 Writer 接入 `asi`，并各带 1 条真实或 fixture golden test。
> 关键依赖：`docs/oss-trajectory-inventory.md`（Lead 正在写）可把 OSS 真实 trace 仓（SWE-agent/OpenHands 数据集等）挂到对应 harness 的样本列。

---

## 5. 下一批最值得做的 6 个（+理由）

1. **Gemini CLI** — 用户基数大、格式最简单（JSON `messages[]`）；ATIF RFC 自带真实轨迹样例（**H**），且是 Qwen Code/iFlow 的格式母本 → 一份 reader 覆盖一个家族。
2. **OpenCode** — 开源、SQLite schema 已在 **C** 中完整给出（session/message/part + 51 真实 sessions），社区活跃；SQLite reader 可为后续 Hermes/Copilot/Devin 复用同一套「SQLite 只读 + JSON blob」工具层。
3. **Cursor** — 最大 IDE 用户盘；CLI 侧 JSONL transcript 可立即做（**C** 有完整行为说明），IDE 侧 `cursorDiskKV` 可复用同一 SQLite 工具层；先做 CLI 即可交付价值。
4. **GitHub Copilot CLI** — SQLite `session-store.db` 有 `assistant_usage_events`（token/AIU/时延/TTFT 全字段）和 `checkpoints`，是 P0/P1 中**元数据最完整**的源；atiifact 已有 CLI 日志→ATIF 的参考实现（**I**）。
5. **Cline** — CLI 与 VS Code 双 store、JSON 直读，且记录 `exit_code/status`（成功/失败）这类其它 harness 少有的语义，能直接喂 ATIF 的 step 状态。
6. **Grok Build** — 目录/schema 已在 **C** 中逐文件给出（events/chat_history/subagents/compaction/rewind），JSONL 多文件易解析；xAI 用户增长快，且 Hermes/OpenClaw 可参考同一「JSONL + SQLite 索引」模式。

> 备选（第 7、8）：**Hermes**（SQLite + 现成 fixture，含 `actual_cost_usd` 可用作成本校验）、**Aider**（Markdown 历史，10 分钟可完成，作为「非结构化源」样板）。

---

## 6. 未核实清单与风险

**未核实（G，需补采/确认后才能排期）**
- Claude Desktop/Cowork 本地会话文件与是否加密；
- Kimi CLI 真实 transcript（本机 `sessions/` 为空）、Kimi Code schema；
- iFlow CLI 是否存在本地 store 及其家族归属；
- Roo Code / Kilo Code 实际默认路径（仅 fixture 线索）；
- Continue / Crush / Zed / Amp / Factory Droid 的本地路径与格式；
- Trae / MiniMax Code / ZCode / Command Code 的原生 store（Codeg 只自记 transcript）；
- Windsurf/Goose/OpenClaw 真实（非 fixture）样本与版本覆盖。

**风险**
- **格式漂移**：Agent Sessions/TokenTelemetry 都记录了多个 harness 的 schema 变更（如 fx 0.0.8、OpenCode 2.x、Codex Desktop 压缩），adapter 必须有 `format_version` 探测 + 宽松容错（协议 §4 要求未知内容进 `warnings`）。
- **隐私**：Grok `rewind_points.jsonl`/`prompts/*.txt`、Copilot `turns`、OpenCode `part.data`、Cursor `agentKv:blob` 均含原文；reader 只抽取必要字段，任何样本入库前必须脱敏（参照 `samples/` 现有做法）。
- **加密/无 schema 部分**（Qoder state.json、Antigravity `.pb`、Claude Desktop）：不承诺迁移，lossy 清单里显式声明。

---

## 7. 参考链接（一手来源）

- 协议：`docs/atif-interop-protocol.md`；格式逆向：`docs/formats/{codex,qoder,omp,dsh}.md`；本地样本：`samples/{codex,qoder,omp,dsh}/`
- ATIF 规范：https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md
- Codeg 支持列表与路径表：https://docs.codeg.app/guide/supported-agents
- TokenTelemetry Harness Survey：https://github.com/VasiHemanth/tokentelemetry/tree/main/docs/research/harness-survey
- Agent Sessions 支持矩阵/Stewards：https://github.com/jazzyalex/agent-sessions/blob/main/STEWARDS.md
- sessionport fixtures：https://github.com/Reality-Shifting-Tech/sessionport/tree/main/tests/fixtures
- Qoder 官方 sessions 文档：https://docs.qoder.com/cli/sessions
- oh-my-pi 官方 session 文档：https://github.com/can1357/oh-my-pi/blob/main/docs/session.md
- 本机实测版本：Codex 0.165 / Qoder CLI 1.1.75 / OMP 18.12.6 / DSH Desktop 0.2.1-rc.3（见 `README.md`）
