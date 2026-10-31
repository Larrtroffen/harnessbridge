# 全项目覆盖账本（30-40 Harness 互转目标）

> 版本：**v0.3 定稿（批 5 + 批 5.1 已验收，达成 30-40 目标）**（2026-10-30）｜维护：Team（本文件是**唯一覆盖账本**，其它文档只引用不重复计数）
> 生成工具：[`tools/coverage-report.py`](../tools/coverage-report.py)（只读 stdlib；`--write` 只刷新本文件生成段；`--check/--json` 行为不变、生成块确定性）
> 数据源（只读）：`tools/agent-session-import/tests/artifacts/{interop-matrix,interop-matrix-batch2,interop-matrix-batch3,interop-matrix-batch4,interop-matrix-batch5}.json` + `samples/batch2/oss-add/`（稀疏标签）+ `docs/harness-catalog.md` + `docs/formats/batch3/4/5-fixtures.md`
> 上游口径：[`docs/atif-interop-protocol.md`](atif-interop-protocol.md) §12.4（覆盖账本分层）与 §13.4（协议覆盖 vs 真实会话覆盖）

> **当前阶段（v0.3 定稿）**：批 1/2/3/4/5/5.1 全部完成并验收。批 5.1 `interop-matrix-batch5.json` 为 **schema `asi-batch5-matrix/v2`**：17 行、pass=16 / partial=1（`fx`：orphan tool_results 有损已声明，按 FIXTURE 计入但不视为完全 pass）/ fail=0；REAL-LOCAL=2（gemini/pi）、FIXTURE=3（fx/mini-swe-agent/opencode 升级）、FIXTURE-LOW=2（codebuddy/kiro）、CONSTRUCTED=10、COLLECTED-SPARSE=1（claude-desktop）。converter 侧与 Lead 均已独立复跑（17 行、55/55 测试）。
> **v0.3 定稿三个数字**：协议覆盖（去重）**40/40（达成目标）**、真实会话覆盖 **21/40**、分层累计 **54/40（超上限→口径停用）**。

---

## 0. 一分钟结论（手写，数字以生成段 B 为准）

**四个数字必须分开报，禁止相加/混算（④ 为批 6 新增）：**

| 口径 | **v0.3 定稿** | v0.2（批 4 定稿） | 增量 | 含义 |
|---|---|---|---|---|
| **① 协议覆盖（去重 Harness，目标口径）** | **40/40 ✅ 达成** | 27/40 | +13 | 有 adapter + 至少 FIXTURE/构造/REAL-LOCAL 证据的**去重 Harness 数**；30-40 目标已达成 |
| **② 分层账本累计（协议 §12.4 口径）** | **54/40（已超上限→停用）** | 37/40 | +17 | 按层相加（含跨层重复）；v0.3 起**不再作为 X/40 进度** |
| **③ 真实会话覆盖（REAL）** | **21/40** | 19/40 | +2 | NATIVE 5 + COLLECTED 14 + REAL-LOCAL 1（gemini）+ COLLECTED-SPARSE 1（claude-desktop）；**FIXTURE/CONSTRUCTED 一律不计** |
| **④ fixture-verified 格式覆盖（批 6 新增）** | **35/40**（6 partial 计入） | — | 批 6 | 用外部/上游 fixture（MIT/Apache/REAL-EXAMPLE）跑 reader→IR→ATIF 验证通过的 canonical 标签数；**CONSTRUCTED 不计**；REAL-EXAMPLE 单列；真实会话覆盖 22/40 |

- **批 5+5.1 新增去重 13 个**：goose、continue、junie、kiro、crush、roo、codebuff、openhands、vibe（批 5 CONSTRUCTED）+ codebuddy、fx、mini-swe-agent（批 5.1）+ claude-desktop（oss-add SPARSE）。其中 mini-swe-agent 为 catalog 外框架（Harbor 样例），**若剔除则 39/40**（仍在 30-40 区间）。
- **升级/补层（不新增去重）**：gemini/pi → REAL-LOCAL；kiro → FIXTURE-LOW；opencode → FIXTURE（既有标签，升级见 docs/usage §12.1/matrix-batch5 文档）；cline/kilo-code 补 CONSTRUCTED。
- **`partial` 处理**：`fx` 为 pass/partial 中的有损行（orphan tool_results 不可表达 + writer 仅持久化文本事件，已在行内声明）→ 计入 FIXTURE 覆盖，但不标记为「完全通过」。
- **不计入任何数字**：gateway/unknown/other（中间件/兜底标签）、纯云端 P2（仅 ATIF 导出）、HAR wire 层（非 Harness）、BLOCKED/CANDIDATE/DOC-ONLY。
- **剩余缺口**（批 6 候选）：Zed（SQLite 线程库，需源码构造/真实 DB）、Warp/Replit（纯云端，仅导出）、iFlow（本地 store 未核实）、Antigravity 原生 protobuf writer（reader 已可，writer 需逆向/编码器）、CodeBuddy 上游真实 fixture（现为 Codeg 派生 FIXTURE-LOW）、Windsurf/Kilo 真实 store；另 gateway 采集缺口不在 30-40 产品去重内。

---

## 1. 证据等级定义（手写，供判定/升级使用）

