"""`asi matrix`: 5-harness ordered-direction interop matrix (ATIF as the hub).

For every ordered pair (A -> B), A != B:
  L0  read a real local session with A's reader -> IR
  L1  IR -> ATIF v1.8 -> IR (ATIF round-trip fidelity)
  L2  IR -> B native store (staging) -> B reader -> semantic compare with the L1 IR
  L3  target-harness discovery/load probe (DSH Session.fromRestore / codex TUI resume /
      claude agents --json / omp --mode=rpc / qoder: no CLI -> format-level)

Also does the 5 ATIF self-round-trips (A -> ATIF -> A).
"""
import datetime as _dt
import json
import os
import re
import shutil
import tempfile
import uuid
from collections import Counter

from . import __version__, atif, targets
from .readers import READERS, get as get_reader
from .writers import native_write

CORE_KINDS = ("user_message", "assistant_message", "tool_result")
DROPPED_KINDS = ("compaction", "system_message", "turn_abort")
PLACEHOLDER_RESULT = "[tool result missing in source session]"
TS_TOLERANCE_MS = 5000


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def counts(ir):
    return dict(Counter(ev.get("kind") for ev in ir.get("events") or []))


def fingerprint(ir):
    """Comparable semantic sequence + known-lossy event counts."""
    seq = []
    losses = Counter()
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind in DROPPED_KINDS:
            losses["%s_dropped_by_target" % kind] += 1
            continue
        if kind == "user_message":
            seq.append(("user", _norm("\n".join(
                b.get("text") or b.get("placeholder") or "" for b in ev.get("blocks") or []))))
        elif kind == "assistant_message":
            text = _norm("\n".join(
                b.get("text") or "" for b in ev.get("blocks") or []
                if b.get("type") in ("text", "reasoning")))
            calls = tuple((b.get("id") or "", b.get("name") or "")
                          for b in ev.get("blocks") or [] if b.get("type") == "tool-call")
            seq.append(("assistant", text, calls))
        elif kind == "tool_result":
            content = _norm(ev.get("content"))
            seq.append(("tool", ev.get("call_id") or "", content, bool(ev.get("is_error"))))
    return seq, losses


def compare(ir_a, ir_b):
    fa, la = fingerprint(ir_a)
    fb, lb = fingerprint(ir_b)
    ok = fa == fb
    detail = None
    if not ok:
        for i, (x, y) in enumerate(zip(fa, fb)):
            if x != y:
                detail = {"index": i, "expected": str(x)[:320], "actual": str(y)[:320]}
                break
        if detail is None:
            detail = {"expected_len": len(fa), "actual_len": len(fb)}
    # timestamp tolerance on matched core events
    # ATIF observation results do not carry per-result timestamps (spec), so only message
    # events participate in the timestamp tolerance check.
    ts_a = [ev.get("ts") for ev in ir_a.get("events") or [] if ev.get("kind") in ("user_message", "assistant_message")]
    ts_b = [ev.get("ts") for ev in ir_b.get("events") or [] if ev.get("kind") in ("user_message", "assistant_message")]
    ts_ok = True
    if len(ts_a) == len(ts_b):
        for x, y in zip(ts_a, ts_b):
            if isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) > TS_TOLERANCE_MS:
                ts_ok = False
                break
    warnings = []
    if (ir_a.get("cwd") or "") != (ir_b.get("cwd") or ""):
        warnings.append("cwd differs: %r -> %r" % (ir_a.get("cwd"), ir_b.get("cwd")))
    if (ir_a.get("title") or "") != (ir_b.get("title") or ""):
        warnings.append("title differs: %r -> %r" % ((ir_a.get("title") or "")[:60],
                                                     (ir_b.get("title") or "")[:60]))
    return {
        "ok": bool(ok and ts_ok),
        "detail": detail,
        "timestamp_ok": ts_ok,
        "lossy": sorted(set(list(la) + list(lb))),
        "warnings": warnings,
        "counts_a": counts(ir_a),
        "counts_b": counts(ir_b),
    }


