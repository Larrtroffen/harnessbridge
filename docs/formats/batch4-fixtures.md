# 批 4 侦察：剩余 Harness fixtures 的可用性与 adapter 方案

> 版本：v0.1（2026-10-30）｜执行：batch3-recon（Team 成员，shared task-18）
> 上游：[`docs/atif-interop-protocol.md`](../atif-interop-protocol.md) §12（批 3 原生格式层与 **30-40 覆盖账本**）；上一轮：[`docs/formats/batch3-fixtures.md`](batch3-fixtures.md)（S1-S4 分类、10 目标判定、缺口 G1-G8）
> 素材：[`samples/batch2/public-fixtures/`](../../samples/batch2/public-fixtures/)（82 文件 / 1,187,119 B；来源/commit/MIT 见 [`SOURCE.md`](../../samples/batch2/public-fixtures/SOURCE.md)）
> 关联：[`docs/harness-catalog.md`](../harness-catalog.md)（49 候选/P0-P2/家族）、`tools/agent-session-import/`（批 3 已实现 copilot/gemini/aider/cursor/qwen/pi，见 `readers/native_batch3.py`、`writers/native_batch3.py`）
> **任务边界**：本文件只做「fixtures 实测盘点 + 可用性判定 + Reader/Writer 方案 + 批 4 批次建议」，**不写转换代码、不改 fixtures、不动其它成员文件**。

> **证据等级（沿用批 3 定义，本文件新增 FIXTURE-LOW）**
> | 代号 | 含义 |
> |---|---|
> | **FIXTURE** | 上游 fixture 的字段语义可支撑该 harness 原生 schema 的 Reader/Writer 实现；仅格式级验证 |
> | **FIXTURE-LOW** | 只有部分证据（如仅 metadata/仅规范化转录/缺事件体）：只能实现部分能力或 reader-only |
> | **FIXTURE-CONSTRUCTED** | 上游 fixture 缺该格式样本，须按本文 schema 表**自构 golden sample**（必须标注 constructed） |
> | **BLOCKED** | 无 schema 级证据（或原生格式为 protobuf/无样本 SQLite），本轮不实施 |
> | **NATIVE / REAL** | 目标 harness 真实安装加载 / 真实用户会话；**批 4 本轮全部不承诺、不宣称** |

---

## 0. 结论摘要（TL;DR）

### 0.1 批 3 未覆盖 fixtures 的判定总表

| # | Harness / 源 | fixture（批 3 未覆盖部分） | 实测 | 类型 | 证据判定 | 建议 |
|---|---|---|---|---|---|---|
| 1 | **OpenClaw** | `agent-sessions/stage0/openclaw/small.jsonl`（1,556 B） | 5 行/3 类事件/3 消息/工具 1+1 | **S1** | **FIXTURE** | 批 4 核心（★，Pi/OMP 族复用） |
| 2 | **Kimi Code** | `agent-sessions/stage0/kimi/small.jsonl`（20,817 B） | 50 行/22 类事件/含合成 parity 段 | **S1** | **FIXTURE** | 批 4 核心（★★） |
| 3 | **Grok Build** | `agent-sessions/stage0/grok/{chat_history.jsonl,summary.json}`（1,774 B） | chat 5 行 + summary 1 文件（2 文件组装） | **S1** | **FIXTURE** | 批 4 核心（★★） |
| 4 | **Factory Droid** | `agent-sessions/stage0/droid/{stream_json_small,session_store_schema_drift}.jsonl`（1,012 B） | 两代：CLI stream 4 行 / session store 3 行 | **S1×2** | **FIXTURE**（路径未核实） | 批 4 核心（★★☆） |
| 5 | **Google Antigravity** | `agent-sessions/stage0/antigravity/{desktop_small,cli_schema_drift}.jsonl`（2,670 B） | 6+3 行 JSONL step 转录 | **S3 规范化转录** | **FIXTURE-LOW**（reader-only；原生 `.pb` BLOCKED） | 批 4 条件项（★★★） |
| 6 | **Hermes** | `agent-sessions/stage0/hermes/small.json`（472 B） | JSON 逻辑投影 2 消息 | **S3 逻辑投影** | **FIXTURE-CONSTRUCTED**（原生 SQLite 需 golden DB） | 批 4 核心·波 2（★★★） |
| 7 | **Devin CLI** | `agent-sessions/stage0/devin/small.json`（1,880 B） | 作者自述逻辑投影 4 nodes | **S3 逻辑投影** | **FIXTURE-CONSTRUCTED**（原生 SQLite 需 golden DB） | 批 4 核心·波 2（★★★） |
| 8 | **OpenCode** | `agent-sessions/stage0/opencode/00{1,2}.json` + `sessionport/.../abc.json` | 仅 part 行（2）+ 简化 session | **S1-part / S2** | **FIXTURE-CONSTRUCTED**（SQLite/多文件需 golden） | 批 4 核心·波 2（★★★） |
| 9 | **Cline** | `agent-sessions/stage0/cline/*.json`（2,592 B） | 仅 metadata（2 个），messages 文件缺失 | **S1-metadata** | **FIXTURE-CONSTRUCTED**（messages 构造） | 扩展（★★★） |
| 10 | **fx**（vercel-labs） | `agent-sessions/stage0/fx/{session,display,checkpoint}.json`（1,293 B） | metadata+display+**坏** checkpoint，缺 events | **S3 伴生** | **FIXTURE-LOW**（metadata 级） | 扩展/补采（★★☆） |
| 11 | **atifact HAR（wire 级）** | `atifact/test-fixtures/*.har`（6 个/14,314 B） | 8 entries；Anthropic×3/OpenAI chat×2/responses×1 | **S4 wire** | **FIXTURE-LOW**（wire 源 adapter，非 session） | 单列 wire 层，不计 native |
| 12 | **vally（合成 provider 流）** | `atifact/test-fixtures/vally-simple.json`（3,310 B） | 10 事件（合成） | **S4** | 不作证据 | 不采用 |
| 13 | Junie / Mistral Vibe / Kilo / Roo / Goose / Windsurf | sessionport 对应 fixture（各 115-138 B，共 5 个；Roo 无 fixture） | 全部为**同一 S2 简化形状**（2 行 `{role,content}`） | **S2** | **BLOCKED**（Kilo/Roo/Goose/Windsurf/Junie/Vibe 无 schema 证据） | 不实施，补采 |
| 14 | Cursor IDE / Copilot DB / Droid native / Antigravity `.pb` | 无 fixture | — | — | **BLOCKED** | 需真实 DB/逆向 |

### 0.2 六条关键判断

1. **批 4 真正能拿到的原生 schema 证据只有 5 个半**：OpenClaw、Kimi Code、Grok Build、Factory Droid（两代格式）、Antigravity（仅 JSONL 转录）；Hermes/Devin/OpenCode 是「逻辑投影或 part 级」→ 原生 SQLite 必须走 **FIXTURE-CONSTRUCTED golden DB**。
2. **建议批 4 核心 8 个 = OpenClaw、Kimi Code、Grok Build、Factory Droid、Antigravity（reader-only）、Hermes、Devin、OpenCode**（与协议 §12.4 的批 4 计划一致）。分两波：**波 1（JSON/JSONL/多文件）5 个**，**波 2（SQLite golden DB）3 个**。
3. **SQLite 类必须先做「golden DB 构造套件」**：public-fixtures 里**没有任何 `.db/.sqlite` 文件**（批 3 已 `find` 验证并沿用）。OpenCode/Hermes/Devin（+可选 Copilot DB、Cursor IDE）的列名/索引无法从 fixtures 核实 → 构造时必须标 `FIXTURE-CONSTRUCTED`，列名不可核实处显式写「未核实」，**不得把构造样本当上游 fixture**。
4. **家族复用明确**：**OpenClaw ↔ Pi ↔ OMP**（pi 系树状 JSONL，代码复用最高，OpenClaw 是该家族第 3 个成员）；**Droid stream-json ↔ atifact Claude/Codex/Copilot CLI stream**（CLI 事件流解析模式）；**Hermes/Devin ↔ OpenAI-chat 消息形状 + SQLite 只读层**；**Kimi 不是 Claude 衍生**（fixture 是自有事件协议 `protocol_version=1.4`，纠正 catalog 的「疑似 Claude Code 系」猜测）；**Antigravity 用 Gemini 模型但格式独立**，原生 protobuf 仍需逆向。
5. **覆盖率两种口径必须分开报**：协议覆盖（分层账本）**29 → 37（+8）**；去重后真实 Harness 标签 **22 → 27（+5 全新：Kimi/Grok/OpenClaw/Antigravity/Devin）**——Droid=Factory Droid、Hermes、OpenCode 是给**已 COLLECTED 标签补原生格式**，不新增标签。若把扩展 Cline/FX/Goose 做满 → 分层 **40**（= 协议上限）/去重 **29**。
6. **HAR/vally 不是 session store**：HAR 是 provider HTTP/SSE 录制，只能作「wire 源 adapter」（类似批 2 的 `oss_traj`），不占 30-40 native 名额；但它能补批 2 的 `claude-desktop`/`gateway` 缺口（wire 级真实录制），建议单列技术路线。

### 0.3 与批 3 文档的关系（继承/修正/新增）

| 项 | 批 3 结论 | 批 4 更新 |
|---|---|---|
| S1-S4 分类 | 定义于 batch3-fixtures.md §1.3 | 沿用；本文件新增 FIXTURE-LOW |
| sessionport 8 个简化 fixture | 「不能当 schema 证据」 | 维持 BLOCKED（Junie/Vibe/Kilo/Goose/Windsurf 仅此一份，Roo 无 fixture） |
| OpenCode | 「半阻塞：part 级 + SQLite 无证据」 | 升级为**批 4 波 2**，给出 3 表 golden DB 构造方案 |
| Cline | 「metadata 级可用，messages 缺失」 | 升级为扩展项，给出 messages.json 构造模板与断言 |
| Devin | 「逻辑投影，不能当物理 schema」 | 维持；给出 JSON 投影 Reader + golden DB 两条路径 |
| Hermes | 批 3 未展开 | 本文件判定为逻辑投影 → CONSTRUCTED |
| Antigravity | 批 3 列为批 4「P2/protobuf 需逆向」 | 本文件确认：**原生 .pb 仍 BLOCKED**；但 JSONL 转录可做 reader-only（FIXTURE-LOW） |
| FX | 批 3 未展开 | 只有 metadata/display + 坏 checkpoint，**缺 events.jsonl** → metadata 级 LOW |

---

## 1. 盘点：批 3 未覆盖的 fixtures 全清单（实测）

> 方法：`python3` 逐文件 `json.loads`/逐行解析（空行跳过），统计行数、事件类型、消息数、工具事件；SQLite 无样本（`find . -name '*.db' -o -name '*.sqlite*'` 为空，故无只读打开动作可做）。
> 文件数与大小均来自 `os.path.getsize` 实测。

### 1.1 逐文件表

