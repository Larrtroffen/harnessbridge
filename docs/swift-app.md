# HarnessBridge（Agent Session Converter）— macOS 用户手册

> 适用版本：v1.5.1（2026-10-31）｜平台：macOS 13 及以上｜构建：Swift 6 / SwiftUI（无需 Xcode）
> 应用位置：`tools/SessionConverterApp/dist/HarnessBridge.app`
> 品牌：HarnessBridge（Agent Session Converter）｜开源项目：github.com/Larrtroffen/harnessbridge
> 一句话：把你的 AI 编程会话，从 A 工具安全地迁移到 B 工具（Session Ferry）。

> **v1.5.0 品牌升级**：应用从 Session Converter 更名为 **HarnessBridge**；旧数据目录
> `~/Library/Application Support/SessionConverter` 会在首次启动时复制迁移到
> `~/Library/Application Support/HarnessBridge`（history/detect-cache/journals，旧数据保留），
> 旧设置 key（`SC.`）也会迁移到新前缀（`HB.`）。默认输出目录为 `~/Documents/HarnessBridgeOut`。

## 0. 便携版与安装（v1.5.1）

发布版为**完全自包含**的 `HarnessBridge.app`，内嵌 Python 3.12 runtime、后端转换工具和 zstd：

- 直接打开 `dist/HarnessBridge-1.5.1-macos-arm64.dmg`，把 `HarnessBridge.app` 拖入「应用程序」即可；
- **不需要** clone 仓库、不需要系统 Python、不需要 Homebrew zstd；
- App 首次启动时优先使用包内 `Contents/Resources/backend`（不再依赖作者路径/`workspace-path.txt`），
  找不到时才会尝试环境变量/用户设置/仓库位置；
- 开发者构建：`./build.sh`（默认 portable，生成 DMG）或 `./build.sh --dev`（使用本仓库 backend，不内嵌运行时）；
- Python runtime 来自 python-build-standalone 3.12.16（固定 URL + sha256，缓存在 `vendor/`，gitignore）；
  zstd 及依赖 dylib 一并内嵌并用 `@executable_path` 重写加载路径；
- `--diagnose` 会打印 `portable: true`、backend root、bundled python/zstd；
- 从挂载的 DMG 直接运行 `--self-test` 应为 **31 PASS / 0 FAIL**（v1.5.1 起自检临时目录带 UUID 后缀并清理旧 selftest 产物）。

## 0.1 Liquid Glass（v1.5.0）

macOS 26+ 使用系统 Liquid Glass（`.glassEffect`）实现克制的层次感：

- 侧栏 / 顶部工具栏 / 底部状态栏：玻璃条；
- 卡片（工具卡片、目标卡片、统计卡片、详情头部、欢迎/帮助卡片）：玻璃卡片 + 细描边 + 柔和阴影；
- 选中态/主按钮：玻璃 tint（`GlassSelectionCard` / `GlassProminentButtonStyle`）；
- 窗口背景：系统 vibrancy + 轻微渐变。

macOS 13–25 自动回退到 `.ultraThinMaterial` / `NSVisualEffectView`；开启「减少透明度」时回退为不透明背景，
「减少动态效果」时关闭缩放/位移动画。复用组件：`GlassCard`、`glassCard()`、`glassBar()`、
`glassSelectionCard(selected:)`、`GlassProminentButtonStyle`，见 `Sources/SessionConverter/Support/Glass.swift`。


---

## 1. 这是什么

如果你同时使用多个 AI 编程工具（Claude Code、Codex、Qoder、OMP、DeepSeek Harness 等），
「HarnessBridge」可以帮你：

- 在一个窗口里看到本机各工具的**全部会话**；
- 把某个（或多个）会话**迁移**到另一个工具继续；
- 把会话**导出**为通用文件，用于备份或审计；
- 全程**不改动原始会话**，迁移结果先保存到你选择的文件夹。

它不会上传任何数据，不需要账号，不依赖网络。

## 2. 安装与打开

本应用由本仓库本地构建，未做 Apple 公证，首次打开可能遇到系统提示：

1. 双击 `dist/HarnessBridge.app`；
2. 若提示「无法验证开发者」：打开「系统设置 → 隐私与安全性」，在底部选择「仍要打开」；
   或右键点击应用图标 →「打开」→ 确认。

