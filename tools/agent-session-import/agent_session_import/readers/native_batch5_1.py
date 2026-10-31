"""Batch-5.1 readers/writers: upstream-fixture sources (CodeBuddy/FX/Mini-SWE)
plus fixture upgrades for Kiro / OpenCode v2.

Evidence: codebuddy=FIXTURE-LOW (Codeg-derived synthetic), fx=FIXTURE (upstream
agent-sessions fixture), mini-swe-agent=FIXTURE (Harbor upstream trajectory sample,
NOT a real user session), kiro=FIXTURE-LOW (captured/trimmed), opencode=FIXTURE
(upstream SQLite-schema JSON fixture).  No NATIVE claim.
"""
import glob
import json
import os

from ..common import iso_to_ms
from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts
from . import external_fixtures as _external

EVIDENCE = {"codebuddy": "FIXTURE-LOW", "fx": "FIXTURE",
            "mini-swe-agent": "FIXTURE", "kiro": "FIXTURE-LOW",
            "opencode": "FIXTURE"}
LABELS = {"codebuddy": "Tencent CodeBuddy", "fx": "vercel-labs FX",
          "mini-swe-agent": "mini-swe-agent", "kiro": "Kiro CLI",
          "opencode": "OpenCode (SQLite v2 fixture)"}
DEFAULT_ROOT = None


def _workspace_root():
    here = os.path.dirname(os.path.abspath(__file__))
    ws = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    return os.path.join(ws, "samples", "batch5")


def fixture_paths(source, root=None):
    if root:
        root = os.path.expanduser(root)
        if os.path.isfile(root):
            return [root]
        found = _external.files(source, root)
        if found:
            if source == "opencode":
                found = [p for p in found if "session_v2" in p.replace(os.sep, "/")] or found
            return found
    root = _workspace_root()
    if source == "codebuddy":
        return sorted(glob.glob(os.path.join(root, "codebuddy", "*.jsonl")))
    if source == "fx":
        base = os.path.join(root, "agent-sessions", "fx", "schema4")
        return [os.path.join(base, "session.json")] if os.path.isfile(
            os.path.join(base, "session.json")) else []
    if source == "mini-swe-agent":
        return [os.path.join(root, "harbor", "mini-swe-agent-trajectory.json")]
    if source == "kiro":
        return [os.path.join(root, "kiro", "sessions",
                             "7787f985-7083-420e-b99d-a74ccce5c00f", "session.jsonl")]
    if source == "opencode":
        return [os.path.join(root, "agent-sessions", "opencode", "sqlite_v2",
                             "session_v2", "ses_fixture_v2.json")]
    return []


def _finish(ir, source, path, fmt):
    ir["extra"] = {"evidence_level": EVIDENCE[source], "constructed": False,
                   "upstream_fixture": True, "source_harness": LABELS[source],
                   "source_format": fmt, "fixture_path": path,
                   "evidence_note": "upstream fixture from samples/batch5 (see SOURCE.md); "
                                    "not a NATIVE load claim"}
    finalize(ir)
    return ir


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        v = content.get("text") or content.get("data") or content.get("output")
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if v is not None else ""
    if isinstance(content, list):
        out = []
        for b in content:
            if not isinstance(b, dict):
                continue
            v = b.get("text") or b.get("data") or b.get("output")
            if isinstance(v, str):
                out.append(v)
            elif v is not None:
                out.append(json.dumps(v, ensure_ascii=False))
        return "\n".join(out)
    return ""


def _blocks(content):
    out = []
    if isinstance(content, str):
        if content.strip():
            out.append(text_block(content))
        return out
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type") or ""
        if t in ("text", "input_text", "output_text"):
            txt = b.get("text") or ""
            if txt.strip():
                out.append(text_block(txt))
        elif t in ("thinking", "reasoning"):
            txt = b.get("thinking") or b.get("text") or ""
            if txt.strip():
                out.append({"type": "reasoning", "text": txt})
        elif t in ("tool_use", "toolUse", "function_call"):
            d = b.get("data") if isinstance(b.get("data"), dict) else b
            cid = d.get("toolUseId") or d.get("id") or ""
            args = d.get("input", d.get("arguments"))
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            out.append({"type": "tool-call", "id": cid, "name": d.get("name") or "tool",
                        "arguments": args})
    return out


