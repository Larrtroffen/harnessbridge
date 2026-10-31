"""Batch-5 readers/writers: 9 constructed adapters + REAL-LOCAL helpers.

Evidence: REAL-LOCAL (gemini/pi, existing readers pointed at local stores) and
FIXTURE-CONSTRUCTED (goose, continue, junie, kiro, crush, cline/roo/kilo-code,
codebuff, openhands, vibe).  Constructed samples live in
``samples/batch5/constructed/<harness>/`` with a README stating schema sources and
unverified fields; no NATIVE claim is made anywhere.
"""
import glob
import json
import os
import sqlite3

from ..common import iso_to_ms
from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts
from . import external_fixtures as _external

CONSTRUCTED = ("goose", "continue", "junie", "kiro", "crush", "cline",
               "roo", "kilo-code", "codebuff", "openhands", "vibe")
EVIDENCE = {s: "FIXTURE-CONSTRUCTED" for s in CONSTRUCTED}
EVIDENCE.update({"gemini": "REAL-LOCAL", "pi": "REAL-LOCAL"})
LABELS = {
    "goose": "Goose", "continue": "Continue", "junie": "JetBrains Junie",
    "kiro": "Kiro CLI", "crush": "Crush", "cline": "Cline CLI",
    "roo": "Roo Code (Cline family)", "kilo-code": "Kilo Code (Cline family)",
    "codebuff": "Codebuff", "openhands": "OpenHands", "vibe": "Mistral Vibe",
    "gemini": "Gemini CLI (REAL-LOCAL)", "pi": "Pi (REAL-LOCAL)",
}
CLINE_FAMILY = {"cline", "roo", "kilo-code"}
SQLITE_SOURCES = {"crush", "goose"}
SCHEMA_SOURCES = {
    "continue": "https://github.com/vshulcz/deja-vu .../docs/registry/continue.md + docs/formats/batch5-docs.md §1.4",
    "junie": "https://github.com/vshulcz/deja-vu .../docs/registry/junie.md + batch5-docs.md §1.8",
    "kiro": "https://github.com/getagentseal/codeburn/.../providers/kiro.md + batch5-docs.md §1.1",
    "crush": "charmbracelet/crush internal/db/migrations/20250424200609_initial.sql + batch5-docs.md §1.6",
    "cline": "codeburn providers/cline-cli.md + batch5-docs.md §1.12",
    "roo": "Roo-Code globalFileNames/task-persistence + batch5-docs.md §1.10 (same parser as cline family)",
    "kilo-code": "codeburn providers/kilo-code.md + batch5-docs.md §1.11 (thin Cline-family wrapper)",
    "codebuff": "codeburn providers/codebuff.md + batch5-docs.md §1.15",
    "openhands": "OpenHands software-agent-sdk PR #41 docs/persistence.md + batch5-docs.md §1.3",
    "vibe": "TokenTelemetry legacy layout + batch5-docs.md §1.9 (multi-generation; legacy only)",
    "goose": "local ~/.local/share/goose/sessions/sessions.db .schema (official app DB) + batch5-docs.md §1.7",
}
UNVERIFIED = {
    "continue": ["history[].message.content block variants", "toolCallStates[] shape"],
    "junie": ["SessionA2uxEvent nested agentEvent kinds", "tool block pairing"],
    "kiro": ["CLI kind names (constructed; community source lists no exact enum)"],
    "crush": ["parts JSON sub-shape", "message_count/token semantics"],
    "cline": ["assistant content block variants", "metrics usage nesting"],
    "roo": ["same parser as cline; Roo host path not constructed here"],
    "kilo-code": ["same parser as cline; Kilo host path not constructed here"],
    "codebuff": ["blocks nesting / runState.sessionState.mainAgentState.messageHistory"],
    "openhands": ["EventBase discriminated union fields", "GUI default store root"],
    "vibe": ["legacy single-json only (2.x unified layout not implemented)"],
    "goose": ["messages.content_json exact shape", "session metadata semantics"],
}
SAMPLE_TEXT = {
    "user": "Batch 5 constructed sample: list the repository files.",
    "assistant": "Batch 5 constructed sample: the repository contains two files.",
}


