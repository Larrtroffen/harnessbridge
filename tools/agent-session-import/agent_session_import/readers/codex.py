"""Codex (~/.codex) reader.

Authoritative source: rollout JSONL (sessions/YYYY/MM/DD/rollout-*.jsonl), ordered by
``ordinal``.  ``state_5.sqlite -> threads`` is used as the thread index (rollout_path,
title, cwd, model) because it always points at the current file for a thread id; a pure
filesystem scan is the fallback when SQLite is unavailable.
"""
import glob
import json
import os
import re
import sqlite3

from ..common import HOME, count_lines, iso_to_ms, iter_jsonl, read_jsonl
from ..ir import add_event, finalize, new_ir, text_block, touch_ts, warn

DEFAULT_ROOT = os.path.join(HOME, ".codex")
SESSIONS_SUBDIR = "sessions"

_EXIT_RE = re.compile(r"Process exited with code (-?\d+)")


def _is_injected_user_text(text):
    """True for Codex-injected user items (environment/instruction preambles).

    A *standalone* ``<environment_context>...</environment_context>`` item is injected; a user
    message that merely starts with such a block and then carries real user content is kept
    (OSS capture sessions often merge them).
    """
    text = (text or "").lstrip()
    if text.startswith("[System]"):
        return True
    for tag in ("environment_context", "user_instructions", "INSTRUCTIONS"):
        open_tag = "<%s>" % tag
        close_tag = "</%s>" % tag
        if text.startswith(open_tag):
            idx = text.find(close_tag)
            if idx < 0:
                return True
            return not text[idx + len(close_tag):].strip()
    return False
_ERROR_MARKER = "\n[asi-import: tool error]"

_IMAGE_TYPES = {"input_image", "image", "image_url", "output_image"}


def default_root():
    return os.path.expanduser(os.environ.get("CODEX_HOME") or DEFAULT_ROOT)


def _root(root=None):
    return os.path.expanduser(root or os.environ.get("CODEX_HOME") or DEFAULT_ROOT)


# --------------------------------------------------------------------------- index
def _connect(root):
    db = os.path.join(root, "state_5.sqlite")
    if not os.path.isfile(db):
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3F"), uri=True)
    except sqlite3.Error:
        return None


def _titles(root):
    """thread id -> thread_name from session_index.jsonl (a partial index)."""
    out = {}
    path = os.path.join(root, "session_index.jsonl")
    if not os.path.isfile(path):
        return out
    try:
        for _i, obj in read_jsonl(path):
            if obj.get("id") and obj.get("thread_name"):
                out[obj["id"]] = obj["thread_name"]
    except OSError:
        pass
    return out


def _fallback_scan(root):
    titles = _titles(root)
    files = glob.glob(os.path.join(root, SESSIONS_SUBDIR, "**", "*.jsonl"), recursive=True)
    best = {}
    for path in files:
        meta = None
        try:
            for _i, row in read_jsonl(path):
                if row.get("type") == "session_meta":
                    meta = row.get("payload") or {}
                    break
        except OSError:
            continue
        if not meta or not meta.get("id"):
            continue
        sid = meta["id"]
        cur = {
            "source": "codex",
            "id": sid,
            "title": titles.get(sid) or "",
            "cwd": meta.get("cwd"),
            "created_at_ms": iso_to_ms(meta.get("timestamp")),
            "updated_at_ms": int(os.path.getmtime(path) * 1000),
            "path": path,
            "lines": 0,
            "model": "",
            "archived": 0,
        }
        old = best.get(sid)
        if old is None or cur["updated_at_ms"] > old["updated_at_ms"]:
            best[sid] = cur
    out = list(best.values())
    out.sort(key=lambda r: r["updated_at_ms"] or 0, reverse=True)
    return out