| 等级 | 判定标准 | 证据来源 | 计入协议覆盖 | 计入真实会话覆盖 |
|---|---|---|---|---|
| **NATIVE** | 目标 harness 真实安装 + 本机真实 store + 原生加载验证（L3 pass / partial） | `interop-matrix.json` | ✅ | ✅ |
| **REAL-LOCAL** | 本机真实安装 + 真实本机会话（如真实 patch 流），**未经原生加载 L3**；与 NATIVE 只差「L3 未验证」 | `interop-matrix-batch5.json`（gemini/pi） | ✅ | ✅ |
| **COLLECTED** | 真实用户会话（OSS `traj-session/1`），B2-L0~L2 + DSH L3；非原生落盘格式 | `interop-matrix-batch2.json` | ✅ | ✅ |
| **COLLECTED-SPARSE** | 真实采集但样本稀疏（claude-desktop 仅 2 条消息）；默认计入并标注 | `samples/batch2/oss-add/` | ✅（标注） | ✅（标注） |
| **FIXTURE** | 上游公开 fixture 原生格式，通过 B3/B4/B5 F 级验证（**partial=有损但通过**，单列标注，不算 fail） | b3/b4/b5 artifacts | ✅ | ❌ |
| **FIXTURE-LOW** | 部分格式证据（Codeg 派生/reader-only/规范化转录） | b5 artifact（codebuddy/kiro） | ✅（标注低） | ❌ |
| **FIXTURE-CONSTRUCTED** | 上游无样本，按 recon/源码 schema 自构 golden sample（必须标注，列名未核实处声明） | b4/b5 artifacts | ✅（标注构造） | ❌ |
| **PLANNED / BLOCKED / CANDIDATE / DOC-ONLY** | 无 artifact 证据 / 仅文档线索 | recon/catalog | ❌ | ❌ |
| **CLOUD** | 纯云端，仅 ATIF 导出 | catalog §3.6 | ❌ | ❌ |

**多证据优先级**：`NATIVE > REAL-LOCAL > COLLECTED > COLLECTED-SPARSE > FIXTURE > FIXTURE-LOW > FIXTURE-CONSTRUCTED`。主表取最高级、fixture 列同时展示较低层证据。**禁止反向升级**：FIXTURE/构造 ≠ REAL-LOCAL；REAL-LOCAL ≠ NATIVE。

---

## 2. 计数口径与去重规则（手写，冲突清单见生成段 D.4）

### 2.1 四个数字的定义

1. **协议覆盖（去重 Harness）**：各层去重后、达到 FIXTURE 及以上的 Harness 数；目标 `X/40`（**唯一对外进度口径**）。
2. **分层账本累计**：`批1 5 + 批2 18 + 批3 6 + 批4 8 + 批5 17` = **54**；超过 40 上限后**口径停用**（仅作批次对账）。
3. **真实会话覆盖（REAL）**：`NATIVE ∪ REAL-LOCAL ∪ COLLECTED(含 SPARSE)` 去重；FIXTURE/CONSTRUCTED 不计。
4. **fixture-verified 格式覆盖（批 6）**：40 canonical 标签中，用外部/上游 fixture 或本仓库 fixture 实际跑通 `reader → IR → ATIF → IR` 的标签数（**partial 计入**，status 见矩阵；共 34 pass + 6 partial = 35/40）；**CONSTRUCTED 不计入**；REAL-EXAMPLE（Harbor 公开真实轨迹样例）单列，不能算真实用户会话；ROI 是「格式可复现验证」，不是 REAL。`iFlow`/`Zed` 为 40 canonical 之外的 bonus source，不计入分母。

**v0.3 定稿算术（与生成段 D.3 一致）**：

```
分层累计   = 37（批1-4）+ 17（批5+5.1）= 54（超 40 上限，口径停用）
去重 Harness = 27（v0.2）+ 13（批5+5.1+oss-add 新增）= 40/40 ✅
真实会话覆盖 = 19（v0.2）+ 1（REAL-LOCAL gemini）+ 1（SPARSE claude-desktop）+ 1（REAL continue）= 22
fixture-verified = 40 canonical 中 34 pass + 6 partial = 35/40（CONSTRUCTED 不计；iFlow/Zed 为 bonus，不入分母）
```

### 2.2 去重规则（合并 = 同一产品/同一格式；不确定按标签计并记 D.4）

**明确合并**：`claude-code→claude`；`codex`；`qoder`；`droid→factory-droid`；`kimi-code→kimi`；`kilo→kilo-code`；`codex-desktop→codex`；`kimi-cli→kimi`；`roo-code→roo`。

**明确不合并**：OMP≠Pi（同族不同产品）；Gemini CLI≠Antigravity（格式独立）；**Cline/Roo/Kilo 同族但按 3 标签计**；**CodeBuddy 虽属 Claude Code 衍生家族（目录布局同形），但按独立产品标签计**（Codeg 派生 FIXTURE-LOW）；**mini-swe-agent 为 catalog 外的 Harbor/ATIF 外部框架样例**，计入则 40/40、剔除则 39/40（由 Lead 决定，本账本默认计入并注明）；Cursor CLI/IDE 同一行（adapter 仅 CLI）。

**批 5 专项**：`cline`/`kilo-code` 本已是 COLLECTED（批 5 只补构造证据）；`roo` 为新增去重；`codebuddy` 是独立标签不并入 Claude；`claude-desktop` 为 oss-add 稀疏真实采集（默认计入并标注）；`gateway`/`unknown`/`other` 不计入。

### 2.3 为什么两个覆盖率数字都要报

分层口径 54 > 40 说明「分层累计」只能回答**批次进度**，不能回答「支持了多少种 Harness」。对外必须报去重口径 **40/40** 并注明真实覆盖 **21/40** 与证据构成（NATIVE 5 / REAL-LOCAL 1 / COLLECTED 14 / SPARSE 1）；**不得用 54 或构造层数冒充 40 个 Harness**。

---

## 3. 生成段（脚本维护，勿手改）

> 以下内容由 `tools/coverage-report.py` 从 5 个 matrix artifact JSON + oss-add + adapter 注册表自动生成；手工修改会在下次 `--write` 时被覆盖。`--check` 在 CI 中用于防止账本过期。