> 如果移动了应用位置，应用仍能通过自动检测或「设置」找到本机的会话数据。

## 3. 首次使用（欢迎页）

第一次打开应用会进入欢迎页：

1. 应用自动检测本机已安装的 AI 编程工具，显示「发现 N 个工具 / M 个会话」；
2. 直接点击「开始使用」即可——**v1.4 起默认把会话直接写入目标工具自己的会话库**，不再要求先选输出文件夹；
   需要"仅导出到文件夹"时，在迁移向导第 4 步的「高级选项」里切换。

以后不再显示欢迎页；可在「设置 → 界面 → 重新查看欢迎页」再次打开。

**首屏加速（v1.3.1）**：应用会在启动时立即显示**上次检测结果**（来自
`~/Library/Application Support/HarnessBridge/detect-cache.json`，标注「上次检测时间」），
同时在后台用 `--fast` 快速刷新；刷新完成自动替换，失败则保留缓存并提示可读错误。
首次启动或缓存缺失时显示骨架卡片而不是空白。

## 4. 首页总览

首页显示：

- **工具卡片**：每个已检测工具的名称、会话数、最近活跃时间（点击卡片可直接开始迁移）；
- **三个主按钮**：`迁移会话`、`浏览会话`、`导出原始轨迹`；
- **最近迁移**：最近 5 条迁移记录。

## 5. 迁移会话（5 步向导，默认直接写入目标会话库）

### 第 1 步：选择来源
只列出本机检测到会话的工具（含会话数量）。

### 第 2 步：选择会话
- 支持搜索、多选、一键「最近 5 个」；
- 点击行可勾选/取消，点击右侧眼睛图标或行右侧按钮查看**预览**：
  标题、项目路径、模型、消息数、工具调用数、首条用户消息摘要。

### 第 3 步：选择目标

v1.4 起目标卡片显示**自动检测到的会话库路径**和**迁移后如何看到**；默认模式是「直接迁移」到该工具自己的会话库：

| 目标 | 说明 | 标签 |
|---|---|---|
| DeepSeek Harness | 写入 `~/.dsh/sessions/...`，可注册到项目；重启 DSH 后可见 | 已验证 |
| Claude Code / Codex / OMP / Qoder | 写入各工具的原生会话目录（沿用其布局） | 实验性 |
| 仅导出到文件夹 | 高级选项：生成标准交换文件，不写入任何工具会话库 | 高级 |

无法写入本地会话库的工具（如 Pi、Gemini、Goose 等）只提供导出并在卡片上说明原因。

### 第 4 步：选项
- **原始会话**：默认「保留」；可选「移出原始会话（可恢复）」——v1.5.0 起由后端 `--session-mode move` 执行：
  迁移并校验成功后把源会话文件重命名为同目录 `*.migrated-<时间>.bak`，**不删除**，可随时恢复；移出需要二次确认；
  若来源暂不支持移出（目录/多文件源等），结果页会明确提示「该来源暂不支持移出，源文件已保留」，且不会显示为成功；
- **写入位置**：直接显示目标工具的会话库路径，无需选择输出文件夹；
- **项目路径处理**：默认保留原项目路径；也可统一指定一个目录（当原路径在本机不存在时使用）；
- **包含系统提示词**：默认不包含；
- **注册到项目**（仅 DeepSeek Harness + 直接迁移模式）：迁移后自动关联到对应项目；
- **高级选项**：可切换「仅导出到文件夹」（此时才显示输出目录）、覆盖已存在会话（默认关闭，
  重复会话默认跳过不覆盖）。

### 第 5 步：执行与结果
- 显示进度条与逐会话状态；
- 完成后显示：成功/失败数、每个会话的**校验状态**、**有损项**说明、输出目录；
- 可「打开输出文件夹」「复制迁移结果」「重试失败项」；
- 目标是 DeepSeek Harness 时，**重启 DeepSeek Harness** 后即可看到迁移的会话。

> 有损说明：不同工具的会话格式不完全一致，部分信息（工具调用细节、系统提示词、时间戳等）
> 在目标工具中没有完全对应的概念，会被省略并在结果中标记为「有损」；原始会话不受影响。

### 5.6 一键迁移（v1.4 新增）

首页主按钮「一键迁移」或侧栏「一键迁移」：

