# agent-session-import (`asi`) 使用说明

把 **Claude Code**（`~/.claude`）、**Codex**（`~/.codex`）、**OMP / oh-my-pi**（`~/.omp`）、
**Qoder**（`~/.qoder`）与 **DeepSeek Harness (DSH) v4**（`~/.dsh`）五个 harness 的会话**两两互转**
（以 **ATIF v1.8** 为统一中枢，也可直接读写各 harness 原生存储），并内置 20 方向互转矩阵自动验收。

- 纯 Python 标准库实现（readers / writer / verify / CLI），只额外依赖 **zstd CLI** 做压缩（`brew install zstd`，本机 `/opt/homebrew/bin/zstd`）。
- 不修改 `~/.codex` / `~/.qoder` / `~/.omp`；`convert` 永远不碰 `~/.dsh`；`import` 默认目标 `~/.dsh` 但**必须显式 `--yes`**，并可用 `--dsh-home` 指向隔离目录做演练。
- DSH 格式依据：`docs/formats/dsh.md`（权威：双 zstd 帧、header 白名单、seq 连续、surfaceOp、配对规则）。
  三源格式逆向依据：`docs/formats/codex.md`、`docs/formats/qoder.md`、`docs/formats/omp.md`。

```
tools/agent-session-import/
├── asi                                  # CLI 入口（可执行）
├── agent_session_import/
│   ├── cli.py                           # list / convert / import / verify
│   ├── ir.py                            # 统一中间表示（IR）
│   ├── readers/{claude,codex,dsh,omp,qoder}.py  # 5 个源 reader
│   ├── writers/{claude,codex,dsh,omp,qoder}.py  # 目标侧原生 writer
│   ├── targets.py                       # 目标根/env 隔离/L3 原生发现验证
│   ├── matrix.py                        # 20 方向矩阵 + markdown/JSON 报告
│   ├── atif.py                          # ATIF v1.8 导入/导出（中枢）
│   ├── dsh.py                           # DSH v4 writer / 导入 / 校验
│   └── common.py
├── tests/test_asi.py                    # 28 个测试（samples/ + 临时隔离 store fixture）
├── tests/e2e_load.mjs                   # 用真实 DSH 代码 Session.fromRestore 读回验证
└── tests/fixtures/codex-sample.atif.json# 由真实样本生成的 ATIF v1.8 样例
```

## 1. 快速开始

所有命令在 `tools/agent-session-import/` 目录下执行（或用绝对路径调用 `asi`）：

```bash
cd tools/agent-session-import

# A) 列出本机可导入会话（id / 时间 / 标题 / 行数 / cwd）
./asi list codex
./asi list qoder
./asi list omp
./asi list atif --root /path/to/atif-dir      # 列出 ATIF 文件

# B) 转换到 DSH v4（只写 --out 目录，绝不碰 ~/.dsh）
./asi convert --from codex --session <thread-id | rollout.jsonl> --out /tmp/asi-out
./asi convert --from qoder --all --out /tmp/asi-out --no-zstd    # 批量时不压缩更快
./asi convert --from omp   --session <session-id | file.jsonl> --out /tmp/asi-out

# C) 校验产物（header 白名单 / 双帧 / seq / surfaceOp / tool 配对）
./asi verify /tmp/asi-out
./asi verify /tmp/dsh-home-test/sessions

# D') 五路互转（IR/ATIF/原生目标；默认只写 --out 暂存目录）
./asi list claude; ./asi list dsh                       # 5 个 source
./asi convert --from claude --session <id|path> --to atif --out /tmp/asi-out
./asi convert --from codex  --session <id|path> --to claude --out /tmp/asi-out
./asi convert --from omp    --session <id|path> --to qoder  --out /tmp/asi-out
./asi convert --from dsh    --session <id|path> --to codex  --out /tmp/asi-out

# E) 写入目标 harness 原生 store：--install 必须 --yes；--install-root / env 隔离
CODEX_HOME=/tmp/codex-home ./asi convert --from claude --session <id|path> \
  --to codex --install --yes
CLAUDE_CONFIG_DIR=/tmp/claude-home ./asi convert --from codex --session <id|path> \
  --to claude --install --yes
DSH_HOME=/tmp/dsh-home ./asi convert --from qoder --session <id|path> --to dsh --install --yes
./asi convert --from codex --session <id|path> --to omp --install --yes --install-root /tmp/omp-sessions

# F) 5×5 有序方向矩阵（20 方向 + 5 个 ATIF 自往返；失败退出码非 0）
./asi matrix --out /tmp/asi-matrix --report /tmp/matrix-report.json \
  --doc docs/interop-matrix.md --verbose

# D) 导入到 DSH（先 dry-run 看计划；写入必须 --yes）
./asi import --from codex --session <id> --dsh-home /tmp/dsh-home-test --dry-run
./asi import --from codex --session <id> --dsh-home /tmp/dsh-home-test --yes
./asi import --from qoder --all --dsh-home /tmp/dsh-home-test --yes --register   # 可选注册到 workspace

# 全量导入：很多源会话的原始 cwd 已不存在（本机实测 133/366），用 --fallback-cwd 兜底；
# 存在的源 cwd 仍按 provenance 保留，--target-cwd 则是全局强制覆盖。
./asi import --from codex --all --dsh-home /tmp/dsh-home-test \
  --fallback-cwd ~/Documents/deepseek-harness/default-workspace --dry-run
./asi import --from omp --all --dsh-home ~/.dsh \
  --fallback-cwd ~/Documents/deepseek-harness/default-workspace --yes --register
```

## 2. `convert` 输出

`--to dsh`（默认）输出目录：

```
<out>/<source>/<source-session-id>/
├── ir.json                    # 规范化 IR（可检查、可 diff；见 ir.py 顶部 schema）
├── session.v4.jsonl           # 明文 DSH v4 JSONL（header + 事件，1 行 1 条）
└── session.v4.jsonl.zstd      # 双 zstd 帧：帧1=单行 header，帧2=全部事件行（可直接导入）
```

`--to atif` 输出 `<out>/<source>/<sid>/<sid>.atif.json`；`--to ir` 只写 IR。
`--no-zstd` 跳过 zstd 产物（批量/调试用）。`--keep-system` 把源里的 system/developer 注入保留为
DSH `system/message`（默认丢弃，避免把几十 KB 技能说明塞进对话）。

转换内容映射（统一 IR：user / assistant(text,reasoning,tool-call) / tool_result / system / compaction）：

| 源 | 读取要点 |
|---|---|
| Codex | 以 rollout JSONL 为权威源，按 `ordinal` 排序；`state_5.sqlite.threads` 只作线程索引（取 `rollout_path`、标题、cwd）。过滤 `developer` 角色与 `<environment_context>` 等注入 user 项；`reasoning.summary[].text` 作为思考；`function_call`/`custom_tool_call` 与 `*_output` 按 `call_id` 配对；`compacted` 记入 IR compaction（不写 DSH 事件）。fork 副本按 thread id 取当前文件，不拼接。 |
| Qoder | assistant **一行一个 block**，按连续相同 `message.id` 合并为一条逻辑消息；`tool_result` 是父链旁支，必须用 `tool_use_id`（及 `sourceToolAssistantUUID`）配对；最终分支 = 最后一条 `active-leaf.leafUuid` 沿 `parentUuid` 回溯，旁支被放弃内容不导出；4 类 user 行（人类输入 / tool_result / 系统注入 / 图片）分别处理；时间戳 ISO 与 epoch ms 混用需归一。 |
| OMP | 树状事件流（`id`/`parentId`），第 1 行恒 `title`、第 2 行恒 `session`，行序 ≠ 时间序；取"无子节点且 timestamp 最新"的叶子回溯当前分支；`message.role` = user/assistant/toolResult/developer；assistant content `thinking`/`text`/`toolCall` 拆块，`toolCall.id` 与 toolResult `toolCallId` 配对；`arguments` 是对象（忽略 `partialArgs`）。仅导入主 transcript，伴生目录里的子代理 `.jsonl` 默认不递归。 |

工具名保留原名（`exec_command`、`Bash`、`bash`…），别名为空时用 `tool`。图片附件一律降级为文本占位
`[image attachment not imported]`（Qoder 的 OSS URL 会过期，默认不下载、不请求）。

## 3. `import`：写入 DSH 与安全策略

- 目录布局：`<dsh-home>/sessions/--<projectKey(cwd)>--/<encodeSegment(sessionId)>/session.v4.jsonl.zstd`；
  header 的 `id`/`cwd` 与目录名严格对应（否则 DSH 判 `corrupt session log`）。
- `sessionId` 由源类型 + 源会话 id 确定性生成：`session-<uuid5>`。**同一会话重复导入自动跳过**（幂等），
  `--overwrite` 才覆盖；写入用临时文件 + `os.replace`，失败会清理本次新建的目录/文件。
