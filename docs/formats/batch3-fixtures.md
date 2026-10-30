# 批 3 原生 fixtures 侦察：格式 schema、Reader/Writer 方案与测试计划

> 版本：v0.1（2026-10-30）｜执行：batch3-recon（Team 成员，shared task-15）
> 上游协议：[`docs/atif-interop-protocol.md`](../atif-interop-protocol.md) §8/§11（ATIF v1.8 统一中转：Reader → IR → ATIF → IR → Writer）
> 素材：[`samples/batch2/public-fixtures/`](../../samples/batch2/public-fixtures/)（82 文件 / **1,187,119 B**；来源/commit/MIT 许可证见同级 [`SOURCE.md`](../../samples/batch2/public-fixtures/SOURCE.md)）
> 关联：[`docs/harness-catalog.md`](../harness-catalog.md)（49 候选/P0-P2/家族）、[`docs/batch2-samples.md`](../batch2-samples.md)（COLLECTED 层）
> **任务边界**：本文件只做「fixtures 盘点 + 原生 schema 侦察 + Reader/Writer 方案 + 测试计划」，**不写转换代码、不改 fixtures、不动其它成员文件**。

> **证据等级声明（贯穿全文）**
> | 代号 | 含义 |
> |---|---|
> | **FIXTURE** | 用 `public-fixtures/` 里的合成/截断样本做**格式级**验证；本轮所有结论最高只到这一级 |
> | **FIXTURE-CONSTRUCTED** | fixture 缺样本、由 converter-dev 按本文 schema 表**自构**最小样本（必须标注 constructed，不是上游 fixture） |
> | **NATIVE** | 目标 harness 真实安装 + 真实 `--resume`/加载成功；**批 3 本轮不承诺、不宣称** |
> | **BLOCKED** | 无 schema 级 fixture、无法从本轮素材得出可实施 schema → 不入首批 |
>
> fixtures 是各仓库为单元测试编写的**合成/裁剪样本**，不是真实用户会话；本文件所有「通过」均指格式级，不得写成 NATIVE/真实会话通过。

---

## 0. 结论摘要（TL;DR）

### 0.1 十个目标的可行性一句话

| 目标（本文 ID） | fixture 质量 | Reader 难度 | Writer 最小可行 | 本轮结论 |
|---|---|---|---|---|
| B3-01 GitHub Copilot CLI | **高**（atifact 6 个真实事件流形状 + agent-sessions 1 个 33 类事件大样本） | ★★ | 事件 JSONL（`session-state/`）；DB 注册未知 | **可实施，建议第 1** |
| B3-02 Gemini CLI | 中高（1 个原生 JSON 形状；无 toolCalls 记录） | ★★ | 单 JSON 写 `chats/session-*.json` | **可实施，建议第 2** |
| B3-03 Qwen Code | 中低（2 文件各 1 行、仅 user 记录） | ★★☆ | JSONL 写 `chats/<uuid>.jsonl` | **可实施（envelope 级），建议第 5** |
| B3-04 Cursor CLI | 中（两代 schema：legacy + turn_ended 版；无时间戳/tool_result） | ★★☆ | transcript JSONL；IDE SQLite 不支持 | **可实施，建议第 4** |
| B3-05 Aider | 中（原生 Markdown 历史；无工具/时间戳） | ★ | Markdown 文件 | **可实施（最快），建议第 3** |
| B3-06 OpenCode | 低（只有 part 行 schema；无 session/message、无 SQLite） | ★★★ | SQLite 写库 or legacy JSON 树（均未验证） | 可实施但需先补 SQLite 证据，排第 6 |
| B3-07 Cline | 低（只有 session metadata；`messages_path` 指向的文件**不存在**） | ★★★ | 双文件（`.json`+`.messages.json`），消息体 schema 缺 | 半阻塞，需补样本 |
| B3-08 Goose | 低（sessionport **简化** `{role,content}`，非原生 schema 证据） | ★★★☆ | 可写简化 JSONL，但无原生依据 | 需补真实样本 |
| B3-09 Windsurf | **无有效证据**（仅同一简化形状） | — | 不建议实现（无路径/schema 依据） | **BLOCKED** |
| B3-10 Roo Code / Kilo Code | **无有效证据**（Roo 无 fixture；Kilo 仅简化形状） | — | 依赖 Cline 消息体 schema | **BLOCKED**（Cline 族联动） |

### 0.2 五条关键判断

1. **fixtures 质量分层明显**：`atifact`（20 文件）与 `agent-sessions stage0`（43 文件，除 devin 逻辑投影、fx 伴生文件外）是**原生 schema 形状**（内容合成/裁剪，字段语义可信）；`sessionport`（15 文件）中 **8/15 是同一套简化 `{role,content}` 两行问答形状**，不能当各 harness 原生 schema 的证据（详见 §1.3）。
2. **`public-fixtures/` 里没有任何 SQLite 文件**（`find . -name '*.db' -o -name '*.sqlite*'` 为空）。因此 OpenCode 现版库、Copilot CLI `session-store.db`、Cursor IDE `state.vscdb`、Devin/Hermes 的 DB schema **本轮无法验证**；SQLite 类只能走「构造最小 golden DB（FIXTURE-CONSTRUCTED）」或下一轮真实安装采集。
3. **Writer 侧证据普遍弱于 Reader 侧**：除 Copilot 事件流/Gemini 单 JSON/Qwen JSONL/Aider Markdown 外，其余目标的「索引/DB 注册/目录命名」fixtures 均未覆盖 → Writer 一律只能承诺**格式级自往返（B3-F3）**，不能承诺原生发现/加载（B3-F4）。
4. **家族复用收益明确**：Gemini → Qwen Code（同源 parts/JSON 家族）；Claude Code 已有 adapter（批 1）→ Qwen 记录 envelope（`uuid/parentUuid/sessionId/message.parts`）可复用；pi 系（OMP 已有树状 adapter）→ `agent-sessions/stage0/pi/small.jsonl` 是现成同族新样本（低成本第 11 个，见 §2.2）。
5. **建议下一轮先做 5 个**：**Copilot CLI、Gemini CLI、Aider、Cursor CLI、Qwen Code**（fixtures 质量够 + 纯 JSON/JSONL/Markdown、零 SQLite 依赖 + Writer 可格式级交付）。OpenCode 作为「SQLite 专项」第 6 个单独立项。

### 0.3 与 `SOURCE.md` 的三处事实更正（以实际解析为准）

| # | SOURCE.md 表述 | 实测事实 |
|---|---|---|
| 1 | sessionport `gemini/session-abc.txt`（JSON） | **不是 JSON**：8 行文本，`## user`/`## model` 标题 + 正文，`json.load` 直接失败（文本渲染投影，非原生格式） |
| 2 | sessionport 15 个 harness fixture 代表各 harness 原生格式 | 实测 **8/15**（copilot/cursor/goose/grok/junie/kilo/vibe/windsurf）是**同一** `{"role","content"}` 两行问答简化形状，只能验证行级读取骨架 |
| 3 | 目录内 fixtures 为「原生 session 格式」 | 其中 `atifact/test-fixtures/*.har`（6 个）是 **provider HTTP wire-level 录制**、`vally-simple.json` 是合成 provider 流、`agent-sessions/stage0/devin/small.json` 是作者自述的 **SQLite 逻辑投影**、`fx/{session,checkpoint,display}.json` 是伴生文件 → 均**不是 session 原生落盘文件** |

---

## 1. fixtures 盘点

### 1.0 总览

| 指标 | 实测值 |
|---|---|
| 文件总数 | **82** = 78 个 fixture + `SOURCE.md` + 3 个 `LICENSES/*.txt` |
| 总字节 | **1,187,119 B**（≈1.19 MB；`SOURCE.md` 写 1.4 MB 有出入，以实测为准） |
| 来源仓库 | sessionport `173e47e2`（15 文件 3,783 B）、atifact `99f30101`（20 文件 50,647 B）、agent-sessions `8ca7aa60`（43 文件 / 1,122,764 B，其中 `codex/small.jsonl` 802,474 B、`claude/small.jsonl` 178,755 B 占 87%） |
| 许可证 | 全部 MIT（`LICENSES/` 附原文）；可入库、可二次分发 |
| 覆盖 harness/源 | sessionport 15、agent-sessions 18（含 DSH 14 文件）+ legacy 4、atifact 3 个 CLI（Claude Code/Codex/Copilot）+ 6 HAR + 1 合成流 |
| 缺失基础设施样本 | **无 `.db/.sqlite`、无 `.zst/.zstd`、无图片/附件实体**（本目录全部为纯文本 JSON/JSONL/MD/HAR） |

### 1.1 仓库 × 复制范围