<!-- BEGIN GENERATED: coverage-ledger -->

### A. 分层汇总（自动生成）

> 数据快照：批 1-4 artifact + 批 5 `interop-matrix-batch5.json`（2026-10-29T20:10:30Z，**schema asi-batch5-matrix/v2 定稿**：17 行 pass=16/partial=1/fail=0；partial 行 fx 为「有损但通过」，按 FIXTURE 计入并注明；claude-desktop 为 COLLECTED-SPARSE（默认计入）。

| 层 | 证据等级 | Harness 数 | 去重/说明 | 最高验证级别 | 证据文件 | 状态 |
|---|---|---|---|---|---|---|
| 批 1 原生（本机安装） | NATIVE | 5 | 5（= 批 1 全量） | L0–L3（codex/qoder L3 partial） | `interop-matrix.json` | ✅ 已定稿 |
| 批 2 采集（OSS 真实会话） | COLLECTED | 18 | 17 真实标签 + `other`（非 Harness） | B2-L0–L3（DSH 真实加载） | `interop-matrix-batch2.json` | ✅ 已定稿 |
| 批 2 oss-add（稀疏采集） | COLLECTED-SPARSE | 1 | claude-desktop 仅 2 条消息（默认计入并标注）；gateway/unknown 不计入 | oss-add 采集补证 | `samples/batch2/oss-add/` | 🟡 稀疏，计真实覆盖 |
| 批 3 原生 fixture | FIXTURE | 6 | 3（copilot/gemini/qwen 新增） | B3-F0–F3 | `interop-matrix-batch3.json` | ✅ 已定稿 |
| 批 4 原生 fixture/构造 | FIXTURE×4 / FIXTURE-CONSTRUCTED×3 / FIXTURE-LOW×1 | 8 | 5（OpenClaw/Kimi/Grok/Antigravity/Devin；Droid/Hermes/OpenCode 为补层） | B4-F0–F3 | `interop-matrix-batch4.json` | ✅ 已定稿 |
| 批 5 REAL-LOCAL + 构造 | COLLECTED-SPARSE×1 / FIXTURE×1 / FIXTURE-CONSTRUCTED×11 / FIXTURE-LOW×2 / REAL-LOCAL×2 | 17 | 13 去重新增（claude-desktop/codebuddy/codebuff/continue/crush/fx/goose/junie/kiro/mini-swe-agent/openhands/roo/vibe）；gemini/pi 为 REAL-LOCAL；cline/kilo-code 为既有标签补构造 | B5-F2/F3 | `interop-matrix-batch5.json` | 🟡 已定稿（schema asi-batch5-matrix/v2，2026-10-29T20:10:30Z；17 行 pass=16/partial=1/fail=0） |
| 批 5.1（已并入批 5 快照） | 并入（FIXTURE×2 / LOW×2 等） | 并入批 5 行 | codebuddy/fx/mini-swe-agent 与 kiro/opencode 升级均已计入批 5 v2 artifact（不单列） | B5.1-F2 | `interop-matrix-batch5.json`（v2） | ✅ 已并入批 5 v2 artifact（codebuddy/fx/mini-swe-agent 已计入；kiro/opencode 升级已反映） |
| wire 层（HAR/SSE，非 Harness） | FIXTURE-LOW | 1（层） | 0（不占 Harness 名额） | — | `atifact/*.har` | ⏳ 可选路线 |
| 纯云端/P2（仅 ATIF 导出） | — | 12 | 0（不排期） | — | harness-catalog.md §3.6 | ⏸ 不排期 |

### B. 进度条与四个数字（自动生成，禁止混算）

```
协议覆盖（去重 Harness，v0.3 定稿）  ██████████████████████████████  40/40  （目标上限 40）
真实会话覆盖（含 REAL-LOCAL/REAL）  ████████████████░░░░░░░░░░░░░░  22/40  （批次前 19；REAL-LOCAL +1、COLLECTED-SPARSE +1、REAL +1）
分层账本累计（口径停用）      ██████████████████████████████  54/40  已超 40 上限，只作批次进度
fixture-verified 格式覆盖（外部 fixture/样例，批 6）  ██████████████████████████░░░░  35/40
```

| 口径 | v0.2（批 4 定稿） | v0.3 定稿（批 5+5.1） | v0.4（批 6） | 增量 | 说明 |
|---|---|---|---|---|---|
| **协议覆盖（去重 Harness）** | **27** | **40/40** | 40/40 | +13 | 新增 13：claude-desktop/codebuddy/codebuff/continue/crush/fx/goose/junie/kiro/mini-swe-agent/openhands/roo/vibe；**达成 40/40 目标**；其中 mini-swe-agent 为 catalog 外框架（剔除则 39/40） |
| 真实会话覆盖（REAL） | 19 | 21 | 22/40 | +3 | REAL-LOCAL（gemini）/ COLLECTED-SPARSE（claude-desktop）/ REAL（continue，批 6）**计入**；FIXTURE/CONSTRUCTED/构造不计 |
| **fixture-verified 格式覆盖（批 6 新增）** | — | — | **35/40** | 批 6 | 外部/上游 fixture 可升 FIXTURE；CONSTRUCTED 不计；REAL-EXAMPLE 单列；REAL 仍 22/40 |
| 分层账本累计 | 37 | 54（超 40 上限→停用） | — | +17 | 批 5+5.1 +17（含构造/稀疏）；**该口径不再作为 X/40 进度** |
| adapter 注册（代码）reader/writer | 19/18（批 4） | 42/32 | — | — | reader 含批 5 新 source；writer 以 NATIVE_TARGETS 为准 |
| FIXTURE 级 partial（有损但通过） | — | fx | — | — | partial 不计 fail，也不当完全 pass；lossy 已在行内声明 |
| 距 30-40 目标（去重口径） | 差 13 | 差 0（40/40） | — | — | 目标达成：40/40（若剔除 catalog 外框架 mini-swe-agent → 39/40，仍在 30-40 区间） |

