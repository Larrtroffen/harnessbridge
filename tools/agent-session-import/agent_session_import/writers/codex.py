"""Codex native writer (IR -> ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl).

Native layout / discovery: Codex scans ``$CODEX_HOME/sessions/**/rollout-*.jsonl``; the
SQLite state_5 index is derived (rebuilt from rollouts), not required for the file to be a
valid transcript.  We emit session_meta + per-turn turn_context/task_started +
response_item stream + task_complete, which is what Codex resume reads.
"""
import datetime as _dt
import json
import os
import re
import uuid

STORE = "sessions"
ERROR_MARKER = "\n[asi-import: tool error]"


def _codex_config():
    """(model, provider) configured in the local ~/.codex/config.toml (+ env override)."""
    model = os.environ.get("ASI_CODEX_FALLBACK_MODEL") or ""
    provider = ""
    cfg = os.path.expanduser("~/.codex/config.toml")
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'^model\s*=\s*"([^"]+)"', line)
                if m and not model:
                    model = m.group(1)
                m = re.match(r'^model_provider\s*=\s*"([^"]+)"', line)
                if m and not provider:
                    provider = m.group(1)
    except OSError:
        pass
    return model or "gpt-5", provider or "openai"


def _iso(ms):
    return _dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def _call_name_map(ir):
    names = {}
    for ev in ir.get("events") or []:
        if ev.get("kind") == "tool_result" and ev.get("call_id"):
            names[ev["call_id"]] = ev.get("name") or "tool"
    return names


