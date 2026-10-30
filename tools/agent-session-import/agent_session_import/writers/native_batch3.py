"""Batch-3 native-format writers (FIXTURE/format-level evidence, staging only).

Each writer emits a *minimal* native-shaped artifact; native CLI load is NOT claimed for
batch 3 (fixtures are synthetic).  ``write(source, ir, root, sid)`` returns the artifact path.
"""
import datetime as _dt
import hashlib
import json
import os
import re
import uuid as _uuid

SOURCES = ("copilot", "gemini", "aider", "cursor", "qwen", "pi")


def _iso(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        ms = 0
    return _dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _uuid_sid(sid):
    if sid.startswith("session-"):
        return sid[8:]
    return sid


def _args(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except ValueError:
            return {"_raw": raw}
        return val if isinstance(val, dict) else {"_raw": raw}
    return {}


def _text(ev):
    return "\n".join(b.get("text") or b.get("placeholder") or "" for b in ev.get("blocks") or [])


def _blocks(ev):
    return ev.get("blocks") or []


def _calls(ev):
    return [b for b in _blocks(ev) if b.get("type") == "tool-call"]


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def _slug(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


# --------------------------------------------------------------------------- copilot
def _write_copilot(ir, root, sid, cwd):
    uid = _uuid_sid(sid)
    sdir = os.path.join(root, "session-state", uid)
    path = os.path.join(sdir, "events.jsonl")
    rows = []
    created = ir.get("created_at_ms") or 0
    model = ir.get("model") or ""

    def ev(etype, data, ephemeral=False):
        rows.append({"type": etype, "data": data, "id": "evt-%03d" % len(rows),
                     "timestamp": _iso(created + len(rows)), "parentId": None,
                     **({"ephemeral": True} if ephemeral else {})})

    ev("session.start", {"sessionId": uid, "version": "fixture",
                         "startTime": _iso(created), "selectedModel": model,
                         "context": {"cwd": cwd}})
    for e in ir.get("events") or []:
        kind = e.get("kind")
        if kind == "user_message":
            ev("user.message", {"content": _text(e), "transformedContent": _text(e),
                                "attachments": []})
        elif kind == "assistant_message":
            reqs = []
            for b in _calls(e):
                reqs.append({"toolCallId": b["id"], "name": b["name"],
                             "arguments": _args(b.get("arguments")), "type": "function"})
            reasoning = "\n".join(b.get("text") or "" for b in _blocks(e)
                                  if b.get("type") == "reasoning")
            content = "\n".join(b.get("text") or "" for b in _blocks(e) if b.get("type") == "text")
            assistant_id = ev("assistant.message", {
                "messageId": "msg-" + str(len(rows)), "content": content,
                "toolRequests": reqs, "reasoningText": reasoning, "outputTokens": 0})
            for b in _calls(e):
                ev("tool.execution_start", {"toolCallId": b["id"], "toolName": b["name"],
                                            "arguments": _args(b.get("arguments"))})
        elif kind == "tool_result":
            ev("tool.execution_complete", {
                "toolCallId": e.get("call_id") or "",
                "success": not e.get("is_error"),
                "result": {"content": e.get("content") or ""}})
        elif kind == "turn_abort":
            ev("abort", {"reason": e.get("reason") or "aborted"})
    ev("result", {"sessionId": uid, "exitCode": 0,
                  "usage": {"premiumRequests": 0, "totalApiDurationMs": 0,
                            "sessionDurationMs": 0}})
    lines = _write_jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "copilot-events-jsonl"}


# --------------------------------------------------------------------------- gemini
def _write_gemini(ir, root, sid, cwd):
    project_hash = hashlib.sha256((cwd or "").encode("utf-8")).hexdigest()
    created = ir.get("created_at_ms") or 0
    short = _uuid_sid(sid)[:6]
    stamp = _dt.datetime.fromtimestamp(created / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H-%M-%S") if created else "1970-01-01T00-00-00"
    path = os.path.join(root, "tmp", project_hash, "chats",
                        "session-%s-%s.json" % (stamp, short))
    messages = []
    for e in ir.get("events") or []:
        kind = e.get("kind")
        if kind == "user_message":
            messages.append({"id": e.get("source_id") or "m%d" % len(messages),
                             "timestamp": _iso(e.get("ts") or created),
                             "type": "user", "content": _text(e),
                             "displayContent": _text(e)})
        elif kind == "assistant_message":
            thoughts = [{"description": b.get("text") or ""} for b in _blocks(e)
                        if b.get("type") == "reasoning"]
            usage = e.get("usage") or {}
            tokens = {"input": usage.get("inputTokens", 0),
                      "output": usage.get("outputTokens", 0),
                      "total": usage.get("totalTokens", 0),
                      "thoughts": usage.get("reasoningTokens", 0), "tool": 0, "cached": 0}
            msg = {"id": e.get("source_id") or "m%d" % len(messages),
                   "timestamp": _iso(e.get("ts") or created),
                   "type": "gemini", "model": e.get("model") or ir.get("model") or "",
                   "tokens": tokens, "thoughts": thoughts,
                   "content": "\n".join(b.get("text") or "" for b in _blocks(e)
                                        if b.get("type") == "text")}
            tool_calls = []
            for b in _calls(e):
                tool_calls.append({"id": b["id"], "name": b["name"],
                                   "args": _args(b.get("arguments"))})
            if tool_calls:
                msg["toolCalls"] = tool_calls
            messages.append(msg)
        elif kind == "tool_result":
            for msg in reversed(messages):
                for tc in msg.get("toolCalls") or []:
                    if tc.get("id") == e.get("call_id"):
                        tc["result"] = e.get("content") or ""
                        break
    doc = {"kind": "chat", "startTime": _iso(created),
           "lastUpdated": _iso(ir.get("updated_at_ms") or created),
           "projectHash": project_hash, "sessionId": _uuid_sid(sid),
           "messages": messages}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": _uuid_sid(sid), "lines": len(messages),
            "format": "gemini-chat-json"}


# --------------------------------------------------------------------------- aider
def _write_aider(ir, root, sid, cwd):
    digest = hashlib.sha256((cwd or _uuid_sid(sid)).encode("utf-8")).hexdigest()[:8]
    path = os.path.join(root, "history", digest + ".md")
    parts = []
    user_text = None
    for e in ir.get("events") or []:
        kind = e.get("kind")
        if kind == "user_message":
            user_text = _text(e).strip().splitlines()[0] if _text(e).strip() else ""
        elif kind == "assistant_message" and user_text is not None:
            reply = "\n".join(b.get("text") or "" for b in _blocks(e)
                              if b.get("type") == "text").strip()
            parts.append("#### %s\n%s\n\n" % (user_text, reply))
            user_text = None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": _uuid_sid(sid), "lines": len(parts), "format": "aider-markdown-history"}


# --------------------------------------------------------------------------- cursor
def _write_cursor(ir, root, sid, cwd):
    uid = _uuid_sid(sid)
    slug = _slug(cwd)
    path = os.path.join(root, "projects", slug, "agent-transcripts", uid, uid + ".jsonl")
    rows = []
    for e in ir.get("events") or []:
        kind = e.get("kind")
        if kind == "user_message":
            rows.append({"role": "user",
                         "message": {"content": [{"type": "text", "text": _text(e)}]}})
        elif kind == "assistant_message":
            content = []
            for b in _blocks(e):
                if b.get("type") == "text":
                    content.append({"type": "text", "text": b.get("text") or ""})
                elif b.get("type") == "tool-call":
                    content.append({"type": "tool_use", "name": b.get("name") or "tool",
                                    "input": _args(b.get("arguments"))})
            if content:
                rows.append({"role": "assistant", "message": {"content": content}})
            rows.append({"type": "turn_ended", "status": "success"})
        elif kind == "turn_abort":
            rows.append({"type": "turn_ended", "status": "error",
                         "error": str(e.get("reason") or "error")})
    lines = _write_jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "cursor-transcript-jsonl"}


# --------------------------------------------------------------------------- qwen
def _qwen_blocks(ev):
    parts = []
    for b in _blocks(ev):
        bt = b.get("type")
        if bt == "text":
            parts.append({"text": b.get("text") or ""})
        elif bt == "reasoning":
            parts.append({"thinking": b.get("text") or ""})
        elif bt == "tool-call":
            parts.append({"functionCall": {"id": b["id"], "name": b.get("name") or "tool",
                                           "args": _args(b.get("arguments"))}})
    return parts


def _write_qwen(ir, root, sid, cwd):
    uid = _uuid_sid(sid)
    path = os.path.join(root, "projects", _slug(cwd), "chats", uid + ".jsonl")
    rows = []
    parent = None
    version = (ir.get("extra") or {}).get("harness_version") or "fixture"
    for e in ir.get("events") or []:
        kind = e.get("kind")
        row_id = str(_uuid.uuid4())
        ts = _iso(e.get("ts") or ir.get("created_at_ms") or 0)
        if kind == "user_message":
            rows.append({"uuid": row_id, "parentUuid": parent, "sessionId": uid,
                         "timestamp": ts, "type": "user", "cwd": cwd, "version": version,
                         "message": {"role": "user", "parts": _qwen_blocks(e)}})
            parent = row_id
        elif kind == "assistant_message":
            rows.append({"uuid": row_id, "parentUuid": parent, "sessionId": uid,
                         "timestamp": ts, "type": "assistant", "cwd": cwd,
                         "version": version,
                         "message": {"role": "assistant", "parts": _qwen_blocks(e)}})
            parent = row_id
        elif kind == "tool_result":
            rows.append({"uuid": row_id, "parentUuid": parent, "sessionId": uid,
                         "timestamp": ts, "type": "tool_result",
                         "toolUseId": e.get("call_id") or "", "cwd": cwd,
                         "content": e.get("content") or ""})
            parent = row_id
    lines = _write_jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "qwen-claude-derived-jsonl"}


