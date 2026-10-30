"""ATIF v1.8 import/export.

Spec: Harbor RFC 0001 ``0001-trajectory-format.md`` (ATIF = Agent Trajectory Interchange
Format), schema_version ``"ATIF-v1.8"``.  Field summary (research doc §1.3)::

    root: {schema_version, session_id?, trajectory_id?, agent, steps[], notes?, final_metrics?,
           continued_trajectory_ref?, extra?, subagent_trajectories?}
    agent: {name, version, model_name?, tool_definitions?, extra?}
    step:  {step_id (1..N), source: system|user|agent, timestamp?, message,
            model_name?, reasoning_effort?, reasoning_content?, tool_calls[],
            observation {results:[{source_call_id, content}]}, metrics?, extra?,
            is_copied_context?, llm_call_count?}
    tool_call: {tool_call_id, function_name, arguments (JSON object), extra?}

ATIF is a trajectory/logging format, not a harness resume state, so the ATIF -> DSH path
(like the native readers) goes through the same IR + DSH v4 writer.
"""
import datetime as _dt
import glob
import json
import os

from . import __version__
from .common import iso_to_ms, now_ms
from .ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts, warn

SCHEMA_VERSION = "ATIF-v1.8"


def _iso(ms):
    if not isinstance(ms, (int, float)):
        return None
    dt = _dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=_dt.timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _message_text(message):
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        out = []
        for part in message:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    out.append(part.get("text") or "")
                elif part.get("type") == "image":
                    out.append("[image attachment not imported]")
            elif isinstance(part, str):
                out.append(part)
        return "\n".join(x for x in out if x)
    return ""