def _flat_fingerprint(ir):
    """Block-level sequence: tolerant to native writers re-grouping assistant items."""
    seq = []
    losses = Counter()
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind in DROPPED_KINDS:
            losses["%s_dropped_by_target" % kind] += 1
            continue
        if kind == "user_message":
            seq.append(("user", _norm("\n".join(b.get("text") or b.get("placeholder") or ""
                                                  for b in ev.get("blocks") or []))))
        elif kind == "assistant_message":
            for b in ev.get("blocks") or []:
                bt = b.get("type")
                if bt == "text":
                    seq.append(("text", _norm(b.get("text") or "")))
                elif bt == "reasoning":
                    seq.append(("reasoning", _norm(b.get("text") or "")))
                elif bt == "tool-call":
                    seq.append(("tool-call", b.get("id") or "", b.get("name") or ""))
        elif kind == "tool_result":
            content = _norm(ev.get("content"))
            if content == _norm(PLACEHOLDER_RESULT):
                losses["placeholder_tool_result_added"] += 1
                continue
            seq.append(("tool", ev.get("call_id") or "", content, bool(ev.get("is_error"))))
    return seq, losses


def compare_flat(ir_a, ir_b):
    """Like compare(), but ignores assistant message grouping; records the normalization."""
    fa, la = _flat_fingerprint(ir_a)
    fb, lb = _flat_fingerprint(ir_b)
    cmp = compare(ir_a, ir_b)
    if fa == fb and not cmp.get("ok"):
        cmp["ok"] = True
        cmp["lossy"] = sorted(set(list(cmp.get("lossy") or [])
                                  + ["message_grouping_normalized"]))
        cmp["detail"] = {"note": "equal at block level; only assistant message grouping differs"}
    cmp["flat_ok"] = fa == fb
    if not fa == fb and cmp.get("ok"):
        cmp["ok"] = False
        cmp["detail"] = {"flat_mismatch": "block-level sequence differs"}
    return cmp


def staging_root(target, work_dir):
    if target == "claude":
        return os.path.join(work_dir, "claude", "projects")
    if target == "dsh":
        return os.path.join(work_dir, "dsh", "sessions")
    if target == "qoder":
        return os.path.join(work_dir, "qoder", "projects")
    return os.path.join(work_dir, target)


