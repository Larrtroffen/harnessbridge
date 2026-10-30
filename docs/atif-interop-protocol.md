# ATIF 统一中转：多 Harness Session 互转协议（v0.1）

> 状态：草案（2026-10-30），第一批实现范围 = Claude Code / Codex / OMP(oh-my-pi) / Qoder / DSH 五个 Harness 两两互转；协议本身按 30-40 个 Harness 设计。
> 配套实现：`tools/agent-session-import/`（CLI `asi`）；测试矩阵：`docs/interop-matrix.md`；Harness 目录：`docs/harness-catalog.md`。
> 统一中转格式：**ATIF v1.8**（Harbor RFC 0001，https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md）。

---

## 1. 目标与非目标

**目标**
- 任一受支持 Harness 的本地 Session（对话轨迹）→ 统一 IR → ATIF v1.8 → 统一 IR → 任一目标 Harness 的原生 Session 文件；
- 每个方向用**至少一个真实 Session** 跑通并留存证据；可自动重复（`asi matrix`）；
- 新增一个 Harness = 实现 reader + writer 两个 adapter，不需要改中枢与其它 adapter。

**非目标（本协议不承诺）**
- 不保证 100% 无损：目标 Harness 没有的概念（某些私有事件、UI 状态、后台 job 元数据）允许丢失，但必须在 `lossy` 清单中显式声明；
- 不做云端 Session 的实时同步/在线迁移（OSS 轨迹只作为测试样本来源）；
- 不替代各 Harness 自己的导出/备份能力。

---

## 2. 术语

| 术语 | 含义 |
|---|---|
| Harness | 一个 Agent 运行框架/产品（Claude Code、Codex CLI、OMP、Qoder、DSH …） |
| Session | 某 Harness 本地持久化的会话（含消息、工具调用、时间、cwd 等） |
| Trajectory | 与 Session 等价的轨迹记录；ATIF 中的载体 |
| IR | 本项目统一中间表示（`agent_session_import/ir.py`，版本 `ir_version=1`），是「读」与「写」的唯一契约 |
| ATIF | 统一中转的交换格式（v1.8，`schema_version:"ATIF-v1.8"`） |
| Reader | Harness 原生存储 → IR |
| Writer | IR → Harness 原生存储 |
| Install | 把生成的产物写入目标 Harness 的**真实**存储根（默认关闭，需显式确认） |

---

## 3. 架构：一个中枢、四个方向

```
        ┌────────── Reader ──────────┐          ┌────────── Writer ──────────┐
  Claude Code ─┐                     ├─→ IR ←───┤                     ┌─ Claude Code
  Codex      ──┼─→ IR ─→ ATIF v1.8 ─→ IR ─→ ────┼─→ IR ─→ ATIF ─→ IR ─┼─ Codex
  OMP        ──┤  (source adapter)   (pivot)     │   (target adapter)  ├─ OMP
  Qoder      ──┤                                 │                     ├─ Qoder
  DSH        ──┘                                 │                     └─ DSH
```

- **任何转换都必须经过 ATIF**（A→IR→ATIF→IR→B），不允许 A→B 直转。好处：N 种 Harness 只需 2N 个 adapter 而不是 N² 个；跨版本可复现；可以离线交换/审计。
- Reader / Writer 之间不共享代码，只共享 IR；adapter 之间禁止互相 import。
- 中枢负责：IR 校验、ATIF 编码/解码、语义比对、路径/ID 分配、幂等与安全写入、矩阵测试。

---

## 4. IR 契约（v1）

```
IR = {
  ir_version: 1,
  source: "<harness-id>",
  source_session_id: str,
  source_path: str,
  cwd: str|null, created_at_ms: int, updated_at_ms: int,
  title: str, model: str, provider: str,
  system_prompt: str|None,
  warnings: [str], lossy: [str],          # 显式有损声明
  stats: {...},
  events: [                               # 线性时间序列
    {kind:"user_message", ts, blocks:[{type:"text"|"image",...}], source_id?},
    {kind:"assistant_message", ts, blocks:[{type:"text"|"reasoning"|"tool-call",...}], model?, provider?, usage?, source_id?},
    {kind:"tool_result", ts, call_id, name?, content, is_error?},
    {kind:"system_message", ts, text, origin?},
    {kind:"compaction", ts, summary, extra?},
    {kind:"turn_abort", ts, reason},
  ]
}
```

硬性约束（写入前校验）：

1. `tool-call` block 的 `id` 在整条 Session 内唯一；每个 `id` 必须有且仅有一条 `tool_result`（源缺失时 writer 生成占位结果并记 `lossy`）。
2. 事件顺序 = 源权威顺序（Codex `ordinal` / Qoder 行序 / OMP 树路径 / Claude 行序 / DSH `seq`），不允许按时间戳重排。
3. 时间戳统一为 epoch ms（ISO/秒/毫秒在 reader 归一），允许 ±1ms 误差用于比较。
4. `cwd` 保留 provenance；写入目标时若目录不存在，由 writer 策略处理（fallback / target-cwd / 报错），不得静默改。
5. 未知内容一律进 `warnings`，不允许让 reader 抛错退出整条 Session（单条坏行跳过并计数）。

---

## 5. ATIF 编码规则

ATIF v1.8 根对象字段（必填/可选按 RFC）：