1. **选择目标**：只列出支持写入会话库的工具（实验性目标会标注）；
2. **选择来源**：默认勾选其他所有有会话的工具（显示会话数与最近时间），可排除；
3. **筛选**：全部 / 最近 1/7/30 天、最多会话数；
4. **预览计划**：显示会话总数、目标会话库路径、keep/move 模式；此时**零写入**；
5. **执行**：进度条 + 逐条结果（成功/失败/跳过/移出）；可随时取消——取消会**真正终止后端进程**（不再继续写盘/改名），
   已完成项与迁移日志会保留，结果页标记「已停止（部分完成）」；
6. **结果**：成功/失败/跳过/移出统计、迁移日志路径、恢复被移出的会话入口、目标工具重启提示。

重复会话默认跳过；如需覆盖请在向导高级选项中开启（会先备份目标侧文件）。

## 6. 浏览会话

- 顶部按工具筛选（带 Harness Logo），支持搜索；
- **点击任意会话即可打开「会话详情页」**（完整时间线、Token 统计等，详见 §7）；
- 也可直接「迁移此会话」或「导出」。

### 6.1 全选与批量操作（v1.3 新增）

浏览会话页支持批量选择：

- **勾选框**：点击行首复选框选择会话；**Shift + 点击**连续选择一段范围；
- 工具条提供「**全选当前筛选**」「**反选**」「**取消选择**」，并实时显示「已选 N / 共 M（筛选后）」；
- 快捷键：`⌘A` 全选当前筛选结果；`Esc` 清除选择；
- 勾选后出现**批量操作条**：`迁移所选`、`导出所选`、`复制摘要`、`取消选择`；
- 批量导出前会弹出确认（会话数 + 输出目录）；批量迁移会打开向导第 2 步并保留所选，最终开始迁移前仍会显示确认摘要。

迁移向导第 2 步同样支持：

- 全选当前筛选 / 反选 / 取消，`已选 N / 共 M（筛选后）`，Shift+点击范围选择；
- 「快速选择」菜单：**最近 10 个 / 最近 50 个 / 全部当前筛选**；
- **选区行为**：切换步骤不会丢失选择；**切换筛选不会清除已选**（已选项即使暂时不可见仍保留）；**切换来源会清空选择**并提示；
- 列表默认先显示 200 个会话，滚动到底或点「加载更多」继续加载。

## 7. 会话详情 / 时间线 / Token 统计（v1.2 新增）

从「浏览会话」点击任意会话（迁移向导第 2 步的预览区也有「查看完整详情」按钮）进入详情页。

### 7.1 页面结构

1. **头部**：Harness Logo + 名称、会话标题、项目路径、模型/提供方、创建/更新时间、来源与证据等级标签。
2. **统计卡片**：
   - 消息数（用户 / 助手 / 工具）；
   - 工具调用数（含结果数、失败数，失败用红色强调）；
   - **Token 用量**：input / output / cache / total；**该工具未提供 Token 统计时显示「该工具未提供 Token 统计」**，不会显示成 0；
   - 会话时长与首末消息时间；
   - 工具使用 Top（按工具名聚合的 chips）。
3. **时间线**：
   - 按后端返回的轮次/时间分区显示，分区头显示「第 N 轮」与该段事件/工具/失败摘要；
   - 每行显示：时间、类型徽标（用户=蓝 / 助手=绿 / 思考=紫 / 工具调用=橙 / 工具结果=青 / 系统=灰 / 压缩=棕）、角色、工具名、调用编号、内容摘要；
   - **工具调用与结果相邻显示并共用调用编号**，失败工具整行红色高亮；
   - 内容默认显示 4 行摘要，超过 160 字符可点「展开全文 / 收起」；
   - 事件较多时只渲染可见区域（懒加载），后端默认最多返回 2000 条事件，超出会显示「显示 N / 共 M 个事件（已截断）」。
4. **筛选 / 搜索 / 跳转**：
   - 类型筛选：全部 / 用户 / 助手 / 思考 / 工具 / 错误；
   - 会话内全文搜索（内容 / 工具名 / 角色）；
   - 「第一个工具」「最后一个工具」按钮快速跳转。
5. **操作**：迁移此会话（跳到迁移向导并预选）、导出、在 Finder 显示源文件、复制会话摘要。
6. **空 / 异常态**：无 Token 数据、时间线需更新后端（降级为最近消息）、内容被截断、加载失败（可读中文 + 重试）。

