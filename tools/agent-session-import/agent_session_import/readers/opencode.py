"""OpenCode adapter.

Supports:
* the **current** OpenCode SQLite store (``<data>/opencode.db``, tables
  ``session`` / ``message`` / ``part``) used by OpenCode >= 1.19;
* the batch-5.1 upstream SQLite-v2 JSON fixture;
* the batch-4 constructed storage tree / JSON fixtures.

The SQLite path keeps the historical fixture fallbacks so existing tests and
offline fixtures keep working.
"""
import glob
import json
import os
import sqlite3

from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts
from . import native_batch4, native_batch5_1


def default_root():
    env = os.environ.get("OPENCODE_HOME") or os.environ.get("OPENCODE_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    return native_batch5_1._workspace_root()


def _db_path(root=None):
    """Locate the OpenCode SQLite store from a file or directory root."""
    root = os.path.expanduser(root) if root else default_root()
    candidates = []
    if os.path.isfile(root) and root.endswith((".db", ".sqlite")):
        candidates.append(root)
    elif os.path.isdir(root):
        candidates.extend([os.path.join(root, "opencode.db"),
                           os.path.join(root, "opencode", "opencode.db")])
    env = os.environ.get("OPENCODE_DATA_DIR") or os.environ.get("OPENCODE_HOME")
    if env:
        candidates.append(os.path.join(os.path.expanduser(env), "opencode.db"))
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, ".local", "share", "opencode", "opencode.db"))
    for p in candidates:
        if p and os.path.isfile(p) and _is_v2_db(p):
            return p
    return None


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _is_v2_db(path):
    """True for OpenCode >=1.19 `opencode.db` (session/message/part schema)."""
    try:
        conn = _connect(path)
        try:
            tables = {r[0] for r in conn.execute(
                "select name from sqlite_master where type='table'")}
            if not {"session", "message", "part"} <= tables:
                return False
            cols = {r[1] for r in conn.execute("pragma table_info(session)")}
            return {"time_updated", "time_created", "model"} <= cols
        finally:
            conn.close()
    except Exception:
        return False


def _json(raw, default):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return default


def _list_db(db):
    out = []
    conn = _connect(db)
    try:
        rows = conn.execute(
            "select id,title,directory,path,time_created,time_updated,model,"
            "tokens_input,tokens_output from session order by time_updated desc").fetchall()
        for r in rows:
            msg_count = conn.execute("select count(*) from message where session_id=?",
                                     (r["id"],)).fetchone()[0]
            model = _json(r["model"], {})
            model_id = model.get("id") or model.get("modelID") or ""
            out.append({
                "source": "opencode", "id": r["id"], "title": r["title"] or "",
                "cwd": r["directory"] or r["path"] or "",
                "created_at_ms": int(r["time_created"] or 0),
                "updated_at_ms": int(r["time_updated"] or r["time_created"] or 0),
                "path": db, "lines": msg_count, "model": model_id,
                "evidence_level": "LOCAL-SMOKE", "fixture": False,
                "layout": "opencode-sqlite-store",
            })
    finally:
        conn.close()
    return out


def _part_blocks(part):
    """Convert one OpenCode `part.data` object into IR blocks/events."""
    data = _json(part, {})
    typ = data.get("type") or ""
    blocks, results = [], []
    if typ in ("text", "input_text", "output_text"):
        text = data.get("text") or ""
        if isinstance(text, str) and text.strip():
            blocks.append(text_block(text))
    elif typ in ("reasoning", "thinking"):
        text = data.get("text") or data.get("thinking") or ""
        if isinstance(text, str) and text.strip():
            blocks.append({"type": "reasoning", "text": text})
    elif typ in ("tool", "tool_call", "tool-invocation"):
        state = data.get("state") if isinstance(data.get("state"), dict) else {}
        name = data.get("tool") or data.get("name") or "tool"
        cid = data.get("callID") or data.get("callId") or data.get("id") or ""
        args = state.get("input", data.get("input", data.get("args")))
        if not isinstance(args, str):
            args = json.dumps(args if args is not None else {}, ensure_ascii=False)
        blocks.append({"type": "tool-call", "id": cid, "name": name, "arguments": args})
        output = state.get("output")
        if isinstance(output, str) and output:
            results.append({"call_id": cid, "name": name, "content": output,
                            "is_error": bool(state.get("isError") or state.get("is_error"))})
    return blocks, results


