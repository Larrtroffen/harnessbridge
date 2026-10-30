# CLI 参考 — `asi`

`asi`（Agent Session Import）是 HarnessBridge 背后的 Python 3 命令行引擎，负责读取、转换、迁移、校验与恢复 Agent 会话。macOS App 调用的就是同一套 CLI；这里展示的 JSON 信封即 App 所消费的格式。

> 本页是实用速查。完整字段、adapter 说明与逐批验收数据见 [`usage.md`](usage.md) 与 [`atif-interop-protocol.md`](atif-interop-protocol.md)。

## 依赖

- Python **3.10+**（仅标准库，无需 `pip install`）。
- 可选：`zstd` CLI（`brew install zstd`），用于 DeepSeek Harness 压缩产物；可用 `--no-zstd` 跳过。
- macOS/Linux。CLI 不依赖 GUI/App；Windows 未纳入 CI 覆盖。
- 在仓库根目录运行，或用绝对路径：

```bash
python3 tools/agent-session-import/asi --help
python3 tools/agent-session-import/asi --version   # asi 0.1.0
```

所有命令都支持 `--json`；默认输出人类可读文本。JSON 中的路径是真实绝对路径。

## 环境变量覆盖

所有 store 根路径都可用环境变量覆盖——测试套件依赖这一点避免写真实数据，你也可以让它指向复制出来的 store：

| 变量 | 作用 | 默认值 |
|---|---|---|
| `HOME` | journal/应用数据默认根 | 用户 home |
| `DSH_HOME` | DeepSeek Harness | `~/.dsh` |
| `CLAUDE_CONFIG_DIR` | Claude Code | `~/.claude` |
| `CODEX_HOME` | Codex | `~/.codex` |
| `OMP_SESSION_DIR` | OMP | `~/.omp/agent/sessions` |
| `QODER_CONFIG_DIR` | Qoder | `~/.qoder` |
| `PI_HOME` | Pi | `~/.pi` |
| `GEMINI_HOME` | Gemini CLI | `~/.gemini` |
| `GOOSE_PATH_ROOT` | Goose | `~/.local/share/goose` |

## 命令总览

| 命令 | 用途 | 是否写入？ |
|---|---|---|
| `asi detect` | 发现 Harness、store 路径、会话数、安装能力 | 否 |
| `asi list` | 列出某来源的会话 | 否 |
| `asi preview` | 预览会话（最近消息） | 否 |
| `asi session-detail` | App 详情页所需的时间线/分区/用量 | 否 |
| `asi convert` | 转换为 DSH JSONL / ATIF / IR / 原生格式 | 仅 `--out` 或 `--install --yes` |
| `asi import` | 导入到 DSH home（`--dsh-home`） | 是（`--yes`） |
| `asi migrate` | 产品级迁移：转换 → 安装 → 校验（可导出兜底） | 是（install 需 `--yes`） |
| `asi migrate-all` | 一键把其他所有 Harness 迁移到一个目标 | 是（`--yes`） |
| `asi migrate-restore` | 撤销 journal 记录的源会话移出 | 是（反向改名） |
| `asi verify` | 校验 DSH 产物 | 否 |
| `asi matrix*` | 运行互转回归矩阵（维护者用） | 否（报告写入 tests/artifacts） |

## `asi detect`

```bash
asi detect --json            # 轻量文件系统扫描（默认，<2s）
asi detect --json --deep     # 读取索引/内容，慢但字段完整
```

每个 Harness 条目包含：

```json
{
  "id": "dsh",
  "name": "DeepSeek Harness",
  "detected": true,
  "session_count": 246,
  "path": "/Users/you/.dsh/sessions",
  "capabilities": {"export": true, "install": true, "install_experimental": false, "preview": true},
  "store_path": "/Users/you/.dsh/sessions",
  "install_supported": true,
  "install_experimental": false,
  "how_to_see": "重启 DeepSeek Harness 后可在会话列表看到…",
  "session_dir_hint": "sessions/<projectKey(cwd)>/<session-id>/session.v4.jsonl.zstd"
}
```

