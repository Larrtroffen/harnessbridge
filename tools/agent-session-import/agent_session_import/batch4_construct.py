"""Batch-4 constructed SQLite golden DBs (FIXTURE-CONSTRUCTED).

Public fixtures contain no .db files, so wave-2 harnesses (hermes/devin/opencode) are
verified against **constructed** golden DBs written here.  Column names are partly
unverified (docs/formats/batch4-fixtures.md §3); each DB carries a ``meta_constructed``
table with the unverified-column list.  These DBs are NOT upstream fixtures.

Verification always opens them read-only (`mode=ro` + `PRAGMA query_only=ON`).
"""
import json
import os
import sqlite3

CONSTRUCTED = {
    "hermes": {
        "schema_source": "docs/harness-catalog.md#C + docs/formats/batch4-fixtures.md §3 B4-G2",
        "unverified_columns": ["sessions.cwd", "sessions.created_at", "messages.role",
                               "messages.content", "messages.timestamp",
                               "session_model_usage.*"],
    },
    "devin": {
        "schema_source": "docs/harness-catalog.md#C/E + batch4-fixtures.md §3 B4-G3",
        "unverified_columns": ["message_nodes.seq", "message_nodes.thinking",
                               "message_nodes.tool_calls", "sessions.working_directory",
                               "sessions.created_at"],
    },
    "opencode": {
        "schema_source": "docs/harness-catalog.md#C + batch4-fixtures.md §3 B4-G1",
        "unverified_columns": ["session.directory", "message.role", "part.data",
                               "part.time_created", "part.message_id"],
    },
}


def default_constructed_root():
    """<tool>/tests/fixtures/batch4-constructed (only constructed artifacts live here)."""
    base = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base, "tests", "fixtures", "batch4-constructed")


def _meta(con, source):
    info = CONSTRUCTED[source]
    con.execute("CREATE TABLE IF NOT EXISTS meta_constructed "
                "(key TEXT PRIMARY KEY, value TEXT)")
    for k, v in (("constructed", "true"), ("reason", "no .db in public fixtures"),
                 ("schema_source", info["schema_source"]),
                 ("unverified_columns", json.dumps(info["unverified_columns"], ensure_ascii=False))):
        con.execute("INSERT OR REPLACE INTO meta_constructed VALUES (?,?)", (k, v))


def _events(ir):
    return ir.get("events") or []


def _a_text(ev):
    return "\n".join(b.get("text") or "" for b in ev.get("blocks") or [] if b.get("type") == "text")


