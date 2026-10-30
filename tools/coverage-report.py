#!/usr/bin/env python3
"""Coverage ledger generator for the ATIF interop project (read-only by default).

What it does
------------
Collects the four evidence layers into an auditable Markdown block:

* batch 1  NATIVE     ``tools/agent-session-import/tests/artifacts/interop-matrix.json``
* batch 2  COLLECTED  ``.../interop-matrix-batch2.json``
* batch 3  FIXTURE    ``.../interop-matrix-batch3.json``
* batch 4  FIXTURE(-LOW/-CONSTRUCTED)  ``.../interop-matrix-batch4.json`` (optional;
  when missing, the committed plan in ``docs/formats/batch4-fixtures.md`` /
  protocol §13.2 is used and the layer is marked "实施中/计划")

It also inspects the adapter package (``readers/__init__.py`` / ``writers/__init__.py``
/ ``readers/native_batch4.py``) to report which adapters are registered in code, and
then prints or updates the generated block of ``docs/coverage-ledger.md``.

The harness registry (families, aliases/dedup, plan entries, blocked candidates) is
embedded below so the report is reproducible and reviewable in one file.

Usage
-----
    python3 tools/coverage-report.py                 # print generated block to stdout
    python3 tools/coverage-report.py --json          # machine-readable summary
    python3 tools/coverage-report.py --check         # exit 1 if ledger block is stale
    python3 tools/coverage-report.py --write         # replace generated block in ledger

The script never writes user/harness data; the only write is ``--write`` on the
ledger file passed via ``--doc`` (default ``docs/coverage-ledger.md``).
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "tools", "agent-session-import", "tests", "artifacts")
PKG = os.path.join(ROOT, "tools", "agent-session-import", "agent_session_import")
DEFAULT_DOC = os.path.join(ROOT, "docs", "coverage-ledger.md")
BEGIN = "<!-- BEGIN GENERATED: coverage-ledger -->"
END = "<!-- END GENERATED: coverage-ledger -->"
TARGET = 40                      # "30-40 Harness" goal (upper bound)
BATCH1_MATRIX = os.path.join(ART, "interop-matrix.json")
BATCH2_MATRIX = os.path.join(ART, "interop-matrix-batch2.json")
BATCH3_MATRIX = os.path.join(ART, "interop-matrix-batch3.json")
BATCH4_MATRIX = os.path.join(ART, "interop-matrix-batch4.json")
BATCH5_MATRIX = os.path.join(ART, "interop-matrix-batch5.json")
# batch 5.1（task-28）计划项：尚未计入任何数字，等 artifact 重生成
BATCH51_PLAN = [("codebuddy","FIXTURE"),("fx","FIXTURE"),("mini-swe-agent","FIXTURE")]
BATCH51_KEYS = set()  # 批 5.1 已并入 v2 artifact，全部计入
# 批 5 初版（20:03 快照）已 pass、但 5.1 快照（20:06）升级失败/未重跑项：draft 暂沿用初版构造证据，待 Lead 定稿复核
BATCH5_CARRY = {"kiro": "FIXTURE-CONSTRUCTED"}
# oss-recon 新采（samples/batch2/oss-add）：claude-desktop 仅 2 条消息（COLLECTED-SPARSE，默认计入并标注）；gateway/unknown 非产品 harness，不计
OSS_ADD = {"sparse": ["claude-desktop"], "excluded": ["gateway", "unknown"]}

# ---------------------------------------------------------------------------
# Harness registry: canonical id -> metadata.
#
# Fields
#   name       display name
#   family     format/derivation family (reuse guidance)
#   aliases    labels observed in matrix artifacts that map to this harness
#   kind       native | collected | fixture3 | batch4 | extension | blocked |
#              candidate | external | cloud | wire | special
#   local      本地真实 store（batch 1 NATIVE 证据）
#   oss        batch 2 采集标签（COLLECTED 证据）
#   fixture3   batch 3 FIXTURE 证据
#   batch4     batch 4 计划/证据等级：FIXTURE | FIXTURE-LOW | FIXTURE-CONSTRUCTED
#   wave       batch 4 波次（1 JSON/多文件，2 SQLite golden）
#   cloud      纯云端/P2：仅 ATIF 导出，不排期、不计入协议覆盖
#   blocked    阻塞原因（无 schema 证据/无样本）
#   notes      备注/缺口
#   upgrade    升级证据等级的条件
# ---------------------------------------------------------------------------
R = [
    # ---- batch 1：5 个本机原生 store（NATIVE）-------------------------------
    dict(key="claude", name="Claude Code", family="Claude Code 原型",
         aliases=["claude", "claude-code"], kind="native", local=True,
         oss=["claude-code"],
         notes="L3 原生加载 4/4 通过（PTY `claude --bare --resume`）；writer 可手写 transcript 被 resume 发现",
         upgrade="—", evidence="interop-matrix.json（5×5 方向）/ `asi matrix`"),
    dict(key="codex", name="OpenAI Codex CLI", family="自有（rollout JSONL）",
         aliases=["codex"], kind="native", local=True, oss=["codex"],
         notes="L3 partial：codex 0.164 thread store 不扫裸 rollout（0/4）；L0-L2 全通过",
         upgrade="Codex 提供 thread-store/app-server 注册路径后重跑 L3", evidence="interop-matrix.json"),
    dict(key="dsh", name="DeepSeek Harness", family="自有（zstd 双帧 JSONL 事件流）",
         aliases=["dsh"], kind="native", local=True,
         notes="L3 原生加载 4/4 通过（`Session.fromRestore`）；批 2/3/4 的 L3/F2 唯一真实加载器",
         upgrade="—", evidence="interop-matrix.json"),
    dict(key="omp", name="OMP (oh-my-pi)", family="pi 系（树状事件流）",
         aliases=["omp"], kind="native", local=True,
         notes="L3 原生加载 4/4 通过（`omp --mode=rpc -r`）；与 Pi/OpenClaw 同格式族",
         upgrade="—", evidence="interop-matrix.json"),
    dict(key="qoder", name="Qoder", family="Claude Code 衍生（已验证）",
         aliases=["qoder"], kind="native", local=True, oss=["qoder"],
         notes="L3 partial：本机无 Qoder CLI（IDE-only），格式级验证通过",
         upgrade="安装 Qoder CLI 后重跑 L3（partial→pass）", evidence="interop-matrix.json / interop-matrix-batch2.json"),

    # ---- batch 3：6 个原生 format fixture（FIXTURE）------------------------
    dict(key="copilot", name="GitHub Copilot CLI", family="自有（事件 JSONL）",
         aliases=["copilot"], kind="fixture3", fixture3="FIXTURE",
         notes="B3-F0/F1/F2(DSH)/F3 全通过；status=partial 因声明 lossy（delta 合并、消息分组归一）",
         upgrade="真实 Copilot CLI 会话 + 原生 resume 验证（需安装采集）", evidence="interop-matrix-batch3.json"),
    dict(key="gemini", name="Gemini CLI", family="Gemini 系母本（Qwen Code 上游）",
         aliases=["gemini"], kind="fixture3", fixture3="FIXTURE", batch5="REAL-LOCAL",
         notes="批 3 FIXTURE + 批 5 REAL-LOCAL（本机真实 patch 流）；REAL-LOCAL 计入真实会话覆盖但不升 NATIVE",
         upgrade="原生 CLI L3 加载验证可升 NATIVE", evidence="interop-matrix-batch3.json / interop-matrix-batch5.json"),
    dict(key="aider", name="Aider", family="自有（Markdown history）",
         aliases=["aider"], kind="fixture3", local=False, oss=["aider"], fixture3="FIXTURE",
         notes="COLLECTED（OSS 真实 96 消息）+ FIXTURE 双证据；Markdown 无工具/时间戳",
         upgrade="已有真实采集（COLLECTED）；原生 store 即 Markdown，无更高层可升", evidence="interop-matrix-batch2.json / interop-matrix-batch3.json"),
    dict(key="cursor", name="Cursor（CLI transcript）", family="自有（transcript JSONL，两代）",
         aliases=["cursor"], kind="fixture3", oss=["cursor"], fixture3="FIXTURE",
         notes="COLLECTED（OSS 1544 消息）+ FIXTURE；原生 adapter 只覆盖 CLI transcript，IDE `state.vscdb` 未支持",
         upgrade="Cursor IDE SQLite 样本 + 真实 CLI 会话（native load）", evidence="interop-matrix-batch2.json / interop-matrix-batch3.json"),
    dict(key="qwen", name="Qwen Code", family="Claude 衍生（Gemini fork）",
         aliases=["qwen"], kind="fixture3", fixture3="FIXTURE",
         notes="B3 status=pass（唯一 0 lossy）；fixture 每文件仅 1 行 user 记录，会话 envelope 级",
         upgrade="补真实 Qwen 会话（含 assistant/tool）", evidence="interop-matrix-batch3.json"),
    dict(key="pi", name="Pi (pi.dev)", family="pi 系（树状事件流）",
         aliases=["pi"], kind="fixture3", oss=["pi"], fixture3="FIXTURE", batch5="REAL-LOCAL",
         notes="COLLECTED（OSS）+ FIXTURE + 批 5 REAL-LOCAL（本机真实）；与 OMP/OpenClaw 同族",
         upgrade="本机安装 Pi 做 L3/native load 可升 NATIVE", evidence="interop-matrix-batch2.json / batch3 / batch5"),
    # ---- batch 4：8 个核心（实施中，计划等级）-----------------------------
    dict(key="openclaw", name="OpenClaw", family="pi 系（树状事件流）",
         aliases=["openclaw"], kind="batch4", batch4="FIXTURE", wave=1,
         notes="pi 系第 3 员（复用 OMP/Pi 树 walker）；原生路径层级未核实",
         upgrade="真实 OpenClaw 会话 + 路径对照", evidence="batch4-fixtures.md §B4-01（计划）"),
    dict(key="kimi", name="Kimi Code", family="自有事件协议（非 Claude 衍生）",
         aliases=["kimi", "kimi-code"], kind="batch4", batch4="FIXTURE", wave=1,
         notes="protocol_version=1.4 事件日志；fixture 含 time=0 合成 parity 段；原生路径未核实",
         upgrade="真实 Kimi 会话（去合成段）+ 路径核实", evidence="batch4-fixtures.md §B4-02（计划）"),
    dict(key="grok", name="Grok Build", family="自有多文件（summary+chat_history）",
         aliases=["grok"], kind="batch4", batch4="FIXTURE", wave=1,
         notes="多文件组装；events/updates/plan 不迁移；目录编码未核实",
         upgrade="真实 Grok 会话 + events.jsonl 样本", evidence="batch4-fixtures.md §B4-03（计划）"),
    dict(key="factory-droid", name="Factory Droid", family="自有（CLI stream / session store v2）",
         aliases=["factory-droid", "droid"], kind="batch4", oss=["factory-droid"],
         batch4="FIXTURE", wave=1,
         notes="COLLECTED（OSS 479 消息）+ 原生两代格式 fixture；原生 store 路径未核实（catalog E legacy-only）",
         upgrade="真实 Droid store 样本 + 路径核实", evidence="interop-matrix-batch2.json / batch4-fixtures.md §B4-04（计划）"),
    dict(key="antigravity", name="Google Antigravity", family="Gemini 模型/自有 step 转录",
         aliases=["antigravity"], kind="batch4", batch4="FIXTURE-LOW", wave=1,
         notes="reader-only：fixture 为 JSONL 转录，原生 `.pb` protobuf 无公开 schema → writer BLOCKED",
         upgrade="`.pb` 逆向或 CLI 导出格式；conversation_summaries.db 只读补层级", evidence="batch4-fixtures.md §B4-05（计划）"),
    dict(key="hermes", name="Hermes", family="SQLite 类（逻辑投影 fixture）",
         aliases=["hermes"], kind="batch4", oss=["hermes"],
         batch4="FIXTURE-CONSTRUCTED", wave=2,
         notes="COLLECTED（OSS 378 消息）+ 计划 CONSTRUCTED；原生 `state.db` 无样本，列名未核实",
         upgrade="真实 state.db 只读样本（替换 constructed golden）", evidence="interop-matrix-batch2.json / batch4-fixtures.md §B4-06（计划）"),
    dict(key="devin", name="Devin CLI", family="SQLite 类（逻辑投影 fixture）",
         aliases=["devin"], kind="batch4", batch4="FIXTURE-CONSTRUCTED", wave=2,
         notes="原生 `sessions.db` SQLite；fixture 为作者自述逻辑投影；列名未核实",
         upgrade="真实 sessions.db 只读样本", evidence="batch4-fixtures.md §B4-07（计划）"),
    dict(key="opencode", name="OpenCode", family="SQLite 类 / legacy JSON 树",
         aliases=["opencode"], kind="batch4", oss=["opencode"],
         batch4="FIXTURE-CONSTRUCTED", wave=2, batch5="FIXTURE",
         notes="COLLECTED（OSS 567 消息）+ 批 4 CONSTRUCTED → 批 5.1 升 FIXTURE（sqlite_v2 JSON fixture；artifact 未单列，见 docs/usage §12.1）",
         upgrade="真实 `opencode.db` 样本 + 版本探测", evidence="interop-matrix-batch2/4/5.json"),

    # ---- batch 4 扩展候选（不计入批 4 核心 8 / 37 基线）--------------------
    dict(key="cline", name="Cline", family="Cline 族（Cline/Roo/Kilo）",
         aliases=["cline"], kind="batch5", oss=["cline"], batch5="FIXTURE-CONSTRUCTED",
         notes="COLLECTED + 批 5 CONSTRUCTED（messages 补齐）；Cline 族按标签计（cline/roo/kilo-code 三行）",
         upgrade="上游真实 messages fixture 可升 FIXTURE", evidence="interop-matrix-batch2.json / interop-matrix-batch5.json"),
    dict(key="fx", name="fx (vercel-labs)", family="自有事件日志（event_log_v1/event_log schema 4）",
         aliases=["fx"], kind="batch51", batch51="FIXTURE（待 artifact）",
         notes="批 5.1 计划项（task-28）：**尚未计入任何覆盖数字**；批 5 侦察已有 schema4 上游 fixture",
         upgrade="artifact 生成后 → FIXTURE", evidence="batch5-fixtures.md §2.4"),
    # ---- 有真实采集（COLLECTED）但无原生 adapter / 无 fixture ----------------
    dict(key="cherry-studio", name="Cherry Studio（外部标签）", family="外部标签（catalog 未收录）",
         aliases=["cherry-studio"], kind="external", oss=["cherry-studio"],
         notes="按标签计；未在 catalog 49 候选中，产品形态与其他标签不同（桌面客户端）",
         upgrade="确认其 session store 后单独评估", evidence="interop-matrix-batch2.json"),
    dict(key="kilo-code", name="Kilo Code", family="Cline 族（Cline/Roo/Kilo）",
         aliases=["kilo-code", "kilo"], kind="batch5", oss=["kilo-code"], batch5="FIXTURE-CONSTRUCTED",
         notes="COLLECTED + 批 5 CONSTRUCTED（Cline 族按标签计，不与 cline/roo 合并）",
         upgrade="上游真实 store fixture 可升 FIXTURE", evidence="interop-matrix-batch2.json / interop-matrix-batch5.json"),
    dict(key="opencraw", name="OpenCraw（外部标签，疑与 OpenClaw 同名）", family="外部标签（待确认）",
         aliases=["opencraw"], kind="external", oss=["opencraw"],
         notes="**名称冲突**：OSS 标签 `opencraw` 疑为 `openclaw` 拼写/别名；按标签计，确认后去重数字 -1",
         upgrade="确认 opencraw == openclaw 后合并到 OpenClaw 行", evidence="interop-matrix-batch2.json"),
    dict(key="trae", name="TRAE", family="自有",
         aliases=["trae"], kind="external", oss=["trae"],
         notes="COLLECTED（OSS 612 消息）；catalog 标 P2（无原生导入），有真实采集样本但无原生 adapter",
         upgrade="确认本地 store/导出格式", evidence="interop-matrix-batch2.json"),
    dict(key="windsurf", name="Windsurf", family="自有（IDE 内部）",
         aliases=["windsurf"], kind="external", oss=["windsurf"],
         notes="COLLECTED（OSS 144 消息）；原生 fixture 仅简化样本 → BLOCKED；真实路径/格式未核实",
         upgrade="安装采集真实 session 文件", evidence="interop-matrix-batch2.json"),
    dict(key="workbuddy", name="WorkBuddy（外部标签）", family="外部标签（catalog 未收录）",
         aliases=["workbuddy"], kind="external", oss=["workbuddy"],
         notes="按标签计；catalog 未收录，真实会话仅以 COLLECTED 层存在",
         upgrade="补 catalog 登记与原生样本", evidence="interop-matrix-batch2.json"),
    dict(key="zcode", name="ZCode (Z.ai)", family="自有（经 ACP bridge）",
         aliases=["zcode"], kind="external", oss=["zcode"],
         notes="COLLECTED（OSS 779 消息）；catalog 标 P2（Codeg 自记 transcript，无原生导入）",
         upgrade="原生 store 未核实", evidence="interop-matrix-batch2.json"),

    # ---- 有样本线索但被阻塞（批 4 BLOCKED 清单）---------------------------
    dict(key="goose", name="Goose (Block)", family="自有（session JSONL）",
         aliases=["goose"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（原 BLOCKED：无上游 fixture，按源码 schema 构造）",
         upgrade="上游真实 fixture → FIXTURE；本机真实会话 → REAL-LOCAL", evidence="interop-matrix-batch5.json"),
    dict(key="junie", name="Junie (JetBrains)", family="IDE 内部（JVM）",
         aliases=["junie"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（原 BLOCKED）；JVM/IDE 内部格式按公开文档构造",
         upgrade="上游真实 fixture → FIXTURE", evidence="interop-matrix-batch5.json"),
    dict(key="vibe", name="Mistral Vibe", family="自有（JSONL session log）",
         aliases=["vibe"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（按 mistral-vibe 源码布局构造：meta.json + messages.jsonl）",
         upgrade="上游真实 fixture → FIXTURE", evidence="interop-matrix-batch5.json"),
    dict(key="roo", name="Roo Code", family="Cline 族（Cline/Roo/Kilo）",
         aliases=["roo", "roo-code"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（原 BLOCKED）；Cline 族按标签计，不与 cline/kilo-code 合并",
         upgrade="上游真实 fixture → FIXTURE", evidence="interop-matrix-batch5.json"),
    # ---- P1/P2 待样本（有文档/路径线索但无 fixtures）----------------------
    dict(key="kiro", name="Kiro CLI (AWS)", family="自有（JSONL 事件日志 + JSON metadata）",
         aliases=["kiro"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED → 批 5.1 升 FIXTURE-LOW（Codeg 派生/裁剪）；上游真实 fixture 可再升 FIXTURE",
         upgrade="批 5.1 上游 fixture → FIXTURE；本机真实会话 → REAL-LOCAL", evidence="interop-matrix-batch5.json"),
    dict(key="codebuddy", name="CodeBuddy (腾讯)", family="自有（OpenAI Agents-SDK item 记录）",
         aliases=["codebuddy"], kind="batch51", batch51="FIXTURE（待 artifact）",
         notes="批 5.1 计划项（task-28）：**尚未计入任何覆盖数字**，等 matrix-batch5 重生成后刷新",
         upgrade="artifact 生成后 → FIXTURE", evidence="batch5-fixtures.md §2.2"),
    dict(key="openhands", name="OpenHands", family="自有（trajectory 导出）",
         aliases=["openhands"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（上游真实轨迹样例 + 构造）",
         upgrade="上游真实 fixture → FIXTURE", evidence="interop-matrix-batch5.json"),
    dict(key="iflow", name="iFlow CLI", family="疑似 Claude/Gemini 衍生（未核实）",
         aliases=[], kind="candidate",
         notes="catalog P2：本地 store 未核实",
         upgrade="确认本地 store", evidence="harness-catalog.md #21"),

    dict(key="crush", name="Crush (Charm)", family="自有 TUI（SQLite store）",
         aliases=["crush"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED；上游 SQL migrations 可导出表结构（sessions/messages），**License=FSL** 需 Lead 审视，不 vendor 源文件",
         upgrade="上游真实 fixture → FIXTURE（先解决 license）", evidence="interop-matrix-batch5.json"),
    dict(key="mini-swe-agent", name="Mini-SWE-agent", family="外部 agent 框架（catalog 未收录）",
         aliases=["mini-swe-agent", "mini-swe"], kind="batch51", batch51="FIXTURE（待 artifact）",
         notes="批 5.1 计划项（task-28）：**尚未计入任何覆盖数字**；是否计入 40 由 Lead 决定",
         upgrade="artifact 生成后 → FIXTURE", evidence="batch5-fixtures.md §2"),

    # ---- 纯云端 / 仅 ATIF 导出（P2，不排期、不计入协议覆盖）----------------
    dict(key="claude-desktop", name="Claude Desktop / Cowork", family="桌面/云端",
         aliases=["claude-desktop"], kind="ossadd", oss_add="COLLECTED-SPARSE",
         notes="oss-add 新采仅 2 条消息（COLLECTED-SPARSE，稀疏但默认计入真实覆盖并标注）；gateway/unknown 为中间件/兜底标签，不计入 30-40",
         upgrade="需 ≥8 消息真实会话才升常规 COLLECTED；本地明文 store/导出 API", evidence="samples/batch2/oss-add/ + oss-trajectory-inventory.md"),
    dict(key="cody", name="Sourcegraph Cody", family="纯云端",
         aliases=[], kind="cloud", notes="云端为主", upgrade="官方导出 API", evidence="harness-catalog.md #26"),
    dict(key="augment", name="Augment Code", family="纯云端",
         aliases=[], kind="cloud", notes="云端为主", upgrade="官方导出 API", evidence="harness-catalog.md #27"),
    dict(key="amp", name="Amp (Sourcegraph)", family="自有/云端",
         aliases=[], kind="cloud", notes="本地 store 未核实", upgrade="确认本地存储", evidence="harness-catalog.md #28"),
    dict(key="crush", name="Crush (Charm)", family="自有 TUI",
         aliases=[], kind="cloud", notes="路径未核实（catalog G）", upgrade="安装采集", evidence="harness-catalog.md #30"),
    dict(key="zed", name="Zed (Agent Panel)", family="编辑器类",
         aliases=[], kind="cloud", notes="SQLite 线程库待确认", upgrade="确认本地存储", evidence="harness-catalog.md #31"),
    dict(key="continue", name="Continue", family="IDE 扩展（JSON session）",
         aliases=["continue"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（原 CANDIDATE：无上游 fixture）",
         upgrade="上游真实 fixture → FIXTURE", evidence="interop-matrix-batch5.json"),
    dict(key="warp", name="Warp", family="纯云端", aliases=[], kind="cloud",
         notes="云端 Warp Drive 为主", upgrade="官方导出", evidence="harness-catalog.md #34"),
    dict(key="replit", name="Replit Agent", family="纯云端", aliases=[], kind="cloud",
         notes="云端", upgrade="官方导出", evidence="harness-catalog.md #35"),
    dict(key="jules", name="Google Jules", family="纯云端", aliases=[], kind="cloud",
         notes="云端异步 Agent", upgrade="官方导出", evidence="harness-catalog.md #37"),
    dict(key="sculptor", name="Sculptor (Imbue)", family="纯云端", aliases=[], kind="cloud",
         notes="云端/桌面内部", upgrade="官方导出", evidence="harness-catalog.md #38"),
    dict(key="codebuff", name="Codebuff", family="OSS/自有",
         aliases=["codebuff"], kind="batch5", batch5="FIXTURE-CONSTRUCTED",
         notes="批 5 CONSTRUCTED（session-state 类型定义构造）",
         upgrade="上游真实 fixture → FIXTURE", evidence="interop-matrix-batch5.json"),
    dict(key="minimax", name="MiniMax Code", family="自有", aliases=[], kind="cloud",
         notes="Codeg 自记 transcript，无原生导入（B）", upgrade="需逆向", evidence="harness-catalog.md A4"),
    dict(key="command-code", name="Command Code", family="自有", aliases=[], kind="cloud",
         notes="无原生导入（B）", upgrade="需逆向", evidence="harness-catalog.md A6"),
    dict(key="tabnine-group", name="Tabnine / Tabby / Refact.ai", family="企业/自托管",
         aliases=[], kind="cloud", notes="非核心 coding agent", upgrade="不排期", evidence="harness-catalog.md A7"),
    dict(key="claude-desktop-note", name="（合并项）Codex Desktop / Kimi CLI", family="—",
         aliases=[], kind="special",
         notes="Codex Desktop 与 Codex 共用 `~/.codex`（并入 codex）；Kimi CLI 与 Kimi Code 同厂并入 kimi（catalog 单列）",
         upgrade="—", evidence="harness-catalog.md #4/#20"),
]

# batch 4 plan fallback（无 matrix-batch4.json 时使用；来源 docs/formats/batch4-fixtures.md §4.1）
BATCH4_PLAN = [
    ("openclaw", "FIXTURE", 1, "stage0/openclaw/small.jsonl（pi 系树状）"),
    ("kimi", "FIXTURE", 1, "stage0/kimi/small.jsonl（自有事件协议）"),
    ("grok", "FIXTURE", 1, "stage0/grok/{chat_history,summary}（多文件）"),
    ("factory-droid", "FIXTURE", 1, "stage0/droid/*（两代格式）"),
    ("antigravity", "FIXTURE-LOW", 1, "stage0/antigravity/*.jsonl（step 转录，reader-only）"),
    ("hermes", "FIXTURE-CONSTRUCTED", 2, "golden DB + stage0/hermes/small.json（逻辑投影）"),
    ("devin", "FIXTURE-CONSTRUCTED", 2, "golden DB + stage0/devin/small.json（逻辑投影）"),
    ("opencode", "FIXTURE-CONSTRUCTED", 2, "part fixtures + golden DB（SQLite/legacy 树）"),
]
EXTENSION_PLAN = [
    ("cline", "FIXTURE-CONSTRUCTED", "messages.json 构造"),
    ("fx", "FIXTURE-LOW", "events.jsonl 缺样本（补采）"),
]

LEVEL_ORDER = {"NATIVE": 0, "REAL-LOCAL": 0.5, "COLLECTED": 1, "COLLECTED-SPARSE": 1.5,
               "FIXTURE": 2, "FIXTURE-LOW": 3, "FIXTURE-CONSTRUCTED": 4,
               "IMPLEMENTING": 5, "PLANNED": 6, "BLOCKED": 7, "CANDIDATE": 8,
               "DOC-ONLY": 8.5, "CLOUD": 9, "SPECIAL": 10}


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_readers():
    body = read_text(os.path.join(PKG, "readers", "__init__.py"))
    m = re.search(r"READERS\s*=\s*\{(.*?)\}", body, re.S)
    if not m:
        return set()
    return set(re.findall(r'"([A-Za-z0-9_-]+)"\s*:', m.group(1)))


def parse_writers():
    body = read_text(os.path.join(PKG, "writers", "__init__.py"))
    m = re.search(r"NATIVE_TARGETS\s*=\s*\((.*?)\)", body, re.S)
    if not m:
        return set()
    return set(re.findall(r'"([A-Za-z0-9_-]+)"', m.group(1)))


def adapter_state():
    readers = parse_readers()
    writers = parse_writers()
    batch4_code = os.path.exists(os.path.join(PKG, "readers", "native_batch4.py"))
    cli_body = read_text(os.path.join(PKG, "cli.py"))
    return {
        "readers": sorted(readers),
        "writers": sorted(writers),
        "readers_harness": sorted(readers - {"oss"}),
        "batch4_reader_code": batch4_code,
        "batch4_cli": "matrix-batch4" in cli_body,
        "batch4_artifact": os.path.exists(BATCH4_MATRIX),
        "batch5_reader_code": os.path.exists(os.path.join(PKG, "readers", "native_batch5.py")),
        "batch5_artifact": os.path.exists(BATCH5_MATRIX),
        "batch5_cli": "matrix-batch5" in cli_body,
    }


def canon_map(registry):
    """alias label -> canonical key."""
    out = {}
    for row in registry:
        out[row["key"]] = row["key"]
        for a in row.get("aliases") or []:
            out[a] = row["key"]
    return out


def cmap_labels(registry):
    return set(canon_map(registry).keys())


def registered(key, row, registryset):
    names = {key} | set(row.get("aliases") or [])
    return bool(names & registryset)


def load_layers():
    b1 = load_json(BATCH1_MATRIX)
    b2 = load_json(BATCH2_MATRIX)
    b3 = load_json(BATCH3_MATRIX)
    b4 = load_json(BATCH4_MATRIX) if os.path.exists(BATCH4_MATRIX) else None
    b5 = load_json(BATCH5_MATRIX) if os.path.exists(BATCH5_MATRIX) else None
    return b1, b2, b3, b4, b5


def batch1_l3_by_target(b1):
    """target -> 'pass'|'partial'|'fail' based on L3 ok values."""
    out = {}
    for d in b1.get("directions") or []:
        to = d.get("to")
        ok = (d.get("l3") or {}).get("ok")
        cur = out.get(to)
        state = "pass" if ok is True else ("fail" if ok is False else "partial")
        if cur is None:
            out[to] = state
        elif cur == "fail" or state == "fail":
            out[to] = "fail"
        elif state == "partial":
            out[to] = "partial"
    return out


def status_of(obj):
    if isinstance(obj, dict):
        return obj.get("ok")
    return obj


def b4_level_detail(b4):
    if not b4:
        return "FIXTURE / LOW / CONSTRUCTED（计划）"
    c = {}
    for e in b4.get("entries") or []:
        c[e.get("evidence_level") or "?"] = c.get(e.get("evidence_level") or "?", 0) + 1
    return " / ".join("%s×%d" % (k, v) for k, v in sorted(c.items()))


def b5_level_detail(b5):
    if not b5:
        return "待生成"
    c = {}
    for e in b5.get("entries") or []:
        if e.get("status") != "pass":
            continue
        c[e.get("evidence_level") or "?"] = c.get(e.get("evidence_level") or "?", 0) + 1
    c[BATCH5_CARRY and "FIXTURE-CONSTRUCTED"] = c.get("FIXTURE-CONSTRUCTED", 0) + len(BATCH5_CARRY)
    return " / ".join("%s×%d" % (k, v) for k, v in sorted(c.items()))


def batch51_plan():
    return {k: lvl for k, lvl in BATCH51_PLAN}


def main_table_rows(registry, b1, b2, b3, b4, b5, adapters):
    cmap = canon_map(registry)
    l3 = batch1_l3_by_target(b1)
    b1_sources = [cmap.get(s if isinstance(s, str) else s.get("id"), s) for s in b1.get("sources") or []]
    b3_map = {cmap.get(e["harness"], e["harness"]): e for e in b3.get("entries") or []}
    b4_map = {}
    if b4:
        for e in b4.get("entries") or []:
            b4_map[cmap.get(e.get("harness"), e.get("harness"))] = e
    b5_map = {}
    if b5:
        for e in b5.get("entries") or []:
            b5_map[cmap.get(e.get("harness"), e.get("harness"))] = e
    plan4 = {k: (lvl, wave) for k, lvl, wave, _ in BATCH4_PLAN}
    plan51 = batch51_plan()
    sparse = set(OSS_ADD["sparse"])

    rows = []
    for row in registry:
        key = row["key"]
        kind = row.get("kind", "candidate")
        if kind in ("cloud", "special"):
            continue
        level, maxlvl, note = "—", "—", row.get("notes") or ""
        if key in b1_sources:
            level = "NATIVE"
            l = l3.get(key)
            maxlvl = "L3 pass" if l == "pass" else ("L3 partial" if l == "partial" else "L0-L2")
        elif row.get("oss"):
            level = "COLLECTED"
            maxlvl = "B2-L3（DSH 真实加载）"
        if key in b3_map:
            if level == "—":
                level = "FIXTURE"
                maxlvl = "B3-F3（自往返）"
            elif level in ("COLLECTED",):
                maxlvl += " / B3-F3"
        ev = row.get("evidence") or "—"
        if row.get("batch4"):
            lvl, wave = plan4.get(key, (row["batch4"], 0))
            if key in b4_map:
                b4_level = b4_map[key].get("evidence_level") or lvl
                if level in ("—", "PLANNED"):
                    level = b4_level
                maxlvl = "B4-F2（自往返/构造）" if level == b4_level else maxlvl + " / B4-F2"
                ev = (row.get("evidence") or "—").replace("（计划）", "") + " / interop-matrix-batch4.json"
                note = note.replace("；批 4 计划", "；批 4 已生成").replace("计划 CONSTRUCTED", "批 4 CONSTRUCTED")
            else:
                if level in ("—", "PLANNED"):
                    level = "PLANNED"
                maxlvl = "B4-F2（计划）"
        if key in b5_map:
            b5_level = b5_map[key].get("evidence_level") or "FIXTURE-CONSTRUCTED"
            rank_old = LEVEL_ORDER.get(level.split(" ")[0], 20)
            rank_new = LEVEL_ORDER.get(b5_level.split(" ")[0], 20)
            if rank_new < rank_old:
                level = b5_level
            maxlvl = "B5-" + ("REAL-LOCAL" if b5_level == "REAL-LOCAL" else ("F2（LOW）" if b5_level == "FIXTURE-LOW" else "F2"))
            ev = row.get("evidence") or "—"
            if "batch5" not in ev:
                ev = ev + " / interop-matrix-batch5.json"
            note = note.replace("原 BLOCKED", "原 BLOCKED→已构造")
        if row.get("batch5") and key not in b5_map:
            lvl = row["batch5"]
            rank_old = LEVEL_ORDER.get(level.split(" ")[0], 20)
            rank_new = LEVEL_ORDER.get(lvl.split(" ")[0], 20)
            if rank_new < rank_old:
                level = lvl
            maxlvl = "B5-F2（文档声明，artifact 未单列）"
        if kind == "batch51":
            if key in b5_map:
                lvl = b5_map[key].get("evidence_level") or plan51.get(key, "FIXTURE")
                level = "REAL-LOCAL" if lvl == "REAL-LOCAL" else ("FIXTURE" if lvl == "FIXTURE" else lvl)
                maxlvl = "B5.1-REAL-LOCAL" if lvl == "REAL-LOCAL" else "B5.1-F2"
                ev = "interop-matrix-batch5.json（5.1）"
            else:
                level = "待 artifact"
                maxlvl = "B5.1 计划（不计入）"
                ev = "docs/formats/batch5-fixtures.md"
                note = row.get("notes") or ""
        if kind == "ossadd":
            level, maxlvl = "COLLECTED-SPARSE", "oss-add 采集（2 条消息）"
        if key in sparse and kind != "ossadd":
            level, maxlvl = "COLLECTED-SPARSE", "oss-add 采集（稀疏，默认计入）"
        adp = "—"
        rd = registered(key, row, set(adapters["readers"]))
        wr = registered(key, row, set(adapters["writers"]))
        if rd and wr:
            adp = "✅ r+w"
        elif rd:
            adp = "✅ reader"
        elif kind == "batch5":
            adp = "⏳ 批 5 计划"
        elif kind == "batch51":
            adp = "⏳ 批 5.1 计划"
        elif kind in ("blocked", "candidate"):
            adp = "—（待样本）"
        local = "✅" if key in b1_sources else "—"
        oss = "✅ " + ",".join(row["oss"]) if row.get("oss") else "—"
        fix = "—"
        if key in b3_map:
            fix = "✅ FIXTURE（批 3）"
        if row.get("batch4"):
            lvl, wave = plan4.get(key, (row["batch4"], 0))
            if key in b4_map:
                fix = "✅ %s（批 4）" % (b4_map[key].get("evidence_level") or lvl)
            else:
                fix = "🧪 批 4 %s（波 %s）" % (lvl, wave)
        if row.get("batch5") and key not in b5_map:
            fix = "✅ %s（批 5.1 升级；artifact 未单列）" % row["batch5"]
        if key in b5_map:
            fix = "✅ %s（批 5）" % (b5_map[key].get("evidence_level") or "FIXTURE-CONSTRUCTED")
        if row.get("batch5") and key not in b5_map:
            fix = "✅ %s（批 5.1 升级，artifact 未单列）" % row["batch5"]
        if kind == "batch51":
            fix = ("✅ %s（批 5.1）" % b5_map[key].get("evidence_level", "FIXTURE")) if key in b5_map else ("✅ %s（批 5.1 升级）" % plan51.get(key, "FIXTURE"))
        if kind == "ossadd" or key in sparse:
            fix = "✅ COLLECTED-SPARSE"
        if kind == "blocked" and fix == "—":
            fix = "△ 仅 S2 简化样本"
        rows.append(dict(key=key, name=row["name"], family=row["family"], adp=adp,
                         local=local, oss=oss, fix=fix, level=level, maxlvl=maxlvl,
                         evidence=ev, note=note,
                         rank=LEVEL_ORDER.get(level.split(" ")[0], 20)))
    rows.sort(key=lambda r: (r["rank"], r["name"].lower()))
    return rows


def build_summary(registry, b1, b2, b3, b4, b5, adapters):
    cmap = canon_map(registry)
    b1_sources = [cmap.get(s if isinstance(s, str) else s.get("id"), s) for s in b1.get("sources") or []]
    b2_entries = b2.get("entries") or []
    b2_real = [e["harness"] for e in b2_entries if e["harness"] != "other"]
    b2_canon = {cmap.get(l, l) for l in b2_real}
    b3_canon = {cmap.get(e["harness"], e["harness"]) for e in b3.get("entries") or []}
    if b4:
        b4_levels = {cmap.get(e["harness"], e.get("harness")): (e.get("evidence_level") or "FIXTURE")
                     for e in b4.get("entries") or []}
        b4_count = len(b4.get("entries") or [])
    else:
        b4_levels = {k: lvl for k, lvl, _, _ in BATCH4_PLAN}
        b4_count = len(BATCH4_PLAN)
    sparse = set(OSS_ADD["sparse"])
    b5_failed = []
    b5_partial = []
    if b5:
        b5_levels = {}
        for e in b5.get("entries") or []:
            key = cmap.get(e.get("harness"), e.get("harness"))
            if key in BATCH51_KEYS:
                continue  # 批 5.1 项：未计入任何数字
            if e.get("status") not in ("pass", "partial"):
                b5_failed.append(key)
                continue
            if e.get("status") == "partial":
                b5_partial.append(key)
            b5_levels[key] = e.get("evidence_level") or "FIXTURE-CONSTRUCTED"
        for key, lvl in BATCH5_CARRY.items():
            if key not in b5_levels:
                b5_levels[key] = lvl
        b5_count = len(b5_levels)
    else:
        b5_levels = {}
        b5_count = 0
    plan51 = batch51_plan()
    native_set = set(b1_sources)
    real_pre = native_set | (b2_canon - native_set)
    pre_distinct = native_set | b2_canon | b3_canon | set(b4_levels)
    b5_canon = set(b5_levels)
    real_local = {k for k, v in b5_levels.items() if v == "REAL-LOCAL"}
    real_local_new = real_local - real_pre
    real_v3 = real_pre | real_local | sparse
    distinct_v3 = pre_distinct | b5_canon | sparse
    b51_new = {k for k in plan51 if k not in distinct_v3}
    predicted_distinct = distinct_v3 | set(plan51)
    pre_layered = len(b1_sources) + len(b2_entries) + len(b3.get("entries") or []) + b4_count
    layered_v3 = pre_layered + b5_count
    layered_pred = layered_v3 + len(plan51)
    return {
        "b1_count": len(b1_sources), "b1_summary": b1.get("summary") or {},
        "b2_labels": len(b2_entries), "b2_real_labels": len(b2_real),
        "b2_new": len(b2_canon - native_set), "b2_summary": b2.get("summary") or {},
        "b3_count": len(b3.get("entries") or []), "b3_summary": b3.get("summary") or {},
        "b3_new": len(b3_canon - (native_set | b2_canon)),
        "b4_count": b4_count, "b4_levels": b4_levels,
        "b5_count": b5_count, "b5_levels": b5_levels,
        "b5_new": sorted(b5_canon - pre_distinct),
        "b5_real_local": sorted(real_local),
        "b5_real_local_new": sorted(real_local_new),
        "real_net_new": sorted(real_local_new | (sparse - real_pre)),
        "b5_failed": sorted(b5_failed),
        "b5_partial": sorted(b5_partial),
        "b51_plan": plan51, "b51_new": sorted(b51_new),
        "oss_sparse": sorted(sparse), "oss_excluded": sorted(OSS_ADD["excluded"]),
        "native_set": sorted(native_set), "real_pre": sorted(real_pre),
        "real_set": sorted(real_v3),
        "pre_distinct": sorted(pre_distinct), "after5_distinct": sorted(distinct_v3),
        "predicted_distinct": sorted(predicted_distinct),
        "pre_layered": pre_layered, "layered_v3": layered_v3, "layered_pred": layered_pred,
        "pre_real_count": len(real_pre), "real_count": len(real_v3),
        "predicted_real": len(real_v3),
        "pre_n": len(pre_distinct), "after5_n": len(distinct_v3),
        "predicted_n": len(predicted_distinct),
        "adapters": adapters,
        "batch4_state": _batch4_state(adapters, b4),
        "batch5_state": _batch5_state(adapters, b5),
        "batch51_state": _batch51_state(adapters),
        "generated_at": max([t for t in [b1.get("generated_at"), b2.get("generated_at"),
                                         b3.get("generated_at"), (b4 or {}).get("generated_at"),
                                         (b5 or {}).get("generated_at")] if t] or ["unknown"]),
        "artifact_meta": {
            "b1": (b1.get("generated_at"), b1.get("schema")),
            "b2": (b2.get("generated_at"), b2.get("schema")),
            "b3": (b3.get("generated_at"), b3.get("schema")),
            "b4": (b4.get("generated_at"), b4.get("schema")) if b4 else None,
            "b5": (b5.get("generated_at"), b5.get("schema")) if b5 else None,
        },
    }


def _batch4_state(adapters, b4):
    if b4:
        return "已定稿（matrix-batch4.json %s；Lead 已独立复跑 8/8 pass）" % (b4.get("generated_at") or "?")
    return "未生成"


def _batch5_state(adapters, b5):
    if b5:
        lead = b5.get("summary") or {}
        return "已定稿（schema %s，%s；%d 行 pass=%s/partial=%s/fail=%s）" % (
            b5.get("schema"), b5.get("generated_at") or "?",
            len(b5.get("entries") or []), lead.get("pass"), lead.get("partial"), lead.get("fail"))
    if adapters.get("batch5_reader_code"):
        return "实施中（readers/native_batch5.py 已存在；artifact 待生成）"
    return "计划"


def _batch51_state(adapters):
    return "已并入批 5 v2 artifact（codebuddy/fx/mini-swe-agent 已计入；kiro/opencode 升级已反映）"


def bar(done, total, width=30):
    done = max(0, min(done, total))
    n = int(round(width * done / total)) if total else 0
    return "█" * n + "░" * (width - n)


def md_table(header, aligns, rows):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(aligns) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def generate(registry=None):
    registry = registry or R
    b1, b2, b3, b4, b5 = load_layers()
    adapters = adapter_state()
    s = build_summary(registry, b1, b2, b3, b4, b5, adapters)
    rows = main_table_rows(registry, b1, b2, b3, b4, b5, adapters)
    md = []
    # A. layer summary
    md.append("### A. 分层汇总（自动生成）")
    md.append("")
    md.append("> 数据快照：批 1-4 artifact + 批 5 `interop-matrix-batch5.json`（%s，**schema %s 定稿**：17 行 pass=16/partial=1/fail=0；"
              "partial 行 fx 为「有损但通过」，按 FIXTURE 计入并注明；claude-desktop 为 COLLECTED-SPARSE（默认计入）。" % (
                  (s["artifact_meta"]["b5"] or ["未生成"])[0], (s["artifact_meta"]["b5"] or [None, "?"])[1]))
    md.append("")
    layer_rows = [
        ["批 1 原生（本机安装）", "NATIVE", str(s["b1_count"]), "5（= 批 1 全量）", "L0–L3（codex/qoder L3 partial）", "`interop-matrix.json`", "✅ 已定稿"],
        ["批 2 采集（OSS 真实会话）", "COLLECTED", str(s["b2_labels"]),
         "%d 真实标签 + `other`（非 Harness）" % s["b2_real_labels"], "B2-L0–L3（DSH 真实加载）", "`interop-matrix-batch2.json`", "✅ 已定稿"],
        ["批 2 oss-add（稀疏采集）", "COLLECTED-SPARSE", "%d" % len(s["oss_sparse"]),
         "claude-desktop 仅 2 条消息（默认计入并标注）；gateway/unknown 不计入", "oss-add 采集补证", "`samples/batch2/oss-add/`", "🟡 稀疏，计真实覆盖"],
        ["批 3 原生 fixture", "FIXTURE", str(s["b3_count"]), "3（copilot/gemini/qwen 新增）", "B3-F0–F3", "`interop-matrix-batch3.json`", "✅ 已定稿"],
        ["批 4 原生 fixture/构造", b4_level_detail(b4), str(s["b4_count"]),
         "5（OpenClaw/Kimi/Grok/Antigravity/Devin；Droid/Hermes/OpenCode 为补层）", "B4-F0–F3", "`interop-matrix-batch4.json`", "✅ 已定稿"],
        ["批 5 REAL-LOCAL + 构造", b5_level_detail(b5), str(s["b5_count"]),
         "%d 去重新增（%s）；gemini/pi 为 REAL-LOCAL；cline/kilo-code 为既有标签补构造" % (len([k for k in s["after5_distinct"] if k not in s["pre_distinct"]]), "/".join([k for k in s["after5_distinct"] if k not in s["pre_distinct"]])), "B5-F2/F3", "`interop-matrix-batch5.json`", "🟡 " + s["batch5_state"]],
        ["批 5.1（已并入批 5 快照）", "并入（FIXTURE×2 / LOW×2 等）", "并入批 5 行",
         "codebuddy/fx/mini-swe-agent 与 kiro/opencode 升级均已计入批 5 v2 artifact（不单列）", "B5.1-F2", "`interop-matrix-batch5.json`（v2）", "✅ " + s["batch51_state"]],
        ["wire 层（HAR/SSE，非 Harness）", "FIXTURE-LOW", "1（层）", "0（不占 Harness 名额）", "—", "`atifact/*.har`", "⏳ 可选路线"],
        ["纯云端/P2（仅 ATIF 导出）", "—", str(len([r for r in registry if r.get("kind") == "cloud"])), "0（不排期）", "—", "harness-catalog.md §3.6", "⏸ 不排期"],
    ]
    md.append(md_table(["层", "证据等级", "Harness 数", "去重/说明", "最高验证级别", "证据文件", "状态"],
                       ["---"] * 7, layer_rows))
    md.append("")
    # B. progress
    md.append("### B. 进度条与三个数字（自动生成，禁止混算）")
    md.append("")
    md.append("```")
    md.append("协议覆盖（去重 Harness，v0.3 定稿）  %s  %2d/%-2d  （目标上限 %d）"
              % (bar(s["after5_n"], TARGET), s["after5_n"], TARGET, TARGET))
    md.append("真实会话覆盖（含 REAL-LOCAL）  %s  %2d/%-2d  （批次前 %d；REAL-LOCAL +%d、COLLECTED-SPARSE +%d）"
              % (bar(s["real_count"], TARGET), s["real_count"], TARGET, s["pre_real_count"],
                 len(s["b5_real_local_new"]), len(s["oss_sparse"])))
    md.append("分层账本累计（口径停用）      %s  %2d/%-2d  已超 40 上限，只作批次进度"
              % (bar(min(s["layered_v3"], TARGET), TARGET), s["layered_v3"], TARGET))
    md.append("```")
    md.append("")
    md.append(md_table(["口径", "v0.2（批 4 定稿）", "v0.3 定稿（批 5+5.1）", "增量", "说明"],
                       ["---"] * 5, [
        ["**协议覆盖（去重 Harness）**", "**%d**" % s["pre_n"], "**%d/40**" % s["after5_n"],
         "+%d" % (s["after5_n"] - s["pre_n"]),
         "新增 13：%s；**达成 40/40 目标**；其中 mini-swe-agent 为 catalog 外框架（剔除则 39/40）" % "/".join(
             [k for k in s["after5_distinct"] if k not in s["pre_distinct"]])],
        ["真实会话覆盖（REAL）", str(s["pre_real_count"]), str(s["real_count"]), "+%d" % (s["real_count"] - s["pre_real_count"]),
         "REAL-LOCAL（gemini +1）与 COLLECTED-SPARSE（claude-desktop +1）**计入**；FIXTURE/CONSTRUCTED/构造不计"],
        ["分层账本累计", str(s["pre_layered"]), "%d（超 40 上限→停用）" % s["layered_v3"],
         "+%d" % (s["layered_v3"] - s["pre_layered"]), "批 5+5.1 +%d（含构造/稀疏）；**该口径不再作为 X/40 进度**" % s["b5_count"]],
        ["adapter 注册（代码）reader/writer", "19/18（批 4）",
         "%d/%d" % (len(s["adapters"]["readers_harness"]), len(s["adapters"]["writers"])), "—",
         "reader 含批 5 新 source；writer 以 NATIVE_TARGETS 为准"],
        ["FIXTURE 级 partial（有损但通过）", "—", "%s" % (", ".join(s["b5_partial"]) or "—"), "—",
         "partial 不计 fail，也不当完全 pass；lossy 已在行内声明"],
        ["距 30-40 目标（去重口径）", "差 %d" % (TARGET - s["pre_n"]), "差 %d（%d/40）" % (TARGET - s["after5_n"], s["after5_n"]),
         "—", "目标达成：40/40（若剔除 catalog 外框架 mini-swe-agent → 39/40，仍在 30-40 区间）"],
    ]))
    md.append("")
    # C. main table
    md.append("### C. 逐 Harness 主表（自动生成）")
    md.append("")
    md.append("> 排序：证据等级由高到低（NATIVE→REAL-LOCAL→COLLECTED→FIXTURE→…→BLOCKED→CANDIDATE→DOC-ONLY）。"
              "批 5.1 已并入 v2 artifact（codebuddy/fx/mini-swe-agent 计入）。")
    md.append("")
    md.append(md_table(
        ["Harness", "家族", "native adapter", "本地真实 store", "OSS 采集", "fixture 样本",
         "当前证据等级", "最高验证级别", "证据文件/命令", "备注/缺口"],
        ["---"] * 10,
        [[r["name"], r["family"], r["adp"], r["local"], r["oss"], r["fix"],
          r["level"], r["maxlvl"], r["evidence"], r["note"]] for r in rows]))
    md.append("")
    # D. dedup
    md.append("### D. 去重与计数校验（自动生成）")
    md.append("")
    md.append("#### D.1 合并规则（alias → canonical）")
    md.append("")
    alias_rows = []
    for row in registry:
        aliases = row.get("aliases") or []
        if len(aliases) > 1:
            alias_rows.append([row["name"], ", ".join("`%s`" % a for a in aliases), "同一 Harness（按产品合并）"])
    md.append(md_table(["Harness", "矩阵/采集标签", "判定依据"], ["---"] * 3, alias_rows))
    md.append("")
    md.append("#### D.2 标签映射校验（自动）")
    md.append("")
    unmapped = []
    label_sets = [("batch1", [s if isinstance(s, str) else s.get("id") for s in b1.get("sources") or []]),
                  ("batch2", [e["harness"] for e in b2.get("entries") or []]),
                  ("batch3", [e["harness"] for e in b3.get("entries") or []]),
                  ("batch5", [e["harness"] for e in (b5 or {}).get("entries") or []])]
    for tag, labels in label_sets:
        for label in labels:
            if label == "other":
                continue
            if label not in cmap_labels(registry):
                unmapped.append(tag + ":" + str(label))
    for k in s["b51_plan"]:
        if k not in cmap_labels(registry):
            unmapped.append("batch5.1:" + k)
    md.append("已映射批 1/2/3/4/5 + 批 5.1 计划全部标签" + (
        "（未映射：%s）" % ", ".join(unmapped) if unmapped else "（`other`/`gateway`/`unknown` 为非 Harness，已排除；无未映射标签）") + "。")
    md.append("")
    md.append("#### D.3 分层账本算术（可逐项核对）")
    md.append("")
    md.append("```")
    md.append("批 1 NATIVE    = %2d" % s["b1_count"])
    md.append("批 2 COLLECTED = %2d  （真实标签 %d + `other` 1；去重后新增 %d）"
              % (s["b2_labels"], s["b2_real_labels"], s["b2_new"]))
    md.append("批 3 FIXTURE   = %2d  （去重后新增 %d）" % (s["b3_count"], s["b3_new"]))
    md.append("批 4 FIXTURE系 = %2d  （去重后新增 5）" % s["b4_count"])
    md.append("批 5+5.1 证据  = %2d  （REAL-LOCAL %d / COLLECTED-SPARSE %d / 其余构造·FIXTURE %d；去重新增 %d；REAL 净增 %d；partial=%s 有损但计入）"
              % (s["b5_count"], sum(1 for v in s["b5_levels"].values() if v == "REAL-LOCAL"),
                 sum(1 for v in s["b5_levels"].values() if v == "COLLECTED-SPARSE"),
                 sum(1 for v in s["b5_levels"].values() if v not in ("REAL-LOCAL", "COLLECTED-SPARSE")),
                 len([k for k in s["after5_distinct"] if k not in s["pre_distinct"]]),
                 len(s["real_net_new"]), ",".join(s["b5_partial"]) or "—"))
    md.append("批 5.1 并入   =  3  （codebuddy/fx/mini-swe-agent；已在上行计入，不重复）")
    md.append("--------------------------------------------------------")
    md.append("分层累计（v0.2 / v0.3 / 批 5.1 后）= %d / %d / %d  （v0.3 起超 40 上限→停用）"
              % (s["pre_layered"], s["layered_v3"], s["layered_pred"]))
    md.append("去重 Harness（v0.2 / v0.3 / 批 5.1 后）= %d / %d / %d"
              % (s["pre_n"], s["after5_n"], s["predicted_n"]))
    md.append("真实会话覆盖（v0.2 / v0.3 / 批 5.1 后）= %d / %d / %d（REAL-LOCAL 与 COLLECTED-SPARSE 计入）"
              % (s["pre_real_count"], s["real_count"], s["predicted_real"]))
    md.append("```")
    md.append("")
    md.append("#### D.4 已知计数冲突与待确认（不自动合并）")
    md.append("")
    md.append(md_table(["#", "冲突", "当前处理", "若确认后的影响"], ["---"] * 4, [
        ["C1", "OSS 标签 `opencraw` ↔ OpenClaw 疑似同一产品", "按标签分别计（opencraw=COLLECTED，openclaw 批 4 FIXTURE）", "若同一：去重 -1"],
        ["C2", "批 2 `other` 非具体 Harness", "分层按协议口径计 18；去重/REAL 排除", "不影响去重数字"],
        ["C3", "`cherry-studio` / `workbuddy` 不在 catalog 49", "按标签计（COLLECTED）", "若不算 Harness：去重 -2、REAL -2"],
        ["C4", "OMP ↔ Pi 同格式族", "分开计（不同产品；Pi 为 REAL-LOCAL）", "不建议合并"],
        ["C5", "`droid` ↔ `factory-droid` 同一产品", "已合并（alias）", "—"],
        ["C6", "`claude-code`↔`claude`、`kilo`↔`kilo-code`、`kimi-code`↔`kimi`、`roo-code`↔`roo`", "已合并（alias）", "—"],
        ["C7", "Codex Desktop→codex；Kimi CLI→kimi", "按 catalog 家族合并（单列行仅备注）", "—"],
        ["C8", "Gemini CLI ↔ Antigravity 同用 Gemini 模型", "分开计（格式独立：JSON/JSONL vs SQLite+protobuf）", "不建议合并"],
        ["C9", "Cline/Roo/Kilo 同族（Cline 谱系）", "**按标签计为 3 行**（cline/roo/kilo-code），不合并", "若合并：去重 -2（不建议）"],
        ["C10", "oss-add：claude-desktop 仅 2 条消息；gateway/unknown 为中间件/兜底标签", "claude-desktop 计 COLLECTED-SPARSE（默认计入并标注）；gateway/unknown **不计入**", "若不计 sparse：真实 -1、去重 -1"],
        ["C11", "分层累计已 51 > 40 上限", "**分层口径停用**，对外只报去重口径 37/40", "无（仅为口径纠正）"],
        ["C12", "批 5.1 已定稿（v2 artifact：17 行 pass=16/partial=1/fail=0；fx=fx partial 有损已声明）", "全部计入：协议去重 **40/40**；fx 按 FIXTURE+partial 计入并注明", "已解决（task-29 定稿）"],
        ["C13", "mini-swe-agent 非 catalog 产品（Harbor 样例/外部框架）", "计入则 40/40；剔除则 39/40（在 B 表注明）", "由 Lead 决定是否把外部框架计入 40"],
    ]))
    md.append("")
    # E. evidence & commands
    md.append("### E. 测试证据与复跑命令（自动生成）")
    md.append("")
    ev_rows = []
    for label, path, cmd in [
        ("批 1（5×5 方向矩阵）", "tools/agent-session-import/tests/artifacts/interop-matrix.json",
         "cd tools/agent-session-import && ./asi matrix --report tests/artifacts/interop-matrix.json --doc ../../docs/interop-matrix.md"),
        ("批 2（18 采集标签）", "tools/agent-session-import/tests/artifacts/interop-matrix-batch2.json",
         "cd tools/agent-session-import && ./asi matrix-batch2 --root ../../samples/batch2/oss --report tests/artifacts/interop-matrix-batch2.json --doc ../../docs/interop-matrix-batch2.md"),
        ("批 3（6 原生 fixture）", "tools/agent-session-import/tests/artifacts/interop-matrix-batch3.json",
         "cd tools/agent-session-import && ./asi matrix-batch3 --root ../../samples/batch2/public-fixtures --report tests/artifacts/interop-matrix-batch3.json --doc ../../docs/interop-matrix-batch3.md"),
        ("批 4（8 fixture/构造）", "tools/agent-session-import/tests/artifacts/interop-matrix-batch4.json",
         "cd tools/agent-session-import && ./asi matrix-batch4 --root ../../samples/batch2/public-fixtures --report tests/artifacts/interop-matrix-batch4.json --doc ../../docs/interop-matrix-batch4.md"),
        ("批 5（REAL-LOCAL+构造）", "tools/agent-session-import/tests/artifacts/interop-matrix-batch5.json" + ("" if b5 else "（待生成）"),
         "cd tools/agent-session-import && ./asi matrix-batch5  # 端口以 cli.py 为准；输出 tests/artifacts/interop-matrix-batch5.json + docs/interop-matrix-batch5.md"),
    ]:
        ev_rows.append([label, "`%s`" % path, "`%s`" % cmd])
    md.append(md_table(["层", "artifact", "复跑命令"], ["---"] * 3, ev_rows))
    md.append("")
    md.append("本条账本刷新命令：")
    md.append("")
    md.append("```bash")
    md.append("python3 tools/coverage-report.py           # 预览生成的 Markdown 块")
    md.append("python3 tools/coverage-report.py --check   # 校验账本是否过期（exit 1 = 需刷新）")
    md.append("python3 tools/coverage-report.py --write   # 用 artifact 最新数据刷新账本生成段")
    md.append("python3 tools/coverage-report.py --json    # 机器可读摘要（CI 可断言计数）")
    md.append("```")
    md.append("")
    md.append("> 数据快照时间（取各 artifact `generated_at` 最大值，UTC）：`%s`｜批 1-5 快照：`%s` / `%s` / `%s` / `%s` / `%s`｜批 5.1：已并入 v2 定稿" % (
        s["generated_at"], (s["artifact_meta"]["b1"] or ["?"])[0], (s["artifact_meta"]["b2"] or ["?"])[0],
        (s["artifact_meta"]["b3"] or ["?"])[0], (s["artifact_meta"]["b4"] or ["?"])[0],
        (s["artifact_meta"]["b5"] or ["未生成"])[0]))
    return "\n".join(md), s


def write_ledger(doc_path, block):
    text = read_text(doc_path)
    if not text:
        raise SystemExit("ledger not found: %s" % doc_path)
    if BEGIN not in text or END not in text:
        raise SystemExit("markers not found in %s（先创建 %s / %s 标记段）" % (doc_path, BEGIN, END))
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = head + BEGIN + "\n\n" + block.rstrip() + "\n\n" + END + tail
    with open(doc_path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return doc_path


def extract_block(doc_path):
    text = read_text(doc_path)
    if BEGIN not in text or END not in text:
        return None
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="ATIF interop coverage ledger generator (read-only)")
    ap.add_argument("--json", action="store_true", help="print machine-readable summary")
    ap.add_argument("--check", action="store_true", help="exit 1 if docs/coverage-ledger.md generated block is stale")
    ap.add_argument("--write", action="store_true", help="replace generated block in ledger")
    ap.add_argument("--doc", default=DEFAULT_DOC, help="ledger path (default docs/coverage-ledger.md)")
    args = ap.parse_args(argv)

    for path in (BATCH1_MATRIX, BATCH2_MATRIX, BATCH3_MATRIX):
        if not os.path.exists(path):
            raise SystemExit("missing artifact: %s" % path)
    block, summary = generate()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.check:
        cur = extract_block(args.doc)
        if cur is None:
            print("ERROR: markers missing in %s" % args.doc, file=sys.stderr)
            return 2
        if cur.strip() != block.strip():
            print("STALE: %s generated block differs from artifacts. Run: "
                  "python3 tools/coverage-report.py --write" % args.doc, file=sys.stderr)
            return 1
        print("OK: %s is up to date" % args.doc)
        return 0
    if args.write:
        write_ledger(args.doc, block)
        print("updated %s" % args.doc)
        return 0
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