def _arguments_object(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except ValueError:
            return {"input": raw}
        return val if isinstance(val, dict) else {"value": val}
    return {}


# --------------------------------------------------------------------------- export
def to_atif(ir):
    """IR -> ATIF v1.8 document (dict)."""
    events = ir.get("events") or []
    steps = []
    i = 0
    while i < len(events):
        ev = events[i]
        kind = ev.get("kind")
        ts = ev.get("ts")
        if kind == "user_message":
            content = []
            for b in ev.get("blocks") or []:
                if b.get("type") == "text":
                    content.append(b.get("text") or "")
                elif b.get("type") == "image":
                    content.append(b.get("placeholder") or "[image attachment not imported]")
            step = {
                "step_id": len(steps) + 1,
                "source": "user",
                "message": "\n".join(x for x in content if x),
            }
            if ts:
                step["timestamp"] = _iso(ts)
            steps.append(step)
            i += 1
        elif kind == "system_message":
            step = {
                "step_id": len(steps) + 1,
                "source": "system",
                "message": ev.get("text") or "",
            }
            if ts:
                step["timestamp"] = _iso(ts)
            steps.append(step)
            i += 1
        elif kind == "assistant_message":
            blocks = ev.get("blocks") or []
            texts, reasonings, tool_calls = [], [], []
            for b in blocks:
                if b.get("type") == "text":
                    texts.append(b.get("text") or "")
                elif b.get("type") == "reasoning":
                    reasonings.append(b.get("text") or "")
                elif b.get("type") == "tool-call":
                    tool_calls.append(
                        {
                            "tool_call_id": b.get("id") or "",
                            "function_name": b.get("name") or "tool",
                            "arguments": _arguments_object(b.get("arguments")),
                        }
                    )
            step = {"step_id": len(steps) + 1, "source": "agent", "message": "\n".join(t for t in texts if t)}
            if ev.get("model") or ir.get("model"):
                step["model_name"] = ev.get("model") or ir.get("model")
            if reasonings:
                step["reasoning_content"] = "\n".join(r for r in reasonings if r)
            if tool_calls:
                step["tool_calls"] = tool_calls
            usage = normalize_usage(ev.get("usage"))
            if usage:
                metrics = {
                    "prompt_tokens": usage["inputTokens"],
                    "completion_tokens": usage["outputTokens"],
                    "cached_tokens": usage.get("cacheReadTokens", 0),
                }
                step["metrics"] = metrics
            if ts:
                step["timestamp"] = _iso(ts)
            # collect following tool results into this step's observation
            i += 1
            results = []
            call_ids = {tc["tool_call_id"]: tc["function_name"] for tc in tool_calls}
            while i < len(events) and events[i].get("kind") == "tool_result":
                r = events[i]
                results.append(
                    {
                        "source_call_id": r.get("call_id") or "",
                        "content": r.get("content") if isinstance(r.get("content"), str) else "",
                    }
                )
                if r.get("is_error"):
                    results[-1]["is_error"] = True
                cid = r.get("call_id")
                if cid and cid not in call_ids:
                    call_ids[cid] = r.get("name") or "tool"
                i += 1
            if results:
                step["observation"] = {"results": results}
            steps.append(step)
        elif kind == "compaction":
            step = {
                "step_id": len(steps) + 1,
                "source": "system",
                "message": ev.get("summary") or "",
                "extra": {"context_management": {"type": "compaction", "boundary": "replace"},
                          "asi_kind": "compaction", "asi_ts": ev.get("ts")},
            }
            if ts:
                step["timestamp"] = _iso(ts)
            steps.append(step)
            i += 1
        else:
            i += 1

    doc = {
        "schema_version": SCHEMA_VERSION,
        "trajectory_id": "%s:%s" % (ir.get("source") or "session", ir.get("source_session_id") or ""),
        "session_id": ir.get("source_session_id") or "",
        "agent": {
            "name": ir.get("source") or "unknown",
            "version": __version__,
            "model_name": ir.get("model") or "unknown",
        },
        "steps": steps,
        "extra": {
            "cwd": ir.get("cwd"),
            "title": ir.get("title"),
            "source": ir.get("source"),
            "source_path": ir.get("source_path"),
            "source_session_id": ir.get("source_session_id"),
            "asi_version": __version__,
        },
    }
    if ir.get("system_prompt"):
        doc["extra"]["system_prompt"] = ir["system_prompt"]
    if ir.get("warnings"):
        doc["notes"] = "; ".join(ir["warnings"])
    turn_aborts = [{"ts": ev.get("ts"), "reason": ev.get("reason")}
                   for ev in events if ev.get("kind") == "turn_abort"]
    if turn_aborts:
        doc["extra"]["asi_turn_aborts"] = turn_aborts
    return doc


# --------------------------------------------------------------------------- import
def _step_ts(step):
    return iso_to_ms(step.get("timestamp"))


def from_atif(doc, source_path=None, keep_system=False):
    """ATIF v1.8 document (dict) -> IR."""
    schema = doc.get("schema_version") or ""
    if not isinstance(schema, str) or not schema.startswith("ATIF"):
        raise ValueError("not an ATIF document: schema_version=%r" % (schema,))
    steps = doc.get("steps")
    if not isinstance(steps, list):
        raise ValueError("ATIF document has no steps[] list")
    agent = doc.get("agent") or {}
    extra = doc.get("extra") or {}
    sid = doc.get("trajectory_id") or doc.get("session_id") or os.path.basename(source_path or "atif")
    ir = new_ir("atif", str(sid), source_path or "")
    ir["cwd"] = extra.get("cwd")
    ir["title"] = extra.get("title") or ""
    ir["model"] = agent.get("model_name") or ""
    ir["provider"] = agent.get("name") or "atif"
    if keep_system and isinstance(extra.get("system_prompt"), str):
        ir["system_prompt"] = extra["system_prompt"]
    created = None
    for n, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        source = step.get("source")
        ts = _step_ts(step)
        if ts is not None:
            created = ts if created is None or ts < created else created
            touch_ts(ir, ts)
        message = _message_text(step.get("message"))
        if source == "system":
            if (step.get("extra") or {}).get("asi_kind") == "compaction":
                add_event(ir, "compaction", (step.get("extra") or {}).get("asi_ts") or ts,
                          summary=message, extra={"restored_from": "atif"})
            elif message:
                add_event(ir, "system_message", ts, text=message, origin="atif-system")
        elif source == "user":
            if message:
                add_event(ir, "user_message", ts, blocks=[text_block(message)])
        elif source == "agent":
            blocks = []
            reasoning = step.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                blocks.append({"type": "reasoning", "text": reasoning})
            if message:
                blocks.append(text_block(message))
            tool_calls = step.get("tool_calls") or []
            call_names = {}
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                cid = tc.get("tool_call_id") or "call_%d_%d" % (n, len(blocks))
                name = tc.get("function_name") or "tool"
                call_names[cid] = name
                args = tc.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                blocks.append({"type": "tool-call", "id": cid, "name": name, "arguments": args})
            if blocks:
                add_event(
                    ir,
                    "assistant_message",
                    ts,
                    blocks=blocks,
                    model=step.get("model_name") or ir.get("model"),
                    provider=ir.get("provider"),
                    usage=step.get("metrics"),
                )
            observation = step.get("observation") or {}
            results = observation.get("results") or []
            for r in results:
                if not isinstance(r, dict):
                    continue
                cid = r.get("source_call_id") or ""
                content = r.get("content")
                if isinstance(content, list):
                    content = _message_text(content)
                add_event(
                    ir,
                    "tool_result",
                    ts,
                    call_id=cid,
                    name=call_names.get(cid, "tool"),
                    content=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                    is_error=bool(r.get("is_error")),
                )
        else:
            warn(ir, "unknown ATIF step source %r at step_id=%r" % (source, step.get("step_id")))
    for rec in extra.get("asi_turn_aborts") or []:
        if isinstance(rec, dict):
            add_event(ir, "turn_abort", rec.get("ts"), reason=rec.get("reason") or "interrupted")
    ir["created_at_ms"] = created or now_ms()
    finalize(ir, fallback_title=ir.get("title") or None)
    return ir


# --------------------------------------------------------------------------- IO / listing
def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_sessions(root):
    """List *.json / *.atif.json files under root that look like ATIF documents."""
    root = os.path.expanduser(root or ".")
    files = sorted(
        set(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
        | set(glob.glob(os.path.join(root, "*.json")))
    )
    out = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(4096)
            if "ATIF" not in head:
                continue
            doc = load(path)
        except (OSError, ValueError):
            continue
        schema = doc.get("schema_version")
        if not isinstance(schema, str) or not schema.startswith("ATIF"):
            continue
        steps = doc.get("steps") or []
        extra = doc.get("extra") or {}
        created = None
        for step in steps:
            ts = _step_ts(step) if isinstance(step, dict) else None
            if ts is not None and (created is None or ts < created):
                created = ts
        out.append(
            {
                "source": "atif",
                "id": doc.get("trajectory_id") or doc.get("session_id") or os.path.basename(path),
                "title": (extra.get("title") or os.path.basename(path))[:120],
                "cwd": extra.get("cwd"),
                "created_at_ms": created,
                "updated_at_ms": int(os.path.getmtime(path) * 1000),
                "path": path,
                "lines": len(steps),
                "model": (doc.get("agent") or {}).get("model_name") or "",
                "schema_version": schema,
            }
        )
    out.sort(key=lambda r: r["updated_at_ms"] or 0, reverse=True)
    return out


def resolve_path(root, session):
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        hits = glob.glob(os.path.join(os.path.expanduser(root or "."), "**", session), recursive=True)
        if hits:
            return hits[0]
    out = list_sessions(root or ".")
    return out[0]["path"] if out else None


def validate(doc):
    errors, warnings = [], []
    schema = doc.get("schema_version")
    if not isinstance(schema, str) or not schema.startswith("ATIF-v"):
        errors.append("schema_version must be an ATIF-v* string")
    if not isinstance(doc.get("agent"), dict):
        errors.append("agent object required")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps[] must be a non-empty list")
        return errors, warnings
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append("steps[%d] is not an object" % i)
            continue
        if step.get("step_id") != i + 1:
            warnings.append("steps[%d].step_id != %d" % (i, i + 1))
        if step.get("source") not in ("system", "user", "agent"):
            errors.append("steps[%d].source invalid: %r" % (i, step.get("source")))
        if "message" not in step:
            errors.append("steps[%d] missing message" % i)
        for tc in step.get("tool_calls") or []:
            if not isinstance(tc, dict) or not tc.get("tool_call_id") or not tc.get("function_name"):
                errors.append("steps[%d] tool_calls entry missing tool_call_id/function_name" % i)
    return errors, warnings
