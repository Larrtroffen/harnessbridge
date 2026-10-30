"""Unified intermediate representation (IR) shared by all readers and writers.

IR JSON shape::

    {
      "ir_version": 1,
      "source": "codex" | "qoder" | "omp" | "atif",
      "source_session_id": str,
      "source_path": str,
      "cwd": str,
      "created_at_ms": int,
      "updated_at_ms": int,
      "title": str,
      "model": str,
      "provider": str,
      "system_prompt": str (optional, only with --keep-system),
      "warnings": [str],
      "stats": {...},
      "events": [ EV, ... ]
    }

Event kinds (ordered, linear timeline):

    user_message      {ts, blocks: [text|image], source_id?}
    assistant_message {ts, blocks: [text|reasoning|tool-call], model, provider, usage?, source_id?}
    tool_result       {ts, call_id, name, content, is_error}
    system_message    {ts, text, origin}
    compaction        {ts, summary, extra}
    turn_abort        {ts, reason}
"""
import json

from .common import iso_to_ms, now_ms, text_placeholder_for_image

IR_VERSION = 1
MISSING_RESULT_TEXT = "[tool result missing in source session]"


def new_ir(source, source_session_id, source_path, cwd=None, created_at_ms=None):
    return {
        "ir_version": IR_VERSION,
        "source": source,
        "source_session_id": source_session_id,
        "source_path": source_path,
        "cwd": cwd,
        "created_at_ms": created_at_ms or now_ms(),
        "updated_at_ms": created_at_ms or now_ms(),
        "title": "",
        "model": "",
        "provider": "",
        "warnings": [],
        "stats": {},
        "events": [],
    }


def add_event(ir, kind, ts, **fields):
    ev = {"kind": kind}
    if ts is not None:
        ev["ts"] = int(ts)
    ev.update({k: v for k, v in fields.items() if v is not None})
    ir["events"].append(ev)
    return ev


def warn(ir, message):
    if message not in ir["warnings"]:
        ir["warnings"].append(message)


def touch_ts(ir, ts):
    if ts is None:
        return
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return
    if ts < 0:
        return
    if not ir.get("created_at_ms"):
        ir["created_at_ms"] = ts
    if not ir.get("updated_at_ms") or ts > ir["updated_at_ms"]:
        ir["updated_at_ms"] = ts


def text_block(text):
    return {"type": "text", "text": text if isinstance(text, str) else str(text)}


def image_block(src=None):
    return {"type": "image", "placeholder": text_placeholder_for_image(src)}


def blocks_text(blocks):
    """Join the text of IR blocks (used for title derivation)."""
    out = []
    for b in blocks or []:
        if b.get("type") == "text":
            out.append(b.get("text") or "")
    return "\n".join(x for x in out if x)


def normalize_usage(raw):
    """Map source usage dicts (codex/qoder/omp/atif) to DSH assistant/message usage shape."""
    if not isinstance(raw, dict) or not raw:
        return None

    def pick(*keys):
        for k in keys:
            if k in raw and raw[k] is not None:
                try:
                    return int(raw[k])
                except (TypeError, ValueError):
                    continue
        return None

    inp = pick("inputTokens", "input_tokens", "input", "prompt_tokens")
    out = pick("outputTokens", "output_tokens", "output", "completion_tokens")
    if inp is None or out is None:
        return None
    cache_read = pick("cacheReadTokens", "cache_read_input_tokens", "cacheRead", "cached_tokens")
    cache_write = pick("cacheWriteTokens", "cache_write_input_tokens", "cacheWrite")
    total = pick("totalTokens", "total_tokens", "total")
    res = {
        "inputTokens": inp,
        "outputTokens": out,
        "cacheReadTokens": cache_read or 0,
        "cacheWriteTokens": cache_write or 0,
        "totalTokens": total if total is not None else inp + out + (cache_read or 0) + (cache_write or 0),
    }
    reasoning = pick("reasoningTokens", "reasoning_tokens", "reasoning_output_tokens")
    if reasoning is not None:
        res["reasoningTokens"] = reasoning
    return res


def finalize(ir, fallback_title=None, model=None, provider=None):
    """Fill title/model/provider/stats defaults. Called by every reader before return."""
    if model and not ir.get("model"):
        ir["model"] = model
    if provider and not ir.get("provider"):
        ir["provider"] = provider
    if not ir.get("title"):
        title = ""
        for ev in ir["events"]:
            if ev.get("kind") == "user_message":
                title = blocks_text(ev.get("blocks")).strip()
                if title:
                    break
        if not title and fallback_title:
            title = fallback_title
        if not title:
            title = "%s imported session %s" % (ir.get("source"), (ir.get("source_session_id") or "")[:8])
        ir["title"] = title.splitlines()[0][:120]
    events = ir["events"]
    # backfill a placeholder result for every tool call that has none, inserted at the end
    # of that assistant step (so every writer/reader sees the same linear order).
    call_names = {}
    for ev in events:
        if ev.get("kind") == "assistant_message":
            for b in ev.get("blocks") or []:
                if b.get("type") == "tool-call" and b.get("id"):
                    call_names.setdefault(b["id"], b.get("name") or "tool")
    have = {ev.get("call_id") for ev in events if ev.get("kind") == "tool_result"}
    missing = {cid for cid in call_names if cid not in have}
    if missing:
        out = []
        pending = []
        last_ts = ir.get("updated_at_ms") or ir.get("created_at_ms")

        def flush_pending():
            nonlocal pending
            for cid in pending:
                out.append({"kind": "tool_result", "ts": last_ts, "call_id": cid,
                            "name": call_names[cid], "content": MISSING_RESULT_TEXT,
                            "is_error": False})
            pending = []

        for ev in events:
            if isinstance(ev.get("ts"), int):
                last_ts = ev["ts"]
            if ev.get("kind") == "assistant_message":
                flush_pending()
                out.append(ev)
                for b in ev.get("blocks") or []:
                    if b.get("type") == "tool-call" and b.get("id") in missing:
                        pending.append(b["id"])
            elif ev.get("kind") == "tool_result":
                out.append(ev)
            else:
                flush_pending()
                out.append(ev)
        flush_pending()
        events[:] = out
    calls = sum(
        1
        for ev in events
        if ev.get("kind") == "assistant_message"
        for b in ev.get("blocks", [])
        if b.get("type") == "tool-call"
    )
    results = sum(1 for ev in events if ev.get("kind") == "tool_result")
    ir["stats"] = {
        "events": len(events),
        "user_messages": sum(1 for ev in events if ev.get("kind") == "user_message"),
        "assistant_messages": sum(1 for ev in events if ev.get("kind") == "assistant_message"),
        "reasoning_blocks": sum(
            1
            for ev in events
            if ev.get("kind") == "assistant_message"
            for b in ev.get("blocks", [])
            if b.get("type") == "reasoning"
        ),
        "tool_calls": calls,
        "tool_results": results,
        "unpaired_tool_calls": max(0, calls - results),
        "compactions": sum(1 for ev in events if ev.get("kind") == "compaction"),
        "system_messages": sum(1 for ev in events if ev.get("kind") == "system_message"),
    }
    ir.setdefault("warnings", [])
    return ir


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, ir):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ir, f, ensure_ascii=False, indent=1)
        f.write("\n")
