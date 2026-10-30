"""Batch-3 matrix: 6 native-format fixtures -> IR -> ATIF -> native writer -> reader.

Evidence level is **FIXTURE** only (public synthetic/trimmed fixtures; no native CLI load).
Per harness (copilot/gemini/aider/cursor/qwen/pi):

  B3-F0  reader -> IR
  B3-F1  IR -> ATIF v1.8 -> IR round-trip
  B3-F2  IR -> DSH staging -> real Session.fromRestore load
  B3-F3  IR -> target native writer -> target reader read-back semantic compare
"""
import copy
import datetime as _dt
import json
import os
import tempfile
import uuid

from . import __version__, atif, matrix, targets
from .ir import MISSING_RESULT_TEXT
from .readers import get as get_reader
from .readers import native_batch3
from .writers import native_write

BATCH3_SOURCES = ("copilot", "gemini", "aider", "cursor", "qwen", "pi")
EVIDENCE = "FIXTURE"
PREFERRED = {
    "copilot": ("copilot-cli-simple.jsonl",),
    "gemini": ("small.json",),
    "aider": ("abc123.md",),
    "cursor": ("small.jsonl",),
    "qwen": ("019f0000000070008000000000000003.jsonl",),
    "pi": ("small.jsonl",),
}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_placeholders(ir):
    events = []
    dropped = 0
    for ev in ir.get("events") or []:
        if ev.get("kind") == "tool_result" and \
                str(ev.get("content") or "").strip() in (MISSING_RESULT_TEXT, "[cursor:tool-result-missing]"):
            dropped += 1
            continue
        events.append(ev)
    if not dropped:
        return ir, 0
    out = copy.deepcopy(ir)
    out["events"] = events
    return out, dropped


def _s(value, limit=300):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value)[:limit]


def _normalize_ids(ir, source):
    """Native formats without tool ids (cursor) get stable synthetic ids; normalize them."""
    if source != "cursor":
        return ir
    out = copy.deepcopy(ir)
    for ev in out.get("events") or []:
        if ev.get("kind") == "assistant_message":
            idx = 0
            for b in ev.get("blocks") or []:
                if b.get("type") == "tool-call":
                    b["id"] = "cursor-tool-%d" % idx
                    idx += 1
        elif ev.get("kind") == "tool_result":
            # match by name/order; cursor placeholders are stripped before compare anyway
            pass
    return out


def _pick(source, rows):
    preferred = PREFERRED.get(source, ())

    def score(row):
        base = os.path.basename(row["path"])
        return (1 if base in preferred else 0,
                1 if (row.get("lines") or 0) > 0 else 0,
                row.get("lines") or 0)

    candidates = sorted(rows, key=score, reverse=True)
    for row in candidates:
        try:
            ir = get_reader(source).load_session(path=row["path"])
        except (OSError, ValueError):
            continue
        stats = ir.get("stats") or {}
        if stats.get("events"):
            return row, ir
    return (candidates[0], get_reader(source).load_session(path=candidates[0]["path"])) if candidates else (None, None)