# --------------------------------------------------------------------------- codebuddy
def load_codebuddy(path):
    uid = os.path.basename(path)[:-6]
    ir = new_ir("codebuddy", uid, path)
    calls = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        t = row.get("type")
        ts = row.get("timestamp")
        ir["source_session_id"] = row.get("sessionId") or ir["source_session_id"]
        ir["cwd"] = row.get("cwd") or ir["cwd"]
        if t == "ai-title":
            ir["title"] = row.get("aiTitle") or ir.get("title") or ""
        elif t == "message":
            blocks = _blocks(row.get("content"))
            if blocks:
                role = "user" if (row.get("role") in ("user", "human")) else "assistant"
                add_event(ir, "user_message" if role == "user" else "assistant_message",
                          ts, blocks=blocks)
                touch_ts(ir, ts)
        elif t in ("function_call", "tool_use"):
            cid = row.get("callId") or row.get("id") or ""
            calls[cid] = row.get("name") or "tool"
            args = row.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            add_event(ir, "assistant_message", ts,
                      blocks=[{"type": "tool-call", "id": cid,
                               "name": row.get("name") or "tool", "arguments": args}])
            touch_ts(ir, ts)
        elif t in ("function_call_output", "function_call_result"):
            cid = row.get("callId") or row.get("id") or ""
            out = row.get("output") or row.get("content") or ""
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False)
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or row.get("name") or "tool",
                      content=out, is_error=bool(row.get("isError")))
            touch_ts(ir, ts)
        pd = row.get("providerData") or {}
        if isinstance(pd.get("rawUsage"), dict):
            ir["source_usage"] = pd["rawUsage"]
    if not ir.get("title"):
        for e in ir["events"]:
            if e.get("kind") == "user_message":
                txt = "\n".join(b.get("text") or "" for b in e["blocks"])
                ir["title"] = txt.strip().splitlines()[0][:80] if txt.strip() else ""
                break
    return _finish(ir, "codebuddy", path, "codebuddy-item/function-call-jsonl")