| 字段 | 我们的用法 |
|---|---|
| `schema_version` | 固定 `"ATIF-v1.8"` |
| `trajectory_id` | `<harness>:<source_session_id>`（全局唯一、可复现） |
| `session_id` | 源 Session id（v1.7 起可选，我们填） |
| `agent` | `{name:<harness-id>, version:<harness 版本或 "unknown">, model_name?}` |
| `steps[]` | 由 IR 线性映射（见下） |
| `notes` | 人类可读备注（可选） |
| `extra` | **约定扩展**（见 5.2） |
| `subagent_trajectories` | 可选；第一批 5 个 Harness 不写子代理，保留字段 |

### 5.1 IR → ATIF steps 映射

| IR 事件 | ATIF step |
|---|---|
| user_message | `source:"user"`，`message` = text blocks 拼接（多模态：`ContentPart[]`，image 放 `images/` 或降级占位） |
| assistant_message（含 reasoning + text + tool-call） | `source:"agent"`：`message` = text，`reasoning_content` = reasoning 拼接，`tool_calls[]` = `{tool_call_id,function_name,arguments(JSON object)}`，`model_name` = 本条模型 |
| tool_result | 归并入对应 agent step 的 `observation.results[] = {source_call_id, content}`；孤立结果（找不到 call）单独成 agent step 并在 `extra` 标记 `orphan_tool_result:true` |
| system_message | `source:"system"`（默认丢弃大段系统提示词；`--keep-system` 时保留） |
| compaction | 不单独成 step；写入 `extra.context_management`（`{type:"compaction", boundary:"replace"}`）并保留 summary 于 `notes` |
| turn_abort | 记入 `extra.turn_aborts[]` |

`metrics` 映射：inputTokens/outputTokens/cacheReadTokens/cacheWriteTokens/totalTokens → `metrics.{prompt_tokens,completion_tokens,cached_tokens}` + `extra.dsh_usage`。

### 5.2 `extra` 扩展约定（保证往返可逆 + 可审计）

```
extra = {
  "ir_version": 1,
  "source_harness": "codex",
  "source_session_id": "...",
  "source_path": "/Users/.../rollout-....jsonl",
  "source_cwd": "/Users/...",             # 原始 cwd（即使目标写入时被 fallback 覆盖）
  "source_model": "gpt-...", "source_provider": "...",
  "created_at_ms": 0, "updated_at_ms": 0,
  "title": "...",
  "lossy": ["qoder:assistant-block-merge", ...],
  "warnings": [...],
  "tool_name_map": {"exec_command":"bash"},   # 可选，跨 harness 工具名归一
  "compaction": [...], "turn_aborts": [...],
}
```

> 规则：**任何目标 Harness 不支持的 IR 信息都要落进 `extra`，而不是丢弃**；这是「可逆性」的来源，也是后续 30-40 个 adapter 不必回读源文件就能重建上下文的基础。

### 5.3 ATIF → IR

- `steps[].source` 决定事件 kind；连续 agent step 的 `tool_calls`+`observation.results` 还原成 assistant_message + tool_result 序列；
- `extra` 里的源信息优先恢复（cwd/title/model/lossy）；
- `subagent_trajectories` 第一批忽略，记 `warning`；
- ATIF 缺 `extra` 时按最小可用字段恢复，允许 cwd 为空（writer 必须要求 `--target-cwd`）。

---

## 6. Adapter 规范

每个 Harness 一个 adapter 包（后续可拆一个文件），实现以下接口（Python 语义，其它语言等价）：

```
class Adapter:
    harness_id: str                 # "claude" | "codex" | "omp" | "qoder" | "dsh" | ...
    capabilities: set[str]          # tool_results, reasoning, images, subagents, compaction, usage, timestamps
    def discover() -> list[SessionRef]              # 只读扫描本地 store
    def read(ref) -> IR                             # 必选
    def write(ir, out_dir, install=False) -> Artifacts  # 必选；install=False 只写暂存
    def verify(artifacts) -> VerifyReport          # 格式级自检（必须）
    def native_load_check(artifacts) -> LoadReport # 可选：目标自己的加载器/CLI 探测（L3）
```

**发现（discover）**：返回 `{harness, id, title, time_ms, cwd, path, size}`；支持 `--root` 覆盖（测试时指向样本目录）。

**写入（write）** 的强制规则：

1. **默认只写 `--out` 暂存目录**（结构 = 目标 Harness 原生布局，可整体拷入 store）；
2. `--install --yes` 才写真实 store，且必须：先备份（如 workspace.json）→ 临时文件 + 原子 replace → 幂等（已存在跳过，`--overwrite` 才覆盖）→ 失败清理本次新建项；
3. 写真实 store 前检测目标 Harness 是否在运行（进程/lock），运行中拒写或告警（各 Harness 的并发语义不同，见各自 format 文档）；
4. 文件权限 600、目录 700（与本机现有数据一致）。

**隔离测试环境**（L3 验证用，禁止污染真实目录）：
Claude Code `CLAUDE_CONFIG_DIR`；Codex `CODEX_HOME`；Qoder `QODER_CONFIG_DIR`；DSH `DSH_HOME`；OMP 以其配置/env 实测结论为准（无隔离则落「格式级验证」）。

---

## 7. 验收标准（通过 = 全部 L0-L2 + L3 尽力项）

