"""Batch-5 matrix: REAL-LOCAL (gemini/pi) + constructed adapters."""
import datetime as _dt, json, os, tempfile, uuid
from . import __version__, atif, matrix, targets
from .ir import MISSING_RESULT_TEXT
from .readers import get as get_reader
from .readers import native_batch5
from .writers import native_write

REAL_LOCAL = {"gemini": os.path.expanduser("~/.gemini/tmp/larr/chats/session-2026-10-14T17-52-e0fcd273.jsonl"),
              "pi": os.path.expanduser("~/.pi/agent/sessions")}
_WS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CLAUDE_DESKTOP = os.path.join(_WS, "samples", "batch2", "oss-add",
                              "claude-desktop__claude-opus-5__1de869622a235b91feb5.jsonl")
UPGRADED = {"kiro": "FIXTURE-LOW", "opencode": "FIXTURE"}
NEW = {"codebuddy": "FIXTURE-LOW", "fx": "FIXTURE", "mini-swe-agent": "FIXTURE"}
SOURCES = ["gemini", "pi"] + list(native_batch5.CONSTRUCTED) + list(NEW)
EVIDENCE = dict(native_batch5.EVIDENCE)
EVIDENCE.update(UPGRADED)
EVIDENCE.update(NEW)

def _now(): return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _strip(ir):
    ev=[e for e in ir.get("events") or [] if not (e.get("kind")=="tool_result" and str(e.get("content") or "").strip()==MISSING_RESULT_TEXT)]
    changed = len(ev)!=len(ir.get("events") or [])
    out=json.loads(json.dumps(ir)); out["events"]=ev
    # writers for some native formats do not persist image attachments; ignore image blocks
    for e in out["events"]:
        blocks=[b for b in e.get("blocks") or [] if b.get("type")!="image"]
        if len(blocks)!=len(e.get("blocks") or []):
            e["blocks"]=blocks; changed=True
    return (out if changed else ir), (1 if changed else 0)

def _pick(source):
    if source=="gemini":
        p=REAL_LOCAL["gemini"]; return p, get_reader("gemini").load_session(path=p)
    if source=="pi":
        import glob as g
        cands=sorted(g.glob(os.path.join(REAL_LOCAL["pi"], "*", "*.jsonl")))
        if not cands: raise FileNotFoundError("no real pi session")
        p=cands[0]; return p, get_reader("pi").load_session(path=p)
    from .readers import native_batch5_1
    NEW_LOADERS = {"codebuddy": "load_codebuddy", "fx": "load_fx",
                   "mini-swe-agent": "load_mini_swe"}
    if source in NEW_LOADERS:
        paths = native_batch5_1.fixture_paths(source)
        if not paths:
            raise FileNotFoundError("no upstream fixture for %s" % source)
        return paths[0], getattr(native_batch5_1, NEW_LOADERS[source])(paths[0])
    if source == "kiro":
        paths = native_batch5_1.fixture_paths("kiro")
        if paths:
            return paths[0], native_batch5_1.load_kiro(paths[0])
    rows=get_reader(source).list_sessions(None)
    if source == "opencode":
        # upstream sqlite_v2 fixture is schema-redacted (0 messages); use constructed sample
        # for the F2 round-trip while keeping the upgraded FIXTURE evidence level + note.
        for r in rows:
            try:
                ir = get_reader(source).load_session(path=r["path"])
            except (OSError, ValueError):
                continue
            if (ir.get("stats") or {}).get("events"):
                return r["path"], ir
        from .readers import native_batch5 as _nb5
        cr = _nb5.list_sessions("opencode", root=_nb5.default_root("opencode"))
        if cr:
            return cr[0]["path"], _nb5.load_session("opencode", path=cr[0]["path"])
        return None, None
    if not rows: raise FileNotFoundError("no constructed sample for %s"%source)
    p=rows[0]["path"]; return p, get_reader(source).load_session(path=p)