# --------------------------------------------------------------------------- fx
def load_fx(path):
    base = os.path.dirname(path)
    session = json.load(open(path, encoding="utf-8"))
    ir = new_ir("fx", session.get("id") or "fx-session", path)
    ir["cwd"] = session.get("workspace_root") or session.get("origin_workspace_root")
    ir["title"] = session.get("title") or ""
    ir["model"] = session.get("model") or ""
    ir["provider"] = session.get("provider") or "fx"
    ir["created_at_ms"] = session.get("created_at_ms") or 0
    ir["updated_at_ms"] = session.get("updated_at_ms") or ir["created_at_ms"]
    events_path = os.path.join(base, "events.jsonl")
    calls = {}
    if os.path.isfile(events_path):
        for line in open(events_path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            ev = row.get("event") or {}
            ts = row.get("timestamp_ms")
            if "user" in ev:
                u = ev["user"]
                blocks = _blocks(u.get("text") or "")
                for img in u.get("images") or []:
                    blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
                if blocks:
                    add_event(ir, "user_message", ts, blocks=blocks)
            elif "assistant" in ev:
                a = ev["assistant"]
                blocks = _blocks(a.get("text") or "")
                for step in (a.get("execution") or {}).get("tool_steps") or []:
                    if step.get("assistant") and not blocks:
                        blocks = _blocks(step["assistant"])
                    for tc in step.get("tool_calls") or []:
                        calls[tc.get("id")] = tc.get("name") or "tool"
                        blocks.append({"type": "tool-call", "id": tc.get("id") or "",
                                       "name": tc.get("name") or "tool",
                                       "arguments": tc.get("arguments_json") or "{}"})
                    for tr in step.get("tool_results") or []:
                        add_event(ir, "tool_result", ts, call_id=tr.get("tool_call_id") or "",
                                  name=tr.get("tool_name") or "tool",
                                  content=str(tr.get("output") or ""),
                                  is_error=str(tr.get("status") or "").lower() == "error")
                if blocks:
                    add_event(ir, "assistant_message", ts, blocks=blocks,
                              model=ir["model"], provider=ir["provider"])
            elif "tool_result" in ev:
                tr = ev["tool_result"]
                add_event(ir, "tool_result", ts, call_id=tr.get("tool_call_id") or "",
                          name=tr.get("tool_name") or "tool",
                          content=str(tr.get("output") or ""), is_error=False)
            touch_ts(ir, ts)
    else:
        ir["warnings"].append("fx:events-missing")
    return _finish(ir, "fx", path, "fx-schema4-session+events")


# --------------------------------------------------------------------------- mini-swe-agent
def load_mini_swe(path):
    doc = json.load(open(path, encoding="utf-8"))
    info = doc.get("info") or {}
    ir = new_ir("mini-swe-agent", os.path.basename(path)[:-5], path)
    ir["title"] = "Harbor mini-swe-agent trajectory sample (not a real user session)"
    ir["model"] = ((info.get("config") or {}).get("model") or {}).get("model_name") \
        if isinstance(info.get("config"), dict) else ""
    ir["created_at_ms"] = 0
    msgs = doc.get("messages") or doc.get("trajectory") or []
    if isinstance(msgs, dict):
        msgs = msgs.get("messages") or []
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            continue
        role = m.get("role") or ("user" if m.get("type") == "user" else "assistant")
        content = m.get("content")
        text = _text(content)
        if role == "user":
            if text.strip():
                add_event(ir, "user_message", i * 1000, blocks=[text_block(text)])
        elif role in ("assistant", "ai"):
            blocks = _blocks(content)
            if text.strip() and not blocks:
                blocks = [text_block(text)]
            if blocks:
                add_event(ir, "assistant_message", i * 1000, blocks=blocks,
                          model=ir["model"], provider="mini-swe-agent")
        elif role == "tool":
            add_event(ir, "tool_result", i * 1000,
                      call_id=m.get("tool_call_id") or "",
                      name=m.get("name") or "tool",
                      content=text, is_error=False)
    if not ir["events"]:
        ir["warnings"].append("mini-swe:no-messages-in-trajectory")
    ir["extra_warning"] = "Harbor Apache-2.0 upstream trajectory sample; not a captured user session"
    return _finish(ir, "mini-swe-agent", path, "harbor-mini-swe-trajectory-json")


# --------------------------------------------------------------------------- kiro (upstream derived)
def load_kiro(path):
    uid = os.path.basename(os.path.dirname(path)) or os.path.basename(path)
    ir = new_ir("kiro", uid, path)
    sib = os.path.join(os.path.dirname(path), "session.json")
    if os.path.isfile(sib):
        try:
            meta = json.load(open(sib, encoding="utf-8"))
            ir["title"] = meta.get("title") or meta.get("name") or ""
            ir["cwd"] = meta.get("cwd") or (meta.get("workspacePaths") or [None])[0] or ir.get("cwd")
            ir["model"] = meta.get("modelId") or ""
            if not ir.get("created_at_ms"):
                ir["created_at_ms"] = iso_to_ms(meta.get("created_at")) or 0
        except ValueError:
            pass
    calls = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind = row.get("kind")
        data = row.get("data") or {}
        ts = ((data.get("meta") or {}).get("timestamp") or 0)
        ts = int(ts) * 1000 if ts and ts < 1e12 else ts
        blocks = []
        for b in data.get("content") or []:
            if not isinstance(b, dict):
                continue
            k = b.get("kind")
            d = b.get("data")
            if k == "text" and isinstance(d, str) and d.strip():
                blocks.append(text_block(d))
            elif k == "thinking" and isinstance(d, dict) and (d.get("text") or "").strip():
                blocks.append({"type": "reasoning", "text": d["text"]})
            elif k == "toolUse" and isinstance(d, dict):
                blocks.append({"type": "tool-call", "id": d.get("toolUseId") or "",
                               "name": d.get("name") or "tool",
                               "arguments": json.dumps(d.get("input") or {}, ensure_ascii=False)})
        if kind in ("user_message", "user"):
            blk = _blocks((data.get("content") or data.get("blocks") or ""))
            if blk:
                add_event(ir, "user_message", ts, blocks=blk)
            touch_ts(ir, ts)
            continue
        elif kind in ("assistant_message", "assistant"):
            blk = _blocks((data.get("content") or data.get("blocks") or ""))
            if blk:
                add_event(ir, "assistant_message", ts, blocks=blk,
                          model=ir.get("model") or "", provider="kiro")
            touch_ts(ir, ts)
            continue
        if kind and "Prompt" in kind:
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif kind and ("Assistant" in kind or "Agent" in kind):
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=ir.get("model") or "", provider="kiro")
        elif kind and "ToolResult" in kind:
            add_event(ir, "tool_result", ts, call_id=data.get("toolUseId") or "",
                      name=data.get("name") or "tool",
                      content=_text(data.get("output") or data.get("content")), is_error=False)
        touch_ts(ir, ts)
    if not ir["events"]:
        ir["warnings"].append("kiro:no-messages")
    ir["extra_captured"] = "captured-from-real-kiro-cli, trimmed (derived from codeg)"
    return _finish(ir, "kiro", path, "kiro-cli-v1-jsonl(derived/captured)")