def default_root(source=None):
    base = os.path.abspath(os.getcwd())
    for _ in range(6):
        cand = os.path.join(base, "samples", "batch5", "constructed")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(base)
        if base == parent:
            break
        base = parent
    return os.path.join(os.getcwd(), "samples", "batch5", "constructed")


PATTERNS = {
    "goose": ("sessions/sessions.db",),
    "crush": ("project/.crush/crush.db",),
    "continue": ("sessions/*.json",),
    "junie": ("sessions/*/events.jsonl",),
    "kiro": ("sessions/cli/*.jsonl",),
    "codebuff": ("projects/*/chats/*/chat-messages.json",),
    "openhands": ("**/base_state.json",),
    "vibe": ("logs/session/session_*.json",),
    "cline": ("data/sessions/*/*.messages.json",),
    "roo": ("tasks/*/api_conversation_history.json", "data/sessions/*/*.messages.json"),
    "kilo-code": ("tasks/*/api_conversation_history.json", "data/sessions/*/*.messages.json"),
}


def _files(source, root=None):
    root = os.path.expanduser(root or default_root(source))
    if os.path.isfile(root):
        return [root]
    patterns = PATTERNS.get(source, ("**/*",))
    out = []
    # normal layout: <root>/<source>/<pattern>; external fixtures pass the
    # harness dir itself as root and nest samples (e.g. <root>/constructed/...)
    for base in (os.path.join(root, source), root):
        if not os.path.isdir(base):
            continue
        for pattern in patterns:
            out.extend(glob.glob(os.path.join(base, pattern), recursive=True))
        if out:
            break
    if _external.is_external_root(root, source):
        # extern fixtures use native layouts the constructed-sample patterns do not
        # cover (e.g. OpenHands Harbor trajectory export alongside LocalFileStore)
        out.extend(_external.files(source, root))
    if not out:
        out = _external.files(source, root)
    if source == "continue":
        out = [p for p in out if os.path.basename(p) != "sessions.json"]
    return sorted(p for p in set(out) if os.path.isfile(p))


def _finish(ir, source, path, fmt):
    ir["extra"] = {"evidence_level": EVIDENCE[source], "constructed": True,
                   "source_harness": LABELS[source], "source_format": fmt,
                   "fixture_path": path,
                   "schema_source": SCHEMA_SOURCES.get(source, ""),
                   "unverified": UNVERIFIED.get(source, [])}
    finalize(ir)
    return ir


def _ev_text(ev):
    return "\n".join(b.get("text") or b.get("placeholder") or "" for b in ev.get("blocks") or [])


