# 常见问题（FAQ）

## 通用

### HarnessBridge 到底做什么？

它把**一个 Agent 会话的对话历史**从一个 AI 编程 Harness 搬到另一个。例如：读取 Claude Code 的会话，经开放的 ATIF v1.8 格式转换，写入 DeepSeek Harness 的本机会话库——之后 DSH 就能把它当作会话列出来。

它不是云同步、不是代理、也不是账号/备份产品。一切都是本地文件。

### 会修改或删除我的原始会话吗？

默认**不会**——源只读。

只有显式开启 `--session-mode move`（App 中需二次确认）时，才会在目标安装**校验成功之后**，把源会话文件在同目录改名为 `*.migrated-<时间戳>.bak`；绝不删除，可随时恢复（`asi migrate-restore --journal …` 或 App 恢复按钮）。

### 转换是无损的吗？

不一定。中枢格式（ATIF v1.8）无法表达所有 Harness 私有概念（图像/音频、私有事件、部分工具调用配对、厂商元数据）。转换会输出 `lossy` 与 warning，而不是假装无损。简单文本/工具会话互转效果较好；富内容会话可能丢失细节。

### ATIF 是什么，为什么重要？

ATIF = **Agent Trajectory Interchange Format**，Harbor 项目的开放规范（RFC 0001，v1.8，Apache-2.0）。用公开的中枢格式意味着转换后的历史可被本工具之外检查，不锁定在内部模型里。注意：ATIF 是*轨迹日志*格式，不是 Agent 的 *resume/checkpoint* 格式。

## 安装与首次启动

### macOS 提示“无法验证开发者”/“应用已损坏”

Release DMG 是 **ad-hoc 签名、未经 Apple 公证**（暂无 Developer ID）。首次启动会被 Gatekeeper 拦截：

- 右键 App → **打开** → 打开；或
- 清除 quarantine 属性：
  ```bash
  xattr -dr com.apple.quarantine /Applications/HarnessBridge.app
  ```

如果不想看到警告，也可以从源码构建。未来版本计划公证。

### 系统要求？

- App：macOS 13+；预编译 DMG 为 Apple Silicon，Intel 需源码构建。
- CLI：Python 3.10+（仅标准库），可选 `zstd` CLI 处理 DSH 产物。

### 为什么 DMG 只有 arm64？Intel 能用吗？

公开预编译包是 `HarnessBridge-1.5.0-macos-arm64.dmg`（CI 在 Apple Silicon runner 上构建）。Intel Mac 可以 `git clone` 后用 Xcode Command Line Tools 本地执行 `./build.sh`。

## 使用 App

### 迁移完成但目标工具看不到会话

- **DeepSeek Harness**：重启 DSH；若勾选了“注册到项目”，重启后打开对应项目/工作区。
- **Claude Code**：重启 `claude`，再 `claude --resume`。
- **OMP / Qoder / Pi**：重启对应工具。
- **Gemini CLI**：重启后 `/resume`。
- **Codex**：`codex resume`；Codex 可能需要重建线程索引（实验性目标）。

同时看结果页的 `installed_path`、`verified` 与逐条 `status`，能确认实际写入了什么。`skipped-exists` 表示目标已有同 id 会话（确实要替换时用 `--overwrite`，会先备份）。

### 为什么有条目被跳过？

目标会话库里已存在相同 id 的会话。默认策略是**跳过、绝不覆盖**。要替换请使用高级覆盖选项 / `--overwrite`，CLI 会先把旧目标改名为 `*.asi-backup-<时间戳>`。

### 如何撤销一次 move 迁移？

在 **迁移历史** 或结果页点 **「恢复被移出的会话」**，或执行：

```bash
asi migrate-restore --journal "<结果中的 journal path>" --json
```

它会把 `*.migrated-*.bak` 改回原路径。已安装到目标库的副本默认保留；加 `--remove-installed` 才一并删除。

### 数据、历史与日志存在哪里？

- App 数据（历史、检测缓存、App 侧 journal）：`~/Library/Application Support/HarnessBridge/`
- CLI/后端迁移 journal：以命令返回的 `journal_path` 为准；v1.5.0 后端默认 `~/Library/Application Support/HarnessBridge/journals/`（历史 companion 目录，计划改为 HarnessBridge）
- 默认导出目录：`~/Documents/HarnessBridgeOut/`
- CLI 导出默认：`./asi-out/`、`./asi-migrate/`（当前工作目录）
- move 源备份：原会话文件旁，`*.migrated-*.bak`

App **不联网、无遥测**，一切都在你的 Mac 上。

### 如何彻底卸载 / 清理？

1. 退出 HarnessBridge 并删除 `/Applications/HarnessBridge.app`。
2. 可选删除：`~/Library/Application Support/HarnessBridge/` 与 `~/Documents/HarnessBridgeOut/`。
3. 如果用过 move 且要拿回源会话，请先从 App 历史/journal 恢复——**恢复前不要删除 journal 或 `.bak` 文件**。
4. 已安装进某个 Harness store 的会话，需要在该工具内删除，或用 `asi migrate-restore --remove-installed` 移除。

## CLI 与自动化

### App 和 CLI 行为一致吗？

一致——App 是同一套 CLI 的前端。安全规则（`--yes`、dry-run、备份、journal）只在 CLI 实现一次。

### `migrate` 不带 `--yes` 会失败，是 bug 吗？

不是。任何真实 store 写入都需要明确确认。预览请用 `--dry-run`；缺少 `--yes` 返回 `requires_yes` 错误并非零退出，不写任何东西。

### 如何安全测试而不碰真实 store？

用 `--dry-run`，或用环境变量把 CLI 指向隔离目录：

```bash
export HOME=/tmp/hb-test
export DSH_HOME=$HOME/.dsh
export CLAUDE_CONFIG_DIR=$HOME/.claude
asi detect --json
```

测试套件就是这么跑的。切勿提交或分享真实 store 中的密钥/私有路径。

### 迁移被取消/中断，数据还能恢复吗？

journal 是原子且增量写入的：每个已完成会话都已记录。已完成的 move 保留 `.bak` 映射，可恢复；重跑迁移会跳过已安装会话（或用 `--overwrite` 刷新）。

### 详情页为什么显示 Token 统计不可用？

源 Harness 没有为该会话暴露 usage（或是无 Token 统计的合成/导入产物）。HarnessBridge 报 `usage.available=false`，不估算数字。

## 兼容性与贡献

### 为什么有些目标标注“实验性”？

Writer 基于对该工具本地格式的最佳理解，并通过读回产物校验；但厂商可能改变格式/索引，工具也可能需要重启或重建索引。实验性 = best-effort；请保留备份，谨慎对待版本升级。

### 某个 Harness 不受支持，能加吗？

可以——这是主要贡献路径：新增 reader/writer + 脱敏 fixture，在 `docs/COMPATIBILITY.zh-CN.md` 记录证据/限制，然后发 PR。脱敏真实样本是把格式从 FIXTURE 提升到 REAL 的最快方式。

### 这和 GitHub 上的 `mandyyyyii/HarnessBridge` 是同一个项目吗？

不是。本项目是 `Larrtroffen/harnessbridge`；另一个仓库只是恰好同名，无任何关联。

### 项目许可证？可以商用吗？

MIT，见 [LICENSE](../LICENSE)。Harness 名称/Logo 的商标归各自所有者；MIT 覆盖本项目的代码与文档，不覆盖第三方商标或 fixture。详见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

### 支持 Windows 吗？

CLI 是纯 Python，理论上可在 Windows 运行，但未经测试、未纳入 CI（路径/引号差异）。App 仅支持 macOS。