# --------------------------------------------------------------------------- opencode sqlite_v2 JSON fixture
def load_opencode_fixture(path):
    base = os.path.dirname(os.path.dirname(path))
    ses = json.load(open(path, encoding="utf-8"))
    uid = ses.get("id") or "opencode-v2"
    ir = new_ir("opencode", uid, path)
    ir["title"] = ses.get("title") or ""
    ir["cwd"] = ses.get("directory") or ses.get("path")
    ir["created_at_ms"] = ses.get("time_created") or ses.get("created") or 0
    msg_dir = os.path.join(base, "session_message")
    for f in sorted(glob.glob(os.path.join(msg_dir, "*.json"))):
        try:
            m = json.load(open(f, encoding="utf-8"))
        except ValueError:
            continue
        mtype = m.get("type") or ""
        data = m.get("data") or {}
        role = m.get("role") or ("user" if mtype == "user" else "assistant")
        blocks = []
        # writer output (staging): {role, time_created, parts:[{type:text,text}]}
        if "parts" in m and "data" not in m:
            for part in m.get("parts") or []:
                if isinstance(part, dict) and part.get("type") == "text" and (part.get("text") or "").strip():
                    blocks.append(text_block(part["text"]))
            ts0 = m.get("time_created") or ir["created_at_ms"]
            if blocks:
                add_event(ir, "user_message" if role == "user" else "assistant_message",
                          ts0, blocks=blocks)
                touch_ts(ir, ts0)
            continue
        txt = data.get("text") if isinstance(data, dict) else None
        if isinstance(txt, str) and txt.strip() and txt != "redacted":
            blocks.append(text_block(txt))
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                inner = b.get("data") if isinstance(b.get("data"), dict) else b
                t = inner.get("text") if isinstance(inner, dict) else None
                if isinstance(t, str) and t.strip() and t != "redacted":
                    blocks.append(text_block(t))
        ts = ((data.get("time") or {}).get("created") if isinstance(data.get("time"), dict) else None)
        if not blocks and mtype in ("user", "assistant"):
            # fixture deliberately redacts content; keep the envelope as a structural event
            blocks = [text_block("[redacted fixture content]")]
            ir["warnings"].append("opencode:redacted-fixture-content")
        if blocks:
            add_event(ir, "user_message" if role == "user" else "assistant_message",
                      ts or ir["created_at_ms"], blocks=blocks)
        touch_ts(ir, ts)
    return _finish(ir, "opencode", path, "opencode-sqlite-v2-json-fixture")


