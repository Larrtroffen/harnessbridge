# 批 5 公开样本来源（SOURCE.md）

> 采集时间：2026-10-30｜执行：batch3-recon（shared task-22）｜目录：`samples/batch5/`（102 文件 / ≈600 KB）
> 用途：为批 5 寻找**新的原生 session schema 证据**（不是又一个简化 `{role,content}` 形状），供 `docs/formats/batch5-fixtures.md` 的 Reader/Writer 方案与测试计划使用。
> 纪律：只从公开仓库复制**小文件**（单文件 ≤2 MB、总量 ≤50 MB）；全部落到本目录，`/tmp` 下的克隆不进入 workspace；不改用户数据。

## 仓库清单

| # | 仓库 | commit / 日期 | License | 复制范围（本目录相对路径） | 用途 |
|---|---|---|---|---|---|
| 1 | [jazzyalex/agent-sessions](https://github.com/jazzyalex/agent-sessions) | `8ca7aa603fe5` / 2026-10-27 | **MIT**（`LICENSES/agent-sessions` 见批 2 目录；本批仅复制文件，未重复许可证副本） | `agent-sessions/**`：Cline `*.messages.json`×3、FX `schema4/**`、OpenCode `sqlite_v2/**`+`storage_v2/**`+`storage_legacy/**`、OpenClaw `sqlite/openclaw-agent.sql`、Kimi `assistant_tools*`/`state.json`/`subagent_agent-0.jsonl`、Gemini `jsonl_v040.jsonl`/`schema_drift.json`/`large.json`、Qwen 5 个新增会话 + `system_telemetry.jsonl`、Devin/Hermes/Droid/Copilot/Cursor/Grok/Claude/Codex 的 `schema_drift`/`large`/`subagent` 变体、Cursor IDE `cursor-ide/test-store.db` | 现有 harness 证据升级 + FX/Cline/OpenCode 补齐 |
| 2 | [spacering-net/codeg](https://github.com/spacering-net/codeg) | `54f07a112433` / 2026-10-29 | **Apache-2.0** | `codeg/antigravity/{agy-fixture-001.db,agy-fixture-001.meta}`（原生 SQLite 样本，`steps(idx,step_payload)`，payload 为 `gemini_coder.Step` protobuf）；`kiro/**`（**derived**：从 `src-tauri/src/parsers/kiro.rs` 测试常量提取的 kiro-cli 2.24.1 会话记录，见下）；`codebuddy/**`（**derived**：从 `src-tauri/src/parsers/codebuddy.rs` 测试构造的 CodeBuddy 原生 JSONL 记录） | 新 Harness：Kiro CLI、CodeBuddy；Antigravity 原生 SQLite |
| 3 | [harbor-framework/harbor](https://github.com/harbor-framework/harbor) | `7e0354ce0900` / 2026-10-29 | **Apache-2.0** | `harbor/openhands_trajectory.json`（62,847 B，RFC 0001 §V 真实 OpenHands 轨迹样例）、`harbor/mini-swe-agent-trajectory.json`（15,173 B，`mini-swe-agent-1` 格式样例） | 新 Harness：OpenHands（真实轨迹）；Mini-SWE-agent（候选） |
| 4 | [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe) | `main` HEAD / 2026-10-30 | **Apache-2.0** | **无上游文件复制**；`vibe/constructed-session/**` 为**本批构造样本**，布局/字段来自仓库源码 `tests/stubs/historical_session.py` + `vibe/core/types.py::LLMMessage` | 新 Harness：Mistral Vibe（FIXTURE-CONSTRUCTED） |

## 未复制/排除（明确记录，避免误用）

| 仓库 | 检查结果 | 处置 |
|---|---|---|
| [charmbracelet/crush](https://github.com/charmbracelet/crush) | 有 `internal/db/migrations/*.sql`（sessions/messages 表结构）；**License = Functional Source License v1.1（not MIT/Apache）** | **不复制文件**；仅在本批文档中记录 schema 事实（表/列名）并标 `FIXTURE-CONSTRUCTED` 候选，vendor 前需 Lead 审视许可证 |
| [block/goose](https://github.com/block/goose) | 全库 2,529 文件扫描：无 session（JSON/JSONL）fixture（仅 `tests/acp_test_data/openai_models.json`） | 不复制；列为 CANDIDATE（源码定义格式） |
| [continuedev/continue](https://github.com/continuedev/continue) | 3,058 文件扫描：无 session fixture | 不复制；CANDIDATE |
| [RooCodeInc/Roo-Code](https://github.com/RooCodeInc/Roo-Code) | 3,022 文件扫描：仅 provider 模型列表 fixtures，无会话历史 fixture | 不复制；CANDIDATE（Cline 族） |
| [zed-industries/zed](https://github.com/zed-industries/zed) | 4,389 文件扫描：`test_data` 均为 git/vim/task 等，无 agent 会话 fixture | 不复制；CANDIDATE |
| [Kilo-Org/kilocode](https://github.com/Kilo-Org/kilocode) | 51 MB 源码：fixtures 为 UI `.tsx`/provider recordings，无原生会话 fixture | 不复制；BLOCKED |
| vercel-labs/fx | 8 MB 源码：未发现 schema 4 事件样本（agent-sessions 仓库中有更完整 `fx/schema4`） | 不复制；以 agent-sessions 为准 |
| JetBrains/junie-guide、Warp、Replit | 无公开 session fixture/仓库 | 不复制；BLOCKED / 仅 ATIF 导出 |

## 派生样本（derived）标注

以下文件**不是上游 fixture 原文件**，由本批从 Apache-2.0 源码的测试数据/格式定义派生，内容为合成/短化，**使用/分发时须保留来源与 license 说明**：

| 文件 | 派生自 | 说明 |
|---|---|---|
| `kiro/sessions/7787f985-…/session.jsonl` | codeg `src-tauri/src/parsers/kiro.rs` 测试常量（作者注明「captured from a real kiro-cli acp 2.24.1 session，signatures/digests trimmed」） | 8 条事件记录；`session.json` 为同测试的 metadata 结构 |
| `codebuddy/item-format.jsonl`、`codebuddy/tool-format.jsonl` | codeg `src-tauri/src/parsers/codebuddy.rs` 测试中的 `json!` 记录 | 两种 CodeBuddy 记录形态（item-format / function_call 格式） |
| `vibe/constructed-session/{meta.json,messages.jsonl}` | mistral-vibe 仓库源码（session 目录布局 + `LLMMessage` 字段） | 明确标注 constructed；非上游 fixture |

## 目录说明：`constructed/`（非本任务产出）

`samples/batch5/constructed/**` 由并行的批 5 adapter 实施任务（converter-dev）生成，用于构造 golden sample（cline/roo/kilo-code/openhands/kiro/junie 等）；**不属于本侦察任务的样本清单**，本任务不据此计数，清单以本文件§仓库清单 + `docs/formats/batch5-fixtures.md` 为准。

## 复现方式（只读）

```bash
# agent-sessions（MIT）与 codeg（Apache-2.0）均为 codeload tarball 或 GitHub API contents（本机 github.com:443 直连受限，raw/codeload 可用）
curl -sL -o /tmp/as.tgz https://codeload.github.com/jazzyalex/agent-sessions/tar.gz/refs/heads/main
curl -sL -o /tmp/codeg.tgz https://codeload.github.com/spacering-net/codeg/tar.gz/refs/heads/main
curl -sL -o /tmp/harbor.tgz https://codeload.github.com/harbor-framework/harbor/tar.gz/refs/heads/main
# OpenHands 样例若 raw 被截断，改用 contents API（base64）
curl -sL https://api.github.com/repos/harbor-framework/harbor/contents/rfcs/0001-trajectory-format/openhands_trajectory.json
```

## 许可与合规声明

- 本目录复制文件均来自 **MIT（agent-sessions）** 或 **Apache-2.0（codeg/harbor）** 仓库；派生样本沿用对应仓库 license 并保留出处。
- **未复制任何 FSL / 专有 / 未明示许可**的仓库内容（Crush 仅记录表结构事实）。
- 样本为**合成/截断/真实示例**混合：agent-sessions 为合成 stage0 fixtures；harbor 样例为真实轨迹示例；derived 标注见上。**任何样本都不得冒充真实用户会话**（证据等级见 `docs/formats/batch5-fixtures.md`）。
