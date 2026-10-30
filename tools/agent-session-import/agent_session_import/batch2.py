"""Batch-2 matrix: OSS ``traj-session/1`` capture -> IR -> ATIF -> native harnesses.

For every harness label found in the OSS capture samples (>=15 labels):

  L0  oss reader -> IR
  L1  IR -> ATIF v1.8 -> IR (round-trip fidelity)
  L2  IR -> DSH staging (session.v4.jsonl.zstd) -> DSH reader read-back semantic compare
  L3  real DSH `Session.fromRestore` loads the staged file (node tests/e2e_load.mjs)
  L2' IR -> each of claude/codex/omp/qoder native staging -> its reader read-back (format-level)

Nothing is written to a real harness store.  The capture format is a *normalized API-capture
format*, not a native session format: L3 native load is only real for DSH here; the other
targets are format-level round-trips.
"""
import datetime as _dt
import json
import os
import tempfile
import uuid

from . import atif, matrix, targets
from .readers import get as get_reader
from .readers import oss_traj
from .writers import native_write

FORMAT_TARGETS = ("claude", "codex", "omp", "qoder")

_CLAUDE_INJECTED_PREFIXES = (
    "[Request interrupted by user",
    "[SYSTEM NOTIFICATION",
    "This session is being continued from a previous conversation",
)


def _filtered_expected_ir(ir, target):
    """Apply the *target reader's* documented row filters to the expected IR.

    The capture format stores some rows (compaction continuations, environment preambles)
    that the target harness's native reader intentionally hides; comparing without this
    adjustment would report false failures.  Returns (ir_copy, filtered_count).
    """
    filtered = 0
    events = []
    for ev in ir.get("events") or []:
        drop = False
        if ev.get("kind") == "user_message" and target == "claude":
            text = "".join(b.get("text") or "" for b in ev.get("blocks") or []).lstrip()
            if text.startswith(_CLAUDE_INJECTED_PREFIXES):
                drop = True
        elif ev.get("kind") == "user_message" and target == "codex":
            from .readers.codex import _is_injected_user_text

            text = "".join(b.get("text") or "" for b in ev.get("blocks") or []).lstrip()
            if _is_injected_user_text(text):
                drop = True
        elif ev.get("kind") == "system_message" and target in ("claude", "codex", "omp", "qoder", "dsh"):
            drop = True
        if drop:
            filtered += 1
        else:
            events.append(ev)
    if not filtered:
        return ir, 0
    import copy

    out = copy.deepcopy(ir)
    out["events"] = events
    return out, filtered


def _strip_placeholder_results(ir):
    """Drop writer-backfilled placeholder tool results before semantic compare.

    Capture sessions can contain tool calls whose result was truncated/lost; every writer
    materializes a placeholder result, but its linear position can differ (step end vs list
    end).  This is a recorded, known loss, not a fidelity failure.
    """
    from .ir import MISSING_RESULT_TEXT

    events = []
    dropped = 0
    for ev in ir.get("events") or []:
        if ev.get("kind") == "tool_result" and str(ev.get("content") or "").strip() == MISSING_RESULT_TEXT:
            dropped += 1
            continue
        events.append(ev)
    if not dropped:
        return ir, 0
    import copy

    out = copy.deepcopy(ir)
    out["events"] = events
    return out, dropped


def _compare_for_target(ir, back, target):
    expected, filtered = _filtered_expected_ir(ir, target)
    expected, placeholders = _strip_placeholder_results(expected)
    back, back_placeholders = _strip_placeholder_results(back)
    cmp = matrix.compare(expected, back)
    lossy = list(cmp.get("lossy") or [])
    if filtered:
        lossy.append("target_filtered_rows:%d" % filtered)
    warnings = list(cmp.get("warnings") or [])
    if placeholders or back_placeholders:
        warnings.append("placeholder_tool_results_normalized:%d"
                        % max(placeholders, back_placeholders))
    cmp["lossy"] = sorted(set(lossy))
    cmp["warnings"] = warnings
    return cmp


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pick_per_harness(rows, min_msgs=1, only=None):
    """One representative sample per harness label (prefer >=8 msgs / high confidence)."""
    picked = {}
    for row in rows:
        harness = row.get("harness") or "other"
        if only and harness not in only:
            continue
        msgs = row.get("lines") or 0
        if msgs < min_msgs:
            continue
        score = (
            1 if msgs >= 8 else 0,
            1 if (row.get("harness_confidence") == "high") else 0,
            -abs(msgs - 40),
            msgs,
        )
        cur = picked.get(harness)
        if cur is None or score > cur[0]:
            picked[harness] = (score, row, msgs)
    return {h: {"row": v[1], "messages": v[2]} for h, v in picked.items()}