- **cwd / provenance 策略**（优先级 `--target-cwd` > 源 cwd > `--fallback-cwd`）：
  默认取源会话记录的原始 cwd（项目路径原样保留）；源 cwd 缺失或在本机不是目录时，若给了
  `--fallback-cwd <已存在目录>` 则用它作为 header cwd，并在输出中注明
  `cwd 缺失 → fallback 到 <目录>`；未给 `--fallback-cwd` 则报错并提示 `--fallback-cwd` / `--target-cwd`
  （不静默改写）。`--target-cwd` 永远优先（全局覆盖）。header 里写 `realpath(cwd)`。
  **fallback 会话的 provenance 只保留在 IR 的 `cwd` 字段（`ir.json`）、`source_path` 和确定性 id
  （由 source + source_session_id 生成）中**，DSH 侧 header 只能看到 fallback 后的 cwd。
- 汇总计数：`import` 结束打印 `imported / overwritten / skipped / failed / fallback_used`；
  `--dry-run` 打印 `would import / would skip / fallback_used / failed`（以及逐会话计划），
  便于在真实数据上先核对 fallback 数量再决定是否写入。
- 默认写入**真实 `~/.dsh` 必须 `--yes`**；不加 `--yes` 直接拒绝（退出码 2）。建议先：
  1. `--dry-run` 打印每个会话的 session_id / cwd / 目标路径（全量时加 `--fallback-cwd`）；
  2. 用 `--dsh-home /tmp/dsh-home-test --yes` 在隔离目录演练 + `asi verify`；
  3. 确认 DSH 桌面端**已退出**（运行中的 app 以内存态为准，可能覆盖 workspace.json 或与新文件竞争）后再写真实目录。
- DSH 目标的 workspace 注册现在**默认开启**（单会话与一键迁移均会尝试把新会话挂到 `cwd` 对应的 workspace；`--no-register` 可关闭）。**先退出 DSH 桌面端**，否则运行中的内存态可能覆盖 workspace.json。
- `--register`：兼容保留；在**先备份** `~/.dsh/storages/workspace.json`（`workspace.json.bak.<epoch_ms>`）后，
  把 id 前插到 `path` 与目标 cwd 相同的 workspace 的 `sessionIds`，并更新 `updatedAt`（原子替换）。
  **对本次被 skip 的会话（artifact 已存在）同样执行注册**——因此支持"先 `--yes` 批量导入、之后再补
  `--register`"的用法；已注册的 id 幂等跳过（不重复插入、不重复备份）。`--dry-run` 只打印每个会话的
  `register: would-register|already|skipped` 计划，不写文件。
  不注册也能被发现：DSH 冷启动扫描 `sessions/` 根目录，未归属会话显示在侧边栏 **"Ungrouped"** 组；
  要归入项目组，需退出 DSH 后注册（详见 `docs/formats/dsh.md` §7/§9）。
- `import` 不写 projcache（纯派生缓存，DSH 打开会话时自动重建）。

> 本次交付**未向本机真实 `~/.dsh` 写入任何数据**；所有 E2E 均在 `/tmp` 隔离 DSH_HOME 中完成。

## 4. ATIF v1.8 互转

ATIF = Harbor RFC 0001 *Agent Trajectory Interchange Format*（`schema_version: "ATIF-v1.8"`，
`trajectory_id`、`agent{name,version,model_name}`、`steps[]{step_id, source: system|user|agent,
timestamp, message, reasoning_content, tool_calls[], observation.results[], metrics}`）。
它是轨迹/日志格式，不是 harness resume 状态；本工具把它当作与 IR 平行的交换格式。

```bash
# 源会话 -> ATIF v1.8
./asi convert --from codex --session <id|path> --to atif --out /tmp/asi-atif
./asi convert --from qoder --all  --to atif --out /tmp/asi-atif
./asi convert --from omp   --session <id|path> --to atif --out /tmp/asi-atif

# 列出现有 ATIF 文件
./asi list atif --root /tmp/asi-atif

# ATIF -> DSH v4（隔离 home；cwd 取自 ATIF extra.cwd，否则必须 --target-cwd）
./asi import --from atif --session /tmp/asi-atif/codex/<sid>/<sid>.atif.json \
  --dsh-home /tmp/dsh-home-test --yes
./asi verify /tmp/dsh-home-test/sessions
```

映射要点：user step → `user/message`；agent step 的 `reasoning_content`/message/tool_calls →
`assistant/message` 的 reasoning/text/tool-call blocks，`observation.results[]` → `tool/result`
（`source_call_id` 即 callId）；system step → `system/message`（仅 `--keep-system`）；
`metrics` → DSH `usage`；`extra.cwd/title/system_prompt` 保留 provenance。
ATIF 往返样例：`tests/fixtures/codex-sample.atif.json`（由 `samples/codex/rollout-small-full.jsonl` 生成）。

## 5. 校验（`verify`）

对每个 session 文件检查：

1. zstd 为**≥2 个独立帧**、第 1 帧解压后**恰好 1 行 header**（带 `\n`）；
2. header 白名单键全、`version=4`、`createdAt` 非负整数、`cwd` 绝对路径、无退休字段；
3. 事件 `seq` 从 0 连续；envelope 只用 7 个允许键；log-only 事件不带 `surfaceOp`；
4. 5 种 surface 事件（`system/developer/user/assistant message`、`tool/result`）必须 `surfaceOp:"append"`；
5. `assistant/message` 有 `turn/step/stream:[]` 且 source=model+provider+model；`usage` 若存在含 inputTokens/outputTokens；
6. `tool/result` 的 `source.callId == toolCallId` 且 `sourceEventSeqs` 指向更早的 `tool/call`；
7. **每条 assistant tool-call block ↔ 一条 `tool/call` ↔ 一条 `tool/result`**（源里缺失结果时 writer 写占位结果）；
8. 目录/header 身份一致（DSH 布局下 `session dir == encodeSegment(id)`、`project dir == projectKey(cwd)`）；
9. 有 surface 内容却缺 `turn/start`（会被 DSH 当 blank 隐藏）、缺尾部 `session/end-seed` → 警告。

退出码：有 ERROR 返回 1。`verify` 也接受 `samples/dsh/01-minimal-valid-session.jsonl` 这类官方样本。

## 6. 测试

```bash
cd tools/agent-session-import
python3 -m unittest discover -s tests -v
node tests/e2e_load.mjs /tmp/dsh-home-test/sessions/.../session.v4.jsonl.zstd   # 真实 DSH 代码只读加载
```

- 28 个测试覆盖：路径编码、三源真实样本转换（Codex 28 行 / Qoder 25 行 / OMP 42 行）、IR→DSH 事件不变量、
  `verify` 正/负例、ATIF 导出/回灌、隔离目录导入（幂等 `skipped`、skip 后补 `--register`、重复注册幂等）、
  `--fallback-cwd`（缺失 cwd 兜底 / 存在 cwd 优先 / `--target-cwd` 最优先 / dry-run 计数）、
  `--yes` 拒绝、`--dry-run` 零写入、**5 个原生 writer→reader 往返**、**ATIF 中枢→5 目标**、
  **`--install`（无 `--yes` 拒绝 + `--install-root` 隔离写入）**、**`asi matrix` 冒烟（schema/字段/自往返）**、
  `asi list claude|dsh --json` 字段契约，以及用全局安装的 `@deepseek-ai/dsh` 包 `Session.fromRestore`
  对导入产物做真实加载（`seq>0`、消息数>0、首条为 user）。
- 测试**不读写** `~/.dsh`、`~/.codex`、`~/.qoder`、`~/.omp`（除只读样例外只用 `samples/` 与临时目录）。

## 7. 已知限制 / 未完成项

1. **子代理轨迹不递归**：Qoder `subagents/agent-*.jsonl`、OMP 伴生目录 `<Child>.jsonl`、Codex 独立
   subagent thread 不并入主会话（Codex 可在 `list` 中单独导入）。DSH 侧如需子会话需 `parentSession`/`origin`
   header，本工具未生成。
2. **上下文压缩只记录不写 DSH 事件**：IR 保留 compaction（summary/tokens/boundary），writer 跳过
   `compaction/*`（不加载必需，且 payload 语义需更多实测）。压缩摘要不会被当作普通 user 消息。
3. **图片附件降级**：不下载 OSS/远程图片，统一文本占位；无 `image` attachment 实体。
4. **Qoder 内部模型 UUID**：默认模型的内部 key（如 `eb7e9f84-…`）不可读，原样写入 DSH `model` 字段；
   未猜映射。
5. **时间戳**：统一为 epoch ms（ISO/秒/毫秒三套已归一）；事件顺序以源权威顺序（Codex ordinal / Qoder 行序 /
   OMP 树路径）为准，不重排。
