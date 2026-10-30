## [v1.5.1] — 2026-10-31

### First public release / 首次公开版本
- **HarnessBridge** brand (formerly Session Converter): `HarnessBridge.app`, bundle id `io.github.larrtroffen.harnessbridge`; data dir `~/Library/Application Support/HarnessBridge`, output `~/Documents/HarnessBridgeOut`.
- **Liquid Glass** UI (macOS 26+ `.glassEffect`; macOS 13–25 material/NSVisualEffectView fallback; Reduce Motion/Transparency).
- **Self-contained arm64 app**: bundles Python 3.12, the `asi` backend and `zstd`; no Python/zstd/repo required. 40MB DMG, ad-hoc signed.
- Backend **81/81 tests**; app `--self-test` **31/31 PASS** from repo and mounted DMG (`portable: true`); backend journal default dir now HarnessBridge (legacy SessionConverter read compatibility).
- GitHub docs: bilingual README/architecture/CLI/compatibility/FAQ, MIT license, CI + release workflows, issue/PR templates, release notes, banner.

# Changelog

> **HarnessBridge** (formerly Session Converter) — Agent Session Converter. 版本记录自 2026-10-30 起。
> English entries are provided for the public releases; older internal entries are kept in Chinese.
> **说明**：仓库此前未初始化 git；历史版本内容与验收数据记录在 `README.md`、`docs/` 与 `docs/reviews/` 中。git 历史从 v1.4.2 的初始导入开始，之后每个版本都会 commit + tag。

## [v1.5.0] — 2026-10-31

### English

- **First public GitHub release** of the project under its new name **HarnessBridge** (formerly Session Converter). Repository: `github.com/Larrtroffen/harnessbridge`.
- **Renamed native macOS app**: `HarnessBridge.app` (bundle id `io.github.larrtroffen.harnessbridge`), refreshed visual design with glass-style surfaces; requires macOS 13+ and ships as an Apple-silicon (arm64) DMG/zip.
- **CLI product surface**: 40/40 protocol coverage with ATIF v1.8 as the hub; 35 import sources and 31 native/export targets in this build.
- **Safe migration model**: direct install into the target harness store by default (DSH/Claude Code/OMP stable; Codex/Qoder/Pi/Gemini experimental; Goose export-only); `keep`/`move` with reversible `*.migrated-*.bak`; `migrate-all` one-click full migration; `migrate-restore`; atomic incremental journals; overwrite backups; `--dry-run` zero writes; `--yes` required for real-store writes.
- **Native app features**: migration wizard, one-click migrate-all, session browser, session timeline with tool pairing and token stats, migration history with restore/journal, 27 harness logos, Chinese UI, Reduce Motion support.
- **Docs & engineering**: bilingual README and docs (architecture, CLI, compatibility, FAQ), contributing/security/conduct policies, MIT license, third-party notices, GitHub issue/PR templates, CI and tag-driven release workflow (DMG/zip/SHA-256).
- **Verification**: backend unit tests run in CI with a temporary `HOME` and env-overridden stores; app `--self-test` (31 checks, isolated install/move/restore; 31 PASS / 0 FAIL on the v1.5.0 repo build) is part of the local acceptance flow. Release artifacts are **ad-hoc signed, not notarized**; see the Gatekeeper note in the README.
- **Known limitations**: conversion can be lossy; ATIF is a trajectory format (not a resume/checkpoint format); experimental targets may need restarts/index rebuilds; prebuilt app is arm64-only; Windows is untested.

### 中文

- **项目首个 GitHub 公开发布**，正式更名 **HarnessBridge**（原 Session Converter）；仓库 `github.com/Larrtroffen/harnessbridge`。
- **原生 macOS App 更名**为 `HarnessBridge.app`（bundle id `io.github.larrtroffen.harnessbridge`），玻璃质感视觉更新；要求 macOS 13+，提供 Apple Silicon（arm64）DMG/zip。
- **CLI 产品面**：以 ATIF v1.8 为中枢，协议覆盖 40/40；当前构建支持 35 个导入来源与 31 个原生/导出目标。
- **安全迁移模型**：默认直接写入目标 Harness 会话库（DSH/Claude Code/OMP 稳定；Codex/Qoder/Pi/Gemini 实验性；Goose 仅导出）；`keep`/`move`（`*.migrated-*.bak` 可恢复）；`migrate-all` 一键全量迁移；`migrate-restore`；原子增量 journal；覆盖前备份；`--dry-run` 零写入；真实 store 写入必须 `--yes`。
- **App 功能**：迁移向导、一键迁移、会话浏览、带工具配对与 Token 统计的时间线、含恢复/journal 的迁移历史、27 个 Harness Logo、中文界面、Reduce Motion。
- **文档与工程**：中英双语 README 与文档（架构/CLI/兼容性/FAQ）、贡献/安全/行为准则、MIT 许可证、第三方声明、Issue/PR 模板、CI 与 tag 驱动的 Release 工作流（DMG/zip/SHA-256）。
- **验证**：后端单元测试在 CI 中用临时 `HOME` 与 env 覆盖 store 运行；App `--self-test`（31 项，含隔离 install/move/restore；v1.5.0 仓库构建实测 31 PASS / 0 FAIL）是本地验收流程的一部分。Release 产物为 **ad-hoc 签名、未公证**；Gatekeeper 说明见 README。
- **已知限制**：转换可能是有损的；ATIF 是轨迹格式（不是 resume/checkpoint 格式）；实验性目标可能需要重启/重建索引；预编译包仅 arm64；Windows 未测试。