def run_batch2(root=None, out_dir=None, report_path=None, doc_path=None,
               limit=None, only=None, do_format=True, target_cwd=None, verbose=False):
    root = os.path.expanduser(root or oss_traj.default_root())
    out_dir = os.path.abspath(out_dir or tempfile.mkdtemp(prefix="asi-batch2-"))
    os.makedirs(out_dir, exist_ok=True)
    cwd = target_cwd or os.getcwd()
    rows = get_reader("oss").list_sessions(root)
    picked = pick_per_harness(rows, only=only)
    harnesses = sorted(picked)
    if limit:
        harnesses = harnesses[:limit]
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)

    entries = []
    for n, harness in enumerate(harnesses, 1):
        item = picked[harness]
        row = item["row"]
        sid = "session-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "asi-batch2:%s:%s" % (harness, row["id"])))
        entry = {
            "harness": harness,
            "model": row.get("model"),
            "harness_version": row.get("harness_version"),
            "harness_confidence": row.get("harness_confidence"),
            "messages_format": row.get("messages_format"),
            "source_session_id": row.get("id"),
            "source_path": row.get("path"),
            "source_messages": item["messages"],
            "bucket": row.get("bucket"),
            "region": row.get("region"),
            "dsh_session_id": sid,
        }
        try:
            ir = get_reader("oss").load_session(path=row["path"])
            entry["l0"] = {"ok": bool(ir.get("events")), "events": (ir.get("stats") or {}).get("events"),
                           "ir_stats": ir.get("stats"), "warnings": ir.get("warnings") or [],
                           "extra": {k: ir.get("extra", {}).get(k) for k in
                                     ("source_harness", "harness_version", "messages_format",
                                      "bucket", "region", "key_prefix", "quality")}}
        except (OSError, ValueError) as exc:
            entry.update({"status": "fail", "error": "L0: %s" % exc,
                          "l0": {"ok": False, "events": 0, "ir_stats": {}, "warnings": []}})
            entries.append(entry)
            log("[%2d] %-16s FAIL L0 %s" % (n, harness, exc))
            continue
        if not entry["l0"]["ok"]:
            entry["status"] = "fail"
            entries.append(entry)
            continue
        # L1: ATIF round-trip
        try:
            doc = atif.to_atif(ir)
            errs, _warns = atif.validate(doc)
            mid = atif.from_atif(doc)
            c1 = matrix.compare(ir, mid)
            entry["l1"] = {"ok": bool(c1.get("ok") and not errs), "detail": c1.get("detail"),
                           "lossy": c1.get("lossy") or [], "validate_errors": errs,
                           "atif_steps": len(doc.get("steps") or [])}
        except (OSError, ValueError) as exc:
            entry["l1"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
            mid = None
        # DSH native staging: L2 compare + L3 real load
        if mid is not None:
            try:
                root_dsh = os.path.join(out_dir, harness, "dsh", "sessions")
                wres = native_write(ir, "dsh", root_dsh, sid, target_cwd=cwd)
                back = get_reader("dsh").load_session(path=wres["artifact"])
                c2 = _compare_for_target(ir, back, "dsh")
                entry["l2"] = {"ok": bool(c2.get("ok")), "detail": c2.get("detail"),
                               "lossy": c2.get("lossy") or [], "artifact": wres["artifact"]}
                l3 = targets.l3_check("dsh", wres["artifact"], root_dsh, sid, ir)
                entry["l3"] = {"ok": bool(l3.get("ok")), "tool": l3.get("tool"),
                               "detail": l3.get("detail"), "evidence": wres["artifact"]}
            except (OSError, ValueError, RuntimeError) as exc:
                entry["l2"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
                entry["l3"] = {"ok": False, "detail": "staging failed"}
        else:
            entry["l2"] = {"ok": False, "detail": "no ATIF IR to stage"}
            entry["l3"] = {"ok": False, "detail": "no ATIF IR to stage"}
        # L2': format-level write + read-back for the native targets
        if do_format:
            fmt = {}
            for target in FORMAT_TARGETS:
                try:
                    tgt = os.path.join(out_dir, harness, target)
                    tgt_root = matrix.staging_root(target, tgt)
                    wres = native_write(ir, target, tgt_root, sid, target_cwd=cwd)
                    back = get_reader(target).load_session(path=wres["artifact"])
                    expected, _f = _filtered_expected_ir(ir, target)
                    expected, _p = _strip_placeholder_results(expected)
                    back, _bp = _strip_placeholder_results(back)
                    c = matrix.compare_flat(expected, back)
                    fmt[target] = {"ok": bool(c.get("ok")), "lossy": c.get("lossy") or [],
                                   "detail": c.get("detail"), "artifact": wres["artifact"]}
                except (OSError, ValueError, RuntimeError) as exc:
                    fmt[target] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
            entry["l2_format"] = fmt
            entry["format_ok"] = all(v.get("ok") for v in fmt.values())
        fmt_lossy = set()
        for v in (entry.get("l2_format") or {}).values():
            fmt_lossy |= set(v.get("lossy") or [])
        lossy = sorted(set((entry.get("l1") or {}).get("lossy") or [])
                       | set((entry.get("l2") or {}).get("lossy") or [])
                       | fmt_lossy)
        entry["lossy"] = lossy
        hard_ok = (entry["l1"].get("ok") and entry["l2"].get("ok") and entry["l3"].get("ok"))
        if not hard_ok:
            entry["status"] = "fail"
        elif not entry.get("format_ok", True) or lossy:
            entry["status"] = "partial"
        else:
            entry["status"] = "pass"
        entries.append(entry)
        log("[%2d/%2d] %-16s %-22s %-20s L0=%s L1=%s L2=%s L3=%s fmt=%s -> %s"
            % (n, len(harnesses), harness, (entry.get("model") or "")[:22],
               entry.get("messages_format"), entry["l0"]["ok"], entry["l1"].get("ok"),
               entry["l2"].get("ok"), entry["l3"].get("ok"),
               entry.get("format_ok"), entry["status"]))

    summary = {
        "harnesses": len(entries),
        "pass": sum(1 for e in entries if e["status"] == "pass"),
        "partial": sum(1 for e in entries if e["status"] == "partial"),
        "fail": sum(1 for e in entries if e["status"] == "fail"),
        "formats": {},
        "l3_dsh": sum(1 for e in entries if (e.get("l3") or {}).get("ok")),
    }
    for e in entries:
        fmt = e.get("messages_format") or "unknown"
        summary["formats"].setdefault(fmt, {"total": 0, "pass": 0})
        summary["formats"][fmt]["total"] += 1
        if e["status"] == "pass":
            summary["formats"][fmt]["pass"] += 1
    report = {
        "schema": "asi-oss-batch2-matrix/v1",
        "asi_version": __import__("agent_session_import").__version__,
        "generated_at": _now(),
        "root": root,
        "out_dir": out_dir,
        "target_cwd": cwd,
        "summary": summary,
        "entries": entries,
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


def _cell(value):
    if value is True:
        return "✅"
    if value is False:
        return "❌"
    if value is None:
        return "—"
    return str(value)


def render_markdown(report):
    s = report["summary"]
    entries = report["entries"]
    lines = []
    lines.append("# 批 2 矩阵：OSS 采集轨迹（traj-session/1）→ IR → ATIF → 原生 Harness\n")
    lines.append("> 自动生成 by `asi matrix-batch2`（asi %s，%s）。每个 harness 标签取 1 个真实采集会话："
                 "OSS reader→IR（L0）→ATIF v1.8 往返（L1）→DSH staging→真实 `Session.fromRestore`（L3）+ "
                 "DSH reader 读回语义比对（L2）；另对 claude/codex/omp/qoder 做格式级写入+读回（L2'）。\n"
                 % (report.get("asi_version"), report.get("generated_at")))
    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| harness 标签数 | %d |" % s["harnesses"])
    lines.append("| 通过 (pass) | %d |" % s["pass"])
    lines.append("| 有损 (partial) | %d |" % s["partial"])
    lines.append("| 失败 (fail) | %d |" % s["fail"])
    lines.append("| DSH 真实加载 (L3) | %d/%d |" % (s["l3_dsh"], s["harnesses"]))
    for fmt, st in sorted((s.get("formats") or {}).items()):
        lines.append("| messages_format `%s` | %d/%d pass |" % (fmt, st["pass"], st["total"]))
    lines.append("")
    lines.append("## 按 harness 分组\n")
    lines.append("| harness | model | messages_format | msgs | L0 | L1 | L2 DSH | L3 DSH load | L2' 4 targets | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for e in entries:
        l2f = e.get("l2_format") or {}
        fmt_ok = sum(1 for v in l2f.values() if v.get("ok"))
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s/%s | **%s** |" % (
            e["harness"], (e.get("model") or "")[:28], e.get("messages_format") or "—",
            e.get("source_messages") or 0, _cell((e.get("l0") or {}).get("ok")),
            _cell((e.get("l1") or {}).get("ok")), _cell((e.get("l2") or {}).get("ok")),
            _cell((e.get("l3") or {}).get("ok")),
            fmt_ok, len(l2f) if l2f else "—", e["status"]))
    lines.append("")
    lines.append("## 每 harness 证据\n")
    for e in entries:
        l3 = e.get("l3") or {}
        lines.append("### %s（%s / %s）\n" % (
            e["harness"], e.get("messages_format"), (e.get("source_session_id") or "")[:24]))
        lines.append("- source: `%s`（%s / %s / %s）" % (
            e.get("source_path"), e.get("bucket") or "?", e.get("region") or "?",
            e.get("harness_confidence") or "?"))
        lines.append("- L0 IR：events=%s user=%s assistant=%s tool_calls=%s tool_results=%s"
                     % ((e.get("l0", {}).get("ir_stats") or {}).get("events"),
                        (e.get("l0", {}).get("ir_stats") or {}).get("user_messages"),
                        (e.get("l0", {}).get("ir_stats") or {}).get("assistant_messages"),
                        (e.get("l0", {}).get("ir_stats") or {}).get("tool_calls"),
                        (e.get("l0", {}).get("ir_stats") or {}).get("tool_results")))
        lines.append("- L1 ATIF：%s（steps=%s，lossy=%s）" % (
            _cell((e.get("l1") or {}).get("ok")), (e.get("l1") or {}).get("atif_steps"),
            ", ".join((e.get("l1") or {}).get("lossy") or []) or "—"))
        lines.append("- L2 DSH 读回：%s；L3 原生加载：%s（`%s`）" % (
            _cell((e.get("l2") or {}).get("ok")), _cell(l3.get("ok")),
            l3.get("tool") or "—"))
        lines.append("- 证据：`%s`" % (l3.get("evidence") or (e.get("l2") or {}).get("artifact") or "—"))
        if e.get("status") != "pass":
            lines.append("- 备注：%s" % ((e.get("error") or (e.get("l3") or {}).get("detail")
                                          or (e.get("l2") or {}).get("detail") or "")[:300]))
        lines.append("")
    lines.append("## 口径与限制\n")
    lines.append("- **采集格式 ≠ 原生格式**：`traj-session/1` 是 API 网关 request-level 录制经归一化管线"
                 "产出的会话外壳（见 `docs/oss-trajectory-inventory.md` §5），事件粒度/cwd/parent 链等原生元数据"
                 "已丢失；L2' 是「格式级写入 + 对应 reader 读回」验证，不等于该 harness 的 CLI 能恢复。")
    lines.append("- **L3 仅 DSH 是真原生加载**（`Session.fromRestore`）；其它 target 在此矩阵中只做格式级往返，"
                 "原生 L3 证据见 `docs/interop-matrix.md`（本地 5 harness 的 20 方向矩阵）。")
    lines.append("- 采集缺陷如实保留：`messages` 为空 / `messages_format` 缺失 / tool_result 不完整 / "
                 "`meta_data.quality` 异常会进入 warnings 或 fail，不做静默补全。")
    lines.append("- 全程只写 `--out` staging 目录，**未写真实** `~/.claude|~/.codex|~/.dsh|~/.qoder|~/.omp`；"
                 "DSH 加载仅在隔离 staging 上做只读 `Session.fromRestore`。")
    lines.append("")
    return "\n".join(lines) + "\n"
