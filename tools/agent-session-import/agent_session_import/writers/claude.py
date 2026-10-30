"""Claude Code native writer (IR -> <config-dir>/projects/<slug>/<uuid>.jsonl).

Rows mirror Claude Code 2.1.x transcripts: user rows (human prompt / tool_result), one
assistant row per logical message with a full content array (thinking/text/tool_use),
``last-prompt`` rows carrying the committed ``leafUuid`` for branch selection, and a
``custom-title`` row for the title.  Root passed to ``write_into`` is the projects dir.
"""
import datetime as _dt
import json
import re

STORE = None  # root already is the projects dir
VERSION = "2.1.308"


def slugify(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


def _iso(ms):
    return _dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def _args_object(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except ValueError:
            return {"input": raw}
        return val if isinstance(val, dict) else {"value": val}
    return {}


def _usage(u):
    if not isinstance(u, dict):
        return None
    mapping = {
        "input_tokens": u.get("inputTokens", u.get("input_tokens", u.get("input"))),
        "output_tokens": u.get("outputTokens", u.get("output_tokens", u.get("output"))),
        "cache_read_input_tokens": u.get("cacheReadTokens", u.get("cache_read_input_tokens", 0)),
        "cache_creation_input_tokens": u.get("cacheWriteTokens", u.get("cache_write_input_tokens", 0)),
    }
    return {k: int(v) for k, v in mapping.items() if isinstance(v, (int, float))}


def build_rows(ir, sid, cwd):
    created = int(ir.get("created_at_ms") or 0)
    rows = []
    prompt = None
    clock = [created]
    parent = None
    last_leaf = None
    call_row = {}

    def tick(ts):
        t = int(ts) if isinstance(ts, (int, float)) else clock[0] + 1
        if t <= clock[0]:
            t = clock[0] + 1
        clock[0] = t
        return t

    def base(rtype, ts, **extra):
        row = {
            "parentUuid": None,
            "isSidechain": False,
            "type": rtype,
            "uuid": None,
            "timestamp": _iso(ts),
            "userType": "external",
            "entrypoint": "cli",
            "cwd": cwd,
            "sessionId": sid,
            "version": VERSION,
            "gitBranch": "HEAD",
        }
        row.update(extra)
        return row

    def last_prompt(ts):
        if last_leaf:
            rows.append({"type": "last-prompt", "lastPrompt": prompt or ir.get("title") or "",
                         "leafUuid": last_leaf, "sessionId": sid})

    if ir.get("title"):
        rows.append({"type": "custom-title", "customTitle": ir["title"], "sessionId": sid})

    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = tick(ev.get("ts"))
        if kind == "user_message":
            import uuid as _uuid

            uid = str(_uuid.uuid4())
            text = "\n".join(b.get("text") or b.get("placeholder") or "" for b in ev.get("blocks") or [])
            if prompt is None:
                prompt = text
            row = base("user", ts, uuid=uid, parentUuid=parent, promptId=str(_uuid.uuid4()),
                       message={"role": "user", "content": [
                           {"type": "text", "text": b.get("text") or b.get("placeholder") or ""}
                           for b in ev.get("blocks") or []]})
            rows.append(row)
            parent = uid
            last_leaf = uid
            last_prompt(ts)
        elif kind == "system_message":
            import uuid as _uuid

            uid = str(_uuid.uuid4())
            rows.append(base("user", ts, uuid=uid, parentUuid=parent, isMeta=True,
                             message={"role": "user",
                                      "content": [{"type": "text", "text": ev.get("text") or ""}]}))
            parent = uid
            last_leaf = uid
            last_prompt(ts)
        elif kind == "assistant_message":
            import uuid as _uuid

            blocks = ev.get("blocks") or []
            if not blocks:
                continue
            uid = str(_uuid.uuid4())
            mid = "msg_" + _uuid.uuid4().hex
            content = []
            has_tool = False
            for b in blocks:
                bt = b.get("type")
                if bt == "reasoning":
                    content.append({"type": "thinking", "thinking": b.get("text") or "", "signature": ""})
                elif bt == "text":
                    content.append({"type": "text", "text": b.get("text") or "", "citations": None})
                elif bt == "tool-call":
                    has_tool = True
                    cid = b.get("id") or "toolu_" + _uuid.uuid4().hex[:16]
                    content.append({"type": "tool_use", "id": cid,
                                    "name": b.get("name") or "tool",
                                    "input": _args_object(b.get("arguments"))})
                    call_row[cid] = uid
            if not content:
                continue
            message = {"content": content, "id": mid,
                       "model": ev.get("model") or ir.get("model") or "unknown",
                       "role": "assistant", "stop_details": None,
                       "stop_reason": "tool_use" if has_tool else "end_turn",
                       "stop_sequence": None, "type": "message"}
            usage = _usage(ev.get("usage"))
            if usage:
                message["usage"] = usage
            rows.append(base("assistant", ts, uuid=uid, parentUuid=parent, message=message))
            parent = uid
            last_leaf = uid
            last_prompt(ts)
        elif kind == "tool_result":
            import uuid as _uuid

            cid = ev.get("call_id") or ""
            uid = str(_uuid.uuid4())
            src = call_row.get(cid)
            content = ev.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False) if content is not None else ""
            row = base("user", ts, uuid=uid, parentUuid=src or parent,
                       promptId=str(_uuid.uuid4()),
                       message={"role": "user", "content": [{
                           "type": "tool_result", "tool_use_id": cid,
                           "content": content, "is_error": bool(ev.get("is_error"))}]})
            if src:
                row["sourceToolAssistantUUID"] = src
            row["toolUseResult"] = {"interrupted": False,
                                    "isImage": False, "noOutputExpected": False}
            rows.append(row)
            parent = uid
            last_leaf = uid
            last_prompt(ts)
    return rows


def write_into(ir, root, sid, target_cwd=None, compress=True):
    cwd = target_cwd or ir.get("cwd") or ""
    uuid_sid = sid[8:] if sid.startswith("session-") else sid
    slug = slugify(cwd)
    project_dir = os.path.join(root, slug)
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, uuid_sid + ".jsonl")
    rows = build_rows(ir, uuid_sid, cwd)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rel = os.path.relpath(path, root)
    return {"artifact": path, "native_root": root, "relpath": rel,
            "session_id": uuid_sid, "cwd": cwd, "slug": slug, "lines": len(rows)}


import os  # noqa: E402  (kept at bottom to mirror the module's small footprint)
