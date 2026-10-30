# Agent Session 互转 / ATIF / 统一管理 App —— Web 研究报告

- 研究人：webresearch（Team 成员）
- 时间：2026-10-30（Asia/Shanghai）
- 范围：ATIF 规范真实性、现有 session 转换工具/包、统一管理多 harness session 的开源桌面 App、可复用组件
- 依据：只采信原始仓库 / 官方文档 / 包注册表 API，全部条目附 URL；检索无果的结论会显式标注检索次数与关键词

---

## 0. 结论速览（TL;DR）

1. **ATIF 真实存在**，正式名称 *Agent Trajectory Interchange Format*，是 **Harbor 项目**的 RFC 0001 规范（当前 v1.8，维护者 Boxuan Li，Apache-2.0 仓库）。
   - 规范原文：https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md
   - 但它定位是**轨迹日志/评测/训练数据格式**（debug、可视化、SFT、RL），**不是**「另一个 harness 能直接 resume 的 session 文件格式」。
2. **没有成熟的「harness session 原生格式互转」通用包**（如 Codex rollout ↔ Claude Code JSONL ↔ Qoder JSONL ↔ DSH v4）。目前生态只有三种替代路径：
   - **聚合 + 原 agent 恢复**：Codeg、Agent Sessions（只读式索引，恢复时交还给原 agent）；
   - **摘要/简报迁移**：sessionport（把任意 session 提炼成 markdown brief，再作为新 agent 的 resume prompt）；
   - **单向导出为分析格式**：atifact / atif-sql / everruns 等把 Codex、Claude Code 日志转成 ATIF。
   - 证据：GitHub repo 检索 `session converter agent cli` 命中 **0** 个仓库；npm search `agent session converter` 无相关包（详见 §5）。
3. **存在一站式管理多 harness session 的开源桌面 App**：**Codeg**（4,210★，Apache-2.0，Rust，桌面/服务端/Docker/移动端；内置 20 个 agent，明确含 **Qoder、DeepSeek Harness、Pi、Codex、Claude Code**）；**Agent Sessions**（924★，MIT，macOS 原生 App，16 个来源含 **DeepSeek Harness**、Codex、Claude Code、Pi）。
   - 但二者都**不做 session 格式互转**：Codeg 是「导入引用 + 在原 agent 内继续 + `@` 跨 agent 只读摘要」，Agent Sessions 是「只读浏览/搜索/复制 resume 命令」。
4. 对「把 Qoder / OMP / Codex 的 session 导入 DSH」：**不存在开箱即用方案，需要自研 importer**，但可复用组件很明确（见 §6）。

---

## 1. ATIF 事实核查

### 1.1 出处与状态（已 web_fetch 原始文件核实）

| 项 | 内容 |
|---|---|
| 全称 | Agent Trajectory Interchange Format (ATIF) |
| 出处 | Harbor 项目 RFC 0001：`harbor-framework/harbor` 仓库 `rfcs/0001-trajectory-format.md` |
| 规范 URL | https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md （raw 已抓取，HTTP 200） |
| 当前版本 | **v1.8**（v1.0 初版起；v1.6 图像/多模态、v1.7 subagent 嵌入 + trajectory_id、v1.8 audio） |
| 状态 / 维护者 | Status: Active；Maintainer: Boxuan Li；文档日期 April 2026 |
| 所属项目 | Harbor：https://github.com/harbor-framework/harbor （6,625★，Apache-2.0，Python，最近 push 2026-10-29；topics: evals / rl-environments / terminal-bench；主页 https://harborframework.com/）——GitHub API 核实 |
| 引用关系佐证 | PyPI `atif` 包的 Specification 链接、everruns 的 `specs/atif-adoption.md` 均指向上面的 canonical RFC，说明该文件是唯一权威出处 |

### 1.2 定位（关键判断）

RFC 开篇明确：ATIF 用于「logging the complete interaction history of autonomous LLM agents」，目标场景是 **debugging、visualization、SFT、RL pipelines**，并作为 Harbor 项目的标准日志格式。规范里**没有**「session 可被某个 harness 直接 resume」的语义（无 agent 内部状态、无 checkpoint、无 harness 私有事件流）。