| 级别 | 名称 | 判定 | 证据 |
|---|---|---|---|
| **L0** | 格式合法 | 产物通过目标格式的结构校验（reader 读回 / verify 无 error） | `asi verify` 报告 |
| **L1** | ATIF 自往返 | A→IR→ATIF→IR'，IR 与 IR' 语义等价（消息数/角色序/文本/tool 配对/时间戳容差） | matrix JSON |
| **L2** | 交叉互转 | A→IR→ATIF→IR'→B 原生文件，用 B 的 reader 读回 IR''；IR'' ≈ IR'（允许声明 lossy 项） | `asi matrix` 报告 |
| **L3** | 原生加载 | 目标 Harness 自己的加载器/CLI 能发现/加载产物（DSH：`Session.fromRestore`；其它：CLI 只读探测/文档结论；无法验证的记录为「格式级」） | native-load 日志 |
| **L4** | 真实会话 | 每个方向至少 1 条**非人工构造**的真实 Session；矩阵中记录 source session id | interop-matrix.md |

- 任何方向 L2 失败 → 视为该方向不通过，不允许「静默降级」；
- 有损项必须在 `lossy` 列表里出现且文档可见，否则算失败；
- 每个 Harness 版本变化（升级）后需重跑矩阵。

**当前批次（批 1，5 个 Harness）**：4 个 harness 的两两组合 = 20 个有序方向，全部要 L2 通过；L3 对 DSH 必须通过，其余尽力。

---

## 8. 扩展到 30-40 个 Harness 的流程

1. 在 `docs/harness-catalog.md` 登记：存储位置、格式、样本来源（本地/OSS/文档构造）、优先级（P0/P1/P2）。
2. 判定格式家族：
   - **Claude Code 衍生**（Qoder、Cursor CLI、Kimi CLI、Qwen Code、iFlow…）：复用 Claude adapter 的 80%，只改根路径/额外记录类型；
   - **Codex 衍生**：复用 Codex adapter；
   - **树状事件流**（OMP/pi 系）：复用 OMP adapter 的 parentId 回溯逻辑；
   - **SQLite/加密/私有二进制**：单独 reader，样本优先从 OSS 轨迹取；
   - **云端-only**：只做 ATIF 导出（有导出 API 时），不做 writer。
3. 新增 adapter 必须自带：`samples/<harness>/` 真实样本、format 文档、reader/writer、至少 1 个真实 Session 的矩阵证据。
4. 批 2 建议（依 harness-catalog 与 OSS 样本可得性）：Cursor CLI、Kimi CLI、Qwen Code、iFlow、Gemini CLI、Copilot CLI、OpenCode、Aider、Goose、Cline/Roo/Kilo（VSCode 衍生）、Trae/Kiro（IDE）。
5. 每个批次交付：`docs/interop-matrix.md` 更新 + `asi matrix --harnesses ...` 全绿 + 已知限制清单。

---

## 9. 安全与隐私

- **默认零写入用户真实数据**：所有转换默认输出到 `--out`；安装/注册必须显式 `--install --yes`/`--register`，并先备份。
- **不上传任何数据**：OSS 轨迹只读下载，测试样本只落本仓库 `samples/`（截断/脱敏；含敏感内容的样本目录在 README 标注勿外传）。
- 密钥（如 AK/SK）不进入仓库、不打印；OSS 操作只读。
- 跨机分享 ATIF 时注意：`extra.source_path`/`cwd` 含主机路径，按需脱敏（协议预留 `--redact-paths`）。

---

## 10. 当前状态（2026-10-30 03:15，Lead 独立复跑）

| Harness | reader | writer | L2 矩阵（20 方向） | L3 原生加载 | 备注 |
|---|---|---|---|---|---|
| Claude Code | ✅ | ✅ | ✅ 全通过 | ✅ 4/4（PTY `claude --bare --resume` 看到源内容） | 无 session 索引，手写 transcript 可 resume |
| Codex | ✅ | ✅ | ✅ 全通过 | 🟡 0/4（thread store 不扫描裸 rollout；见矩阵文档） | rollout JSONL 权威源 |
| OMP | ✅ | ✅ | ✅ 全通过 | ✅ 4/4（`--session-dir --mode=rpc -r`，model 映射后） | 树状事件流 |
| Qoder | ✅ | ✅ | ✅ 全通过 | 🟡 0/4（本机无 Qoder CLI） | Claude Code 衍生 |
| DSH | ✅（zstd 多帧+surface 折叠） | ✅ | ✅ 全通过 | ✅ 4/4（真实 `Session.fromRestore`） | 目标文件 `session.v4.jsonl.zstd` |

- **矩阵统计**：20 方向 fail=0；pass=12 / partial=8（partial 全部来自 L3 级别，L0-L2 皆通过）；ATIF 自往返 5/5。
- 正式矩阵与逐方向证据：`docs/interop-matrix.md`（由 `asi matrix` 自动生成，含 source session id / 命令 / 输出摘要）。
- 复跑命令：`cd tools/agent-session-import && ./asi matrix --report tests/artifacts/interop-matrix.json --doc ../../docs/interop-matrix.md`。

---

## 11. 采集轨迹层（Batch 2）：用云端采集样本把协议扩展到 30-40 个 Harness

### 11.1 动机与定位

本机只有 5 个 Harness 的**原生 store**；其余 Harness 没有安装/没有真实本地会话，无法直接做「原生 reader」。阿里云 OSS 的 `traj-session/1` 采集格式保存了真实会话在 API 网关层的完整请求/响应录制，覆盖 **19 个 harness 标签**（claude-code、codex、aider、cherry-studio、cursor、windsurf、opencode、trae、qoder、cline、kilo-code、hermes、zcode、workbuddy、claude-desktop、factory-droid、opencraw、pi、other），可作为**真实会话的测试样本**。