def write_golden_db(source, ir, path):
    """Write a constructed golden SQLite DB for hermes / devin / opencode."""
    if source not in CONSTRUCTED:
        raise ValueError("no constructed golden DB schema for %r" % (source,))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    con = sqlite3.connect(path)
    try:
        _meta(con, source)
        sid = str(ir.get("source_session_id") or "constructed-session")
        created = int(ir.get("created_at_ms") or 0)
        if source == "hermes":
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, cwd TEXT,"
                        " created_at INTEGER, updated_at INTEGER)")
            con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,"
                        " role TEXT, content TEXT, finish_reason TEXT, tool_call_id TEXT,"
                        " tool_name TEXT, timestamp INTEGER)")
            con.execute("CREATE TABLE session_model_usage (session_id TEXT, model TEXT,"
                        " input_tokens INTEGER, output_tokens INTEGER, actual_cost_usd REAL)")
            con.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",
                        (sid, ir.get("title") or "", ir.get("cwd") or "",
                         created // 1000, created // 1000))
            idx = 0
            usage_done = False
            for ev in _events(ir):
                kind = ev.get("kind")
                if kind in ("user_message", "assistant_message"):
                    idx += 1
                    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                                (idx, sid, "user" if kind == "user_message" else "assistant",
                                 _a_text(ev), "stop", None, None, ev.get("ts") or created))
                    if kind == "assistant_message" and not usage_done and ev.get("usage"):
                        u = ev["usage"]
                        con.execute("INSERT INTO session_model_usage VALUES (?,?,?,?,?)",
                                    (sid, ev.get("model") or ir.get("model") or "",
                                     u.get("inputTokens", 0), u.get("outputTokens", 0), 0.0))
                        usage_done = True
                elif kind == "tool_result":
                    idx += 1
                    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                                (idx, sid, "tool", str(ev.get("content") or ""), None,
                                 ev.get("call_id") or "", ev.get("name") or "tool",
                                 ev.get("ts") or created))
        elif source == "devin":
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT,"
                        " working_directory TEXT, backend_type TEXT, model TEXT,"
                        " agent_mode TEXT, created_at INTEGER, last_activity_at INTEGER,"
                        " main_chain_id INTEGER, hidden INTEGER)")
            con.execute("CREATE TABLE message_nodes (message_id TEXT PRIMARY KEY, session_id TEXT,"
                        " seq INTEGER, role TEXT, content TEXT, thinking TEXT, tool_calls TEXT,"
                        " tool_call_id TEXT, timestamp INTEGER)")
            con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (sid, ir.get("title") or "", ir.get("cwd") or "", "constructed",
                         ir.get("model") or "", "default", created // 1000,
                         (ir.get("updated_at_ms") or created) // 1000, 0, 0))
            seq = 0
            for ev in _events(ir):
                kind = ev.get("kind")
                if kind not in ("user_message", "assistant_message", "tool_result"):
                    continue
                seq += 1
                tools = []
                for b in ev.get("blocks") or []:
                    if b.get("type") == "tool-call":
                        try:
                            args = json.loads(b.get("arguments") or "{}")
                        except ValueError:
                            args = {}
                        tools.append({"id": b.get("id"), "index": len(tools),
                                      "kind": "function", "name": b.get("name"),
                                      "arguments": args})
                thinking = "\n".join(b.get("text") or "" for b in ev.get("blocks") or []
                                     if b.get("type") == "reasoning")
                role = {"user_message": "user", "assistant_message": "assistant"}.get(kind, "tool")
                con.execute("INSERT INTO message_nodes VALUES (?,?,?,?,?,?,?,?,?)",
                            ("m%d" % seq, sid, seq, role,
                             _a_text(ev) if kind != "tool_result" else str(ev.get("content") or ""),
                             thinking, json.dumps(tools, ensure_ascii=False),
                             ev.get("call_id") if kind == "tool_result" else None,
                             ev.get("ts") or created))
        else:  # opencode
            con.execute("CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT,"
                        " created INTEGER, updated INTEGER)")
            con.execute("CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, role TEXT,"
                        " time_created INTEGER, data TEXT)")
            con.execute("CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,"
                        " type TEXT, text TEXT, data TEXT, time_created INTEGER)")
            con.execute("INSERT INTO session VALUES (?,?,?,?,?)",
                        (sid, ir.get("title") or "", ir.get("cwd") or "", created, created))
            midx = 0
            pidx = 0
            for ev in _events(ir):
                kind = ev.get("kind")
                if kind in ("user_message", "assistant_message"):
                    midx += 1
                    mid = "msg-%d" % midx
                    con.execute("INSERT INTO message VALUES (?,?,?,?,?)",
                                (mid, sid, "user" if kind == "user_message" else "assistant",
                                 ev.get("ts") or created, "{}"))
                    for b in ev.get("blocks") or []:
                        pidx += 1
                        if b.get("type") == "text":
                            con.execute("INSERT INTO part VALUES (?,?,?,?,?,?,?)",
                                        ("part-%d" % pidx, mid, sid, "text",
                                         b.get("text") or "", "{}", ev.get("ts") or created))
                        elif b.get("type") == "reasoning":
                            con.execute("INSERT INTO part VALUES (?,?,?,?,?,?,?)",
                                        ("part-%d" % pidx, mid, sid, "reasoning",
                                         b.get("text") or "", "{}", ev.get("ts") or created))
                        elif b.get("type") == "tool-call":
                            try:
                                args = json.loads(b.get("arguments") or "{}")
                            except ValueError:
                                args = {}
                            data = {"tool": b.get("name") or "tool",
                                    "callID": b.get("id") or "",
                                    "state": {"status": "completed", "input": args}}
                            con.execute("INSERT INTO part VALUES (?,?,?,?,?,?,?)",
                                        ("part-%d" % pidx, mid, sid, "tool", "",
                                         json.dumps(data, ensure_ascii=False), ev.get("ts") or created))
                elif kind == "tool_result":
                    pidx += 1
                    data = {"tool": ev.get("name") or "tool",
                            "callID": ev.get("call_id") or "",
                            "state": {"status": "completed",
                                      "output": str(ev.get("content") or "")}}
                    con.execute("INSERT INTO part VALUES (?,?,?,?,?,?,?)",
                                ("part-%d" % pidx, "", sid, "tool", "",
                                 json.dumps(data, ensure_ascii=False), ev.get("ts") or created))
        con.commit()
    finally:
        con.close()
    return path