6. **Codex fork/续写副本**：按 thread id 取当前 rollout 文件；多文件历史请用 `thread_id` 分别导入，
   不做跨文件拼接。
7. `--no-zstd` 产物不能直接放进 DSH zstd root（encoding mismatch）；批量压测时建议 `--out /tmp` 并清理。
8. 真实导入验收需人工在 DSH GUI 侧确认（本次未启动/未写入真实 `~/.dsh`）。
9. **原生互转**：`system_message`/`compaction` 等 DSH 私有事件在多数目标 writer 中丢弃；源里缺失结果的
   tool call 会按 IR 约定补占位结果；L3 原生加载已升级（见 §8.2）：Claude（隔离配置+PTY resume 检测内容）、
   OMP（writer 模型映射到本机配置 + rpc 加载）、DSH（Session.fromRestore）通过；Codex 因 0.164 paginated
   thread store 不扫描裸 rollout 文件仍为 partial（已试命令与证据见矩阵报告）；Qoder 无 CLI 为格式级。
10. **矩阵**默认每个方向取 1 个真实会话（最短且非空），不是全量；报告结果可在 `tools/agent-session-import/tests/artifacts/interop-matrix.json` 复现。

## 8. 5 路互转 / 原生写入 / 20 方向矩阵（L3）

### 8.1 转换矩阵 CLI

```bash
asi convert --from <claude|codex|omp|qoder|dsh|atif> --to <claude|codex|omp|qoder|dsh|atif|ir> \
  --session <id|path> [--out DIR] [--json]
asi matrix [--sources claude,codex,dsh,omp,qoder] [--out DIR] [--report JSON] [--doc MD] [--json] [--no-l3]
```

- **默认只写 `--out` 暂存目录**（`<out>/<source>/<session-id>/` 下按目标原生布局），不碰任何真实 store。
- `--install --yes` 才写目标 harness store；`--install-root <dir>` 或对应 env 可隔离目标根，避免污染真实数据。
- 目标根（reader-root 语义）与环境隔离：

| target | 默认 store root | 环境变量（已验证/说明） |
|---|---|---|
| claude | `~/.claude/projects` | `CLAUDE_CONFIG_DIR`（其 `projects/` 子目录）✅ |
| codex | `~/.codex` | `CODEX_HOME` ✅ |
| dsh | `~/.dsh/sessions` | `DSH_HOME` ✅ |
| omp | `~/.omp/agent/sessions` | `--session-dir`（CLI 参数，隔离 session 存储）；本工具另支持 `--install-root`；无已核实 env ✅（`--session-dir` 模式） |
| qoder | `~/.qoder/projects` | Qoder CLI **未安装**（仅 IDE），无法 CLI 验证；`--install-root` 可隔离写入，L3 只能格式级 |

### 8.2 L3 目标侧发现/恢复验证（矩阵自动执行）

| target | 验证方式 | 本机结论 |
|---|---|---|
| dsh | 真实代码 `Session.fromRestore`（`tests/e2e_load.mjs`） | **通过**（seq/messages 与写入一致） |
| claude | 隔离 `CLAUDE_CONFIG_DIR`+最小 `.claude.json`(onboarding/trust)+假 `ANTHROPIC_API_KEY`，PTY `claude --bare --resume <绝对路径.jsonl>`，不输入 prompt，从 TUI 画面 grep 源会话文本 | **通过**（TUI 渲染源会话内容；无模型请求） |
| omp | writer 将 IR.model 映射到本机 `~/.omp/agent/config.yml` 的 `modelRoles.default`（可用 `ASI_OMP_FALLBACK_MODEL` 覆盖）；`omp --session-dir <staging> --mode=rpc -r <file> [--model <configured>]`（不发 prompt） | **通过**（原生加载 transcript；`<synthetic>`/未配置模型不再报 restore 失败） |
| codex | `CODEX_HOME=<staging> codex resume --last --include-non-interactive`（PTY）、`codex --no-alt-screen resume` picker、`codex app-server` 的 `thread/resume(path)`+`thread/items/list` 均已尝试 | **部分（已记录）**：0.164 的 paginated thread store 不扫描裸 rollout 文件（picker 报 0/0、by-id 报 No saved session）；app-server 可 resume thread 元数据但 items 依赖 `event_msg.item_completed` 物化，矩阵中未能稳定复现内容级 → 保留 partial，不虚报 |
| qoder | 无 CLI | **格式级**（schema + reader 读回验证；partial） |

### 8.3 矩阵报告

`asi matrix` 对 20 个有序方向（A≠B）各取 1 个本机真实会话：
`A reader→IR → ATIF v1.8 → IR → B 原生文件 → B reader 读回 → 语义比对`（消息条数/角色顺序/文本/
tool_call↔tool_result 配对/时间戳 ±5s），并另做 5 个 `A→ATIF→A` 自往返。
输出：`--doc docs/interop-matrix.md`（表格 + 证据）与 `--report report.json`（稳定 schema
`asi-interop-matrix/v1`；每个方向一条：
`{from,to,source_session_id,status,l0,l1,l2,l3,ir_counts,lossy,warnings,evidence_path}`）。
status = `pass`（无有损且 L3 通过）/ `partial`（有已知有损或 L3 仅部分/格式级）/ `fail`（L1/L2 语义不符）；
任一 fail → 退出码非 0。当前本机实测：**fail=0、pass=12 / partial=8、ATIF 自往返 5/5**
（claude/dsh/omp 目标共 12 个方向内容级 L3 通过；target=codex 4 个与 target=qoder 4 个仍 partial，
原因见 §8.2 与 [docs/interop-matrix.md](interop-matrix.md) 每方向 `l3.detail`）。

### 8.4 `--json` 接口（GUI 契约）

所有 `list/convert/import/verify/matrix` 均支持 `--json`：stdout 只输出一个 JSON 对象，进度/警告走 stderr，退出码语义不变。

- `list`：`{ok,command:"list",source,count,sessions:[{source,id,title,cwd,created_at_ms,updated_at_ms,path,lines,model,...}]}`
- `convert`：`{ok,command:"convert",source,to,out,summary:{converted,failed,total},results:[{source_session_id,status,output_dir,ir,artifact,native_root,relpath,installed?,isolation?,stats,warnings,error?}]}`
- `import`：`{ok,command:"import",dsh_home,dry_run,register,summary:{imported|would_import,skipped|would_skip,failed,fallback_used,total},results:[...],registrations:[...]}`
- `verify`：`{ok,command:"verify",checked,failed,results:[{path,ok,errors,warnings,info,header}]}`
- `matrix`：完整 `asi-interop-matrix/v1` 报告对象（含 `summary/directions/atif_self_roundtrip/sessions`）

## 9. 批 2：OSS 采集轨迹（traj-session/1）→ IR → ATIF → 原生 Harness

除本地 5 个原生 harness 外，本工具新增 **OSS 采集轨迹源 `oss`**：把 `traj-session/1` 归一化采集会话
（API 网关 request-level 录制 + 归一化管线产物，见 `docs/oss-trajectory-inventory.md` §5）转成 IR，
再经 ATIF 中枢落到各 harness。采集样本默认取 `samples/batch2/oss/`（不存在时回退 `samples/oss/`）。

```bash
# 列出采集会话（按 harness/model/messages_format 可见；--json 供 GUI）
cd tools/agent-session-import
./asi list oss                                  # 默认 samples/batch2/oss，否则 samples/oss
./asi list oss --root ../../samples/batch2/oss --json

# 单会话转换（OSS -> ATIF / IR / 任意已实现 target；--to dsh 需 --target-cwd，因为采集格式无 cwd）
./asi convert --from oss --session <session-id|path> --to atif --out /tmp/asi-oss
./asi convert --from oss --session <path> --to dsh --out /tmp/asi-oss \
  --target-cwd ~/Documents/deepseek-harness/default-workspace
./asi convert --from oss --session <path> --to claude --out /tmp/asi-oss

# 批 2 矩阵：每个 harness 标签 1 个真实采集会话
#   L0 OSS→IR / L1 ATIF 往返 / L2 DSH staging 读回 / L3 真实 Session.fromRestore /
#   L2' claude/codex/omp/qoder 格式级写入+读回
./asi matrix-batch2 --root ../../samples/batch2/oss \
  --report tests/artifacts/interop-matrix-batch2.json \
  --doc ../../docs/interop-matrix-batch2.md --verbose
./asi matrix-batch2 --root ../../samples/oss --limit 3 --no-format   # 冒烟
```

`--json` 输出 `asi-oss-batch2-matrix/v1` 报告：每个 harness 一条
`{harness, model, messages_format, source_session_id, source_messages, l0, l1, l2, l3, l2_format, lossy, status}`
+ `summary{harnesses,pass,partial,fail,formats,l3_dsh}`。任一 harness 的 DSH L3 失败 → 退出码非 0。