| 分组 | 文件（相对 `public-fixtures/`） | B | 实测 | S 类 | 批 4 判定 |
|---|---|---|---|---|---|
| **agent-sessions 剩余** | `stage0/antigravity/desktop_small.jsonl` | 2,152 | 6 行：USER_INPUT×1/PLANNER_RESPONSE×3/GENERIC×2；tool_calls 2 | S3 | FIXTURE-LOW |
| | `stage0/antigravity/cli_schema_drift.jsonl` | 518 | 3 行：USER_INPUT/PLANNER_RESPONSE/BROWSER_NAVIGATE；`promptVariant`/`telemetry` 漂移 | S3 | FIXTURE-LOW |
| | `stage0/devin/small.json` | 1,880 | session 10 字段 + 4 nodes（system/user/assistant/tool） | S3 | FIXTURE-CONSTRUCTED |
| | `stage0/droid/stream_json_small.jsonl` | 561 | 4 记录（+1 空行）：message/tool_call/tool_result/completion | S4 CLI | FIXTURE（CLI 侧） |
| | `stage0/droid/session_store_schema_drift.jsonl` | 451 | 3 行：session_start(v2)/message×2 | S1 | FIXTURE |
| | `stage0/fx/session.json` | 920 | schema 3 / event_log_v1 metadata（`history_len:5`、`event_log_bytes:1` 占位） | S3 | FIXTURE-LOW |
| | `stage0/fx/display.json` | 196 | schema 1：title/preview/workspace | S3 | FIXTURE-LOW |
| | `stage0/fx/checkpoint.json` | 177 | **坏 JSON**（`Invalid control character` line 8 col 45） | S3 负样本 | 仅容错测试 |
| | `stage0/grok/chat_history.jsonl` | 872 | 5 行：system/user/assistant(工具1)/tool_result/assistant | S1 | FIXTURE |
| | `stage0/grok/summary.json` | 902 | 20 字段伴生索引（id/cwd/时间/title/model/session_kind） | S1 | FIXTURE |
| | `stage0/hermes/small.json` | 472 | 8 键；2 消息（user/assistant） | S3 | FIXTURE-CONSTRUCTED |
| | `stage0/kimi/small.jsonl` | 20,817 | **50 行 / 22 类事件**；3 prompt / 4 append_message / 13 llm.request / 3 agent.message.appended / 7 loop events | S1 | FIXTURE |
| | `stage0/openclaw/small.jsonl` | 1,556 | 5 行：session/model_change/message×3（含 toolResult） | S1 | FIXTURE |
| | `stage0/opencode/001.json`、`002.json` | 79+88 | 2 个 part：`{id,type:text,text,time.start}` | S1-part | FIXTURE-CONSTRUCTED |
| | `stage0/cline/cline-desktop-continued.json`、`session_1792607722905_fixt1.json` | 1,066+1,526 | metadata v1；`messages_path` 指向文件不存在 | S1-meta | FIXTURE-CONSTRUCTED |
| | `stage0/copilot/small.jsonl` | 38,322 | （批 3 已覆盖）33 类事件 | S1 | 批 3 |
| **sessionport 剩余** | `openclaw/sessions/o1.jsonl`（125）、`junie/sessions/j1.jsonl`（133）、`vibe/sessions/v1.jsonl`（130）、`kilo/sessions/k1.jsonl`（132）、`goose/sessions/g1.jsonl`（138）、`windsurf/sessions/s1.jsonl`（115）、`cline/tasks/t1.jsonl`（117）、`copilot/sessions/c1.jsonl`（136） | 1,026 合计 | 8 个**同形** 2 行（`role/content` 或 `type/content`） | **S2** | BLOCKED（不可作 schema 证据） |
| | `opencode/storage/session/abc.json` | 255 | 简化 `{id,parts}`（parts 顺序非标准） | S2 | 仅骨架 |
| **legacy** | `legacy/Cursor/{test-session,subagent-session}.jsonl` | 1,378 | （批 3 已覆盖：旧代 transcript） | S1 | 批 3 |
| | `legacy/codex_052_raw.jsonl`、`legacy/session_simple.jsonl` | 1,189 | Codex 旧版事件 / 归一 2 行 | S1 / S4 | 批 1/不采用 |
| **atifact 剩余** | `har-anthropic.har`（1,612，1 entry）、`har-anthropic-thinking.har`（1,754，1）、`har-anthropic-multiturn.har`（6,119，3）、`har-openai-chat.har`（1,204，1）、`har-openai-chat-tools.har`（2,025，1）、`har-openai-responses.har`（1,600，1） | 14,314 | HAR 1.2；请求 JSON + 响应 **SSE**（`event:`/`data:`） | S4 wire | FIXTURE-LOW（wire 层） |
| | `vally-simple.json` | 3,310 | 10 个合成事件 + metrics | S4 | 不作证据 |
| | `copilot-cli-*.jsonl`×6 / `claude-code-*.jsonl`×5 / `codex-cli-*.jsonl`×2 | 33,023 | 批 1/批 3 已覆盖 | S1 | 批 1/批 3 |

### 1.2 关键事实更正/新增发现（相对批 3 文档与 SOURCE.md）

| # | 发现 | 影响 |
|---|---|---|
| N1 | **Kimi fixture 内含显式「合成 parity」段**：line 37-49 的 `time=0`（line 37-44 为 parity 段：`turn.prompt→agent.turn.started→think→step.end→agent.message.appended×3→agent.turn.ended`；line 45-49 为合成 context 回放）、文本 `SYNTHETIC KIMI PARITY PROMPT/REASONING/ASSISTANT TEXT`，是作者**故意补齐**的消息+工具语义覆盖；line 36 的 `prompt.completed` 是裁剪占位（time=0），line 0-35 为真实事件日志的截断（时间戳正常） | 可作为工具配对/角色序断言来源，但必须标注「含合成 parity 段、时间戳不可用」 |
| N2 | **Droid 是两套格式**：`stream_json_small.jsonl` = CLI `--output-format stream-json` 输出（S4 CLI），`session_store_schema_drift.jsonl` = **session store JSONL（version 2，S1）**；后者才是 writer 目标 | 一个 reader 双输入；writer 对 session store |
| N3 | **Antigravity fixture 不是原生 `.pb`**：JSONL step 转录（`step_index/source/type/status/created_at/content/tool_calls`），是规范化表示；catalog 的 `conversations/<uuid>.pb` 无公开 schema | 只能做 JSONL reader（FIXTURE-LOW）；native `.pb` BLOCKED |
| N4 | **FX fixture 缺 `events.jsonl`**：只有 `session.json`（schema 3，`event_log_bytes:1` 占位）、`display.json`、以及**坏** `checkpoint.json` | reader 仅 metadata 级；事件格式无样本 → 转换能力 BLOCKED（见 B4-G7） |
| N5 | **Hermes/Devin 是逻辑投影**：Devin 的 `_fixture` 字段自述「SQLite 逻辑投影，live DB 由 agent_watch 归一」；Hermes 的 `small.json` 是 SQLite `state.db` 的 JSON 投影（catalog 说 Hermes 原生是 SQLite） | 原生 schema 需 golden DB（FIXTURE-CONSTRUCTED） |
| N6 | **sessionport 剩余 8 个仍是同一 S2 形状**（含 openclaw/cline/copilot 的 S2 版本）；对应 harness 只有 OpenClaw/Cline 在 agent-sessions 有 S1 证据，**Junie/Vibe/Kilo/Goose/Windsurf 仍无 schema** | 维持 BLOCKED |
| N7 | **HAR 响应体是 SSE 流**（Anthropic `message_start/content_block_delta`；OpenAI chat `data: {...}`；OpenAI responses `event: response.*`），请求体是 JSON（多轮 HAR 的 `messages[]` 为**累积**形态） | wire adapter 需 SSE 解析 + 累积请求去重 |
| N8 | **Droid `stream_json_small.jsonl` 含 1 个空行**（第 2 行），逐行解析需跳过空行；Kimi/Antigravity/Grok/OpenClaw 文件尾部仅普通换行 | 行级容错（`common.iter_jsonl` 已实现 skip-blank） |

### 1.3 能力矩阵（批 4 候选 × IR 还原要素）

| Harness | user/assistant | tool_call/result | 时间戳 | cwd | 标题 | 模型/usage | 结论 |
|---|---|---|---|---|---|---|---|
| OpenClaw | ✅ text blocks | ✅（toolCall/toolResult） | ✅ ISO | ✅ session.cwd | ❌（可派生） | ✅ message.usage | **FIXTURE** |
| Kimi Code | ✅ user/assistant/tool | ✅ toolCalls + tool 消息 | ✅（前置段）/ ❌（parity 段=0） | ✅ `profile.bind.environmentDisclosure` | ❌（派生首条 user） | ✅ meta.usage/model | **FIXTURE** |
| Grok Build | ✅ | ✅（tool_calls + tool_result） | ✅ summary/缺行内 ts | ✅ summary.info.cwd | ✅ generated_title | ✅ current_model_id | **FIXTURE** |
| Droid | ✅ | ✅（两代） | ✅ | ✅ session_start.cwd | ✅ title | ❌ usage（无样本） | **FIXTURE** |
| Antigravity | ✅ | 🟡 工具结果需按「上一条 tool_call + 后续 GENERIC」推断 | ✅ created_at | ❌ | ❌ | ✅ tokens（PLANNER_RESPONSE） | FIXTURE-LOW |
| Hermes | ✅ | ❌（投影无工具） | ✅ | ✅ | ❌ | ✅ model | FIXTURE-CONSTRUCTED |
| Devin | ✅（system/user/assistant/tool） | ✅ tool_calls + tool 节点 | ✅ epoch 秒 | ✅ working_directory | ✅ title | 🟡 metadata.num_tokens=null | FIXTURE-CONSTRUCTED |
| OpenCode | 🟡 part 级 | 🟡（真实 part tool 形态据 C，fixture 无） | ✅ part.time.start | ❌（session 级缺） | ❌ | ❌ | FIXTURE-CONSTRUCTED |

---

## 2. 逐 harness 方案

> 每节：原生存储事实 → fixture 实测（字段表 + ≤300 字符截断示例 + 精确计数）→ Reader 映射规则 → Writer 最小可行 → 测试计划 → 有损项 → 判定。
> 示例均为 fixture 原文截断/节选（`…` 表示截断），不是真实用户会话。

### B4-01 OpenClaw（FIXTURE｜难度 ★）

**原生存储事实**（证据：harness-catalog **B** Codeg 路径表 `~/.openclaw/agents/` JSONL + **D** fixture；**C** 未覆盖该 harness）。fixture 是 **pi 系树状事件流**：`session` 根 → `model_change` → `message`（`id/parentId` 树链）。

**fixture**：`agent-sessions/stage0/openclaw/small.jsonl`（1,556 B，5 行，`json.loads` 全部通过；S1）。