**定位**：`oss_traj` 是「source adapter 的一种」——采集格式 → IR，与其它 adapter 共享 IR/ATIF/writer/矩阵/验收；Harness 标签写入 `extra.source_harness`（附 `harness_confidence`），不改变其它环节。它**不等于**原生格式 adapter：采集层没有原生的 parentUuid/分支/cwd/状态行。

### 11.2 `traj-session/1` → IR 映射（按 `messages_format` 分支）

| `messages_format` | 录制形态 | IR 映射 |
|---|---|---|
| `anthropic-messages` | `messages[]` 的 content 为 block 数组（text / thinking / tool_use / tool_result） | text→text、thinking→reasoning、tool_use→tool-call、tool_result→tool_result（按 tool_use_id 配对） |
| `openai-responses` | item 序列（message / function_call / function_call_output / reasoning） | message→user/assistant text、function_call→tool-call、function_call_output→tool_result、reasoning→reasoning |
| `openai-chat` | messages[]（role: user/assistant/tool/tool_calls） | tool_calls→tool-call、role=tool→tool_result；assistant content 可为纯字符串 |

公共字段：`system_prompt[]`（默认丢弃，`--keep-system` 保留为 system_message）、`tools[]`、`usage{input_tokens,output_tokens,cache_*}`、`created_at/updated_at`（ISO→epoch ms）、`model`、`harness/harness_version`、`meta_data.source{bucket,region,key_prefix,supplier,harness_confidence}`。

### 11.3 Batch 2 验收标准（与 §7 的 L0-L4 对齐）

| 级别 | 判定 | 证据 |
|---|---|---|
| **B2-L0** 采集解析 | `schema_version=traj-session/1`；`harness/model/messages_format` 合法；`len(messages) ≥ 8`（测试用真实样本阈值） | per-harness 行 |
| **B2-L1** ATIF 往返 | IR→ATIF v1.8→IR 语义等价（消息/角色/工具配对） | matrix JSON |
| **B2-L2** DSH 原生加载 | 写 DSH staging → **真实** `Session.fromRestore` 加载成功 → DSH reader 读回与 IR 语义比对 | 每 harness ≥1 通过 |
| **B2-L3** 目标 writer 格式级 | 写 5 个已实现 target（claude/codex/omp/qoder/dsh）→ target reader 读回语义等价；原生 CLI 验证对采集样本不适用（记录 N/A） | matrix JSON |
| **B2-L4** 真实性 | 每个 harness 标签至少 1 个**真实采集会话**（OSS bucket/key/session_id 可追溯，非人工构造） | 报告附带来源 |

- 任一 harness 的 B2-L2 失败 → 该 harness 不通过；失败/有损如实记录，不虚报。
- 采集格式的已知信息损失：分支/parentUuid、原生 cwd、状态行、图片实体、部分工具原始输出；这些在 ATIF `extra.lossy` 中声明。

### 11.4 覆盖率目标与证据等级

| 层 | Harness 数 | 证据等级 | 说明 |
|---|---|---|---|
| 原生（批 1） | 5 | **NATIVE**（L0-L3） | Claude Code / Codex / OMP / Qoder / DSH |
| 采集（批 2） | 15-19 | **COLLECTED**（B2-L0~L2 必过、L3 格式级） | 内部 OSS 轨迹采集（bucket 名已隐去） |
| 公开 fixture 层（批 3 起） | 待定 | **FIXTURE**（格式级） | sessionport/atifact/Agent Sessions 的合成/截断样本，不作为真实会话 |
| 纯云端（P2） | 待定 | 仅 ATIF 导出 | Cody/Augment/Amp/Warp/Replit/Jules 等 |

> 30-40 个 Harness 的最终目标是「每个 Harness 至少 1 个真实 Session + 至少格式级通过；能拿到原生样本的升到 NATIVE」；证据等级必须在报告中显式标注，`COLLECTED` 不得冒充 `NATIVE`。

### 11.5 当前状态（2026-10-30 03:30，Lead 独立复跑）

| 项目 | 状态 |
|---|---|
| `oss_traj` reader（`traj-session/1`，三种 messages_format） | ✅ 已实现（`readers/oss_traj.py`；anthropic-messages / openai-responses / openai-chat 三分支；重复采集行折叠 + callId 去重 + step 末尾占位结果） |
| `asi list oss` / `asi convert --from oss` | ✅ 已实现（`--json` 支持；`--to atif/ir/dsh/claude/codex/omp/qoder`） |
| 批 2 矩阵 | ✅ `asi matrix-batch2`（`docs/interop-matrix-batch2.md` 自动生成）：**18 harness 标签、21 个真实采集文件，pass=17 / partial=1 / fail=0，DSH 真实加载 L3=18/18**；唯一 partial = claude-code（codex 原生化时 assistant 消息分组被重新组织，block 级内容一致，记 `message_grouping_normalized` 已知有损） |
| messages_format 覆盖 | anthropic-messages 16 / openai-responses 1 / openai-chat 1（三格式全覆盖） |
| `samples/batch2/oss/` 真实采集样本 | ✅ 21 会话 / 54.3MB，全部 `traj-session/1` 且 `len(messages)≥8`（11–2,610 条）；见 `docs/batch2-samples.md` |
| 公开 native fixtures | ✅ `samples/batch2/public-fixtures/` 82 文件 / 1.4MB（sessionport / atifact / agent-sessions，MIT/Apache，附 SOURCE.md；标注为合成/截断，不得冒充真实会话） |

