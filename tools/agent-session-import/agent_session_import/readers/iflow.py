"""iFlow CLI (~/.iflow/projects/<project>/<sessionId>.jsonl) reader.

iFlow CLI 0.5.x stores CLI chat sessions as **Claude Code compatible JSONL**: one
JSON object per line with ``uuid``/``parentUuid``/``sessionId``/``timestamp``/
``type`` (user/assistant) and ``message`` content blocks (text / thinking /
tool_use / tool_result) — the same schema as ``~/.claude/projects`` (see
``readers.claude``), just under the iFlow config root.

Evidence (task-62): kenn-io/agentsview ``internal/parser/iflow.go`` + MIT testdata
``testdata/iflow/session-*.jsonl``; storage layout reverse-documented from the
npm package ``@iflow-ai/iflow-cli@0.5.19`` (``getProjectsDir()`` / ``saveMessage``).

Root resolution: ``$IFLOW_HOME/projects`` (``IFLOW_HOME`` also accepts the iFlow
config root itself), default ``~/.iflow/projects``.

ACP fallback: iFlow also keeps ``<IFLOW_HOME>/acp/sessions/<sid>.json`` for ACP
mode. That JSON schema is not published; the fallback accepts a best-effort
``{sessionId,cwd,title?,messages:[{role,content}]}`` shape and warns that the
schema is unverified. Native CLI JSONL always wins.

Reader-only: no writer is registered for iFlow in this build (the claude writer
could be pointed at the iFlow root, but that wiring is outside this task's
scope). ``product.py`` marks iFlow export-only.
"""
import glob
import json
import os

from ..common import HOME, iso_to_ms, iter_jsonl, read_jsonl
from ..ir import add_event, finalize, new_ir, text_block, touch_ts, warn
from . import claude

SOURCE = "iflow"
DEFAULT_IFLOW_HOME = os.path.join(HOME, ".iflow")


def iflow_home():
    return os.path.expanduser(os.environ.get("IFLOW_HOME") or DEFAULT_IFLOW_HOME)


def default_root():
    return os.path.join(iflow_home(), "projects")


def _projects_root(root=None):
    """Accept the projects dir, the iFlow config root, or the sessions root."""
    root = os.path.expanduser(root or default_root())
    if os.path.isdir(os.path.join(root, "projects")):
        return os.path.join(root, "projects")
    return root


def acp_root():
    return os.path.join(iflow_home(), "acp", "sessions")


# --------------------------------------------------------------------------- native
def _relabel(rows):
    for row in rows:
        row["source"] = SOURCE
        row["provider"] = "iflow"
        row["evidence_level"] = "FIXTURE+REAL-LOCAL layout (Claude-compatible JSONL)"
    return rows


def _native_files(root):
    return [f for f in glob.glob(os.path.join(root, "*", "*.jsonl")) if os.path.isfile(f)]


# --------------------------------------------------------------------------- ACP fallback
def _acp_files(root=None):
    root = os.path.expanduser(root or acp_root())
    return sorted(f for f in glob.glob(os.path.join(root, "*.json")) if os.path.isfile(f))