def _load_db(db, session=None):
    conn = _connect(db)
    try:
        if session:
            row = conn.execute("select * from session where id=?", (session,)).fetchone()
        else:
            row = conn.execute("select * from session order by time_updated desc limit 1").fetchone()
        if not row:
            raise FileNotFoundError("opencode session not found: %r" % session)
        sid = row["id"]
        model = _json(row["model"], {})
        ir = new_ir("opencode", sid, db, cwd=row["directory"] or row["path"],
                    created_at_ms=int(row["time_created"] or 0))
        ir["title"] = row["title"] or ""
        ir["model"] = model.get("id") or model.get("modelID") or ""
        ir["provider"] = model.get("providerID") or model.get("provider") or ""
        usage_total = None
        messages = conn.execute(
            "select * from message where session_id=? order by time_created,id", (sid,)
        ).fetchall()
        for m in messages:
            data = _json(m["data"], {})
            role = data.get("role") or "assistant"
            ts = int(m["time_created"] or 0)
            parts = conn.execute(
                "select data from part where message_id=? order by time_created,id",
                (m["id"],)).fetchall()
            blocks, results = [], []
            for p in parts:
                b, rr = _part_blocks(p["data"])
                blocks.extend(b)
                results.extend(rr)
            # OpenCode's SQLite v2 store keeps step-start/step-finish messages as
            # well; only emit conversation-bearing messages (text/reasoning/tool).
            if not blocks and not results:
                continue
            if blocks:
                kind = "user_message" if role == "user" else "assistant_message"
                ev = {"kind": kind, "ts": ts, "blocks": blocks}
                if role == "assistant":
                    u = data.get("tokens") or {}
                    nu = normalize_usage({"input_tokens": u.get("input"),
                                          "output_tokens": u.get("output")})
                    if nu:
                        ev["usage"] = nu
                        usage_total = nu
                    if data.get("error"):
                        ir["warnings"].append("opencode:assistant-error")
                add_event(ir, **ev)
            for rr in results:
                add_event(ir, "tool_result", ts, **rr)
            touch_ts(ir, ts)
        if usage_total:
            ir["stats"]["usage"] = usage_total
        ir["extra"] = {"evidence_level": "LOCAL-SMOKE", "constructed": False,
                       "source_harness": "OpenCode", "source_format": "opencode-sqlite-store",
                       "evidence_note": "real local OpenCode SQLite store (smoke session; "
                                        "conversation model may be a local mock)"}
        finalize(ir)
        return ir
    finally:
        conn.close()


def list_sessions(root=None):
    db = _db_path(root)
    if db:
        rows = _list_db(db)
        if rows:
            return rows
    rows = native_batch5_1.list_opencode_sessions()
    if rows:
        return rows
    return native_batch4.list_sessions("opencode", root=root)


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    if path and path.endswith((".db", ".sqlite")) and os.path.isfile(path):
        if _is_v2_db(path):
            return _load_db(path, session=session)
        # legacy/constructed batch-4 SQLite fixture: keep the historical parser
        return native_batch4.load_session("opencode", root=root, session=session,
                                          path=path, keep_system=keep_system)
    db = _db_path(root)
    if db and os.path.isfile(db):
        return _load_db(db, session=session)
    if path and path.endswith("ses_fixture_v2.json"):
        return native_batch5_1.load_opencode_fixture(path)
    paths = native_batch5_1.fixture_paths("opencode")
    if not path and paths:
        return native_batch5_1.load_opencode_fixture(paths[0])
    return native_batch4.load_session("opencode", root=root, session=session,
                                      path=path, keep_system=keep_system)