**口径（务必区分）**：`traj-session/1` 是**采集/中转格式**，不是任何 harness 的原生 session 格式
（事件粒度、`cwd`、`parentUuid` 链、原生元数据已丢失；保留的是三种 API messages 编码、harness 判定证据
与质量标记）。因此批 2 矩阵里 **L3 只对 DSH 是真实原生加载**（`Session.fromRestore`）；claude/codex/omp/qoder
是格式级 writer+reader 往返，不等于其 CLI 能恢复。采集样本中缺失/截断的 tool_result 会由 IR 补占位结果，
属于已知有损项（报告中以 warnings 记录），不做静默补全。

**本机实测（2026-10-30，batch2 快照）**：21 个采集会话文件 / **18 个 harness 标签**
（aider、cherry-studio、claude-code、cline、codex、cursor、factory-droid、hermes、kilo-code、opencode、
opencraw、other、pi、qoder、trae、windsurf、workbuddy、zcode），
三种 `messages_format` 全覆盖（anthropic-messages 16、openai-responses 1、openai-chat 1）；
矩阵 **pass=17 / partial=1 / fail=0，DSH 真实加载 18/18**。唯一 partial 为 `claude-code`
（L0/L1/L2/L3 全通过）：其 4 个格式级 target 中 **codex** 目标会按原生 response-item 语义重新分组
assistant 消息（写出的 block 内容/顺序完全一致，仅消息分组不同）→ 记 `message_grouping_normalized`
已知有损，报告逐条记录，不是转换错误。当前快照缺 `claude-desktop` 标签样本，待 oss-recon 补齐后
重跑同一命令即可扩展。

**采集重复行规范化（复跑稳定性的关键）**：部分采集会话把跨 API 调用的累计前缀重复写入 `messages`
（同一 assistant/tool_use 与 tool_result 出现多次）。`oss_traj` reader 会折叠连续重复消息并按
`call_id` 去重 tool_result（记 warning），IR 层把缺失结果的 tool call 在所属 step 末尾补占位结果；
否则 DSH writer 对同一 callId 只保留一个 result，会让读回顺序错位（此前 claude-code 的 DSH L2 ❌
即由此产生，现已修复）。

## 10. 批 3：6 个原生格式 adapter（FIXTURE 证据级）

批 3 新增 6 个 **原生格式** source：`copilot`（GitHub Copilot CLI 事件 JSONL）、`gemini`（Gemini CLI 单 JSON）、
`aider`（Aider Markdown history）、`cursor`（Cursor CLI transcript JSONL，current/legacy 两代）、
`qwen`（Qwen Code，Claude 衍生 JSONL envelope）、`pi`（pi.dev，OMP 同族树状 JSONL）。
**证据等级只到 FIXTURE**：fixtures 来自 `samples/batch2/public-fixtures/`（公开合成/裁剪样本，非真实会话）；
本轮不声明 NATIVE，也不声称任何 harness CLI 能 `--resume` 这些产物。

```bash
cd tools/agent-session-import
# fixtures 根：默认自动定位 samples/batch2/public-fixtures；也可 --root 指定目录/单文件
./asi list copilot --json            # 其余：gemini / aider / cursor / qwen / pi
./asi convert --from gemini --session <id|path> --to atif --out /tmp/asi-b3
./asi convert --from aider  --session <path> --to dsh --target-cwd ~/Documents/deepseek-harness/default-workspace --out /tmp/asi-b3
./asi convert --from pi     --session <path> --to claude --out /tmp/asi-b3   # --to 支持全部已实现 writer

# 批 3 矩阵：6 个 harness × (reader→IR / ATIF 往返 / DSH staging + 真实 Session.fromRestore / 原生 writer→reader 自往返)
./asi matrix-batch3 --root ../../samples/batch2/public-fixtures \
  --report tests/artifacts/interop-matrix-batch3.json \
  --doc ../../docs/interop-matrix-batch3.md --verbose
```

writer 默认只写 `--out` staging（原生布局：copilot `session-state/<uuid>/events.jsonl`、gemini
`tmp/<sha256(cwd)>/chats/session-*.json`、aider `history/<hash>.md`、cursor
`projects/<slug>/agent-transcripts/<sid>/<sid>.jsonl`、qwen `projects/<enc-cwd>/chats/<uuid>.jsonl`、
pi `sessions/<slug>/<iso>_<uuid>.jsonl`），**不写真实 harness store**；每个 writer 都通过
「writer→对应 reader 读回」自往返（B3-F3）。

`asi matrix-batch3` 输出 JSON schema `asi-batch3-matrix/v1`（`summary{harnesses,pass,partial,fail,evidence_level}` +
每 harness `{harness,evidence_level,fixture_path,ir_counts,l0,f1,f2,f3,lossy,warnings,status}`），
表内证据等级固定为 **FIXTURE**；任一 harness 的 B3-F0/F1/F2/F3 失败 → 退出码非 0。
口径：`partial` 表示该 harness 存在 fixture 文档已声明的已知有损项（如 aider 无时间戳/无工具事件、
gemini 无 cwd/标题派生、cursor 无时间戳/无 tool_result、copilot delta 合并/子代理折叠），
不是转换错误；失败/有损逐条写入报告。
**本机实测（2026-10-30 fixture 快照）**：6/6 harness 的 B3-F0/F1/F2/F3 全部通过（**fail=0**），
其中 qwen 无额外有损 → pass；其余 5 个因 fixture 固有有损标 partial；全部产物只落 staging。

## 11. 批 4：8 个 adapter（FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED）

批 4 新增 8 个 source，证据等级逐项标注，**不宣称 NATIVE**（fixtures 为 public synthetic/trimmed；
wave-2 为**本仓库构造**的 golden SQLite DB）：

| source | 证据等级 | 读取 | writer |
|---|---|---|---|
| `openclaw` | FIXTURE | pi 系树状 JSONL（session/model_change/message） | sessions JSONL（格式级） |
| `kimi` | FIXTURE | 自有事件协议：主通道 `agent.message.appended` + 备用 loop events；parity 段 `time=0` 标注合成 | sessions 事件 JSONL |
| `grok` | FIXTURE | 多文件组装 `summary.json` + `chat_history.jsonl` | 两文件同形（格式级） |
| `droid` | FIXTURE | session store JSONL v2 + CLI stream-json 两代自动探测 | 按 IR 探测写 session store / CLI stream |
| `antigravity` | FIXTURE-LOW | JSONL step 转录（`USER_INPUT`/`PLANNER_RESPONSE`/`GENERIC`，工具结果按 GENERIC 推断） | **不支持**（原生 `.pb` 无公开 schema，BLOCKED） |
| `hermes` | FIXTURE-CONSTRUCTED | JSON 逻辑投影 + 构造 `state.db`（sqlite 只读 `mode=ro`+`query_only`） | 构造 DB（列名部分未核实） |
| `devin` | FIXTURE-CONSTRUCTED | JSON 逻辑投影 + 构造 `sessions.db`/`message_nodes` | 构造 DB |
| `opencode` | FIXTURE-CONSTRUCTED | part/session JSON + 构造 `opencode.db`(session/message/part, `data` JSON) | 构造 DB |

```bash
cd tools/agent-session-import
./asi list openclaw --json          # 其余：kimi / grok / droid / antigravity / hermes / devin / opencode
./asi convert --from kimi --session <id|path> --to atif --out /tmp/asi-b4
./asi matrix-batch4 --root ../../samples/batch2/public-fixtures \
  --report tests/artifacts/interop-matrix-batch4.json \
  --doc ../../docs/interop-matrix-batch4.md --verbose
```

`matrix-batch4` 对 8 个 harness 各取 ≥1 fixture：F0 reader→IR、F1 ATIF 往返、F2 writer→reader 自往返
（`antigravity` reader-only → N/A）、F2b DSH staging→真实 `Session.fromRestore`；输出 JSON schema
`asi-batch4-matrix/v1`（每行必带 `evidence_level`）。任一 fail → 退出码非 0。
**构造 DB 说明**：wave-2 的 `.db` 由 `agent_session_import/batch4_construct.py` 在 `--out` staging 内生成，
DB 内 `meta_constructed` 表记录 `schema_source` 与 `unverified_columns`；**列名/索引部分未核实，
不得当作上游 fixture，也不代表 harness 原生可加载**。所有产物只写 staging，不写真实 store。
**本机实测**：8/8 harness 的 F0/F1/F2/F2b 全部通过（fail=0；antigravity F2=N/A，证据 FIXTURE-LOW）。

## 12. 批 5：REAL-LOCAL（Gemini/Pi）+ 11 个 CONSTRUCTED adapter（去重覆盖 ≥30）