### C. 逐 Harness 主表（自动生成）

> 排序：证据等级由高到低（NATIVE→REAL-LOCAL→COLLECTED→FIXTURE→…→BLOCKED→CANDIDATE→DOC-ONLY）。批 5.1 已并入 v2 artifact（codebuddy/fx/mini-swe-agent 计入）。

| Harness | 家族 | native adapter | 本地真实 store | OSS 采集 | fixture 样本 | 当前证据等级 | 最高验证级别 | 证据文件/命令 | 备注/缺口 |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code | Claude Code 原型 | ✅ r+w | ✅ | ✅ claude-code | — | NATIVE | L3 pass | interop-matrix.json（5×5 方向）/ `asi matrix` | L3 原生加载 4/4 通过（PTY `claude --bare --resume`）；writer 可手写 transcript 被 resume 发现 |
| DeepSeek Harness | 自有（zstd 双帧 JSONL 事件流） | ✅ r+w | ✅ | — | — | NATIVE | L3 pass | interop-matrix.json | L3 原生加载 4/4 通过（`Session.fromRestore`）；批 2/3/4 的 L3/F2 唯一真实加载器 |
| OMP (oh-my-pi) | pi 系（树状事件流） | ✅ r+w | ✅ | — | — | NATIVE | L3 pass | interop-matrix.json | L3 原生加载 4/4 通过（`omp --mode=rpc -r`）；与 Pi/OpenClaw 同格式族 |
| OpenAI Codex CLI | 自有（rollout JSONL） | ✅ r+w | ✅ | ✅ codex | — | NATIVE | L3 partial | interop-matrix.json | L3 partial：codex 0.164 thread store 不扫裸 rollout（0/4）；L0-L2 全通过 |
| Qoder | Claude Code 衍生（已验证） | ✅ r+w | ✅ | ✅ qoder | — | NATIVE | L3 partial | interop-matrix.json / interop-matrix-batch2.json | L3 partial：本机无 Qoder CLI（IDE-only），格式级验证通过 |
| Gemini CLI | Gemini 系母本（Qwen Code 上游） | ✅ r+w | — | — | ✅ REAL-LOCAL（批 5） | REAL-LOCAL | B5-REAL-LOCAL | interop-matrix-batch3.json / interop-matrix-batch5.json | 批 3 FIXTURE + 批 5 REAL-LOCAL（本机真实 patch 流）；REAL-LOCAL 计入真实会话覆盖但不升 NATIVE |
| Pi (pi.dev) | pi 系（树状事件流） | ✅ r+w | — | ✅ pi | ✅ REAL-LOCAL（批 5） | REAL-LOCAL | B5-REAL-LOCAL | interop-matrix-batch2.json / batch3 / batch5 | COLLECTED（OSS）+ FIXTURE + 批 5 REAL-LOCAL（本机真实）；与 OMP/OpenClaw 同族 |
| Aider | 自有（Markdown history） | ✅ r+w | — | ✅ aider | ✅ FIXTURE（批 3） | COLLECTED | B2-L3（DSH 真实加载） / B3-F3 | interop-matrix-batch2.json / interop-matrix-batch3.json | COLLECTED（OSS 真实 96 消息）+ FIXTURE 双证据；Markdown 无工具/时间戳 |
| Cherry Studio（外部标签） | 外部标签（catalog 未收录） | ✅ reader | — | ✅ cherry-studio | — | COLLECTED | B2-L3（DSH 真实加载） | interop-matrix-batch2.json | 按标签计；未在 catalog 49 候选中，产品形态与其他标签不同（桌面客户端） |
| Cline | Cline 族（Cline/Roo/Kilo） | ✅ r+w | — | ✅ cline | ✅ FIXTURE-CONSTRUCTED（批 5） | COLLECTED | B5-F2 | interop-matrix-batch2.json / interop-matrix-batch5.json | COLLECTED + 批 5 CONSTRUCTED（messages 补齐）；Cline 族按标签计（cline/roo/kilo-code 三行） |
| Cursor（CLI transcript） | 自有（transcript JSONL，两代） | ✅ r+w | — | ✅ cursor | ✅ FIXTURE（批 3） | COLLECTED | B2-L3（DSH 真实加载） / B3-F3 | interop-matrix-batch2.json / interop-matrix-batch3.json | COLLECTED（OSS 1544 消息）+ FIXTURE；原生 adapter 只覆盖 CLI transcript，IDE `state.vscdb` 未支持 |
| Factory Droid | 自有（CLI stream / session store v2） | ✅ r+w | — | ✅ factory-droid | ✅ FIXTURE（批 4） | COLLECTED | B2-L3（DSH 真实加载） / B4-F2 | interop-matrix-batch2.json / batch4-fixtures.md §B4-04 / interop-matrix-batch4.json | COLLECTED（OSS 479 消息）+ 原生两代格式 fixture；原生 store 路径未核实（catalog E legacy-only） |
| Hermes | SQLite 类（逻辑投影 fixture） | ✅ r+w | — | ✅ hermes | ✅ FIXTURE-CONSTRUCTED（批 4） | COLLECTED | B2-L3（DSH 真实加载） / B4-F2 | interop-matrix-batch2.json / batch4-fixtures.md §B4-06 / interop-matrix-batch4.json | COLLECTED（OSS 378 消息）+ 批 4 CONSTRUCTED；原生 `state.db` 无样本，列名未核实 |
| Kilo Code | Cline 族（Cline/Roo/Kilo） | ✅ r+w | — | ✅ kilo-code | ✅ FIXTURE-CONSTRUCTED（批 5） | COLLECTED | B5-F2 | interop-matrix-batch2.json / interop-matrix-batch5.json | COLLECTED + 批 5 CONSTRUCTED（Cline 族按标签计，不与 cline/roo 合并） |
| OpenCode | SQLite 类 / legacy JSON 树 | ✅ r+w | — | ✅ opencode | ✅ FIXTURE（批 5.1 升级，artifact 未单列） | COLLECTED | B5-F2（文档声明，artifact 未单列） | interop-matrix-batch2/4/5.json / interop-matrix-batch4.json | COLLECTED（OSS 567 消息）+ 批 4 CONSTRUCTED → 批 5.1 升 FIXTURE（sqlite_v2 JSON fixture；artifact 未单列，见 docs/usage §12.1） |
| OpenCraw（外部标签，疑与 OpenClaw 同名） | 外部标签（待确认） | ✅ reader | — | ✅ opencraw | — | COLLECTED | B2-L3（DSH 真实加载） | interop-matrix-batch2.json | **名称冲突**：OSS 标签 `opencraw` 疑为 `openclaw` 拼写/别名；按标签计，确认后去重数字 -1 |
| TRAE | 自有 | ✅ reader | — | ✅ trae | — | COLLECTED | B2-L3（DSH 真实加载） | interop-matrix-batch2.json | COLLECTED（OSS 612 消息）；catalog 标 P2（无原生导入），有真实采集样本但无原生 adapter |
| Windsurf | 自有（IDE 内部） | ✅ reader | — | ✅ windsurf | — | COLLECTED | B2-L3（DSH 真实加载） | interop-matrix-batch2.json | COLLECTED（OSS 144 消息）；原生 fixture 仅简化样本 → BLOCKED；真实路径/格式未核实 |
| WorkBuddy（外部标签） | 外部标签（catalog 未收录） | ✅ reader | — | ✅ workbuddy | — | COLLECTED | B2-L3（DSH 真实加载） | interop-matrix-batch2.json | 按标签计；catalog 未收录，真实会话仅以 COLLECTED 层存在 |
| ZCode (Z.ai) | 自有（经 ACP bridge） | ✅ reader | — | ✅ zcode | — | COLLECTED | B2-L3（DSH 真实加载） | interop-matrix-batch2.json | COLLECTED（OSS 779 消息）；catalog 标 P2（Codeg 自记 transcript，无原生导入） |
| Claude Desktop / Cowork | 桌面/云端 | ✅ reader | — | — | ✅ COLLECTED-SPARSE | COLLECTED-SPARSE | oss-add 采集（2 条消息） | samples/batch2/oss-add/ + oss-trajectory-inventory.md / interop-matrix-batch5.json | oss-add 新采仅 2 条消息（COLLECTED-SPARSE，稀疏但默认计入真实覆盖并标注）；gateway/unknown 为中间件/兜底标签，不计入 30-40 |
| fx (vercel-labs) | 自有事件日志（event_log_v1/event_log schema 4） | ✅ r+w | — | — | ✅ FIXTURE（批 5.1） | FIXTURE | B5.1-F2 | interop-matrix-batch5.json（5.1） | 批 5.1 计划项（task-28）：**尚未计入任何覆盖数字**；批 5 侦察已有 schema4 上游 fixture |
| GitHub Copilot CLI | 自有（事件 JSONL） | ✅ r+w | — | — | ✅ FIXTURE（批 3） | FIXTURE | B3-F3（自往返） | interop-matrix-batch3.json | B3-F0/F1/F2(DSH)/F3 全通过；status=partial 因声明 lossy（delta 合并、消息分组归一） |
| Grok Build | 自有多文件（summary+chat_history） | ✅ r+w | — | — | ✅ FIXTURE（批 4） | FIXTURE | B4-F2（自往返/构造） | batch4-fixtures.md §B4-03 / interop-matrix-batch4.json | 多文件组装；events/updates/plan 不迁移；目录编码未核实 |
| Kimi Code | 自有事件协议（非 Claude 衍生） | ✅ r+w | — | — | ✅ FIXTURE（批 4） | FIXTURE | B4-F2（自往返/构造） | batch4-fixtures.md §B4-02 / interop-matrix-batch4.json | protocol_version=1.4 事件日志；fixture 含 time=0 合成 parity 段；原生路径未核实 |
| Mini-SWE-agent | 外部 agent 框架（catalog 未收录） | ✅ r+w | — | — | ✅ FIXTURE（批 5.1） | FIXTURE | B5.1-F2 | interop-matrix-batch5.json（5.1） | 批 5.1 计划项（task-28）：**尚未计入任何覆盖数字**；是否计入 40 由 Lead 决定 |
| OpenClaw | pi 系（树状事件流） | ✅ r+w | — | — | ✅ FIXTURE（批 4） | FIXTURE | B4-F2（自往返/构造） | batch4-fixtures.md §B4-01 / interop-matrix-batch4.json | pi 系第 3 员（复用 OMP/Pi 树 walker）；原生路径层级未核实 |
| Qwen Code | Claude 衍生（Gemini fork） | ✅ r+w | — | — | ✅ FIXTURE（批 3） | FIXTURE | B3-F3（自往返） | interop-matrix-batch3.json | B3 status=pass（唯一 0 lossy）；fixture 每文件仅 1 行 user 记录，会话 envelope 级 |
| CodeBuddy (腾讯) | 自有（OpenAI Agents-SDK item 记录） | ✅ r+w | — | — | ✅ FIXTURE-LOW（批 5.1） | FIXTURE-LOW | B5.1-F2 | interop-matrix-batch5.json（5.1） | 批 5.1 计划项（task-28）：**尚未计入任何覆盖数字**，等 matrix-batch5 重生成后刷新 |
| Google Antigravity | Gemini 模型/自有 step 转录 | ✅ reader | — | — | ✅ FIXTURE-LOW（批 4） | FIXTURE-LOW | B4-F2（自往返/构造） | batch4-fixtures.md §B4-05 / interop-matrix-batch4.json | reader-only：fixture 为 JSONL 转录，原生 `.pb` protobuf 无公开 schema → writer BLOCKED |
| Kiro CLI (AWS) | 自有（JSONL 事件日志 + JSON metadata） | ✅ r+w | — | — | ✅ FIXTURE-LOW（批 5） | FIXTURE-LOW | B5-F2（LOW） | interop-matrix-batch5.json | 批 5 CONSTRUCTED → 批 5.1 升 FIXTURE-LOW（Codeg 派生/裁剪）；上游真实 fixture 可再升 FIXTURE |
| Codebuff | OSS/自有 | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（session-state 类型定义构造） |
| Continue | IDE 扩展（JSON session） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（原 CANDIDATE：无上游 fixture） |
| Crush (Charm) | 自有 TUI（SQLite store） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED；上游 SQL migrations 可导出表结构（sessions/messages），**License=FSL** 需 Lead 审视，不 vendor 源文件 |
| Devin CLI | SQLite 类（逻辑投影 fixture） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 4） | FIXTURE-CONSTRUCTED | B4-F2（自往返/构造） | batch4-fixtures.md §B4-07 / interop-matrix-batch4.json | 原生 `sessions.db` SQLite；fixture 为作者自述逻辑投影；列名未核实 |
| Goose (Block) | 自有（session JSONL） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（原 BLOCKED→已构造：无上游 fixture，按源码 schema 构造） |
| Junie (JetBrains) | IDE 内部（JVM） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（原 BLOCKED→已构造）；JVM/IDE 内部格式按公开文档构造 |
| Mistral Vibe | 自有（JSONL session log） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（按 mistral-vibe 源码布局构造：meta.json + messages.jsonl） |
| OpenHands | 自有（trajectory 导出） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（上游真实轨迹样例 + 构造） |
| Roo Code | Cline 族（Cline/Roo/Kilo） | ✅ r+w | — | — | ✅ FIXTURE-CONSTRUCTED（批 5） | FIXTURE-CONSTRUCTED | B5-F2 | interop-matrix-batch5.json | 批 5 CONSTRUCTED（原 BLOCKED→已构造）；Cline 族按标签计，不与 cline/kilo-code 合并 |
| iFlow CLI | 疑似 Claude/Gemini 衍生（未核实） | ✅ reader | — | — | — | — | — | harness-catalog.md #21 | catalog P2：本地 store 未核实 |

