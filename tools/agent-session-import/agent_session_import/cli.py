"""Command line interface: ``asi list|convert|import|verify``."""
import argparse
import datetime as _dt
import json
import os
import re
import sys

from . import SOURCES, __version__, atif, dsh
from .common import HOME, dumps
from .ir import load as load_ir, save as save_ir
from .readers import get as get_reader

DEFAULT_DSH_HOME = os.path.join(HOME, ".dsh")
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe(name):
    return (_SAFE_RE.sub("_", str(name)) or "session")[:120]


def _fmt_ts(ms):
    if not isinstance(ms, (int, float)):
        return "-"
    try:
        return _dt.datetime.fromtimestamp(float(ms) / 1000.0).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


def emit(args, message="", err=False):
    """Human progress goes to stderr in --json mode so stdout stays pure JSON."""
    if not message:
        return
    if getattr(args, "json", False):
        if err:
            print(message, file=sys.stderr)
    else:
        print(message, file=sys.stderr if err else sys.stdout)


def print_json(obj):
    print(dumps(obj, indent=1))


def _print_table(rows, as_json=False):
    if as_json:
        return
    if not rows:
        print("(no sessions found)")
        return
    print("%-38s  %-16s  %-40s  %8s  %s" % ("ID", "TIME", "TITLE", "LINES", "CWD"))
    for r in rows:
        print(
            "%-38s  %-16s  %-40s  %8s  %s"
            % (
                (r.get("id") or "")[:38],
                _fmt_ts(r.get("created_at_ms")),
                (r.get("title") or "").replace("\n", " ")[:40],
                r.get("lines") if r.get("lines") is not None else "-",
                r.get("cwd") or "-",
            )
        )
    print("\n%d session(s)" % len(rows))


# --------------------------------------------------------------------------- list
def cmd_list(args):
    if args.source == "atif":
        rows = atif.list_sessions(args.root or ".")
    else:
        root = args.root
        if args.source == "dsh" and not root and getattr(args, "dsh_home", None):
            root = os.path.join(os.path.expanduser(args.dsh_home), "sessions")
        rows = get_reader(args.source).list_sessions(root)
    if args.limit:
        rows = rows[: args.limit]
    if args.json:
        print_json({"ok": True, "command": "list", "source": args.source,
                    "count": len(rows), "sessions": rows})
        return 0
    _print_table(rows)
    return 0


# --------------------------------------------------------------------------- session selection
def _select(source, args):
    """Return list of dicts {id, path?, ref?} for convert/import."""
    if source == "atif":
        if args.session:
            path = atif.resolve_path(args.root or ".", args.session)
            if not path:
                raise SystemExit("ATIF session not found: %r" % args.session)
            return [{"id": os.path.basename(path), "path": path}]
        if not args.all:
            raise SystemExit("pass --session <file.json> or --all")
        rows = atif.list_sessions(args.root or ".")
        if args.limit:
            rows = rows[: args.limit]
        return [{"id": r["id"], "path": r["path"]} for r in rows]

    reader = get_reader(source)
    if args.session:
        return [{"id": args.session, "ref": args.session}]
    if not args.all:
        raise SystemExit("pass --session <id|path> or --all")
    rows = reader.list_sessions(args.root)
    rows = [r for r in rows if r.get("path") and os.path.isfile(r["path"])]
    if source == "codex" and not getattr(args, "include_archived", False):
        rows = [r for r in rows if not r.get("archived")]
    if args.limit:
        rows = rows[: args.limit]
    return [{"id": r["id"], "path": r["path"]} for r in rows]


def _load_ir(source, item, args):
    if source == "atif":
        doc = atif.load(item["path"])
        errs, warns = atif.validate(doc)
        if errs:
            raise ValueError("invalid ATIF document: " + "; ".join(errs[:3]))
        return atif.from_atif(doc, source_path=item["path"], keep_system=args.keep_system)
    reader = get_reader(source)
    return reader.load_session(
        root=args.root, session=item.get("ref"), path=item.get("path"), keep_system=args.keep_system
    )