### 7.2 数据来源与降级

- 优先调用后端 `session-detail` 接口（完整 meta / stats / sections / timeline）；
- 后端未就绪时自动降级为「摘要模式」：显示基本信息 + 最近消息，并在时间线区域提示「时间线功能需要更新后端」，不影响其他功能；
- 大会话分页/截断由后端控制（`--max-events` 默认 2000、`--text-limit` 默认 400），App 端使用懒加载渲染。

### 7.3 截图说明

> 详情页布局（文字描述）：顶部为返回按钮 + Harness Logo + 名称 + 右侧「迁移此会话 / 导出 / 源文件 / 复制摘要 / 刷新」操作；下方第一张卡片是
> 「Logo + 会话标题 + 路径/模型/时间 + 来源徽标」；再往下是 4 张统计卡片（消息 / 工具调用 / Token 用量 / 会话时长）与工具使用 Top；
> 底部是「时间线」区域：一行类型筛选胶囊 + 搜索框 + 首/末工具跳转按钮，随后是按「第 N 轮」分区的可滚动事件列表，
> 用户为蓝色、助手绿色、工具调用橙色、工具结果为青色、失败为红色，点击「展开全文」可看完整内容。

### 7.4 Harness Logo

- App 为每个 Harness 显示 Logo（详情头部、首页卡片、迁移向导来源卡片、侧栏工具列表）；
- Logo 来自应用包内 `Contents/Resources/Logos/<harness-id>.png`（构建时从 `Assets/Logos/` 或工作区
  `assets/harness-logos/` 整目录复制，支持子目录，如 `raw/<id>.png`）；
- 找不到对应图片时回退为「首字母 + 品牌色」的圆角色块，不会联网下载图片；
- 别名归一：`claude-code→claude`、`kimi-code→kimi`、`kilo→kilo-code`、`factory-droid→droid`、
  `open-code→opencode` 等命中同一 Logo。

## 8. 迁移历史

- 每次迁移自动记录：时间、来源、目标、会话数、成功/失败数、输出目录、逐会话结果；
- 保存在 `~/Library/Application Support/HarnessBridge/history.json`，**重启应用后仍在**；
- 支持打开输出文件夹（仅导出模式）、复制摘要、删除单条记录、清除全部历史；
- 直接迁移记录会显示目标会话库、keep/move 模式、跳过数、迁移日志、真实源文件路径（可在 Finder 定位），
  并带「恢复被移出的会话」按钮；恢复默认只还原源会话，另可选「同时删除已安装的目标副本」（默认关闭）；

## 9. 设置

- **保存位置**：修改迁移输出目录；
- **会话工具位置**：一般无需修改；自动检测失败时可手动指定工具所在目录；
- **界面**：重新查看欢迎页；界面语言为简体中文；
- **数据与隐私**：说明只读策略与写入规则；可清除迁移历史；
- **关于**：版本、后端模式、证据等级说明、应用文档入口。

## 10. 快捷键与交互习惯（v1.3）

| 快捷键 | 作用 |
|---|---|
| `⌘R` | 刷新当前页面（检测/会话列表/详情/历史） |
| `⌘F` | 聚焦当前页搜索框 |
| `⌘A` | 全选当前筛选（浏览页 / 向导 Step2）；**焦点在搜索框时改为全选输入框文本** |
| `Esc` | 返回/取消：关闭详情、取消选择、上一步、关闭弹窗；焦点在输入框时先退出编辑。详情页：搜索框有文字时第一次 Esc 清空文字、第二次返回；无文字时第一次 Esc 直接返回。Toast 不拦截 Esc |
| `Return` | 打开选中的单个会话详情（未选中时打开列表第一条；输入框内不误触） |
| `⌘↩` | 下一步 / 开始迁移（向导内）；浏览页有选择时进入批量迁移 |
| `⌘,` | 打开设置 |
| `⌘O` | 打开输出文件夹 |
| `⌘↑` / `⌘↓` | 详情页跳到第一个 / 最后一个工具调用 |

其他交互习惯：