**覆盖率（有真实 Session 与测试证据的 Harness 标签）**：批 1 原生 **5** + 批 2 采集 **18** = **23 个**；另有批 3 公开 fixtures 待接入（见 `docs/formats/batch3-fixtures.md`，批 3 侦察中）。

**复跑命令**：

```bash
cd tools/agent-session-import
./asi matrix-batch2 --root ../../samples/batch2/oss \
  --report tests/artifacts/interop-matrix-batch2.json \
  --doc ../../docs/interop-matrix-batch2.md
```

**限制**：采集层无原生 cwd/parentUuid/分支/状态行/图片实体；`--to` 原生目标需 `--target-cwd`；harness 标签来自采集管线检测（`harness_confidence` 记录）；`claude-desktop`（桶内样本仅 1-2 条消息）与 `gateway`（messages=0）暂无合格真实样本，已在 `docs/batch2-samples.md` 记录缺口。

---

## 12. 批 3：原生格式层（Fixture 证据级）与 30-40 覆盖账本

### 12.1 定位

批 1 覆盖 5 个**本机安装** Harness 的原生 store（NATIVE 级）；批 2 用 OSS 采集轨迹覆盖 18 个 Harness 标签（COLLECTED 级）。批 3 的目标是：用公开仓库的**原生格式 fixtures**，为更多 Harness 实现 reader/writer adapter——但 fixtures 是合成/截断样本，因此证据等级最高只到 **FIXTURE**，不能宣称「真实会话通过」或「原生加载通过」。

### 12.2 批 3 目标与方案来源

逐 harness 的 schema 字段表、Reader 映射规则、Writer 最小可行、测试计划见 `docs/formats/batch3-fixtures.md`（batch3-recon，实测解析 82 个 fixtures）。第一批实施 6 个：

| Harness | fixture 主证据 | Reader 难度 | Writer | 证据等级 |
|---|---|---|---|---|
| GitHub Copilot CLI | atifact events JSONL + agent-sessions stage0/copilot | ★★ | session-state 事件 JSONL | FIXTURE |
| Gemini CLI | agent-sessions stage0/gemini 单 JSON | ★★ | `chats/session-*.json` | FIXTURE |
| Aider | sessionport/aider 原生 Markdown history | ★ | Markdown history | FIXTURE |
| Cursor CLI | agent-sessions stage0/cursor transcript JSONL（legacy + turn_ended 两代） | ★★☆ | transcript JSONL | FIXTURE |
| Qwen Code | agent-sessions stage0/qwen JSONL envelope（Claude Code 衍生） | ★★☆ | `chats/<uuid>.jsonl` | FIXTURE |
| Pi（低成本加项） | agent-sessions stage0/pi 树状 JSONL（OMP 同族） | ★★ | 树状 JSONL | FIXTURE |

本轮**不做**：OpenCode（需 SQLite 证据）、Cline（messages_path 文件缺失）、Goose（仅简化样本）、Windsurf / Roo / Kilo（无有效 schema fixture）→ 归入批 4 或需补样本。

### 12.3 批 3 验收标准（Definition of Done）

| 级别 | 判定 | 证据 |
|---|---|---|
| **B3-F0** fixture 解析 | `asi list <src>` 能列出 fixture 会话；记录条数/类型数与 recon 文档断言一致 | per-harness 行 |
| **B3-F1** ATIF 往返 | fixture→IR→ATIF→IR 语义等价 | matrix JSON |
| **B3-F2** 目标格式自往返 | IR→writer 原生格式→**同一 reader** 读回，与 IR 语义比对通过 | matrix JSON |
| **B3-F2b** DSH 原生加载 | 写 DSH staging → 真实 `Session.fromRestore` 加载成功（Synthetic 会话也算真实加载器验证） | native-load 日志 |
| **B3-F3** 证据等级 | 报告必须标 **FIXTURE**；原生 CLI 加载（B3-F4）本轮 **N/A**，不得声称 NATIVE | 报告列 |

- 每个 Harness ≥1 个 fixture 会话（真实上游 fixtures，或明确标注的 FIXTURE-CONSTRUCTED）；
- 任一 Harness 的 B3-F1/F2 失败 → 不通过；有损项必须声明。

### 12.4 覆盖账本（证据等级分层，不得混算）

| 层 | Harness 数 | 证据等级 | 备注 |
|---|---|---|---|
| 批 1 原生（本机安装） | 5 | **NATIVE**（L0-L3） | Claude Code / Codex / OMP / Qoder / DSH |
| 批 2 采集（OSS 真实会话） | 18 | **COLLECTED**（B2-L0~L2，DSH L3） | 与批 1 有重叠标签（claude/codex/qoder/omp/pi…） |
| 批 3 原生 fixtures | 6 | **FIXTURE**（B3-F0~F2b） | Copilot CLI / Gemini CLI / Aider / Cursor CLI / Qwen Code / Pi |
| 批 4 计划（fixtures 可得） | 8-12 | FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED | Droid / Grok / Hermes / Kimi / OpenClaw / Antigravity / Devin / OpenCode(SQLite) / Cline / Goose… |
| 纯云端（P2） | 若干 | 仅 ATIF 导出 | Cody / Augment / Amp / Warp / Replit / Jules |