### D. 去重与计数校验（自动生成）

#### D.1 合并规则（alias → canonical）

| Harness | 矩阵/采集标签 | 判定依据 |
|---|---|---|
| Claude Code | `claude`, `claude-code` | 同一 Harness（按产品合并） |
| Kimi Code | `kimi`, `kimi-code` | 同一 Harness（按产品合并） |
| Factory Droid | `factory-droid`, `droid` | 同一 Harness（按产品合并） |
| Kilo Code | `kilo-code`, `kilo` | 同一 Harness（按产品合并） |
| Roo Code | `roo`, `roo-code` | 同一 Harness（按产品合并） |
| Mini-SWE-agent | `mini-swe-agent`, `mini-swe` | 同一 Harness（按产品合并） |

#### D.2 标签映射校验（自动）

已映射批 1/2/3/4/5 + 批 5.1 计划全部标签（`other`/`gateway`/`unknown` 为非 Harness，已排除；无未映射标签）。

#### D.3 分层账本算术（可逐项核对）

```
批 1 NATIVE    =  5
批 2 COLLECTED = 18  （真实标签 17 + `other` 1；去重后新增 14）
批 3 FIXTURE   =  6  （去重后新增 3）
批 4 FIXTURE系 =  8  （去重后新增 5）
批 5+5.1 证据  = 17  （REAL-LOCAL 2 / COLLECTED-SPARSE 1 / 其余构造·FIXTURE 14；去重新增 13；REAL 净增 2；partial=fx 有损但计入）
批 5.1 并入   =  3  （codebuddy/fx/mini-swe-agent；已在上行计入，不重复）
--------------------------------------------------------
分层累计（v0.2 / v0.3 / 批 5.1 后）= 37 / 54 / 57  （v0.3 起超 40 上限→停用）
去重 Harness（v0.2 / v0.3 / 批 5.1 后）= 27 / 40 / 40
真实会话覆盖（v0.2 / v0.3 / 批 5.1 后）= 19 / 22 / 21（REAL-LOCAL 与 COLLECTED-SPARSE 计入）
```