用 `store_path` + `install_supported` 判断迁移会写到哪里，用 `how_to_see` 告诉用户迁移后如何打开。

## `asi list`

```bash
asi list claude --json
asi list codex --limit 20 --json
asi list dsh --json --dsh-home /tmp/isolated-dsh
```

返回信封：`{ "ok": true, "command": "list", "source": "claude", "count": 3, "sessions": [{ "id", "title", "cwd", "path", "lines", "model", "created_at_ms", "updated_at_ms" }] }`。

`--root` 可覆盖来源根目录（适合复制/隔离 store）；`--include-archived` 可包含 Codex 已归档线程。

## `asi preview` / `asi session-detail`

```bash
asi preview --from claude --session <id> --json
asi session-detail --from qoder --session <id> --json --max-events 2000 --text-limit 400
```

- `preview` 返回最近消息摘要（只读）。
- `session-detail` 返回 App 详情页所需的稳定字段：会话元数据、有序时间线、分区、配对的工具调用/结果，以及来源提供的 Token 用量；来源没有时 `usage.available=false`——**不编造统计**。

## `asi convert`（转换/导出）

```bash
# 导出到文件夹（最安全；不碰任何 Harness 会话库）
asi convert --from codex --session <id> --to atif --out ~/Documents/HarnessBridgeOut --json
asi convert --from claude --all --to dsh --out /tmp/export --limit 5 --json

# 可选直装到目标 store（DSH；需确认）
asi convert --from claude --session <id> --to dsh --install --yes --install-root /tmp/isolated-dsh --json
```

`--to` 接受 `dsh`、`atif`、`ir` 或原生 writer 名（完整列表见 `asi convert --help`；`antigravity` 无 writer）。`--no-zstd` 跳过 DSH 压缩产物。

## `asi import`

把会话写入 **DSH home** 的传统路径：

```bash
asi import --from codex --session <id> --dsh-home ~/.dsh --dry-run --json
asi import --from codex --session <id> --dsh-home ~/.dsh --yes --register --json
```

`--dry-run` 只打印计划；`--overwrite` 覆盖既有会话文件；`--register` 写入 `workspace.json` 的 sessionIds。

## `asi migrate` — 产品级迁移

目标支持直装时默认 **install**；否则 export。真实 store 写入必须 `--yes`。

```bash
# 1) 先看能力
asi detect --json

# 2) dry-run：只出计划，零写入
asi migrate --from claude --session <id> --to dsh --dry-run --json

# 3) 直装（保留源）
asi migrate --from claude --session <id> --to dsh --yes --register --json

# 4) 直装 + 移出源（可恢复；仅安装+校验成功后）
asi migrate --from codex --session <id> --to omp --yes --session-mode move --json

# 5) 改为导出（高级）
asi migrate --from codex --session <id> --to atif --mode export --out /tmp/export --json
```

关键参数：

| 参数 | 含义 |
|---|---|
| `--mode install` / `--mode export` | 直装目标 store vs 导出到文件夹（默认自动：支持则 install） |
| `--session-mode keep` / `move` | 保留源（默认）或在校验成功后改名为 `*.migrated-<ts>.bak` |
| `--journal <path>` | 恢复日志路径（以返回的 `journal_path` 为准；v1.5.0 后端默认 `~/Library/Application Support/HarnessBridge/journals/migrate-<ts>-<rand>.json`） |
| `--overwrite` | 覆盖前先备份同 id 目标（`*.asi-backup-<ts>`），默认跳过 |
| `--register` | 仅 DSH：同时注册到 `workspace.json` |
| `--dry-run` | 只出计划——零写入、不写 journal |
| `--yes` | install 写入必需 |
| `--session <id-or-path>`（可重复）/ `--all` / `--all-limit N` | 选择会话 |
| `--root <path>` | 覆盖来源根（测试/复制 store） |
| `--target-cwd` / `--fallback-cwd` | 覆盖/回退目标的 cwd 映射 |