# --------------------------------------------------------------------------- pi
def _write_pi(ir, root, sid, cwd):
    uid = _uuid_sid(sid)
    created = ir.get("created_at_ms") or 0
    stamp = _dt.datetime.fromtimestamp(created / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z" if created else "1970-01-01T00-00-00-000Z"
    path = os.path.join(root, "sessions", _slug(cwd), "%s_%s.jsonl" % (stamp, uid))
    rows = [{"type": "session", "version": 3, "id": uid, "timestamp": _iso(created),
             "cwd": cwd}]
    parent = None
    counter = [0]

    def hid():
        counter[0] += 1
        return "%08x" % (0x10000000 + counter[0])

    mid = hid()
    rows.append({"type": "model_change", "id": mid, "parentId": None,
                 "timestamp": _iso(created), "modelId": ir.get("model") or "fixture-model"})
    parent = mid
    for e in ir.get("events") or []:
        kind = e.get("kind")
        ts = _iso(e.get("ts") or ir.get("created_at_ms") or 0)
        eid = hid()
        if kind == "user_message":
            rows.append({"type": "message", "id": eid, "parentId": parent, "timestamp": ts,
                         "message": {"role": "user", "content": _blocks(e)}})
        elif kind == "assistant_message":
            content = []
            for b in _blocks(e):
                if b.get("type") == "reasoning":
                    content.append({"type": "thinking", "thinking": b.get("text") or ""})
                elif b.get("type") == "text":
                    content.append({"type": "text", "text": b.get("text") or ""})
                elif b.get("type") == "tool-call":
                    content.append({"type": "toolCall", "id": b["id"],
                                    "name": b.get("name") or "tool",
                                    "arguments": _args(b.get("arguments"))})
            rows.append({"type": "message", "id": eid, "parentId": parent, "timestamp": ts,
                         "message": {"role": "assistant", "content": content,
                                     "provider": e.get("provider") or "pi",
                                     "model": e.get("model") or ir.get("model") or "",
                                     "usage": e.get("usage") or {}}})
        elif kind == "tool_result":
            rows.append({"type": "message", "id": eid, "parentId": parent, "timestamp": ts,
                         "message": {"role": "toolResult",
                                     "toolCallId": e.get("call_id") or "",
                                     "toolName": e.get("name") or "tool",
                                     "content": [{"type": "text", "text": e.get("content") or ""}],
                                     "isError": bool(e.get("is_error"))}})
        elif kind == "compaction":
            rows.append({"type": "compaction", "id": eid, "parentId": parent, "timestamp": ts,
                         "summary": e.get("summary") or ""})
        else:
            continue
        parent = eid
    lines = _write_jsonl(path, rows)
    return {"artifact": path, "native_root": root, "relpath": os.path.relpath(path, root),
            "session_id": uid, "lines": lines, "format": "pi-tree-jsonl"}


WRITERS = {
    "copilot": _write_copilot,
    "gemini": _write_gemini,
    "aider": _write_aider,
    "cursor": _write_cursor,
    "qwen": _write_qwen,
    "pi": _write_pi,
}


def write(source, ir, root, sid, target_cwd=None):
    cwd = target_cwd or ir.get("cwd") or os.getcwd()
    os.makedirs(root, exist_ok=True)
    writer = WRITERS.get(source)
    if writer is None:
        raise ValueError("no batch3 writer for %r" % (source,))
    return writer(ir, root, sid, cwd)