#### D.4 已知计数冲突与待确认（不自动合并）

| # | 冲突 | 当前处理 | 若确认后的影响 |
|---|---|---|---|
| C1 | OSS 标签 `opencraw` ↔ OpenClaw 疑似同一产品 | 按标签分别计（opencraw=COLLECTED，openclaw 批 4 FIXTURE） | 若同一：去重 -1 |
| C2 | 批 2 `other` 非具体 Harness | 分层按协议口径计 18；去重/REAL 排除 | 不影响去重数字 |
| C3 | `cherry-studio` / `workbuddy` 不在 catalog 49 | 按标签计（COLLECTED） | 若不算 Harness：去重 -2、REAL -2 |
| C4 | OMP ↔ Pi 同格式族 | 分开计（不同产品；Pi 为 REAL-LOCAL） | 不建议合并 |
| C5 | `droid` ↔ `factory-droid` 同一产品 | 已合并（alias） | — |
| C6 | `claude-code`↔`claude`、`kilo`↔`kilo-code`、`kimi-code`↔`kimi`、`roo-code`↔`roo` | 已合并（alias） | — |
| C7 | Codex Desktop→codex；Kimi CLI→kimi | 按 catalog 家族合并（单列行仅备注） | — |
| C8 | Gemini CLI ↔ Antigravity 同用 Gemini 模型 | 分开计（格式独立：JSON/JSONL vs SQLite+protobuf） | 不建议合并 |
| C9 | Cline/Roo/Kilo 同族（Cline 谱系） | **按标签计为 3 行**（cline/roo/kilo-code），不合并 | 若合并：去重 -2（不建议） |
| C10 | oss-add：claude-desktop 仅 2 条消息；gateway/unknown 为中间件/兜底标签 | claude-desktop 计 COLLECTED-SPARSE（默认计入并标注）；gateway/unknown **不计入** | 若不计 sparse：真实 -1、去重 -1 |
| C11 | 分层累计已 51 > 40 上限 | **分层口径停用**，对外只报去重口径 37/40 | 无（仅为口径纠正） |
| C12 | 批 5.1 已定稿（v2 artifact：17 行 pass=16/partial=1/fail=0；fx=fx partial 有损已声明） | 全部计入：协议去重 **40/40**；fx 按 FIXTURE+partial 计入并注明 | 已解决（task-29 定稿） |
| C13 | mini-swe-agent 非 catalog 产品（Harbor 样例/外部框架） | 计入则 40/40；剔除则 39/40（在 B 表注明） | 由 Lead 决定是否把外部框架计入 40 |

