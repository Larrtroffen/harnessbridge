"""Batch-4 matrix: 8 adapters -> IR -> ATIF -> writer/reader (evidence levels honest).

Evidence levels per row: FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED.  Never NATIVE.
Wave-2 harnesses (hermes/devin/opencode) are verified against **constructed golden SQLite
DBs** written by this repo (column names partly unverified — see docs/formats/batch4-fixtures.md).
"""
import copy
import datetime as _dt
import json
import os
import tempfile
import uuid

from . import __version__, atif, matrix, targets
from . import batch4_construct
from .ir import MISSING_RESULT_TEXT
from .readers import get as get_reader
from .readers import native_batch4
from .writers import native_write

SOURCES = ("openclaw", "kimi", "grok", "droid", "antigravity",
           "hermes", "devin", "opencode")
EVIDENCE = native_batch4.EVIDENCE
CONSTRUCTED = {"hermes", "devin", "opencode"}
READER_ONLY = {"antigravity"}
JSON_PROJECTION = {
    "hermes": "agent-sessions/stage0/hermes/small.json",
    "devin": "agent-sessions/stage0/devin/small.json",
    "opencode": "agent-sessions/stage0/opencode/001.json",
}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_placeholders(ir):
    events, dropped = [], 0
    for ev in ir.get("events") or []:
        if ev.get("kind") == "tool_result" and \
                str(ev.get("content") or "").strip() == MISSING_RESULT_TEXT:
            dropped += 1
            continue
        events.append(ev)
    if not dropped:
        return ir, 0
    out = copy.deepcopy(ir)
    out["events"] = events
    return out, dropped


def _pick(source, rows):
    def score(row):
        return (1 if (row.get("lines") or 0) > 0 else 0, row.get("lines") or 0)
    for row in sorted(rows, key=score, reverse=True):
        try:
            return row, get_reader(source).load_session(path=row["path"])
        except (OSError, ValueError):
            continue
    return (rows[0], get_reader(source).load_session(path=rows[0]["path"])) if rows else (None, None)