**真实会话（REAL）覆盖 = 批 1 的 5 + 批 2 独有的采集标签**；批 3/4 的 FIXTURE 级只计入「协议覆盖」，**不计入真实会话覆盖**。最终报告必须同时给「协议覆盖 Harness 数」与「真实会话覆盖 Harness 数」两个数字，禁止把 FIXTURE 当 REAL。

### 12.5 当前状态（2026-10-30 03:45，Lead 独立复跑）

| 项目 | 状态 |
|---|---|
| 6 个 reader（copilot/gemini/aider/cursor/qwen/pi） | ✅ 已实现（`readers/native_batch3.py` + source 包装；容错/`--keep-system`/时间戳归一/`extra.evidence_level=FIXTURE`） |
| 6 个 writer（格式级） | ✅ 已实现（最小原生布局；writer→对应 reader 自往返 B3-F3 全过；默认只写 `--out` staging） |
| `asi matrix-batch3` | ✅ 已实现：**harnesses=6，pass=1 / partial=5 / fail=0**，`evidence_level=FIXTURE`；B3-F0/F1/F2/F3 全通过（B3-F2 为 DSH 真实 `Session.fromRestore`） |
| 有损项 | copilot（delta 合并/子代理）、gemini（thoughts 合并/标题派生）、aider（无时间戳/无工具事件）、cursor（无时间戳/缺 tool_result/turn_abort 丢弃）、pi（compaction 丢弃）；qwen 无额外有损 → pass。全部为 fixture 文档已声明的固有有损，已写入矩阵报告 |
| 测试 | **42/42 OK**（33 原有 + 9 新增：6 reader fixture 精确断言、writer 往返、matrix smoke） |
| 文档 | `docs/interop-matrix-batch3.md`（自动生成）、`docs/usage.md §10`、JSON 报告 `tests/artifacts/interop-matrix-batch3.json` |

**复跑命令**：

```bash
cd tools/agent-session-import
./asi matrix-batch3 --root ../../samples/batch2/public-fixtures \
  --report tests/artifacts/interop-matrix-batch3.json \
  --doc ../../docs/interop-matrix-batch3.md
```

**批 3 边界（再次强调）**：fixtures 均为 public synthetic/trimmed，**不是真实会话**；本轮不声明 NATIVE、不声明原生 CLI 恢复成功。批 4 侦察（`docs/formats/batch4-fixtures.md`）将覆盖剩余 fixtures 候选（Droid/Grok/Hermes/Kimi/OpenClaw/Antigravity/Devin/OpenCode(SQLite)/Cline/Goose…），目标把协议覆盖推向 30-40。

---

## 13. 批 4：补充原生层（Fixtures/构造样本）与覆盖账本

### 13.1 目标

批 3 已覆盖 6 个原生 Harness（FIXTURE 级）。批 4 依据 `docs/formats/batch4-fixtures.md`（722 行实测盘点），再补 8 个 Harness，使**协议覆盖**（分层账本）从约 29 提升到约 37，去重真实 Harness 标签约 22→27（新增 Kimi/Grok/OpenClaw/Antigravity/Devin；Droid/Hermes/OpenCode 为既有 COLLECTED 标签补原生格式）。**REAL 覆盖不增加**：批 4 全部只到 FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED。

### 13.2 批 4 目标与证据等级

| 波 | Harness | fixture 依据 | 证据等级 | 能力边界 |
|---|---|---|---|---|
| 1 | OpenClaw | `stage0/openclaw/small.jsonl`（pi 系树状） | FIXTURE | reader+writer；复用 Pi/OMP |
| 1 | Kimi Code | `stage0/kimi/small.jsonl`（自有事件协议，非 Claude 衍生） | FIXTURE | reader+writer；fixture 含合成 parity 段（time=0），时间戳不可用 |
| 1 | Grok Build | `stage0/grok/chat_history.jsonl` + `summary.json` | FIXTURE | reader+writer（两文件组装） |
| 1 | Factory Droid | `stage0/droid/{stream_json_small,session_store_schema_drift}.jsonl` | FIXTURE | reader 双格式；writer 对 session store v2 |
| 1 | Antigravity | `stage0/antigravity/*.jsonl`（JSONL step 转录） | **FIXTURE-LOW** | **reader-only**；原生 `.pb` BLOCKED，无 writer |
| 2 | Hermes | `stage0/hermes/small.json`（逻辑投影） | **FIXTURE-CONSTRUCTED** | SQLite golden DB 构造；列名部分未核实 |
| 2 | Devin | `stage0/devin/small.json`（逻辑投影） | **FIXTURE-CONSTRUCTED** | 同上 |
| 2 | OpenCode | part 行 + 简化 session | **FIXTURE-CONSTRUCTED** | 同上 |

**BLOCKED（本轮不做）**：Cline（messages 文件缺失）、FX（缺 events.jsonl）、Junie/Vibe/Kilo/Roo/Goose/Windsurf（仅简化样本/无 fixture）、Cursor IDE/Copilot DB（无 SQLite 样本）、Antigravity 原生 protobuf。HAR（wire 层录制）不占 native 名额，仅可作 wire 源 adapter 路线。

### 13.3 批 4 验收标准（B4）

