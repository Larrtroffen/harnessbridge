# 兼容性与证据等级

HarnessBridge 刻意分开报告三个容易混淆的数字：

| 口径 | 数值 | 含义 |
|---|---|---|
| **协议覆盖** | **40 / 40** | 有 adapter 且至少有 FIXTURE / CONSTRUCTED / REAL-LOCAL 证据的去重 Harness 格式数（项目最初 30–40 的目标） |
| **真实会话覆盖** | **21 / 40** | 用真实（或采集）会话验证过的格式：NATIVE 5 + COLLECTED 14 + REAL-LOCAL 1 + COLLECTED-SPARSE 1。FIXTURE/CONSTRUCTED **不计入** |
| **当前产物** | **35 个导入来源 / 31 个写出目标** | 当前 `asi` CLI 暴露的范围（以 `asi --help` 枚举为准） |

权威、可自动生成校验的数字见[覆盖账本](coverage-ledger.md)；逐批证据见[互转协议](atif-interop-protocol.md)与 `docs/usage.md` §8–§15。账本可用 `tools/coverage-report.py --check` 校验。

> 我们不宣称「100% 无损」，也不宣称所有已覆盖 Harness 都能原生 resume。「覆盖」表示有 adapter 与证据；「目标工具原生可加载」是更严格、单独跟踪的属性。

## 直装支持级别

直装会把会话写进 Harness 自己的本地会话库。支持级别由 `asi detect --json` 返回（`install_supported` / `install_experimental`）。

| 目标 | store（环境变量覆盖） | 级别 | 迁移后 |
|---|---|---|---|
| **DeepSeek Harness（DSH）** | `~/.dsh/sessions`（`DSH_HOME`） | ✅ 稳定 | 重启 DSH；可选 `--register` 注册到项目 |
| **Claude Code** | `~/.claude/projects`（`CLAUDE_CONFIG_DIR`） | ✅ 稳定 | 重启 Claude Code；`claude --resume` |
| **OMP** | `~/.omp/agent/sessions`（`OMP_SESSION_DIR`） | ✅ 稳定 | 重启 OMP |
| **Codex** | `~/.codex`（`CODEX_HOME`） | 🧪 实验性 | `codex resume`；可能需要重建线程索引 |
| **Qoder** | `~/.qoder/projects`（`QODER_CONFIG_DIR`） | 🧪 实验性 | 重启 Qoder |
| **Pi** | `~/.pi/agent/sessions`（`PI_HOME`） | 🧪 实验性 | 重启 Pi |
| **Gemini CLI** | `~/.gemini/tmp`（`GEMINI_HOME`） | 🧪 实验性 | 重启 Gemini CLI；`/resume` |
| **Goose** | SQLite（`GOOSE_PATH_ROOT`） | 📦 仅导出 | 用 `--mode export` |

「实验性」意味着：writer 基于我们对原生布局的最佳理解，并通过读回产物做校验，但厂商可能改变格式/索引，目标工具也可能需要重启或重建索引。请按 best-effort 使用，并保留备份。

## 证据等级

| 等级 | 定义 | 计入「真实」？ |
|---|---|---|
| **NATIVE** | 真实本地安装 + 真实本地 store + 原生加载/恢复验证（L3） | ✅ |
| **REAL-LOCAL** | 真实本地安装 + 真实本机会话，未验证原生加载 | ✅ |
| **COLLECTED** | 开源 `traj-session/1` 采集的真实用户会话（B2 L0–L2 + DSH L3） | ✅ |
| **COLLECTED-SPARSE** | 真实采集但样本极稀疏 | ✅（标注） |
| **FIXTURE** | 上游公开的原生格式 fixture，通过 F 级验证 | ❌ |
| **FIXTURE-LOW** | 低置信度/派生 fixture | ❌ |
| **CONSTRUCTED** | 根据文档/规范构造，无上游样本 | ❌ |

逐批摘要（来自账本）：

| 批次 | 范围 | 证据 | 结果 |
|---|---|---|---|
| B1 | Claude Code、Codex、OMP、Qoder、DeepSeek Harness → ATIF → DSH | NATIVE + 真实本机 | 5 Harness 主矩阵 L3 通过 |
| B2 | OSS `traj-session/1` 采集（15+ 标签）→ IR → ATIF → 各 Harness | COLLECTED（+SPARSE） | B2 L0–L2、DSH L3 |
| B3 | 6 个原生 fixture adapter | FIXTURE | 矩阵通过 |
| B4 | 8 个 adapter | FIXTURE / FIXTURE-LOW / CONSTRUCTED | 矩阵通过 |
| B5 / B5.1 | 17 行，REAL-LOCAL + 构造升级 | REAL-LOCAL 2、FIXTURE 3、FIXTURE-LOW 2、CONSTRUCTED 10、COLLECTED-SPARSE 1 | **pass 16 / partial 1 / fail 0**（`fx` partial：orphan tool_results + 仅文本 writer，已声明有损） |

