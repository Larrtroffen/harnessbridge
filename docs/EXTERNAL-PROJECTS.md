# 外部同类项目与可复用样本（调研摘要）

> 日期：2026-10-31｜目的：为 HarnessBridge 的 30-40 Harness 支持找可复用实现、格式事实与 fixture。
> 纪律：外部项目只作参考，未 vendor 任何受限代码/资产；样本按各自许可使用并在各目录 `SOURCE.md` 记录。

## 1. 同类项目

| 项目 | Stars | License | 形态 | 与本项目的关系 |
|---|---|---|---|---|
| [luoyuctl/agenttrace](https://github.com/luoyuctl/agenttrace) | 152 | MIT | Rust TUI/CLI 成本审计 | `testdata/` 覆盖 12 个 harness，是本项目外部 fixture 的主要来源之一 |
| [jazzyalex/agent-sessions](https://github.com/jazzyalex/agent-sessions) | 928 | MIT | Swift macOS App | 17 个 source 的 parser 与 fixture（Codex/Claude/OpenCode/Cursor/Antigravity/Hermes/OpenClaw/Copilot/Qwen/Kimi/Grok/Devin/Fx/Cline/Droid/DSH） |
| [spacering-net/codeg](https://github.com/spacering-net/codeg) | 4,239 | Apache-2.0 | Rust 桌面/服务 | `src-tauri/src/parsers/*.rs` 覆盖 20 个 harness，是本项目之外最完整的 parser 集合之一（仅参考结构） |
| [Reality-Shifting-Tech/sessionport](https://github.com/Reality-Shifting-Tech/sessionport) | 1 | MIT | Python CLI | 16 个 store adapter + `tests/fixtures/`（含 Windsurf/Junie/Vibe/Goose/Kilo） |
| [getagentseal/codeburn](https://github.com/getagentseal/codeburn) | 11,633 | MIT | TypeScript CLI | `docs/providers/` 43 个 provider 的路径/字段/quirk 文档 |
| [kenn-io/agentsview](https://github.com/kenn-io/agentsview) | 6,312 | MIT | Go 服务端+Web UI | README 的「Supported Agents」给出约 50 个 agent 的 session 目录，是最全路径清单 |
| [vshulcz/deja-vu](https://github.com/vshulcz/deja-vu) | 1,342 | MIT | Go CLI | `docs/registry/` 约 40 个 harness 的 store 路径与 resume 机制 |
| [VasiHemanth/tokentelemetry](https://github.com/VasiHemanth/tokentelemetry) | 385 | MIT | Python | 20+ harness 的字段级 survey |
| [firstintent/ccteam](https://github.com/firstintent/ccteam) | 640 | MIT | Rust | ACP/exec 驱动多 agent，非 session 读取 |
| [dotneet/agent-session-view](https://github.com/dotneet/agent-session-view) 等 | 小体量 | MIT | viewer | 两源 viewer，参考价值低 |

**结论**：未发现「多 harness 双向转换 + ATIF 中转」的成熟开源竞品；社区集中在 viewer/aggregator/成本审计三类。HarnessBridge 的差异化是 **双向转换 + ATIF hub + 原生 store 直装/可恢复移出**。

## 2. 从外部项目学到的格式事实

- **路径与方言**：同一 harness 常有 legacy/现代两代 store（Cursor store.db vs agent-transcripts、OpenCode storage 树 vs sqlite_v2、Kiro JSONL+metadata、TRAE CLI=Codex fork rollout vs ACP transcript）。
- **工具调用表示**：Claude 式 `tool_use/tool_result`、Cline 族 flat `api_conversation_history`、Codex `function_call/function_call_output`、Copilot `events.jsonl` parentId 链、Antigravity SQLite+protobuf step。
- **写入语义**：外部项目基本只读/导出；原生 writer 与 L3 加载需本项目自研 + 目标工具读回验证（这是 HarnessBridge 的额外工作）。

## 3. 外部 fixture 的使用与许可

| 来源 | License | 用途 |
|---|---|---|
| agenttrace `testdata/` | MIT | workbuddy/kimi/qwen/copilot/antigravity/cline/opencode/pi/cursor/codex/openclaw 等最小样本 |
| agent-sessions `Resources/Fixtures/stage0` | MIT | Codex/Claude/OpenCode/Cursor/Antigravity/Hermes/OpenClaw/Copilot/Qwen/Kimi/Grok/Devin/Fx/Cline/Droid 等 |
| sessionport `tests/fixtures` | MIT | Windsurf/Junie/Vibe/Goose/Kilo/Aider 等 |
| codeg parser 内联测试 | Apache-2.0 | CodeBuddy/Antigravity SQLite/Kiro 等字段参考 |
| Harbor RFC 0001 §V 示例 | Apache-2.0 | OpenHands / mini-swe-agent 公开真实轨迹样例（**REAL-EXAMPLE**，不等同于真实用户会话） |
| `oleg121203/Developer` Continue 会话 | Apache-2.0 | Continue 真实用户 session（REAL，已脱敏并记录 commit） |

**不复制**：Crush（FSL-1.1-MIT）、Zed（NOASSERTION/GPL 混合）的源代码/资产；无 license 的仓库只记录 path 线索，不复制内容。

## 4. 我们的覆盖口径

HarnessBridge 分开报告：

1. **协议覆盖 40/40**：有 adapter + 至少 FIXTURE/构造/REAL-LOCAL 证据的去重 Harness（30-40 目标口径）。
2. **fixture-verified 格式覆盖（批 6 新增）**：外部/上游 fixture 实际跑通 reader→IR→ATIF 的 canonical 标签数（partial 计入，CONSTRUCTED 不计）。
3. **真实会话覆盖 22/40**：NATIVE / REAL-LOCAL / COLLECTED / REAL 的用户会话证据；外部 fixture 与构造样本一律不计入。

详见 [coverage-ledger.md](coverage-ledger.md) 与 `research/external/`（仓库内调研记录）。