| 级别 | 判定 |
|---|---|
| **B4-F0** fixture 解析 | `asi list <src>` 列出会话；条数/事件类/消息数/工具配对与 `batch4-fixtures.md` 实测断言一致 |
| **B4-F1** ATIF 往返 | fixture→IR→ATIF→IR 语义等价 |
| **B4-F2** 目标格式自往返 | IR→writer 原生格式→同 reader 读回语义一致；**Antigravity 无 writer → N/A**；构造 DB 项须证明「构造→读回」一致且标注 constructed |
| **B4-F2b** DSH 真实加载 | 写 DSH staging → 真实 `Session.fromRestore` 加载成功 |
| **B4-F3** 证据等级 | 报告逐行标注 FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED；原生 CLI 加载（B4-F4）N/A；禁止宣称 NATIVE |

- 构造样本（golden DB）必须在文件名/extra/文档中标注 `constructed`，列名未核实处写明；
- 任一 Harness 的 F1/F2（非 N/A 项）失败 → 不通过；有损项声明。

### 13.4 覆盖账本

维护 `docs/coverage-ledger.md`（由 coverage-report 工具从 3+1 个 matrix artifact JSON 汇总）：分层汇总 + 逐 Harness 主表 + 「X/40」进度条 + 去重规则。**两个数字必须分开报**：

- **协议覆盖**（有 adapter + 至少 FIXTURE 证据的 Harness 数）；
- **真实会话覆盖**（NATIVE 或 COLLECTED，有真实用户会话 + 转换证据的 Harness 数）；
- FIXTURE / FIXTURE-LOW / CONSTRUCTED 一律不计入真实会话覆盖。

### 13.5 当前状态（2026-10-30 03:50，Lead 独立复跑）

| 项目 | 状态 |
|---|---|
| 批 4 8 个 adapter（波1+波2） | ✅ 已实现：openclaw / kimi / grok / droid（FIXTURE）、antigravity（FIXTURE-LOW，reader-only，F2=N/A）、hermes / devin / opencode（FIXTURE-CONSTRUCTED，构造 golden SQLite DB，`meta_constructed` 记录未核实列） |
| `asi matrix-batch4` | ✅ **harnesses=8，pass=8 / partial=0 / fail=0**；F0/F1/F2/F2b 全通过；证据等级逐行标注（3 constructed + 1 reader-only）；有损声明：kimi synthetic-time、grok row-ts-derived、antigravity inferred-pairing/other、hermes/devin json-projection-not-native、opencode orphan-part |
| 测试 | **50/50 OK**（42 原有 + 8 批 4 用例，含构造 DB 只读拒绝测试） |
| 文档 | `docs/interop-matrix-batch4.md`（自动生成）、`docs/usage.md §11`、JSON 报告 `tests/artifacts/interop-matrix-batch4.json`（schema `asi-batch4-matrix/v1`，每行 evidence_level 必填） |
| 覆盖账本 | ✅ **v0.2 定稿** `docs/coverage-ledger.md` + `tools/coverage-report.py`；Lead 已确认批 4：协议覆盖（去重）**27/40**、分层累计 **37/40**、真实会话覆盖 **19/40**；`--check` 通过 |

**复跑命令**：

```bash
cd tools/agent-session-import
./asi matrix-batch4 --root ../../samples/batch2/public-fixtures \
  --report tests/artifacts/interop-matrix-batch4.json \
  --doc ../../docs/interop-matrix-batch4.md
```

**批 4 边界**：fixtures 均为 public synthetic/trimmed（非真实会话）；wave2 为构造 golden DB（列名/索引部分未核实，不得当上游 fixture，不代表原生可加载）；antigravity 原生 `.pb` 仍 BLOCKED；**REAL 覆盖不增加**。

---

## 14. 批 5：补齐 30-40 覆盖（新 fixtures / 官方文档 / 本地真实样本）

### 14.1 目标

批 4 后账本：**协议覆盖（去重）27/40、分层 37/40、真实会话 19/40**。批 5 的任务是：

1. **新 Harness 入协议**：从公开 fixtures + 官方文档 + 构造样本三路补齐，把去重协议覆盖推向 **≥30（目标 33-35）**；
2. **提升既有 Harness 的证据等级/真实度**：把能拿到**本机真实 session** 的从 FIXTURE/COLLECTED 升级（例：Gemini CLI 本机有真实 `~/.gemini/tmp/<user>/chats/session-*.jsonl`；Pi 本机有真实 `~/.pi/agent/sessions/...`；Goose 本机 `~/.local/share/goose/sessions/sessions.db` 有官方 SQLite schema 但无会话 → 构造）；
3. **补齐批 2 缺口**：claude-desktop / gateway 的采集样本（OSS 再挖）。

### 14.2 证据等级扩展（批 5 新增/明确）

| 等级 | 定义 | 计入协议覆盖 | 计入真实会话覆盖 |
|---|---|---|---|
| **NATIVE** | 本机真实 store + 原生加载验证 | ✅ | ✅ |
| **REAL-LOCAL**（批 5 新增） | 本机真实 session 文件/DB 存在，reader 转换 +（若 CLI 不可得）格式级/DSH 加载验证；不声称原生 CLI 恢复 | ✅ | ✅（真实会话） |
| **COLLECTED** | OSS 真实采集会话 | ✅ | ✅ |
| **FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED** | 公开合成样本 / 部分证据 / 自构 golden 样本 | ✅（标注低） | ❌ |
| **DOC-ONLY** | 官方文档/源码确认 schema，但无任何样本可测 | ❌（直到有样本） | ❌ |