def pick_sessions(sources, limit=1):
    """Pick >=1 real local session per source (small but conversational, fast to convert)."""
    picked = {}
    for src in sources:
        reader = get_reader(src)
        try:
            rows = [r for r in reader.list_sessions(None) if r.get("path") and os.path.isfile(r["path"])]
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError("cannot list %s sessions: %s" % (src, exc))
        rows.sort(key=lambda r: (r.get("lines") or 0))
        candidates = [r for r in rows if 6 <= (r.get("lines") or 0) <= 2000] or rows
        loaded = None
        for r in candidates:
            try:
                ir = reader.load_session(path=r["path"])
            except (OSError, ValueError) as exc:
                continue
            st = ir.get("stats") or {}
            if (st.get("user_messages") or 0) >= 1 and (st.get("assistant_messages") or 0) >= 1:
                loaded = {"row": r, "ir": ir}
                break
        if loaded is None and rows:
            r = rows[0]
            loaded = {"row": r, "ir": reader.load_session(path=r["path"])}
        if loaded is None:
            raise RuntimeError("no usable real %s session found" % src)
        picked[src] = loaded
        if len(picked) >= len(sources):
            break
    return picked


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_matrix(sources=None, out_dir=None, report_path=None, doc_path=None,
               l3=True, limit=1, verbose=False):
    sources = list(sources or targets.TARGETS)
    out_dir = os.path.abspath(out_dir or tempfile.mkdtemp(prefix="asi-matrix-"))
    os.makedirs(out_dir, exist_ok=True)
    picked = pick_sessions(sources, limit=limit)
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)

    # Pre-compute A -> ATIF -> IR once per source (L1 is direction independent).
    atif_round = {}
    for src in sources:
        ir = picked[src]["ir"]
        try:
            doc = atif.to_atif(ir)
            errs, _ = atif.validate(doc)
            mid = atif.from_atif(doc)
            cmp = compare(ir, mid)
            atif_round[src] = {"doc": doc, "ir": mid, "compare": cmp,
                               "validate_errors": errs}
        except (ValueError, OSError) as exc:
            atif_round[src] = {"doc": None, "ir": None,
                               "compare": {"ok": False, "detail": str(exc), "lossy": [], "warnings": []},
                               "validate_errors": [str(exc)]}

    directions = []
    total = len(sources) * (len(sources) - 1)
    n = 0
    for a in sources:
        row_a = picked[a]
        ir_a = row_a["ir"]
        rt = atif_round[a]
        for b in sources:
            if a == b:
                continue
            n += 1
            entry = {
                "from": a, "to": b,
                "source_session_id": ir_a.get("source_session_id"),
                "source_path": row_a["row"].get("path"),
                "ir_counts": counts(ir_a),
            }
            entry["l0"] = {"ok": ir_a is not None,
                           "detail": "reader=%s events=%d" % (a, len(ir_a.get("events") or []))}
            c1 = rt["compare"]
            entry["l1"] = {"ok": bool(c1.get("ok")), "detail": c1.get("detail"),
                           "lossy": c1.get("lossy") or [],
                           "timestamp_ok": c1.get("timestamp_ok")}
            work = os.path.join(out_dir, "directions", "%s_to_%s" % (a, b))
            root = staging_root(b, work)
            sid = "session-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "asi-matrix:%s:%s" % (a, b)))
            try:
                wres = native_write(rt["ir"], b, root, sid,
                                    target_cwd=ir_a.get("cwd") or row_a["row"].get("cwd"))
                back = get_reader(b).load_session(path=wres["artifact"])
                c2 = compare(rt["ir"], back)
                entry["l2"] = {"ok": bool(c2.get("ok")), "detail": c2.get("detail"),
                               "lossy": c2.get("lossy") or [],
                               "timestamp_ok": c2.get("timestamp_ok"),
                               "artifact": wres["artifact"],
                               "native_lines": wres.get("lines") or wres.get("events")}
            except (OSError, ValueError, RuntimeError) as exc:
                entry["l2"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc),
                               "lossy": [], "artifact": None}
            if l3 and entry["l2"].get("artifact"):
                try:
                    entry["l3"] = targets.l3_check(
                        b, entry["l2"]["artifact"], root, sid, rt["ir"])
                except (OSError, ValueError, RuntimeError) as exc:
                    entry["l3"] = {"ok": False, "tool": None, "detail": "probe error: %s" % exc}
            else:
                entry["l3"] = {"ok": None, "tool": None, "detail": "disabled"}
            entry["lossy"] = sorted(set(entry["l1"].get("lossy") or [])
                                    | set(entry["l2"].get("lossy") or []))
            entry["warnings"] = (c1.get("warnings") or []) + (entry["l2"].get("warnings") or [])
            entry["evidence_path"] = entry["l2"].get("artifact")
            hard_ok = entry["l1"].get("ok") and entry["l2"].get("ok")
            l3_ok = entry["l3"].get("ok")
            if not hard_ok:
                entry["status"] = "fail"
            elif entry["lossy"] or l3_ok is not True:
                entry["status"] = "partial"
            else:
                entry["status"] = "pass"
            directions.append(entry)
            log("[%2d/%2d] %-6s -> %-6s %-7s l1=%s l2=%s l3=%s lossy=%s"
                % (n, total, a, b, entry["status"], entry["l1"].get("ok"),
                   entry["l2"].get("ok"), l3_ok, ",".join(entry["lossy"]) or "-"))

    self_roundtrip = []
    for src in sources:
        rt = atif_round[src]
        self_roundtrip.append({
            "source": src,
            "source_session_id": picked[src]["ir"].get("source_session_id"),
            "ok": bool(rt["compare"].get("ok")),
            "validate_errors": rt["validate_errors"],
            "lossy": rt["compare"].get("lossy") or [],
            "counts": counts(picked[src]["ir"]),
            "detail": rt["compare"].get("detail"),
        })

    summary = {
        "directions_total": len(directions),
        "pass": sum(1 for d in directions if d["status"] == "pass"),
        "partial": sum(1 for d in directions if d["status"] == "partial"),
        "fail": sum(1 for d in directions if d["status"] == "fail"),
        "atif_self_pass": sum(1 for r in self_roundtrip if r["ok"]),
        "atif_self_total": len(self_roundtrip),
    }
    report = {
        "schema": "asi-interop-matrix/v1",
        "asi_version": __version__,
        "generated_at": _now(),
        "sources": sources,
        "out_dir": out_dir,
        "sessions": {src: {
            "source_session_id": picked[src]["ir"].get("source_session_id"),
            "path": picked[src]["row"].get("path"),
            "title": (picked[src]["ir"].get("title") or "")[:120],
            "cwd": picked[src]["ir"].get("cwd"),
            "ir_stats": picked[src]["ir"].get("stats"),
        } for src in sources},
        "summary": summary,
        "directions": directions,
        "atif_self_roundtrip": self_roundtrip,
    }
    if report_path:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
            f.write("\n")
        report["report_path"] = os.path.abspath(report_path)
    if doc_path:
        os.makedirs(os.path.dirname(os.path.abspath(doc_path)) or ".", exist_ok=True)
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(render_markdown(report))
        report["doc_path"] = os.path.abspath(doc_path)
    return report