| 行 type | 字段 | 实测 | IR 用途 |
|---|---|---|---|
| `session` | `id,version,timestamp,cwd` | `openclaw-stage0-small` / `3` / `2026-02-24T09:00:00Z` / `/tmp/repo` | 会话元数据 |
| `model_change` | `id,parentId,modelId,provider,timestamp` | `mc1` ← session；`openclaw-small`/`openclaw-model` | model/provider |
| `message` | `id,parentId,timestamp,message` | `m1`/`m2`/`m3` 树链 | 消息 |
| └ `message` | `role` | `user` / `assistant` / `toolResult` | 角色分派 |
| └ `message` | `content[]` | `[{type:"text",text}]` / `[{type:"toolCall",id,name,arguments,input}]` / toolResult 块 | text/tool-call |
| └ `message` | `toolCallId,toolName,isError`（toolResult 行） | `tc1`/`shell_exec`/`false` | tool_result 配对 |
| └ `message` | `model,usage{input,output,cacheRead,cacheWrite,totalTokens,cost}` | `usage: input 12/output 3/cacheRead 2/totalTokens 17` | usage/metrics |
| └ `message` | `stopReason,sourceChannel,api,provider,__openclaw{...}` | `toolUse`/`fixture`/`fixture-api` | extra/lossy |

**截断示例（assistant 行，≤300 字符）**

```json
{"type":"message","id":"m2","parentId":"m1","timestamp":"2026-02-24T09:00:03Z","message":{"role":"assistant","content":[{"type":"text","text":"Running ls now."},{"type":"toolCall","id":"tc1","name":"shell_exec","arguments":{"command":"ls"}}],"model":"openclaw-small"}}
```

**Reader 映射规则**

1. 读全部行 → 建 `id → entry` 索引；从 `type=="session"` 根出发沿 `parentId` 树 walker（复用批 1 OMP / 批 3 Pi 的树状逻辑）；文件顺序作为同层序，树分叉进 `extra.branch_points`。
2. `message.role`：`user`→`user_message`；`assistant`→`assistant_message`（`content[].type=="text"`→text、`"toolCall"`→tool-call，`arguments` 为对象，`input` 是重复字段可忽略）；`toolResult`→`tool_result`（call_id=`toolCallId`，content 取 `content[].text/content`，`isError`→is_error）。
3. 时间：`timestamp` ISO→epoch ms；行内 `message.timestamp`（epoch ms）优先。
4. cwd=`session.cwd`；model=`model_change.modelId`（fallback 行内 `message.model`）；provider 同；usage 按 `ir.normalize_usage`（input/output/cacheRead/cacheWrite/totalTokens）。
5. `__openclaw.mirrorIdentity/mirrorOrigin/senderIsOwner`、`cost`、`stopReason`、`sourceChannel`、`api` → `extra`/`lossy`（不进 IR 主体）。
6. `version` 非 3 → warning `openclaw:schema-version-?`，仍尽力解析。

**Writer 最小可行**：`<out>/sessions/<sid>.jsonl`（或 `<out>/<slug>/sessions/<sid>.jsonl`，路径以 **B** 的 `~/.openclaw/agents/` 为根、具体层级**未核实**）：首行 `session`（id/version:3/timestamp/cwd）→ `model_change` → 每个 IR 事件一条 `message`（user/assistant/toolResult；tool-call 写 `content[].type="toolCall"`）。无索引证据 → 格式级自往返（B4-F3）；默认 `--install` 关闭。

**测试计划（期望值来自实测）**

| 用例 | 断言 | 证据 |
|---|---|---|
| OCW-F1 | 5 行全部解析；1 个 session 根 + 1 model_change + **3 条 message**（user/assistant/toolResult）；cwd=`/tmp/repo`、version=3、model=`openclaw-small` | FIXTURE（B4-F1/F2） |
| OCW-F2 | tool-call=1（`shell_exec`, args `{command:"ls"}`）且 tool_result=1 配对；结果 content=`"main.swift\nResources\n"`；usage input=12/output=3/cacheRead=2/totalTokens=17 | FIXTURE |
| OCW-F3（写） | IR→JSONL→同 reader 读回：3 消息、角色序 user→assistant→tool、工具配对、cwd/model 一致；树 `parentId` 链完整 | FIXTURE（B4-F3） |

**已知有损项**：`__openclaw` 镜像身份、cost/stopReason/sourceChannel 丢弃；树分叉线性化；标题派生；`usage` 的缓存拆分进 extra。

---

### B4-02 Kimi Code（FIXTURE｜难度 ★★）

**原生存储事实**（证据：harness-catalog **C** `~/.kimi/{sessions/<id>/,user-history/<id>.jsonl,kimi.json}`、**B** Kimi Code `~/.kimi-code/sessions/*.jsonl`；format 细节 catalog 标「未核实」）。fixture 是**事件日志 JSONL**（`protocol_version:1.4`），包含截断真实段 + **合成 parity 段**（N1）。

**fixture**：`agent-sessions/stage0/kimi/small.jsonl`（20,817 B，**50 行 / 22 类事件**；S1）。

| type | 关键字段 | 实测 | IR 用途 |
|---|---|---|---|
| `metadata` | `protocol_version,created_at` | `1.4` / `1784950509920` | 版本/created_at |
| `config.update` | `profileName,systemPrompt,modelAlias,thinkingEffort` | `agent` / `…Kimi Code CLI…` / `moonshot-ai/kimi-k2.7-code` / `on` | model/system（默认丢） |
| `tools.set_active_tools` | `names[]` | 6 个（Read/Write/Edit/Grep/Glob/Bash） | extra |
| `turn.prompt` | `input[{type:text,text}],origin.kind,agentId,promptId,turnId` | 3 条：`hi`/`hi`/`SYNTHETIC KIMI PARITY PROMPT` | user 消息来源之一 |
| `context.append_message` | `message{role,content[{type:text/think}],toolCalls[],origin}` | 4 条（user） | 备用消息源 |
| `context.append_loop_event` | `event{type:step.begin/content.part/step.end/tool.call/tool.result,…}` | 7 条（2 step.begin + 2 content.part + step.end + tool.call + tool.result） | 备用 block/工具源 |
| `llm.request` | `provider,model,modelAlias,messageCount,turnStep` | 13 条 | 仅统计/extra |
| `agent.message.appended` | `message.message{role,content,toolCalls[]} + meta{createdAt,messageId,origin,model{model,provider},usage{inputCacheCreation,inputCacheRead,inputOther,output},finish}` | **3 条**（user/assistant/tool，parity 段） | **主消息源** |
| `agent.turn.started/ended` | `turnId,kind,outcome` | 1/1（completed） | 轮次边界 |
| `profile.bind` | `environmentDisclosure.cwd,agentsMdPaths,activeToolNames` | cwd=`/private/tmp/as-agent-lab/kimi/project` | **cwd 来源** |
| `token_counting.measured/turn_recorded` | `tokens,length,turnId` | 23231（turn 0） | usage 参考（累计，非精确） |
| `turn.steer/turn.cancel/permission.set_mode/plugin.session_start/runtime.set_binding/prompt.completed/turn.ended/changeNotifier.snapshot/llm.tools_snapshot` | 各 | 见 fixture | warnings/extra/lossy |

**截断示例（parity 段 assistant 行，节选，≤300 字符）**

```json
{"type":"agent.message.appended","message":{"message":{"role":"assistant","content":[{"type":"think","think":"SYNTHETIC REASONING"},{"type":"text","text":"SYNTHETIC ASSISTANT TEXT"}],"toolCalls":[{"id":"synthetic-tool","name":"Bash","arguments":"{\"command\":\"pwd\"}"}]}}}
```

**Reader 映射规则**

1. **主通道**：按行序处理 `agent.message.appended` → `message.message.role`：`user`→user_message（content text）、`assistant`→assistant_message（`think`→reasoning、`text`→text、`toolCalls[]`→tool-call，`arguments` 为 **JSON 字符串**需 `json.loads`）、`tool`→tool_result（`toolCallId`）。
2. **备用通道**（事件日志被截断、无 agent.message.appended 时）：`turn.prompt.input` → user；`context.append_loop_event.event`：`content.part.part.type=="think"`→reasoning、`type=="text"`→text、`tool.call`→tool-call、`tool.result`→tool_result。两通道**同时存在时优先主通道**，备用仅补缺；切换记 `warning kimi:fallback-channel`。
3. 时间：事件行 `time`（epoch ms）→ ts；parity 段 `time=0` → 用前一条有效时间并 warning `kimi:synthetic-time`。
4. cwd：`profile.bind.environmentDisclosure.cwd`（最先出现者）；缺失→`cwd=None`+warning。model：`config.update.modelAlias`/`agent.message.appended.meta.model`；provider 同。
5. usage：主通道 `meta.usage{inputCacheCreation,inputCacheRead,inputOther,output}`→`normalize_usage`；`token_counting.turn_recorded.tokens` 仅作 extra（累计值，不可当单轮）。
6. title：首条 user 文本前 80 字符；subagent 列表（`changeNotifier.snapshot.subagentNames`）→ extra（不展开）。
7. `llm.request`/`llm.tools_snapshot`/hash 字段全部跳过（不进 IR）；未知 type → warning。

**Writer 最小可行**：`<out>/sessions/<sid>.jsonl`（Kimi Code **B** 路径形状；Kimi CLI `sessions/<id>/wire.jsonl` 变体**未核实**，用 `--layout kimicode|kimicli` 参数化）：行序 = `metadata`（protocol_version:1.4、created_at）→ `config.update`（modelAlias/systemPrompt）→ `tools.set_active_tools` → 每个 IR 事件：user→`turn.prompt`+`agent.message.appended(user)`；assistant→`agent.message.appended(assistant)`（content think+text，toolCalls arguments 写字符串）；tool_result→`agent.message.appended(tool)`；轮末 `agent.turn.ended{outcome:"completed"}`。格式级自往返（B4-F3）；不写 `user-history`/`kimi.json`（schema 未核实）。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| KIM-F1 | 50 行全部解析；**22 类事件**；计数：turn.prompt=3、context.append_message=4、llm.request=13、context.append_loop_event=7、agent.message.appended=3、agent.turn.started/ended=1/1 | FIXTURE |
| KIM-F2 | parity 段：user 文本=`SYNTHETIC KIMI PARITY PROMPT`；assistant reasoning=`SYNTHETIC REASONING`、text=`SYNTHETIC ASSISTANT TEXT`；tool-call=1（Bash/pwd，args JSON 字符串解析为 `{command:"pwd"}`）、tool_result=1（`/tmp/synthetic-kimi`）配对；model=`kimi-k2.7-code`/provider=`kimi`；usage inputOther=1/output=1 | FIXTURE |
| KIM-F3 | cwd 取 `profile.bind.environmentDisclosure.cwd`=`/private/tmp/as-agent-lab/kimi/project`；`turn.steer/turn.cancel/permission.set_mode/plugin.*/runtime.*/prompt.completed/changeNotifier.snapshot` → warnings；`protocol_version=1.4` 进 extra | FIXTURE |
| KIM-F4（写） | IR→JSONL→读回：3 消息、角色序、工具配对、model/cwd 一致；arguments 字符串→对象往返一致 | FIXTURE（B4-F3） |

**已知有损项**：parity 段为合成内容、`time=0` 不可作真实时间；`llm.request`/tools_snapshot/hash、`turn.steer/cancel`、`plugin/runtime` 事件丢弃；usage 仅有 meta 级；token_counting 为累计；子代理不展开；原生路径/文件名未核实。