批 5 新增 **2 个 REAL-LOCAL 行**（本机真实会话）与 **11 个 FIXTURE-CONSTRUCTED source**
（构造样本在 `samples/batch5/constructed/<harness>/`，每目录 README 标注 `CONSTRUCTED` + schema 来源 + 未核实项）。

| source | 证据等级 | 存储/读取要点 |
|---|---|---|
| `gemini`（REAL-LOCAL 行） | REAL-LOCAL | 本机 `~/.gemini/tmp/<user>/chats/session-*.jsonl`：header + `{"$set":{...}}` patch 流（reader 合并 patch；仍兼容批 3 单 JSON fixture）；Gemini CLI 未安装 → 无原生 CLI 加载，不标 NATIVE |
| `pi`（REAL-LOCAL 行） | REAL-LOCAL | 本机 `~/.pi/agent/sessions/<slug>/<ts>_<uuid>.jsonl`（96 events / 51 tool 配对，树状 id/parentId，复用 Pi reader） |
| `goose` | FIXTURE-CONSTRUCTED | 本机官方 `~/.local/share/goose/sessions/sessions.db` 的 DDL（sessions/messages；DDL 已核实、字段语义部分未核实）→ 构造 DB 读写，只读 `mode=ro` |
| `continue` | FIXTURE-CONSTRUCTED | `~/.continue/sessions/<id>.json`（history[] 整文件 JSON）+ `sessions.json` |
| `junie` | FIXTURE-CONSTRUCTED | `~/.junie/sessions/<id>/events.jsonl`（UserPromptEvent / SessionA2uxEvent）+ state.json + index.jsonl |
| `kiro` | FIXTURE-CONSTRUCTED | `~/.kiro/sessions/cli/<id>.jsonl`（每行 version/kind/data）+ `<id>.json` |
| `crush` | FIXTURE-CONSTRUCTED | SQLite sessions/messages 两表、时间戳秒级（DDL 来自 charmbracelet/crush migration） |
| `cline` / `roo` / `kilo-code` | FIXTURE-CONSTRUCTED | Cline CLI 双文件 `<id>.json` + `<id>.messages.json`；Roo/Kilo 复用同一 reader（source id 独立计去重标签） |
| `codebuff` | FIXTURE-CONSTRUCTED | `projects/<p>/chats/<id>/chat-messages.json`（variant/blocks）+ run-state.json |
| `openhands` | FIXTURE-CONSTRUCTED | LocalFileStore：`base_state.json` + `events/event_<idx>.json` |
| `vibe` | FIXTURE-CONSTRUCTED | Mistral Vibe 2.x legacy 单 `session_*.json`（新版 unified 布局未实现） |

```bash
cd tools/agent-session-import
./asi list goose --json                       # 其余 constructed：continue/junie/kiro/crush/cline/roo/kilo-code/codebuff/openhands/vibe
./asi convert --from crush --session <id|path> --to atif --out /tmp/asi-b5
./asi matrix-batch5 --report tests/artifacts/interop-matrix-batch5.json \
  --doc ../../docs/interop-matrix-batch5.md --verbose
```

`matrix-batch5`：REAL-LOCAL + CONSTRUCTED 每 source 各 ≥1 样本，跑 F0 解析 → F1 ATIF 往返 →
F2 writer→reader 自往返 → F2b DSH staging→真实 `Session.fromRestore` → 行级 `evidence_level`；
JSON schema `asi-batch5-matrix/v1`，任一 fail → 退出码非 0。**本机实测：harnesses=13，
pass=13 / fail=0（REAL-LOCAL=2、FIXTURE-CONSTRUCTED=11）**。
**覆盖**：在批 1–4 的 20 个 source 基础上新增 11 个去重标签 → **31 个不同 harness source 标签**
（≥30）；REAL-LOCAL 证据来自本机真实 Gemini/Pi 会话，其余为构造样本、**不宣称 NATIVE**。


### 12.1 批 5.1：上游 fixture 补源与证据升级（matrix-batch5 v2）

- 新 source：`codebuddy`（FIXTURE-LOW，Codeg Apache-2.0 派生样本：`item-format.jsonl`/`tool-format.jsonl`；item/function_call 两种记录形态）、`fx`（FIXTURE，`samples/batch5/agent-sessions/fx/schema4/**` session+schema3 events）、`mini-swe-agent`（FIXTURE，Harbor Apache-2.0 轨迹样例；**非真实用户会话**，注明 trajectory sample）。
- 证据升级：`kiro` → **FIXTURE-LOW**（`samples/batch5/kiro/sessions/<id>/session.jsonl` + `session.json`，derived from codeg，captured/trimmed），`opencode` → **FIXTURE**（`samples/batch5/agent-sessions/opencode/sqlite_v2/**` SQLite-v2 JSON fixture；该 fixture 消息为 redacted，功能往返仍用构造样本，报告行注明）。
- 可选行：`claude-desktop` **COLLECTED-SPARSE**（`samples/batch2/oss-add/claude-desktop__*.jsonl`，仅 2 条消息；不计入完整真实覆盖）。
- 矩阵：`asi matrix-batch5` 输出 schema **`asi-batch5-matrix/v2`**，覆盖旧 doc/artifact；**17 行：pass=16 / partial=1 / fail=0**（partial=`fx`：fixture 的 orphan tool_results 无法在 ATIF 表达 + writer 仅持久化文本事件；已按行如实标注）；REAL-LOCAL=2、FIXTURE=3（fx/mini-swe/opencode）、FIXTURE-LOW=2（codebuddy/kiro）、FIXTURE-CONSTRUCTED=10、COLLECTED-SPARSE=1。
- 覆盖：批 1–4 的 20 标签 + 批 5 的 11 标签 + 本轮 3 个新标签 = **34 个不同 harness source 标签**（另有 claude-desktop 稀疏采集行 1 行，未计入完整真实覆盖）；`opencode` 不再计为 CONSTRUCTED。
- 上游 fixtures 只读、未修改；所有写入仅 staging 与 `--out`。

## 13. 产品级命令（供 Swift 用户 App 调用：detect / preview / migrate）

本节是面向真实用户的产品后端契约；Swift App **只调用**这三个命令（以及现有 `verify`），
不需要理解 IR/reader/writer。所有命令均支持 `--json`：**stdout 只有纯 JSON**，进度/提示走 stderr；
退出码：`0`=成功、`1`=有失败项、`2`=需要确认/参数错误。错误信息为中文用户可读文案。

```bash
cd tools/agent-session-import
./asi detect --json                       # 检测本机可迁移 Harness（默认 fast，<2s）
./asi detect --json --fast                # 显式 fast（等价于默认）
./asi detect --json --deep                # 精确检测（读取会话索引/内容，较慢）
./asi preview --from dsh --session <id> --json --limit 6
./asi migrate --from codex --session <id> --to dsh --mode export --out /tmp/asi-out --json
./asi migrate --from codex --session <id> --to dsh --mode install --yes --register --json
```

### 13.1 `asi detect --json`（默认 fast；`--deep` 精确）

检测本机安装/使用中的 Harness（只读）。**默认 `--fast`：只做文件系统计数**（目录/文件名 + mtime），
不解析任何会话内容，首屏可 <0.1s 返回；`--deep` 走完整 reader（读取会话索引/内容，字段更精确但约 8-9s）。
fast 与 deep 对 claude/codex/omp/qoder/dsh 五个核心源的 `session_count` **完全一致**（已加测试），
其余源（pi/gemini/goose）也一致；`recent_at` 在 fast 下用文件 mtime 近似（可能差几百 ms）。
单项失败只写 `notes`，不影响整体。

```json
{"ok": true, "command": "detect", "generated_at": 1790000000000,
 "fast": true, "scan": "fast",
 "harnesses": [{"id": "dsh", "display_name": "DeepSeek Harness", "name": "DeepSeek Harness",
                "family": "dsh", "detected": true, "path": "/Users/me/.dsh/sessions",
                "session_count": 225, "recent_at": 1793374804892,
                "notes": "目标应用；导入后需要重启 DeepSeek Harness 才能看到新会话",
                "capabilities": {"export": true, "install": true,
                                 "install_experimental": false, "preview": true}}],
 "totals": {"harnesses_detected": 8, "total_sessions": 601}}
```

- `id`：`dsh / claude / codex / omp / qoder / pi / gemini / goose`；`display_name` 为界面用中文/产品名。
- `capabilities`：`export` 导出、`install` 写回（DSH 为正式能力；Claude/Codex/OMP/Qoder 为实验性；Pi/Gemini/Goose 只读导出）、`preview` 预览。
- `recent_at`：最近一条会话的 epoch **毫秒**；`path` 为该 Harness 的会话根目录。
- `--fast`（默认）：只做文件系统计数，不解析会话；`--deep`：完整 reader 精确检测。
- 性能实测（2026-10-31，本机）：`time asi detect --json --fast` ≈ **0.09s**（<0.1s，远低于 2s 目标）；
  `asi detect --json --deep` ≈ **8.8s**。fast/deep 计数一致：dsh 239 / codex 206 / omp 121 / qoder 44 /
  claude 3 / pi 1 / gemini 1 / goose 0（共 615；数字随本机会话变化）。