| 仓库 | commit | License | 复制内容 | 覆盖 | 本批用途 |
|---|---|---|---|---|---|
| [sessionport](https://github.com/Reality-Shifting-Tech/sessionport) | `173e47e2` | MIT | `tests/fixtures/**` 15 文件 | claude-code, codex, cursor, gemini, opencode, copilot, grok, goose, junie, kilo, vibe, windsurf, cline, aider, openclaw | 路径/骨架参考；8 个为简化形状，**不作 schema 依据** |
| [atifact](https://github.com/waldekmastykarz/atifact) | `99f30101` | MIT | `test/fixtures/` 20 文件 | Claude Code×5、Codex CLI×2、**Copilot CLI×6**、provider HAR×6、vally 合成流×1 | **B3-01 Copilot CLI 的主证据**；HAR/vally 供未来 wire 层参考 |
| [agent-sessions](https://github.com/jazzyalex/agent-sessions) | `8ca7aa60` | MIT | `stage0/agents/<harness>/` 18 组 + DSH 14 + legacy 4 | antigravity, claude, cline, codex, copilot, cursor, devin, droid, fx, gemini, grok, hermes, kimi, openclaw, opencode, pi, qwen, deepseek-harness | **B3-02/03/04/05/07 的主证据**；其余为批 4 候选 |

### 1.2 逐 harness fixture 清单表

> 类型列：**S1** 原生 schema 形状-合成内容 / **S2** 简化通用形状 / **S3** 逻辑投影或渲染文本 / **S4** 中间或 wire 级格式。可信度 = 能否作为「该 harness 原生 schema 证据」：高/中/低/无。

#### 1.2.1 sessionport `tests-fixtures/`（每 harness 1 文件，共 15 文件 / 3,783 B）

| harness | 文件 | B | 类型 | 可信度 | 批 3 用途 |
|---|---|---|---|---|---|
| claude-code | `claude-code/9f9f9f9f-…jsonl` | 1055 | S1 | 中（含 tool_result/uuid/timestamp，schema 近原生） | 批 1 已覆盖，不重复 |
| codex | `codex/session-xyz.jsonl` | 670 | S1 | 中（`response_item/payload` 形状） | 批 1 已覆盖 |
| cline | `cline/tasks/t1.jsonl` | 117 | S2 | 低（仅 `type/content`） | B3-07 辅助 |
| gemini | `gemini/session-abc.txt` | 247 | **S3 文本** | **无**（非 JSON） | 仅作反例记录 |
| opencode | `opencode/storage/session/abc.json` | 255 | S2 | 低（`{id,parts}` 简化，parts 顺序也不标准） | B3-06 辅助 |
| aider | `aider/history/abc123.md` | 198 | **S1-M**（原生 Markdown 历史） | **高**（与 aider 真实 history 形状一致） | **B3-05 主证据** |
| copilot | `copilot/sessions/c1.jsonl` | 136 | S2 | **无**（真实 Copilot CLI 是事件流，见 atifact） | 不用 |
| cursor | `cursor/agent/session-1.jsonl` | 200 | S2 | 低（内容数组形态接近，但缺 turn_ended/时间） | B3-04 辅助 |
| goose | `goose/sessions/g1.jsonl` | 138 | S2 | **无** | B3-08 仅骨架 |
| kilocode | `kilo/sessions/k1.jsonl` | 132 | S2 | **无** | B3-10 仅骨架 |
| windsurf | `windsurf/sessions/s1.jsonl` | 115 | S2 | **无** | B3-09 仅骨架 |
| grok | `grok/sessions/gk1.jsonl` | 132 | S2 | **无** | 批 4 |
| junie | `junie/sessions/j1.jsonl` | 133 | S2 | **无** | 批 4 |
| vibe | `vibe/sessions/v1.jsonl` | 130 | S2 | **无** | 批 4 |
| openclaw | `openclaw/sessions/o1.jsonl` | 125 | S2 | 低（`type/content`） | 批 4 |

#### 1.2.2 agent-sessions `stage0/<harness>/`（18 组 / 43 文件，含 DSH 14）与 `legacy/`

| harness | 文件 | 数 | B | 类型 | 可信度 | 批 3 用途 |
|---|---|---|---|---|---|---|
| **copilot** | `small.jsonl` | 1 | 38,322 | S1 | **高**（61 行/33 类事件，`session.start`/`subagent`/`hook`/`shutdown` 全覆盖，内容裁剪） | **B3-01 补充证据** |
| **gemini** | `small.json` | 1 | 756 | S1 | **高**（`kind/startTime/projectHash/sessionId/messages[]` 原生形状） | **B3-02 主证据** |
| **qwen** | `019f0000-…0002.jsonl`, `019f0000…0003.jsonl` | 2 | 750 | S1 | 中（record envelope 可信，但**每文件仅 1 行 user**；一例故意 sessionId 不匹配文件名，一例紧凑 ID） | **B3-03 主证据（envelope 级）** |
| **cursor** | `small.jsonl` | 1 | 497 | S1 | 中高（role/message.content + `turn_ended` 状态行，无时间戳） | **B3-04 主证据（新代）** |
| **cline** | `cline-desktop-continued.json`, `session_…fixt1.json` | 2 | 2,592 | S1 | 中（session metadata v1 真实形状；`messages_path` 文件**未随附**） | **B3-07 主证据（metadata 级）** |
| **opencode** | `001.json`, `002.json` | 2 | 167 | S1 | 中（part 行真实形状 `{id,type,text,time}`，缺 message/session 关联字段） | **B3-06 主证据（part 级）** |
| **pi** | `small.jsonl` | 1 | 5,071 | S1 | 高（树状事件 `session/model_change/message/parentId`，15 行） | 批 3 备选（OMP 家族复用） |
| **kimi** | `small.jsonl` | 1 | 20,817 | S1 | 中高（Kimi Code 事件流 50 行 `metadata/config.update/turn.prompt/...`） | 批 4 |
| **grok** | `chat_history.jsonl`, `summary.json` | 2 | 1,774 | S1 + S3 | 中（chat 记录近原生；summary 是伴生索引） | 批 4 |
| **hermes** | `small.json` | 1 | 472 | S1 | 中（SQLite 表的逻辑投影 JSON，作者未声称物理格式） | 批 4（需 DB 证据） |
| **devin** | `small.json` | 1 | 1,880 | **S3 逻辑投影** | 中（作者明说 SQLite 逻辑投影，`_fixture` 字段自述） | 批 4（需 DB 证据） |
| **fx** | `session.json`, `checkpoint.json`, `display.json` | 3 | 1,293 | S3 伴生/事件日志 | 中（`schema_version:3 / event_log_v1`；`checkpoint.json` **json.load 失败**，含非法控制字符 → 当坏样本用） | 批 4 |
| **droid** | `stream_json_small.jsonl`, `session_store_schema_drift.jsonl` | 2 | 1,012 | S1 | 中（stream-json 事件流 + schema drift 两代） | 批 4 |
| **antigravity** | `desktop_small.jsonl`, `cli_schema_drift.jsonl` | 2 | 2,670 | S1 | 中（JSONL step 记录；`.pb`/SQLite 原生未覆盖） | 批 4（catalog 定 P2） |
| **openclaw** | `small.jsonl` | 1 | 1,556 | S1 | 中高（树状事件 `session/model_change/message/parentId/toolCall`） | 批 4 |
| **claude** | `small.jsonl` | 1 | 178,755 | S1 | 高（Claude Code 真实 CLI 事件，含大量私有类型） | 批 1 已覆盖 |
| **codex** | `small.jsonl` | 1 | 802,474 | S1 | 高（rollout 全量事件） | 批 1 已覆盖 |
| **deepseek-harness** | 14 文件（v0-v4/schema drift/坏 tail/未知事件/manifest/normalized） | 14 | 59,339 | S1 | 高（DSH 官方格式验证 fixture 全套） | 批 1 已覆盖 |
| legacy | `codex_052_raw.jsonl`, `session_simple.jsonl` | 2 | 1,189 | S1 / **S4 归一** | codex 中 / session_simple 低 | 批 1 Codex 历史版本参考 |
| legacy/Cursor | `test-session.jsonl`, `subagent-session.jsonl` | 2 | 1,378 | S1（**legacy 代**） | 中高（`role`+`message.content[text/tool_use]`，无 `turn_ended`、无时间戳） | **B3-04 主证据（旧代）** |

#### 1.2.3 atifact `test-fixtures/`（20 文件 / 50,647 B）

| 分组 | 文件 | 数 | B | 类型 | 可信度 | 批 3 用途 |
|---|---|---|---|---|---|---|
| Copilot CLI | `copilot-cli-{simple,subagent,mcp-skills,no-result,no-tools-updated,shutdown}.jsonl` | 6 | 17,270 | S1 | **高**（事件流 6 种边界场景） | **B3-01 主证据** |
| Claude Code | `claude-code-{simple,subagent,no-init,cache-creation,rate-limit-prefix}.jsonl` | 5 | 6,754 | S1 | 高（CLI stream-json 输出，非 session store） | 批 1 边界参考 |
| Codex CLI | `codex-cli-{simple,subagent}.jsonl` | 2 | 8,999 | S1 | 高（CLI stream-json 输出） | 批 1 边界参考 |
| provider HAR | `har-{anthropic,anthropic-thinking,anthropic-multiturn,openai-chat,openai-chat-tools,openai-responses}.har` | 6 | 14,314 | **S4 wire 级** | 高（HTTP 请求/响应录制） | 不属于 session 存储；未来 wire 采集层参考 |
| 合成 provider 流 | `vally-simple.json` | 1 | 3,310 | S4 中间格式 | — | 仅参考 |

### 1.3 可信度分级与「能否作为 schema 证据」判定

| 级别 | 判定标准 | 命中 fixtures | 用法 |
|---|---|---|---|
| **S1 原生形状** | 字段名/层级与该 harness 真实落盘一致（内容可合成/裁剪） | atifact CLI×13、agent-sessions stage0 除 devin/fx 外、legacy/Cursor、sessionport 的 claude-code/codex | **可写 Reader/Writer schema** |
| **S2 简化通用形状** | `{"role":"user/assistant","content":"..."}` 两行问答；与真实 schema 无对应 | sessionport 的 copilot/cursor/goose/grok/junie/kilo/vibe/windsurf（8 个完全同形） | 只可验证「行级读取 + 角色提取」骨架，**不能据此宣称 Reader 实现** |
| **S3 渲染/伴生/投影** | Markdown 渲染文本、summary 索引、逻辑投影、伴生 checkpoint | sessionport gemini（文本）、agent-sessions devin（逻辑投影）/grok summary/fx 伴生、aider markdown（**这是原生格式本身**，单独标 S1-M） | 视具体用途；devin 不能当 SQLite 物理 schema |
| **S4 中间/wire 级** | HAR、合成 provider 流、归一化 session_simple | atifact HAR×6、vally、legacy/session_simple | 不用于 session 原生 schema 证据 |

> **教训（下一轮采集/使用 fixture 必须遵守）**：同名目录/单一小文件 ≠ 原生 schema 证据。使用前必须核对字段名、层级与来源仓库实现（`SOURCE.md` 只证明来源与 commit，不证明快照是原生格式）。

### 1.4 覆盖矩阵：批 3 目标 × 可用能力

| 目标 | 读（Reader） | 写（Writer） | 工具配对样本 | 时间戳样本 | cwd/标题样本 | 结论 |
|---|---|---|---|---|---|---|
| Copilot CLI | ✅ 事件流 | 🟡 事件流 | ✅ 完整 | ✅ | ✅ `session.start.context.cwd` | 可实施 |
| Gemini CLI | ✅ 单 JSON | ✅ 单 JSON | ❌（无 toolCalls 记录） | ✅ | ❌ cwd 靠 projectHash 反查 | 可实施（工具分支未验证） |
| Qwen Code | 🟡 envelope | ✅ JSONL | ❌ | ✅ | ✅ cwd/version/gitBranch | 可实施（envelope 级） |
| Cursor CLI | ✅ 两代 JSONL | 🟡 transcript | ❌（无 tool_result） | ❌ | ❌（无 cwd） | 可实施（有损大） |
| Aider | ✅ Markdown | ✅ Markdown | ❌（历史不记录工具） | ❌ | ❌ | 可实施（纯文本通道） |
| OpenCode | 🟡 part only | ❌ 无 DB schema | ❌ | ✅ part.time.start | ❌ | 需补 SQLite 证据 |
| Cline | 🟡 metadata only | 🟡 双文件但消息体缺 | ❌ | ✅ | ✅ cwd/workspace_root | 半阻塞 |
| Goose | ❌ 仅简化 | ❌ 无依据 | ❌ | ❌ | ❌ | 需补真实样本 |
| Windsurf | ❌ 无 | ❌ 无 | ❌ | ❌ | ❌ | BLOCKED |
| Roo/Kilo | ❌ 无 | ❌ 无 | ❌ | ❌ | ❌ | BLOCKED |

### 1.5 关键缺口清单（下一轮补采/构造的输入）

| # | 缺口 | 影响 | 建议补法 |
|---|---|---|---|
| G1 | `public-fixtures/` **无 SQLite 文件** | OpenCode 现版库、Copilot `session-store.db`、Cursor IDE `state.vscdb`、Devin/Hermes DB 全部不可验证 | ① 真实安装后采集只读副本；② 按 harness-catalog **C** 的 schema 用 `sqlite3` 构造最小 golden（FIXTURE-CONSTRUCTED，只读打开验证） |
| G2 | Cline **messages 文件缺失**（metadata `messages_path` 指向不存在路径，`os.path.exists=False`） | 无法验证 Cline 消息体 schema（只支持 `say/ask` 两型记录） | 安装 Cline CLI 采 1 条真实会话，或从 Cline 开源仓库取 schema |
| G3 | Gemini fixture **无 `toolCalls[]`** | Gemini 工具调用/结果分支无法做 fixture 验证（只验证文本/thoughts/tokens） | 补真实 gemini session（含函数调用），或按 **C** 的 schema 自构 2 条记录 |
| G4 | Qwen fixture **每文件仅 1 行 user** | 无法验证 assistant/tool/usage/整条会话 | 补真实 Qwen 会话（catalog **E** 已验 0.14.3），或自构 5 行 golden |
| G5 | OpenCode fixture **仅 part 行** | 缺 `messageID/sessionID` 关联、缺 message/session schema | 补真实 `opencode.db` 只读副本 |
| G6 | Goose/Windsurf/Roo/Kilo 只有 **S2 简化样本** | 真实路径与 schema 均未核实 | 安装采集；或按 catalog **C/D** 的路径表 + 真实仓库源码实现（本轮素材不足） |
| G7 | `fx/checkpoint.json` 是**坏 JSON**（`json.load` 第 8 行第 45 列非法控制字符） | 只能当容错坏样本 | 保留作 reader 容错测试输入（预期 warnings 而非崩溃） |
| G8 | sessionport gemini `.txt` 非 JSON、sessionport 8 个 S2 | 已在 §0.3/§1.3 更正 | 使用 fixture 前先做 JSON 可解析性 + 形状核对 |

---

## 2. 批 3 目标与难度排序

### 2.1 建议顺位（含依赖）

| 顺位 | ID | Harness | 难度 | 关键依赖 | 交付物 | 上限证据 |
|---|---|---|---|---|---|---|
| 1 | B3-01 | **GitHub Copilot CLI** | ★★ | 无（JSONL 事件流直读） | reader + writer(events) + 6 用例 | FIXTURE |
| 2 | B3-02 | **Gemini CLI** | ★★ | 无 | reader + writer(JSON) + 2 用例 | FIXTURE |
| 3 | B3-03 | **Aider** | ★ | 无（Markdown） | reader + writer(MD) + 2 用例 | FIXTURE |
| 4 | B3-04 | **Cursor CLI** | ★★☆ | 无 | reader + writer(JSONL) + 3 用例 | FIXTURE |
| 5 | B3-05 | **Qwen Code** | ★★☆ | 复用 Gemini/Claude 家族经验（非代码强依赖） | reader + writer(JSONL) + 3 用例 | FIXTURE |
| 6 | B3-06 | **OpenCode** | ★★★ | **SQLite 层 + 构造 golden DB** | reader(part) + SQLite 专项 | FIXTURE / FIXTURE-CONSTRUCTED |
| 7 | B3-07 | **Cline** | ★★★ | Cline 消息体样本（G2） | metadata reader 先落地 | FIXTURE（metadata 级） |
| 8 | B3-08 | **Goose** | ★★★☆ | 真实样本（G6） | 仅骨架 reading | FIXTURE-LOW |
| 9 | B3-09 | **Windsurf** | — | 真实样本 + 路径（G6） | 不做 | BLOCKED |
| 10 | B3-10 | **Roo/Kilo** | — | Cline 消息体 schema + 真实路径（G2/G6） | 不做 | BLOCKED |

> 注：B3 编号按 Lead 任务列表顺序语义分组（Copilot/Gemini/Qwen/Cursor/Aider 在前），**实施顺位以上表「顺位」列为准**（Aider 最简单可提前）。

### 2.2 低成本加项（不占 10 个名额，建议顺手做）

| ID | Harness | fixture | 理由 |
|---|---|---|---|
| B3-11 | **Pi（pi.dev）** | `agent-sessions/stage0/pi/small.jsonl`（5,071 B，15 行树状事件） | 与 OMP（批 1 已有树状 adapter）**同格式族**，改 profile 即可复用；`session/model_change/message/parentId` 树 walker 已存在 |
| B3-12 | **Hermes** | `agent-sessions/stage0/hermes/small.json`（逻辑投影） | 只在拿到真实 `state.db` 后才做（G1）；否则不做，避免把逻辑投影当物理 schema |

---

## 3. 逐 harness 方案

> 每节格式：原生存储事实 → fixture 解析验证（字段表 + ≤300 字符截断示例）→ Reader 映射规则 → Writer 最小可行 → 测试计划 → 已知有损项。
> 示例均为 fixture 原文截断（`…` 表示截断），不是真实用户会话。

### B3-01 GitHub Copilot CLI（难度 ★★｜上限 FIXTURE）

**原生存储事实**（证据：harness-catalog **C** 完整 schema + atifact **I** 已有 Copilot CLI→ATIF 实现 + **E**）：CLI 事件流持久化在 `~/.copilot/session-state/<uuid>/`（据 **C** 该目录 + atifact **I** 解析 JSONL 事件流推断为 `<uuid>/` 下一份事件 JSONL，**具体文件名未核实**），另 `~/.copilot/session-store.db`（SQLite：sessions/turns/checkpoints/`assistant_usage_events` + FTS5）作索引/查询。**本轮 fixtures 只覆盖事件 JSONL 侧，SQLite 侧无样本（G1）**。

**fixture**：`atifact/test-fixtures/copilot-cli-*.jsonl`（6 个，主证据）+ `agent-sessions/stage0/copilot/small.jsonl`（33 类事件大样本）。全部用 `python3 json.loads` 逐行解析通过。

**字段表（事件 envelope）**

| 字段 | 类型 | 示例/取值 | IR 用途 | 备注 |
|---|---|---|---|---|
| `type` | str | `session.start` / `user.message` / `assistant.message` / `tool.execution_complete` / `result` | 事件分派 | 见下表事件清单 |
| `data` | obj | 事件负载 | 各类型字段 | 全部业务字段在 `data` 内 |
| `id` / `parentId` | str | `evt-007` / `evt-004` | provenance、线性化校验 | 裁剪样本中有 `"[trimmed for fixture]"`，**不能依赖父链完整** |
| `timestamp` | ISO8601 | `2026-03-27T14:42:15.415Z` | `ts`（→epoch ms） | 缺 timestamp 时用前一条+0 并记 warning |
| `sessionId` | str | 仅 `result` 事件携带 | `source_session_id` | `session.start.data.sessionId` 也携带 |
| `ephemeral` | bool | `true` | 过滤 | 增量/瞬态事件：`*_delta`、`tools_updated`、`mcp/skills_loaded` 等 |
| `exitCode` / `usage` | int/obj | `0` / `{premiumRequests,totalApiDurationMs,sessionDurationMs,codeChanges}` | `stats`/退出状态 | 来自 `result` 事件 |

**事件清单（7 个 Copilot fixtures 的并集实测覆盖 40 种事件类型，下表按 IR 相关性分组）**

| 事件 type | data 关键字段 | IR 映射 |
|---|---|---|
| `session.start` | `sessionId,version,copilotVersion,startTime,selectedModel,context{cwd,gitRoot,repository,branch,headCommit,hostType}` | session 元数据（cwd/model/created_at） |
| `user.message` | `content,transformedContent,attachments,interactionId` | `user_message`（text=content；attachments→image 或 lossy） |
| `assistant.turn_start/end` | `turnId,interactionId` | 仅顺序参考（不产生 IR 事件） |
| `assistant.reasoning` / `reasoning_delta` | `reasoningId,content/deltaContent` | reasoning block（delta 仅在无最终 reasoning 时兜底） |
| `assistant.message` | `messageId,content,toolRequests[{toolCallId,name,arguments,type,intentionSummary}],reasoningText,outputTokens,model?,parentToolCallId?` | `assistant_message` + `tool-call` blocks；reasoningText→reasoning |
| `assistant.message_delta` | `messageId,deltaContent` | 兜底合并（当 `assistant.message.content==""` 时，见 simple/mcp-skills） |
| `tool.execution_start` | `toolCallId,toolName,arguments,parentToolCallId?` | 仅起止上下文（不单独成 IR 事件） |
| `tool.execution_complete` | `toolCallId,success,result{content,detailedContent},model,parentToolCallId?` | `tool_result`（call_id=toolCallId，is_error=!success） |
| `session.tools_updated` / `model_change` | `model` / `newModel,previousModel,...` | model 元数据（后者来自 agent-sessions）；前者 ephemeral |
| `session.shutdown` | `shutdownType,currentModel,totalPremiumRequests,modelMetrics{...},currentTokens,...` | `stats`/attempt 汇总（可丢失） |
| `result` | `sessionId,exitCode,usage{...}` | 会话结束状态 + usage |
| `session.resume/info/error/usage_checkpoint/usage_record/truncation/auto_mode_resolved`、`subagent.started/completed`、`hook.start`、`abort`、`model.*`、`system.message/notification`、`session.mcp_*`、`session.skills_loaded` | 见 agent-sessions 样本 | 进 `warnings`/`lossy`；`abort`→`turn_abort`；`hook.start` 含 toolResult 可辅助配对（不建议主用） |

**截断示例（simple 第 8/10 行，各 ≤300 字符）**

```json
{"type":"assistant.message","data":{"messageId":"msg-001","content":"","toolRequests":[{"toolCallId":"tooluse_abc123","name":"bash","arguments":{"command":"ls -la"},"type":"function","intentionSummary":"List files"}]…}
```
```json
{"type":"tool.execution_complete","data":{"toolCallId":"tooluse_abc123","model":"claude-sonnet-4.6","success":true,"result":{"content":"README.md\npackage.json\nsrc/","detailedContent":"…"}},…}
```

**Reader 映射规则**

1. **行序权威**：按文件行序线性化（事件流的持久化顺序），`parentId` 仅用于一致性校验/子代理归属；不得按 timestamp 重排。
2. **折叠瞬态**：先收集全部事件，再按 `messageId` 合并：最终 `assistant.message` 优先；若其 `content==""` 且存在同 `messageId` 的 `assistant.message_delta`，按行序拼接 delta（记 `lossy:copilot:delta-merge`）。`ephemeral:true` 事件默认不进 IR。
3. **工具配对**：`toolRequests[].toolCallId` → tool-call；`tool.execution_complete` → tool_result。fixture 中存在**只有 complete 没有 start**（shutdown）与**有 request 无 complete**（agent-sessions 裁剪样本 7 requests vs 3 starts/4 completes）→ Reader 容错：缺失 start 仍产出 result；缺失 result 由 Writer 补占位（协议 §4 约束 1）。
4. **arguments 双形态**：`arguments` 可能是 JSON **对象**（atifact）或 JSON **字符串**（agent-sessions 的 `"{\"command\":\"ls\"}"`）→ reader 统一 `json.loads` 字符串形态，失败则 `{"_raw": str}` + warning。
5. **子代理**：`parentToolCallId` 非空（实测 subagent fixture 4 个事件）→ 归入父 tool-call 的 `extra.subagents[]`；IR/ATIF 第一版不展开，记 `lossy:copilot:subagent-collapsed`。
6. **会话元数据**：`session.start.context.cwd`→`cwd`；`selectedModel`/`session.tools_updated.model`→model；startTime→created_at；`result.usage`→stats。缺失 `session.start`（simple/mcp-skills/shutdown 均无）→ `cwd=None`+warning，writer 需 `--target-cwd`。
7. **未知事件**：不抛错，进 `warnings`（协议 §4.5），例如 `model.*`、`hook.start`、`session.mcp_server_status_changed`。

**Writer 最小可行**

- 产物：`<out>/session-state/<uuid>/events.jsonl`，行序 = IR 事件序：`session.start`（写 cwd/model/startTime）→ 每个 turn `assistant.turn_start` + `user.message` / `assistant.message`（含 toolRequests）/`tool.execution_start/complete` → 末尾 `result`（sessionId/exitCode/usage）。
- `assistant.message.toolRequests[].arguments` 写 **JSON 对象**（atifact 形态，主样本）。
- 工具结果缺失时生成 `tool.execution_complete` 占位（success=false + `lossy`）。
- **不写** `session-store.db`（schema 无 fixture 依据）→ **原生 `--resume` 发现未知，只能承诺格式级自往返**。
- 输出目录 `<out>/` 结构与真实布局同形，可整体 `--install` 拷贝（默认关闭，协议 §6）。

**测试计划（期望值均来自 python3 实测）**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| CP-F1 | `copilot-cli-simple.jsonl` | 19 行/14 类事件；user_message=1、assistant_message=2；tool-call=1 且 tool_result=1 配对；缺 `session.start` → warnings 含 `missing-session-start`；`result.sessionId=session-xyz-789`、exitCode=0、premiumRequests=1；`content==""` 的两条 assistant 消息由 delta 合并后非空 | FIXTURE（B3-F1/F2） |
| CP-F2 | `copilot-cli-subagent.jsonl` | 17 行；user=1、assistant.message=4；toolRequests=3 = starts=3 = completes=3 全配对；`parentToolCallId` 事件=4 → `extra.subagents` 非空 + lossy；`session.start.context.cwd="/home/user/project"` | FIXTURE |
| CP-F3 | `copilot-cli-shutdown.jsonl` | 7 行；toolRequests=1 但 `tool.execution_start=0`、complete=1 → 仍产出 1 条 tool_result（不崩溃）；`session.shutdown.modelMetrics` 进 stats/extra；exitCode=0 | FIXTURE |
| CP-F4 | `copilot-cli-no-result.jsonl` | 6 行；无 `result` → 会话仍可读（1 user+1 assistant），`updated_at` 取最后事件 ts，warning 含 `missing-result` | FIXTURE |
| CP-F5 | `copilot-cli-mcp-skills.jsonl` | 11 行；`session.mcp_servers_loaded`/`skills_loaded` 进 lossy；唯一 `assistant.message.content==""` 由 1 条 delta 合并；无工具调用断言 0/0 | FIXTURE |
| CP-F6 | `agent-sessions/stage0/copilot/small.jsonl` | 61 行/33 类事件全部解析无异常；user=5、assistant.message=9、toolRequests=7 / start=3 / complete=4（其中 6 个 id 被裁剪为 `[trimmed for fixture]`）→ 必须容错不崩溃：裁剪 id 记 warning `copilot:tool-id-trimmed` 并生成稳定占位 id，IR 中**每个 tool-call 恰有 1 条 tool_result**（占位或真实），tool_result 总数=7；`subagent.started/completed`、`session.resume`、`abort` → warnings/`turn_aborts` | FIXTURE |
| CP-F7（写） | IR ← CP-F2/Copilot | 写 events.jsonl → 用本 reader 读回：user≥1、tool-call=3 且每个都有 result（真实或占位）、cwd/model 一致、assistant 文本非空 ≥1 → B3-F3 自往返；子代理折叠信息在 lossy | FIXTURE |

**已知有损项**：delta 合并不保证与原文逐字一致；`hooks`/`model.*`/`mcp/skills` 事件丢弃；attachments 仅保留路径；`assistant_usage_events` 级 token/时延明细（DB）不迁移；子代理折叠；`ephemeral` 顺序信息丢失；sessionId 仅在 result/start，缺失时需生成。

---

### B3-02 Gemini CLI（难度 ★★｜上限 FIXTURE）

**原生存储事实**（证据：harness-catalog **C** 完整 schema + **D** fixture + Harbor RFC 真实 gemini-cli 轨迹 **H**）：单会话单文件 `~/.gemini/tmp/<sha256(project)>/chats/session-<ISO>-<short>.json`，结构 `{sessionId, projectHash, startTime, lastUpdated, messages[]}`；`~/.gemini/history/<slug>/.project_root` 提供 hash→cwd 反查。**P0**。

**fixture**：`agent-sessions/stage0/gemini/small.json`（756 B，`json.load` 通过，2 条消息）。**另** `sessionport/tests-fixtures/gemini/session-abc.txt` 是 `## user`/`## model` 文本渲染，**不是 JSON、不作证据**（§0.3#1）。

**字段表**

| 字段路径 | 类型 | fixture 实测值/示例 | IR 用途 |
|---|---|---|---|
| `kind` | str | `"chat"` | 格式识别（≠chat 则 warning） |
| `sessionId` | str | `"session-2026-01-16T18-34-3739ef95"` | `source_session_id` |
| `projectHash` | sha256 hex(64) | `0b7dfb12…e9c9` | cwd 反查键（用 `history/<slug>/.project_root`） |
| `startTime` / `lastUpdated` | ISO8601 | `2026-01-16T18:34:00.000Z` / `…10.000Z` | created_at/updated_at |
| `messages[].id` | str | `m1` / `m2` | source_id |
| `messages[].timestamp` | ISO8601 | `2026-01-16T18:34:01.000Z` | ts |
| `messages[].type` | str | `"user"` / `"gemini"` | 事件类型（gemini→assistant） |
| `messages[].content` | str | `"Hello"` / `"Hi!"` | text block |
| `messages[].displayContent` | str | `"Hello"` | 忽略（lossy，UI 用） |
| `messages[].model` | str | `"gemini-3-flash-preview"` | model |
| `messages[].tokens` | obj | `{input:10,output:5,total:15,thoughts:0,tool:0,cached:0}` | usage/metrics |
| `messages[].thoughts[]` | obj[] | `[{"description":"Short reasoning placeholder."}]` | reasoning block |
| `messages[].toolCalls[]` | obj[] | **fixture 无**（G3） | tool-call/tool_result（需按 C/F 实现） |

**截断示例（原文 756 B，去空白并省略 timestamp 等字段，≤300 字符）**

```json
{"kind":"chat","sessionId":"session-2026-01-16T18-34-3739ef95","messages":[{"id":"m1","type":"user","content":"Hello"},{"id":"m2","type":"gemini","model":"gemini-3-flash-preview","tokens":{"input":10,…},"thoughts":[{"description":"Short reasoning placeholder."}],"content":"Hi!"}]}
```

**Reader 映射规则**

1. 单文件 `json.load`；`kind!="chat"` 时仍尝试按 messages 读并 warning。
2. `type=="user"`→`user_message`；`type=="gemini"`（及 `"model"` 别名）→`assistant_message`：`content`→text，`thoughts[].description` 按序拼接→reasoning（多块可合并，`lossy:gemini:thoughts-merged`），`tokens`→usage（thoughts/tool/cached 进 extra）。
3. `toolCalls[]`（真实 schema，fixture 缺）：每个 `{id,name,args,result/…}` → tool-call + 对应 tool_result；实现时按 C/F 字段名做**宽松多键探测**（`id/toolCallId`、`args/arguments/input`、`result/output`），并标 `lossy:gemini:toolcalls-schema-unverified`，因为本轮无 fixture 可验证。
4. `cwd`：fixture 无 cwd → 读 `~/.gemini/history/<projectHash 反查>/…` 得 project root；取不到则 `cwd=None`+warning `gemini:cwd-unresolved`（writer 必须要求 `--target-cwd`）。
5. `title`：Gemini 会话无标题字段 → 取首条 user `content` 前 80 字符（或 `session-<id>`），标 `lossy:gemini:title-derived`。
6. 顺序按 messages 数组；时间缺失时置 0+warning。

**Writer 最小可行**

- 产物：`<out>/tmp/<sha256(abs cwd)>/chats/session-<ISO-compact>-<short6>.json`，字段按上表逆映射（`kind:"chat"`、`projectHash`、`startTime/lastUpdated`、`messages[]`）。
- `projectHash = sha256(<cwd>)`（hash 输入形式——绝对路径/realpath/是否含尾斜杠——**未核实**，需下一轮用真实 Gemini 安装对照；writer 提供 `--project-hash` 覆盖）。
- 无索引文件（目录扫描发现会话）→ 可尝试原生 `gemini --resume` 但**未验证**；本轮只承诺 B3-F3 自往返。
- 工具调用写入 `toolCalls[]`（按真实 schema，需真实样本可用后回填验证）。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| GEM-F1 | `gemini/small.json` | 2 条消息、角色序 `[user, assistant]`；model=`gemini-3-flash-preview`；usage input=10/output=5/total=15；reasoning 1 块文本 `"Short reasoning placeholder."`；created_at≈`2026-01-16T18:34:00Z`；sessionId 原样保留 | FIXTURE（B3-F1/F2） |
| GEM-F2 | 同上 | `cwd` 未解析 → warnings 含 `gemini:cwd-unresolved`；`title` 派生非空；`projectHash` 保留进 `extra` | FIXTURE |
| GEM-F3（写） | IR（GEM-F1） | 写 JSON → 文件名匹配 `session-<ISO>-<short>.json` → 本 reader 读回 2 条、文本/角色/tokens 一致 | FIXTURE（B3-F3） |
| GEM-F4（工具） | **自构** 2 条含 `toolCalls` 的 JSON（FIXTURE-CONSTRUCTED） | tool-call=1、tool_result=1、配对成功；`lossy` 含 `toolcalls-schema-unverified` | FIXTURE-CONSTRUCTED |

**已知有损项**：`displayContent` 丢弃；thoughts 多块合并；无 cwd/标题；toolCalls 未经 fixture 验证；无分支/子代理；`tool/output` token 统计部分进 extra。

---

### B3-03 Qwen Code（难度 ★★☆｜上限 FIXTURE）

**原生存储事实**（证据：harness-catalog **C** 完整 schema + **E** 验证过 0.14.3）：`~/.qwen/projects/<enc-cwd>/chats/<uuid>.jsonl`；另有旧存储 `tmp/<sha256>/logs.json`、`todos/<sid>.json`。Qwen Code 是 **Gemini CLI fork**（C 明确），但本 fixture 记录 envelope 更接近 **Claude Code JSONL**（`uuid/parentUuid/sessionId/message.parts`）——两者都要按「宽松多形态」处理。**P1**。

**fixture**：`agent-sessions/stage0/qwen/` 2 文件，各 **1 行**（仅 user 记录，G4）：
- `019f0000-0000-7000-8000-000000000002.jsonl`：**故意**让记录 `sessionId=…0099` 与文件名 `…0002` 不一致（负样本）。
- `019f0000000070008000000000000003.jsonl`：紧凑 ID（无连字符）文件名，记录 `sessionId` 一致（正样本，含 `gitBranch`/`systemPayload`）。

**字段表（记录 envelope）**

| 字段 | 类型 | fixture 实测 | IR 用途 |
|---|---|---|---|
| `uuid` | str | `019f0000-0000-7000-8000-000000000021` | source_id |
| `parentUuid` | str/null | `null` | 分支链（线性化按行序，分支信息进 extra） |
| `sessionId` | str | `…0099`（负样本）/ `…0003` | `source_session_id`（**记录优先于文件名**，不匹配记 warning） |
| `timestamp` | ISO8601 | `2026-08-17T12:00:00.000Z` | ts |
| `type` | str | `"user"`（另有 `assistant`/`tool_result` 等，fixture 未覆盖） | 事件类型 |
| `cwd` | str | `/tmp/as-qwen-fixture/compact-project` | cwd |
| `version` | str | `"0.21.13"` | agent.version |
| `gitBranch` | str | `"fixture-branch"` | extra |
| `systemPayload.displayText` | str | `"Inspect a compact-ID synthetic fixture."` | system_message 或 extra（默认 extra+warning） |
| `message.role` | str | `"user"` | 角色 |
| `message.parts[]` | obj[] | `[{"text":"…"}]` | text/reasoning/tool（真实 schema 可能为 Gemini 风格 `functionCall/functionResponse`——未核实，G3 同源风险） |

**截断示例（正样本整行，节选：省略 `parentUuid/systemPayload/gitBranch`，≤300 字符）**

```json
{"uuid":"019f0000-…-000033","sessionId":"019f0000000070008000000000000003","timestamp":"2026-08-17T12:30:00.000Z","type":"user","cwd":"/tmp/as-qwen-fixture/compact-project","version":"0.21.13","message":{"role":"user","parts":[{"text":"Inspect a compact-ID synthetic fixture."}]}}
```

**Reader 映射规则**

1. JSONL 逐行；坏行跳过+计数（协议 §4.5）。
2. `type` 归一：`user`→user_message；`assistant`/`model`/`gemini`→assistant_message（`message.parts` 中 `{text}`→text、`{thinking|reasoning}`→reasoning、`{functionCall|toolCall}`→tool-call、`{functionResponse|toolResult}`→tool_result）；`tool_result` 独立行→tool_result（call_id 从 `toolUseId/tool_call_id` 宽松探测）。
3. **sessionId 决策**：以记录字段为准；文件名与记录不一致 → warning `qwen:session-id-mismatch`，并在 extra 保留两者；文件名紧凑格式（无 `-`）与记录格式互转（`019f0000000070008000000000000003` ↔ `019f0000-…-0003`）→ 视为同一 ID（记录规范形式优先）。
4. `parentUuid` 树：按行序线性输出；若出现 parentUuid 指向非上一条（真分支）→ `warnings` + `extra.branch_points`（`lossy:qwen:branch-linearized`）。
5. `systemPayload.displayText`→`system_message`（`--keep-system` 时）否则 extra+warning。
6. 无 `cwd` 记录时 `cwd=None`；usage 未在 fixture 出现，若真实记录带 `tokens` 按 Gemini 风格映射。

**Writer 最小可行**

- 产物：`<out>/projects/<enc-cwd>/chats/<uuid>.jsonl`，每事件一行，记录含 `uuid/parentUuid/sessionId/timestamp/type/cwd/version/message{role,parts}`。
- `<enc-cwd>` 编码规则**未核实**（catalog 只写 `<enc-cwd>`）：默认用「cwd 的 `/`→`-`」并允许 `--dir-name` 覆盖（Claude 风格；Gemini 风格是 sha256，两者都不能确证）。
- 写 `parentUuid` 线性链；无索引 → 格式级（`--resume` 发现未验证）。
- 目录/文件权限 600/700。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| QW-F1 | `…0002.jsonl`（负样本） | 1 条 user；`uuid`/`cwd`/`version=0.21.13` 保留；记录 sessionId=`…0099` 与文件名不一致 → warning `qwen:session-id-mismatch`，IR `source_session_id` 用记录值 | FIXTURE（B3-F1/F2） |
| QW-F2 | `…0003.jsonl`（正样本） | sessionId 一致；`gitBranch` 进 extra；`systemPayload` 不丢失（extra 或 system_message）；文本精确等于 `"Inspect a compact-ID synthetic fixture."` | FIXTURE |
| QW-F3（写） | IR（QW-F2） | 写 JSONL → 读回 1 条 user、uuid/sessionId/cwd/version 一致 → B3-F3；文件名使用记录 sessionId 规范形式 | FIXTURE（B3-F3） |
| QW-F4（多记录） | **自构** 5 行（user/assistant/tool_result，FIXTURE-CONSTRUCTED） | 角色序、tool 配对、`parts` 多类型映射、parentUuid 链 | FIXTURE-CONSTRUCTED |

**已知有损项**：无 assistant/tool/usage 的真实 fixture → 工具分支仅构造验证；`<enc-cwd>` 与文件命名规则未核实；分支线性化；`systemPayload` 语义不确定；旧存储 `logs.json/todos` 不迁移。

---

### B3-04 Cursor CLI（难度 ★★☆｜上限 FIXTURE）

**原生存储事实**（证据：harness-catalog **C** 完整 schema + **B** + **D**）：CLI `~/.cursor/projects/<slug>/agent-transcripts/<sid>/<sid>.jsonl`；IDE 侧 `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`（SQLite KV：`composerData/bubbleId` 等，**本轮无样本**）。只做 CLI 侧；IDE 明确标注不支持。

**fixture**：两代 schema 各 2 个（S1）：
- **新代（current）** `agent-sessions/stage0/cursor/small.jsonl`（6 行）：`role` 行 + `type:"turn_ended"` 状态行。
- **旧代（legacy）** `agent-sessions/legacy/Cursor/{test-session,subagent-session}.jsonl`（6/3 行）：只有 `role` 行、`<user_query>` 包裹 prompt；无 `turn_ended`、无时间戳。
- `sessionport/tests-fixtures/cursor/agent/session-1.jsonl`：S2 简化，仅作骨架参考。

**字段表**

| 行类型 | 字段 | 类型/示例 | IR 用途 |
|---|---|---|---|
| 消息行 | `role` | `"user"` / `"assistant"` | 角色 |
| 消息行 | `message.content[]` | `[{"type":"text","text":"List the files."}]` | text block |
| 消息行 | `message.content[]` | `[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]` | tool-call（**无原生 id 字段**→ reader 生成 `cursor:<n>`） |
| 状态行 | `type` | `"turn_ended"` | 轮次结束 |
| 状态行 | `status` | `"success"` / `"error"` | error→`turn_abort`/warning |
| 状态行 | `error` | `"[trimmed for fixture]"` | abort reason |
| （缺失） | 时间戳 | —— | ts=0 + `lossy:cursor:no-timestamps` |
| （缺失） | tool_result | —— | 生成占位 + `lossy:cursor:tool-result-missing` |
| （缺失） | session id / cwd | —— | 由路径推导（`<sid>`/`<slug>`）或 `--target-cwd` |

**截断示例（新代 4 行中的 assistant 行 + 2 个 turn_ended 行，≤300 字符）**

```json
{"role":"assistant","message":{"content":[{"type":"text","text":"Running ls."},{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}
```
```json
{"type":"turn_ended","status":"error","error":"[trimmed for fixture]"}
```

**Reader 映射规则**

1. 逐行分派：有 `role` → 消息行；`type=="turn_ended"` → 状态行；其他未知 → warning。
2. 用户文本中的 `<user_query>\n…\n</user_query>` 包裹（legacy 两文件均出现）→ 默认**剥壳**并记 `lossy:cursor:user-query-unwrapped`；`--keep-wrappers` 可保留。
3. `tool_use` → tool-call：id 缺失 → 生成稳定 ID（`cursor:<session>:<行号>:<块序号>`）；同会话去重。
4. **tool_result 缺失（fixture 无任一 result 记录）**：IR 硬约束要求每个 call 有 result → Reader 直接生成 `content="[cursor:tool-result-missing]"`、`is_error=true`，记 lossy；或提供 `--strict` 模式报错（默认容错）。
5. `turn_ended.status=="error"` → `turn_abort`（reason=error 文本）；`success` 仅作轮次边界，不进 IR。
6. 顺序=行序；无时间戳 → ts=0 + warning（**不伪造 mtime**；提供 `--mtime-ts` 显式开关才用文件 mtime）。
7. cwd/session：路径含 `<slug>/agent-transcripts/<sid>/` → 尝试从 slug 反推 cwd（`-`↔`/` 歧义，未核实）→ 失败则 `cwd=None`+warning，session_id=`<sid>`（文件名去 `.jsonl`）。
8. 子代理：`legacy/Cursor/subagent-session.jsonl` 无任何子代理标记 → 不能区分主/子会话（warning）。

**Writer 最小可行**

- 产物：`<out>/projects/<slug>/agent-transcripts/<sid>/<sid>.jsonl`：`{"role":"user","message":{"content":[{"type":"text","text":…}]}}` / assistant（text 与 `tool_use` 分开 block）/ 每条 tool_result **丢弃**（原生无此概念）→ 记 lossy；turn 结束写 `{"type":"turn_ended","status":"success"}` 或 error+reason。
- `slug` 与 cwd 转义规则未核实 → 要求 `--slug`/`--target-cwd`；无索引 → 格式级；IDE `state.vscdb` **不支持**（SQLite 无 schema）。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| CUR-F1 | `stage0/cursor/small.jsonl` | 6 行 → 4 条消息（user=2/assistant=2）+ 2 个 turn_ended；tool-call=1（Bash/command=ls）、生成占位 result=1；lossy 含 `tool-result-missing`、`no-timestamps`；error 的 turn_ended→`turn_abort`=1 | FIXTURE（B3-F1/F2） |
| CUR-F2 | `legacy/Cursor/test-session.jsonl` | 6 条消息（user=2/assistant=4）；`<user_query>` 剥壳后 user 文本=`run ls command`、`now show me the git status`；tool-call=2（Shell）；占位 result=2 | FIXTURE |
| CUR-F3 | `legacy/Cursor/subagent-session.jsonl` | 3 条消息、1 个 tool-call+占位 result；无子代理标记 → warning `cursor:subagent-undetectable` | FIXTURE |
| CUR-F4（写） | IR（CUR-F1） | 写 transcript → 读回：消息数/角色序一致；tool_result 不落盘（lossy 声明）；turn_ended 与 IR 轮次对应 | FIXTURE（B3-F3） |

**已知有损项**：无时间戳；无 tool_result/tool id；无 cwd/标题/session 元数据（路径推导有限）；`turn_ended` 只保留成败；子代理不可识别；IDE 侧（SQLite）完全不支持。

---

### B3-05 Aider（难度 ★｜上限 FIXTURE）

**原生存储事实**（证据：harness-catalog **D** + aider 官方文档 **F**）：`~/.aider.chat/history/<hash>.md`，**Markdown 对话历史**；文件即导出，无 JSON/DB。`<hash>` 与仓库路径的映射规则**未核实**。

**fixture**：`sessionport/tests-fixtures/aider/history/abc123.md`（198 B，S1-M，与真实 history 形状一致）：2 个 `#### <user prompt>` 块 + 对应助手 Markdown 回答。

**结构（无固定 schema，靠 Markdown 标题分块）**

| 元素 | 实测 | IR 用途 |
|---|---|---|
| `^#### (.+)$` | `#### Refactor the queue to use an outbox` | user_message.text = 标题行文本 |
| 标题后正文直到下一个 `####` | 多行 Markdown | assistant_message.text（保留 Markdown 原文） |
| 时间戳 | **无** | ts=0 + `lossy:aider:no-timestamps` |
| 工具调用 | **无**（aider 的编辑/命令不在 history 里） | 无 tool 事件；`lossy:aider:no-tool-events` |
| cwd/标题/session id | 无（只能从文件路径/文件名推断） | title=首个 `####` 文本；session_id=`<hash>` |

**截断示例（全文 198 B，≤300 字符）**

```markdown
#### Refactor the queue to use an outbox
Decision: use the outbox pattern. Files: queue.py, outbox.py.
Next: add tests.

#### Can you also handle retries?
Yes, retries with backoff go in outbox.py.
```

**Reader 映射规则**

1. 按行扫描，`#### ` 行开启新块：该行文本 = user 消息；后续行（至下一个 `#### ` 前）拼接（strip 尾空白）= assistant 消息。
2. 前缀/空文件容错：文件开头不是 `####` 的文本 → 归入首个 assistant 块前的 system/孤立块 + warning。
3. 空块（只有标题无回复）→ assistant 文本为空字符串，warning `aider:empty-reply`（不丢 user）。
4. 代码围栏、列表等 Markdown 原样保留在 assistant text；不解析工具/命令。
5. `title`=首个 user 文本首行；`cwd=None`（writer 需要 `--target-cwd`）；ts=0。
6. 无法识别「aider 内部提示行」（如 `> ` 命令行）→ 保留为文本并 warning。

**Writer 最小可行**

- 产物：`<out>/history/<hash>.md`，按 `#### <user 首行>\n<assistant Markdown>\n\n` 逐对写出。
- `<hash>` 计算规则未核实 → 要求 `--hash` 或由 `--target-cwd` 的稳定 hash 生成（默认 sha256(cwd) 前 8 位，标注 non-native）；幂等：文件已存在则写 `<hash>.md.new` + 提示（不静默覆盖）。
- 不写索引（无）；格式级自往返（B3-F3）。原生 aider 加载历史只读展示，writer 可被 `aider --load-history` 尝试，但**未验证**。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| AID-F1 | `aider/history/abc123.md` | 块数=2；user=2/assistant=2 交替；user1=`Refactor the queue to use an outbox`、user2=`Can you also handle retries?`；assistant1 含 `Decision: use the outbox pattern.`；title=user1；lossy 含 `no-timestamps`/`no-tool-events` | FIXTURE（B3-F1/F2） |
| AID-F2 | 同上 | 多行回复完整（assistant1 两行均保留）、Markdown 缩进/代码围栏不丢 | FIXTURE |
| AID-F3（写） | IR（AID-F1） | 写 `<hash>.md` → 读回：块数/文本逐字符相等 → B3-F3；重复写幂等检查（.new 策略） | FIXTURE（B3-F3） |

**已知有损项**：无时间戳；无工具调用/命令输出；无 cwd/模型/usage；user prompt 多行语义未验证（fixture 全单行）；`<hash>` 规则未核实；图片/附件不支持。

---

### B3-06 OpenCode（难度 ★★★｜上限 FIXTURE / FIXTURE-CONSTRUCTED）

**原生存储事实**（证据：harness-catalog **C** 真实 51 sessions schema + **B** + **D**）：现版 `~/.local/share/opencode/opencode.db`（**SQLite**：`session/message/part` 表，业务字段在 `data` JSON blob；另有 `storage/session_diff/`、`snapshot/`、`tool-output/`）；旧版为 JSON 目录树（`storage/session|message|part/…`）。`XDG_DATA_HOME`/`OPENCODE_DB` 可覆盖。**P0**。

**fixture**（只有 part 级，G5）：
- `agent-sessions/stage0/opencode/001.json`、`002.json`：真实 part 形状 `{id,type:"text",text,time:{start}}`（缺 `messageID/sessionID` 关联字段）。
- `sessionport/tests-fixtures/opencode/storage/session/abc.json`：`{id,parts:[…]}` 简化（parts 顺序 assistant 在前、user 在后，**顺序不标准**）。
- **无 `.db` 文件** → SQLite schema 只能用 C 的字段表 + 构造 golden。

**字段表（part / session 两级）**

| 层 | 字段 | 实测/依据 | IR 用途 |
|---|---|---|---|
| part | `id` | `p_user_1` | source_id / tool id 参考 |
| part | `type` | `"text"`（真实另有 `tool`/`reasoning`/`file` 等，据 C） | block 类型 |
| part | `text` | `"Hello"` / `"Found 2 files."` | text block |
| part | `time.start` | `1730000001000`（ms） | ts |
| part | `messageID/sessionID`（真实 part 应有） | fixture 缺失 | 关联键（G5） |
| part（tool） | `tool`、`state:{status,input,output,metadata}`（据 C，fixture 无） | —— | tool-call/tool_result（配对靠 `state.status`/`toolCallId`，需真实样本确认） |
| message | `id,role,time{created,completed},sessionID,parentID,modelID,providerID`（据 C，fixture 无） | —— | 角色/模型/父链 |
| session | `id,projectID,directory,title,time{created,updated},version`（据 C） | fixture 的 `abc.json` 仅 `{id,parts}` | cwd/title |

**截断示例（真实 part 形状，各 ≤300 字符）**

```json
{"id":"p_user_1","type":"text","text":"Hello","time":{"start":1730000001000}}
```
```json
{"id":"p_text_1","type":"text","text":"Found 2 files.","time":{"start":1730000003100}}
```

**Reader 映射规则**

1. **两形态**：(a) legacy JSON 树：`session/{project}/{sid}.json` + `message/{sid}/{msgID}.json` + `part/{msgID}/{partID}.json` —— 按 message `time.created` 排序、part 按 `id`/时间组装；(b) SQLite：只读 `sqlite3.connect("file:opencode.db?mode=ro", uri=True)` + `PRAGMA query_only=ON`，`SELECT` session/message/part，`data` 做 `json.loads`。**SQLite 表结构本轮无 fixture 证据** → 必须标 `lossy:opencode:sqlite-schema-unverified`，并允许配置 `--schema-profile`（版本探测：读 `schema_migrations` 或 `session.version`）。
2. `type=="text"`→text block；`reasoning`→reasoning；`tool`→tool-call（`tool` 字段做 name）+ 对应 tool_result（`state.status=="completed"` 时 output 为 result；error→is_error）。
3. 消息角色：`message.role=="user"|"assistant"`；其他（system）→system_message/extra。
4. 顺序：legacy 下按 `time.created`；**若 part 文件顺序异常（sessionport 简化样本 assistant 在 user 前）→ 以 message 时间排序并 warning `opencode:part-order-nonstandard`**，不得静默按文件序。
5. cwd=session.directory；title=session.title；model=message.modelID；usage 从 assistant message `tokens`（据 C）。
6. 子代理/分支：`message.parentID` 树 → 线性化 + extra。

**Writer 最小可行（本轮只能承诺格式级/构造级）**

- **不建议**写 SQLite 主库（schema 版本、WAL、索引、迁移未知）→ 明确标注「Writer 暂不交付」或只交付 **legacy JSON 树** writer：`<out>/storage/session/<proj>/<sid>.json` + `message/<sid>/<msgID>.json` + `part/<msgID>/<partID>.json`（多文件、无 DB 版本冲突）。**现版 OpenCode 是否仍读 legacy 树未核实** → 只能当「结构等价产物 + 待验证」。
- 若 Lead 要求 SQLite writer：先做 §5 的 FIXTURE-CONSTRUCTED golden DB（3 表最小列），用 `sqlite3` 只读回读验证，并由 `--schema-profile` 锁版本；风险高，排到 SQLite 专项。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| OC-F1 | `agent-sessions/stage0/opencode/001.json`+`002.json` | 2 个 part 解析：type=text、text 精确、`time.start`=1730000001000/1730000003100；缺关联字段 → warnings 含 `opencode:orphan-part` | FIXTURE（B3-F1/F2） |
| OC-F2 | `sessionport/.../storage/session/abc.json` | parts=2；按 message 语义重排为 `[user, assistant]`（原数组顺序 assistant 在前）→ warning `part-order-nonstandard`；user/assistant 文本精确 | FIXTURE |
| OC-F3（构造） | **自构** golden DB（FIXTURE-CONSTRUCTED，3 表：session 1 行 / message 2 行 / part 3 行，只读打开） | 只读连接成功；reader 产出 2 消息 + 1 组 tool 配对；`lossy` 含 `sqlite-schema-unverified` | FIXTURE-CONSTRUCTED |
| OC-F4（写） | IR（OC-F2） | legacy JSON 树 writer 产物 → 读回等价；`--install` 真实库**不支持**（显式报错） | FIXTURE（B3-F3，结构级） |

**已知有损项**：SQLite 表结构/索引/版本未验证；part 关联字段缺样本；tool 配对依赖 `state` 字段（未验证）；snapshot/tool-output 实体不迁移；分支/子代理线性化；legacy 树与现版兼容性未知。

---

### B3-07 Cline（难度 ★★★｜上限 FIXTURE，metadata 级）

**原生存储事实**（证据：harness-catalog **C** 完整 schema + **B**）：CLI `~/.cline/data/sessions/<epochms>_<slug>/{<id>.json, <id>.messages.json}`；VS Code 扩展 `globalStorage/saoudrizwan.claude-dev/tasks/`。CLI 会话是 **metadata JSON + messages JSON 双文件**。

**fixture**（**只有 metadata，messages 文件缺失**，G2）：
- `agent-sessions/stage0/cline/cline-desktop-continued.json`（1,066 B，`status=completed, exit_code=0`，含 `importedFrom` 导入溯源）
- `agent-sessions/stage0/cline/session_1792607722905_fixt1.json`（1,526 B，`status=idle, exit_code=null`，含 usage/totalCost/systemPrompt）
- `sessionport/tests-fixtures/cline/tasks/t1.jsonl` 为 S2 简化（不可用）

**字段表（metadata v1）**

| 字段 | 类型 | fixture 实测 | IR 用途 |
|---|---|---|---|
| `version` | int | `1` | 版本探测 |
| `session_id` | str | `cline-desktop-continued` / `session_1792607722905_fixt1` | source_session_id |
| `source` / `provider` | str | `desktop` / `cline` | provenance |
| `pid` / `interactive` / `enable_tools`/`enable_spawn`/`enable_teams` | int/bool | `4343` / `true` | extra |
| `started_at` / `ended_at` | ISO8601 | `2026-09-15T20:25:52.339Z` / `…20:36:50.694Z` | created/updated |
| `exit_code` / `status` | int/null / str | `0`/`completed`；`null`/`idle` | 退出状态→extra；completed→正常；idle→未结束 warning |
| `cwd` / `workspace_root` | str | `/tmp/as-agent-fixture/project` / `/` | cwd / extra |
| `model` | str | `gpt-5.6-terra` / `~anthropic/claude-fable-latest` | model |
| `prompt` | str | `<user_input mode="act">List the files…</user_input>` | 首条 user_message（**仅当 messages 缺**时兜底；正常应优先 messages） |
| `metadata.title` | str | `Review the fixture project` | title |
| `metadata.usage` / `aggregateUsage` | obj | `{inputTokens:32103,outputTokens:301,cacheReadTokens:15738,cacheWriteTokens:0,totalCost}` | stats |
| `metadata.systemPrompt` | str | `"You are a coding assistant…"` | system_message（默认丢） |
| `metadata.importedFrom{...}` / `sessionHistoryOrigin` | obj | `{tool:"codex",sourceSessionId,…}` | extra（导入溯源） |
| `messages_path` | str | `/tmp/as-agent-fixture/cline/desktop_tool/<id>.messages.json` → **不存在** | messages 文件定位（G2） |

**截断示例（`session_…fixt1.json` 头尾节选，≤300 字符）**

```json
{"version":1,"session_id":"session_1792607722905_fixt1","started_at":"2026-10-21T18:35:23.146Z","exit_code":null,"status":"idle","cwd":"/","model":"~anthropic/claude-fable-latest","prompt":"<user_input>List the files…</user_input>","metadata":{"title":"List the files in /tmp/desk-probe"}}
```

**Reader 映射规则**

1. 先读 metadata JSON（上表映射）；再按 `messages_path`/同目录约定找 `<id>.messages.json`（**fixture 缺失 → warning `cline:messages-file-missing`**，此时只用 `prompt` 产出 1 条 user_message 并标 lossy，禁止假装完整会话）。
2. messages 文件 schema（据 C，未 fixture 验证）：数组 `{ts, type:"say"|"ask", say:"text"|"tool"|"command"|"completion_result"|…, text, partial?, images?}` → `say:"text"`/`ask:"text"`→文本；`say:"tool"`→tool-call；`say:"command"`→tool_result 或命令块；ask/say 的完成态按 `partial` 过滤（增量行折叠）。实现时用 **allowlist + 未知类型进 warnings**，并标 `lossy:cline:messages-schema-unverified`。
3. `prompt` 中的 `<user_input mode="act">…</user_input>` → 剥壳为 user 文本（`lossy:cline:prompt-unwrapped`）。
4. `status`/`exit_code`→`extra`；`status!="completed"` → warning；`ended_at` 缺失 → updated_at=started_at。
5. `cwd`/`workspace_root`→IR cwd/extra；title=metadata.title；usage→stats；systemPrompt 默认丢（`--keep-system` 保留）。
6. `importedFrom`/`sessionHistoryOrigin` → extra（这是 Cline 的「导入溯源」，对互转审计有用）。

**Writer 最小可行**

- 产物：`<out>/data/sessions/<epochms>_<slug>/` 下写 `<id>.json`（metadata 全部必填字段）+ `<id>.messages.json`（消息体按 C schema；本轮**消息体 schema 未验证**→ writer 标 experimental）。
- metadata 回填：`messages_path` 指向同目录 messages 文件；`started_at/ended_at/status/exit_code/cwd/model/prompt/title/usage`。
- 目录命名 `<epochms>_<slug>`（fixture 文件名 `session_1792607722905_fixt1` 提示 epochms 前缀；slug 规则未核实）。
- 无索引证据 → 格式级；VS Code 扩展 store **不支持**。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| CL-F1 | `cline-desktop-continued.json` | 19 个顶层字段解析；status=completed、exit_code=0、cwd=`/tmp/as-agent-fixture/project`、model=`gpt-5.6-terra`；`messages_path` 不存在 → warning `cline:messages-file-missing`；仅产出 1 条 user（prompt 剥壳）且 lossy | FIXTURE（B3-F1/F2，metadata 级） |
| CL-F2 | `session_…fixt1.json` | status=idle、exit_code=null → warning `cline:session-idle`；usage inputTokens=32103/outputTokens=301/cacheReadTokens=15738/totalCost=0.1826345；title 正确；`<user_input>` 剥壳 | FIXTURE |
| CL-F3（双文件） | **自构** `<id>.messages.json`（FIXTURE-CONSTRUCTED，含 say/ask/tool 三类） | metadata+messages 组装：消息数/角色序/tool 配对；`lossy:cline:messages-schema-unverified` | FIXTURE-CONSTRUCTED |
| CL-F4（写） | IR（CL-F2） | 写 metadata+messages 双文件 → reader 读回 status/usage/title/消息数一致 | FIXTURE（B3-F3） |

**已知有损项**：消息体 schema 无 fixture 证据；checkpoints/图片/命令输出细节；`enable_spawn/teams` 等运行态字段不迁移；`importedFrom` 仅审计；VS Code store 不支持；`status=idle` 会话可能未结束。

---

### B3-08 Goose（难度 ★★★☆｜上限 FIXTURE-LOW，需补样本 G6）

**原生存储事实**：catalog **D** 只给出 fixture 线索（`sessions/*.jsonl`），**真实默认路径与 schema 未核实**（catalog 列 P0「仅 fixture」；本次素材无新增证据）。

**fixture**：`sessionport/tests-fixtures/goose/sessions/g1.jsonl`（138 B，2 行）——**S2 简化形状**，只能证明「JSONL + role/content 两行问答」骨架，**不能作为 Goose 原生 schema 证据**。

**结构（仅 fixture 可见部分）**

| 字段 | 实测 | 备注 |
|---|---|---|
| `role` | `"user"` / `"assistant"` | 唯一可用字段 |
| `content` | str | 无 block 数组、无时间戳、无 usage、无工具 |
| 其他 | **无** | 真实 Goose 可能为 `content[]` blocks + created/usage（据公开源码印象，**未核实**，本报告不据此写实现） |

**截断示例（整行，≤300 字符）**

```json
{"role":"assistant","content":"Decision: ship it incrementally. Files: main.py."}
```

**Reader 映射规则（provisional，可实施部分）**

1. 逐行 JSON；`role` user/assistant → 对应消息；`role=="tool"` → tool_result（无 call id → orphan_tool_result）。
2. `content` 支持 str 与 `[{type:"text",text}]` 两种形态（前瞻容错，数组形态为 FIXTURE-CONSTRUCTED 假设，**标 experimental**）。
3. 无时间戳 → ts=0+warning；无 cwd/title → `None`+warning；`--target-cwd` 必需。
4. **不承诺**工具配对/usage/分支。

**Writer 最小可行**：`<out>/sessions/<id>.jsonl` 写 `{"role":…,"content":…}`；目录名/文件命名未核实 → 参数化；格式级自往返；**原生加载不承诺**。

**测试计划**

| 用例 | fixture | 断言 | 证据等级 |
|---|---|---|---|
| GOO-F1 | `goose/sessions/g1.jsonl` | 2 行 → 1 user+1 assistant；文本精确；warnings 含 `goose:no-timestamps`/`goose:no-cwd` | FIXTURE-LOW（B3-F1） |
| GOO-F2 | 同上 | writer 自往返 2 条角色/文本一致 | FIXTURE-LOW（B3-F3） |
| GOO-F3 | **自构** content 数组形态（FIXTURE-CONSTRUCTED） | 数组→text blocks；标 experimental | FIXTURE-CONSTRUCTED |

**已知有损项**：真实 schema 未知（路径、content 形态、时间、usage、工具）；建议先补 1 条真实会话再升级结论。

---

### B3-09 Windsurf（难度 —｜**BLOCKED**）

**原生存储事实**：catalog 仅有 **D** fixture 线索（`~/.windsurf` JSONL，「具体层级未核实」）；无 **B/C/F** 证据。真实 Windsurf 为 IDE 内部 store（可能 SQLite/私有格式），**本报告不臆造路径**。

**fixture**：`sessionport/tests-fixtures/windsurf/sessions/s1.jsonl`（115 B）——S2 简化形状（与 8 个 harness 完全同形），**零 schema 证据**。

**结论**：本轮**不实施 Reader/Writer**。若必须做，只能实现「简化 JSONL 骨架 reader」并明确标注 non-native（不建议写入协议矩阵）。**前置条件**：安装 Windsurf 采集真实会话文件（1 个即可）+ 确认路径/格式（catalog §6 未核实清单）。

**测试计划**：无有效断言；`WS-F0` 可做「不实现」记录（BLOCKED + 原因）。

---

### B3-10 Roo Code / Kilo Code（难度 —｜**BLOCKED（Cline 族联动）**）

**原生存储事实**：Roo = VS Code 扩展 `rooveterinaryinc.roo-cline/tasks/<id>/`（catalog 标 **G 未核实**）；Kilo = 无确定默认路径（catalog 仅 **D** 暗示 `~/.kilo/sessions/*.jsonl`）。两者均为 **Cline 族**（Cline/Roo/Kilo 同源 fork）。

**fixture**：Roo **无任何 fixture**；Kilo 只有 `sessionport/tests-fixtures/kilo/sessions/k1.jsonl`（132 B，S2 简化）。**本批无法给出可实施 schema**。

**结论**：与 B3-07 Cline 一起作为 **Cline 家族 pack** 处理：
1. 先完成 Cline metadata + messages schema（G2）；
2. 用 family profile 扩展 Roo/Kilo（路径/目录名/allowlist 类型不同，schema 预计 80% 复用）；
3. 真实路径需安装采集（catalog §6 未核实清单已列）。
**本轮**：不实施、不写矩阵行；测试计划记 `ROO-F0/KILO-F0 = BLOCKED（无 schema fixture）`。

---

## 4. 跨 harness 公共实现层（下一轮 converter-dev 优先复用）

| # | 能力 | 适用 harness | 实现要点（本批从 fixtures 实测得出的规则） |
|---|---|---|---|
| L1 | **JSONL 行级容错** | 全部 JSONL 源 | 跳过坏行 + 计数进 warnings（协议 §4.5）；坏样本参考：DSH `malformed_torn_tail.jsonl`、fx `checkpoint.json`（非法控制字符） |
| L2 | **瞬态/增量折叠** | Copilot（`*_delta`/ephemeral）、Cline（`partial`）、OpenCode（part 顺序） | 最终态优先；最终消息空 → 按序拼接 delta；折叠记 lossy |
| L3 | **工具配对补全** | Cursor/Goose/Cline、Copilot（部分） | 缺 result → 生成占位（协议 §4 约束 1）；孤儿 result → `orphan_tool_result`（协议 §5.1） |
| L4 | **时间归一** | 全部 | ISO8601/epoch ms/无时间戳三态：无时间戳 → ts=0+warning，**禁止静默伪造**（`--mtime-ts` 显式开关除外） |
| L5 | **多文件/目录组装** | Cline（metadata+messages）、OpenCode（session/message/part）、fx（伴生）、Grok（chat_history+summary） | 先 `discover()` 找主文件，再按约定补伴生文件；缺文件 → warning 不崩 |
| L6 | **SQLite 只读层（专项）** | OpenCode、Copilot DB、Cursor IDE、Devin/Hermes（后续） | `sqlite3.connect("file:…?mode=ro", uri=True)` + `PRAGMA query_only=ON`；JSON blob 二次解析；WAL 下只读可能需先 copy；**本轮无 DB fixture → 构造 golden（FIXTURE-CONSTRUCTED）先行** |
| L7 | **格式版本探测** | 全部 | 记录 `format_version`/`kind`/`version` 字段；未知版本仍尽力解析 + warning（catalog 风险：fx 0.0.8、OpenCode 2.x、DB schema drift） |
| L8 | **Writer 自往返校验** | 全部 writer | B3-F3：写产物 → 用同 reader 读回 → 语义比对；B3-F4 原生加载本轮全部 N/A |

---

## 5. 批 3 证据等级与验收标准（建议 Lead 采纳为下一轮 Definition of Done）

| 代号 | 判定 | 证据 | 本轮可得 |
|---|---|---|---|
| **B3-F0** 格式识别 | reader 能识别目标格式（kind/版本/形状），对错误格式明确拒绝 | 单元测试 | 全部可做 |
| **B3-F1** fixture 解析 | 上游 fixture 解析为 IR 且通过字段级断言（消息数/角色序/工具配对/时间） | §3 各测试计划表 | 8/10 可做（Windsurf/Roo/Kilo 无） |
| **B3-F2** ATIF 往返 | IR→ATIF v1.8→IR' 语义等价 | matrix JSON | 可做 |
| **B3-F3** 写回自往返 | IR→目标格式→同 reader 读回 IR''，差异均已在 lossy 声明 | matrix JSON | 可做（格式级） |
| **B3-F4** 原生加载 | 目标 harness 真实加载产物 | native-load 日志 | **N/A（本轮不承诺）** |
| **B3-F5** 真实会话 | 非人工构造的真实 session 样本 | 源 id 可追溯 | **无**（fixtures 是合成；COLLECTED 层见 batch2） |

> 硬性规则：报告中每行必须显式标 `FIXTURE`；不得把 FIXTURE 写成 NATIVE。fixtures 合成内容不得作为「真实会话」证据入 `interop-matrix*.md` 的真实性列。

---

## 6. 已知有损项汇总（跨目标）

| Harness | 主要 lossy 项 |
|---|---|
| Copilot CLI | delta 合并；hooks/model.*/mcp/skills 事件丢弃；attachments 路径化；DB 级 usage 明细不迁移；子代理折叠；缺失 session.start 时的 cwd |
| Gemini CLI | displayContent；thoughts 多块合并；cwd（projectHash 反查失败）；title 派生；toolCalls schema 未验证；无分支/子代理 |
| Qwen Code | 工具/usage/assistant 记录未经 fixture 验证；分支线性化；`<enc-cwd>`/命名规则未核实；systemPayload 语义 |
| Cursor CLI | 无时间戳；无 tool_result/tool id；无 cwd/标题；turn_ended 仅成败；子代理不可识别；IDE SQLite 不支持 |
| Aider | 无时间戳/工具/命令输出；无 cwd/模型/usage；多行 prompt 语义未验证；`<hash>` 规则未核实 |
| OpenCode | SQLite schema/索引/版本未验证；part→message 关联；tool state 配对；snapshot/tool-output 不迁移；legacy 树兼容性 |
| Cline | messages 体 schema 未验证；checkpoints/图片；运行态 enable_*；VS Code store；idle 会话 |
| Goose | 真实 schema 未知（路径/content 形态/时间/usage/工具） |
| Windsurf / Roo / Kilo | 无 schema 证据 → 不实施 |

通用 lossy 前缀建议：`<harness>:<item>`，与协议 §4 `lossy` 列表风格一致；Writer 生成占位结果时追加 `<harness>:placeholder-tool-result`。

---

## 7. 风险、限制与未核实清单

**限制（本报告）**
1. **证据等级上限 FIXTURE**：fixtures 为合成/裁剪样本；无真实会话；未做任何原生 CLI/加载验证。
2. **无 SQLite/压缩/图片样本**：公共 fixtures 全为纯文本；SQLite 类能力只能构造 golden（标 CONSTRUCTED）。
3. **未核对上游仓库实现代码**：本报告 schema 以 fixtures 实测 + `docs/harness-catalog.md`（C/D/B/F 级）为准；未逐个 clone 目标 harness 源码核对字段语义（受 15-25 分钟任务预算限制）。
4. **未安装目标 harness**：B3-F4 原生加载全部 N/A。

**未核实（下一轮必须确认）**
- Gemini `projectHash=sha256(?)` 的输入形式（绝对路径/realpath/大小写）；
- Qwen `<enc-cwd>` 编码与文件命名规则；
- Cursor `<slug>` 转义规则、`--resume` 发现机制；
- Cline `<id>.messages.json` 的完整字段（say/ask 类型集合）；
- OpenCode SQLite 表名/列名/版本迁移、legacy JSON 树是否仍被读取；
- Goose/Windsurf/Roo/Kilo 真实路径与 schema；
- Aider `<hash>` 算法与多行 prompt 在 history 中的表示；
- 各 Writer 产物是否会被原生 CLI discover/`--resume`（B3-F4）。

**风险**
- **格式漂移**：Copilot 事件 `copilotVersion` 已见 1.0.12/1.0.77 两代；Cursor 已见两代 transcript；OpenCode 2.x JSON→SQLite 迁移；adapter 必须有版本探测 + 宽松容错（catalog §6）。
- **把 S2 简化 fixture 当 schema 证据**：本轮已发现 8 个同形简化样本 + 1 个非 JSON 文本样本，下一轮务必先跑 §1.3 判定。
- **Writer 越权承诺**：所有 writer 第一版只能写 `--out` 暂存 + B3-F3；`--install` 真实 store 需备份/原子/幂等/运行中检测（协议 §6），本轮不实现。

---

## 8. 下一轮建议与索引

### 8.1 建议下一轮（批 3 第一波）先做 5 个 + 理由

| 顺位 | Harness | 理由 |
|---|---|---|
| 1 | **Copilot CLI** | fixture 质量最高（6 个 atifact 边界用例 + 33 类事件大样本）；JSONL 事件流直读；工具配对/子代理/usage/shutdown 语义齐全；metadata 最全（catalog 评「元数据最完整」） |
| 2 | **Gemini CLI** | 格式最简单（单 JSON 2 条消息即可全字段断言）；Qwen/iFlow 家族母本；writer 单文件可交付；Harbor RFC 有真实轨迹（**H**）可作后续 NATIVE 升级参照 |
| 3 | **Aider** | 难度最低（Markdown 分块 30 行内可完成）；作为「非结构化/纯文本源」样板验证 IR 的文本通道；用户基数大 |
| 4 | **Cursor CLI** | 用户盘最大；两代 JSONL 都在 fixture 中；能验证「无 tool_result 时占位补全」这一跨 harness 通用规则 |
| 5 | **Qwen Code** | 与 Gemini/Claude 家族双复用（parts + record envelope）；fixture 含正负样本（sessionId 不一致/紧凑 ID），能验证 ID 归一规则；writer 是纯 JSONL |
| 6（专项） | **OpenCode** | 单独作为「SQLite 专项」：先构造 golden DB + 只读层，再交付 reader；为 Copilot store/Cursor IDE/Devin/Hermes 复用同一工具层；不与前 5 个耦合 |

> 一句话：前 5 个全部是 **JSON/JSONL/Markdown 零 SQLite 依赖**，可在一轮内让 `asi` 的 FIXTURE 级 harness 从 0 → 5，并且写回自往返都能交付；SQLite 能力单独一轮做，避免阻塞主线。

### 8.2 文档与素材索引

| 内容 | 路径 |
|---|---|
| fixtures 来源/commit/许可证/原路径 | [`samples/batch2/public-fixtures/SOURCE.md`](../../samples/batch2/public-fixtures/SOURCE.md) |
| fixtures 许可证原文 | [`samples/batch2/public-fixtures/LICENSES/`](../../samples/batch2/public-fixtures/LICENSES/) |
| 本报告（批 3 方案） | `docs/formats/batch3-fixtures.md`（本文件） |
| 协议 §8/§11（扩展流程/采集层） | [`docs/atif-interop-protocol.md`](../atif-interop-protocol.md) |
| Harness 目录（49 候选/P0-P2/家族/路径证据） | [`docs/harness-catalog.md`](../harness-catalog.md) |
| 批 2 样本（COLLECTED 层） | [`docs/batch2-samples.md`](../batch2-samples.md)、`samples/batch2/oss/` |
| 批 1 格式文档（可复用家族逻辑） | [`docs/formats/claude-code.md`](claude-code.md)、[`codex.md`](codex.md)、[`omp.md`](omp.md)、[`qoder.md`](qoder.md)、[`dsh.md`](dsh.md) |
| 复现解析（本报告数据来源命令） | `cd samples/batch2/public-fixtures && python3 -c "…"`（见 §1.2 说明；全部为只读 `open/json.load/glob`，SQLite 未打开——无 DB 文件） |

### 8.3 本报告可复现性说明

- 盘点：`python3` 遍历 82 文件（`os.walk` + `getsize` + 逐文件 `json.loads` 判定 JSON/JSONL/MD/HAR）。
- 所有测试计划中的**精确期望值**（行数、事件类型数、消息数、toolRequests/starts/completes、token 数、时间戳）均由脚本实测得出，非 README 推测。
- SQLite 相关：本目录**不存在** `.db/.sqlite` 文件，故无「只读打开 SQLite fixture」动作可执行；下一轮拿到真实 DB 后用 `sqlite3.connect("file:…?mode=ro", uri=True)` + `PRAGMA query_only` 只读验证。