---

### B4-03 Grok Build（FIXTURE｜难度 ★★）

**原生存储事实**（证据：harness-catalog **C** 完整目录/schema：`~/.grok/sessions/<url-encoded-cwd>/<uuid>/` 含 `summary.json`/`events.jsonl`/`chat_history.jsonl`/`updates.jsonl`/`plan.json`/`subagents/`/`compaction/` + `session_search.sqlite`；**D** fixture；P0）。fixture = 该目录中的 **2 个文件**（summary + chat_history），S1。

**fixture**：`agent-sessions/stage0/grok/summary.json`（902 B，20 字段）+ `chat_history.jsonl`（872 B，5 行）。

| 文件 | 字段 | 实测 | IR 用途 |
|---|---|---|---|
| summary.json | `info{id,cwd}` | id=`019f6851-…`；cwd=`/tmp/as-agent-lab/grok/project` | session id / cwd |
| | `session_summary` / `generated_title` | `Count the Python files under the project root` | title |
| | `created_at`/`updated_at`/`last_active_at` | `2026-01-01T00:00:10/20Z` | created/updated |
| | `num_messages`/`num_chat_messages` | `4` / `2` | 审计断言 |
| | `current_model_id`/`chat_format_version`/`session_kind` | `grok-4.5` / `1` / `subagent` | model / 版本 / extra（子代理） |
| | `git_root_dir/git_remotes/head_commit/head_branch/grok_home/agent_name/sandbox_profile/reasoning_effort` | 见 fixture | extra |
| chat_history.jsonl | `type` | `system`/`user`/`assistant`/`tool_result` | 分派 |
| | user：`content[{type:"text",text}],prompt_index` | 1 条 | user_message |
| | assistant：`content(str),tool_calls[{id,name,arguments(str)}],model_id,model_fingerprint,reasoning_effort` | 2 条（第 1 条含 1 工具） | assistant_message + tool-call |
| | tool_result：`tool_call_id,content` | 1 条（`call-…-0`） | tool_result |

**截断示例（summary 片段 + assistant 行，各 ≤300 字符）**

```json
{"info":{"id":"019f6851-…-03f3eee38756","cwd":"/tmp/as-agent-lab/grok/project"},"created_at":"2026-01-01T00:00:10.000000Z","num_messages":4,"num_chat_messages":2,"session_kind":"subagent","generated_title":"Count the Python files under the project root","current_model_id":"grok-4.5"}
```
```json
{"type":"assistant","content":"I'll count them.","tool_calls":[{"id":"call-…-0","name":"run_terminal_cmd","arguments":"{\"command\":\"find . -name '*.py' | wc -l\"}"}],"model_id":"grok-4.5","reasoning_effort":"high"}
```

**Reader 映射规则**

1. **多文件组装**：`summary.json` 提供会话元数据；`chat_history.jsonl` 提供消息；两者按目录配对（`summary.info.id` = 目录名/会话 id）。缺 summary → warning 并只读 chat_history。
2. system 行 → `system_message`（默认丢弃/`--keep-system`）；user → user_message；assistant → assistant_message（`content` 字符串→text；`tool_calls[].arguments` 为 **JSON 字符串**→`json.loads` 失败则 `{"_raw":…}`+warning；`model_id`→本条 model）；tool_result → tool_result（call_id=`tool_call_id`）。
3. 时间：行内多数无 timestamp → 用 summary `created_at`+行序递增（记 `lossy:grok:row-ts-derived`）；有 `last_active_at` 作 updated_at。
4. cwd=`info.cwd` 或 `git_root_dir`；title=`generated_title`∪`session_summary`；`session_kind=="subagent"`→`extra.session_kind`+warning；`num_messages` 与实际消息数不一致 → warning。
5. `prompt_index`/`model_fingerprint`/`reasoning_effort`/`git_remotes`/`sandbox_profile` → extra。

**Writer 最小可行**：`<out>/sessions/<url-encoded-cwd>/<sid>/` 下写 `summary.json`（info.id/cwd、session_summary、created_at/updated_at、num_messages、generated_title、current_model_id、chat_format_version:1、session_kind、git 字段可空） + `chat_history.jsonl`（system/user/assistant/tool_result 行，`arguments` 写 JSON 字符串）。不写 `events.jsonl`/`updates.jsonl`/`plan.json`/`subagents/`（无样本）→ 格式级自往返；`session_search.sqlite` 不写（无样本，可能影响搜索/resume，未核实）。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| GROK-F1 | summary 20 字段解析；cwd/title/model/created/updated；`num_messages=4`、`num_chat_messages=2` 与解析结果核对（4 条非 system 消息） | FIXTURE |
| GROK-F2 | chat_history 5 行：system=1/user=1/assistant=2/tool_result=1；tool-call=1（`run_terminal_cmd`，args 字符串解析出 command）与 tool_result=1 配对（id 一致）；model=`grok-4.5`；`session_kind=subagent`→extra | FIXTURE |
| GROK-F3（写） | IR→2 文件→读回：消息数/角色序/文本/工具配对/标题/cwd 一致；`num_messages` 回填正确 | FIXTURE（B4-F3） |

**已知有损项**：行内时间缺失（派生）；`events.jsonl`/`updates.jsonl`/`plan.json`/`subagents`/`compaction` 不迁移；`session_search.sqlite` 索引不写（resume/搜索未知）；`prompt_index`/fingerprint 丢弃；多文件需目录命名规则（url-encoded-cwd，**未核实**编码形式）。

---

### B4-04 Factory Droid（FIXTURE｜难度 ★★☆，路径未核实）

**原生存储事实**（证据：harness-catalog **E** Agent Sessions「legacy-only，不再做格式校验」，行 29；路径 catalog 标**未核实**）。fixture 提供**两代格式**：CLI stream-json 输出（S4）与 session store JSONL v2（S1）。

**fixture A（session store）** `agent-sessions/stage0/droid/session_store_schema_drift.jsonl`（451 B，3 行）：

| 行 | 字段 | 实测 | IR 用途 |
|---|---|---|---|
| `session_start` | `id,title,owner,version,cwd` | `droid_drift` / `Stage0 Droid Drift` / `alexm` / `2` / `/tmp` | 会话元数据/标题/cwd/版本 |
| `message` | `id,timestamp,message{role,content[]}` | `m1` user（content 含 `<system-reminder>\nBe concise.\n</system-reminder>\n\nDo the thing`）、`m2` assistant `Ok` | 消息 |

**fixture B（CLI stream-json）** `agent-sessions/stage0/droid/stream_json_small.jsonl`（561 B，4 记录 + 1 空行）：

| 行 | 字段 | 实测 | IR 用途 |
|---|---|---|---|
| `message` | `session_id,timestamp,role,text` | `sid_stage0_small` / user / `Do thing` | user_message |
| `tool_call` | `session_id,timestamp,toolCallId,toolName,parameters` | `c1` / `Shell` / `{command:"echo hi"}` | tool-call |
| `tool_result` | `…,toolCallId,value{stdout,exitCode}` | `c1` / stdout `hi\n` / exit 0 | tool_result |
| `completion` | `…,finalText,id` | `Done` / `end` | final assistant_message |

**截断示例（各 ≤300 字符）**

```json
{"type":"session_start","id":"droid_drift","title":"Stage0 Droid Drift","owner":"alexm","version":2,"cwd":"/tmp"}
```
```json
{"type":"tool_result","session_id":"sid_stage0_small","timestamp":"2025-12-26T00:00:02.000Z","toolCallId":"c1","value":{"stdout":"hi\n","exitCode":0}}
```

**Reader 映射规则**

1. **格式探测**：首行 `type=="session_start"` → session store 模式；首行 `type in {message,tool_call,tool_result,completion}` 且有 `session_id` → CLI stream 模式；两者都兼容时优先 session store。
2. session store：`session_start`→会话元数据（id/title/cwd/version 进 extra）；`message{role,content}`→user/assistant 消息；content 中 `<system-reminder>…</system-reminder>` **默认剥离**进 extra 并 warning `droid:embedded-system-reminder`（也可 `--keep-system-reminder` 保留）。
3. CLI stream：`message(role=user)`→user_message；`tool_call`→tool-call（parameters 对象）；`tool_result`→tool_result（call_id=toolCallId，content=`value.stdout`，exitCode≠0→is_error）；`completion.finalText`→assistant_message（置后于工具结果）；无 assistant 中间 text 行 → 不构造空消息。
4. cwd/title：session store 有；CLI stream 无 → 需 `--target-cwd`/参数补，warning。
5. usage：fixture 无 → 不写 metrics；`version=2` → extra（schema drift 断言点）。

**Writer 最小可行**：写 **session store JSONL** `<out>/sessions/<sid>.jsonl`（首行 `session_start{id,title,owner,version:2,cwd}` + 每条 `message{id,timestamp,message{role,content}}`）；CLI stream-json 是输出格式、不是 store → 不作 writer 目标。原生 store 路径/文件名**未核实** → 格式级自往返；`--install` 不可承诺（catalog E 已标 legacy-only）。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| DRD-A1 | session store 3 行解析；title=`Stage0 Droid Drift`、cwd=`/tmp`、version=2；2 消息（user/assistant）；`<system-reminder>` 剥离后 user 文本=`Do the thing` + warning | FIXTURE |
| DRD-B1 | CLI stream 4 记录（+空行跳过）：1 user；tool-call=1（Shell/echo hi）/tool_result=1 配对，stdout=`hi\n`、exitCode=0；completion.finalText=`Done`→assistant 文本；`session_id` 一致 | FIXTURE |
| DRD-A2（写） | IR→session store JSONL→读回：标题/cwd/消息/角色序一致 | FIXTURE（B4-F3） |

**已知有损项**：原生路径/文件名未核实（legacy-only）；两代格式互不兼容（CLI stream 只是输出）；无 usage；`<system-reminder>` 语义；无树/分支；`owner` 等运行态字段不迁移。

---

### B4-05 Google Antigravity（FIXTURE-LOW｜难度 ★★★，reader-only）

**原生存储事实**（证据：harness-catalog **C** 完整目录与 DB schema：`~/.gemini/antigravity*/conversations/<uuid>.pb` **protobuf 无公开 schema**、`conversation_summaries.db`（SQLite，131 行含 `battle_id/nesting_depth`）、`brain/<uuid>/*.md` artifacts；**P2**「`.pb` 需逆向」）。fixture 是 **JSONL step 转录**（规范化表示，非 `.pb`，N3），S3。

**fixture**：
- `agent-sessions/stage0/antigravity/desktop_small.jsonl`（2,152 B，6 行）：`USER_INPUT×1 / PLANNER_RESPONSE×3 / GENERIC×2`；tool_calls=2（`run_command`、`read_file`）；tokens：(9452/518)、(10146/168)、(10406/148)；created_at ISO。
- `cli_schema_drift.jsonl`（518 B，3 行）：`USER_INPUT(含 promptVariant:"experimental") / PLANNER_RESPONSE(thinking、tool_calls:[]、telemetry.latencyMs) / BROWSER_NAVIGATE(content)`。

