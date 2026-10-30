"""OMP (oh-my-pi) native writer (IR -> <agent-dir>/sessions/<slug>/<ISO>_<sid>.jsonl).

OMP transcripts are a *tree* event stream: ``title`` line first, ``session`` line second,
then entries with ``id``/``parentId``.  Codex-style discovery is directory-based (the
history.db/agent.db tables are indexes, not the source of truth), so a well-formed JSONL
under sessions/<slug>/ is discoverable by ``omp resume``.
"""
import datetime as _dt
import json
import os
import re

STORE = None  # root already is the sessions dir


def _iso(ms):
    return _dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def _slug(cwd, home):
    cwd = cwd or ""
    if home and cwd.startswith(home):
        rel = cwd[len(home):].lstrip("/")
    else:
        rel = re.sub(r"^/+", "", cwd)
    rel = rel.replace("/", "-")
    return "-" + rel if rel else "-"


def _omp_models():
    """Models known to the local ~/.omp/agent/config.yml (+ ASI_OMP_FALLBACK_MODEL)."""
    configured = set()
    default = os.environ.get("ASI_OMP_FALLBACK_MODEL") or ""
    cfg = os.path.expanduser("~/.omp/agent/config.yml")
    in_roles = False
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                if line.startswith("modelRoles:"):
                    in_roles = True
                    continue
                if in_roles and not line.startswith((" ", "\t")):
                    break
                if in_roles:
                    m = re.match(r"\s+([A-Za-z0-9_-]+):\s*([A-Za-z0-9_.\-/]+)", line)
                    if m:
                        configured.add(m.group(2))
                        if m.group(1) == "default" and not default:
                            default = m.group(2)
    except OSError:
        pass
    if default:
        configured.add(default)
    if not default:
        default = "magpie/deepseek/deepseek-flash"
    return configured, default


def pick_model(raw):
    """Keep the source model when the local OMP profile knows it, else use its default role."""
    configured, default = _omp_models()
    raw = raw or ""
    if raw and raw in configured:
        return raw, raw
    return default, raw


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


def _hex_id(used):
    while True:
        eid = os.urandom(4).hex()
        if eid not in used:
            used.add(eid)
            return eid


def build_rows(ir, sid, cwd):
    created = int(ir.get("created_at_ms") or 0)
    title = ir.get("title") or "Imported session"
    model, original_model = pick_model(ir.get("model"))
    provider = ir.get("provider") or (model.split("/")[0] if "/" in model else "imported")
    rows = [
        {"type": "title", "v": 1, "title": title, "source": "user",
         "updatedAt": _iso(created), "pad": " " * 8},
        {"type": "session", "version": 3, "id": sid, "timestamp": _iso(created),
         "cwd": cwd, "title": title, "titleSource": "auto"},
    ]
    used = set()
    parent = None
    clock = [created]
    mid = [_hex_id(used)]

    def tick(ts):
        t = int(ts) if isinstance(ts, (int, float)) else clock[0] + 1
        if t <= clock[0]:
            t = clock[0] + 1
        clock[0] = t
        return t

    def add_entry(eid, parent_id, ts, entry):
        entry.update({"id": eid, "parentId": parent_id, "timestamp": _iso(ts)})
        rows.append(entry)
        return eid

    model_entry = {
        "type": "model_change", "runtime": {"version": "18.12.6"}, "model": model,
        "resolvedModelIsFallback": False,
    }
    if original_model and original_model != model:
        model_entry["originalModel"] = original_model
    add_entry(mid[0], None, created, model_entry)
    parent = mid[0]

    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = tick(ev.get("ts"))
        eid = _hex_id(used)
        if kind == "user_message":
            content = [{"type": "text", "text": b.get("text") or b.get("placeholder") or ""}
                       for b in ev.get("blocks") or []]
            add_entry(eid, parent, ts, {"type": "message", "message": {
                "role": "user", "content": content, "attribution": "user", "timestamp": int(ts)}})
            parent = eid
        elif kind == "system_message":
            add_entry(eid, parent, ts, {"type": "message", "message": {
                "role": "developer",
                "content": [{"type": "text", "text": ev.get("text") or ""}],
                "timestamp": int(ts)}})
            parent = eid
        elif kind == "assistant_message":
            blocks = ev.get("blocks") or []
            content = []
            has_tool = False
            for b in blocks:
                bt = b.get("type")
                if bt == "reasoning":
                    content.append({"type": "thinking", "thinking": b.get("text") or ""})
                elif bt == "text":
                    content.append({"type": "text", "text": b.get("text") or ""})
                elif bt == "tool-call":
                    has_tool = True
                    content.append({"type": "toolCall", "id": b.get("id") or "call_asi_" + eid,
                                    "name": b.get("name") or "tool",
                                    "arguments": _args_object(b.get("arguments"))})
            if not content:
                continue
            usage = ev.get("usage")
            msg = {
                "role": "assistant", "content": content,
                "api": "openai-completions", "provider": ev.get("provider") or provider,
                "model": ev.get("model") or model,
                "stopReason": "toolUse" if has_tool else "stop",
                "timestamp": int(ts),
            }
            if isinstance(usage, dict):
                msg["usage"] = usage
            add_entry(eid, parent, ts, {"type": "message", "message": msg})
            parent = eid
        elif kind == "tool_result":
            cid = ev.get("call_id") or ""
            content_text = ev.get("content")
            if not isinstance(content_text, str):
                content_text = json.dumps(content_text, ensure_ascii=False) if content_text is not None else ""
            add_entry(eid, parent, ts, {"type": "message", "message": {
                "role": "toolResult", "toolCallId": cid, "toolName": ev.get("name") or "tool",
                "content": [{"type": "text", "text": content_text}],
                "details": {"cwd": cwd}, "isError": bool(ev.get("is_error")),
                "useless": False, "timestamp": int(ts)}})
            parent = eid
    return rows


def write_into(ir, root, sid, target_cwd=None, compress=True):
    cwd = target_cwd or ir.get("cwd") or ""
    sid = sid[8:] if sid.startswith("session-") else sid
    slug = _slug(cwd, os.path.expanduser("~"))
    project_dir = os.path.join(root, slug) if STORE is None else os.path.join(root, STORE, slug)
    os.makedirs(project_dir, exist_ok=True)
    created = int(ir.get("created_at_ms") or 0)
    dt = _dt.datetime.fromtimestamp(float(created) / 1000.0, tz=_dt.timezone.utc)
    fname = "%s_%s.jsonl" % (dt.strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z", sid)
    path = os.path.join(project_dir, fname)
    rows = build_rows(ir, sid, cwd)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rel = os.path.relpath(path, root)
    return {"artifact": path, "native_root": root, "relpath": rel,
            "session_id": sid, "cwd": cwd, "slug": slug, "lines": len(rows)}