- **搜索防抖 250ms**：输入后自动过滤，不打断输入；支持清空；
- **排序 / 显示密度**：浏览页工具条可切换「按时间 / 按标题 / 按消息数」与「紧凑 / 舒适」；
- **记忆**：窗口大小/位置、上次来源、上次目标、输出目录、高级选项、浏览筛选与排序、详情筛选，重启后保留；
- **详情返回**：从详情页返回列表会回到原来的滚动位置；
- **反馈**：复制/导出/迁移完成显示 Toast；破坏性操作（清除历史、真实写入）二次确认；
- **加载/错误态**：列表与详情有骨架屏/进度提示，失败可重试。

## 11. 常见问题

**Q：迁移会修改我的原始会话吗？**
不会。应用对原始会话只读；结果先写入输出文件夹。只有显式开启「直接写入真实 Harness」时才会写入目标工具数据目录，且会先自动备份。

**Q：为什么在详情页第一次按 Esc 没有返回？**
v1.3.2 起：详情页打开时不会自动聚焦搜索框；若你在搜索框里输入了文字，第一次 Esc 会清空搜索（保留焦点），第二次 Esc 返回列表；搜索框为空时第一次 Esc 直接返回。Toast 不会拦截 Esc。

**Q：启动时先看到「上次检测」的结果，是旧数据吗？**
这是首屏缓存（v1.3.1）：先立即显示上次成功检测的卡片，同时后台快速刷新并在完成后替换；如果有工具变化，等「刷新中」消失即可。检测失败时会保留缓存并提示原因。

**Q：怎么一次迁移很多会话？**
在浏览页勾选（可全选当前筛选/Shift 范围选择）后点「迁移所选」，或在向导第 2 步使用「快速选择」；开始前会显示确认摘要。

**Q：为什么列表只显示 200 个会话？**
为避免一次渲染过多行造成卡顿，列表分批加载；滚动到底或点「加载更多」即可继续。详情时间线同理（首批 200 条事件）。

**Q：从旧版 Session Converter 升级后会丢设置/历史吗？**
不会。首次启动会把旧数据目录（history/detect-cache/journals）复制到 HarnessBridge 目录并合并历史记录，
旧目录保留不删；UserDefaults 从 `SC.` 前缀迁移到 `HB.`（缺新值时复制旧值）。

**Q：输出文件夹去哪了？**
v1.4 起默认直接写入目标工具自己的会话库，不再需要选输出文件夹；如只需导出文件，在迁移向导第 4 步「高级选项」里切换「仅导出到文件夹」。

**Q：移出原始会话会删除吗？**
不会。移出只是把源会话文件重命名为同目录 `*.migrated-<时间>.bak`；迁移历史/结果页提供「恢复被移出的会话」，日志文件记录原路径与备份路径。

**Q：迁移完成后在目标工具里看不到会话？**
- 目标是 DeepSeek Harness：请**重启** DeepSeek Harness；
- 其他目标：当前版本生成的是目标格式文件，可能仍需目标工具自身导入/刷新。

**Q：为什么有的会话显示「有损」？**
见 §5 末尾说明；有损只影响迁移副本，不影响原始会话。

**Q：没有检测到我的工具 / 会话数为 0？**
请确认该工具至少使用过一次并保存了会话；仍找不到时在「设置 → 会话工具位置」手动指定其数据目录。

**Q：应用打不开 / 提示无法验证开发者？**
见 §2；这是本地构建应用的正常提示。

**Q：为什么看不到 Token 统计？**
不是所有工具都会在会话文件中记录 Token 用量。应用会显示「该工具未提供 Token 统计」；原始会话中有时也能在别处查看用量，但本应用不会猜测或补造数据。

**Q：时间线显示「需要更新后端」/ 只有最近消息？**
说明当前组件尚不支持完整会话详情接口，应用已自动降级为摘要模式；更新组件后会自动恢复完整时间线，无需修改应用设置。

**Q：数据会上传吗？**
不会。应用没有网络上传逻辑；所有读写都在本机完成。

**Q：界面里的「实验性」是什么意思？**
表示该方向的迁移已可生成目标格式文件，但尚未做目标工具的自动注册/原生加载验证。

## 12. 限制