| 字段 | 类型 | 实测 | IR 用途 |
|---|---|---|---|
| `step_index` | int | 0..5 / 0..2 | 顺序（权威） |
| `source` | str | `USER_EXPLICIT` / `MODEL` | 角色来源 |
| `type` | str | `USER_INPUT`/`PLANNER_RESPONSE`/`GENERIC`/`BROWSER_NAVIGATE` | 分派 |
| `status` | str | `DONE` | extra |
| `created_at` | ISO | `2026-10-21T18:36:32Z` | ts |
| `content` | str | user 包裹 `<USER_REQUEST>…</USER_REQUEST>`；GENERIC=命令/文件输出；最终回答 | text / tool_result 内容 |
| `thinking` | str | `"[trimmed for fixture]"` / `"..."` | reasoning（PII 裁剪） |
| `tool_calls[]` | obj[] | `{name:"run_command",args:{CommandLine:"…",WaitMsBeforeAsync:"5000",toolSummary:"…"}}`；`{name:"read_file",args:{Path:"…"}}` | tool-call（**无 id**） |
| `input_tokens/output_tokens/cache_read_tokens` | int | 见上 | usage |
| `promptVariant`/`telemetry` | str/obj | `experimental` / `{latencyMs:12}` | extra（schema drift） |

**截断示例（tool_call 行 + GENERIC 结果行，各 ≤300 字符）**

```json
{"step_index":1,"source":"MODEL","type":"PLANNER_RESPONSE","status":"DONE","created_at":"2026-10-21T18:36:32Z","input_tokens":9452,"output_tokens":518,"tool_calls":[{"name":"run_command","args":{"CommandLine":"\"ls -la /tmp/desk-probe\""}}]}
```
```json
{"step_index":2,"source":"MODEL","type":"GENERIC","status":"DONE","created_at":"2026-10-21T18:36:38Z","content":"Command exited with code 0.\n\nCommand output:\ntotal 8\r\n…"}
```

**Reader 映射规则**

1. 按 `step_index`（权威，不按时间戳重排）线性化。
2. `USER_INPUT`→user_message：剥 `<USER_REQUEST>…</USER_REQUEST>` 外壳；`<ADDITIONAL_METADATA>`/`<USER_SETTINGS_CHANGE>` 段 → extra + `lossy:antigravity:user-envelope`（也可 `--keep-wrappers` 保留）。
3. `PLANNER_RESPONSE`：有 `tool_calls` → assistant_message + tool-call（**无原生 id** → 生成 `ant:<step>:<i>`）；无 tool_calls → assistant_message（text=thinking→reasoning? 见 4）。
4. **工具结果配对（推断）**：紧跟 tool_call 之后的 `GENERIC` 记录 → 该 tool-call 的 tool_result（`inferred_pairing:true` + lossy）；连续多个 tool_call 与 GENERIC 数量不匹配 → 未配对 call 由 Writer 补占位。
5. `BROWSER_NAVIGATE` 等未知 type → 进 warnings/extra；`status!="DONE"`→warning。
6. tokens 只在 PLANNER_RESPONSE 行 → usage；cwd 未提供 → `cwd=None`+warning（writer/转换需 `--target-cwd`）。title=首条 user 文本。
7. **可扩展点**：同一套 step 语义可从 `conversation_summaries.db`（SQLite 只读）补 `battle_id/nesting_depth`（子代理层级）——但 DB 无 fixture → 标 FIXTURE-CONSTRUCTED 另行验证。

**Writer 最小可行：不支持（BLOCKED）**。原生 `.pb` 无公开 schema、需逆向；写 JSONL 转录不是 Antigravity 可加载格式 → 本批**只做 reader**（`--to antigravity` 应显式报 unsupported）。若未来逆向 `.pb`，另立专项（建议先只读 summaries.db 补层级）。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| ANT-F1 | desktop 6 行；user=1；assistant=3（3 条 PLANNER_RESPONSE，其中 2 条带 tool_calls）；tool-call=2（run_command/read_file）；推断 tool_result=2（GENERIC×2）且标记 inferred；最终文本含 `` `a.txt` ``；tokens 合计 input=9452+10146+10406=30004、output=518+168+148=834 | FIXTURE-LOW（B4-F1/F2） |
| ANT-F2 | cli drift 3 行：USER_INPUT 剥壳→`Go`；PLANNER_RESPONSE tool_calls=[]、thinking→无 text；`BROWSER_NAVIGATE`→warning；`promptVariant`/`telemetry`→extra | FIXTURE-LOW |
| ANT-F3 | cwd 缺失 → warning；写入目标不支持 → `--to antigravity` 返回 unsupported（负用例） | FIXTURE-LOW |

**已知有损项**：非原生格式（`.pb` 未覆盖）；工具结果靠 GENERIC 推断配对；无工具 id/cwd/title；user 信封剥离；thinking 被 fixture 裁剪；`conversation_summaries.db` 层级未读；写方向完全 BLOCKED。

---

### B4-06 Hermes（FIXTURE-CONSTRUCTED｜难度 ★★★）

**原生存储事实**（证据：harness-catalog **C** 真实 schema：`~/.hermes/state.db`（SQLite：sessions/messages/`session_model_usage`/cron）+ `sessions/`、`kanban.db`、`projects.db`，`HERMES_HOME`；P0「SQLite 类」）。fixture 是 JSON **逻辑投影**（N5），非原生 DB 文件。

**fixture**：`agent-sessions/stage0/hermes/small.json`（472 B，8 键，2 消息）：

