"""Windsurf / Codeium Cascade session reader (JSONL transcripts).

Store candidates (first existing wins; all can be overridden):
    ``$WINDSURF_HOME`` / ``$SESSIONPORT_WINDSURF_HOME``
    ``~/.windsurf/sessions``, ``~/.windsurf``, ``~/.codeium/windsurf/sessions``

Each session is one JSONL file; the common shape is
``{"role": "user"|"assistant"|"tool", "content": str | [blocks]}`` plus optional
``timestamp``/``created_at``/``cwd``/``model``/``tool_calls``/``tool_call_id``.
The parser is deliberately tolerant: blocks may be strings or
``{"type":"text"|"input_text"|"output_text","text":...}``; unknown fields are
kept as warnings rather than dropped silently.

Evidence: native-format reader (sessionport ``WindsurfStore`` cross-check);
local store not present on this machine. Reader-only: no verified native writer.
"""
import glob
import json
import os

from ..common import iso_to_ms
from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts, warn


def _candidate_roots():
    override = os.environ.get("WINDSURF_HOME") or os.environ.get("SESSIONPORT_WINDSURF_HOME")
    if override:
        return [os.path.expanduser(override)]
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".windsurf", "sessions"),
        os.path.join(home, ".windsurf"),
        os.path.join(home, ".codeium", "windsurf", "sessions"),
    ]


def default_root():
    for cand in _candidate_roots():
        if os.path.isdir(cand):
            return cand
    return _candidate_roots()[0]


def _files(root):
    root = os.path.expanduser(root or default_root())
    if os.path.isfile(root):
        return [root]
    if not os.path.isdir(root):
        return []
    return sorted(f for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
                  if os.path.isfile(f))


def _rows(path):
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                rows.append({"__parse_error__": True})
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _role(row):
    return str(row.get("role") or row.get("type") or "").lower()


def _content_blocks(content):
    out = []
    if isinstance(content, str):
        if content.strip():
            out.append(text_block(content))
        return out
    if isinstance(content, list):
        for b in content:
            if isinstance(b, str):
                if b.strip():
                    out.append(text_block(b))
            elif isinstance(b, dict):
                bt = b.get("type")
                if bt in (None, "text", "input_text", "output_text"):
                    if isinstance(b.get("text"), str) and b["text"].strip():
                        out.append(text_block(b["text"]))
                elif bt in ("thinking", "reasoning"):
                    txt = b.get("thinking") or b.get("text") or ""
                    if txt.strip():
                        out.append({"type": "reasoning", "text": txt})
                elif bt in ("tool_use", "tool_call", "tool-call"):
                    out.append({"type": "tool-call",
                                "id": str(b.get("id") or b.get("tool_call_id") or ""),
                                "name": str(b.get("name") or "tool"),
                                "arguments": _json_text(b.get("input", b.get("arguments")))})
                elif bt in ("image", "image_url"):
                    out.append({"type": "image", "placeholder": "[image attachment not imported]"})
    elif isinstance(content, dict):
        return _content_blocks([content])
    return out


def _json_text(value):
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _first_user_title(rows):
    for row in rows:
        if _role(row) in ("user", "human", "prompt"):
            blocks = _content_blocks(row.get("content"))
            text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            if text:
                return text.splitlines()[0][:120]
    return ""


def _session_id(rows, path):
    for row in rows:
        for key in ("session_id", "sessionId", "conversation_id", "conversationId", "id"):
            value = row.get(key)
            if isinstance(value, str) and value:
                return value
    return os.path.splitext(os.path.basename(path))[0]


