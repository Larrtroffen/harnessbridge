"""Batch-4 writers (format-level / FIXTURE-CONSTRUCTED; staging only).

* wave 1 native-shaped JSON/JSONL: openclaw, kimi, grok, droid
* wave 2 constructed golden SQLite DBs: hermes, devin, opencode (via batch4_construct)
* antigravity: NOT implemented (native .pb has no public schema) -> --to antigravity unsupported
"""
import datetime as _dt
import hashlib
import json
import os
import re
import uuid as _uuid

from .. import batch4_construct

SOURCES = ("openclaw", "kimi", "grok", "droid", "hermes", "devin", "opencode")
CONSTRUCTED = {"hermes", "devin", "opencode"}


def _iso(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        return "1970-01-01T00:00:00.000Z"
    return _dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _uid(sid):
    return sid[8:] if sid.startswith("session-") else sid


def _cwd(ir):
    return ir.get("cwd") or os.getcwd()


def _args(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
        except ValueError:
            return {"_raw": raw}
        return v if isinstance(v, dict) else {"_raw": raw}
    return {}


def _text(ev):
    return "\n".join(b.get("text") or "" for b in ev.get("blocks") or [] if b.get("type") == "text")


def _jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def _write_openclaw(ir, root, sid, cwd):
    uid = _uid(sid)
    path = os.path.join(root, "sessions", uid + ".jsonl")
    created = ir.get("created_at_ms") or 0
    rows = [{"type": "session", "id": uid, "version": 3, "timestamp": _iso(created),
             "cwd": cwd},
            {"type": "model_change", "id": "mc1", "parentId": uid,
             "modelId": ir.get("model") or "fixture-model",
             "provider": ir.get("provider") or "fixture-provider",
             "timestamp": _iso(created)}]
    parent = "mc1"
    n = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind not in ("user_message", "assistant_message", "tool_result"):
            continue
        n += 1
        eid = "m%d" % n
        ts = _iso(ev.get("ts") or created)
        def native_blocks(blocks):
            out = []
            for b in blocks or []:
                bt = b.get("type")
                if bt == "text":
                    out.append({"type": "text", "text": b.get("text") or ""})
                elif bt == "reasoning":
                    out.append({"type": "text", "text": b.get("text") or ""})
                elif bt == "tool-call":
                    args = _args(b.get("arguments"))
                    out.append({"type": "toolCall", "id": b.get("id") or "",
                                "name": b.get("name") or "tool",
                                "arguments": args, "input": args})
            return out

        if kind == "user_message":
            msg = {"role": "user", "content": native_blocks(ev.get("blocks"))}
        elif kind == "assistant_message":
            msg = {"role": "assistant", "content": native_blocks(ev.get("blocks")),
                   "model": ev.get("model") or ir.get("model") or "",
                   "provider": ev.get("provider") or "openclaw"}
            if ev.get("usage"):
                u = ev["usage"]
                msg["usage"] = {"input": u.get("inputTokens", 0),
                                "output": u.get("outputTokens", 0),
                                "cacheRead": u.get("cacheReadTokens", 0),
                                "cacheWrite": u.get("cacheWriteTokens", 0),
                                "totalTokens": u.get("totalTokens", 0)}
        else:
            msg = {"role": "toolResult", "toolCallId": ev.get("call_id") or "",
                   "toolName": ev.get("name") or "tool",
                   "content": [{"type": "toolResult", "content": str(ev.get("content") or ""),
                                "text": str(ev.get("content") or "")}],
                   "isError": bool(ev.get("is_error"))}
        rows.append({"type": "message", "id": eid, "parentId": parent,
                     "timestamp": ts, "message": msg})
        parent = eid
    lines = _jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "openclaw-pi-tree-jsonl"}


def _write_kimi(ir, root, sid, cwd):
    uid = _uid(sid)
    path = os.path.join(root, "sessions", uid + ".jsonl")
    created = ir.get("created_at_ms") or 0
    rows = [{"type": "metadata", "protocol_version": "1.4", "created_at": created},
            {"type": "config.update", "profileName": "agent", "systemPrompt": "",
             "modelAlias": ir.get("model") or "", "thinkingEffort": "on", "time": created},
            {"type": "tools.set_active_tools", "names": [], "time": created}]
    n = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = ev.get("ts") or created
        if kind in ("user_message", "assistant_message"):
            n += 1
            blocks = []
            tool_calls = []
            for b in ev.get("blocks") or []:
                bt = b.get("type")
                if bt == "text":
                    blocks.append({"type": "text", "text": b.get("text") or ""})
                elif bt == "reasoning":
                    blocks.append({"type": "think", "think": b.get("text") or ""})
                elif bt == "tool-call":
                    tool_calls.append({"id": b.get("id") or "",
                                       "name": b.get("name") or "tool",
                                       "arguments": json.dumps(_args(b.get("arguments")),
                                                               ensure_ascii=False)})
            inner = {"role": "user" if kind == "user_message" else "assistant",
                     "content": blocks}
            if tool_calls:
                inner["toolCalls"] = tool_calls
            msg = {"message": {"message": inner, "meta": {
                "createdAt": ts, "messageId": "m%d" % n,
                "origin": {"kind": "user" if kind == "user_message" else "assistant"},
                "model": {"model": ev.get("model") or ir.get("model") or "",
                          "provider": ev.get("provider") or "kimi"}}}}
            if kind == "assistant_message" and False:
                u = ev.get("usage") or {}
                msg["meta"]["usage"] = {"inputCacheCreation": u.get("cacheWriteTokens", 0),
                                        "inputCacheRead": u.get("cacheReadTokens", 0),
                                        "inputOther": max(0, u.get("inputTokens", 0)
                                                          - u.get("cacheReadTokens", 0)
                                                          - u.get("cacheWriteTokens", 0)),
                                        "output": u.get("outputTokens", 0)}
            rows.append({"type": "agent.message.appended", "time": ts, **msg})
        elif kind == "tool_result":
            rows.append({"type": "agent.message.appended", "time": ts,
                         "message": {"message": {"role": "tool",
                                                 "toolCallId": ev.get("call_id") or "",
                                                 "content": str(ev.get("content") or "")},
                                     "meta": {"createdAt": ts}}})
    rows.append({"type": "agent.turn.ended", "turnId": "turn-1", "outcome": "completed",
                 "time": rows[-1].get("time", created)})
    lines = _jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "kimi-events-jsonl"}