| 字段 | 实测 | IR 用途 |
|---|---|---|
| `session_id` / `model` / `platform` | `20260429_hermes_small` / `claude-sonnet-4-6` / `cli` | id/model/extra |
| `session_start` / `last_updated` | `2026-04-29T20:00:00Z` / `…04Z` | created/updated |
| `cwd` / `message_count` | `/tmp/hermes-small` / `2` | cwd / 审计 |
| `messages[{role,content,finish_reason}]` | user `Summarize this directory.`；assistant …`+`finish_reason:"stop"` | 消息 |

**截断示例（整文件节选，≤300 字符）**

```json
{"session_id":"20260429_hermes_small","model":"claude-sonnet-4-6","session_start":"2026-04-29T20:00:00Z","cwd":"/tmp/hermes-small","messages":[{"role":"user","content":"Summarize this directory."},{"role":"assistant","content":"This directory contains a small Hermes fixture."}]}
```

**Reader 映射规则**

1. **阶段 A（现在可做）**：JSON 逻辑投影 reader：user/assistant→对应消息；`session_start`→created；cwd/title（无 title 字段→派生）；`finish_reason`→extra；tool 消息（投影 fixture 无，真实可能有 `role:"tool"`+`tool_call_id`）按通用规则处理。
2. **阶段 B（需 golden DB，B4-G2）**：SQLite 只读 `sqlite3.connect("file:state.db?mode=ro", uri=True)` + `PRAGMA query_only=ON`；按 catalog **C** 的表名 `sessions/messages/session_model_usage` 读取；**列名 catalog 未给全，构造 golden 时只能假设，必须标「列名未核实」**；`session_model_usage`→usage（含 `actual_cost_usd` 可作成本校验，catalog 提到）。
3. 若 DB 中 `content` 为 JSON（消息 content 可能是 blocks 序列化）→ 二次 `json.loads` 容错。

**Writer 最小可行**：阶段 A 写 JSON 投影 `<out>/sessions/<sid>.json`（可直接被本 reader 读回，**非 Hermes 原生**）；阶段 B 写 SQLite `state.db`（INSERT sessions/messages）→ **BLOCKED 直到 golden DB 列名核实**。本轮只交付「JSON 投影 writer（格式级）+ 原生 DB writer 待 golden」。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| HER-F1 | JSON 8 键；2 消息（user/assistant）；cwd/model/session_start/last_updated 精确；`message_count==2` 与解析一致 | FIXTURE（投影级） |
| HER-F2（写） | IR→JSON 投影→读回 2 消息一致 | FIXTURE（B4-F3，投影级） |
| HER-F3（golden DB） | **自构** state.db（sessions 1 行 + messages 2 行，FIXTURE-CONSTRUCTED）→ 只读打开 → reader 读回 2 消息/角色序/cwd；断言连接串 `mode=ro` 生效（写操作抛错） | FIXTURE-CONSTRUCTED |

**已知有损项**：原生 SQLite 列名/索引未核实；投影无 tools/usage 明细；`session_model_usage.actual_cost_usd` 等成本字段在阶段 B 才能保留；`finish_reason` 仅 extra。

---

### B4-07 Devin CLI（FIXTURE-CONSTRUCTED｜难度 ★★★）

**原生存储事实**（证据：harness-catalog **E** 253 sessions 审计 + **C** 明细：`~/.local/share/devin/cli/sessions.db`（SQLite），有 `devin --resume <slug>`、无导出）。fixture 是作者明确的**逻辑投影**（`_fixture` 字段自述：live DB 由 `agent_watch` 归一，shapes verified against CLI 3000.3.27 / `0becb483`）。

**fixture**：`agent-sessions/stage0/devin/small.json`（1,880 B）：`session` 10 字段 + `nodes` 4 个。

| 部分 | 字段 | 实测 | IR 用途 |
|---|---|---|---|
| session | `id,title,working_directory,backend_type,model,agent_mode` | `bald-ketch` / `Fix the broken checks` / `/tmp/as-agent-lab/devin/project` / `Windsurf` / `swe-1-7` / `bypass` | id/title/cwd/extra |
| | `created_at,last_activity_at`（epoch **秒**） | `1786004275` / `1786004400` | created/updated（×1000） |
| | `main_chain_id,hidden` | `5` / `0` | extra |
| nodes[] | `message_id,role,content` | m1 system / m2 user / m3 assistant / m4 tool | 消息 |
| | `thinking{signature,thinking}` | `{sig, "I should read it first."}` | reasoning |
| | `tool_calls[{id,index,kind,name,arguments}]` | `call_1`/`function`/`read_file`/`{path:"hello.py"}` | tool-call |
| | `tool_call_id`（tool 节点） | `call_1` | tool_result 配对 |
| | `metadata{num_tokens,is_user_input}` | `null` / `true` | extra |

**截断示例（session + assistant 节点，各 ≤300 字符）**

```json
{"id":"bald-ketch","title":"Fix the broken checks","working_directory":"/tmp/as-agent-lab/devin/project","backend_type":"Windsurf","model":"swe-1-7","agent_mode":"bypass","created_at":1786004275,"last_activity_at":1786004400,"main_chain_id":5}
```
```json
{"message_id":"m3","role":"assistant","content":"Reading the file.","thinking":{"signature":"sig","thinking":"I should read it first."},"tool_calls":[{"id":"call_1","index":0,"kind":"function","name":"read_file","arguments":{"path":"hello.py"}}]}
```

**Reader 映射规则**

1. JSON 投影：`session`→元数据（created×1000→ms）；`nodes` 按 `message_id`/数组顺序线性化（`main_chain_id` 提示主链，节点无 parent 字段 → 无法还原分支，warning）。
2. `role`：`system`→system_message（默认丢）；`user`→user_message（`metadata.is_user_input`→extra）；`assistant`→assistant_message（`content`→text、`thinking.thinking`→reasoning、`tool_calls[]`→tool-call，arguments 为对象）；`tool`→tool_result（call_id=`tool_call_id`，content）。
3. usage：`metadata.num_tokens` 为 null → 不写 metrics（warning）；`backend_type=="Windsurf"` 提示 Devin 后端形态，进 extra。
4. title/cwd/model 来自 session；`hidden`/`agent_mode`→extra。
5. **原生 DB 路径（阶段 B）**：`~/.local/share/devin/cli/sessions.db`，消息 payload 据作者描述为「sessions 行 + main-chain message_nodes」→ golden DB 需 sessions/message_nodes（B4-G3），列名未核实。

**Writer 最小可行**：阶段 A 写 JSON 投影 `<out>/sessions/<sid>.json`（非原生，格式级）；阶段 B 写 SQLite sessions.db → **BLOCKED 直到 golden DB 核实**；不实现 `devin --resume` 注册。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| DEV-F1 | session 10 字段；4 nodes；消息：system 默认丢→3 条（user/assistant/tool）；tool-call=1/tool_result=1 配对；reasoning=`I should read it first.`；created_ms=1786004275000；title/cwd/model 精确 | FIXTURE（投影级） |
| DEV-F2 | `--keep-system` 时 4 条消息且 system 首位；`metadata.num_tokens=null`→metrics 空+warning | FIXTURE |
| DEV-F3（写） | IR→JSON 投影→读回角色序/工具配对/时间一致 | FIXTURE（B4-F3） |
| DEV-F4（golden DB） | 自构 sessions.db（sessions 1 行 + message_nodes 按 main_chain 顺序，FIXTURE-CONSTRUCTED）只读读回 3 消息 | FIXTURE-CONSTRUCTED |

**已知有损项**：逻辑投影非物理 schema；SQLite 列名/索引未核实；`backend_type`/`agent_mode`/`hidden`/签名 thinking 仅 extra；分支（main_chain_id）不可还原；resume 注册未知。

---

### B4-08 OpenCode（FIXTURE-CONSTRUCTED｜难度 ★★★，批 3 续）

**原生存储事实**（证据：harness-catalog **C** 真实 51 sessions：现版 `~/.local/share/opencode/opencode.db`（SQLite：session/message/part 表，`data` JSON blob；另有 `session_diff/snapshot/tool-output`）；旧版 JSON 目录树 `storage/session|message|part/…`；`OPENCODE_DB`/`XDG_DATA_HOME` 可覆盖）；批 3 结论「半阻塞」。

**fixture**（仅 part 级，G5）：`agent-sessions/stage0/opencode/001.json`（79 B）、`002.json`（88 B）：`{"id":"p_user_1","type":"text","text":"Hello","time":{"start":1730000001000}}`；`sessionport/.../abc.json`（255 B）简化 `{id,parts}`（parts 顺序非标准：assistant 在 user 前）。

**Reader 映射规则（两形态）**

1. **legacy JSON 树**：`session/<project>/<sid>.json` + `message/<sid>/<msgID>.json` + `part/<msgID>/<partID>.json`；按 message `time.created` 排序、part 按 id/时间组装；part `type=="text"`→text、`reasoning`→reasoning、`tool`→tool-call + `state.output`→tool_result（`state.status=="completed"`）。
2. **SQLite**：只读 URI + `PRAGMA query_only`；表 session/message/part，业务字段在 `data` JSON → `json.loads`；列名/版本**未核实** → `lossy:opencode:sqlite-schema-unverified` + `--schema-profile`。
3. fixture 顺序异常 → 以 message 时间排序并 warning（批 3 已定）。
4. cwd=session.directory；title=session.title；usage 从 assistant message tokens（据 C）；子代理/分支按 parentID。

**Writer 最小可行**：交付 **legacy JSON 树 writer**（多文件，结构等价、标注 experimental；现版是否仍读 legacy 未核实）；SQLite writer **BLOCKED** 直到 golden DB 列名核实（B4-G1）。`--install` 真实库不支持（显式报错）。

**测试计划**

| 用例 | 断言 | 证据 |
|---|---|---|
| OC-F1 | part 文件 2 个：type=text、text 精确（`Hello`/`Found 2 files.`）、`time.start`=1730000001000/1730000003100；缺关联字段 → `opencode:orphan-part` warning | FIXTURE |
| OC-F2 | sessionport abc：parts=2，重排为 [user,assistant]+warning；文本精确 | FIXTURE |
| OC-F3（golden DB） | 自构 opencode.db：session 1 行 / message 2 行 / part 3 行（含 1 组 tool）→ 只读打开 → 2 消息+1 配对；`lossy sqlite-schema-unverified` | FIXTURE-CONSTRUCTED |
| OC-F4（写） | legacy 树 writer → 读回等价；SQLite writer 显式 unsupported/experimental | FIXTURE（B4-F3，结构级） |

**已知有损项**：SQLite 表结构/索引/版本未知；part→message 关联缺样本；tool state 配对未验证；snapshot/tool-output 不迁移；legacy 兼容性未知。

---

### B4-09 Cline（FIXTURE-CONSTRUCTED｜难度 ★★★，扩展）

**原生存储事实**（catalog **C** 完整 schema + **B**）：CLI `~/.cline/data/sessions/<epochms>_<slug>/{<id>.json,<id>.messages.json}`；VS Code 扩展 `globalStorage/saoudrizwan.claude-dev/tasks/`。fixture 只有 **metadata**（批 3 已实测：2 个 metadata 文件，`messages_path` 指向文件**不存在**）。

**fixture 实测**：`cline-desktop-continued.json`（1,066 B，status=completed/exit_code=0/cwd=/tmp/as-agent-fixture/project/metadata.title）；`session_1792607722905_fixt1.json`（1,526 B，status=idle/exit_code=null/usage input 32103/output 301/cacheRead 15738/totalCost 0.1826345）。

**Reader 映射规则**：metadata 字段（version/session_id/started_at/ended_at/exit_code/status/cwd/workspace_root/model/prompt/metadata.title/systemPrompt/usage/importedFrom）→ IR 元数据；`prompt` 中 `<user_input mode="act">…</user_input>` 剥壳→首条 user；messages 文件缺失 → warning `cline:messages-file-missing`（禁止假装完整会话）。messages 文件（需构造，B4-G6）：数组 `{ts,type:"say"|"ask",say|ask:"text"|"tool"|"command"|"completion_result",text,partial?}` → say/text/ask/text 映射消息；say tool→tool-call；完成后行折叠。

**Writer 最小可行**：写 `<out>/data/sessions/<epochms>_<slug>/<id>.json` + `<id>.messages.json`（messages 体 **experimental**，schema 未 fixture 验证）；目录命名规则未核实；格式级自往返。

**测试计划**：CL-F1 metadata（19 键/status/exit_code/cwd/usage/title/`messages-file-missing`）；CL-F2 idle 状态 warning；CL-F3 自构 messages.json（FIXTURE-CONSTRUCTED）→ 消息数/角色序/tool 配对；CL-F4 双文件往返。证据：FIXTURE（metadata）+ FIXTURE-CONSTRUCTED（messages）。

**有损项**：messages 体 schema 未验证；checkpoints/图片；运行态 enable_*；VS Code store 不支持；`status=idle` 会话可能未结束。

---

### B4-10 fx（vercel-labs）（FIXTURE-LOW｜难度 ★★☆，metadata 级）

**原生存储事实**（证据：harness-catalog 附录 A1 + **E** 逐字段验证：`~/.fx/sessions/<id>/{checkpoint.json,session.json,display.json}`；0.0.8+ 改为 `events.jsonl`（schema 4）；有 `fx --resume <id>`；格式年轻易漂移）。

**fixture 实测**（N4）：
- `session.json`（920 B）：`schema_version:3`、`storage_format:"event_log_v1"`、`id`、`authority_id`、`created_at_ms/updated_at_ms`、`origin_workspace_root/workspace_root`、`conversation_language`、`history_len:5`、`log_generation`、`last_event_seq:1`、`event_log_bytes:1`（**占位**）、`event_log_stat_fingerprint`、`generation_base_seq/bytes`、`checkpoint_seq/sha256`、`total_input_tokens:1200`、`total_output_tokens:340`、`preferences{model:"demo/model-1",effort:"auto",fast_mode:false}`。
- `display.json`（196 B）：`schema_version:1`、`title:"List the files in the current directory"`、`preview`、`origin_workspace_root`。
- `checkpoint.json`（177 B）：**坏 JSON**（line 8 col 45 非法控制字符，记录被故意截断 `"unterminated recor`）→ 只能作容错负样本。
- **缺 `events.jsonl`** → 会话消息体无任何样本。

**Reader 映射规则（可达部分）**：session.json→cwd/title/created/updated/model/preferences/token 总计；display.json→title 优先；messages 主体**无法还原**（events 缺失）→ 只能产出「元数据会话 + warning `fx:events-missing`」，不得输出伪消息。`checkpoint.json` 解析失败 → warning（预期行为）。
**Writer**：写 session.json+display.json 会被 fx 视为不完整会话（`history_len/event_log_bytes` 矛盾）；events.jsonl schema 4 无样本 → **BLOCKED**。
**测试计划**：FX-F1 session.json 全字段/display title/preferences/token 总计；FX-F2 checkpoint 坏 JSON → 断言 reader 报 warning 不崩；FX-F3 `events.jsonl` 缺失 → 判断为「metadata-only 会话」并 warning。**补采建议**：安装 fx 0.0.8+ 生成 1 个真实 `events.jsonl`，或从 vercel-labs/fx 仓库 tests 取 schema 4 事件样本。
**判定**：FIXTURE-LOW（仅 metadata）；转换能力 BLOCKED；不进批 4 核心。

---

### B4-11 Wire 层：atifact HAR / SSE（FIXTURE-LOW｜独立路线，不计 native）

**对象**：`atifact/test-fixtures/*.har`（6 个 / 14,314 B / 8 entries）：
- `har-anthropic.har`（1 entry，`POST /v1/messages`，请求含 system+messages+tools，响应 SSE `message_start/content_block_*`）
- `har-anthropic-thinking.har`（1，含 thinking 块）
- `har-anthropic-multiturn.har`（3 entries，**请求 messages[] 累积**）
- `har-openai-chat.har`（1，`data:` chunk 流）
- `har-openai-chat-tools.har`（1，请求含 tool_calls，响应 delta tool_calls）
- `har-openai-responses.har`（1，`event: response.output_text.delta` 等）
- `vally-simple.json`（3,310 B）：atifact 自身合成 provider 流（10 事件：user_message/turn_start/reasoning/assistant_message/tool_call/tool_result/token_usage/turn_end/system(compaction)/agentId 子代理）→ **不是 harness session**，不作证据。