→ 结论：**ATIF ≈ 轨迹交换/训练数据格式，不是 harness 间 session 交互协议**。用它做「统一中转格式」可行，但必须自己补「ATIF → 目标 harness session」的最后一段（目前无人实现，见 §5）。

### 1.3 字段结构摘要（v1.8）

根对象：
- `schema_version`（如 `"ATIF-v1.8"`）、`session_id`（v1.7 起可选，run 级）、`trajectory_id`（v1.7+，文档级唯一）、`agent`、`steps[]`（必填）
- `notes`、`final_metrics`、`continued_trajectory_ref`、`extra`、`subagent_trajectories[]`

`agent`：`name`（如 `"claude-code"`）、`version` 必填；`model_name`、`tool_definitions`（OpenAI function-calling 结构）、`extra` 可选。

`steps[]`（每项）：
- `step_id`（从 1 递增）、`source` ∈ `system|user|agent`、`timestamp`、`message`（string 或 `ContentPart[]`）
- agent 步骤：`model_name`、`reasoning_effort`、`reasoning_content`、`tool_calls[]`、`observation.results[]`、`metrics`
- `tool_calls[]`：`tool_call_id`、`function_name`、`arguments`（JSON object）、`extra`
- `observation.results[]`：`source_call_id`、`content`、`subagent_trajectory_ref[]`（v1.7 起按 `trajectory_id` 或 `trajectory_path` 解析）
- `metrics`：`prompt_tokens`、`completion_tokens`、`cached_tokens`、`cost_usd`、`prompt_token_ids`/`completion_token_ids`、`logprobs`、`extra`
- 扩展：`llm_call_count`（v1.7，`0` 表示确定性编排）、`is_copied_context`（压缩上下文标记，SFT 需过滤）
- `extra.context_management = {type: compaction|pruning|injection, boundary: replace|append|truncate}`（v1.7 约定）

多模态：`ContentPart` = text / image（v1.6）/ audio（v1.8）；`ImageSource{media_type,path}`、`AudioSource{media_type,path,duration_sec}`，媒体文件放在轨迹文件旁的 `images/`、`audio/` 目录，按相对路径引用。

### 1.4 实现与生态（均核实存在）

| 名称 | 类型 | 语言/许可 | 成熟度（核实值） | 与 ATIF 的关系 |
|---|---|---|---|---|
| Harbor 参考实现 | 官方模型 + 校验 CLI | Python / Apache-2.0 | 6,625★，活跃 | `src/harbor/models/trajectories/` Pydantic 模型；`src/harbor/utils/trajectory_validator.py`（RFC §VI） |
| `atif` (PyPI) | 第三方 Pydantic 模型库 | Python / MIT | v1.8.0，2026-10-11 发布；自述 “**not an official implementation**” | 实现 ATIF v1.8；repo：https://github.com/bolu61/python-atif ；发布者 alexgshaw |
| everruns | Agent harness（Rust，MIT，62★，push 2026-10-29） | Rust | 已上线 | **ATIF 实际采用者**：`GET /v1/sessions/{id}/export?format=atif`、dataset export、`POST /v1/evals/{eval_id}/atif_import`；导出 pin `ATIF-v1.7`，导入容忍任意 `ATIF-*`；spec：`specs/atif-adoption.md`（raw 已核实） |
| atifact | CLI 转换器 | TypeScript / MIT，6★，push 2026-10-14 | 活跃小项目 | **HAR / Claude Code / Copilot CLI / Codex CLI 日志 → ATIF v1.7**：https://github.com/waldekmastykarz/atifact |
| atif-sql | 分析管线 | 仓库描述：Claude Code sessions → ATIF → DuckDB corpus | 存在性已核实 | https://github.com/laithalsaadoon/atif-sql |
| trajectory-fidelity-bridge | 转换器 | Python / MIT，2★，push 2026-10-29 | 活跃小项目 | Claude Code → ATIF v1.7，带保真度核算/脱敏：https://github.com/atomicdjt/trajectory-fidelity-bridge |
| TrajectoryLite | 轻量采集 + adapters | Python / MIT，1★ | 原型 | https://github.com/fyyqwq/TrajectoryLite |
| ATIF-trajectory-viewer | Web 可视化 | TS / Apache-2.0，27★ | 有在线 demo | https://github.com/Slimshilin/ATIF-trajectory-viewer |
| atif-lens | CLI 查看器 + shadcn 组件 | TS / MIT，6★ | 小项目 | https://github.com/Eli-Chandler/atif-lens |
| vsc-atifviz | VSCode 扩展 | TS / MIT，1★ | 小项目 | https://github.com/waldekmastykarz/vsc-atifviz |
| atif-rust | Rust crate | Rust / MIT，0★ | 原型 | https://github.com/leto-labs/atif-rust |
| agentpile | 数据集加载器 | Python / Apache-2.0，31★ | 新项目（2026-10） | 把公开 agent-trajectory 数据集/轨迹加载为 ATIF 记录：https://github.com/yzhao062/agentpile |