## 按证据分组的 Harness 覆盖

**原生本地 reader（真实本机 store）：** Claude Code、Codex、OMP、Qoder、DeepSeek Harness。

**真实本机 writer：** Gemini CLI、Pi。

**采集 / OSS 组：** OpenHands、Gemini CLI、Codex、Claude Code，以及 `samples/batch2/` 中的其他 `traj-session/1` 标签（见 `docs/batch2-samples.md`）。

**Fixture / 构造覆盖（协议 adapter）：** Copilot CLI、Aider、Cursor CLI、Qwen Code、OpenClaw、Kimi Code、Grok Build、Factory Droid、Antigravity（仅 reader）、Hermes、Devin CLI、OpenCode、Goose、Continue、JetBrains Junie、Kiro CLI、Crush、Cline、Roo Code、Kilo Code、Codebuff、Mistral Vibe、CodeBuddy、FX（`fx`）、mini-swe-agent、Zed（调研），以及 ATIF / IR 两个通用目标。

以上是摘要而非权威计数。逐 Harness 证据行（含 `partial` 标记与 fixture 来源）以 [`docs/coverage-ledger.md`](coverage-ledger.md)、[`docs/harness-catalog.md`](harness-catalog.md) 与各批次文档为准。

## 已知限制

### 转换保真度

- **并非所有 Harness 特性都有 ATIF/IR 等价表达。** 图像/音频内容、私有系统事件、部分工具结果配对、厂商私有元数据可能被丢弃或降级成文本；转换会输出 `lossy` 警告。
- **`fx`（Vercel Labs FX）为声明性 partial**：orphan `tool_results` 无法表达，writer 只持久化文本事件。
- **Token 口径依赖来源。** 部分 Harness 不暴露 usage；HarnessBridge 报 `usage.available=false`，不估算。
- **ATIF 是轨迹日志格式，不是 resume 格式。** 迁移提供对话历史，不提供源 Agent 的私有运行时状态。

### 直装 / move

- **DSH move** 改名的对象是主文件 `session.v4.jsonl.zstd`；会话目录与 journal 记录会作为恢复证据保留。
- **目录/多文件型源会话**报告 `source_move_status: "unsupported"`，源完全不动。
- **move 依赖已知源文件路径。** 路径与计数来自 Harness reader；无法读取的异常 store 会被跳过，而不是猜测。
- **实验性目标**（Codex/Qoder/Pi/Gemini）可能需要目标侧重启、重建索引，且行为可能随 Harness 版本变化。
- **覆盖**是显式选择（`--overwrite`），会先把旧目标备份为 `*.asi-backup-<timestamp>`；默认跳过。
- **并发写**同一目标会话没有互斥锁；请避免同时向同一目标 store 跑两个迁移。

### 平台

- **预编译 DMG**：Apple Silicon（arm64），macOS 13+，ad-hoc 签名、未公证；Intel Mac 需从源码构建。
- **CLI**：Python 3.10+ 标准库；可选 `zstd` CLI；Windows 未测试、未纳入 CI。
- **Harness 版本会漂移。** 格式是逆向的，厂商更新可能破坏 reader/writer。遇到格式/版本问题欢迎提 Issue（尽量附脱敏 fixture）。

## 测试策略

- 所有 install/move/restore 测试都在**临时 HOME + env 覆盖的 store** 上跑；测试会断言真实 store 未被修改。
- 证据产物（矩阵 JSON）与 fixture 在 `tools/agent-session-import/tests/` 与 `samples/` 中纳入版本管理。
- App `--self-test` 覆盖隔离 install/keep/move+restore/migrate-all dry-run/取消；详见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

## 对路线图的影响

缺失的原生 writer（如 Zed、Antigravity writer）与真实 fixture（Windsurf、Kilo 真实 store、CodeBuddy 上游）记录在覆盖账本的「剩余缺口」中。如果你能提供脱敏的真实样本，是把某个 Harness 从 FIXTURE 提升到 REAL 的最快方式。