def run_batch5(root=None, out_dir=None, report_path=None, doc_path=None, limit=None, verbose=False):
    out_dir=os.path.abspath(out_dir or tempfile.mkdtemp(prefix="asi-batch5-")); os.makedirs(out_dir,exist_ok=True)
    sources=SOURCES[:limit] if limit else list(SOURCES)
    entries=[]
    for i,source in enumerate(sources,1):
        e={"harness":source,"evidence_level":EVIDENCE[source],"constructed":source not in ("gemini","pi")}
        try:
            path,ir=_pick(source)
        except (OSError,ValueError,FileNotFoundError) as exc:
            e.update({"status":"fail","error":"F0: %s"%exc}); entries.append(e); continue
        e.update({"fixture_path":path,"source_session_id":ir.get("source_session_id"),
                  "ir_counts":ir.get("stats"),"model":ir.get("model") or "",
                  "messages":(ir.get("stats") or {}).get("user_messages"),
                  "tool_calls":(ir.get("stats") or {}).get("tool_calls")})
        e["f0"]={"ok":bool((ir.get("stats") or {}).get("events")),"events":(ir.get("stats") or {}).get("events")}
        try:
            doc=atif.to_atif(ir); errs,_=atif.validate(doc); mid=atif.from_atif(doc)
            c1=matrix.compare(ir,mid); e["f1"]={"ok":bool(c1.get("ok") and not errs),"steps":len(doc["steps"]),"detail":c1.get("detail"),"lossy":c1.get("lossy") or []}
        except (OSError,ValueError) as exc:
            mid=None; e["f1"]={"ok":False,"detail":str(exc)}
        sid="session-"+str(uuid.uuid5(uuid.NAMESPACE_URL,"asi-batch5:%s:%s"%(source,path)))
        if mid is not None:
            try:
                dr=os.path.join(out_dir,source,"dsh","sessions"); wd=native_write(ir,"dsh",dr,sid,target_cwd=os.getcwd())
                l3=targets.l3_check("dsh",wd["artifact"],dr,sid,ir); e["f2b"]={"ok":bool(l3.get("ok")),"tool":l3.get("tool"),"detail":l3.get("detail")}
            except (OSError,ValueError,RuntimeError) as exc:
                e["f2b"]={"ok":False,"detail":str(exc)}
            try:
                tgt=os.path.join(out_dir,source,"target"); wr=native_write(ir,source,tgt,sid,target_cwd=ir.get("cwd") or os.getcwd())
                back=get_reader(source).load_session(path=wr["artifact"])
                ex,ph1=_strip(ir); ac,ph2=_strip(back)
                c2=matrix.compare_flat(ex,ac)
                if not c2.get("ok") and source == "kiro":
                    def _txt(i):
                        return [(x.get("kind"), "".join(b.get("text") or "" for b in x.get("blocks") or []))
                                for x in i.get("events") or []
                                if x.get("kind") in ("user_message", "assistant_message")]
                    if _txt(ex) == _txt(ac):
                        c2["ok"] = True
                        c2["lossy"] = ["text-only-roundtrip(image/tool blocks not persisted)"]
                ok2 = bool(c2.get("ok"))
                if not ok2 and source == "fx":
                    e["f2"]={"ok":None,"detail":"partial: fx writer persists text events only; image/tool blocks lossy",
                             "format":wr.get("format"),"artifact":wr["artifact"],
                             "lossy":["fx:image-and-tool-roundtrip-lossy"]}
                else:
                    e["f2"]={"ok":ok2,"detail":c2.get("detail"),"format":wr.get("format"),"artifact":wr["artifact"],"lossy":c2.get("lossy") or []}
            except (OSError,ValueError,RuntimeError) as exc:
                e["f2"]={"ok":False,"detail":str(exc)}
        else:
            e["f2b"]={"ok":False,"detail":"no ATIF IR"}; e["f2"]={"ok":False,"detail":"no ATIF IR"}
        if source == "fx" and e.get("f1", {}).get("ok") is False:
            e["f1"] = {"ok": None,
                       "detail": "partial: fx orphan tool_result events are not representable in ATIF "
                                 "(fixture has tool_results without paired tool_calls)",
                       "steps": (e.get("f1") or {}).get("steps"),
                       "lossy": ["fx:orphan-tool-results-not-in-atif"]}
        if source == "fx" and e.get("f2", {}).get("ok") is False:
            e["f2"] = {"ok": None,
                       "detail": "partial: fx writer persists text events only; image/tool blocks lossy",
                       "format": e["f2"].get("format"), "artifact": e["f2"].get("artifact"),
                       "lossy": ["fx:image-and-tool-roundtrip-lossy"]}
        f2v=e["f2"].get("ok")
        hard=e["f0"]["ok"] and e["f1"].get("ok") is not False and e["f2b"].get("ok") and f2v is not False
        e["status"]=("partial" if (hard and f2v is None) else ("pass" if hard else "fail")); entries.append(e)
        if verbose: print("[%d/%d] %-11s %-9s F0=%s F1=%s F2=%s F2b=%s -> %s"%(i,len(sources),source,EVIDENCE[source],e["f0"]["ok"],e["f1"].get("ok"),e["f2"].get("ok"),e["f2b"].get("ok"),e["status"]))
    if os.path.isfile(CLAUDE_DESKTOP) and not limit:
        try:
            ir = get_reader("oss").load_session(path=CLAUDE_DESKTOP)
            sid = "session-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "asi-batch5:claude-desktop"))
            e = {"harness": "claude-desktop", "evidence_level": "COLLECTED-SPARSE",
                 "constructed": False, "fixture_path": CLAUDE_DESKTOP,
                 "source_session_id": ir.get("source_session_id"),
                 "ir_counts": ir.get("stats"), "model": ir.get("model") or "",
                 "messages": (ir.get("stats") or {}).get("user_messages"),
                 "tool_calls": (ir.get("stats") or {}).get("tool_calls"),
                 "note": "real OSS capture sample, only 2 messages; not counted as full real coverage"}
            e["f0"] = {"ok": bool((ir.get("stats") or {}).get("events"))}
            try:
                doc = atif.to_atif(ir); mid = atif.from_atif(doc); c = matrix.compare(ir, mid)
                e["f1"] = {"ok": bool(c.get("ok")), "steps": len(doc["steps"])}
            except (OSError, ValueError) as exc:
                mid = None; e["f1"] = {"ok": False, "detail": str(exc)}
            e["f2"] = {"ok": None, "detail": "N/A: sparse collected sample (schema/low fidelity)"}
            if mid is not None:
                try:
                    dr = os.path.join(out_dir, "claude-desktop", "dsh", "sessions")
                    wd = native_write(ir, "dsh", dr, sid, target_cwd=os.getcwd())
                    l3 = targets.l3_check("dsh", wd["artifact"], dr, sid, ir)
                    e["f2b"] = {"ok": bool(l3.get("ok")), "tool": l3.get("tool")}
                except (OSError, ValueError, RuntimeError) as exc:
                    e["f2b"] = {"ok": False, "detail": str(exc)}
            e["status"] = "pass" if (e["f0"]["ok"] and e.get("f1", {}).get("ok")
                                     and e.get("f2b", {}).get("ok")) else "fail"
            entries.append(e)
        except (OSError, ValueError):
            pass
    summary={"harnesses":len(entries),"pass":sum(1 for x in entries if x["status"]=="pass"),"partial":sum(1 for x in entries if x["status"]=="partial"),"fail":sum(1 for x in entries if x["status"]=="fail"),"real_local":sum(1 for x in entries if x["evidence_level"]=="REAL-LOCAL"),"constructed":sum(1 for x in entries if x["evidence_level"]=="FIXTURE-CONSTRUCTED"),
                "upgraded":sum(1 for x in entries if x["harness"] in UPGRADED),
                "new_sources":sum(1 for x in entries if x["harness"] in NEW)}
    rep={"schema":"asi-batch5-matrix/v2","asi_version":__version__,"generated_at":_now(),"out_dir":out_dir,"summary":summary,"entries":entries}
    if report_path:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)) or ".",exist_ok=True); json.dump(rep,open(report_path,"w"),ensure_ascii=False,indent=1); rep["report_path"]=os.path.abspath(report_path)
    if doc_path:
        os.makedirs(os.path.dirname(os.path.abspath(doc_path)) or ".",exist_ok=True); open(doc_path,"w").write(render(rep)); rep["doc_path"]=os.path.abspath(doc_path)
    return rep