**ATIF 生态方向性**：仓库检索 `ATIF trajectory` 共 23 个仓库，清一色是「→ ATIF」（导入器/查看器/分析/数据集），**未发现任何 ATIF → 具体 harness session 的导出器**（见 §5）。

---

## 2. Session 转换 / 迁移工具（含「最接近」的候选）

> 判定标准：能读 A harness 的本地 session，并让 B harness 用它继续工作。
> 注意区分三种实际能力：**格式重写**（真转换）／**摘要迁移**（提炼 brief 作为 resume prompt）／**引用恢复**（索引原文件，交还原 agent）。

| 工具 | 形态/许可/成熟度 | 覆盖 harness | 方向与机制 | 限制 |
|---|---|---|---|---|
| **sessionport** | PyPI 0.3.0（2026-08-06）/ MIT / 1★（2026-08-06 单日提交，极早期） | Claude Code、Codex、OpenCode、Gemini CLI、Hermes、Cursor、Aider、Windsurf、OpenClaw、Cline（README §Supported agents） | CLI：`list / export / import / score / mcp`。**摘要迁移**：读本地 store → 确定性启发式提炼 `sessionport-brief/v1` markdown（Goal/Decisions/State/Constraints…）→ `import --into <agent>` 生成 resume prompt；可接 MCP。离线，无 LLM（score 才可选调 LLM） | **不写任何原生 session 文件**，目标 agent 拿到的是文字简报；适配器最新只到 README 所列（仓库 `tests/fixtures/` 还含 Copilot/Grok/Goose/Junie/Kilo/Vibe 样例），**无 Qoder / OMP / DSH** |
| **Codeg** | 桌面 App + 自托管 Server + Docker + iOS/Android / Apache-2.0 / **4,210★，535 forks，Rust，push 2026-10-29** | 内置 20 个 agent：Claude Code、Codex、Gemini CLI、OpenClaw、OpenCode、Cline、Hermes、CodeBuddy、Kimi Code、MiniMax Code、Pi、Grok、Cursor、**DeepSeek Harness**、**Qoder**、Antigravity、Kiro CLI、ZCode、TRAE CLI、Command Code，+ 任意 ACP agent | **聚合 + 引用恢复**：扫描各 agent 原生 store → 导入会话引用 → 打开即在**原 agent** 内续聊（history 从磁盘实时读取）；`@` 引用其他 agent 的会话（只读、精简最近轮次，非完整上下文转移，「Not a transfer of context」） | 不重写 session 文件；跨 agent 只能通过 `@` 摘要；Codeg 未在支持列表里出现 **OMP（oh-my-pi）**；Qoder 等部分来源依赖其自身 store 存在 |
| **Agent Sessions** | macOS 原生 App（Swift）/ MIT / **924★，66 forks，v6.2，push 2026-10-27** | 16 个来源：Codex、Claude Code、Cursor、Copilot CLI、OpenCode、Antigravity、Pi、Kimi Code、Grok CLI、Hermes、OpenClaw、Qwen Code、Devin CLI、fx、Cline、**DeepSeek Harness**（Droid 为 legacy） | **只读索引 + 恢复**：本地索引/搜索/查看 transcript、Session Info、配额燃烧；对支持项复制 resume 命令或开终端 | 明确「read-only」「session folders are read rather than rewritten」；**无导出/转换**；不含 Qoder/OMP |
| **Session-Viewer**（goblin-red） | macOS Swift / MIT / 0★，push 2026-10-06 | Claude Code、Codex、Grok、OpenCode | 浏览 + **把终端 session 导入 Claude / Codex 桌面 App** | 极小项目；只支持导入到 Claude/Codex 两家 |
| **Omnigent**（Databricks） | PyPI 0.20.0（2026-10-28）/ Apache-2.0 / alpha | Claude Code、Codex、Cursor、OpenCode、Hermes、Pi、Antigravity、Copilot、Devin、Kiro、Grok + 自定义 YAML agent | **Meta-harness**：统一编排层，自己的 server/desktop/web 管理会话；可混用多个 harness | 不是「接管已有本地 session 并互转」；会话以 Omnigent 自管为主 |
| **agent-session-viewer**（dhruv-anand） | npm 0.1.36 / MIT / repo 9★，push 2026-08-06 | Claude Code、Cursor、Codex、OpenCode、Hermes、Antigravity | 本地 daemon + Web UI 的实时 session viewer | 只读查看，无转换 |
| **pi-search**（oreid-zd） | Python / 0★ | Pi | fzf 式 pi session 搜索/查看 | 只读；可作 OMP/pi 系格式参考 |