# --------------------------------------------------------------------------- markdown
def render_markdown(report):
    s = report["summary"]
    lines = []
    lines.append("# 5-Harness 互转矩阵（ATIF v1.8 中枢）\n")
    lines.append("> 自动生成 by `asi matrix`（asi %s，%s）。真实本机会话经 "
                 "A→IR→ATIF→IR→B 原生→B reader 读回→语义比对；L3 = 目标 harness 原生发现/加载。\n"
                 % (report.get("asi_version"), report.get("generated_at")))
    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| 有序方向 | %d |" % s["directions_total"])
    lines.append("| 通过 (pass) | %d |" % s["pass"])
    lines.append("| 有损 (partial) | %d |" % s["partial"])
    lines.append("| 失败 (fail) | %d |" % s["fail"])
    lines.append("| ATIF 自往返通过 | %d/%d |" % (s["atif_self_pass"], s["atif_self_total"]))
    lines.append("")
    lines.append("## 矩阵（行 = from，列 = to；* = 本工具方向）\n")
    sources = report["sources"]
    idx = {(d["from"], d["to"]): d for d in report["directions"]}
    lines.append("| from \\ to | " + " | ".join(sources) + " |")
    lines.append("|---|" + "---|" * len(sources))
    for a in sources:
        cells = []
        for b in sources:
            if a == b:
                cells.append("—")
            else:
                d = idx.get((a, b))
                mark = {"pass": "✅ pass", "partial": "🟡 partial", "fail": "❌ fail"}.get(
                    d["status"] if d else "fail", "?")
                cells.append(mark)
        lines.append("| **%s** | %s |" % (a, " | ".join(cells)))
    lines.append("")
    lines.append("## 方向明细\n")
    lines.append("| from→to | status | L1 ATIF 往返 | L2 原生读回 | L3 原生发现/加载 | lossy | source session |")
    lines.append("|---|---|---|---|---|---|---|")
    for d in report["directions"]:
        l3 = d.get("l3") or {}
        l3txt = {True: "✅", False: "❌", "partial": "🟡"}.get(l3.get("ok"), "—")
        lines.append("| %s→%s | %s | %s | %s | %s | %s | %s |" % (
            d["from"], d["to"], d["status"],
            "✅" if d["l1"].get("ok") else "❌",
            "✅" if d["l2"].get("ok") else "❌",
            l3txt,
            ", ".join(d.get("lossy") or []) or "—",
            (d.get("source_session_id") or "")[:18] + "…",
        ))
    lines.append("")
    lines.append("## L3 目标侧发现/加载验证\n")
    seen = set()
    for d in report["directions"]:
        b = d["to"]
        if b in seen:
            continue
        seen.add(b)
        l3 = d.get("l3") or {}
        lines.append("- **%s**：%s\n  - tool: `%s`\n  - command: `%s`\n  - detail: %s"
                     % (b, {True: "通过", False: "失败", "partial": "部分（有损/受限）"}.get(l3.get("ok"), "格式级（无 CLI 验证）"),
                        l3.get("tool"), (l3.get("command") or "")[:220], (l3.get("detail") or "")[:600]))
    lines.append("")
    lines.append("## ATIF 自往返（A → ATIF v1.8 → A）\n")
    lines.append("| source | 结果 | lossy | ir events |")
    lines.append("|---|---|---|---|")
    for r in report["atif_self_roundtrip"]:
        lines.append("| %s | %s | %s | %s |" % (
            r["source"], "✅" if r["ok"] else "❌",
            ", ".join(r.get("lossy") or []) or "—", (r.get("counts") or {}).get("events", "—")))
    lines.append("")
    lines.append("## 会话样本（每个源 1 个真实本机会话）\n")
    lines.append("| source | session id | cwd | 标题 | IR 事件/消息/工具 |")
    lines.append("|---|---|---|---|---|")
    for src in sources:
        meta = (report.get("sessions") or {}).get(src) or {}
        st = meta.get("ir_stats") or {}
        lines.append("| %s | `%s` | `%s` | %s | %s/%s/%s |" % (
            src, (meta.get("source_session_id") or "")[:26],
            meta.get("cwd") or "", (meta.get("title") or "").replace("|", "\\|")[:40],
            st.get("events"), st.get("user_messages"), st.get("tool_calls")))
    lines.append("")
    lines.append("## 口径与已知有损项\n")
    lines.append("- **L0**：A reader 从真实会话读出 IR。**L1**：ATIF v1.8 往返（IR→ATIF→IR）。"
                 "**L2**：IR→B 原生存储（staging）→B reader 读回，比对消息条数/角色顺序/文本/工具调用↔结果配对/时间戳(±5s)。"
                 "**L3**：目标 harness 原生发现/加载（DSH 用真实 `Session.fromRestore`；Codex/Claude/OMP/Qoder 见上）。")
    lines.append("- 已知有损：`system_message`/`compaction`/`turn_abort` 在多数目标 writer 中被丢弃；"
                 "源中缺失结果的工具调用会按 IR 约定补占位结果。")
    lines.append("- L3 判定命令：DSH = `node tests/e2e_load.mjs <zstd>`（真实 Session.fromRestore）；"
                 "Claude = 隔离 `CLAUDE_CONFIG_DIR`+最小 `.claude.json`+假 `ANTHROPIC_API_KEY`，PTY "
                 "`claude --bare --resume <abs path.jsonl>` 后从 TUI 画面检测源会话文本（不发 prompt/不调模型）；"
                 "OMP = writer 把模型映射到本机 `~/.omp/agent/config.yml` 的 `modelRoles.default` 后 "
                 "`omp --session-dir <staging> --mode=rpc -r <file>` 加载；"
                 "Codex = `CODEX_HOME=<staging> codex resume --last/--include-non-interactive`（PTY，picker 0/0）"
                 "及 `codex app-server` 的 `thread/resume(path)` + `thread/items/list` 均已尝试，"
                 "0.164 的 paginated thread store 不扫描裸 rollout 文件 → 保留 partial（详见每方向 l3.detail）；"
                 "Qoder = CLI 未安装 → 格式级（partial）。")
    lines.append("- 所有原生写入都落在 `--out` staging 目录（临时/指定路径），**未写真实** "
                 "`~/.claude|~/.codex|~/.dsh|~/.qoder|~/.omp`。")
    lines.append("")
    return "\n".join(lines) + "\n"
