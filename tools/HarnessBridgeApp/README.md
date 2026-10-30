# HarnessBridge — Agent Session Converter（macOS 原生应用 v1.5.1）

把 AI 编程会话在不同 Harness（Claude Code / Codex / OMP / Qoder / DeepSeek Harness 等）之间
安全迁移的原生 macOS 应用。产品化前端，**不包含转换逻辑**：所有迁移/详情数据由仓库内的 `asi` CLI 后端提供。

## v1.5.1（独立分发包）

- `./build.sh` 默认 **portable**：内嵌 python-build-standalone 3.12.16 + `Contents/Resources/backend` +
  `Contents/Resources/bin/zstd`（依赖 dylib 重写为 @executable_path），产出自包含 `HarnessBridge.app`
  与 `HarnessBridge-1.5.1-macos-arm64.dmg`（约 40MB）；`--dev` 保持仓库 backend 行为；
- App 在找不到 repo/env 时优先使用 bundle 内 backend；无个人绝对路径；`--diagnose` 打印 portable/backend/python/zstd；
- self-test 临时目录带 UUID 后缀并清理旧产物；从 DMG 挂载运行 **31 PASS / 0 FAIL**；
- 品牌名 HarnessBridge、数据/输出目录与 UserDefaults 迁移同 v1.5.0。

## v1.5.0（HarnessBridge + Liquid Glass）

- 品牌更名 HarnessBridge；App/可执行/build 产物/Info.plist/DMG 命名/窗口标题/菜单/About/欢迎/帮助全部更名；
- 数据迁移与设置迁移（SessionConverter → HarnessBridge，SC. → HB.）；默认输出 HarnessBridgeOut；
- Liquid Glass 设计系统（`GlassCard`/`glassBar`/`glassSelectionCard`/`GlassProminentButtonStyle`），macOS 13-25 material 回退，尊重 Reduce Transparency/Motion；
- self-test 31 项（含品牌/数据目录断言）；

## v1.4.2（move/restore 收尾 + 安全取消）

- 移出原始会话优先走后端 `migrate --session-mode move`（读取 source_moved/status/backup/journal，source_moved=true 绝不二次改名）；
  旧后端才使用 App 安全改名兜底；
- 暂不支持移出来源（unsupported/failed）明确提示「源文件已保留」，不显示成功；
- 一键迁移取消现在会真正终止后端进程（SIGTERM/SIGKILL），已完成项与 journal 保留；
- 计划页显示预计跳过数；结果页区分 skipped-exists；恢复支持可选删除目标安装副本（默认关闭）；
- journal 路径直接使用后端返回，不自行拼接；self-test 30 项（隔离后端真实 move/restore、取消终止/取消保留 journal）。

## v1.4.0（新迁移模型）

- **默认直接写入目标工具会话库**（自动检测 store 路径，不再先选输出文件夹）；输出目录仅在高级「仅导出」出现；
- 目标卡片展示会话库路径、迁移后查看方式、已验证/实验性标签；不支持写入的工具自动只提供导出；
- **保留 / 移出原始会话（可恢复）**：默认保留；move 成功安装+校验后把源文件改名 `.migrated-<时间>.bak`（绝不删除），
  结果页/历史可一键恢复；
- **一键迁移**：目标 → 来源默认全选其他工具 → 时间/数量筛选 → 计划预览（dry-run 零写入）→ 执行/逐条结果/取消 → 恢复入口；
- 迁移历史增加目标会话库、模式、keep/move、跳过数、journal/恢复按钮；
- 后端可用时优先使用 `migrate-all` / `migrate-restore`；App 侧保留安全改名与日志兜底；
- self-test 28 项，含临时 HOME/DSH_HOME 隔离的 install+verify、keep、move+restore、migrate-all dry-run/小样本（不触碰真实 store）。

## v1.3.2（发布前小补丁）