## [v1.4.3] — 2026-10-31

### 修复
- **「下一步：选择来源」按钮点了没反应**（v1.4.2 回归）：该按钮先把步骤设为 2，随后 `refreshMigrateAllSources()` 又把步骤重置回 1，导致点击后被立刻弹回，表现为按钮“点不动”。修复：步骤切换与数据刷新解耦，刷新不再重置导航状态；增加目标有效性自动纠正；「一键迁移」默认目标改为 **DeepSeek Harness（推荐）**。
- 「预览计划」生成期间显示进度指示（会话多时约需数秒），避免看起来卡住。

### 验收
- `--self-test` 30 PASS / 0 FAIL；无障碍（AX）实测：一键迁移 → 「下一步：选择来源」→ 进入「选择来源与筛选」，目标默认 DeepSeek Harness，预览计划可用。

## [v1.4.2] — 2026-10-31

### 新增（v1.4 主线）
- **默认直接写入目标 Harness 会话库**（自动检测 store）：DSH / Claude Code / OMP 正式；Codex / Qoder / Pi / Gemini 实验性；Goose 等仅导出。迁移不再默认要求输出文件夹。
- **保留原始 / 移出原始（可恢复）**：`--session-mode keep|move`；move 仅在安装+verify 成功后把源文件改名为 `<原名>.migrated-<ts>.bak`，不删除；journal + `asi migrate-restore` 反向恢复（可选删除已安装副本）。
- **一键全量迁移**：`asi migrate-all --to <target>`；App 新增「一键迁移」页（来源默认全选其他 Harness、筛选/计划预览/进度/取消/结果/恢复）。
- `asi detect` 增 `store_path / install_supported / install_experimental / how_to_see / session_dir_hint`。

### 修复（安全审查发现，v1.4.1/v1.4.2）
- move 源路径丢失导致「移出」不生效（source_path/source_dir/source_files 全链路传递；目录/多文件源明确 unsupported 且不动源）。
- journal 秒级命名冲突覆盖（毫秒+随机后缀、每会话增量原子写、失败/取消保留已完成映射）。
- install 临时 staging + 原子 replace；verify 失败回滚清理；migrate-all dry-run plan 增 skip_count；move 后空目录仅记录不强删。
- App：优先后端 move（清理双 journal）、unsupported 文案、source_path 展示、恢复删除目标副本选项、取消真正 SIGTERM/SIGKILL 后端、计划页预计跳过数。

### 验收
- 后端 80/80 测试（隔离 HOME/env，真实 store 不写）；App `--self-test` 30 PASS / 0 FAIL。
- 独立安全审查 `docs/reviews/swift-v14-safety-review.md`：v1.4.2 复审结论 **可发布，无 P0/P1**（残留 P2：取消后已完成项列表 schema 显示问题，计划 v1.4.3）。

## [v1.3.2] — 2026-10-31
- 全选/批量选择（浏览页 + 迁移向导：筛选后全选/反选/Shift 范围/Cmd+A/快捷最近 N）；快捷键、状态记忆、搜索防抖、排序密度、骨架/Toast；UI 动画（向导 spring、卡片 hover、复选、Token 数字、时间线展开、shimmer、Reduce Motion）；性能打磨（detect --fast 0.1s、并发 pipe drain、后台 decode、缓存、取消 generation、分批加载）。
- v1.3.1/v1.3.2 修复独立审查 P1：⌘A 双动作、选区 anchor、首屏空窗、Esc/Return、中文 IME、详情错误静默降级；Esc 一次生效、警告文案、真原子写、详情后台分组。

## [v1.2] — 2026-10-31
- 会话详情/时间线：统计卡片（消息/工具/Token/时长/工具 Top）、按轮次分区、工具调用与结果配对、筛选/搜索/跳转、迁移/导出/恢复入口。
- Harness Logo：27 个可再分发品牌图标（Codeg/sessionport/官方仓库，附 SOURCE/manifest），明暗自适应底板，5 个回退首字母。
- Token 口径增强：Codex 增量求和、Claude/OMP/DSH/Pi/Gemini 等；无数据时明确 unavailable 不编造。

## [v1.1] — 2026-10-31
- SwiftUI App 产品化：欢迎/首次启动、总览、5 步迁移向导、会话浏览、迁移历史、设置/帮助；全中文；DMG；`--self-test` / `--diagnose`。
- 后端产品级命令：`asi detect / preview / migrate`。

## [v1.0] — 2026-10-31
- 首个 SwiftUI macOS App（薄前端 + `asi` 后端）：源/目标列表、单会话转换、批量、矩阵、账本、控制台、设置；`build.sh` + ad-hoc 签名 + .app。

## [v0.3] — 2026-10-31
- 批次 3–5.1 扩展到 **协议覆盖 40/40 Harness**；`docs/coverage-ledger.md` v0.3 定稿；5 套互转矩阵（batch1–5）；证据等级体系（NATIVE/REAL-LOCAL/COLLECTED/FIXTURE…）。

## [v0.2] — 2026-10-30
- ATIF v1.8 作为统一中转的互转协议 v0.14；5 Harness 两两互转 + 20 方向自动矩阵；本地 Python Web GUI；49 候选 Harness 目录；OSS 轨迹样本盘点。

## [v0.1] — 2026-10-30
- 调研报告；Claude Code / Codex / Qoder / OMP / DSH 格式逆向规格；`agent-session-import` 工具（Codex/Qoder/OMP ↔ ATIF ↔ DSH）。