# --------------------------------------------------------------------------- convert
def cmd_convert(args):
    source = args.source
    if getattr(args, "install", False) and not getattr(args, "yes", False):
        message = ("REFUSING --install without --yes (it can overwrite the target harness store).\n"
                   "  use --install --yes, or omit --install to write only to --out staging.")
        if getattr(args, "json", False):
            print_json({"ok": False, "command": "convert", "error": "--install requires --yes"})
        print(message, file=sys.stderr)
        return 2
    targets = _select(source, args)
    out_root = os.path.expanduser(args.out)
    os.makedirs(out_root, exist_ok=True)
    results = []
    done = failed = 0
    for n, item in enumerate(targets, 1):
        rec = {"source": source, "source_session_id": item.get("id"), "status": "failed"}
        try:
            ir = _load_ir(source, item, args)
        except (OSError, ValueError) as exc:
            rec["error"] = str(exc)
            results.append(rec)
            emit(args, "FAIL  %s: %s" % (item.get("id"), exc), err=True)
            failed += 1
            continue
        sid = ir.get("source_session_id") or item.get("id")
        adir = os.path.join(out_root, source, _safe(sid))
        os.makedirs(adir, exist_ok=True)
        ir_path = os.path.join(adir, "ir.json")
        save_ir(ir_path, ir)
        rec.update({"source_session_id": sid, "output_dir": adir, "ir": ir_path,
                    "stats": ir.get("stats"), "warnings": ir.get("warnings") or []})
        try:
            if args.to == "atif":
                doc = atif.to_atif(ir)
                path = os.path.join(adir, _safe(sid) + ".atif.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False, indent=1)
                    f.write("\n")
                rec.update({"artifact": path, "atif_steps": len(doc["steps"])})
                emit(args, "[%d/%d] %s %s -> %s  atif_steps=%d  artifact=%s"
                     % (n, len(targets), source, str(sid)[:24], adir,
                        len(doc["steps"]), os.path.basename(path)))
            elif args.to == "ir":
                rec["artifact"] = ir_path
                emit(args, "[%d/%d] %s %s -> %s" % (n, len(targets), source, str(sid)[:24], adir))
            elif getattr(args, "install", False):
                from . import targets as targets_mod
                res = targets_mod.install_session(
                    ir, args.to, sid, install_root=getattr(args, "install_root", None),
                    target_cwd=args.target_cwd)
                rec.update(res)
                rec["installed"] = True
                emit(args, "[%d/%d] %s %s -> INSTALL %s (%s)  isolation=%s"
                     % (n, len(targets), source, str(sid)[:24], res.get("artifact"),
                        args.to, res.get("isolation")))
            else:
                from . import writers
                res = writers.write_ir_to(ir, args.to, adir, sid, target_cwd=args.target_cwd,
                                          compress=not args.no_zstd)
                rec.update(res)
                emit(args, "[%d/%d] %s %s -> %s  native=%s  artifact=%s"
                     % (n, len(targets), source, str(sid)[:24], adir,
                        args.to, res.get("artifact")))
            rec["status"] = "ok"
            done += 1
        except (ValueError, OSError) as exc:
            rec["error"] = str(exc)
            emit(args, "FAIL  %s: %s" % (sid, exc), err=True)
            failed += 1
        results.append(rec)
    if args.json:
        print_json({"ok": failed == 0, "command": "convert", "source": source, "to": args.to,
                    "out": out_root, "summary": {"converted": done, "failed": failed,
                                                 "total": len(targets)}, "results": results})
    else:
        print("\nconverted %d session(s), %d failed; output root: %s (does NOT touch ~/.dsh)"
              % (done, failed, out_root))
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------- import
def cmd_import(args):
    source = args.source
    dsh_home = os.path.abspath(os.path.expanduser(args.dsh_home or DEFAULT_DSH_HOME))
    is_real_home = os.path.realpath(dsh_home) == os.path.realpath(DEFAULT_DSH_HOME)
    if not args.dry_run and not args.yes:
        message = ("REFUSING to write sessions without --yes.\n"
                   "  target dsh home: %s\n"
                   "  this tool never writes ~/.dsh unless you explicitly pass --yes;\n"
                   "  use --dry-run to print the plan, or --dsh-home /tmp/dsh-home-test for a sandbox."
                   % dsh_home)
        if args.json:
            print_json({"ok": False, "command": "import", "error": "--yes required",
                        "dsh_home": dsh_home})
        print(message, file=sys.stderr)
        return 2
    if not args.dry_run and is_real_home:
        print("WARNING: target is the real DSH home (%s).\n"
              "         Quit the DSH desktop app first: while running it keeps workspace state in memory\n"
              "         and may overwrite workspace.json / race on session files." % dsh_home,
              file=sys.stderr)
    if args.register and args.no_register:
        print("ERROR: --register and --no-register are mutually exclusive", file=sys.stderr)
        return 2
    args.register = bool(args.register or not args.no_register)
    targets = _select(source, args)
    results = {"imported": 0, "overwritten": 0, "skipped": 0, "failed": 0, "fallback_used": 0}
    dry = {"to_import": 0, "to_skip": 0, "failed": 0, "fallback_used": 0}
    registration = []
    records = []
    for n, item in enumerate(targets, 1):
        rec = {"source": source, "source_session_id": item.get("id")}
        try:
            ir = _load_ir(source, item, args)
            plan = dsh.plan_import(
                ir,
                dsh_home,
                target_cwd=args.target_cwd,
                fallback_cwd=args.fallback_cwd,
                keep_system=args.keep_system,
            )
        except (OSError, ValueError) as exc:
            print("FAIL  %s: %s" % (item.get("id"), exc))
            results["failed"] += 1
            dry["failed"] += 1
            rec.update({"status": "failed", "error": str(exc)})
            records.append(rec)
            continue
        rec.update({
            "session_id": plan["session_id"],
            "cwd": plan["cwd"],
            "cwd_note": plan["cwd_note"],
            "fallback_used": plan["fallback_used"],
            "source_cwd": plan.get("source_cwd"),
            "target": plan["path"],
            "events": len(plan["events"]),
        })
        if plan["fallback_used"]:
            results["fallback_used"] += 1
            dry["fallback_used"] += 1
            print("  cwd 缺失 → fallback 到 %s" % plan["cwd"])
        if args.dry_run:
            would_skip = os.path.exists(plan["path"]) and not args.overwrite
            if would_skip:
                dry["to_skip"] += 1
            else:
                dry["to_import"] += 1
            rec.update({"status": "dry-run", "would_skip": would_skip,
                        "would_register": dsh.registration_plan(
                            dsh_home, plan["cwd"], plan["session_id"])[0] if args.register else None})
            records.append(rec)
            print(
                "[dry-run %d/%d] %s %s\n  session_id: %s\n  cwd: %s (%s)\n  target: %s%s\n  events: %d"
                % (n, len(targets), source, str(ir.get("source_session_id"))[:24],
                   plan["session_id"], plan["cwd"], plan["cwd_note"], plan["path"],
                   " (would skip: artifact already exists)" if would_skip else "",
                   len(plan["events"])))
            if plan["fallback_used"]:
                print("  cwd 缺失 → fallback 到 %s" % plan["cwd"])
            if args.register:
                reg_status, reg_detail = dsh.registration_plan(dsh_home, plan["cwd"], plan["session_id"])
                print("  [dry-run] register: %s (%s)" % (reg_status, reg_detail))
                rec.update({"register_plan": {"status": reg_status, "detail": reg_detail}})
            continue
        existed = os.path.exists(plan["path"])
        try:
            status = dsh.write_import(plan, overwrite=args.overwrite)
        except OSError as exc:
            print("FAIL  %s: write failed: %s" % (plan["session_id"], exc))
            results["failed"] += 1
            rec.update({"status": "failed", "error": str(exc)})
            records.append(rec)
            continue
        if status == "skipped":
            results["skipped"] += 1
            rec["status"] = "skipped"
        elif existed:
            results["overwritten"] += 1
            rec["status"] = "overwritten"
        else:
            results["imported"] += 1
            rec["status"] = "imported"
        print(
            "[%d/%d] %s %s -> %s (cwd=%s, %s)"
            % (n, len(targets), source, str(ir.get("source_session_id"))[:24],
               plan["path"], plan["cwd"], plan["cwd_note"]))
        if plan["fallback_used"]:
            print("  cwd 缺失 → fallback 到 %s" % plan["cwd"])
        # --register works for skipped sessions too: the common real-world flow is
        # "import everything now, attach the ones already present to a workspace later".
        if args.register:
            registration.append((plan["cwd"], plan["session_id"]))
        records.append(rec)
    registered = []
    if args.register and not args.dry_run:
        for cwd, sid in registration:
            status, detail = dsh.register_in_workspace(dsh_home, cwd, sid, create=True)
            registered.append({"session_id": sid, "status": status, "detail": detail})
            print("[register] %s: %s (%s)" % (sid, status, detail))
    summary = dict(results) if not args.dry_run else {
        "would_import": dry["to_import"], "would_skip": dry["to_skip"],
        "fallback_used": dry["fallback_used"], "failed": dry["failed"], "total": len(targets)}
    if args.json:
        print_json({"ok": results["failed"] == 0, "command": "import", "source": source,
                    "dsh_home": dsh_home, "dry_run": bool(args.dry_run),
                    "register": bool(args.register), "summary": summary,
                    "results": records, "registrations": registered})
    elif args.dry_run:
        print("\n[dry-run] would import=%d would skip=%d fallback_used=%d failed=%d  dsh_home=%s"
              % (dry["to_import"], dry["to_skip"], dry["fallback_used"], dry["failed"], dsh_home))
    else:
        print("\nimported=%d overwritten=%d skipped=%d failed=%d fallback_used=%d  dsh_home=%s"
              % (results["imported"], results["overwritten"], results["skipped"],
                 results["failed"], results["fallback_used"], dsh_home))
        if not args.register:
            print("note: unregistered sessions show under 'Ungrouped' in the DSH sidebar;")
            print("      re-run with --register after quitting DSH to attach them to a workspace.")
    return 0 if results["failed"] == 0 else 1


# --------------------------------------------------------------------------- verify
def cmd_verify(args):
    artifacts = dsh.discover_artifacts(args.paths)
    if not artifacts:
        print("no session artifacts found in: %s" % ", ".join(args.paths), file=sys.stderr)
        if args.json:
            print_json({"ok": False, "command": "verify", "error": "no artifacts found",
                        "checked": 0, "failed": 0, "results": []})
        return 2
    bad = 0
    reports = []
    for path in artifacts:
        report = dsh.verify_file(path)
        ok = not report["errors"]
        if not ok:
            bad += 1
        info = report.get("info") or {}
        hdr = report.get("header") or {}
        reports.append({"path": path, "ok": ok, "errors": report["errors"],
                        "warnings": report["warnings"], "info": info, "header": hdr})
        if args.json:
            continue
        print("%s %s\n     id=%s cwd=%s events=%s surface=%s tool_calls=%s tool_results=%s"
              % ("OK  " if ok else "FAIL", path, hdr.get("id"), hdr.get("cwd"),
                 info.get("events"), info.get("surface"), info.get("tool_calls"),
                 info.get("tool_results")))
        if path.endswith(".zstd"):
            print("     frames=%s header_frame_bytes=%s" % (info.get("frames"), info.get("header_frame_bytes")))
        for w in report["warnings"]:
            print("     WARN: " + w)
        for e in report["errors"]:
            print("     ERROR: " + e)
    if args.json:
        print_json({"ok": bad == 0, "command": "verify", "checked": len(artifacts),
                    "failed": bad, "results": reports})
    else:
        print("\n%d artifact(s) checked, %d failed" % (len(artifacts), bad))
    return 0 if bad == 0 else 1


# --------------------------------------------------------------------------- product commands
def cmd_session_detail(args):
    from . import product
    try:
        report = product.session_detail(
            args.source, args.session,
            root=args.root or _product_source_root(args.source),
            max_events=args.max_events, text_limit=args.text_limit)
    except (OSError, ValueError) as exc:
        if args.json:
            print_json({"ok": False, "command": "session-detail", "error": str(exc)})
        print("session-detail failed: %s" % exc, file=sys.stderr)
        return 1
    if args.json:
        print_json(report)
    else:
        m = report["meta"]
        st = report["stats"]
        print("会话详情：%s" % (m.get("title") or report.get("session_id")))
        print("  %s｜cwd: %s｜model: %s%s" % (m.get("source_label"),
                                               m.get("cwd") or "-", m.get("model") or "-",
                                               "｜" + m.get("provider") if m.get("provider") else ""))
        print("  消息: user=%d assistant=%d tool=%d reasoning=%d system=%d compaction=%d"
              % (st["messages"]["user"], st["messages"]["assistant"], st["messages"]["tool"],
                 st["messages"]["reasoning"], st["messages"]["system"],
                 st["messages"]["compaction"]))
        u = st["usage"]
        print("  Token: " + (("input=%d output=%d cache_read=%d cache_write=%d total=%d"
                             % (u["input_tokens"], u["output_tokens"], u["cache_read_tokens"],
                                u["cache_write_tokens"], u["total_tokens"]))
                            if u["available"] else "该工具未提供"))
        print("  工具调用=%d 结果=%d 失败=%d 时长=%dms"
              % (st["tool_calls"], st["tool_results"], st["tool_errors"], st["duration_ms"]))
        print("  时间线: %d/%d 条，%d 个分区"
              % (st["events_shown"], st["events_total"], len(report["sections"])))
        for w in report["warnings"]:
            print("  ⚠ %s" % w)
    return 0


def _product_source_root(source):
    if source == "dsh":
        home = os.environ.get("DSH_HOME")
        if home:
            return os.path.join(os.path.expanduser(home), "sessions")
    return None


def cmd_detect(args):
    from . import product
    fast = not bool(getattr(args, "deep", False))
    report = product.detect(fast=fast)
    if args.json:
        print_json(report)
    else:
        print("本机可迁移的 Harness：")
        for h in report["harnesses"]:
            mark = "✓" if h["detected"] else "-"
            print("  %s %-18s %-12s sessions=%-5d %s"
                  % (mark, h["display_name"], h["family"], h["session_count"],
                     h.get("notes") or ""))
        print("\n检测到 %d 个，共 %d 个会话"
              % (report["totals"]["harnesses_detected"], report["totals"]["total_sessions"]))
    return 0


def cmd_preview(args):
    from . import product
    try:
        report = product.preview(args.source, session=args.session,
                                 root=args.root or _product_source_root(args.source),
                                 limit=args.limit or 6,
                                 keep_system=args.keep_system)
    except (OSError, ValueError) as exc:
        if args.json:
            print_json({"ok": False, "command": "preview", "error": str(exc)})
        print("preview failed: %s" % exc, file=sys.stderr)
        return 1
    if args.json:
        print_json(report)
    else:
        print("会话预览：%s" % (report.get("title") or report.get("session_id")))
        print("  cwd: %s  model: %s  provider: %s" % (report.get("cwd") or "-",
                                                      report.get("model") or "-",
                                                      report.get("provider") or "-"))
        c = report["counts"]
        print("  消息: user=%d assistant=%d tool_calls=%d tool_results=%d"
              % (c["user_messages"], c["assistant_messages"], c["tool_calls"], c["tool_results"]))
        print("\n首条用户消息:\n  %s" % (report.get("first_user_message") or "-"))
        for m in report["last_messages"]:
            print("  [%s] %s" % (m["role"], (m["text"] or "")[:300]))
    return 0


def cmd_migrate(args):
    from . import product
    report = product.migrate(
        args.source,
        sessions=args.sessions or None,
        all_limit=args.all_limit,
        limit=args.limit,
        to=args.to,
        out=args.out,
        mode=args.mode,
        target_cwd=args.target_cwd,
        register=(args.register or (args.to == "dsh" and not args.no_register)),
        dry_run=args.dry_run,
        yes=args.yes,
        dsh_home=args.dsh_home,
        fallback_cwd=args.fallback_cwd,
        overwrite=args.overwrite,
        keep_system=args.keep_system,
        root=args.root or _product_source_root(args.source),
        all_sessions=bool(getattr(args, "all", False)),
        session_mode=getattr(args, "session_mode", "keep"),
        journal=getattr(args, "journal", None),
    )
    if args.json:
        print_json(report)
    else:
        if not report.get("ok") and report.get("error"):
            print("migrate failed: %s" % report["error"], file=sys.stderr)
        elif report.get("dry_run"):
            print("[dry-run] %d 个会话，不会写入任何目录：" % len(report.get("plan") or []))
            for pl in report.get("plan") or []:
                print("  %s -> %s%s" % (pl["source_session_id"], pl["target"],
                                        " (会写入真实存储)" if pl.get("will_write_real_store") else ""))
        else:
            for r in report.get("results") or []:
                print("%s %s -> %s%s" % ("OK  " if r["status"] == "ok" else "FAIL",
                                         r["source_session_id"], r.get("artifact") or "-",
                                         "" if r["status"] == "ok" else "  " + (r.get("error") or "")))
            s = report["summary"]
            print("\n完成：total=%d ok=%d skipped=%d failed=%d verified=%d moved=%d lossy=%d"
                  % (s["total"], s["ok"], s.get("skipped", 0), s["failed"],
                     s["verified"], s.get("moved", 0), s["lossy"]))
            if report.get("to") and report.get("mode") == "install":
                print("目标 store：%s（重启目标工具后可见）"
                      % (report.get("dsh_home") or report.get("results", [{}])[0].get("installed_root")))
            if report.get("journal_path"):
                print("迁移日志：%s（可用 migrate-restore 恢复移出的源会话）" % report["journal_path"])
    if report.get("requires_yes"):
        print("REFUSING install without --yes (二次确认是必需的).", file=sys.stderr)
        return 2
    return 0 if report.get("ok") else 1


def cmd_migrate_all(args):
    from . import product
    report = product.migrate_all(
        args.to,
        sources=getattr(args, "sources", None),
        limit=args.limit,
        since_days=args.since_days,
        session_mode=args.session_mode,
        dry_run=args.dry_run,
        yes=args.yes,
        overwrite=args.overwrite,
        target_cwd=args.target_cwd,
        dsh_home=args.dsh_home,
        journal=args.journal,
        register=(args.register or (args.to == "dsh" and not args.no_register)),
        keep_system=args.keep_system,
    )
    if args.json:
        print_json(report)
    elif not report.get("ok") and report.get("error"):
        print("migrate-all failed: %s" % report["error"], file=sys.stderr)
    elif report.get("dry_run"):
        plan = report.get("plan") or {}
        print("[dry-run] 目标 store: %s；来源：%s；共 %d 个会话，零写入"
              % (report.get("target_store"), ", ".join(s["id"] for s in plan.get("sources") or []),
                 plan.get("total", 0)))
    else:
        s = report["summary"]
        print("完成：total=%d ok=%d skipped=%d failed=%d moved=%d"
              % (s["total"], s["ok"], s.get("skipped", 0), s["failed"], s.get("moved", 0)))
        if report.get("journal_path"):
            print("迁移日志：%s" % report["journal_path"])
    if report.get("requires_yes"):
        print("REFUSING migrate-all without --yes.", file=sys.stderr)
        return 2
    return 0 if report.get("ok") else 1


def cmd_dsh_workspaces(args):
    dsh_home = os.path.abspath(os.path.expanduser(
        args.dsh_home or os.environ.get("DSH_HOME") or DEFAULT_DSH_HOME))
    report = dsh.repair_workspaces(dsh_home, dry_run=not args.fix,
                                   create_workspaces=bool(getattr(args, "create_workspaces", False)))
    if args.json:
        print_json(report)
    elif not report.get("ok"):
        print("repair failed: %s" % report.get("error"), file=sys.stderr)
    else:
        print("[%s] checked=%d registered=%d mismatched=%d skipped=%d  dsh_home=%s"
              % ("dry-run" if report.get("dry_run") else "fixed", report["checked"],
                 report["registered"], report.get("mismatched", 0), report["skipped"], dsh_home))
        for d in report.get("details") or []:
            print("  %-15s %s %s" % (d.get("status"), d.get("session_id"),
                                     d.get("detail") or d.get("cwd") or d.get("reason") or ""))
        if report.get("dry_run"):
            print("re-run with --fix to register (quit the DSH desktop app first).")
    return 0 if report.get("ok") else 1


def cmd_migrate_restore(args):
    from . import product
    report = product.migrate_restore(args.journal, remove_installed=args.remove_installed,
                                     dry_run=args.dry_run)
    if args.json:
        print_json(report)
    elif not report.get("ok"):
        print("restore failed: %s" % report.get("error"), file=sys.stderr)
    else:
        s = report["summary"]
        print("%s恢复：total=%d restored=%d removed_installed=%d failed=%d"
              % ("[dry-run] " if report.get("dry_run") else "", s["total"], s["restored"],
                 s["removed_installed"], s["failed"]))
        for r in report.get("results") or []:
            print("  %-24s %s" % (r.get("status"), r.get("source_path") or ""))
    return 0 if report.get("ok") else 1


# --------------------------------------------------------------------------- matrix
def cmd_matrix(args):
    from . import matrix as matrix_mod
    sources = [x.strip() for x in (args.sources or "").split(",") if x.strip()]
    unknown = [x for x in sources if x not in matrix_mod.targets.TARGETS]
    if unknown or not sources:
        print("unknown/empty --sources: %s (choose from %s)"
              % (",".join(unknown) or "<empty>", ",".join(matrix_mod.targets.TARGETS)),
              file=sys.stderr)
        return 2
    report = matrix_mod.run_matrix(
        sources=sources, out_dir=args.out, report_path=args.report,
        doc_path=args.doc, l3=not args.no_l3, limit=args.limit,
        verbose=bool(args.verbose and not args.json))
    summary = report["summary"]
    if args.json:
        print_json(report)
    else:
        print("\ninterop matrix: pass=%d partial=%d fail=%d / %d directions; ATIF self-roundtrip %d/%d"
              % (summary["pass"], summary["partial"], summary["fail"], summary["directions_total"],
                 summary["atif_self_pass"], summary["atif_self_total"]))
        if report.get("report_path"):
            print("report: %s" % report["report_path"])
        if report.get("doc_path"):
            print("doc:    %s" % report["doc_path"])
        print("staging output: %s (no real harness store was written)" % report["out_dir"])
    return 0 if summary["fail"] == 0 else 1


# --------------------------------------------------------------------------- batch2 matrix
def cmd_matrix_batch2(args):
    from . import batch2
    report = batch2.run_batch2(
        root=args.root, out_dir=args.out, report_path=args.report, doc_path=args.doc,
        limit=args.limit,
        only=[x.strip() for x in (args.only_harness or "").split(",") if x.strip()] or None,
        do_format=not args.no_format, target_cwd=args.target_cwd, verbose=args.verbose)
    summary = report["summary"]
    if args.json:
        print_json(report)
    else:
        print("\nbatch2 matrix: harnesses=%d pass=%d partial=%d fail=%d l3_dsh=%d"
              % (summary["harnesses"], summary["pass"], summary["partial"],
                 summary["fail"], summary["l3_dsh"]))
        for fmt, st in sorted((summary.get("formats") or {}).items()):
            print("  messages_format %-18s %d/%d pass" % (fmt, st["pass"], st["total"]))
        if report.get("report_path"):
            print("report: %s" % report["report_path"])
        if report.get("doc_path"):
            print("doc:    %s" % report["doc_path"])
        print("staging output: %s (no real harness store was written)" % report["out_dir"])
    return 0 if summary["fail"] == 0 else 1


# --------------------------------------------------------------------------- batch3 matrix
def cmd_matrix_batch3(args):
    from . import batch3
    report = batch3.run_batch3(
        root=args.root, out_dir=args.out, report_path=args.report, doc_path=args.doc,
        limit=args.limit,
        only=[x.strip() for x in (args.only_harness or "").split(",") if x.strip()] or None,
        verbose=args.verbose)
    s = report["summary"]
    if args.json:
        print_json(report)
    else:
        print("\nbatch3 matrix (FIXTURE): harnesses=%d pass=%d partial=%d fail=%d"
              % (s["harnesses"], s["pass"], s["partial"], s["fail"]))
        if report.get("report_path"):
            print("report: %s" % report["report_path"])
        if report.get("doc_path"):
            print("doc:    %s" % report["doc_path"])
        print("staging output: %s (no real harness store was written)" % report["out_dir"])
    return 0 if s["fail"] == 0 else 1


# --------------------------------------------------------------------------- batch4 matrix
def cmd_matrix_batch4(args):
    from . import batch4
    report = batch4.run_batch4(
        root=args.root, out_dir=args.out, report_path=args.report, doc_path=args.doc,
        limit=args.limit,
        only=[x.strip() for x in (args.only_harness or "").split(",") if x.strip()] or None,
        verbose=args.verbose)
    s = report["summary"]
    if args.json:
        print_json(report)
    else:
        print("\nbatch4 matrix: harnesses=%d pass=%d fail=%d (evidence: %s)"
              % (s["harnesses"], s["pass"], s["fail"], ",".join(s["evidence_levels"])))
        if report.get("report_path"):
            print("report: %s" % report["report_path"])
        if report.get("doc_path"):
            print("doc:    %s" % report["doc_path"])
        print("staging output: %s (no real harness store was written)" % report["out_dir"])
    return 0 if s["fail"] == 0 else 1


# --------------------------------------------------------------------------- batch6 matrix
def cmd_matrix_batch6(args):
    from . import batch6
    only = [x.strip() for x in (args.only_harness or "").split(",") if x.strip()] or None
    report = batch6.run_batch6(report_path=args.report or batch6.DEFAULT_REPORT,
                               limit=args.limit, only=only, verbose=args.verbose)
    s = report["summary"]
    if args.json:
        print_json(report)
    else:
        print("\nbatch6 matrix: readers pass=%d/partial=%d/fail=%d；writers pass=%d/partial=%d/fail=%d"
              % (s["readers_pass"], s["readers_partial"], s["readers_fail"],
                 s["writers_pass"], s["writer_partial"], s["writers_fail"]))
        print("fixture-verified format coverage: %d/%d（REAL sessions=%d，REAL-EXAMPLE=%d）"
              % (s["fixture_verified"], s["fixture_verified_total"],
                 s["real_sessions"], s["real_example"]))
        if report.get("report_path"):
            print("report: %s" % report["report_path"])
    return 0


# --------------------------------------------------------------------------- batch5 matrix
def cmd_matrix_batch5(args):
    from . import batch5
    rep = batch5.run_batch5(root=args.root, out_dir=args.out, report_path=args.report,
                            doc_path=args.doc, limit=args.limit, verbose=args.verbose)
    s = rep["summary"]
    if args.json: print_json(rep)
    else:
        print("\nbatch5 matrix: harnesses=%d pass=%d fail=%d (REAL-LOCAL=%d, CONSTRUCTED=%d)"
              % (s["harnesses"], s["pass"], s["fail"], s["real_local"], s["constructed"]))
        if rep.get("report_path"): print("report: %s" % rep["report_path"])
        if rep.get("doc_path"): print("doc:    %s" % rep["doc_path"])
    return 0 if s["fail"] == 0 else 1


# --------------------------------------------------------------------------- main
def build_parser():
    p = argparse.ArgumentParser(
        prog="asi",
        description="Convert sessions between Claude Code / Codex / OMP / Qoder / DSH (and OSS "
        "traj-session/1 captures) with ATIF v1.8 as the hub. Never writes a real harness store.",
    )
    p.add_argument("--version", action="version", version="asi " + __version__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp, need_all=True):
        sp.add_argument("--from", dest="source", required=True, choices=list(SOURCES) + ["atif"])
        sp.add_argument("--session", help="session id or path")
        if need_all:
            sp.add_argument("--all", action="store_true", help="all sessions of that source")
        sp.add_argument("--root", help="override source root (codex home / qoder projects / omp sessions / atif dir)")
        sp.add_argument("--limit", type=int, help="max sessions")
        sp.add_argument("--keep-system", action="store_true", help="keep system/developer messages")
        sp.add_argument("--target-cwd", help="override DSH header cwd (default: source session cwd)")

    lp = sub.add_parser("list", help="list importable sessions")
    lp.add_argument("source", choices=list(SOURCES) + ["atif"])
    lp.add_argument("--root")
    lp.add_argument("--limit", type=int)
    lp.add_argument("--json", action="store_true")
    lp.add_argument("--include-archived", action="store_true", help="include archived Codex threads")
    lp.add_argument("--dsh-home", help="DSH data home for `asi list dsh` (default: ~/.dsh)")
    lp.set_defaults(func=cmd_list)

    cp = sub.add_parser("convert", help="convert sessions to DSH JSONL / ATIF (never touches ~/.dsh)")
    add_common(cp)
    cp.add_argument("--to", choices=["dsh", "atif", "ir", "claude", "codex", "qoder", "omp",
                                     "copilot", "gemini", "aider", "cursor", "qwen", "pi",
                                     "openclaw", "kimi", "grok", "droid",
                                     "hermes", "devin", "opencode",
                                     "goose", "continue", "junie", "kiro", "crush",
                                     "cline", "roo", "kilo-code", "codebuff", "openhands", "vibe"],
                    default="dsh", help="output format/target (default: dsh; "
                                        "antigravity writer is unsupported)")
    cp.add_argument("--out", default="asi-out", help="output directory (default: ./asi-out)")
    cp.add_argument("--no-zstd", action="store_true", help="skip the zstd artifact")
    cp.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    cp.add_argument("--install", action="store_true",
                    help="write into the target harness store instead of --out (requires --yes)")
    cp.add_argument("--yes", action="store_true", help="confirm --install writes")
    cp.add_argument("--install-root",
                    help="override the target harness store root for --install (reader-root semantics)")
    cp.set_defaults(func=cmd_convert)

    ip = sub.add_parser("import", help="write sessions into a DSH home (requires --yes)")
    add_common(ip)
    ip.add_argument("--dsh-home", default=DEFAULT_DSH_HOME, help="DSH data home (default: ~/.dsh)")
    ip.add_argument(
        "--fallback-cwd",
        help="cwd used only when the source cwd is missing/does not exist "
        "(existing source cwd still wins; --target-cwd overrides everything)",
    )
    ip.add_argument("--register", action="store_true", help="also add ids to workspace.json sessionIds")
    ip.add_argument("--no-register", action="store_true", help="do not touch workspace.json")
    ip.add_argument("--yes", action="store_true", help="confirm writing to the DSH home")
    ip.add_argument("--dry-run", action="store_true", help="print the import plan only")
    ip.add_argument("--overwrite", action="store_true", help="overwrite an existing session file")
    ip.add_argument("--include-archived", action="store_true")
    ip.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    ip.set_defaults(func=cmd_import)

    mp = sub.add_parser("matrix", help="run the 5-harness ordered-direction interop matrix (ATIF hub)")
    mp.add_argument("--sources", default="claude,codex,dsh,omp,qoder",
                    help="comma separated source harnesses (default: all five)")
    mp.add_argument("--out", help="staging output directory (temp dir when omitted; never a real store)")
    mp.add_argument("--report", help="write the JSON matrix report to this path")
    mp.add_argument("--doc", help="write the markdown report (e.g. docs/interop-matrix.md)")
    mp.add_argument("--json", action="store_true", help="print the full JSON report on stdout")
    mp.add_argument("--no-l3", action="store_true", help="skip native discovery/load probes")
    mp.add_argument("--limit", type=int, default=1, help="sessions per source (default 1)")
    mp.add_argument("--verbose", action="store_true", help="per-direction progress")
    mp.set_defaults(func=cmd_matrix)

    b2 = sub.add_parser("matrix-batch2",
                        help="OSS traj-session/1 capture -> ATIF -> harness matrix (15+ labels)")
    b2.add_argument("--root", default=None,
                    help="OSS capture sample dir (default: samples/batch2/oss else samples/oss)")
    b2.add_argument("--out", default=None, help="staging output dir (temp when omitted)")
    b2.add_argument("--report", default=None, help="write JSON report to this path")
    b2.add_argument("--doc", default=None, help="write markdown report (e.g. docs/interop-matrix-batch2.md)")
    b2.add_argument("--json", action="store_true", help="print the full JSON report on stdout")
    b2.add_argument("--limit", type=int, default=None, help="max harness labels")
    b2.add_argument("--only-harness", default=None, help="comma separated harness labels")
    b2.add_argument("--no-format", action="store_true",
                    help="skip the 4 format-level target round-trips (L2')")
    b2.add_argument("--target-cwd", default=None,
                    help="cwd recorded in native headers (capture format has no cwd; default: current dir)")
    b2.add_argument("--verbose", action="store_true", help="per-harness progress")
    b2.set_defaults(func=cmd_matrix_batch2)

    b3 = sub.add_parser("matrix-batch3",
                        help="batch-3 native fixture adapters matrix (6 harnesses, FIXTURE evidence)")
    b3.add_argument("--root", default=None,
                    help="public-fixtures root (default: samples/batch2/public-fixtures)")
    b3.add_argument("--out", default=None, help="staging output dir (temp when omitted)")
    b3.add_argument("--report", default=None, help="write JSON report to this path")
    b3.add_argument("--doc", default=None, help="write markdown report (e.g. docs/interop-matrix-batch3.md)")
    b3.add_argument("--json", action="store_true", help="print the full JSON report on stdout")
    b3.add_argument("--limit", type=int, default=None, help="max harnesses")
    b3.add_argument("--only-harness", default=None, help="comma separated harnesses")
    b3.add_argument("--verbose", action="store_true", help="per-harness progress")
    b3.set_defaults(func=cmd_matrix_batch3)

    b4 = sub.add_parser("matrix-batch4",
                        help="batch-4 adapters matrix (8 harnesses; FIXTURE/constructed evidence)")
    b4.add_argument("--root", default=None, help="public-fixtures root")
    b4.add_argument("--out", default=None, help="staging output dir (temp when omitted)")
    b4.add_argument("--report", default=None, help="write JSON report to this path")
    b4.add_argument("--doc", default=None, help="write markdown report (docs/interop-matrix-batch4.md)")
    b4.add_argument("--json", action="store_true", help="print the full JSON report on stdout")
    b4.add_argument("--limit", type=int, default=None, help="max harnesses")
    b4.add_argument("--only-harness", default=None, help="comma separated harnesses")
    b4.add_argument("--verbose", action="store_true", help="per-harness progress")
    b4.set_defaults(func=cmd_matrix_batch4)

    b6 = sub.add_parser("matrix-batch6",
                        help="batch-6 external-fixture reader/writer matrix (fixture-verified X/40)")
    b6.add_argument("--report", default=None,
                    help="JSON report path (default tests/artifacts/interop-matrix-batch6.json)")
    b6.add_argument("--json", action="store_true", help="print the full JSON report on stdout")
    b6.add_argument("--limit", type=int, default=None, help="max canonical reader labels")
    b6.add_argument("--only-harness", default=None, help="comma separated canonical labels")
    b6.add_argument("--verbose", action="store_true", help="per-reader/writer progress")
    b6.set_defaults(func=cmd_matrix_batch6)

    b5 = sub.add_parser("matrix-batch5", help="batch-5 REAL-LOCAL + constructed matrix")
    b5.add_argument("--root", default=None); b5.add_argument("--out", default=None)
    b5.add_argument("--report", default=None); b5.add_argument("--doc", default=None)
    b5.add_argument("--json", action="store_true"); b5.add_argument("--limit", type=int, default=None)
    b5.add_argument("--verbose", action="store_true")
    b5.set_defaults(func=cmd_matrix_batch5)

    sdp = sub.add_parser("session-detail",
                         help="会话详情/时间线/Token 统计（产品级，供 Swift App 调用）")
    sdp.add_argument("--from", dest="source", required=True, choices=list(SOURCES) + ["atif"])
    sdp.add_argument("--session", required=True, help="session id 或文件路径")
    sdp.add_argument("--root", help="override source root")
    sdp.add_argument("--max-events", type=int, default=2000,
                     help="时间线最多返回多少条事件（0=全量，默认 2000）")
    sdp.add_argument("--text-limit", type=int, default=400,
                     help="单条文本最大字符数（默认 400）")
    sdp.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    sdp.set_defaults(func=cmd_session_detail)

    dp = sub.add_parser("detect", help="检测本机可迁移的 Harness（产品级，供 Swift App 调用）")
    dp.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    dp.add_argument("--fast", action="store_true",
                    help="轻量文件系统计数（默认；不解析会话内容，<2s）")
    dp.add_argument("--deep", action="store_true",
                    help="精确检测（读取会话索引/内容，较慢但字段完整）")
    dp.set_defaults(func=cmd_detect)

    pp = sub.add_parser("preview", help="会话预览摘要（只读，不写任何目录）")
    pp.add_argument("--from", dest="source", required=True, choices=list(SOURCES) + ["atif"])
    pp.add_argument("--session", help="session id or path")
    pp.add_argument("--root", help="override source root")
    pp.add_argument("--limit", type=int, default=6, help="最近消息条数（默认 6）")
    pp.add_argument("--keep-system", action="store_true")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_preview)

    mg = sub.add_parser("migrate",
                        help="用户级迁移：转换 →（可选）写入 → verify（export 默认安全）")
    mg.add_argument("--from", dest="source", required=True, choices=list(SOURCES) + ["atif"])
    mg.add_argument("--root", help="override source root")
    mg.add_argument("--session", dest="sessions", action="append",
                    help="session id 或 path，可重复指定多个")
    mg.add_argument("--all", action="store_true", help="迁移该 source 的全部会话")
    mg.add_argument("--all-limit", type=int, default=None, help="最多迁移多少个会话")
    mg.add_argument("--limit", type=int, default=None, help="同 --all-limit（兼容）")
    mg.add_argument("--to", default="dsh",
                    help="目标：dsh（默认）/ atif / 原生 harness 名（见 convert --to）")
    mg.add_argument("--out", default=None, help="导出目录（仅 export 模式需要，default: ./asi-migrate）")
    mg.add_argument("--mode", choices=["install", "export"], default=None,
                    help="install（默认，直装目标 store，需 --yes）或 export（只写 --out）")
    mg.add_argument("--session-mode", choices=["keep", "move"], default="keep",
                    help="原会话处理：keep 保留（默认）/ move 安装校验后改名 *.migrated-*.bak（可恢复）")
    mg.add_argument("--journal", default=None,
                    help="迁移日志路径（默认 ~/Library/Application Support/SessionConverter/journals/…）")
    mg.add_argument("--target-cwd", default=None)
    mg.add_argument("--fallback-cwd", default=None)
    mg.add_argument("--register", action="store_true",
                    help="install 到 DSH 时注册到 workspace（默认开启；保留兼容）")
    mg.add_argument("--no-register", action="store_true",
                    help="不修改 workspace.json（默认会尝试注册 DSH 目标）")
    mg.add_argument("--dry-run", action="store_true", help="只打印计划，零写入")
    mg.add_argument("--yes", action="store_true", help="install 模式二次确认")
    mg.add_argument("--overwrite", action="store_true", help="install 到 DSH 时覆盖已存在会话")
    mg.add_argument("--keep-system", action="store_true")
    mg.add_argument("--dsh-home", default=None, help="DSH 数据目录（默认 DSH_HOME 或 ~/.dsh）")
    mg.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    mg.set_defaults(func=cmd_migrate)

    ma = sub.add_parser("migrate-all",
                        help="一键把其他所有 Harness 的会话迁移到目标 store（需 --yes）")
    ma.add_argument("--to", required=True,
                    choices=[h["id"] for h in __import__("agent_session_import.product", fromlist=["HARNESSES"]).HARNESSES])
    ma.add_argument("--from", dest="sources", default=None,
                    help="逗号分隔的来源 id 过滤（默认全部其他已检测 Harness）")
    ma.add_argument("--limit", type=int, default=None, help="每个来源最多多少个会话")
    ma.add_argument("--since-days", type=int, default=None, help="只迁移最近 N 天的会话")
    ma.add_argument("--session-mode", choices=["keep", "move"], default="keep")
    ma.add_argument("--dry-run", action="store_true", help="只打印计划，零写入")
    ma.add_argument("--yes", action="store_true", help="确认真实写入")
    ma.add_argument("--overwrite", action="store_true", help="覆盖目标已存在的同 id 会话（先备份）")
    ma.add_argument("--register", action="store_true", help="DSH 目标：注册到 workspace（默认开启）")
    ma.add_argument("--no-register", action="store_true", help="DSH 目标：不修改 workspace.json")
    ma.add_argument("--target-cwd", default=None)
    ma.add_argument("--keep-system", action="store_true")
    ma.add_argument("--dsh-home", default=None)
    ma.add_argument("--journal", default=None)
    ma.add_argument("--json", action="store_true")
    ma.set_defaults(func=cmd_migrate_all)

    wp = sub.add_parser("dsh-workspaces",
                        help="扫描并修复 DSH workspace.json 的会话归属（默认 dry-run）")
    wp.add_argument("--dsh-home", default=None, help="DSH data home (default: $DSH_HOME or ~/.dsh)")
    wp.add_argument("--fix", action="store_true", help="write workspace.json (quit DSH first)")
    wp.add_argument("--create-workspaces", action="store_true",
                    help="create a workspace entry for cwd paths not in workspace.json")
    wp.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    wp.set_defaults(func=cmd_dsh_workspaces)

    mr = sub.add_parser("migrate-restore",
                        help="按迁移日志恢复被移出的源会话（可选删除已安装目标文件）")
    mr.add_argument("--journal", required=True, help="迁移日志路径")
    mr.add_argument("--remove-installed", action="store_true",
                    help="同时删除本次安装到目标 store 的文件（默认不删）")
    mr.add_argument("--dry-run", action="store_true")
    mr.add_argument("--json", action="store_true")
    mr.set_defaults(func=cmd_migrate_restore)

    vp = sub.add_parser("verify", help="validate DSH session artifacts (header/seq/surfaceOp/pairing)")
    vp.add_argument("paths", nargs="+", help="session dirs, .zstd/.jsonl files, or output roots")
    vp.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    vp.set_defaults(func=cmd_verify)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