def _slug(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


def _write_grok(ir, root, sid, cwd):
    uid = _uid(sid)
    base = os.path.join(root, "sessions", _slug(cwd), uid)
    os.makedirs(base, exist_ok=True)
    created = ir.get("created_at_ms") or 0
    updated = ir.get("updated_at_ms") or created
    rows = []
    msg_count = 0
    chat_count = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = _iso(ev.get("ts") or created)
        if kind == "system_message":
            continue
        if kind == "user_message":
            msg_count += 1
            rows.append({"type": "user", "content": [{"type": "text",
                                                      "text": _text(ev)}],
                         "prompt_index": chat_count})
            chat_count += 1
        elif kind == "assistant_message":
            msg_count += 1
            tools = [{"id": b.get("id"), "name": b.get("name"),
                      "arguments": json.dumps(_args(b.get("arguments")), ensure_ascii=False)}
                     for b in ev.get("blocks") or [] if b.get("type") == "tool-call"]
            rows.append({"type": "assistant", "content": _text(ev), "tool_calls": tools,
                         "model_id": ev.get("model") or ir.get("model") or "",
                         "reasoning_effort": "fixture", "timestamp": ts})
        elif kind == "tool_result":
            msg_count += 1
            rows.append({"type": "tool_result", "tool_call_id": ev.get("call_id") or "",
                         "content": str(ev.get("content") or ""), "timestamp": ts})
    summary = {
        "info": {"id": uid, "cwd": cwd},
        "session_summary": ir.get("title") or "",
        "generated_title": ir.get("title") or "",
        "created_at": _iso(created), "updated_at": _iso(updated),
        "last_active_at": _iso(updated), "num_messages": msg_count,
        "num_chat_messages": sum(1 for r in rows if r.get("type") in ("user", "assistant")),
        "current_model_id": ir.get("model") or "", "chat_format_version": 1,
        "session_kind": "main", "next_trace_turn": 1, "git_root_dir": cwd,
    }
    with open(os.path.join(base, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    lines = _jsonl(os.path.join(base, "chat_history.jsonl"), rows)
    return {"artifact": os.path.join(base, "chat_history.jsonl"), "native_root": root,
            "relpath": os.path.relpath(base, root), "session_id": uid,
            "lines": lines + 1, "format": "grok-summary+chat-history"}


def _write_droid(ir, root, sid, cwd):
    uid = _uid(sid)
    schema = (ir.get("extra") or {}).get("schema")
    if schema == "cli_stream_json":
        path = os.path.join(root, "cli-stream", uid + ".jsonl")
        rows = []
        n = 0
        for ev in ir.get("events") or []:
            kind = ev.get("kind")
            ts = _iso(ev.get("ts") or ir.get("created_at_ms") or 0)
            if kind == "user_message":
                n += 1
                rows.append({"type": "message", "session_id": uid, "timestamp": ts,
                             "role": "user", "text": _text(ev)})
            elif kind == "assistant_message":
                for b in ev.get("blocks") or []:
                    if b.get("type") == "tool-call":
                        n += 1
                        rows.append({"type": "tool_call", "session_id": uid,
                                     "timestamp": ts, "toolCallId": b.get("id") or "",
                                     "toolName": b.get("name") or "tool",
                                     "parameters": _args(b.get("arguments"))})
                    elif b.get("type") == "text":
                        n += 1
                        rows.append({"type": "message", "session_id": uid, "timestamp": ts,
                                     "role": "assistant", "text": b.get("text") or ""})
            elif kind == "tool_result":
                n += 1
                rows.append({"type": "tool_result", "session_id": uid, "timestamp": ts,
                             "toolCallId": ev.get("call_id") or "",
                             "value": {"stdout": str(ev.get("content") or ""),
                                       "exitCode": 1 if ev.get("is_error") else 0}})
        lines = _jsonl(path, rows)
        return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
                "session_id": uid, "lines": lines, "format": "droid-cli-stream-json"}
    path = os.path.join(root, "sessions", uid + ".jsonl")
    rows = [{"type": "session_start", "id": uid, "title": ir.get("title") or "",
             "owner": "fixture", "version": 2, "cwd": cwd}]
    n = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind not in ("user_message", "assistant_message"):
            continue
        n += 1
        rows.append({"type": "message", "id": "m%d" % n,
                     "timestamp": _iso(ev.get("ts") or ir.get("created_at_ms") or 0),
                     "message": {"role": "user" if kind == "user_message" else "assistant",
                                 "content": ev.get("blocks") or []}})
    lines = _jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "droid-session-store-jsonl"}


def _write_constructed(source, ir, root, sid, cwd):
    uid = _uid(sid)
    path = os.path.join(root, "constructed", source, uid + ".db")
    batch4_construct.write_golden_db(source, ir, path)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": 0, "format": "constructed-sqlite-golden-db",
            "evidence_level": "FIXTURE-CONSTRUCTED"}


WRITERS = {
    "openclaw": _write_openclaw,
    "kimi": _write_kimi,
    "grok": _write_grok,
    "droid": _write_droid,
    "hermes": lambda ir, root, sid, cwd: _write_constructed("hermes", ir, root, sid, cwd),
    "devin": lambda ir, root, sid, cwd: _write_constructed("devin", ir, root, sid, cwd),
    "opencode": lambda ir, root, sid, cwd: _write_constructed("opencode", ir, root, sid, cwd),
}


def write(source, ir, root, sid, target_cwd=None):
    writer = WRITERS.get(source)
    if writer is None:
        raise ValueError("batch4 target %r is unsupported (antigravity writer is BLOCKED: "
                         "native .pb has no public schema)" % (source,))
    os.makedirs(root, exist_ok=True)
    return writer(ir, root, sid, _cwd(ir) if not target_cwd else target_cwd)