1. 当前版本面向本机已安装的少数主流工具（Claude Code / Codex / OMP / Qoder / DeepSeek Harness 等）；
2. 目标为 Claude Code / Codex / OMP / Qoder 时，产物是目标格式文件，暂不自动安装/注册；
3. 有损项由源/目标格式差异决定，无法完全避免；
4. 未做 Apple 公证，其他机器首次打开可能有 Gatekeeper 提示；
5. 本轮不含 Windows/Linux、云同步或多机迁移；
6. 会话详情依赖后端 `session-detail`：未就绪时降级为摘要模式（仅基本信息 + 最近消息）；
7. 超大会话默认只加载最近 2000 条事件/单条 400 字符，超出部分显示「已截断」提示（可在高级/未来版本调整）；
8. 检测结果缓存文件位于 `~/Library/Application Support/HarnessBridge/detect-cache.json`，仅本机保存；
9. 迁移历史最多保留最新 200 条（原子写入，超限自动裁剪）；
10. 直接写入各工具会话库属于新能力：DSH 已验证，Claude Code/Codex/OMP/Qoder 为实验性；其他工具只支持导出；
11. 移出原始会话只做改名、不删除；若日志丢失，仍可在源目录按 `*.migrated-*.bak` 手动恢复。

---

# 开发者 / 架构附录

## A. 目录与构建

```
tools/SessionConverterApp/
├── Package.swift                 # SwiftPM，macOS 13+，executableTarget
├── Assets/AppIcon.icns|png       # 应用图标（build.sh 自动打包）
├── Assets/Logos/                 # 可选：Harness Logo（build.sh 拷入 Resources/Logos）
├── build.sh                      # release 构建 + .app 组装 + ad-hoc codesign
├── dist/HarnessBridge.app     # 产物
└── Sources/SessionConverter/
    ├── AppMain.swift             # 显式 @main + --self-test/--diagnose 分流
    ├── AppModel.swift            # 产品状态机（首页/向导弹/会话/历史/设置/高级）
    ├── Backend/
    │   ├── BackendBridge.swift   # Process+Pipe 调 CLI，超时/错误类型/PATH 注入
    │   ├── Models.swift          # CLI JSON 契约与通用 JSONValue
    │   ├── ProductBackend.swift  # 产品级 API：detect/preview/migrate（含降级）
    │   └── ProductModels.swift   # HarnessInfo/迁移目标/历史记录等
    ├── Support/
    │   ├── Support.swift         # 路径发现（多级回退）、格式化、日志
    │   ├── HistoryStore.swift    # ~/Library/Application Support/.../history.json
    │   └── Headless.swift        # --self-test / --diagnose
    └── Views/                    # 欢迎/首页/向导/浏览/会话详情/历史/设置/帮助/高级
        ├── LogoView.swift        # Harness Logo 加载 + 首字母回退
        └── SessionDetailView.swift  # 详情/时间线/筛选/搜索/Token 卡片
```

构建与打包（无需 Xcode/xcodebuild）：

```bash
cd tools/SessionConverterApp
swift build -c release          # 纯 SwiftPM，无第三方依赖、无网络
./build.sh                      # 组装 dist/HarnessBridge.app + 可选图标 + ad-hoc 签名
codesign -v dist/HarnessBridge.app
```

## B. 后端命令（复用 `asi`，不重写转换逻辑）

产品级命令（优先使用，能力探测自动切换）：

| 命令 | 用途 |
|---|---|
| `asi detect --json` | 检测本机工具与会话数 |
| `asi preview --from <src> --session <id> --json --limit N` | 会话摘要预览 |
| `asi session-detail --from <src> --session <id> --json [--max-events N] [--text-limit N]` | 会话详情：meta/stats/sections/timeline（供详情页/时间线使用） |
| `asi migrate --from <src> --session <id> --to <target> --out <dir> --mode export|install --json` | 一次完成迁移 + 校验（install 需 `--yes`，后端负责备份） |
| `asi migrate --session-mode keep|move --journal <path>` | 后端移动/日志能力（App 仍以自身的安全改名 + App Support journal 作为兜底） |
| `asi migrate-all --to <target> [--from ...] [--dry-run] [--yes] --json` | 一键迁移（App 在命令可用时优先使用 dry-run 预览/执行） |
| `asi migrate-restore --journal <path> --json` | 恢复后端日志中被移出的源会话 |

未就绪时自动降级为 `asi list` + `asi convert` + `asi verify` 的组合，后端接口就绪后无需更新应用。

## C. 无界面自检 / 诊断