def list_sessions(root=None):
    root = _root(root)
    con = _connect(root)
    rows = []
    if con is not None:
        try:
            sql = (
                "select id, rollout_path, cwd, title, first_user_message, updated_at, "
                "updated_at_ms, created_at_ms, model, model_provider, archived from threads "
                "order by updated_at desc"
            )
            for r in con.execute(sql):
                (sid, rollout, cwd, title, first_user, updated_s, updated_ms, created_ms,
                 model, provider, archived) = r
                updated = updated_ms or (int(updated_s) * 1000 if updated_s else None)
                created = created_ms or (int(updated_s) * 1000 if updated_s else None)
                title = (title or "").strip() or (first_user or "").strip()
                rows.append(
                    {
                        "source": "codex",
                        "id": sid,
                        "title": title[:120],
                        "cwd": cwd,
                        "created_at_ms": created,
                        "updated_at_ms": updated,
                        "path": rollout,
                        "lines": 0,
                        "model": model or "",
                        "provider": provider or "",
                        "archived": int(archived or 0),
                    }
                )
        except sqlite3.Error:
            rows = []
        finally:
            con.close()
    if not rows:
        rows = _fallback_scan(root)
    for r in rows:
        if r.get("path") and os.path.isfile(r["path"]):
            try:
                r["lines"] = count_lines(r["path"])
            except OSError:
                r["lines"] = 0
        else:
            r["lines"] = 0
    return rows


def resolve_path(root, session=None):
    root = _root(root)
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        con = _connect(root)
        if con is not None:
            try:
                row = con.execute("select rollout_path from threads where id=?", (session,)).fetchone()
            except sqlite3.Error:
                row = None
            finally:
                con.close()
            if row and row[0] and os.path.isfile(row[0]):
                return row[0]
        # filename contains the thread id (base id or fork id)
        hits = []
        for path in glob.glob(os.path.join(root, SESSIONS_SUBDIR, "**", "*.jsonl"), recursive=True):
            if session in os.path.basename(path):
                hits.append(path)
        if hits:
            hits.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return hits[0]
        # scan first line for payload.id / payload.session_id
        for path in glob.glob(os.path.join(root, SESSIONS_SUBDIR, "**", "*.jsonl"), recursive=True):
            try:
                for _i, row in read_jsonl(path):
                    if row.get("type") == "session_meta":
                        p = row.get("payload") or {}
                        if session in (p.get("id"), p.get("session_id")):
                            return path
                        break
            except OSError:
                continue
    # newest rollout as a last resort
    files = glob.glob(os.path.join(root, SESSIONS_SUBDIR, "**", "*.jsonl"), recursive=True)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