- Swift App 首屏请用默认 `asi detect --json`（fast）；详情页再按需调用 preview/session-detail。

### 13.2 `asi preview --from <src> --session <id> --json [--limit N]`

只读会话摘要，**不写任何目录**；`--limit` 控制 `last_messages` 条数（默认 6，文本≤300 字）。

```json
{"ok": true, "command": "preview", "source": "dsh", "session_id": "6fdc…",
 "title": "实现会话导入转换工具 asi", "cwd": "/Users/me/work", "model": "…",
 "provider": "…", "created_at_ms": 1790000000000, "updated_at_ms": 1790000000000,
 "counts": {"user_messages": 32, "assistant_messages": 304, "tool_calls": 356, "tool_results": 375},
 "first_user_message": "≤500 字的首条用户消息",
 "last_messages": [{"role": "assistant", "text": "≤300 字", "ts": 1790000000000}],
 "tool_names": ["read_file", "…"], "warnings": []}
```

`role` 仅 `user / assistant / tool`；会话不存在时返回 `{"ok":false,"error":"会话不存在: …"}` 且退出码 1。

### 13.3 `asi migrate --json`

一次调用完成「转换 →（可选）写入目标 → verify」，逐条结果不中断。

参数：`--from <src>`；会话选择 `--session <id|path>`（可重复）或 `--all [--all-limit N]`；
`--to <target>`（默认 `dsh`，也可 `atif` 或原生 harness 名）；`--out <dir>`（默认 `./asi-migrate`）；
`--mode export|install`（默认 **export**）；`--target-cwd`；`--register`；`--dry-run`；`--yes`；
`--dsh-home`（install 到 DSH 时的目标数据目录，默认 `DSH_HOME` 或 `~/.dsh`）。

```json
{"ok": true, "command": "migrate", "source": "codex", "to": "dsh", "mode": "install",
 "dry_run": false, "out": "/tmp/asi-out", "dsh_home": "/Users/me/.dsh", "register": true,
 "plan": [{"source_session_id": "01a1…", "to": "dsh", "mode": "install",
           "will_write_real_store": true, "target_home": "/Users/me/.dsh", "note": "…"}],
 "results": [{"source_session_id": "01a1…", "status": "ok",
              "output_dir": "/Users/me/.dsh/sessions/--Users-me--/session-…",
              "artifact": "/Users/me/.dsh/sessions/--Users-me--/session-…/session.v4.jsonl.zstd",
              "verify": {"ok": true, "checked": 1, "failed": 0},
              "lossy": [], "warnings": [], "register": {"status": "registered", "detail": "backup: …"}}],
 "summary": {"total": 1, "ok": 1, "failed": 0, "verified": 1, "lossy": 0}}
```

安全语义：
- **默认 export**：只写 `--out`，不碰任何真实 Harness 存储；`verify` 对 ATIF 重新校验、对 DSH 产物跑完整结构校验。
- **install**：无 `--yes` 直接拒绝（退出码 2，JSON `requires_yes:true`）；`--to dsh` 走现有 `import` 管道（自动备份/注册 `workspace.json`，`--register` 时）；Claude/Codex/OMP/Qoder 的 install 为**实验性**，结果里带 `experimental:true`；Pi/Gemini/Goose 只支持 export。
- **dry-run**：返回完整 `plan`（含 `will_write_real_store`），`results` 为空，**零写入**；目录都不会创建。
- 逐条失败只记入该条 `results[i].status=failed/error`，其余会话继续。
- 会话选择缺省必须显式 `--session` 或 `--all`，避免误迁移全部；`--all` 可配 `--all-limit`。

## 14. 会话详情命令（`asi session-detail`，供 Swift App 详情页/时间线/Token 统计）

```bash
cd tools/agent-session-import
./asi session-detail --from dsh --session <id> --json
./asi session-detail --from codex --session <path> --json --max-events 0 --text-limit 1000
```

- `--max-events N`：时间线最多返回 N 条（默认 **2000**；`0` = 全量）；**统计与分区基于完整会话**，仅 timeline 截断并附 warning。
- `--text-limit N`：单条文本最大字符数（默认 **400**，超出以 `…` 截断）。
- 只读：不写任何用户目录；任意已支持 source（native 5 / 采集 / fixtures / constructed / `atif`）均可用。

### 14.1 返回 JSON（字段稳定，可增不改）

```json
{
 "ok": true, "command": "session-detail", "source": "dsh", "session_id": "…",
 "meta": {"title": "…", "cwd": "/Users/me/work", "model": "…", "provider": "…",
          "created_at_ms": 0, "updated_at_ms": 0, "path": "/Users/me/.dsh/sessions/…",
          "source_label": "DeepSeek Harness", "evidence_level": "LOCAL"},
 "stats": {
   "messages": {"user": 28, "assistant": 336, "tool": 389, "reasoning": 276,
                "system": 1, "compaction": 0},
   "tool_calls": 376, "tool_results": 389, "tool_errors": 1,
   "tool_usage": [{"name": "read_file", "count": 120}, {"name": "bash", "count": 64}],
   "usage": {"input_tokens": 943283, "output_tokens": 500739,
             "cache_read_tokens": 124192512, "cache_write_tokens": 0,
             "total_tokens": 125636534, "available": true},
   "duration_ms": 82854041, "first_ts": 1790000000000, "last_ts": 1790082854041,
   "events_total": 1083, "events_shown": 1083, "truncated": false
 },
 "sections": [{"index": 1, "kind": "turn", "title": "第 1 轮", "start_index": 0,
               "end_index": 12, "ts": 1790000000000, "tool_calls": 3, "tokens": 4210}],
 "timeline": [{"index": 0, "ts": 1790000000000, "kind": "user", "role": "user",
               "text": "…", "section": 1},
              {"index": 1, "ts": 1790000001000, "kind": "thinking", "role": "assistant",
               "text": "…", "section": 1},
              {"index": 2, "ts": 1790000002000, "kind": "tool_call", "role": "assistant",
               "text": "{\"command\":\"ls\"}", "section": 1,
               "tool": {"name": "bash", "call_id": "call_1", "is_error": false},
               "usage": {"input_tokens": 12979, "output_tokens": 1238,
                         "cache_read_tokens": 256, "cache_write_tokens": 0,
                         "total_tokens": 14473}}],
 "warnings": ["该工具未提供 Token 用量数据（usage.available=false）"],
 "limits": {"max_events": 2000, "text_limit": 400}
}
```

字段说明：
- `kind`：`user / assistant / thinking / tool_call / tool_result / system / compaction`；`role`：`user / assistant / tool / system`。
- 工具事件带 `tool{name,call_id,is_error}`；**同一 `call_id` 的 tool_call/tool_result 由前端配对展示**，`is_error=true` 标红。
- `assistant` 事件在源提供 usage 时携带该条 `usage`（已归一化为 `input_tokens/output_tokens/cache_read_tokens/cache_write_tokens/total_tokens`）。
- `sections`：优先按「用户消息开始一轮」分组（`kind=turn`，标题「第 N 轮」），无显式轮次时按 >15 分钟时间窗口分段（`kind=time`，「第 N 段」）；`start_index/end_index` 指向 `timeline` 下标；附 `tool_calls/tokens` 段摘要。
- `usage.available=false` 表示该 Harness/会话**没有可用的 Token 数据**（UI 显示「该工具未提供」），同时 `warnings` 给出中文说明；源提供字段但累计为 0 也会标 false 并提示。
- `evidence_level`：`LOCAL`（本机真实会话）/ `FIXTURE` / `FIXTURE-LOW` / `FIXTURE-CONSTRUCTED` / `COLLECTED` / `ATIF`（fixtures、采集、ATIF 轨迹）；`source_label` 为界面展示名。
- `stats.events_total/events_shown/truncated` 便于 UI 显示「已显示前 N 条」；时间线截断时 `warnings` 附带中文提示。

### 14.2 实测与 Token 可达性（2026-10-31，本机真实源 + fixtures）

