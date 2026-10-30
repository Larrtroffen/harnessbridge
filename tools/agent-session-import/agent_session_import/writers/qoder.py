"""Qoder native writer (IR -> ~/.qoder/projects/<slug>/<sid>.jsonl).

Qoder transcripts are Claude-Code-derived: one *block* per assistant row sharing
``message.id``, ``uuid``/``parentUuid`` tree, tool results as sibling user rows paired via
``tool_use_id``, and ``active-leaf`` records pointing at the latest committed leaf.
"""
import datetime as _dt
import json
import os
import re
import uuid

STORE = None  # root already is the projects dir
VERSION = "1.0.0-asi"


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


def build_rows(ir, sid, cwd):
    created = int(ir.get("created_at_ms") or 0)
    rows = []

    def base(rtype, ts, **extra):
        row = {
            "type": rtype,
            "timestamp": _iso(ts),
            "sessionId": sid,
            "cwd": cwd,
            "isSidechain": False,
            "userType": "external",
            "entrypoint": "cli",
            "version": VERSION,
            "gitBranch": "HEAD",
        }
        row.update(extra)
        return row

    def add(row):
        rows.append(row)

    def active_leaf(ts, leaf):
        add({"type": "active-leaf", "sessionId": sid, "leafUuid": leaf,
             "explicit": False, "timestamp": int(ts)})

    add({"type": "workspace-directories", "sessionId": sid, "directories": [cwd]})
    add({"type": "runtime-config", "sessionId": sid, "model": ir.get("model") or "imported",
         "reasoningEffort": None, "contextWindow": None, "generation": None,
         "timestamp": created})

    parent = None
    last_leaf = None
    call_row = {}  # tool_use id -> assistant row uuid (sourceToolAssistantUUID)
    first_prompt = None
    clock = [created]

    def tick(ts):
        t = int(ts) if isinstance(ts, (int, float)) else clock[0] + 1
        if t <= clock[0]:
            t = clock[0] + 1
        clock[0] = t
        return t

    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = tick(ev.get("ts"))
        if kind == "user_message":
            uid = str(uuid.uuid4())
            text = "\n".join(
                b.get("text") or b.get("placeholder") or ""
                for b in ev.get("blocks") or []
            )
            if first_prompt is None:
                first_prompt = text
            add(base("user", ts, uuid=uid, parentUuid=parent,
                     message={"role": "user", "content": [
                         {"type": "text", "text": b.get("text") or b.get("placeholder") or ""}
                         for b in ev.get("blocks") or []]},
                     permissionMode="yolo", origin={"kind": "human"},
                     promptId=str(uuid.uuid4()), humanInput={"text": text, "mode": "prompt"},
                     requestSetId=str(uuid.uuid4())))
            parent = uid
            last_leaf = uid
            active_leaf(ts, uid)
        elif kind == "system_message":
            uid = str(uuid.uuid4())
            add(base("user", ts, uuid=uid, parentUuid=parent,
                     message={"role": "user", "content": [{"type": "text", "text": ev.get("text") or ""}]},
                     isMeta=True, origin={"kind": "system"}))
            parent = uid
            last_leaf = uid
            active_leaf(ts, uid)
        elif kind == "assistant_message":
            mid = str(uuid.uuid4())
            blocks = ev.get("blocks") or []
            if not blocks:
                continue
            model = ev.get("model") or ir.get("model") or "imported"
            tool_blocks = [b for b in blocks if b.get("type") == "tool-call"]
            for bi, b in enumerate(blocks):
                uid = str(uuid.uuid4())
                bt = b.get("type")
                if bt == "reasoning":
                    content = {"type": "thinking", "thinking": b.get("text") or "", "signature": ""}
                elif bt == "text":
                    content = {"type": "text", "text": b.get("text") or "", "citations": None}
                elif bt == "tool-call":
                    cid = b.get("id") or "call_asi_%s" % uuid.uuid4().hex[:8]
                    content = {"type": "tool_use", "id": cid, "name": b.get("name") or "tool",
                               "input": _args_object(b.get("arguments"))}
                    call_row[cid] = uid
                else:
                    continue
                last = bi == len(blocks) - 1
                msg = {
                    "id": mid, "type": "message", "role": "assistant", "model": model,
                    "stop_reason": ("tool_use" if tool_blocks else "end_turn") if last else None,
                    "stop_sequence": None, "content": [content],
                }
                usage = ev.get("usage")
                if last and isinstance(usage, dict):
                    msg["usage"] = usage
                add(base("assistant", ts, uuid=uid, parentUuid=parent, message=msg))
                parent = uid
            last_leaf = parent
            active_leaf(ts, parent)
        elif kind == "tool_result":
            cid = ev.get("call_id") or ""
            result_uuid = str(uuid.uuid4())
            src_uuid = call_row.get(cid)
            content = ev.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False) if content is not None else ""
            row = base("user", ts, uuid=result_uuid, parentUuid=src_uuid or parent,
                       message={"role": "user", "content": [{
                           "type": "tool_result", "tool_use_id": cid,
                           "content": content, "is_error": bool(ev.get("is_error")),
                       }]},
                       promptId=str(uuid.uuid4()))
            if src_uuid:
                row["sourceToolAssistantUUID"] = src_uuid
            row["toolUseResult"] = {
                "kind": "tool-status" if ev.get("is_error") else "completed",
                "isImage": False, "interrupted": False,
            }
            add(row)
            parent = result_uuid
            last_leaf = result_uuid
            active_leaf(ts, result_uuid)

    if last_leaf:
        add({"type": "last-prompt", "sessionId": sid, "lastPrompt": first_prompt or ir.get("title") or ""})
    return rows


def write_into(ir, root, sid, target_cwd=None, compress=True):
    cwd = target_cwd or ir.get("cwd") or ""
    sid = sid[8:] if sid.startswith("session-") else sid
    slug = slugify(cwd)
    project_dir = os.path.join(root, slug) if STORE is None else os.path.join(root, STORE, slug)
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, sid + ".jsonl")
    rows = build_rows(ir, sid, cwd)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rel = os.path.relpath(path, root)
    return {"artifact": path, "native_root": root, "relpath": rel,
            "session_id": sid, "cwd": cwd, "slug": slug, "lines": len(rows)}