def _timestamp(row):
    for key in ("timestamp", "created_at", "createdAt", "ts", "time"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        ms = iso_to_ms(value)
        if ms:
            return int(ms)
    return None


def _usage(rows):
    for row in rows:
        raw = row.get("usage") if isinstance(row.get("usage"), dict) else None
        if raw is None and isinstance(row.get("metrics"), dict):
            raw = row.get("metrics")
        usage = normalize_usage(raw)
        if usage:
            return usage
    return None


def list_sessions(root=None):
    root = os.path.expanduser(root or default_root())
    out = []
    for path in _files(root):
        rows = [r for r in _rows(path) if "__parse_error__" not in r]
        if not rows:
            continue
        times = [t for t in (_timestamp(r) for r in rows) if t]
        cwd = next((r.get("cwd") for r in rows if isinstance(r.get("cwd"), str)), None)
        model = next((r.get("model") for r in rows if isinstance(r.get("model"), str)), "")
        out.append({
            "source": "windsurf",
            "id": _session_id(rows, path),
            "title": _first_user_title(rows) or os.path.basename(path),
            "cwd": cwd,
            "created_at_ms": min(times) if times else int(os.path.getmtime(path) * 1000),
            "updated_at_ms": max(times) if times else int(os.path.getmtime(path) * 1000),
            "path": path,
            "lines": len(rows),
            "model": model,
        })
    out.sort(key=lambda r: (r.get("updated_at_ms") or 0, r.get("id") or ""), reverse=True)
    return out


def resolve_path(root, session=None):
    root = os.path.expanduser(root or default_root())
    for row in list_sessions(root):
        if str(row.get("id")) == str(session) or os.path.basename(row.get("path") or "") == str(session):
            return row["path"]
    if session and os.path.isfile(os.path.expanduser(str(session))):
        return os.path.expanduser(str(session))
    return None


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or default_root())
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("windsurf session not found for %r under %s" % (session, root))
    rows = _rows(path)
    sid = _session_id(rows, path)
    cwd = next((r.get("cwd") for r in rows if isinstance(r.get("cwd"), str)), None)
    ir = new_ir("windsurf", sid, path, cwd=cwd)
    ir["provider"] = "windsurf"
    times = [t for t in (_timestamp(r) for r in rows) if t]
    if times:
        ir["created_at_ms"] = min(times)
        ir["updated_at_ms"] = max(times)
    ir["model"] = next((r.get("model") for r in rows if isinstance(r.get("model"), str)), "")
    for row in rows:
        if "__parse_error__" in row:
            warn(ir, "skipped malformed windsurf line")
            continue
        role = _role(row)
        ts = _timestamp(row)
        touch_ts(ir, ts)
        blocks = _content_blocks(row.get("content"))
        # Anthropic-style tool_calls on an assistant row
        for call in row.get("tool_calls") or []:
            if isinstance(call, dict):
                fn = call.get("function") if isinstance(call.get("function"), dict) else call
                blocks.append({"type": "tool-call",
                               "id": str(call.get("id") or call.get("tool_call_id") or ""),
                               "name": str(fn.get("name") or "tool"),
                               "arguments": _json_text(fn.get("arguments"))})
        if role in ("user", "human", "prompt"):
            text_blocks = [b for b in blocks if b.get("type") != "tool-call"]
            if text_blocks:
                add_event(ir, "user_message", ts, blocks=text_blocks)
        elif role == "assistant":
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks)
        elif role == "tool":
            result = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            add_event(ir, "tool_result", ts,
                      call_id=str(row.get("tool_call_id") or row.get("toolCallId") or ""),
                      name=str(row.get("name") or "tool"),
                      content=result or "[non-text tool result omitted]",
                      is_error=bool(row.get("is_error") or row.get("error")))
        elif role in ("system", "developer"):
            if keep_system:
                text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                if text:
                    add_event(ir, "system_message", ts, text=text)
        else:
            warn(ir, "unknown windsurf role skipped: %r" % (role,))
    usage = _usage(rows)
    if usage:
        ir["source_usage"] = usage
        for ev in reversed(ir["events"]):
            if ev.get("kind") == "assistant_message":
                ev["usage"] = usage
                break
    ir["extra"] = {
        "evidence_level": "NATIVE-FORMAT (store unavailable on this machine)",
        "native_layout": "~/.windsurf/**/*.jsonl (or Codeium Cascade dir)",
        "format_source": "sessionport stores.py::WindsurfStore (MIT)",
        "reader_only": True,
    }
    finalize(ir)
    return ir