| source | 结果 | Token usage | 口径/说明 |
|---|---|---|---|
| `dsh` | events 1083、工具 376/389、29 分区 | ✅ total 125636534（in 943283 / out 500739 / cache_read 124192512 / cache_write 0） | reader 逐条 assistant `usage` 求和 |
| `omp` | events 1746、工具 405/405、85 分区 | ✅ total 87846333 | reader 逐条 assistant `usage` 求和（含 cacheRead） |
| `codex` | events 94、工具 36/36（errors 3）、5 分区 | ✅ total 1779381（in 1761450 / out 17931） | **`token_usage_record.usage` 逐响应增量求和**；`event_msg.token_count.info.total_token_usage` 是线程累计值（用于交叉校验/无 record 时兜底）；resume/compacted rollout 的累计值可能含更早片段，此时以本文件逐响应求和为准并附 warning |
| `claude` | 真实会话 3 个中 2 个有 token | ✅ 例：total 46606813（in 460 / out 541746 / cache_read 46064607 / cache_write 3109063） | assistant `message.usage`：`cache_creation_input_tokens→cache_write_tokens`、`cache_read_input_tokens→cache_read_tokens`；1 个 synthetic 会话 usage 全 0 → ❌ `available=false` + 「源未记录 token」（该会话为 synthetic/未启用计费） |
| `qoder` | 44 会话中部分带 token（其余无） | ◐ 部分 ✅（例 total 314207：in 162778 / out 4229 / cache_read 147200） | assistant `message.usage` 存在时提取；很多历史 Qoder 会话未记录 usage → ❌ `available=false` + warning |
| `pi` / `gemini`（fixtures） | 可读 | ✅（本机真实 pi 例 total 59 / fixture 例 19；gemini fixture 例 total 15） | reader 已映射逐条 usage |
| `copilot`（fixture） | 可读 | ❌ `available=false` | 上游 fixture 未提供 usage 字段 |
| `goose`（constructed fixture） | 2 条 user/assistant | ❌ `available=false` | 构造样本无 token |
| `oss` 采集样本 / `atif` 轨迹 | 均可读 | ◐ 依源而定（oss 例 ✅ / atif 样例 ❌） | 采集样本若带 usage 则提取；ATIF `metrics` 有则提取 |

**Token 口径（统一）**：
- `usage.total_tokens` 优先用源提供的 total（codex `total_tokens`、dsh/omp `totalTokens`）；缺失时按 `input+output+cache_read+cache_write` 求和。
- 逐事件 usage 归一化键：`input_tokens / output_tokens / cache_read_tokens / cache_write_tokens / total_tokens`；对源别名做兼容（`input_tokens`、`cached_input_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`、`cache_write_input_tokens`、`prompt_tokens` 等）。
- 无数据的源/会话：`usage.available=false` + warning「源未记录 token（…）」，**不编造 0 以外的数字**；`stats.usage.caliber` 标明来源：`codex_token_usage_record_incremental` / `codex_token_count_cumulative` / `source_event_usage` / `none`。


- 默认 `max-events=2000` 已覆盖数百条消息；超大 session（>2000 timeline 条）自动截断并附 warning，UI 可用 `--max-events 0` 取全量或分页。
- 大文件加载为**一次 IR 构建**（沿用现有 reader 能力，不写盘）；详情页首屏建议先 `preview`，打开详情再调用 `session-detail`。

## 15. 迁移 v1.4：默认直装目标会话库 + keep/move + migrate-all + restore

产品行为变化（供 Swift App 调用）：`asi migrate` **默认 `--mode install`**，直接把会话写入目标 Harness
的本地会话库（自动检测路径，无需先选输出目录）；`--mode export` 仍保留为高级「仅导出」。

### 15.1 目标 store 与支持级别

| target | store（自动检测；env 可覆盖） | install_supported | experimental | 可见方式 / 目录提示 |
|---|---|---|---|---|
| `dsh` | `${DSH_HOME:-~/.dsh}/sessions` | ✅ | ❌ | 重启 DSH 后可见；`sessions/<projectKey(cwd)>/<id>/session.v4.jsonl.zstd` |
| `claude` | `${CLAUDE_CONFIG_DIR:-~/.claude}/projects` | ✅ | ❌ | 重启 Claude Code，`claude --resume` 可见；`projects/<cwd-slug>/<uuid>.jsonl` |
| `codex` | `${CODEX_HOME:-~/.codex}` | ✅ | ✅ | `codex resume`（可能需重建线程索引）；`sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl` |
| `omp` | `${OMP_SESSION_DIR:-~/.omp/agent/sessions}` | ✅ | ❌ | 重启 OMP 可见；`sessions/<cwd-slug>/<ISO>_<uuid>.jsonl` |
| `qoder` | `${QODER_CONFIG_DIR:-~/.qoder}/projects` | ✅ | ✅ | 重启 Qoder；`projects/<cwd-slug>/<uuid>.jsonl` |
| `pi` | `${PI_HOME:-~/.pi}/agent/sessions` | ✅ | ✅ | 重启 Pi；`sessions/<cwd-slug>/<ISO>_<uuid>.jsonl` |
| `gemini` | `${GEMINI_HOME:-~/.gemini}/tmp` | ✅ | ✅ | 重启 Gemini CLI，`/resume` 可见；`tmp/<project-hash>/chats/session-<ts>-<id>.json` |
| `goose` | `${GOOSE_PATH_ROOT:-~/.local/share/goose}/sessions` | ❌（仅导出） | ❌ | SQLite 会话库；`asi migrate --mode export` |

`asi detect --json` 每行新增：`store_path`、`install_supported`、`install_experimental`、
`how_to_see`、`session_dir_hint`（App 用它们展示「将写入哪里 / 迁移后如何看到」）。
所有路径均支持 env 覆盖（`HOME`、`CLAUDE_CONFIG_DIR`、`CODEX_HOME`、`OMP_SESSION_DIR`、
`QODER_CONFIG_DIR`、`PI_HOME`、`GEMINI_HOME`、`DSH_HOME`、`GOOSE_PATH_ROOT`），测试全部使用隔离根。

### 15.2 `asi migrate`（默认 install）

```bash
./asi detect --json                          # 先拿目标 store_path / install_supported
./asi migrate --from codex --session <id> --to dsh --yes --register --journal /tmp/j.json --json
./asi migrate --from claude --session <id> --to omp --yes --session-mode move --json
./asi migrate --from codex --session <id> --to atif --mode export --out /tmp/export --json
```

- 默认 `--mode install`（目标 `install_supported=true` 时；对 `atif`/`ir`/`goose` 自动退回 export）。
  真实写入必需 `--yes`（缺失 → 退出码 2、JSON `requires_yes:true`）；`--dry-run` 零写入（不建目录、不写日志）。
- 安装目标 store 不存在时报错并提示改用 export；安装后**自动 verify**（DSH 用 `verify_file`，
  其他 target 用目标 reader 读回或文件级校验），结果含 `installed_path`、`verified`、`verify{ok,checked,failed,method}`。
- **重复**：目标已存在同 id → `status:"skipped-exists"`；`--overwrite` 先用 `<path>.asi-backup-<ts>`
  重命名备份再写（`backup_path`）。
- **`--session-mode keep|move`**（默认 keep）：`move` 仅在**安装且校验成功**后，将源会话文件**重命名**
  为 `<原名>.migrated-<ts>.bak`（同目录、不删除、可恢复）。
  - `source_path` **全链路真实**：来自 reader/`--session` ref（不只接受文件路径）；plan/results/journal 均携带
    `source_path`、`source_dir`、`source_files`（多文件源的主文件清单）。
  - 结果字段：`source_moved`、`source_move_status`（`moved` / `unsupported` / `failed`）、
    `source_backup_path`、`source_move_error`。失败/不支持会明确报错并加 warning，**绝不假报 moved**。
  - DSH 源移动其主会话文件 `session.v4.jsonl.zstd`（journal 记录所属 session 目录）；**目录/多文件型源
    暂不支持 move**（`source_move_status:"unsupported"`，源完全不动）。
  - `asi list codex` 在 `CODEX_HOME` 无 `state_5.sqlite` 时也会回退扫描 `sessions/**/rollout-*.jsonl`，
    与 detect/migrate 的发现保持一致（便携/测试环境不再显示 0 会话）。
- **`--journal <path>`**：默认
  `~/Library/Application Support/HarnessBridge/journals/migrate-<YYYYMMDD-HHMMSS-mmm>-<rand6>.json`
  （**毫秒 + 随机短后缀，绝不冲突**；可用 env `HARNESSBRIDGE_APP_SUPPORT` 覆盖 App Support 根目录，
  日志仍在 `<root>/HarnessBridge/journals/`）。日志**每完成一个会话即增量原子写入**（同目录临时文件 +
  `os.replace`），中途失败/取消仍保留已完成会话的 move/restore 映射；同秒多次迁移互不覆盖。
- **旧品牌兼容**：旧目录 `~/Library/Application Support/SessionConverter/journals/` 仅作**读取/恢复兼容**
  （`migrate-restore --journal <文件名>` 会依次在显式路径、新目录、旧目录中查找）；**新写入默认一律新目录**，
  不会自动迁移或删除旧 journal。显式 `--journal <绝对路径>` 完全不受品牌变更影响。
  日志记录每个会话的源路径、目标安装文件、备份、移出后路径与结果，供 restore 使用（JSON 顶层返回 `journal_path`）。