**结论**：真正「读写另一种 harness 原生 session 文件」的工具，在本次检索范围内**一个都没有**。最接近「转换」体验的是 Codeg（跨 agent 引用）与 sessionport（brief 迁移），二者都是**语义迁移而非格式互转**。

---

## 3. 你的三个来源的格式事实（供 importer 设计）

### 3.1 Qoder（阿里）

- **官方文档已确认本地路径**：`~/.qoder/projects/<processed-project-path-name>/<session-id>.jsonl` 存对话日志，`<session-id>/state.json` 存会话状态；`QODER_CONFIG_DIR` 可改根目录；CLI 支持 `-c/--continue`、`-r/--resume`、`--fork-session`、`/export`、`--list-sessions`。
  - https://docs.qoder.com/cli/sessions
- **第三方文件系统调查（与你的本机结构一致）**：Qoder CLI 是 **Claude Code 的衍生物**，`~/.qoder` 布局与 `~/.claude` 相同，记录含 `cwd/gitBranch/isSidechain/parentUuid/sessionId/version/userType/entrypoint`，「Claude Code's schema verbatim」；额外记录类型 `workspace-directories / runtime-config / last-prompt / active-leaf / attachment`；**usage 里 token 全为 0，只记 credits**；`state.json` 加密；`~/Library/Application Support/com.qoder.app.stable/main.sqlite` 是同一批 session 的投影（勿重复计数）。
  - https://github.com/vasihemanth/tokentelemetry/blob/b637b1ae12799639bcb119019617093f3d770483/docs/research/harness-survey/harness-qoder.md
- **已有采集适配器设计（Rust）**：relayhistory 的 Qoder provider 针对 `@qoder-ai/qodercli` 1.1.75，解析 `<config>/projects/<project-hash>/<session-id>.jsonl`，有 writer/reader fixture 验证（session UUID、parentUUID、model、tool-use/result ID、cwd、时间戳、resume append）。
  - https://github.com/agentworkforce/relayhistory/blob/d7ed15606b0416ab5b6ee39d8fe1b01634954ec3/plans/history-providers/qoder.md
  - 注：这是 plan 文档（issue #457），成熟度未核实，不可当作可直接依赖的库。

### 3.2 OMP（oh-my-pi，pi 系 TUI）