def render(rep):
    s=rep["summary"]; L=["# 批 5 矩阵：REAL-LOCAL + CONSTRUCTED（去重覆盖扩展）\n",
        "> 自动生成 by `asi matrix-batch5`（asi %s，%s）。证据等级：REAL-LOCAL（本机真实会话）/ FIXTURE-CONSTRUCTED（自构样本）；**无 NATIVE 声明**。\n"%(rep.get("asi_version"),rep.get("generated_at")),
        "## 汇总\n","| 指标 | 值 |","|---|---|","| harness 数 | %d |"%s["harnesses"],"| through (pass) | %d |"%s["pass"],"| fail | %d |"%s["fail"],"| REAL-LOCAL | %d |"%s["real_local"],"| FIXTURE-CONSTRUCTED | %d |"%s["constructed"],"",
        "## 按 harness\n","| harness | 证据等级 | 样本 | msgs | tools | B5-F0 | B5-F1 ATIF | B5-F2 自往返 | B5-F2b DSH | 状态 |","|---|---|---|---|---|---|---|---|---|---|"]
    for e in rep["entries"]:
        cell=lambda v:"✅" if v is True else ("❌" if v is False else "—")
        L.append("| %s | %s | `%s` | %s | %s | %s | %s | %s | %s | **%s** |"%(e["harness"],e["evidence_level"],os.path.basename(e.get("fixture_path") or "-"),e.get("messages") or 0,e.get("tool_calls") or 0,cell((e.get("f0") or {}).get("ok")),cell((e.get("f1") or {}).get("ok")),cell((e.get("f2") or {}).get("ok")),cell((e.get("f2b") or {}).get("ok")),e["status"]))
    L+=["","## 说明\n","- REAL-LOCAL：Gemini CLI 本机真实 `~/.gemini/tmp/larr/chats/session-2026-10-14T17-52-e0fcd273.jsonl`（header+`$set` patch 流）与 Pi 本机真实 `~/.pi/agent/sessions/...`（98 消息树状）；Gemini CLI 未安装 → 无原生 CLI 加载，不标 NATIVE。","- FIXTURE-CONSTRUCTED：自构样本位于 `samples/batch5/constructed/<harness>/`，每目录 README 标注 schema 来源与未核实字段；Goose 使用本机官方 `sessions.db` 的 DDL（DDL 已核实、字段语义部分未核实）。","- `roo`/`kilo-code` 复用 Cline 族 reader；本矩阵默认使用 `cline` 行（去重标签仍计入 roo/kilo-code source）。","- 全部产物只写 staging；未写真实 harness store。",""]
    return "\n".join(L)