**判定**：HAR 是 **wire-level（S4）**，不是任何 harness 的 session store → **不能作 native adapter**；但可作为「wire 源 adapter」（与批 2 `oss_traj` 同层）：解析请求 JSON + 响应 SSE → IR。证据上限 FIXTURE-LOW（6 个单轮/多轮样本，非真实会话）。**价值**：可补批 2 的 `claude-desktop`/`gateway` 缺口（wire 级真实录制），且 Anthropic/OpenAI 三种 provider 形态与 `oss_traj` 的 `messages_format` 分支高度重合，可复用其归一化代码。
**测试计划**：HAR-F1 `har-anthropic.har`→1 user+1 assistant+tool-call（calculator）；HAR-F2 `har-openai-chat-tools.har`→tool_calls 1 配对；HAR-F3 `har-openai-responses.har`→output text 还原；HAR-F4 `har-anthropic-multiturn.har`→按末次请求 messages 或逐 entry 配对，避免重复 user（3 entries 累积）；HAR-F5 vally → 拒绝/标 synthetic。**结论**：单列「wire 层」技术路线，**不占 30-40 native 名额**。

---

### B4-12 BLOCKED 汇总（批 4 不实施）

| Harness / 源 | 证据状态 | 阻塞原因 | 补采/解锁建议 |
|---|---|---|---|
| **Junie**（JetBrains） | 仅 sessionport S2（133 B，2 行） | 无原生 schema；catalog 说实际为 IDE/JVM 内部，默认路径未核实 | 安装 Junie 采真实会话；或上游 repo tests 找原生 fixture |
| **Mistral Vibe** | 仅 sessionport S2（130 B） | 同上；catalog C 称 `~/.vibe/logs/session/session_<ts>_<hash>.json` 单文件含 stats/messages，但 fixtures 未体现 | 按 catalog **C/F** 路径采真实 JSON；或自构（标 CONSTRUCTED） |
| **Kilo Code** | 仅 sessionport S2（132 B） | 无 schema；真实 store 未核实（Cline 族） | 先完成 Cline pack，再按同族 profile 扩展 |
| **Roo Code** | **无 fixture** | 无任何样本 | 同 Kilo；需安装采集 |
| **Goose** | 仅 sessionport S2（138 B） | 无原生 schema 证据（批 3 已判 LOW） | 安装 goose 采 1 条真实 session（`~/.local/share/goose/sessions/*.jsonl` 待核实） |
| **Windsurf** | 仅 sessionport S2（115 B） | IDE 内部存储，路径/格式未核实（catalog D only） | 安装采集；或从 Agent Sessions 上游补 fixture |
| **Cursor IDE** | 无 fixture（SQLite `state.vscdb`） | 无 DB 样本 | B4-G5 golden DB（cursorDiskKV composerData/bubbleId）或真实采集；CLI 侧批 3 已覆盖 |
| **Copilot `session-store.db`** | 无 DB fixture（事件流已覆盖） | 无 DB 样本 | B4-G4 golden DB（可选，仅用于原生 resume/加载验证） |
| **Droid 原生 store 路径** | 路径未核实 | catalog **E** 标 legacy-only | 以 fixture 格式（session store JSONL v2）为准，路径参数化 |
| **Antigravity `.pb`** | protobuf 无公开 schema | 需逆向 | 专项逆向；或先只读 `conversation_summaries.db` 补层级（FIXTURE-CONSTRUCTED） |

---

## 3. 需构造 golden sample 清单（FIXTURE-CONSTRUCTED）

> 规则：public-fixtures **无任何 `.db/.sqlite` 文件**（已实测）；以下构造样本由 converter-dev 生成后入库 `samples/batch2/public-fixtures/batch4-constructed/`（或 `tests/artifacts/`），**文件名/README 必须标 `constructed`**，**不得与上游 fixtures 混放**。构造时优先用 `sqlite3` CLI + Python `sqlite3` 写入，验证时**只读打开**：`sqlite3.connect("file:X.db?mode=ro", uri=True)` + `PRAGMA query_only=ON`。

| ID | 对象 | 需构造的文件 | 已知字段（来源） | 未核实/风险 | 验证方式 | 证据 |
|---|---|---|---|---|---|---|
| **B4-G1** | OpenCode | `opencode.db`：`session` 1 行 / `message` 2 行 / `part` 3 行（含 1 组 tool） | 表名 session/message/part（**C**）；列名与 `data` JSON 结构**未核实** | 列名/索引/版本可能全错 | 只读连接 + reader 读回 2 消息/1 配对 | FIXTURE-CONSTRUCTED |
| **B4-G2** | Hermes | `state.db`：`sessions` 1 / `messages` 2（+`session_model_usage` 可选） | 表名（**C**）；列名未核实；`actual_cost_usd` 可作成本校验 | 列名未核实 | 只读连接 + reader | FIXTURE-CONSTRUCTED |
| **B4-G3** | Devin | `sessions.db`：`sessions` 1 行 + `message_nodes` 4 节点（main chain） | 作者描述逻辑投影（**E**）；物理列名未核实 | 列名未核实 | 只读连接 + reader；JSON 投影做对照 | FIXTURE-CONSTRUCTED |
| **B4-G4** | Copilot CLI（可选） | `session-store.db`（sessions/turns/checkpoints/assistant_usage_events） | **C** 完整 schema | 仅用于批 3 writer 的原生 resume 验证，非本批必需 | 只读连接 | FIXTURE-CONSTRUCTED |
| **B4-G5** | Cursor IDE（可选） | `state.vscdb`（`cursorDiskKV`: composerData/bubbleId） | **C** 两侧完整 schema | KV JSON blob 结构复杂 | 只读连接 | FIXTURE-CONSTRUCTED |
| **B4-G6** | Cline | `<id>.messages.json`（say/ask 记录 4-6 条） | **C**「完整 schema（含 exit_code/status）」；say/ask 子类型集合未核实 | 子类型集合未核实，Reader 需 allowlist+warnings | JSON 读回 + IR 断言 | FIXTURE-CONSTRUCTED |
| **B4-G7** | fx | `events.jsonl`（schema 4） | **E**：0.0.8+ 事件日志；事件字段**无样本** | 字段完全未核实 → **不建议凭猜测构造**；优先真实采集 | — | 建议 BLOCKED |
| **B4-G8** | Goose/Junie/Vibe/Windsurf/Roo/Kilo | 真实 session 各 1 个 | 无 | 无 | — | BLOCKED（补采） |

> 构造 golden 的纪律（写进下一轮任务）：① 每个构造文件必须带 `"__constructed": {"reason": "...", "schema_source": "docs/harness-catalog.md#C", "unverified_columns": [...]}` 之类标记或 README 说明；② 报告证据列写 `FIXTURE-CONSTRUCTED`，不得写 FIXTURE；③ 若构造后 reader 无法自洽（如列名全错），该 harness 回退 BLOCKED 并记录。

---

## 4. 批 4 建议（8 个核心 + 3 个扩展）与家族复用

### 4.1 建议核心 8 个（按实施顺位与难度）

| 顺位 | ID | Harness | 难度 | fixture 证据 | Reader | Writer 最小可行 | 证据上限 | 覆盖增量（分层） |
|---|---|---|---|---|---|---|---|---|
| 1 | B4-01 | **OpenClaw** | ★ | S1 5 行/3 消息 | 树状 JSONL（复用 Pi/OMP） | sessions JSONL | FIXTURE | +1 |
| 2 | B4-02 | **Kimi Code** | ★★ | S1 50 行/22 类事件 | 事件日志（主通道 agent.message.appended） | sessions JSONL | FIXTURE | +1 |
| 3 | B4-03 | **Grok Build** | ★★ | S1 两文件 | 多文件组装（summary+chat_history） | summary.json+chat_history.jsonl | FIXTURE | +1 |
| 4 | B4-04 | **Factory Droid** | ★★☆ | S1 两代格式 | session store JSONL v2 + CLI stream | sessions JSONL | FIXTURE | +1（补已 COLLECTED） |
| 5 | B4-05 | **Antigravity** | ★★★ | S3 JSONL 转录 | reader-only（step 转录） | **不支持**（`.pb` BLOCKED） | FIXTURE-LOW | +1（标注 LOW） |
| 6 | B4-06 | **Hermes** | ★★★ | S3 逻辑投影 | JSON 投影 + SQLite golden | JSON 投影（原生 DB 待 golden） | FIXTURE-CONSTRUCTED | +1（补已 COLLECTED） |
| 7 | B4-07 | **Devin CLI** | ★★★ | S3 逻辑投影 | JSON 投影 + SQLite golden | JSON 投影（原生 DB 待 golden） | FIXTURE-CONSTRUCTED | +1 |
| 8 | B4-08 | **OpenCode** | ★★★ | part 级 + S2 | legacy JSON 树 + SQLite golden | legacy 树（experimental） | FIXTURE-CONSTRUCTED | +1（补已 COLLECTED） |

**分波执行**：
- **波 1（JSON/JSONL/多文件，5 个）**：OpenClaw → Kimi → Grok → Droid → Antigravity(reader-only)。全部可在一轮内交付 FIXTURE 级 reader + 格式级 writer（Antigravity 仅 reader）。
- **波 2（SQLite golden 套件，3 个）**：先交 B4-G1/G2/G3 构造脚本与只读打开验证，再交 Hermes/Devin/OpenCode 的 reader（+OpenCode legacy 树 writer）。
- **扩展（3 个，不阻塞核心）**：Cline（G6 messages 构造，metadata + 消息体双层验证）、fx（metadata-only；events 待补采）、wire-HAR（独立技术路线）。

### 4.2 与批 3 的家族复用矩阵

| 家族 | 成员 | 可复用点 | 批 4 增量 |
|---|---|---|---|
| **pi 系（树状 JSONL）** | OMP（批 1 native）/ Pi（批 3）/ **OpenClaw**（批 4） | 树 walker、`session/model_change/message/parentId` 布局、`content[]` block 映射 | OpenClaw 仅需新 profile（字段名差异：`toolCall/toolResult`、`usage` 结构）；建议把 `readers/omp.py`/`native_batch3._load_pi` 的树逻辑抽公共 helper |
| **事件日志（自有协议）** | Copilot CLI（批 3）/ Kimi Code（批 4）/ DSH（批 1） | 行序权威、delta/瞬态折叠、行级容错、未知事件→warning | Kimi 需「主通道 agent.message.appended + 备用 loop events」双通道 |
| **多文件 + 伴生索引** | Grok（批 4）/ fx（批 4）/ Cline（批 4）/ Cursor legacy（批 3） | 主文件 + 伴生文件组装、缺文件 warning | Grok 的 `summary+chat_history` 是干净样板 |
| **CLI stream-json** | atifact Claude/Codex CLI（批 1 参考）/ Copilot CLI events（批 3）/ **Droid stream**（批 4） | message/tool_call/tool_result/completion 事件解析模式 | Droid 两种输入统一 |
| **OpenAI-chat 消息形状** | oss `openai-chat`（批 2）/ **Hermes** / **Devin nodes**（批 4） | role/content/tool_calls/tool 归一、`finish_reason`/`num_tokens` 进 extra | SQLite 投影读取 |
| **SQLite 只读层** | OpenCode（批 4）/ Hermes（批 4）/ Devin（批 4）/ Copilot DB（可选）/ Cursor IDE（可选） | `sqlite3` URI 只读 + PRAGMA query_only + `data` JSON 二次解析 + golden DB 构造 | 波 2 建立公共 `sqlite_ro.py` 工具层 |
| **Gemini 家族** | Gemini（批 3）/ Qwen（批 3） | 不直接复用 Antigravity（见下） | **Antigravity 用 Gemini 模型但格式独立**（step 转录/`.pb`），不能复用 Gemini JSON reader |
| **Claude 衍生** | Claude Code（批 1）/ Qoder（批 1）/ Qwen（批 3，envelope 层面） | — | **Kimi 不是 Claude 衍生**：fixture 是自有事件协议（纠正 catalog 猜测） |