# --------------------------------------------------------------------------- convert
def load_session(root=None, session=None, path=None, keep_system=False):
    root = _root(root)
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("codex rollout not found for session=%r root=%s" % (session, root))

    bad = []
    rows = [obj for _i, obj in iter_jsonl(path, bad)]
    rows.sort(key=lambda r: (r.get("ordinal") if isinstance(r.get("ordinal"), int) else 0))
    titles = _titles(root)

    meta = {}
    ir = None
    ir = new_ir("codex", "", path)
    calls = {}
    pending = []  # assistant blocks accumulated until a boundary
    pending_ts = None
    current_model = ""
    pending_images = 0
    skipped_agent_messages = 0
    injected_user_count = 0
    abort_reason = None

    def flush_assistant():
        nonlocal pending, pending_ts
        if not pending:
            pending_ts = None
            return
        add_event(
            ir,
            "assistant_message",
            pending_ts,
            blocks=pending,
            model=current_model or meta.get("model") or "",
            provider=meta.get("model_provider") or "codex",
            source_id=None,
        )
        pending = []
        pending_ts = None

    def push_block(ts, block):
        nonlocal pending_ts
        if pending_ts is None or (ts is not None and ts < pending_ts):
            pending_ts = ts
        pending.append(block)

    for row in rows:
        rtype = row.get("type")
        payload = row.get("payload") or {}
        ts = iso_to_ms(row.get("timestamp"))
        if rtype == "session_meta":
            if not meta:
                meta = payload
                ir["source_session_id"] = payload.get("id") or payload.get("session_id") or ""
                ir["cwd"] = payload.get("cwd")
                ir["created_at_ms"] = iso_to_ms(payload.get("timestamp")) or ts
                ir["updated_at_ms"] = ir["created_at_ms"]
                if keep_system:
                    bi = (payload.get("base_instructions") or {}).get("text")
                    if bi:
                        ir["system_prompt"] = bi
            touch_ts(ir, ts)
        elif rtype == "turn_context":
            current_model = payload.get("model") or current_model
            touch_ts(ir, ts)
        elif rtype == "response_item":
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                blocks = []
                for b in payload.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt in _IMAGE_TYPES:
                        blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
                    else:
                        txt = b.get("text")
                        if isinstance(txt, str) and txt:
                            blocks.append(text_block(txt))
                if role == "user":
                    flush_assistant()
                    joined = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").lstrip()
                    injected = _is_injected_user_text(joined)
                    if not blocks or not "".join(
                        b.get("text", "") for b in blocks if b.get("type") == "text"
                    ).strip():
                        pass
                    elif injected:
                        injected_user_count += 1
                        if keep_system:
                            add_event(ir, "system_message", ts, text=joined, origin="injected-user")
                            touch_ts(ir, ts)
                    else:
                        add_event(ir, "user_message", ts, blocks=blocks)
                        touch_ts(ir, ts)
                elif role == "assistant":
                    for b in blocks:
                        push_block(ts, b)
                elif role == "developer":
                    if keep_system:
                        flush_assistant()
                        txt = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                        if txt:
                            add_event(ir, "system_message", ts, text=txt, origin="developer")
                            touch_ts(ir, ts)
            elif ptype == "reasoning":
                summary = payload.get("summary") or []
                txt = "\n".join(s.get("text", "") for s in summary if isinstance(s, dict) and s.get("text"))
                if txt:
                    push_block(ts, {"type": "reasoning", "text": txt})
            elif ptype in ("function_call", "custom_tool_call"):
                call_id = payload.get("call_id") or payload.get("id") or ""
                name = payload.get("name") or "tool"
                args = payload.get("arguments")
                if args is None:
                    args = payload.get("input")
                if not isinstance(args, str):
                    args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                calls[call_id] = {"name": name}
                push_block(ts, {"type": "tool-call", "id": call_id, "name": name, "arguments": args})
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                flush_assistant()
                call_id = payload.get("call_id") or ""
                output = payload.get("output")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False) if output is not None else ""
                if output.endswith(_ERROR_MARKER):
                    output = output[: -len(_ERROR_MARKER)]
                    is_error = True
                else:
                    m = _EXIT_RE.search(output)
                    is_error = bool(m and int(m.group(1)) != 0)
                add_event(
                    ir,
                    "tool_result",
                    ts,
                    call_id=call_id,
                    name=(calls.get(call_id) or {}).get("name") or "tool",
                    content=output,
                    is_error=is_error,
                )
                touch_ts(ir, ts)
            elif ptype == "web_search_call":
                action = payload.get("action") or {}
                call_id = payload.get("call_id") or payload.get("id") or ""
                name = "web_search"
                calls[call_id] = {"name": name}
                push_block(
                    ts,
                    {
                        "type": "tool-call",
                        "id": call_id,
                        "name": name,
                        "arguments": json.dumps(action, ensure_ascii=False),
                    },
                )
            elif ptype == "agent_message":
                skipped_agent_messages += 1
            elif ptype in ("tool_search_call", "tool_search_output", "image_generation_call"):
                pass
        elif rtype == "event_msg":
            etype = payload.get("type")
            if etype in ("task_started", "task_complete", "turn_aborted"):
                flush_assistant()
                if etype == "turn_aborted":
                    abort_reason = payload.get("reason") or "interrupted"
            touch_ts(ir, ts)
        elif rtype == "compacted":
            flush_assistant()
            add_event(ir, "compaction", ts, summary=payload.get("message") or "", extra={"window_number": payload.get("window_number")})
            touch_ts(ir, ts)
    flush_assistant()

    if abort_reason is not None:
        add_event(ir, "turn_abort", ir.get("updated_at_ms"), reason=str(abort_reason))

    if not ir["source_session_id"]:
        ir["source_session_id"] = os.path.basename(path).rsplit(".", 1)[0]
    if not ir.get("cwd"):
        ir["cwd"] = (meta.get("cwd") or "")
    title = titles.get(ir["source_session_id"]) or ""
    finalize(ir, fallback_title=title, model=current_model or meta.get("model") or "", provider=meta.get("model_provider"))
    if bad:
        warn(ir, "%d malformed JSONL line(s) skipped" % len(bad))
    if skipped_agent_messages:
        warn(ir, "%d inter-agent (agent_message) item(s) skipped" % skipped_agent_messages)
    if injected_user_count:
        warn(ir, "%d injected environment/instruction user item(s) skipped (use --keep-system to keep)" % injected_user_count)
    unpaired = ir["stats"]["unpaired_tool_calls"]
    if unpaired:
        warn(ir, "%d tool call(s) had no output in source (placeholder result will be written)" % unpaired)
    return ir