### E. 测试证据与复跑命令（自动生成）

| 层 | artifact | 复跑命令 |
|---|---|---|
| 批 1（5×5 方向矩阵） | `tools/agent-session-import/tests/artifacts/interop-matrix.json` | `cd tools/agent-session-import && ./asi matrix --report tests/artifacts/interop-matrix.json --doc ../../docs/interop-matrix.md` |
| 批 2（18 采集标签） | `tools/agent-session-import/tests/artifacts/interop-matrix-batch2.json` | `cd tools/agent-session-import && ./asi matrix-batch2 --root ../../samples/batch2/oss --report tests/artifacts/interop-matrix-batch2.json --doc ../../docs/interop-matrix-batch2.md` |
| 批 3（6 原生 fixture） | `tools/agent-session-import/tests/artifacts/interop-matrix-batch3.json` | `cd tools/agent-session-import && ./asi matrix-batch3 --root ../../samples/batch2/public-fixtures --report tests/artifacts/interop-matrix-batch3.json --doc ../../docs/interop-matrix-batch3.md` |
| 批 4（8 fixture/构造） | `tools/agent-session-import/tests/artifacts/interop-matrix-batch4.json` | `cd tools/agent-session-import && ./asi matrix-batch4 --root ../../samples/batch2/public-fixtures --report tests/artifacts/interop-matrix-batch4.json --doc ../../docs/interop-matrix-batch4.md` |
| 批 5（REAL-LOCAL+构造） | `tools/agent-session-import/tests/artifacts/interop-matrix-batch5.json` | `cd tools/agent-session-import && ./asi matrix-batch5  # 端口以 cli.py 为准；输出 tests/artifacts/interop-matrix-batch5.json + docs/interop-matrix-batch5.md` |

本条账本刷新命令：

```bash
python3 tools/coverage-report.py           # 预览生成的 Markdown 块
python3 tools/coverage-report.py --check   # 校验账本是否过期（exit 1 = 需刷新）
python3 tools/coverage-report.py --write   # 用 artifact 最新数据刷新账本生成段
python3 tools/coverage-report.py --json    # 机器可读摘要（CI 可断言计数）
```

> 数据快照时间（取各 artifact `generated_at` 最大值，UTC）：`2026-10-29T20:10:30Z`｜批 1-5 快照：`2026-10-29T19:10:51Z` / `2026-10-29T19:25:43Z` / `2026-10-29T19:41:20Z` / `2026-10-29T19:47:53Z` / `2026-10-29T20:10:30Z`｜批 5.1：已并入 v2 定稿

<!-- END GENERATED: coverage-ledger -->

---

## 4. 维护指南（手写，后续批次按此操作）

### 4.1 刷新流程（artifact 更新后）

```bash
python3 tools/coverage-report.py           # 预览生成段（不写文件）
python3 tools/coverage-report.py --check   # exit 0 = 最新；exit 1 = 需刷新（CI 用）
python3 tools/coverage-report.py --write   # 只刷新 docs/coverage-ledger.md 标记段
python3 tools/coverage-report.py --json    # 机器可读摘要（三个口径数字）
```

生成段确定性：`generated_at` 取各 artifact 最大值；同一输入重复运行输出一致，`--check` 可靠。

### 4.2 如何新增一个 Harness 行

1. `tools/coverage-report.py` 顶部 `R` 列表加 dict（字段见文件头注释）；`aliases` 填 matrix/采集标签；`kind` 选 `native / collected / fixture3 / batch4 / batch5 / batch51 / ossadd / blocked / candidate / cloud`。
2. 在 `build_summary()` 中补充层/去重算术；REAL-LOCAL/SPARSE 需确认计入 `real_set`；`partial` 行需在 `b5_partial` 单列（不算 fail）。
3. `--write` 后检查生成段 A-E 与 §0/§2 手写数字；D.2 校验未映射标签。

### 4.3 何时升级证据等级