def run_batch4(root=None, out_dir=None, report_path=None, doc_path=None, limit=None,
               only=None, verbose=False):
    root = os.path.expanduser(root or native_batch4.default_root("openclaw"))
    out_dir = os.path.abspath(out_dir or tempfile.mkdtemp(prefix="asi-batch4-"))
    os.makedirs(out_dir, exist_ok=True)
    sources = [s for s in (only or SOURCES) if s in SOURCES]
    if limit:
        sources = sources[:limit]
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    entries = []
    for n, source in enumerate(sources, 1):
        entry = {"harness": source, "evidence_level": EVIDENCE[source],
                 "reader_only": source in READER_ONLY,
                 "constructed": source in CONSTRUCTED}
        try:
            if source in CONSTRUCTED:
                # F0 on the JSON logical projection; constructed DB built below for F2/F3
                rel = JSON_PROJECTION[source]
                fixture = os.path.join(root, rel)
                ir = get_reader(source).load_session(path=fixture)
                entry["fixture_path"] = fixture
                entry["fixture_type"] = "logical JSON projection (constructed DB below)"
            else:
                rows = get_reader(source).list_sessions(root)
                row, ir = _pick(source, rows)
                if row is None or ir is None:
                    raise ValueError("no fixture")
                fixture = row["path"]
                entry["fixture_path"] = fixture
                entry["fixture_type"] = "public fixture (synthetic/trimmed)"
        except (OSError, ValueError) as exc:
            entry.update({"status": "fail", "error": "F0: %s" % exc})
            entries.append(entry)
            log("[%d] %-11s FAIL F0 %s" % (n, source, exc))
            continue
        sid = "session-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "asi-batch4:%s:%s" % (source, entry["fixture_path"])))
        entry.update({
            "source_session_id": ir.get("source_session_id"),
            "model": ir.get("model") or "",
            "messages": (ir.get("stats") or {}).get("user_messages"),
            "tool_calls": (ir.get("stats") or {}).get("tool_calls"),
            "ir_counts": ir.get("stats"),
            "lossy": list(ir.get("lossy") or []),
            "warnings": list(ir.get("warnings") or []),
            "dsh_session_id": sid,
        })
        entry["f0"] = {"ok": bool((ir.get("stats") or {}).get("events")),
                       "events": (ir.get("stats") or {}).get("events")}
        # F1: ATIF round-trip
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
        # F2/F2b: native writer -> same reader; DSH staging -> real Session.fromRestore
        if mid is not None:
            try:
                dsh_root = os.path.join(out_dir, source, "dsh", "sessions")
                wd = native_write(ir, "dsh", dsh_root, sid, target_cwd=os.getcwd())
                l3 = targets.l3_check("dsh", wd["artifact"], dsh_root, sid, ir)
                entry["f2b"] = {"ok": bool(l3.get("ok")), "tool": l3.get("tool"),
                                "detail": l3.get("detail"), "artifact": wd["artifact"]}
            except (OSError, ValueError, RuntimeError) as exc:
                entry["f2b"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
            if source in READER_ONLY:
                entry["f2"] = {"ok": None, "detail": "N/A: reader-only (native .pb writer BLOCKED)"}
            else:
                try:
                    tgt = os.path.join(out_dir, source, "target")
                    wr = native_write(ir, source, tgt, sid,
                                      target_cwd=ir.get("cwd") or os.getcwd())
                    back = get_reader(source).load_session(path=wr["artifact"])
                    expected, ph1 = _strip_placeholders(ir)
                    actual, ph2 = _strip_placeholders(back)
                    c2 = matrix.compare_flat(expected, actual)
                    entry["f2"] = {"ok": bool(c2.get("ok")), "detail": c2.get("detail"),
                                   "lossy": c2.get("lossy") or [],
                                   "artifact": wr["artifact"], "format": wr.get("format"),
                                   "evidence_level": wr.get("evidence_level") or EVIDENCE[source]}
                except (OSError, ValueError, RuntimeError) as exc:
                    entry["f2"] = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
        else:
            entry["f2b"] = {"ok": False, "detail": "no ATIF IR"}
            entry["f2"] = {"ok": False, "detail": "no ATIF IR"}
        hard = (entry["f0"].get("ok") and entry["f1"].get("ok")
                and entry["f2b"].get("ok")
                and (entry["f2"].get("ok") is not False))
        entry["status"] = "fail" if not hard else "pass"
        entries.append(entry)
        log("[%d/%d] %-11s %-40s %s F0=%s F1=%s F2=%s F2b=%s -> %s"
            % (n, len(sources), source, os.path.basename(entry["fixture_path"]),
               entry["evidence_level"], entry["f0"]["ok"], entry["f1"].get("ok"),
               entry["f2"].get("ok"), entry["f2b"].get("ok"), entry["status"]))

    summary = {"harnesses": len(entries),
               "pass": sum(1 for e in entries if e["status"] == "pass"),
               "partial": 0,
               "fail": sum(1 for e in entries if e["status"] == "fail"),
               "evidence_levels": sorted({e["evidence_level"] for e in entries}),
               "constructed": sum(1 for e in entries if e.get("constructed")),
               "reader_only": sum(1 for e in entries if e.get("reader_only"))}
    report = {"schema": "asi-batch4-matrix/v1", "asi_version": __version__,
              "generated_at": _now(), "root": root, "out_dir": out_dir,
              "evidence_note": "FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED only; no NATIVE claim. "
                               "Constructed SQLite DBs have partly unverified column names and are "
                               "not upstream fixtures.",
              "summary": summary, "entries": entries}
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
    return "✅" if v is True else ("❌" if v is False else ("N/A" if v is None else str(v)))


def _s(v, limit=300):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return str(v)[:limit]


def render_markdown(report):
    s = report["summary"]
    lines = ["# 批 4 矩阵：8 个 adapter（**FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED**）\n"]
    lines.append("> 自动生成 by `asi matrix-batch4`（asi %s，%s）。**不宣称 NATIVE**；"
                 "wave-2 使用本仓库构造的 golden SQLite DB（列名部分未核实）。\n"
                 % (report.get("asi_version"), report.get("generated_at")))
    lines.append("## 汇总\n")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| harness 数 | %d |" % s["harnesses"])
    lines.append("| 通过 (pass) | %d |" % s["pass"])
    lines.append("| 失败 (fail) | %d |" % s["fail"])
    lines.append("| 构造 DB (FIXTURE-CONSTRUCTED) | %d |" % s["constructed"])
    lines.append("| reader-only | %d |" % s["reader_only"])
    lines.append("| 证据等级集合 | %s |" % ", ".join(s["evidence_levels"]))
    lines.append("")
    lines.append("## 按 harness\n")
    lines.append("| harness | 证据等级 | fixture | msgs | tools | B4-F0 | B4-F1 ATIF | B4-F2 writer→reader | B4-F2b DSH load | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for e in report["entries"]:
        lines.append("| %s | **%s** | `%s` | %s | %s | %s | %s | %s | %s | **%s** |" % (
            e["harness"], e["evidence_level"], os.path.basename(e.get("fixture_path") or "-"),
            e.get("messages") or 0, e.get("tool_calls") or 0,
            _cell((e.get("f0") or {}).get("ok")), _cell((e.get("f1") or {}).get("ok")),
            _cell((e.get("f2") or {}).get("ok")), _cell((e.get("f2b") or {}).get("ok")),
            e["status"]))
    lines.append("")
    lines.append("## 每 harness 证据\n")
    for e in report["entries"]:
        lines.append("### %s（%s）\n" % (e["harness"], e["evidence_level"]))
        lines.append("- fixture: `%s`" % (e.get("fixture_path") or "—"))
        lines.append("- IR: events=%s user=%s assistant=%s tool_calls=%s tool_results=%s"
                     % ((e.get("ir_counts") or {}).get("events"),
                        (e.get("ir_counts") or {}).get("user_messages"),
                        (e.get("ir_counts") or {}).get("assistant_messages"),
                        (e.get("ir_counts") or {}).get("tool_calls"),
                        (e.get("ir_counts") or {}).get("tool_results")))
        lines.append("- F1 ATIF steps=%s；F2=%s；F2b=%s"
                     % ((e.get("f1") or {}).get("steps"), _s((e.get("f2") or {}).get("format")
                                                             or (e.get("f2") or {}).get("detail")),
                        _s((e.get("f2b") or {}).get("detail"))))
        lines.append("- 已知有损/提示：%s" % (", ".join(e.get("lossy") or []) or "—"))
        if e["status"] != "pass":
            lines.append("- 备注：%s" % _s(e.get("error") or (e.get("f2") or {}).get("detail")))
        lines.append("")
    lines.append("## 证据与限制\n")
    lines.append("- **证据等级逐行如实标注**（FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED），本轮不宣称 NATIVE，"
                 "不声称任何 harness CLI 可恢复这些产物。")
    lines.append("- wave 1：OpenClaw/Kimi/Grok/Droid 为 public fixture（synthetic/trimmed）；"
                 "Antigravity 为 JSONL step 转录（FIXTURE-LOW，原生 `.pb` BLOCKED，**writer 不实现**，F2=N/A）。")
    lines.append("- wave 2：Hermes/Devin/OpenCode 的 `*.db` 是本仓库**构造的 golden SQLite**（`batch4_construct.py`），"
                 "**列名/索引部分未核实，不得当作上游 fixture**；DB 内 `meta_constructed` 表记录未核实列。")
    lines.append("- DSH 加载（F2b）使用真实 `Session.fromRestore`（只读）；所有产物只写 `--out` staging，"
                 "不写真实 harness store。")
    lines.append("")
    return "\n".join(lines) + "\n"