def run_batch3(root=None, out_dir=None, report_path=None, doc_path=None, limit=None,
               only=None, verbose=False):
    root = os.path.expanduser(root or native_batch3.default_root("copilot"))
    out_dir = os.path.abspath(out_dir or tempfile.mkdtemp(prefix="asi-batch3-"))
    os.makedirs(out_dir, exist_ok=True)
    sources = list(only) if only else list(BATCH3_SOURCES)
    sources = [s for s in sources if s in BATCH3_SOURCES]
    if limit:
        sources = sources[:limit]
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    entries = []
    for n, source in enumerate(sources, 1):
        try:
            rows = get_reader(source).list_sessions(root)
        except (OSError, ValueError) as exc:
            entries.append({"harness": source, "status": "fail",
                            "error": "list failed: %s" % exc})
            continue
        row, ir = _pick(source, rows)
        if row is None or ir is None:
            entries.append({"harness": source, "status": "fail", "error": "no fixture"})
            continue
        sid = "session-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "asi-batch3:%s:%s" % (source, row["id"])))
        entry = {
            "harness": source,
            "evidence_level": EVIDENCE,
            "fixture_path": row["path"],
            "fixture_type": "public-fixture (synthetic/trimmed)",
            "source_session_id": row.get("id"),
            "model": (ir.get("model") or ""),
            "messages": (ir.get("stats") or {}).get("user_messages"),
            "tool_calls": (ir.get("stats") or {}).get("tool_calls"),
            "ir_counts": ir.get("stats"),
            "lossy": list(ir.get("lossy") or []),
            "warnings": list(ir.get("warnings") or []),
            "dsh_session_id": sid,
        }
        entry["l0"] = {"ok": True, "events": (ir.get("stats") or {}).get("events"),
                       "note": "reader -> IR"}
        # B3-F1: ATIF round-trip
        try:
            doc = atif.to_atif(ir)
            errs, _ = atif.validate(doc)
            mid = atif.from_atif(doc)
            c1 = matrix.compare(ir, mid)
            entry["f1"] = {"ok": bool(c1.get("ok") and not errs), "steps": len(doc["steps"]),
                           "detail": c1.get("detail"), "lossy": c1.get("lossy") or []}
        except (OSError, ValueError) as exc:
            mid = None
            entry["f1"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
        # B3-F2: DSH staging + real Session.fromRestore
        if mid is not None:
            try:
                dsh_root = os.path.join(out_dir, source, "dsh", "sessions")
                wres = native_write(ir, "dsh", dsh_root, sid, target_cwd=os.getcwd())
                l3 = targets.l3_check("dsh", wres["artifact"], dsh_root, sid, ir)
                entry["f2"] = {"ok": bool(l3.get("ok")), "tool": l3.get("tool"),
                               "detail": l3.get("detail"), "artifact": wres["artifact"]}
            except (OSError, ValueError, RuntimeError) as exc:
                entry["f2"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
        else:
            entry["f2"] = {"ok": False, "detail": "no ATIF IR"}
        # B3-F3: writer -> reader self round-trip (format level)
        try:
            tgt = os.path.join(out_dir, source, "target")
            wres = native_write(ir, source, tgt, sid, target_cwd=ir.get("cwd") or os.getcwd())
            back = get_reader(source).load_session(path=wres["artifact"])
            expected, ph1 = _strip_placeholders(ir)
            actual, ph2 = _strip_placeholders(back)
            expected = _normalize_ids(expected, source)
            actual = _normalize_ids(actual, source)
            c2 = matrix.compare_flat(expected, actual)
            entry["f3"] = {"ok": bool(c2.get("ok")), "detail": c2.get("detail"),
                           "lossy": c2.get("lossy") or [],
                           "artifact": wres["artifact"], "native_lines": wres.get("lines"),
                           "format": wres.get("format"),
                           "placeholder_results_normalized": max(ph1, ph2)}
        except (OSError, ValueError, RuntimeError) as exc:
            entry["f3"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
        hard = entry["l0"]["ok"] and entry["f1"].get("ok") and entry["f2"].get("ok") and entry["f3"].get("ok")
        extra_lossy = list(entry.get("lossy") or [])
        if (entry["f3"].get("lossy") or []):
            extra_lossy = sorted(set(extra_lossy + entry["f3"]["lossy"]))
        entry["lossy"] = extra_lossy
        # "message_grouping_normalized" = block-level equal (native writer re-grouping), documented
        substantive = [x for x in extra_lossy if x != "message_grouping_normalized"]
        if not hard:
            entry["status"] = "fail"
        elif substantive:
            entry["status"] = "partial"
        else:
            entry["status"] = "pass"
        entries.append(entry)
        log("[%d/%d] %-8s %-22s L0=%s F1=%s F2=%s F3=%s -> %s (lossy=%s)"
            % (n, len(sources), source, os.path.basename(row["path"]), entry["l0"]["ok"],
               entry["f1"].get("ok"), entry["f2"].get("ok"), entry["f3"].get("ok"),
               entry["status"], ",".join(entry["lossy"]) or "-"))

    summary = {
        "harnesses": len(entries),
        "pass": sum(1 for e in entries if e["status"] == "pass"),
        "partial": sum(1 for e in entries if e["status"] == "partial"),
        "fail": sum(1 for e in entries if e["status"] == "fail"),
        "evidence_level": EVIDENCE,
    }
    report = {
        "schema": "asi-batch3-matrix/v1",
        "asi_version": __version__,
        "generated_at": _now(),
        "root": root,
        "out_dir": out_dir,
        "evidence_level": EVIDENCE,
        "evidence_note": "FIXTURE: public synthetic/trimmed fixtures, not real sessions; "
                         "no native CLI load is claimed (B3-F2 is DSH-only real load).",
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


def _cell(v):
    if v is True:
        return "✅"
    if v is False:
        return "❌"
    return "—"


def render_markdown(report):
    s = report["summary"]
    lines = ["# 批 3 矩阵：6 个原生 Harness adapter（**FIXTURE 证据级**）\n"]
    lines.append("> 自动生成 by `asi matrix-batch3`（asi %s，%s）。fixtures 来自 "
                 "`samples/batch2/public-fixtures/`（public synthetic/trimmed，非真实会话）。\n"
                 % (report.get("asi_version"), report.get("generated_at")))
    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| harness 数 | %d |" % s["harnesses"])
    lines.append("| 通过 (pass) | %d |" % s["pass"])
    lines.append("| 有损 (partial) | %d |" % s["partial"])
    lines.append("| 失败 (fail) | %d |" % s["fail"])
    lines.append("| 证据等级 | **FIXTURE**（非 NATIVE） |")
    lines.append("")
    lines.append("## 按 harness\n")
    lines.append("| harness | fixture | 类型 | msgs | tool_calls | B3-F0 | B3-F1 ATIF | B3-F2 DSH load | B3-F3 自往返 | 证据 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for e in report["entries"]:
        lines.append("| %s | `%s` | %s | %s | %s | %s | %s | %s | %s | %s | **%s** |" % (
            e["harness"], os.path.basename(e.get("fixture_path") or "-"),
            "public-fixture", e.get("messages") or 0, e.get("tool_calls") or 0,
            _cell((e.get("l0") or {}).get("ok")), _cell((e.get("f1") or {}).get("ok")),
            _cell((e.get("f2") or {}).get("ok")), _cell((e.get("f3") or {}).get("ok")),
            e.get("evidence_level"), e["status"]))
    lines.append("")
    lines.append("## 每 harness 证据\n")
    for e in report["entries"]:
        lines.append("### %s（%s）\n" % (e["harness"], e.get("evidence_level")))
        lines.append("- fixture: `%s`" % (e.get("fixture_path") or "—"))
        lines.append("- IR：events=%s user=%s assistant=%s tool_calls=%s tool_results=%s"
                     % ((e.get("ir_counts") or {}).get("events"),
                        (e.get("ir_counts") or {}).get("user_messages"),
                        (e.get("ir_counts") or {}).get("assistant_messages"),
                        (e.get("ir_counts") or {}).get("tool_calls"),
                        (e.get("ir_counts") or {}).get("tool_results")))
        lines.append("- B3-F1 ATIF steps=%s ok=%s；B3-F2 DSH：%s；B3-F3 自往返 fmt=%s lines=%s ok=%s"
                     % ((e.get("f1") or {}).get("steps"), _cell((e.get("f1") or {}).get("ok")),
                        (e.get("f2") or {}).get("detail") or _cell((e.get("f2") or {}).get("ok")),
                        (e.get("f3") or {}).get("format"), (e.get("f3") or {}).get("native_lines"),
                        _cell((e.get("f3") or {}).get("ok"))))
        lines.append("- 已知有损/提示：%s" % (", ".join(e.get("lossy") or []) or "—"))
        if e.get("warnings"):
            lines.append("- reader warnings：%s" % "; ".join(e["warnings"][:6]))
        if e["status"] != "pass":
            lines.append("- 备注：%s" % _s(e.get("error") or (e.get("f3") or {}).get("detail")
                                          or (e.get("f2") or {}).get("detail")))
        lines.append("")
    lines.append("## 口径与限制\n")
    lines.append("- **证据等级 = FIXTURE**：全部 fixture 为 public synthetic/trimmed 样本，不是真实用户会话；"
                 "本轮**不宣称 NATIVE**，也不声称任何 harness CLI 可原生 `--resume` 这些产物。")
    lines.append("- **B3-F0** reader→IR；**B3-F1** IR→ATIF v1.8→IR；**B3-F2** IR→DSH staging→真实 "
                 "`Session.fromRestore`（唯一真实加载项）；**B3-F3** IR→目标原生 writer→目标 reader 读回。")
    lines.append("- 已知有损（逐 harness，均在 fixture 文档中声明）：copilot delta 合并/子代理折叠/事件裁剪；"
                 "gemini 无 cwd/标题派生/thoughts 合并、toolCalls schema 未验证；aider 无时间戳/无工具事件；"
                 "cursor 无时间戳/无 tool_result/`<user_query>` 剥壳/子代理不可识别；qwen 分支线性化/"
                 "sessionId 文件名不一致负样本；pi/omp 同族树形。")
    lines.append("- 全程只写 `--out` staging，不写真实 harness store。")
    lines.append("")
    return "\n".join(lines) + "\n"