- 官方仓库：https://github.com/can1357/oh-my-pi （**37,066★，MIT，TypeScript，push 2026-10-29**，主页 https://omp.sh），描述 “Coding agent with the IDE wired in. Built by Stencil Labs.”——即你所说的 OMP。
- 官方 session 文档在仓库内（docs 目录已核实存在）：
  - `docs/session.md`（51 KB，session 格式/生命周期）
  - `docs/session-operations-export-share-fork-resume.md`（53 KB，导出/分享/分叉/恢复）
  - `docs/session-switching-and-recent-listing.md`、`docs/session-tree-plan.md`
  - 目录：https://github.com/can1357/oh-my-pi/tree/main/docs
- `omp.sh/docs/session-format` 页面是 JS 渲染，web_fetch 只拿到导航壳；以上仓库文档是可解析的原始来源。
- **未找到** OMP 与其他 harness 之间的转换工具（见 §5）；Agent Sessions / sessionport / Codeg 支持列表里均无 OMP（Codeg 只写了 Pi）。

### 3.3 Codex

- Codex session 是 `~/.codex/sessions/**/rollout-*.jsonl`（用户本机已确认），是生态里被支持最广的格式：
  - sessionport 支持 `~/.codex/sessions`（README）；
  - atifact 支持 Codex CLI 日志 → ATIF v1.7（README）；
  - Agent Sessions 支持 Codex（含 Codex 桌面 App 的 `.jsonl.zst` 压缩会话，只读不改）；
  - Codeg 支持 Codex 会话聚合与原 agent 续聊。

---

## 4. 「统一管理全种类 session」的开源 Desktop App —— 直接回答

**有，但能力边界要说清**：

- **Codeg**（首选，最接近你描述的一站式）：桌面 App / Server / Docker / 移动端；一个界面管 20 个 agent 的会话；可扫描整机所有 agent 的 session store、按项目分组导入、搜索、在原 agent 内继续、`@` 跨 agent 引用；明确支持 **Qoder** 与 **DeepSeek Harness**。
  - 关键文档：https://docs.codeg.app/guide/aggregation
  - 仓库：https://github.com/spacering-net/codeg
- **Agent Sessions**（macOS 原生，浏览/检索最佳）：16 个来源，含 DSH 与 Pi；有配额/成本视图；只读。
  - 仓库：https://github.com/jazzyalex/agent-sessions
- **不存在**「勾选 A/B harness session → 一键转成 C harness 原生文件」的开源桌面 App；Codeg 的「hand it to a different agent」是 `@` 只读摘要，不是格式转换（官方原文：*Read-only... Not a transfer of context*）。

---

## 5. 检索记录与「未找到」证据

所有检索于 2026-10-30 执行：

| 检索 | 结果 |
|---|---|
| GitHub repo search `session converter agent cli` | **total_count = 0**（`https://api.github.com/search/repositories?q=session+converter+agent+cli`） |
| GitHub repo search `ATIF trajectory` | 23 个仓库，全部为 → ATIF 的导入/查看/分析工具，**无 ATIF → harness 导出器**（`https://api.github.com/search/repositories?q=ATIF+trajectory`） |
| GitHub repo search `agent session history viewer` | 19 个，均为 viewer/browser，无转换器 |
| npm search `agent session converter` | 无相关包（结果全是无关的 converter 库） |
| PyPI 检索 ATIF / session 转换 | 仅 `atif`（第三方模型库）、`sessionport`（brief 迁移）、`omnigent`（meta-harness）等；无 harness 间格式互转包 |
| 关键词 `codex session converter claude code`、`qoder session export`、`omp agent session format`、`trajectory interchange format`、`session migration agent harness`、`agent-history` | 无「原生互转工具」命中；仅命中上述 viewer/aggregator/ATIF 工具与 Qoder/OMP 官方文档 |

**明确结论**：
- 「统一包/工具把 A harness session 直接转成 B harness session」：**未找到**（多次检索 + GitHub/npm/PyPI 均无）。
- 「ATIF 规范本身」：**真实存在**（Harbor RFC 0001，v1.8）。
- 「ATIF → 任意 harness session」的成品：**未找到**（只有 → ATIF 方向）。
- 「Qoder 专用转换工具」：**未找到**；只有 relayhistory 的 Qoder 历史采集 plan（Rust）与 tokentelemetry 的格式调查。
- 「OMP 专用转换工具」：**未找到**。

---