### 4.3 建议实现结构（与批 3 对齐，供 converter-dev 参考）

- `tools/agent-session-import/agent_session_import/readers/native_batch4.py`：
  - `FIXTURE_EVIDENCE = {"openclaw": "FIXTURE", "kimi": "FIXTURE", "grok": "FIXTURE", "droid": "FIXTURE", "antigravity": "FIXTURE-LOW", "hermes": "FIXTURE-CONSTRUCTED", "devin": "FIXTURE-CONSTRUCTED", "opencode": "FIXTURE-CONSTRUCTED"}`
  - `PRIMARY_FILES`/`EXTRA_PATTERNS` 用本文 §1.1 路径；`load_session(source, root, session, path, keep_system…)`、`list_sessions(source, root)`（与 `native_batch3.py` 同签名）。
- `writers/native_batch4.py`：`WRITERS = {openclaw,kimi,grok,droid,hermes,devin,opencode}` + `write(source, ir, root, sid, target_cwd)`；Antigravity 不注册（unsupported）。
- 新增 `sqlite_ro.py`：只读连接/查询/JSON blob 解析 + golden DB 构造脚本放 `tests/tools/make_batch4_golden.py`。
- 证据常量、`docs/interop-matrix-batch4.md` 的「证据等级」列直接引用本文判定。
- 批 3 已交付 reader/writer 在 `native_batch3.py`；批 4 不修改其逻辑，只复用 helper（如需抽公共 helper，单独 PR 并跑批 3 回归）。

---

## 5. 与 30-40 覆盖账本的对应关系

> **批 4 验收级别（建议）**：**B4-F1** fixture 解析（reader 读回 IR，断言与本文 §2 测试计划一致）→ **B4-F2** ATIF 往返（IR→ATIF→IR 语义等价）→ **B4-F3** 目标格式自往返（writer 产物用同一 reader 读回）→ **B4-F4** 原生加载（目标 harness 真实加载；本轮全部 **N/A**）→ **B4-F5** 真实会话（无；fixtures 均为合成）。报告每行必须标证据等级（FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED / BLOCKED），**不得混算**。

### 5.1 账本口径（沿用协议 §12.4，不得混算）

| 层 | 当前数量 | 批 4 增量 | 批 4 后 | 证据等级 |
|---|---|---|---|---|
| 批 1 原生（本机安装） | 5 | 0 | 5 | **NATIVE**（L0-L3） |
| 批 2 采集（OSS 真实会话） | 18 | 0 | 18 | **COLLECTED** |
| 批 3 原生 fixtures | 6 | 0 | 6 | **FIXTURE**（B3-F0~F2b） |
| **批 4 核心（本文建议）** | 0 | **+8** | **37（分层合计）** | 4×FIXTURE + 1×FIXTURE-LOW + 3×FIXTURE-CONSTRUCTED |
| 批 4 扩展（可选） | 0 | +3（Cline/FX/HAR-wire） | 37→39（Cline/FX 计入；HAR 不计） | FIXTURE-CONSTRUCTED / FIXTURE-LOW |
| 批 4 上限（含 Goose） | — | +1 | **40（分层上限）** | 需补样本 |

- **协议覆盖（分层账本）**：**29 → 37**（核心 8）；做满扩展 Cline+FX+Goose → **40**（恰好协议上限 30-40）。
- **去重真实 Harness 标签**：**22 → 27**（核心 8 中 5 个全新：Kimi/Grok/OpenClaw/Antigravity/Devin；Droid=Factory Droid、Hermes、OpenCode 属**已 COLLECTED 标签补原生格式**，不新增去重标签）。扩展 Cline（已 COLLECTED）不加、FX（新）+1=28、Goose（新）+1=29。
- **真实会话覆盖（REAL）**：**不变**（批 1 5 + 批 2 独有采集标签）；批 4 全是 FIXTURE 层，**不得计入 REAL/真实会话覆盖**。

### 5.2 与协议 §12.4 计划的对照

| 协议 §12.4 批 4 计划 | 本文结论 | 证据 |
|---|---|---|
| Droid | ✅ 核心（FIXTURE，两代格式） | §B4-04 |
| Grok | ✅ 核心（FIXTURE） | §B4-03 |
| Hermes | ✅ 核心（FIXTURE-CONSTRUCTED，SQLite golden） | §B4-06 |
| Kimi | ✅ 核心（FIXTURE） | §B4-02 |
| OpenClaw | ✅ 核心（FIXTURE，pi 系复用） | §B4-01 |
| Antigravity | 🟡 条件核心（JSONL reader-only FIXTURE-LOW；`.pb` BLOCKED） | §B4-05 |
| Devin | ✅ 核心（FIXTURE-CONSTRUCTED，SQLite golden） | §B4-07 |
| OpenCode（SQLite） | ✅ 核心·波 2（FIXTURE-CONSTRUCTED） | §B4-08 |
| Cline | 🟡 扩展（messages 构造） | §B4-09 |
| Goose | ❌ BLOCKED（仅 S2） | §B4-12 |

---

## 6. 已知有损项汇总（批 4 候选）

| Harness | 主要 lossy 项 |
|---|---|
| OpenClaw | `__openclaw` 镜像身份/cost/stopReason/sourceChannel；树分叉线性化；标题派生 |
| Kimi Code | parity 段合成时间不可用；llm.request/tools_snapshot/hash/turn.* 事件丢弃；usage 仅 meta；token_counting 累计；子代理不展开 |
| Grok Build | 行内时间缺失（派生）；events/updates/plan/subagents/compaction 不迁移；`session_search.sqlite` 不写；目录编码未核实 |
| Droid | 原生路径未核实（legacy-only）；两代格式不互通；无 usage；`<system-reminder>` 语义；无分支 |
| Antigravity | 非原生 JSONL 转录；工具结果推断配对；无工具 id/cwd/title；`.pb` 与 summaries.db 未覆盖；写方向 BLOCKED |
| Hermes | SQLite 列名未核实；投影无 tools/usage 明细；成本字段仅阶段 B |
| Devin | 逻辑投影非物理 schema；列名未核实；签名 thinking/backend_type/agent_mode 仅 extra；分支不可还原；resume 未知 |
| OpenCode | SQLite schema/索引/版本未知；part 关联缺样本；tool state 配对未验证；legacy 兼容性未知 |
| Cline | messages 体 schema 未验证；checkpoints/图片/运行态字段；VS Code store 不支持 |
| fx | 只有 metadata；events.jsonl 缺失；写方向 BLOCKED |
| HAR/wire | 非 session；多轮累积请求需去重；SSE 增量需合并；合成成分（vally）不采用 |

---

## 7. 风险、限制与未核实清单

**限制（本报告）**
1. 证据上限 = **FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED**；无真实会话、未安装目标 harness、无原生加载验证（B4-F4 全部 N/A）。
2. **无 SQLite 样本**：所有 DB 结论均为「方案 + 构造清单」，非已验证 schema；列名未核实处已标注，不得当事实引用。
3. 未 clone 各 harness 源码逐一核对（受任务时长限制）；格式判断以 fixtures 实测 + `docs/harness-catalog.md`（C/D/B/E 级）为准。
4. 本文件不写代码；golden 构造与 adapter 实现留给下一轮 converter-dev。

**未核实（下一轮必须确认）**
- OpenClaw 原生路径层级（`~/.openclaw/agents/` 下具体目录）；
- Kimi 原生文件名/路径（Kimi Code `sessions/*.jsonl` vs Kimi CLI `sessions/<id>/wire.jsonl`）；
- Grok 目录命名（url-encoded-cwd 编码形式）与 `events.jsonl` 是否必需；
- Droid 原生 store 路径/版本（catalog E 标 legacy-only）；
- Antigravity JSONL 转录来源（是否 CLI/agent-sessions 规范化产物）与 `.pb` 逆向；
- Hermes/Devin/OpenCode SQLite 表名/列名/索引；
- Cline messages 体 say/ask 子类型全集；
- fx events.jsonl schema 4 字段；
- HAR/SSE 到 IR 的多轮去重与 tool 配对规则。

**风险**
- **构造样本冒充上游**：B4-G1/G2/G3/G6 一旦不加标注就会污染 FIXTURE 证据；必须 README/字段双标记。
- **格式漂移**：Kimi `protocol_version`（1.4）、Antigravity `promptVariant/telemetry`、Droid `version:2`、fx schema 3→4、OpenCode 2.x JSON→SQLite 均已见 drift 迹象 → adapter 必须有版本探测 + 宽松容错。
- **覆盖率虚高**：FIXTURE-CONSTRUCTED 与 FIXTURE-LOW 若直接计入「协议覆盖」会虚增；建议报告同时给「FIXTURE 及以上」「含 CONSTRUCTED/LOW」「去重 REAL」三列。

---

## 8. 索引与可复现性

| 内容 | 路径 |
|---|---|
| fixtures 来源/commit/许可证/原路径 | [`samples/batch2/public-fixtures/SOURCE.md`](../../samples/batch2/public-fixtures/SOURCE.md) |
| 批 3 方案（S1-S4 分类、10 目标判定、缺口 G1-G8） | [`docs/formats/batch3-fixtures.md`](batch3-fixtures.md) |
| 协议 §12（批 3 层与 30-40 覆盖账本） | [`docs/atif-interop-protocol.md`](../atif-interop-protocol.md) |
| Harness 目录（49 候选/家族/路径证据） | [`docs/harness-catalog.md`](../harness-catalog.md) |
| 批 2 采集样本（COLLECTED 层） | [`docs/batch2-samples.md`](../batch2-samples.md)、`samples/batch2/oss/` |
| 批 1 原生格式文档（家族逻辑参考） | [`docs/formats/claude-code.md`](claude-code.md)、[`codex.md`](codex.md)、[`omp.md`](omp.md)、[`qoder.md`](qoder.md)、[`dsh.md`](dsh.md) |
| 批 3 实现（接口/证据常量参考） | `tools/agent-session-import/agent_session_import/readers/native_batch3.py`、`writers/native_batch3.py` |

**复现说明**：本文所有「实测」数字由 `python3` 遍历 fixtures 得到（`os.walk`/`os.path.getsize`/逐行 `json.loads`/`collections.Counter`），空行跳过；坏样本（`fx/checkpoint.json`）用 `json.load` 捕获异常验证；**未对任何 SQLite 文件做打开操作**（目录内无 DB 文件，已 `find` 验证）。fixtures 未做任何修改。