结果条目示例（截断）：

```json
{
  "source_session_id": "b59c58e1-…",
  "status": "ok",
  "verified": true,
  "installed_path": "/Users/you/.dsh/sessions/…/session.v4.jsonl.zstd",
  "source_path": "/Users/you/.claude/projects/…/b59c58e1-….jsonl",
  "source_moved": true,
  "source_move_status": "moved",
  "source_backup_path": "/Users/you/.claude/projects/…/b59c58e1-….jsonl.migrated-1793387793719.bak",
  "journal_path": "/Users/you/Library/Application Support/HarnessBridge/journals/migrate-20261030-191633-719-d25429.json"
}
```

安全行为：
- 目标已有同 id → `skipped-exists`（除非 `--overwrite`）；
- 失败回滚本次新建的文件/目录并恢复覆盖前备份；
- `source_move_status` 为 `moved` / `unsupported` / `failed`——请求了 move 但无法执行时如实报告未移动，绝不假报；
- 每完成一个会话就原子追加 journal，中断批次仍保留下恢复映射。

## `asi migrate-all`

```bash
# 预览（零写入）
asi migrate-all --to dsh --from claude,codex --limit 10 --since-days 30 --session-mode keep --dry-run --json

# 执行（需 --yes）
asi migrate-all --to dsh --limit 10 --session-mode keep --yes --json
```

- 来源默认为**其他所有已检测且有会话的 Harness**；`--from id1,id2` 可收窄。
- `--limit` 是**每个来源**的上限；`--since-days` 按会话更新时间过滤。
- 返回 `plan.sources[]`、`plan.total`、`plan.skip_count`/`will_skip`（dry-run）、`results[]`、`summary{total,ok,failed,skipped,moved,verified}` 与 `journal_path`。
- 重复项跳过；失败不中断批次；取消（SIGTERM）会保留已完成项的有效 journal。

## `asi migrate-restore`

```bash
asi migrate-restore --journal /path/to/journal.json --dry-run --json
asi migrate-restore --journal /path/to/journal.json --json
asi migrate-restore --journal /path/to/journal.json --remove-installed --json
```

把源文件从 `*.migrated-*.bak` **反向改回**原路径。默认**保留**已安装到目标库的副本；只有 `--remove-installed` 才删除该 journal 安装的目标文件。结果状态：`restored` / `already-restored` / `skipped-original-exists` / `missing-backup` / `failed`。

## `asi verify`

```bash
asi verify ~/.dsh/sessions/<project>/<session-id>
asi verify /tmp/artifact-root --json
```

校验 DSH 产物（header、seq、surfaceOp、工具配对）。退出码 0 表示干净；JSON 含逐项检查结果。

## 退出码与自动化

- `0` — 成功（含计划与空结果）。
- 非零 — 失败。`migrate`/`migrate-all` 缺少 `--yes` 返回 `requires_yes` 错误并非零退出（2）。
- 传 `--json` 时 stdout 为 JSON（个别拒绝路径会先打印一行人类可读提示，严格解析器需容忍首行），stderr 为诊断信息。
- `--dry-run` 绝不修改文件系统，可安全用于 CI。

## 常用配方

```bash
# 迁移前先复制备份一份 store（只读复制）
cp -R ~/.dsh/sessions /tmp/dsh-backup-$(date +%s)

# 写之前先看清一切
asi detect --json | python3 -m json.tool
asi list claude --json | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["sessions"]))'

# 迁移一个会话，并保留可撤销能力
asi migrate --from claude --session <id> --to omp --yes --session-mode move --json
# ……之后用返回的 journal_path 恢复
asi migrate-restore --journal "<journal_path>" --json
```

另见：[兼容性](COMPATIBILITY.zh-CN.md) · [FAQ](FAQ.zh-CN.md) · [架构](ARCHITECTURE.zh-CN.md)