## 6. 对「导入 Qoder / OMP / Codex 到 DSH」的可复用组件清单

> 目标链路建议：**source adapter（读原生 store）→ 统一中间模型（可直接用 ATIF 的 Step/ToolCall/Observation 字段）→ DSH session 写入器（`session.v4.jsonl.zstd`，zstd framed JSONL）**。
> 注意：ATIF 缺少 DSH 私有事件（compaction、subagent、系统钩子等）与 resume 状态，中间层要预留 `extra`，且**不能**指望直接把 ATIF 文件丢给 DSH 使用。

### 可直接复用（代码/格式资产）

1. **sessionport 的 Codex / Claude 系读取层**（Python，MIT）
   - 文件：`src/sessionport/stores.py`（~26 KB，各 agent session store 发现与读取）、`src/sessionport/extract.py`、`src/sessionport/brief.py`、`src/sessionport/models.py`、`src/sessionport/cli.py`、`src/sessionport/mcp_server.py`
   - 仓库：https://github.com/Reality-Shifting-Tech/sessionport
   - 价值：Codex rollout JSONL 解析、Claude Code JSONL 解析（Qoder 与其同构，改根路径即可）、统一中间结构；`tests/fixtures/`（codex、claude-code、cursor、gemini、opencode、copilot、grok、goose、junie、kilo、vibe、windsurf 等小样本）可直接做回归测试。
   - 注意：2026-08-06 单日发布，1★，ADR 齐全但未经验证，需自行兜底。
2. **atifact 的 Codex / Claude → ATIF 转换器**（TypeScript，MIT）
   - 仓库：https://github.com/waldekmastykarz/atifact（含 HAR / Claude Code / Copilot CLI / Codex CLI 四类输入）
   - 价值：若 DSH 想要「先统一成 ATIF 再落库」，这是现成的 Codex 段实现。
3. **ATIF 官方的 Pydantic 模型与校验器**（Python，Apache-2.0）
   - 路径：Harbor 仓库 `src/harbor/models/trajectories/*.py`、`src/harbor/utils/trajectory_validator.py`
   - 轻量替代：`pip install atif`（MIT，v1.8.0，第三方实现，`Trajectory.model_validate` + `to_json_dict(exclude_none=True)`）
   - 价值：中间层 schema 校验；代价是 Python 侧依赖。
4. **everruns 的事件日志 → ATIF fold 实现（Rust，MIT）**
   - 路径：`crates/server/src/atif.rs`；spec：`specs/atif-adoption.md`
   - 价值：真·生产级 fold 参考，含 image ContentPart、subagent_trajectory_ref、segmented export（`continued_trajectory_ref` + opaque cursor）、导入侧容忍未知版本；若 DSH 用 Rust/TS 写转换器，可对照其字段映射表。
5. **Qoder 格式的权威资料**
   - 官方路径说明：https://docs.qoder.com/cli/sessions
   - 逐字段调查（Claude Code 衍生、记录类型、credits、加密 state.json、SQLite 投影）：tokentelemetry `docs/research/harness-survey/harness-qoder.md`
   - 可复用代码思路：relayhistory `plans/history-providers/qoder.md` + fixtures（Rust；写入/读取验证脚本 `fixtures/qoder/capture.mjs`）；**注意它尚未发布为库，只可借鉴实现**
   - 结论：**直接复用 Claude Code JSONL 解析器、把根路径换成 `~/.qoder/projects` 是最省成本路径**（schema 逐字兼容，仅多出 `workspace-directories/runtime-config/last-prompt/active-leaf/attachment` 类型，需按 allowlist 过滤）。
6. **OMP（oh-my-pi）格式资料**
   - https://github.com/can1357/oh-my-pi/blob/main/docs/session.md
   - https://github.com/can1357/oh-my-pi/blob/main/docs/session-operations-export-share-fork-resume.md
   - 无现成解析器可复用；pi 系可参考 pi-search（fzf viewer）与 Agent Sessions 的 Pi source。