- 失败回滚：安装后 verify 失败会删除本次新建的目标文件、清理本次新建的**空 session 目录**并恢复覆盖前备份；
  源文件永不删除。install 写入采用**同目录 staging（`.asi-tmp-*`）+ 原子 rename**，失败清理临时文件。
- move 后若源 session 目录为空，仅在结果/日志中记录 `source_dir_kept_empty` 与 warning，**保留目录、不强制删除**。
- `migrate-all --dry-run` 的 plan 额外给出 `items[]`（含 `will_skip`）、`skip_count`/`will_skip` 汇总，
  UI 可在执行前预告重复跳过数；dry-run 仍零写入。

### 15.3 `asi migrate-all`（一键全量迁移）

```bash
./asi migrate-all --to dsh --limit 10 --yes --session-mode keep --json
./asi migrate-all --to claude --from codex,omp --since-days 30 --dry-run --json
```

- 来源默认为**其他所有已检测且存在会话的 Harness**，可用 `--from id1,id2` 过滤；`--limit` 为**每个来源**上限，
  `--since-days` 按会话更新时间过滤；目标选择同 migrate（`install_supported` 必需）。
- 返回 `plan.sources[]`（各来源会话数/选中数）+ `plan.total` + `results[]` + `summary{total,ok,failed,skipped,moved,verified}` + `journal_path`。
- 重复项默认跳过、逐条失败不中断；`--dry-run` 只返回 plan（`journal_path=null`，零写入）；真实写入必需 `--yes`。

### 15.4 `asi migrate-restore`（恢复被移出的源会话）

```bash
./asi migrate-restore --journal /path/to/migrate-<ts>.json --json
./asi migrate-restore --journal /path/to/j.json --dry-run --json
./asi migrate-restore --journal /path/to/j.json --remove-installed --json
```

- 按 journal 把 `*.migrated-*.bak` **反向 rename 回源路径**（默认保留本次安装到目标库的文件）；
  `--remove-installed` 才删除本次安装的目标文件；**源文件永不删除**（仅恢复移动）。
- `--dry-run` 零写入；返回 `results[]`（restored / already-restored / skipped-original-exists / failed）
  与 `summary{total,restored,removed_installed,failed}`。

### 15.5 安全与测试

- 真实写入必须 `--yes`；`--dry-run` 零写入；失败回滚本次新建目标文件；`move` 只 rename 可恢复、绝不删除源文件。
- 测试全部隔离：临时 `HOME` + 各 Harness env store，覆盖单会话 install 到 dsh/claude/omp（verify 通过）、
  keep 源不变、move 后 `.migrated-*.bak` 且 restore 恢复、重复 skip、overwrite 备份、migrate-all dry-run 零写入
  与真实隔离安装、restore `--remove-installed`、无 `--yes` 拒绝（退出码 2）。
- 风险/限制：Codex/Qoder/Pi/Gemini 写入为实验性（目标工具可能需要重建索引/重启才可见）；
  `move` 依赖源会话文件路径（多文件来源/Directory 型源会记为 move 失败但不删源）；
  真实用户 store 的写入前备份由 `--overwrite` 与 journal 保障，仍建议先 `--dry-run` 预览。

## 16. 批 6：外部 fixture 入库 + `asi matrix-batch6`（fixture-verified 覆盖）

批 6 把「协议覆盖 40/40」升级为**可复现的 fixture 验证覆盖**：外部/上游许可清晰的 fixture 入库
`samples/batch6/external/<harness>/`（每个目录保留上游 `SOURCE.md`），并新增矩阵命令：

```bash
cd tools/agent-session-import
./asi matrix-batch6 --json                    # 生成/覆盖 tests/artifacts/interop-matrix-batch6.json
./asi matrix-batch6 --only-harness copilot,kiro --verbose
./asi matrix-batch6 --report /tmp/batch6.json --json
```

### 16.1 证据等级（不可混淆）

| 等级 | 来源 | 计入 REAL 真实覆盖？ |
|---|---|---|
| **NATIVE / REAL-LOCAL / COLLECTED** | 本机真实 store / 真实采集 | ✅（真实覆盖仍 21/40） |
| **REAL-EXAMPLE** | Harbor RFC 0001 公开真实轨迹样例（openhands / mini-swe-agent） | ❌ 单列 |
| **FIXTURE / FIXTURE-LOW** | 上游 MIT/Apache 测试 fixture、Codeg 派生（kiro/codebuddy/antigravity） | ❌ |
| **CONSTRUCTED** | 本仓库按 schema 构造（`samples/batch5/constructed/`） | ❌ |

- 外部 fixture 可把格式证据升到 FIXTURE，但**不得冒充真实用户会话**；Crush（FSL）、Zed（GPL 混合）未复制任何上游文件。
- 批 6 新增**第四个数字**：**fixture-verified format coverage 35/40**（含 6 个 partial；用外部/本仓库
  fixture 实跑 `reader → IR → ATIF → IR` 的 canonical 标签数；CONSTRUCTED 不计；REAL-EXAMPLE 单列）。
- Continue 新增 Apache-2.0 真实样本（`samples/batch6/real/continue/session-28fdaafd.json`，REAL）：
  真实会话覆盖 21/40 → **22/40**；该样本**不得与 CONSTRUCTED 混淆**，SOURCE.md 已记录 repo/commit/license。

### 16.2 矩阵内容

- **Readers（40 canonical 标签）**：每个标签按其最佳可用 fixture（外部 `samples/batch6` / 仓库批 3-5 fixture /
  sample 目录 / 本机 store **只读**）→ reader→IR→ATIF→verify；记录 `status`（pass/partial/fail）、
  `fixture`/`fixture_kind`、`events`、`stats`、ATIF steps/errors/lossy、`warnings`。
  无 adapter 的标签（cherry-studio/opencraw/trae/windsurf/workbuddy/zcode）记 fail + 原因，不静默 pass。
- **Writers（32 个 NATIVE_TARGETS）**：以一份 ATIF 文档为输入 → 写 staging（唯一临时目录，结束清理）→
  对应 reader 读回/文件级 verify；产物只写临时目录，**不写真实用户 store**，不联网。
- 不跑 40×31 全量；只做「每源一次 reader 校验 + 每 writer 一次自往返」。artifact schema：
  `asi-batch6-matrix/v1`（`readers[] / writers[] / summary / failures / evidence_rule`）。

### 16.3 已知失败与限制（如实记录）

- **reader**：**34 pass / 6 partial / 0 fail**（batch3-recon 的 workbuddy/windsurf/trae/zcode/
  cherry-studio/claude-desktop/opencraw 7 个 reader 已接入外部 fixture；opencode 改用可解析的
  batch3-style fixture；Continue 使用真实样本 REAL）。
- **reader partial（6）**：`codex / cline / fx / kilo-code / roo / openhands`（ATIF round-trip 有损/
  compare mismatch，`partial_reason` 记录 lossy 原因，**不算 fail**）。
- **writer**：**32/32 pass，fail=0**（staging 临时目录，读回验证）。
- `iFlow` / `Zed` 为 batch3-recon 追加的 bonus source（40 canonical 分母之外，后续任务定稿时再决定是否计入）。
- 所有外部 fixture ≤200KB、无凭据；只读本机 store；matrix 生成后清理临时目录。

## 17. 参考

- `docs/formats/dsh.md`：DSH v4 格式/最小事件序列/发现与注册/严格校验清单。
- `docs/formats/codex.md`、`docs/formats/qoder.md`、`docs/formats/omp.md`：源格式逆向规格与坑。
- `research/agent-session-interchange-research.md`：ATIF 事实核查与生态。
- ATIF 规范：<https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md>
- 样本目录：`samples/dsh/`（含官方最小会话模板）、`samples/codex|qoder|omp/`（真实截断样本，含敏感内容，勿外传）。


## DSH 工作区修复（v1.7.1）

旧版本迁移到 DSH 的会话可能只写了 session 文件、没有写入 `workspace.json`，在 DSH 侧边栏显示为 **Ungrouped**。先退出 DeepSeek Harness，再运行：

```bash
./asi dsh-workspaces --dsh-home ~/.dsh --json        # dry-run，查看待注册/不匹配
./asi dsh-workspaces --dsh-home ~/.dsh --fix         # 写入（会备份 workspace.json）
```

App 中也可用 **设置 → DeepSeek Harness 工作区 → 修复工作区归属**。修复只处理 `realpath(header.cwd) == workspace.path` 的精确匹配；cwd 位于其他 workspace 子目录的会话会被报告为 `path-mismatch`，不会强行移动（DSH 的 attachSession 会过滤不匹配的 workspace）。