def build_rollout(ir, codex_id, cwd):
    """IR -> list of rollout line dicts (ordinal ascending)."""
    created = int(ir.get("created_at_ms") or 0)
    lines = []
    ordinal = [0]

    def add(ts, rtype, payload):
        lines.append({"timestamp": _iso(ts), "ordinal": ordinal[0], "type": rtype, "payload": payload})
        ordinal[0] += 1
        return lines[-1]

    model, provider = _codex_config()
    ir_model = ir.get("model") or ""
    if ir_model and ir_model == model:
        pass
    add(
        created,
        "session_meta",
        {
            "session_id": codex_id,
            "id": codex_id,
            "timestamp": _iso(created),
            "cwd": cwd,
            "originator": "asi-import",
            "cli_version": "0.164.0",
            "source": "cli",
            "thread_source": "user",
            "model_provider": provider,
            "history_mode": "paginated",
            "base_instructions": {"text": ir.get("system_prompt") or ""},
        },
    )

    names = _call_name_map(ir)
    events = ir.get("events") or []
    i = 0
    turn_no = 0
    clock = [created]

    def tick(ts):
        t = int(ts) if isinstance(ts, (int, float)) else clock[0] + 1
        if t <= clock[0]:
            t = clock[0] + 1
        clock[0] = t
        return t

    def item_completed(ts, item, turn_id):
        add(ts, "event_msg", {
            "type": "item_completed", "thread_id": codex_id, "turn_id": turn_id,
            "item": item, "started_at_ms": int(ts), "completed_at_ms": int(ts),
        })

    pending_turn = None  # dict(turn_id, started, last_text)

    def open_turn(ts):
        nonlocal turn_no, pending_turn
        turn_no += 1
        turn_id = str(uuid.uuid4())
        pending_turn = {"turn_id": turn_id, "started": int(ts / 1000) if ts else clock[0] // 1000, "last_text": ""}
        add(ts, "turn_context", {
            "turn_id": turn_id, "root_turn_id": turn_id, "cwd": cwd,
            "approval_policy": "never", "sandbox_policy": {"type": "danger-full-access"},
            "model": model,
        })
        add(ts, "event_msg", {"type": "task_started", "turn_id": turn_id,
                              "root_turn_id": turn_id, "started_at": pending_turn["started"],
                              "model_context_window": 0})

    def close_turn(ts):
        nonlocal pending_turn
        if not pending_turn:
            return
        add(ts, "event_msg", {"type": "task_complete", "turn_id": pending_turn["turn_id"],
                              "last_agent_message": pending_turn["last_text"],
                              "started_at": pending_turn["started"],
                              "completed_at": int(ts / 1000), "duration_ms": 0})
        pending_turn = None

    while i < len(events):
        ev = events[i]
        kind = ev.get("kind")
        ts = tick(ev.get("ts"))
        if kind == "user_message":
            close_turn(clock[0] - 1)
            open_turn(ts)
            blocks = [{"type": "input_text", "text": b.get("text") or b.get("placeholder") or ""}
                      for b in ev.get("blocks") or []]
            msg_id = "msg_" + str(uuid.uuid4())
            add(ts, "response_item", {"type": "message", "role": "user", "content": blocks,
                                      "id": msg_id})
            item_completed(ts, {"type": "UserMessage", "id": str(uuid.uuid4()),
                                "client_id": str(uuid.uuid4()),
                                "content": [{"type": "text", "text": b.get("text") or "",
                                             "text_elements": []} for b in blocks]},
                           pending_turn["turn_id"] if pending_turn else str(uuid.uuid4()))
        elif kind == "system_message":
            add(ts, "response_item", {"type": "message", "role": "developer",
                                      "content": [{"type": "input_text", "text": ev.get("text") or ""}],
                                      "id": "msg_" + str(uuid.uuid4())})
        elif kind == "assistant_message":
            if not pending_turn:
                open_turn(ts)
            for b in ev.get("blocks") or []:
                bt = b.get("type")
                if bt == "reasoning":
                    rid = "rs_" + str(uuid.uuid4())
                    add(ts, "response_item", {
                        "type": "reasoning", "id": rid,
                        "summary": [{"type": "summary_text", "text": b.get("text") or ""}],
                    })
                    item_completed(ts, {"type": "Reasoning", "id": rid, "summary": [
                        {"type": "summary_text", "text": b.get("text") or ""}]},
                        pending_turn["turn_id"] if pending_turn else str(uuid.uuid4()))
                elif bt == "text":
                    pending_turn["last_text"] = b.get("text") or ""
                    aid = "msg_" + str(uuid.uuid4())
                    add(ts, "response_item", {
                        "type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": b.get("text") or ""}],
                        "id": aid,
                    })
                    item_completed(ts, {"type": "AgentMessage", "id": aid,
                                        "text": b.get("text") or "", "phase": "final_answer"},
                                   pending_turn["turn_id"] if pending_turn else str(uuid.uuid4()))
                elif bt == "tool-call":
                    cid = b.get("id") or "call_" + str(uuid.uuid4())
                    args = b.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    add(ts, "response_item", {
                        "type": "function_call", "name": b.get("name") or "tool",
                        "arguments": args, "call_id": cid, "status": "completed",
                        "id": "fc_" + str(uuid.uuid4()),
                    })
        elif kind == "tool_result":
            cid = ev.get("call_id") or ""
            name = names.get(cid) or ev.get("name") or "tool"
            out = ev.get("content")
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False) if out is not None else ""
            if ev.get("is_error") and ERROR_MARKER not in out:
                out += ERROR_MARKER
            add(ts, "response_item", {
                "type": "function_call_output", "call_id": cid, "name": name, "output": out,
                "id": "fco_" + str(uuid.uuid4()),
            })
        elif kind == "turn_abort":
            close_turn(ts)
        i += 1
    close_turn(clock[0])
    return lines


def write_into(ir, root, sid, target_cwd=None, compress=True):
    cwd = target_cwd or ir.get("cwd") or ""
    codex_id = sid[8:] if sid.startswith("session-") else sid
    lines = build_rollout(ir, codex_id, cwd)
    created = ir.get("created_at_ms") or 0
    dt = _dt.datetime.fromtimestamp(float(created) / 1000.0, tz=_dt.timezone.utc)
    day = os.path.join(root, STORE, dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d"))
    os.makedirs(day, exist_ok=True)
    fname = "rollout-%s-%s.jsonl" % (dt.strftime("%Y-%m-%dT%H-%M-%S"), codex_id)
    path = os.path.join(day, fname)
    with open(path, "w", encoding="utf-8") as f:
        for row in lines:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rel = os.path.relpath(path, root)
    return {"artifact": path, "native_root": root, "relpath": rel,
            "session_id": codex_id, "cwd": cwd, "lines": len(lines)}