```bash
APP=tools/SessionConverterApp/dist/HarnessBridge.app/Contents/MacOS/HarnessBridge
"$APP" --self-test   # 14 项既有检查 + 16 项产品流程（含隔离 install/keep/后端真实 move+restore/migrate-all/取消终止后端/取消保留 journal，共 31 项）
"$APP" --diagnose    # workspace、CLI 路径、版本、capabilities、history 文件等
```

自检产物写入 `~/Documents/HarnessBridgeOut/selftest-<时间戳>/`；自检产生的历史记录会写入
history.json 并在产品界面中以「自检」标记或过滤展示，不影响真实迁移记录。

## D. 性能设计（v1.3）

- **进程 I/O**：stdout/stderr 各由后台线程 `readDataToEndOfFile` 并发 drain，避免大 JSON 填满 pipe 造成死锁；超时会 `terminate` 后 `SIGKILL`，再等待读取线程结束；
- **缓存**：detect / list 缓存 30s（手动刷新强制）、详情缓存 120s 且最多 5 条；迁移后失效相关缓存；启动时使用 `detect-cache.json` 立即渲染上次检测结果（后台 `--fast` 刷新替换）；
- **输入法**：搜索框组词期间不覆盖用户输入（`hasMarkedText()` 判断）；`⌘A` 在文本焦点时交给系统文本全选；
- **历史/缓存**：`history.json` 与 `detect-cache.json` 均通过 `Data.write(to:options:.atomic)` 原子写入（系统 temp+rename），历史最多保留 200 条；
- **详情警告**：后端原始 warning（含 `usage.available=false` 等开发者后缀）会先翻译/清洗成用户文案再显示，Token 提示不重复出现；
- **取消**：列表/详情/检测请求带 generation token，切换来源/搜索/关闭详情时旧结果会被丢弃；详情离开页面释放大对象；
- **后台重活**：JSON decode、列表过滤/排序在 `Task.detached` 完成，主线程批量应用结果；
- **增量渲染**：浏览列表与向导 Step2 首批 200 条滚动加载；详情时间线首批 200 事件可「加载更多」；
- **搜索防抖 250ms**；动画尊重系统「减少动态效果」（Reduce Motion 时禁用/缩短）。

## E. 直接迁移与安全（v1.4）

- 目标安装位置来自 `asi detect` 的 store 路径与 install capability（`install_supported` / `install_experimental`）；
- 默认安装模式不写输出文件夹；「仅导出」是高级选项；
- `move` 安全语义：安装并校验成功后才把**源会话**改名 `.migrated-<时间>.bak`（同目录），不删除；
  若后端未真正移动则由 App 兜底改名，并在 `~/Library/Application Support/HarnessBridge/journals/` 写恢复日志；
- move：优先调用后端 `migrate --session-mode move` 并读取 `source_moved/source_move_status/source_backup_path/journal_path`；
  App 自实现改名仅在「旧后端无 --session-mode」时兜底，且 `source_moved=true` 时绝不二次改名；
- unsupported：后端返回 `source_move_status=unsupported/failed` 时，结果项标记为未成功并提示「该来源暂不支持移出，源文件已保留」；
- 取消：`CancellationFlag` 轮询触发 BackendBridge 对运行中的 CLI 发送 SIGTERM/SIGKILL；后端未被终止前不会返回取消完成；
- 恢复：优先使用后端 `migrate-restore`（journal 路径直接取后端返回值，不自行拼接文件名），App 日志仅在旧后端时使用兜底改名；可选 `--remove-installed`（默认关闭）；
- 计划：一键迁移计划显示后端返回的预计跳过数（`will_skip`/`skip_count`）；
- 所有真实写入/移出在 UI 二次确认；self-test 全程使用临时 HOME/DSH_HOME，并在结束校验真实 store 会话文件数不变。

## F. 安全边界

- 源 Harness 存储**只读**；
- 迁移产物默认写入用户选择的输出目录；
- 写入目标真实 store 仅通过后端 `migrate --mode install`（需显式确认 + 后端备份），默认关闭；
- 应用无网络请求、无遥测；历史仅本机保存。

## G. 与其它产物分工

- `tools/agent-session-import/`：转换器与 CLI（本应用的唯一后端）；
- `tools/session-converter-gui/`：开发者用的 Python Web GUI（浏览器形态，功能覆盖矩阵/证据等级/批量等）；
- 本应用：面向普通用户的原生 macOS 产品前端；两者互不依赖。