| 场景 | 操作 | 结果 |
|---|---|---|
| 本机真实会话（非原生加载） | matrix 标记 `REAL-LOCAL` | 计入真实+协议；**不是 NATIVE** |
| REAL-LOCAL → NATIVE | 目标 CLI 原生加载（L3）通过 | 升 NATIVE |
| FIXTURE-CONSTRUCTED → FIXTURE | 用上游 fixture/真实文件替换构造（如批 5.1 的 kiro/opencode） | 去构造标注；协议数字不变，主表等级更新 |
| FIXTURE → REAL-LOCAL | 有本机真实会话 | 真实 +1、等级 REAL-LOCAL |
| BLOCKED/CANDIDATE → CONSTRUCTED | 按源码/文档构造 golden sample 并通过 F2 读回 | 计入协议覆盖（标注构造） |
| COLLECTED-SPARSE → COLLECTED | 补采 ≥8 条消息真实会话 | 去稀疏标注；数字不变 |
| **partial → pass** | 修掉有损（如 fx 的 orphan tool_results 表达）并重跑 | 行内去掉 partial 标注；覆盖数字不变 |

### 4.4 数据源与判定命令

| 层 | artifact | 生成时间（UTC） | 复跑命令 |
|---|---|---|---|
| 批 1 | `interop-matrix.json` | 2026-10-29T19:10:51Z | `./asi matrix --report tests/artifacts/interop-matrix.json --doc ../../docs/interop-matrix.md` |
| 批 2 | `interop-matrix-batch2.json` | 2026-10-29T19:25:43Z | `./asi matrix-batch2 --root ../../samples/batch2/oss --report ...` |
| 批 2 oss-add（稀疏） | `samples/batch2/oss-add/` | 2026-10-30 | claude-desktop 计 COLLECTED-SPARSE；gateway/unknown 排除 |
| 批 3 | `interop-matrix-batch3.json` | 2026-10-29T19:41:20Z | `./asi matrix-batch3 --root ../../samples/batch2/public-fixtures --report ...` |
| 批 4 | `interop-matrix-batch4.json` | 2026-10-29T19:47:53Z | `./asi matrix-batch4 --root ../../samples/batch2/public-fixtures --report ...` |
| **批 5/5.1** | `interop-matrix-batch5.json`（**v2 定稿**） | **2026-10-29T20:10:30Z** | `./asi matrix-batch5`（输出 artifact + `docs/interop-matrix-batch5.md`） |

### 4.5 v0.3 定稿记录（已完成）

- 批 5.1 artifact 已定稿：schema `asi-batch5-matrix/v2`、17 行 pass=16/partial=1/fail=0；`kiro` 升 FIXTURE-LOW、`opencode` 升 FIXTURE（既有标签）、新增 codebuddy/fx/mini-swe-agent；converter 与 Lead 均复跑（55/55 测试）。
- 本账本已 `--write` 刷新并 `--check` 通过；下一轮（批 6）新增 artifact 后重复 §4.1 即可。

---

## 5. 已知计数冲突与待确认（摘要；完整清单见生成段 D.4）

| # | 冲突 | 当前处理 | 若确认后的影响 |
|---|---|---|---|
| C1 | `opencraw` ↔ `openclaw` 疑似同一产品 | 按标签分别计 | 去重 -1（40→39） |
| C3 | `cherry-studio`/`workbuddy` 不在 catalog 49 | 按标签计 | 若不算 Harness：去重 -2、真实 -2 |
| C9 | Cline/Roo/Kilo 同族 | 按 3 标签计 | 若合并：去重 -2（不建议） |
| C10 | oss-add：claude-desktop 稀疏；gateway/unknown 中间件 | claude-desktop 计 SPARSE；gateway/unknown 排除 | 若不计 sparse：真实 -1、去重 -1 |
| C11 | 分层累计 54 > 40 上限 | **分层口径停用**，只报去重 40/40 | 无（口径纠正） |
| C13 | mini-swe-agent 为 catalog 外框架 | 默认计入（40/40）；剔除则 39/40 | 由 Lead 决定 |

## 6. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-10-30 | 基线账本（批 1-3 定稿 + 批 4 待确认）；建立 coverage-report.py |
| v0.2 | 2026-10-30 | 批 4 定稿：分层 37 / 去重 27 / 真实 19 |
| v0.3-draft | 2026-10-30 | 纳入批 5：REAL-LOCAL/COLLECTED-SPARSE/DOC-ONLY；去重 37、真实 21；分层 51 停用；批 5.1 未计入 |
| **v0.3 定稿** | 2026-10-30 | 批 5.1 v2 artifact 验收：**去重 40/40（达成 30-40 目标）**、真实 **21/40**、分层 54（停用）；新增去重 13（goose/continue/junie/kiro/crush/roo/codebuff/openhands/vibe/codebuddy/fx/mini-swe-agent/claude-desktop）；kiro→LOW、opencode→FIXTURE 升级；fx partial 有损单列；批 6 缺口清单更新 |

## 7. 限制

- **FIXTURE 级 ≠ 真实会话**：批 3/4/5 多数样本为合成/派生/构造；FIXTURE-LOW（codebuddy/kiro）与 CONSTRUCTED 不得表述为「原生加载通过」。
- **REAL-LOCAL ≠ NATIVE**：gemini/pi 本机真实会话未经过原生加载 L3。
- **partial**：fx 行有损（orphan tool_results + writer 仅文本）已声明，不视为完全通过。
- **真实会话覆盖 21**：NATIVE 5 + COLLECTED 14 + REAL-LOCAL 1（gemini）+ SPARSE 1（claude-desktop）；批 3/4/5 的 FIXTURE/CONSTRUCTED 不计。
- 本账本不记录临时路径；长期证据以 `docs/interop-matrix*.md` 与 `tests/artifacts/*.json` 为准。