# --------------------------------------------------------------------------- format writers
def _w_continue(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "continue", "sessions")
    os.makedirs(d, exist_ok=True)
    history = []
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind in ("user_message", "assistant_message"):
            history.append({"message": {"role": "user" if kind == "user_message" else "assistant",
                                        "content": _ev_text(ev)}})
    doc = {"sessionId": uid, "title": ir.get("title") or "",
           "dateCreated": ir.get("created_at_ms") or 0,
           "workspaceDirectory": ir.get("cwd") or "", "history": history}
    path = os.path.join(d, uid + ".json")
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"sessions": [{"id": uid, "title": doc["title"],
                             "dateCreated": doc["dateCreated"],
                             "workspaceDirectory": doc["workspaceDirectory"]}]},
              open(os.path.join(d, "sessions.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return path, "continue-session-json"


def _w_junie(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "junie", "sessions", uid)
    os.makedirs(d, exist_ok=True)
    events = []
    for ev in ir.get("events") or []:
        ts = ev.get("ts") or 0
        if ev.get("kind") == "user_message":
            events.append({"kind": "UserPromptEvent", "timestampMs": ts,
                           "prompt": _ev_text(ev), "presentablePrompt": _ev_text(ev)})
        elif ev.get("kind") == "assistant_message":
            events.append({"kind": "SessionA2uxEvent", "timestampMs": ts,
                           "event": {"agentEvent": {"kind": "MarkdownBlockUpdatedEvent",
                                                    "stepId": "step-1",
                                                    "markdown": _ev_text(ev)}}})
    ep = os.path.join(d, "events.jsonl")
    with open(ep, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    json.dump({"sessionId": uid, "projectDir": ir.get("cwd") or ""},
              open(os.path.join(d, "state.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    idx = os.path.join(root, "junie", "sessions", "index.jsonl")
    with open(idx, "w", encoding="utf-8") as f:
        f.write(json.dumps({"sessionId": uid, "projectDir": ir.get("cwd") or "",
                            "taskName": ir.get("title") or ""}, ensure_ascii=False) + "\n")
    return ep, "junie-events-jsonl+state"


def _w_kiro(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "kiro", "sessions", "cli")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, uid + ".jsonl")
    rows = []
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind in ("user_message", "assistant_message"):
            rows.append({"version": 1,
                         "kind": "user_message" if kind == "user_message" else "assistant_message",
                         "timestamp": ev.get("ts") or 0,
                         "data": {"content": ev.get("blocks") or []}})
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump({"session_state": {"metering_usage": {"credits": 0.0}}},
              open(os.path.join(d, uid + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return path, "kiro-cli-jsonl"


def _w_crush(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "crush", "project", ".crush")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "crush.db")
    if os.path.exists(path):
        os.unlink(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT,"
                " title TEXT NOT NULL, message_count INTEGER NOT NULL DEFAULT 0,"
                " prompt_tokens INTEGER NOT NULL DEFAULT 0,"
                " completion_tokens INTEGER NOT NULL DEFAULT 0,"
                " cost REAL NOT NULL DEFAULT 0.0, updated_at INTEGER NOT NULL,"
                " created_at INTEGER NOT NULL)")
    con.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
                " role TEXT NOT NULL, parts TEXT NOT NULL DEFAULT '[]', model TEXT,"
                " created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)")
    ts = (ir.get("created_at_ms") or 0) // 1000
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
                (uid, None, ir.get("title") or "", 0, 0, 0, 0.0, ts, ts))
    n = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind not in ("user_message", "assistant_message"):
            continue
        n += 1
        parts = [{"type": "text", "text": b.get("text") or ""} for b in ev.get("blocks") or []
                 if b.get("type") == "text"]
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                    ("%s-%d" % (uid, n), uid, "user" if kind == "user_message" else "assistant",
                     json.dumps(parts, ensure_ascii=False), ir.get("model"),
                     ev.get("ts") or ts * 1000, ev.get("ts") or ts * 1000))
    con.commit()
    con.close()
    return path, "crush-sqlite"


def _w_cline(ir, root, sid, source="cline"):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, source, "data", "sessions", uid)
    os.makedirs(d, exist_ok=True)
    messages = []
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind in ("user_message", "assistant_message"):
            messages.append({"role": "user" if kind == "user_message" else "assistant",
                             "content": ev.get("blocks") or []})
    usage = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0,
             "cacheWriteTokens": 0, "totalCost": 0.0}
    paths = os.path.join(d, uid + ".messages.json")
    json.dump({"version": 1, "updated_at": ir.get("updated_at_ms") or 0,
               "sessionId": uid, "system_prompt": "",
               "messages": messages, "agent": "batch5-constructed"},
              open(paths, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    meta = os.path.join(d, uid + ".json")
    json.dump({"session_id": uid, "title": ir.get("title") or "",
               "cwd": ir.get("cwd") or "", "model": ir.get("model") or "",
               "started_at": ir.get("created_at_ms") or 0, "ended_at": 0,
               "messages_path": paths, "metadata": {"usage": usage}},
              open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return paths, "%s-cli-session-json+%s.messages.json" % (source, source)


def _w_codebuff(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "codebuff", "projects", "constructed-project", "chats", uid)
    os.makedirs(d, exist_ok=True)
    msgs = []
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind in ("user_message", "assistant_message"):
            msgs.append({"variant": "user" if kind == "user_message" else "ai",
                         "blocks": [{"type": "text", "text": _ev_text(ev)}],
                         "timestamp": ev.get("ts") or 0})
    path = os.path.join(d, "chat-messages.json")
    json.dump(msgs, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"cwd": ir.get("cwd") or ""},
              open(os.path.join(d, "run-state.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return path, "codebuff-chat-messages-json"


def _w_openhands(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "openhands", "conversations", uid)
    ed = os.path.join(d, "events")
    os.makedirs(ed, exist_ok=True)
    json.dump({"id": uid, "title": ir.get("title") or "",
               "workspace_directory": ir.get("cwd") or "",
               "model": ir.get("model") or ""},
              open(os.path.join(d, "base_state.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    idx = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind == "user_message":
            e = {"kind": "MessageEvent", "source": "user", "message": _ev_text(ev),
                 "timestamp": ev.get("ts") or 0}
        elif kind == "assistant_message":
            e = {"kind": "MessageEvent", "source": "agent", "message": _ev_text(ev),
                 "timestamp": ev.get("ts") or 0}
        elif kind == "tool_result":
            e = {"kind": "ObservationEvent", "source": "environment",
                 "observation": {"content": str(ev.get("content") or "")},
                 "timestamp": ev.get("ts") or 0}
        else:
            continue
        json.dump(e, open(os.path.join(ed, "event_%d.json" % idx), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        idx += 1
    return os.path.join(d, "base_state.json"), "openhands-localfilestore"


def _w_vibe(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "vibe", "logs", "session")
    os.makedirs(d, exist_ok=True)
    ts = ir.get("created_at_ms") or 0
    stamp = __import__("datetime").datetime.utcfromtimestamp(ts / 1000 if ts else 0).strftime(
        "%Y%m%d_%H%M%S")
    path = os.path.join(d, "session_%s_%s.json" % (stamp, uid[:8]))
    msgs = [{"role": "user" if e.get("kind") == "user_message" else "assistant",
             "content": _ev_text(e)} for e in ir.get("events") or []
            if e.get("kind") in ("user_message", "assistant_message")]
    doc = {"session_id": uid, "metadata": {"title": ir.get("title") or "",
                                           "cwd": ir.get("cwd") or "",
                                           "model": ir.get("model") or "",
                                           "stats": {"input_tokens": 0, "output_tokens": 0}},
           "messages": msgs}
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path, "vibe-legacy-single-json"


def _w_goose(ir, root, sid):
    uid = sid[8:] if sid.startswith("session-") else sid
    d = os.path.join(root, "goose", "sessions")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "sessions.db")
    if os.path.exists(path):
        os.unlink(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',"
                " working_dir TEXT NOT NULL, created_at TIMESTAMP, updated_at TIMESTAMP,"
                " total_tokens INTEGER, input_tokens INTEGER, output_tokens INTEGER,"
                " provider_name TEXT, model_config_json TEXT, session_type TEXT DEFAULT 'user')")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " message_id TEXT, session_id TEXT NOT NULL, role TEXT NOT NULL,"
                " content_json TEXT NOT NULL, created_timestamp INTEGER NOT NULL,"
                " timestamp TIMESTAMP, tokens INTEGER, metadata_json TEXT)")
    ts = ir.get("created_at_ms") or 0
    con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (uid, ir.get("title") or "", ir.get("cwd") or "", ts, ts, 0, 0, 0,
                 "constructed", json.dumps({"model": ir.get("model") or ""}), "user"))
    n = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind not in ("user_message", "assistant_message", "tool_result"):
            continue
        n += 1
        payload = ({"type": "text", "text": str(ev.get("content") or "")}
                   if kind == "tool_result" else {"content": ev.get("blocks") or []})
        con.execute("INSERT INTO messages (message_id, session_id, role, content_json,"
                    " created_timestamp, timestamp, tokens, metadata_json) VALUES (?,?,?,?,?,?,?,?)",
                    ("%s-%d" % (uid, n), uid,
                     {"user_message": "user", "assistant_message": "assistant"}.get(kind, "tool"),
                     json.dumps(payload, ensure_ascii=False), ev.get("ts") or ts,
                     ev.get("ts") or ts, 0, "{}"))
    con.commit()
    con.close()
    return path, "goose-sqlite-official-schema"


WRITERS = {
    "continue": _w_continue, "junie": _w_junie, "kiro": _w_kiro, "crush": _w_crush,
    "cline": lambda ir, root, sid: _w_cline(ir, root, sid, "cline"),
    "roo": lambda ir, root, sid: _w_cline(ir, root, sid, "roo"),
    "kilo-code": lambda ir, root, sid: _w_cline(ir, root, sid, "kilo-code"),
    "codebuff": _w_codebuff, "openhands": _w_openhands, "vibe": _w_vibe, "goose": _w_goose,
}


def write(source, ir, root, sid, target_cwd=None):
    writer = WRITERS.get(source)
    if writer is None:
        raise ValueError("no batch5 writer for %r" % (source,))
    os.makedirs(root, exist_ok=True)
    path, fmt = writer(ir, root, sid)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": sid, "format": fmt}


# --------------------------------------------------------------------------- readers
def _read_json(path):
    return json.load(open(path, encoding="utf-8", errors="replace"))


def _user_assistant(ir, role, text, ts=None, usage=None):
    if not text:
        return
    if role in ("user", "human"):
        add_event(ir, "user_message", ts, blocks=[text_block(text)])
    elif role in ("assistant", "ai", "agent", "model", "gemini"):
        add_event(ir, "assistant_message", ts, blocks=[text_block(text)],
                  model=ir.get("model") or "", provider=ir.get("provider") or "",
                  usage=usage)
    touch_ts(ir, ts)


def _blocks_text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content
                         if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def _load_continue(path):
    doc = _read_json(path)
    uid = str(doc.get("sessionId") or os.path.basename(path)[:-5])
    ir = new_ir("continue", uid, path)
    ir["cwd"] = doc.get("workspaceDirectory")
    ir["title"] = doc.get("title") or ""
    ir["created_at_ms"] = doc.get("dateCreated") or 0
    ts0 = ir["created_at_ms"]
    for i, item in enumerate(doc.get("history") or []):
        msg = (item or {}).get("message") or {}
        _user_assistant(ir, msg.get("role"), _blocks_text_of(msg.get("content")),
                        ts0 + i * 1000)
    return _finish(ir, "continue", path, "continue-session-json")


def _load_junie(path):
    uid = os.path.basename(os.path.dirname(os.path.abspath(path))) or os.path.basename(path)
    ir = new_ir("junie", uid, path)
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        ts = ev.get("timestampMs")
        if ev.get("kind") == "UserPromptEvent":
            _user_assistant(ir, "user", ev.get("prompt") or "", ts)
        elif ev.get("kind") == "SessionA2uxEvent":
            agent = ((ev.get("event") or {}).get("agentEvent")) or {}
            k = agent.get("kind") or ""
            txt = agent.get("markdown") or agent.get("text") or agent.get("output") or ""
            if txt and ("Markdown" in k or "Result" in k or "Text" in k):
                _user_assistant(ir, "assistant", txt, ts)
    state = os.path.join(os.path.dirname(path), "state.json")
    if os.path.isfile(state):
        try:
            ir["cwd"] = _read_json(state).get("projectDir") or ir.get("cwd")
        except ValueError:
            pass
    if not ir.get("cwd"):
        ir["warnings"].append("junie:projectDir-missing")
    return _finish(ir, "junie", path, "junie-events-jsonl")


def _load_kiro(path):
    uid = os.path.basename(path)[:-6]
    ir = new_ir("kiro", uid, path)
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = (ev.get("kind") or "").lower()
        data = ev.get("data") or {}
        ts = ev.get("timestamp") or iso_to_ms(ev.get("timestamp"))
        content = data.get("content")
        text = _blocks_text_of(content) if not isinstance(content, str) else content
        if "user" in kind:
            _user_assistant(ir, "user", text, ts)
        elif "assistant" in kind:
            _user_assistant(ir, "assistant", text, ts,
                            normalize_usage(data.get("usage")))
    sib = os.path.join(os.path.dirname(path), uid + ".json")
    if os.path.isfile(sib):
        try:
            ir["extra_state"] = _read_json(sib).get("session_state")
        except ValueError:
            pass
    if not ir["events"]:
        ir["warnings"].append("kiro:no-messages")
    return _finish(ir, "kiro", path, "kiro-cli-jsonl")


def _load_crush(path):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("?", "%3F"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        sessions = [dict(r) for r in con.execute("SELECT * FROM sessions")]
        messages = [dict(r) for r in con.execute("SELECT * FROM messages ORDER BY id")]
    finally:
        con.close()
    s = sessions[0] if sessions else {}
    ir = new_ir("crush", str(s.get("id") or os.path.basename(path)), path)
    ir["title"] = s.get("title") or ""
    def _to_ms(v):
        v = int(v or 0)
        return v if v > 1e12 else v * 1000
    ir["created_at_ms"] = _to_ms(s.get("created_at"))
    for m in messages:
        try:
            parts = json.loads(m.get("parts") or "[]")
        except ValueError:
            parts = []
        text = _blocks_text_of(parts)
        _user_assistant(ir, m.get("role"), text, _to_ms(m.get("created_at")), None)
    ir["warnings"].append("crush:cwd-from-project-registry-unverified")
    return _finish(ir, "crush", path, "crush-sqlite")


def _load_cline(path, source="cline"):
    base = os.path.basename(path)
    if base.endswith(".messages.json"):
        doc = _read_json(path)
        meta_path = path[: -len(".messages.json")] + ".json"
        uid = doc.get("sessionId") or os.path.basename(os.path.dirname(path))
        ir = new_ir(source, str(uid), path)
        if os.path.isfile(meta_path):
            try:
                meta = _read_json(meta_path)
            except ValueError:
                meta = {}
            ir["title"] = meta.get("title") or ""
            ir["cwd"] = meta.get("cwd") or meta.get("workspace_root")
            ir["model"] = meta.get("model") or ""
            ir["created_at_ms"] = meta.get("started_at") or 0
            ir["source_usage"] = ((meta.get("metadata") or {}).get("usage"))
            usage = normalize_usage(ir["source_usage"])
        else:
            usage = None
            ir["warnings"].append("%s:meta-json-missing" % source)
        for i, m in enumerate(doc.get("messages") or []):
            content = m.get("content")
            text = _blocks_text_of(content)
            _user_assistant(ir, m.get("role"), text, (ir.get("created_at_ms") or 0) + i * 1000,
                            usage if m.get("role") == "assistant" else None)
        for b in [b for m in doc.get("messages") or [] for b in (m.get("content") or [])
                  if isinstance(b, dict) and b.get("type") in ("tool_use",)]:
            ir["lossy"] = ir.get("lossy") or []
            ir["lossy"].append("%s:tool-use-not-paired" % source)
        return _finish(ir, source, path, "%s-cli-messages-json" % source)
    # cline-family extension layout: tasks/<id>/api_conversation_history.json
    if base == "api_conversation_history.json":
        doc = _read_json(path)
        uid = os.path.basename(os.path.dirname(path))
        ir = new_ir(source, uid, path)
        for i, m in enumerate(doc.get("messages") or []):
            _user_assistant(ir, m.get("role"), _blocks_text_of(m.get("content")),
                            i * 1000)
        ir["warnings"].append("%s:extension-layout-constructed" % source)
        return _finish(ir, source, path, "%s-extension-history-json" % source)
    raise ValueError("unsupported %s file: %s" % (source, base))


def _load_codebuff(path):
    msgs = _read_json(path)
    uid = os.path.basename(os.path.dirname(path))
    ir = new_ir("codebuff", uid, path)
    rs = os.path.join(os.path.dirname(path), "run-state.json")
    if os.path.isfile(rs):
        try:
            ir["cwd"] = _read_json(rs).get("cwd")
        except ValueError:
            pass
    if isinstance(msgs, dict):
        msgs = msgs.get("messages") or []
    for i, m in enumerate(msgs):
        variant = (m.get("variant") or "").lower()
        text = _blocks_text_of(m.get("blocks")) or _blocks_text_of(m.get("content"))
        role = "user" if variant == "user" else "assistant"
        _user_assistant(ir, role, text, m.get("timestamp") or i * 1000)
    return _finish(ir, "codebuff", path, "codebuff-chat-messages-json")


def _load_openhands(path):
    d = os.path.dirname(os.path.abspath(path))
    uid = os.path.basename(d)
    ir = new_ir("openhands", uid, path)
    try:
        base = _read_json(path)
    except ValueError:
        base = {}
    ir["title"] = base.get("title") or ""
    ir["cwd"] = base.get("workspace_directory")
    ir["model"] = base.get("model") or ""
    ed = os.path.join(d, "events")
    files = sorted(glob.glob(os.path.join(ed, "event_*.json")),
                   key=lambda p: int(re_find_index(p)))
    for i, f in enumerate(files):
        try:
            ev = _read_json(f)
        except ValueError:
            continue
        ts = ev.get("timestamp")
        kind = ev.get("kind")
        if kind == "MessageEvent":
            _user_assistant(ir, ev.get("source"),
                            ev.get("message") or "", ts)
        elif kind == "ObservationEvent":
            add_event(ir, "tool_result", ts, call_id=ev.get("tool_call_id") or "",
                      name="tool",
                      content=str((ev.get("observation") or {}).get("content") or ""),
                      is_error=False)
    return _finish(ir, "openhands", path, "openhands-localfilestore")


def re_find_index(path):
    base = os.path.basename(path)
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits or "0"


def _load_vibe(path):
    doc = _read_json(path)
    meta = doc.get("metadata") or {}
    uid = str(doc.get("session_id") or os.path.basename(path))
    ir = new_ir("vibe", uid, path)
    ir["title"] = meta.get("title") or ""
    ir["cwd"] = meta.get("cwd")
    ir["model"] = meta.get("model") or ""
    started = doc.get("start_time") or meta.get("start_time")
    ir["created_at_ms"] = iso_to_ms(started) or 0
    stats = (meta.get("stats") or {})
    usage = normalize_usage(stats)
    for i, m in enumerate(doc.get("messages") or []):
        _user_assistant(ir, m.get("role"), _blocks_text_of(m.get("content")),
                        ir["created_at_ms"] + i * 1000,
                        usage if m.get("role") == "assistant" else None)
    return _finish(ir, "vibe", path, "vibe-legacy-single-json")


def _load_goose(path):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("?", "%3F"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        sessions = [dict(r) for r in con.execute("SELECT * FROM sessions")]
        messages = [dict(r) for r in con.execute("SELECT * FROM messages ORDER BY id")]
    finally:
        con.close()
    s = sessions[0] if sessions else {}
    ir = new_ir("goose", str(s.get("id") or os.path.basename(path)), path)
    ir["title"] = s.get("name") or s.get("description") or ""
    ir["cwd"] = s.get("working_dir")
    ir["created_at_ms"] = iso_to_ms(s.get("created_at")) or 0
    usage = normalize_usage({"input_tokens": s.get("input_tokens") or 0,
                             "output_tokens": s.get("output_tokens") or 0,
                             "total_tokens": s.get("total_tokens") or 0})
    for m in messages:
        try:
            payload = json.loads(m.get("content_json") or "{}")
        except ValueError:
            payload = {}
        text = _blocks_text_of(payload.get("content") if isinstance(payload, dict) else payload)
        if not text and isinstance(payload, dict):
            text = payload.get("text") or ""
        role = m.get("role")
        _user_assistant(ir, role, text, m.get("created_timestamp"),
                        usage if role == "assistant" else None)
    if not ir["events"]:
        ir["warnings"].append("goose:no-messages")
    return _finish(ir, "goose", path, "goose-sqlite-official-schema")


def _load_generic(ir, source, path, fmt):
    return _finish(ir, source, path, fmt)


LOADS = {
    "continue": _load_continue, "junie": _load_junie, "kiro": _load_kiro,
    "crush": _load_crush, "codebuff": _load_codebuff, "openhands": _load_openhands,
    "vibe": _load_vibe, "goose": _load_goose,
}


def load_session(source, root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or default_root(source))
    if not path:
        if session:
            cand = os.path.expanduser(session)
            if os.path.isfile(cand):
                path = cand
            else:
                for f in _files(source, root):
                    if session in f:
                        path = f
                        break
        if not path:
            files = _files(source, root)
            path = files[0] if files else None
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("%s constructed sample not found (root=%s)" % (source, root))
    norm = path.replace(os.sep, "/")
    base_name = os.path.basename(path)
    if source == "openhands" and base_name != "base_state.json" and path.endswith(".json"):
        try:
            return _external.load_openhands_harbor(path, keep_system=keep_system)
        except ValueError:
            pass
    if source == "vibe" and base_name == "meta.json":
        try:
            return _external.load_vibe_dir(path, keep_system=keep_system)
        except ValueError:
            pass
    if (source in CLINE_FAMILY and base_name.endswith("api_conversation_history.json")
            and "/research/external/fixtures/" not in norm):
        try:
            return _external.load_cline_task(path, source=source, keep_system=keep_system)
        except ValueError:
            pass
    if (_external.is_external_root(root, source)
            or "/research/external/fixtures/" in norm):
        try:
            return _external.load(path, source=source, keep_system=keep_system)
        except ValueError:
            pass
    if source in CLINE_FAMILY:
        ir = _load_cline(path, source)
        return _finish(ir, source, path, ir["extra"]["source_format"])
    loader = LOADS.get(source)
    if loader is None:
        raise ValueError("unknown batch5 source %r" % (source,))
    ir = loader(path)
    return _finish(ir, source, path, ir["extra"].get("source_format") or source)


def list_sessions(source, root=None):
    root = os.path.expanduser(root or default_root(source))
    out = []
    for path in _files(source, root):
        if source in CLINE_FAMILY and not (path.endswith(".messages.json")
                                          or os.path.basename(path).endswith("api_conversation_history.json")):
            continue
        if source in ("goose", "crush") and not path.endswith(".db"):
            continue
        try:
            ir = load_session(source, root=root, path=path)
        except (OSError, ValueError, sqlite3.Error):
            continue
        out.append({"source": source, "id": ir.get("source_session_id"),
                    "title": (ir.get("title") or os.path.basename(path))[:120],
                    "cwd": ir.get("cwd"), "created_at_ms": ir.get("created_at_ms"),
                    "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
                    "path": path, "lines": len(ir.get("events") or []),
                    "evidence_level": EVIDENCE[source],
                    "fixture": True, "constructed": True})
    return out


# --------------------------------------------------------------------------- constructed samples
def synth_ir():
    ir = new_ir("constructed", "batch5-constructed-sample", "constructed://batch5")
    ir["cwd"] = "/tmp/as-agent-lab/batch5/project"
    ir["model"] = "batch5-constructed-model"
    ir["created_at_ms"] = 1793400000000
    add_event(ir, "user_message", 1793400000000, blocks=[text_block(SAMPLE_TEXT["user"])])
    add_event(ir, "assistant_message", 1793400001000,
              blocks=[text_block(SAMPLE_TEXT["assistant"])],
              model="batch5-constructed-model", provider="batch5")
    finalize(ir)
    return ir


README_TMPL = """# {label} — CONSTRUCTED batch-5 sample

**CONSTRUCTED**: this sample was generated by `agent_session_import/batch5_construct.py`
(not captured from a real {label} installation, not an upstream fixture).

- schema source: {schema}
- unverified fields: {unverified}
- evidence level: **FIXTURE-CONSTRUCTED**
- constructed at: {built_at}
"""


def make_constructed_samples(root=None):
    """Generate the committed batch-5 constructed samples (idempotent)."""
    root = os.path.expanduser(root or default_root())
    ir = synth_ir()
    built = {}
    for source in CONSTRUCTED:
        base = os.path.join(root, source)
        os.makedirs(base, exist_ok=True)
        sid = "session-" + "b5" + source
        res = WRITERS[source](ir, root, sid)
        path = res[0] if isinstance(res, tuple) else res
        readme = os.path.join(base, "README.md")
        with open(readme, "w", encoding="utf-8") as f:
            f.write(README_TMPL.format(label=LABELS[source], schema=SCHEMA_SOURCES[source],
                                       unverified=", ".join(UNVERIFIED[source]),
                                       built_at="2026-10-30"))
        built[source] = path
    return built