7. **「各 agent session 存在哪里 / 哪些版本验证过」的元数据**
   - Agent Sessions：`STEWARDS.md`（各来源格式维护人、验证日期、测试版本）、`ThirdParty/DSHZstd/`（vendored Zstandard 1.5.7 + DSH v4 zstd 解码，说明其已逆向过 DSH 的 framed JSONL + checksum 结构——对写 DSH importer/writer 有参考价值）
   - Codeg 的 supported-agents 文档：https://docs.codeg.app/guide/supported-agents （列出每个 agent 的 session 存储位置；本次抓取 HTML 页未展开正文，README 已确认 20 agent 名单）
8. **交叉验证样本来源**：sessionport `tests/fixtures/`、everruns `specs/atif-adoption.md` 的字段映射表、Harbor RFC §V 附带的 3 份真实轨迹示例（mini-swe-agent / openhands / gemini-cli）。

### 不建议依赖

- **ATIF 直接当 DSH session**：ATIF 是日志格式，无 DSH 事件类型/harness 状态，且生态里没有 ATIF → harness 的写入器。
- **sessionport 的 brief 当唯一导入路径**：会丢 tool 调用细节与文件 diff，只适合「迁移上下文/待办」，不适合保真导入。
- **把 Codeg 当转换器**：官方明确 `@` 引用是只读摘要，不转移上下文。

---

## 7. 参考链接汇总

**规范/项目**
- Harbor RFC 0001 (ATIF v1.8): https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md
- Harbor repo: https://github.com/harbor-framework/harbor
- ATIF adopters: https://github.com/everruns/everruns/blob/26ff77ef5d33ee529eb05bb9c95def091a475fc2/specs/atif-adoption.md
- PyPI `atif`: https://pypi.org/project/atif/ （repo: https://github.com/bolu61/python-atif）

**转换/聚合工具**
- sessionport: https://pypi.org/project/sessionport/ ，https://github.com/Reality-Shifting-Tech/sessionport
- Codeg: https://github.com/spacering-net/codeg ，聚合文档 https://docs.codeg.app/guide/aggregation ，支持列表 https://docs.codeg.app/guide/supported-agents
- Agent Sessions: https://github.com/jazzyalex/agent-sessions
- Omnigent: https://pypi.org/project/omnigent/ ，https://github.com/omnigent-ai/omnigent
- agent-session-viewer: https://www.npmjs.com/package/agent-session-viewer ，https://github.com/dhruv-anand-aintech/agent-session-viewer
- Session-Viewer: https://github.com/goblin-red/Session-Viewer
- pi-search: https://github.com/oreid-zd/pi-search

**ATIF 工具**
- atifact: https://github.com/waldekmastykarz/atifact
- atif-sql: https://github.com/laithalsaadoon/atif-sql
- trajectory-fidelity-bridge: https://github.com/atomicdjt/trajectory-fidelity-bridge
- TrajectoryLite: https://github.com/fyyqwq/TrajectoryLite
- ATIF-trajectory-viewer: https://github.com/Slimshilin/ATIF-trajectory-viewer
- atif-lens: https://github.com/Eli-Chandler/atif-lens
- vsc-atifviz: https://github.com/waldekmastykarz/vsc-atifviz
- atif-rust: https://github.com/leto-labs/atif-rust
- agentpile: https://github.com/yzhao062/agentpile

**来源 harness 格式**
- Qoder sessions 官方: https://docs.qoder.com/cli/sessions
- Qoder 文件系统调查: https://github.com/vasihemanth/tokentelemetry/blob/b637b1ae12799639bcb119019617093f3d770483/docs/research/harness-survey/harness-qoder.md
- relayhistory Qoder adapter plan: https://github.com/agentworkforce/relayhistory/blob/d7ed15606b0416ab5b6ee39d8fe1b01634954ec3/plans/history-providers/qoder.md
- oh-my-pi (OMP): https://github.com/can1357/oh-my-pi ，session 文档 https://github.com/can1357/oh-my-pi/blob/main/docs/session.md

**检索接口**
- GitHub search API 查询见 §5；npm registry search: `https://registry.npmjs.org/-/v1/search?text=agent%20session%20converter`；PyPI JSON API: `https://pypi.org/pypi/<pkg>/json`