# --------------------------------------------------------------------------- writers
def write(source, ir, root, sid, target_cwd=None):
    os.makedirs(root, exist_ok=True)
    kind = source
    if kind == "codebuddy":
        p = os.path.join(root, "codebuddy", sid + ".jsonl")
        rows = []
        for ev in ir.get("events") or []:
            if ev.get("kind") in ("user_message", "assistant_message"):
                rows.append({"type": "message",
                             "role": "user" if ev["kind"] == "user_message" else "assistant",
                             "timestamp": ev.get("ts") or 0, "cwd": ir.get("cwd"),
                             "sessionId": sid, "content": ev.get("blocks") or []})
        _jsonl(p, rows); fmt = "codebuddy-jsonl"
    elif kind == "fx":
        base = os.path.join(root, "fx", sid)
        os.makedirs(base, exist_ok=True)
        json.dump({"schema_version": 4, "id": sid, "workspace_root": ir.get("cwd"),
                   "created_at_ms": ir.get("created_at_ms"),
                   "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms"),
                   "title": ir.get("title"), "model": ir.get("model"),
                   "provider": ir.get("provider") or "fx"},
                  open(os.path.join(base, "session.json"), "w"), ensure_ascii=False)
        rows = []
        for i, ev in enumerate(ir.get("events") or []):
            if ev.get("kind") == "user_message":
                rows.append({"schema_version": 3, "seq": i, "timestamp_ms": ev.get("ts"),
                             "event": {"user": {"text": "".join(b.get("text") or ""
                                                                for b in ev.get("blocks") or [])}}})
            elif ev.get("kind") == "assistant_message":
                rows.append({"schema_version": 3, "seq": i, "timestamp_ms": ev.get("ts"),
                             "event": {"assistant": {"text": "".join(b.get("text") or ""
                                                                     for b in ev.get("blocks") or [])}}})
        _jsonl(os.path.join(base, "events.jsonl"), rows)
        p = os.path.join(base, "session.json"); fmt = "fx-session+events"
    elif kind == "mini-swe-agent":
        p = os.path.join(root, "harbor", sid + ".json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        msgs = []
        for ev in ir.get("events") or []:
            if ev.get("kind") in ("user_message", "assistant_message"):
                msgs.append({"role": "user" if ev["kind"] == "user_message" else "assistant",
                             "content": [{"type": "text", "text": b.get("text") or ""}
                                         for b in ev.get("blocks") or []]})
        json.dump({"info": {"mini_version": "fixture"}, "messages": msgs},
                  open(p, "w"), ensure_ascii=False, indent=1)
        fmt = "harbor-mini-swe-trajectory-json"
    elif kind == "kiro":
        base = os.path.join(root, "kiro", "sessions", sid)
        os.makedirs(base, exist_ok=True)
        def kiro_blocks(blocks):
            out = []
            for b in blocks or []:
                if b.get("type") == "text":
                    out.append({"kind": "text", "data": b.get("text") or ""})
                elif b.get("type") == "reasoning":
                    out.append({"kind": "thinking", "data": {"text": b.get("text") or ""}})
                elif b.get("type") == "tool-call":
                    out.append({"kind": "toolUse", "data": {
                        "toolUseId": b.get("id") or "", "name": b.get("name") or "tool",
                        "input": _text({}) if False else json.loads(b.get("arguments") or "{}")
                        if isinstance(b.get("arguments"), str) else b.get("arguments") or {}}})
            return out

        rows = []
        for ev in ir.get("events") or []:
            if ev.get("kind") == "user_message":
                rows.append({"version": "v1", "kind": "Prompt",
                             "data": {"message_id": "p1", "content": kiro_blocks(ev.get("blocks")),
                                      "meta": {"timestamp": (ev.get("ts") or 0) // 1000}}})
            elif ev.get("kind") == "assistant_message":
                rows.append({"version": "v1", "kind": "AssistantMessage",
                             "data": {"message_id": "a1", "content": kiro_blocks(ev.get("blocks"))}})
        _jsonl(os.path.join(base, "session.jsonl"), rows)
        json.dump({"id": sid, "title": ir.get("title")}, open(os.path.join(base, "session.json"), "w"))
        p = os.path.join(base, "session.jsonl"); fmt = "kiro-cli-v1-jsonl"
    elif kind == "opencode":
        base = os.path.join(root, "opencode", "sqlite_v2")
        os.makedirs(os.path.join(base, "session_v2"), exist_ok=True)
        os.makedirs(os.path.join(base, "session_message"), exist_ok=True)
        json.dump({"id": sid, "title": ir.get("title"), "directory": ir.get("cwd"),
                   "time_created": ir.get("created_at_ms")},
                  open(os.path.join(base, "session_v2", "ses_fixture_v2.json"), "w"))
        idx = 0
        for ev in ir.get("events") or []:
            if ev.get("kind") not in ("user_message", "assistant_message"):
                continue
            idx += 1
            role = "user" if ev["kind"] == "user_message" else "assistant"
            json.dump({"role": role, "time_created": ev.get("ts"),
                       "parts": [{"type": "text", "text": b.get("text") or ""}
                                 for b in ev.get("blocks") or [] if b.get("type") == "text"]},
                      open(os.path.join(base, "session_message", "%03d-%s.json" % (idx, role)), "w"))
        p = os.path.join(base, "session_v2", "ses_fixture_v2.json"); fmt = "opencode-sqlite-v2-json-fixture"
    else:
        raise ValueError("no batch5.1 writer for %r" % (source,))
    return {"artifact": p, "native_root": root, "relpath": os.path.relpath(p, root),
            "session_id": sid, "format": fmt}


def _jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _generic_list(source, loader):
    out = []
    for path in fixture_paths(source):
        try:
            ir = loader(path)
        except (OSError, ValueError):
            continue
        out.append({"source": source, "id": ir.get("source_session_id"),
                    "title": (ir.get("title") or os.path.basename(path))[:120],
                    "cwd": ir.get("cwd"), "created_at_ms": ir.get("created_at_ms"),
                    "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
                    "path": path, "lines": len(ir.get("events") or []),
                    "evidence_level": EVIDENCE[source], "fixture": True})
    return out


def list_kiro_sessions():
    return _generic_list("kiro", load_kiro)


def list_opencode_sessions():
    return _generic_list("opencode", load_opencode_fixture)