REAL-LOCAL 的判定要求：样本必须是**用户本机 harness 生成的 session 文件**（非仓库 fixture、非人工构造），且能由 reader 还原出完整消息序列；若目标 CLI 不存在，L3 记 N/A，不冒充 NATIVE。

### 14.3 批 5 验收标准（B5）

| 级别 | 判定 |
|---|---|
| **B5-F0** 解析 | 每个新 source 至少 1 个样本（fixtures/本机真实/构造），`asi list <src>` 与实测计数一致 |
| **B5-F1** ATIF 往返 | sample→IR→ATIF→IR 语义等价 |
| **B5-F2** 目标格式自往返 | IR→writer→reader 比对（reader-only 目标 N/A） |
| **B5-F2b** DSH 真实加载 | 写 DSH staging → 真实 `Session.fromRestore` 成功 |
| **B5-F3** 证据等级 | 每行标 NATIVE / REAL-LOCAL / FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED；DOC-ONLY 不进矩阵 |
| **B5-F4** 账本 | `docs/coverage-ledger.md` 刷新：协议覆盖 ≥30、真实会话覆盖如实增加；`--check` 通过 |

### 14.4 批 5 候选与三路来源（实施中）

| 路 | Harness 候选 | 来源 |
|---|---|---|
| 本机真实 | **Gemini CLI**（`~/.gemini/tmp/*/chats/session-*.jsonl`，patch 流格式）、**Pi**（`~/.pi/agent/sessions/**`，树状 JSONL） | 本机，REAL-LOCAL（能拿 CLI 则 NATIVE） |
| 官方 schema + 构造 | **Goose**（`~/.local/share/goose/sessions/sessions.db`，SQLite schema v17：sessions/messages），可能 Continue/Zed/Crush | 官方仓库 DDL + 自构 golden DB（FIXTURE-CONSTRUCTED） |
| 公开 fixtures | OpenHands、Kiro CLI、CodeBuddy、Junie、Mistral Vibe、Roo/Kilo、Cline（补 messages）、FX（补 events）等（以 `docs/formats/batch5-fixtures.md` 实测为准） | GitHub MIT/Apache fixtures（待采） |
| 文档核实 | 上述候选的路径/格式/恢复机制（`docs/formats/batch5-docs.md`） | 官方文档/源码（DOC 级） |

### 14.5 当前状态（2026-10-30 04:15，批 5 + 5.1 验收完成）

| 项目 | 状态 |
|---|---|
| 本机 REAL-LOCAL 样本 | ✅ Gemini CLI（`~/.gemini/tmp/*/chats/session-*.jsonl`，header+`$set` patch 流）、Pi（`~/.pi/agent/sessions/**`，96 events/51 tool 配对）→ 证据等级 REAL-LOCAL |
| 新 Harness（批 5） | ✅ 11 个 CONSTRUCTED：goose（本机官方 SQLite DDL 构造）、continue、junie、kiro、crush、cline/roo/kilo-code、codebuff、openhands、vibe |
| 新 Harness（批 5.1，上游 fixtures） | ✅ codebuddy（FIXTURE-LOW，Codeg 派生）、fx（FIXTURE，agent-sessions schema4，唯一 partial：orphan tool_results 有损已声明）、mini-swe-agent（FIXTURE，Harbor 样例，非真实会话）；kiro 升 FIXTURE-LOW、opencode 升 FIXTURE；claude-desktop COLLECTED-SPARSE 行 |
| `asi matrix-batch5` | ✅ schema `asi-batch5-matrix/v2`：**17 行，pass=16 / partial=1 / fail=0**；F0/F1/F2/F2b 全通过；证据分布 REAL-LOCAL 2 / FIXTURE 3 / FIXTURE-LOW 2 / FIXTURE-CONSTRUCTED 10 / COLLECTED-SPARSE 1 |
| 测试 | **55/55 OK** |
| 覆盖账本 | ✅ **v0.3 定稿** `docs/coverage-ledger.md`：**协议覆盖（去重）40/40 ✅ 达成 30-40 目标**；真实会话覆盖 **21/40**；分层累计 54/40 超上限→停用（仅批次对账）；`--check` 通过 |
| 剩余缺口（批 6 可选） | Zed（SQLite 线程库，需源码构造/真实 DB）、Warp/Replit（纯云端仅导出）、iFlow（本地 store 未核实）、Antigravity 原生 protobuf writer（reader 已可）、CodeBuddy 上游真实 fixture、Windsurf/Kilo 真实 store |

**复跑命令**：

```bash
cd tools/agent-session-import
./asi matrix-batch5 --report tests/artifacts/interop-matrix-batch5.json \
  --doc ../../docs/interop-matrix-batch5.md --verbose
python3 tools/coverage-report.py --check        # 账本是否最新
python3 tools/coverage-report.py --json         # 三个口径数字
```

**验收结论（对应本协议总目标）**：五原生 Harness 两两互转 + 20 方向矩阵（批 1）、OSS 采集多 Harness 样本（批 2）、30-40 Harness 协议覆盖（批 3-5.1，账本 40/40）均已交付并留证；**证据等级分层如实标注**（真实会话 21/40，其余为上游 fixture/构造样本，不冒充 NATIVE/真实）。