- Esc 首次生效：详情页不自动聚焦搜索；有文字首次 Esc 清空、二次返回；空文字首次 Esc 返回；Toast 不拦截 Esc；
- 详情页 backend warning 翻译/清洗（不再显示 `usage.available=false` 等开发者文本）；
- HistoryStore / DetectCacheStore 改为 `Data.write(.atomic)` 真原子写（历史上限 200 条保留）；
- 详情时间线分组移后台计算、主线程批量赋值；Reduce Motion 统一包装；
- self-test 24 项（新增「Esc 决策」）；list/preview/detail 阈值收紧至 8s。

## v1.3.1（审查修复）

- ⌘A/Return/Esc 在文本输入焦点下不再误触，Esc/Return 使用系统 cancel/default action 绑定；
- 选区 anchor 改为稳定 session id（筛选/排序变化后 Shift 范围仍正确），向导复用同一引擎；
- 启动首屏：立即显示上次检测缓存（`~/Library/Application Support/SessionConverter/detect-cache.json`）
  并后台 `detect --fast` 刷新，缺失时显示骨架卡片；
- 详情读取失败不再静默降级：命令未实现走摘要模式、调用失败显示可读错误 + 重试；
- 中文输入法组词期间不覆盖输入；迁移历史原子写 + 上限 200 条；详情过滤/分组移后台；
- self-test 23 项（新增历史原子写/上限与选择 anchor 断言；detect 阈值 5s）。

## v1.3 新增

- **全选 / 批量选择**：浏览页与迁移向导 Step2 支持「全选当前筛选 / 反选 / 取消」、已选计数、
  Shift 范围选择、⌘A 全选、最近 10/50/全部快捷选择；批量操作条（迁移所选 / 导出所选 / 复制摘要）；
  批量迁移前显示确认摘要。
- **快捷键与习惯优化**：⌘R 刷新、⌘F 搜索、⌘A 全选、Esc 返回/取消、⌘, 设置、Return 详情、
  ⌘↩ 下一步/开始迁移、⌘O 打开输出目录、⌘↑/⌘↓ 首末工具；搜索防抖 250ms；排序/密度切换；
  窗口、来源、目标、筛选等状态记忆；骨架屏/Toast/破坏性确认。
- **UI 动画**：向导步骤 spring 过渡、卡片 hover、按钮按压缩放、复选 spring、列表行动画、
  侧栏选中动效、Token 数字滚动、时间线展开动画、进度 shimmer、Toast 滑入；尊重 Reduce Motion。
- **性能与逻辑**：Process I/O 确定性并发读取（大详情无死锁）、detect/list 缓存 30s + 取消 token、
  过滤/排序后台执行、列表/时间线增量渲染（每批 200）、详情缓存与离开释放、批量逐条容错。
- `--self-test` 新增「选择逻辑」与「性能基线」，共 **22 项**，保持 exit 0。

## 构建与打包（无需 Xcode）

```bash
cd tools/SessionConverterApp
swift build -c release
./build.sh                         # → dist/SessionConverter.app（含图标/Logo，ad-hoc 签名）
codesign -v dist/SessionConverter.app
open dist/SessionConverter.app     # 首次启动进入中文欢迎页
```

Logo 资产：若存在 `Assets/Logos/` 或工作区 `assets/harness-logos/`，`build.sh` 会整目录拷入
`Contents/Resources/Logos/`（支持子目录，如 `raw/<id>.png`）；资源由项目 owner 提供，应用不联网下载。

## 无界面验收

```bash
APP=dist/SessionConverter.app/Contents/MacOS/SessionConverter
"$APP" --self-test    # 14 项既有 + 8 项产品流程（检测/预览/详情/迁移/校验/历史/选择逻辑/性能基线）
"$APP" --diagnose     # 环境、后端路径、版本、capabilities、history 文件
```

## 功能

- 欢迎/首次启动、首页总览、迁移向导 5 步、会话浏览（批量选择）、迁移历史、设置、帮助；
- 会话详情/时间线/Token 统计；
- 迁移历史持久化到 `~/Library/Application Support/SessionConverter/history.json`；
- 高级工具（矩阵、覆盖统计、日志）；
- 源数据只读；写入真实 store 需二次确认且默认关闭。

## 文档

用户手册与开发者附录：[`docs/swift-app.md`](../../docs/swift-app.md)。