def _acp_title(obj):
    for key in ("title", "name"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for msg in obj.get("messages") or []:
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip().splitlines()[0][:120]
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip():
                        return b["text"].strip().splitlines()[0][:120]
    return ""


def _list_acp(root=None):
    rows = []
    for path in _acp_files(root):
        sid = os.path.basename(path)[:-5]
        title, cwd, updated = "", None, int(os.path.getmtime(path) * 1000)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                title = _acp_title(obj)
                cwd = obj.get("cwd") or obj.get("working_directory")
                updated = iso_to_ms(obj.get("updatedAt") or obj.get("updated_at")
                                    or obj.get("lastActivityAt")) or updated
        except (OSError, ValueError):
            pass
        rows.append({"source": SOURCE, "id": sid, "title": title or sid, "cwd": cwd,
                     "created_at_ms": updated, "updated_at_ms": updated, "path": path,
                     "lines": 0, "model": "", "archived": 0,
                     "evidence_level": "ACP-JSON(unverified)"})
    return rows


# --------------------------------------------------------------------------- list
def list_sessions(root=None):
    root = _projects_root(root)
    rows = _relabel(claude.list_sessions(root))
    if not rows:
        rows = _list_acp()
    return rows


# --------------------------------------------------------------------------- resolve
def resolve_path(root, session=None):
    root = _projects_root(root)
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        sid = session[6:] if session.startswith("iflow:") else session
        hits = [p for p in _native_files(root) if os.path.splitext(os.path.basename(p))[0] == sid]
        if hits:
            hits.sort(key=os.path.getmtime, reverse=True)
            return hits[0]
        acp = os.path.join(acp_root(), "%s.json" % sid)
        if os.path.isfile(acp):
            return acp
        # sessionId may differ from the file stem? iFlow stores <sessionId>.jsonl.
        return claude.resolve_path(root, session=sid)
    return claude.resolve_path(root, session=None)


# --------------------------------------------------------------------------- ACP load
def _load_acp(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("iFlow ACP session JSON must be an object: %s" % path)
    sid = obj.get("sessionId") or obj.get("session_id") or os.path.basename(path)[:-5]
    ir = new_ir(SOURCE, sid, path, cwd=obj.get("cwd") or obj.get("working_directory"))
    msgs = obj.get("messages")
    if not isinstance(msgs, list):
        raise ValueError("iFlow ACP session JSON has no messages list: %s" % path)
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or msg.get("type")
        ts = iso_to_ms(msg.get("timestamp") or msg.get("created_at"))
        content = msg.get("content")
        texts = []
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and isinstance(b.get("text"), str):
                    texts.append(b["text"])
        text = "\n".join(t for t in texts if t.strip())
        if not text:
            continue
        if role in ("user", "human"):
            add_event(ir, "user_message", ts, blocks=[text_block(text)])
        elif role in ("assistant", "ai", "agent"):
            add_event(ir, "assistant_message", ts, blocks=[text_block(text)],
                      model=obj.get("model") or "", provider="iflow")
        else:
            add_event(ir, "system_message", ts, text=text, origin="acp:%s" % role)
        ir["updated_at_ms"] = ts or ir["updated_at_ms"]
    warn(ir, "iFlow ACP JSON schema is not published; parsed with a best-effort fallback")
    finalize(ir, fallback_title=obj.get("title") or "")
    return ir


# --------------------------------------------------------------------------- native load
def _ms(o):
    return iso_to_ms(o.get("timestamp"))


def _classify_user(o):
    """iFlow user rows: tool_result / compact summary / injected / human prompt.

    iFlow native rows do not carry Claude's ``promptId``/``origin`` fields, so a
    non-empty string/text row is a human prompt unless it is a meta/injected row.
    """
    msg = o.get("message") or {}
    content = msg.get("content")
    first = content[0] if isinstance(content, list) and content else None
    if isinstance(first, dict) and first.get("type") == "tool_result":
        return "tool_result"
    if o.get("isCompactSummary"):
        return "compact_summary"
    if o.get("isMeta"):
        return "injected"
    origin = (o.get("origin") or {}).get("kind")
    if origin in ("task-notification", "system"):
        return "injected"
    texts = "\n".join(claude._texts(content)).lstrip()
    if texts.startswith(claude._INJECTED_PREFIXES):
        return "injected"
    if isinstance(first, dict) and first.get("type") == "image":
        return "image"
    if texts.strip():
        return "human"
    return "other"


def _assistant_blocks(content, ir, seen_calls=None, stats=None):
    blocks = []
    seen_calls = seen_calls if seen_calls is not None else set()
    stats = stats if stats is not None else {"duplicate_tool_uses": 0}
    content = content if isinstance(content, list) else []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            txt = b.get("text")
            if isinstance(txt, str) and txt.strip():
                blocks.append(text_block(txt))
        elif bt == "thinking":
            txt = b.get("thinking") or b.get("text")
            if isinstance(txt, str) and txt.strip():
                blocks.append({"type": "reasoning", "text": txt})
        elif bt == "tool_use":
            cid = b.get("id") or ""
            if cid and cid in seen_calls:
                # iFlow repeats each tool_use in adjacent incremental assistant rows.
                stats["duplicate_tool_uses"] += 1
                continue
            if cid:
                seen_calls.add(cid)
            args = b.get("input")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            blocks.append({"type": "tool-call", "id": cid,
                           "name": b.get("name") or "tool", "arguments": args})
        elif bt == "image":
            blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
    return blocks


def _tool_result_text(inner):
    if isinstance(inner, str):
        return inner
    if isinstance(inner, list):
        parts = []
        for b in inner:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
        return "\n".join(parts) or "[non-text tool result omitted]"
    return json.dumps(inner, ensure_ascii=False)[:4000] if inner is not None else ""


def _load_native(path, keep_system=False):
    bad = []
    rows = [obj for _i, obj in iter_jsonl(path, bad)]
    sid = os.path.splitext(os.path.basename(path))[0]
    ir = new_ir(SOURCE, sid, path)
    ir["provider"] = "iflow"
    seen_calls, dup_stats = set(), {"duplicate_tool_uses": 0}
    # Group consecutive assistant rows sharing message.id into one logical message.
    groups = []   # list of {"id","model","usage","blocks","ts","start","end"}
    current = None
    for idx, row in enumerate(rows):
        if row.get("type") != "assistant":
            current = None
            continue
        msg = row.get("message") or {}
        mid = msg.get("id") or ""
        if current is None or current["id"] != mid:
            current = {"id": mid, "model": msg.get("model") or "",
                       "usage": msg.get("usage"), "blocks": [], "ts": _ms(row),
                       "start": idx, "end": idx}
            groups.append(current)
        current["blocks"].extend(_assistant_blocks(msg.get("content"), ir, seen_calls, dup_stats))
        current["ts"] = current["ts"] or _ms(row)
        current["end"] = idx
        if not ir.get("model") and msg.get("model"):
            ir["model"] = msg["model"]
    start_at = {g["start"]: g for g in groups}
    consumed = set()
    for g in groups:
        consumed.update(range(g["start"], g["end"] + 1))
    injected = compact = 0
    for idx, row in enumerate(rows):
        rtype = row.get("type")
        if idx in start_at:
            g = start_at[idx]
            if g["blocks"]:
                add_event(ir, "assistant_message", g["ts"], blocks=g["blocks"],
                          model=g["model"] or "", provider="iflow", usage=g["usage"])
            touch_ts(ir, g["ts"])
            if not ir.get("cwd") and row.get("cwd"):
                ir["cwd"] = row["cwd"]
            continue
        if idx in consumed:
            continue
        if rtype == "user":
            cls = _classify_user(row)
            msg = row.get("message") or {}
            content = msg.get("content")
            if cls == "tool_result":
                first = content[0]
                inner = first.get("content")
                add_event(ir, "tool_result", _ms(row),
                          call_id=first.get("tool_use_id") or "",
                          name="tool", content=_tool_result_text(inner),
                          is_error=bool(first.get("is_error")))
            elif cls in ("human", "image"):
                blocks = claude._content_blocks(content)
                if blocks:
                    add_event(ir, "user_message", _ms(row), blocks=blocks)
            elif cls == "compact_summary":
                compact += 1
                if keep_system:
                    text = "\n".join(claude._texts(content))
                    if text:
                        add_event(ir, "system_message", _ms(row), text=text,
                                  origin="compact_summary")
            else:
                injected += 1
                if keep_system:
                    text = "\n".join(claude._texts(content))
                    if text:
                        add_event(ir, "system_message", _ms(row), text=text, origin=cls)
            touch_ts(ir, _ms(row))
            if not ir.get("cwd") and row.get("cwd"):
                ir["cwd"] = row["cwd"]
        elif rtype in ("system", "last-prompt", "custom-title", "ai-title"):
            if rtype == "system" and keep_system and row.get("subtype") == "compact_boundary":
                add_event(ir, "compaction", _ms(row), summary=row.get("content") or "")
            touch_ts(ir, _ms(row))
            if not ir.get("cwd") and row.get("cwd"):
                ir["cwd"] = row["cwd"]
        else:
            # unknown/aux row type: ignore silently (same policy as other readers)
            touch_ts(ir, _ms(row))
    if not ir.get("cwd"):
        for row in rows:
            if row.get("cwd"):
                ir["cwd"] = row["cwd"]
                break
    finalize(ir, fallback_title="")
    if bad:
        warn(ir, "%d malformed JSONL line(s) skipped" % len(bad))
    if injected:
        warn(ir, "%d injected/meta user row(s) skipped (use --keep-system to keep)" % injected)
    if compact:
        warn(ir, "%d compaction summary row(s) skipped (use --keep-system to keep)" % compact)
    if dup_stats["duplicate_tool_uses"]:
        warn(ir, "%d duplicated incremental tool_use block(s) deduped (iFlow row layout)"
             % dup_stats["duplicate_tool_uses"])
    if any(e.get("kind") == "tool_result" for e in ir["events"]):
        pass
    return ir


# --------------------------------------------------------------------------- load
def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    root = _projects_root(root)
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("iflow session not found for session=%r root=%s" % (session, root))
    if path.endswith(".json"):
        return _load_acp(path)
    return _load_native(path, keep_system=keep_system)
