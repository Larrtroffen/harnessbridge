"""Zed (editor Agent Panel) reader — ``threads/threads.db`` SQLite, reader-only.

Storage (verified against zed-industries/zed source + agentsview parser):

* macOS:   ``~/Library/Application Support/Zed/threads/threads.db``
* Linux:   ``~/.local/share/zed/threads/threads.db``
* Windows: ``%LOCALAPPDATA%\\Zed\\threads\\threads.db``
* override: ``$ZED_HOME`` (may point at the Zed data dir, the ``threads`` dir, or
  the ``threads.db`` file itself)

Table (old DBs may miss the last four columns — readers must tolerate that)::

    threads(id TEXT PRIMARY KEY, summary TEXT, updated_at TEXT, data_type TEXT,
            data BLOB, parent_id TEXT, folder_paths TEXT,
            folder_paths_order TEXT, created_at TEXT)

``data_type`` is ``json`` or ``zstd`` (zstd-compressed JSON via the zstd CLI).
``data`` JSON is Rust ``DbThread``: ``{title, messages:[Message], updated_at,
model:{model,provider}, cumulative_token_usage, request_token_usage, ...}`` with
externally-tagged serde enums::

    Message  = {"User": {id, content:[UserMessageContent]}}
             | {"Agent": {content:[AgentMessageContent], tool_results:{id:result}}}
             | "Resume"
             | {"Compaction": {"Summary": "..."} | {"ProviderNative": {...}}}
    UserMessageContent  = {"Text": "..."} | {"Mention": {...}} | {"Image": ...}
    AgentMessageContent = {"Text": "..."} | {"Thinking": {text, signature}}
                        | {"RedactedThinking": "..."} | {"ToolUse": {id, name, input}}
    tool_results        = {tool_use_id: <result>}

Writer is intentionally NOT implemented: the DB is app-owned (sqlez migrations,
private serde payload, no CLI resume). ``product.py`` marks Zed reader-only /
export-only.
"""
import glob
import json
import os
import sqlite3

from ..common import HOME, ZSTD, iso_to_ms, zcat
from ..ir import (add_event, blocks_text, finalize, new_ir, normalize_usage,
                  text_block, touch_ts, warn)

SOURCE = "zed"
DEFAULT_MAC_ZED = os.path.join(HOME, "Library", "Application Support", "Zed")
DEFAULT_LINUX_ZED = os.path.join(HOME, ".local", "share", "zed")


def _zed_data_dir():
    env = os.environ.get("ZED_HOME")
    if env:
        return os.path.expanduser(env)
    if os.path.isdir(DEFAULT_MAC_ZED):
        return DEFAULT_MAC_ZED
    return DEFAULT_LINUX_ZED


def default_root():
    """Return the directory that holds ``threads.db`` (or the db path itself if ZED_HOME names it)."""
    data = _zed_data_dir()
    if data.endswith(".db"):
        return data
    return os.path.join(data, "threads")


def _db_path(root=None):
    root = os.path.expanduser(root or default_root())
    if os.path.isfile(root):
        return root
    cand = os.path.join(root, "threads.db")
    if os.path.isfile(cand):
        return cand
    # also accept the Zed data dir
    cand = os.path.join(root, "threads", "threads.db")
    if os.path.isfile(cand):
        return cand
    return None


def _connect(db_path):
    uri = "file:%s?mode=ro" % db_path.replace("?", "%3F")
    return sqlite3.connect(uri, uri=True)


def _columns(con):
    try:
        return {row[1] for row in con.execute("PRAGMA table_info(threads)")}
    except sqlite3.Error:
        return set()


def _first_folder(folder_paths):
    """Zed stores worktree roots in a PathList-ish column; accept plain path / JSON."""
    if not folder_paths:
        return None
    if isinstance(folder_paths, str):
        s = folder_paths.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
        except ValueError:
            return s.split(os.pathsep)[0] or s
        return _first_folder(parsed)
    if isinstance(folder_paths, dict):
        for key in ("paths", "items", "roots", "values"):
            if key in folder_paths:
                return _first_folder(folder_paths[key])
        return None
    if isinstance(folder_paths, (list, tuple)):
        for item in folder_paths:
            cwd = _first_folder(item)
            if cwd:
                return cwd
        return None
    return None


# --------------------------------------------------------------------------- decode
_THREAD_ENUMS = ("User", "Agent", "Resume", "Compaction")


def decode_thread_data(data_type, data):
    """Decode the ``threads.data`` BLOB into a DbThread dict."""
    if isinstance(data, str):
        raw = data.encode("utf-8")
    elif isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    else:
        raw = bytes(data or b"")
    kind = (data_type or "").strip().lower()
    if not kind:
        kind = "zstd" if raw[:4] == b"\x28\xb5\x2f\xfd" else "json"
    if kind == "zstd":
        if ZSTD is None:
            raise RuntimeError("zstd CLI not found; cannot decode Zed thread (brew install zstd)")
        payload = zcat(raw)
    elif kind == "json":
        payload = raw
    else:
        raise ValueError("unsupported Zed data_type %r" % data_type)
    if not payload.strip():
        return {}
    doc = json.loads(payload.decode("utf-8", "replace"))
    if not isinstance(doc, dict):
        raise ValueError("Zed thread payload is not a JSON object")
    return doc


# --------------------------------------------------------------------------- enum helpers
def _content_items(content):
    if isinstance(content, str):
        return [content] if content.strip() else []
    if isinstance(content, (list, tuple)):
        return list(content)
    return []


def _user_blocks(content, ir):
    blocks = []
    for item in _content_items(content):
        if isinstance(item, str):
            if item.strip():
                blocks.append(text_block(item))
            continue
        if not isinstance(item, dict):
            continue
        if "Text" in item:
            text = item.get("Text")
            if isinstance(text, str) and text.strip():
                blocks.append(text_block(text))
        elif "Mention" in item:
            mention = item.get("Mention") or {}
            uri = mention.get("uri") if isinstance(mention, dict) else None
            label = uri if isinstance(uri, str) else "mention"
            blocks.append(text_block("[mention] %s" % label))
        elif "Image" in item:
            blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
        elif isinstance(item.get("type"), str) and isinstance(item.get("text"), str):
            # tolerate a JSON-shaped variant ({"type":"text","text":...})
            if item["text"].strip():
                blocks.append(text_block(item["text"]))
        else:
            warn(ir, "Zed user content variant not recognized: %s" % list(item)[:3])
    return blocks


def _agent_blocks(content, ir):
    blocks = []
    for item in _content_items(content):
        if isinstance(item, str):
            if item.strip():
                blocks.append(text_block(item))
            continue
        if not isinstance(item, dict):
            continue
        if "Text" in item:
            text = item.get("Text")
            if isinstance(text, str) and text.strip():
                blocks.append(text_block(text))
        elif "Thinking" in item:
            thinking = item.get("Thinking") or {}
            text = thinking.get("text") if isinstance(thinking, dict) else None
            if isinstance(text, str) and text.strip():
                blocks.append({"type": "reasoning", "text": text})
        elif "RedactedThinking" in item:
            blocks.append({"type": "reasoning", "text": "[redacted thinking]",
                           "redacted": True})
        elif "ToolUse" in item:
            tool = item.get("ToolUse") or {}
            if not isinstance(tool, dict):
                continue
            args = tool.get("input")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            blocks.append({"type": "tool-call", "id": tool.get("id") or "",
                           "name": tool.get("name") or "tool", "arguments": args})
        elif isinstance(item.get("type"), str) and isinstance(item.get("text"), str):
            if item["text"].strip():
                blocks.append(text_block(item["text"]))
        else:
            warn(ir, "Zed agent content variant not recognized: %s" % list(item)[:3])
    return blocks


def _result_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("content", "output", "text", "result", "stdout"):
            if key in value:
                return _result_text(value[key])
        # LanguageModelToolResult may be {"Text": "..."} or {"Image": ...}
        if "Text" in value:
            return _result_text(value["Text"])
        return json.dumps(value, ensure_ascii=False)[:2000]
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and isinstance(item.get("Text"), str):
                parts.append(item["Text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else json.dumps(value, ensure_ascii=False)[:2000]
    return str(value)


def _parse_messages(doc, ir, fallback_ts):
    messages = doc.get("messages")
    if isinstance(messages, dict):
        messages = list(messages.values())
    if not isinstance(messages, list):
        warn(ir, "Zed thread has no messages list")
        return
    pending_results = []  # (call_id, name, text) flushed right after the assistant message
    for item in messages:
        if isinstance(item, str):
            if item == "Resume":
                continue
            warn(ir, "Zed message variant not recognized: %r" % item[:40])
            continue
        if not isinstance(item, dict) or len(item) != 1:
            warn(ir, "Zed message variant not recognized: %s" % str(item)[:60])
            continue
        variant, body = next(iter(item.items()))
        if variant == "User":
            content = body.get("content") if isinstance(body, dict) else body
            blocks = _user_blocks(content, ir)
            if blocks:
                add_event(ir, "user_message", fallback_ts, blocks=blocks)
        elif variant == "Agent":
            body = body if isinstance(body, dict) else {}
            blocks = _agent_blocks(body.get("content"), ir)
            if blocks:
                add_event(ir, "assistant_message", fallback_ts, blocks=blocks,
                          model=(doc.get("model") or {}).get("model") or "",
                          provider=(doc.get("model") or {}).get("provider") or "zed")
            call_names = {}
            for block in blocks:
                if block.get("type") == "tool-call" and block.get("id"):
                    call_names[block["id"]] = block.get("name") or "tool"
            results = body.get("tool_results") or {}
            if isinstance(results, dict):
                for call_id, value in results.items():
                    pending_results.append((call_id, _result_text(value), call_names.get(call_id)))
            for call_id, text, name in pending_results:
                add_event(ir, "tool_result", fallback_ts, call_id=call_id,
                          name=name or "tool", content=text, is_error=False)
            pending_results = []
        elif variant == "Resume":
            continue
        elif variant == "Compaction":
            summary = ""
            if isinstance(body, dict):
                summary = body.get("Summary") or ""
            add_event(ir, "compaction", fallback_ts, summary=summary)
            warn(ir, "Zed compaction marker imported as a compaction event")
        else:
            warn(ir, "Zed message variant not recognized: %r" % variant)


# --------------------------------------------------------------------------- list
def list_sessions(root=None):
    db = _db_path(root)
    if not db:
        return []
    rows = []
    try:
        con = _connect(db)
    except sqlite3.Error:
        return []
    try:
        cols = _columns(con)
        if "threads" not in {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}:
            return []
        extra = []
        for col in ("parent_id", "folder_paths", "folder_paths_order", "created_at"):
            extra.append(col if col in cols else "NULL AS %s" % col)
        sql = ("SELECT id, summary, updated_at, data_type, data, %s FROM threads "
               "ORDER BY updated_at DESC, id" % ", ".join(extra))
        for tid, summary, updated_at, data_type, data, parent_id, folder_paths, _order, created_at in con.execute(sql):
            doc = {}
            msg_count = 0
            try:
                doc = decode_thread_data(data_type, data)
                msgs = doc.get("messages")
                msg_count = len(msgs) if isinstance(msgs, list) else 0
            except (ValueError, RuntimeError, OSError):
                doc = {}
            title = (summary or "").strip() or (doc.get("title") or "").strip()
            rows.append({
                "source": SOURCE,
                "id": tid,
                "title": title[:120] or tid,
                "cwd": _first_folder(folder_paths),
                "created_at_ms": iso_to_ms(created_at) or iso_to_ms(updated_at),
                "updated_at_ms": iso_to_ms(updated_at) or iso_to_ms(created_at),
                "path": "%s#%s" % (db, tid),
                "lines": msg_count,
                "model": ((doc.get("model") or {}).get("model") if isinstance(doc.get("model"), dict) else "") or "",
                "archived": 0,
                "parent_id": parent_id,
                "evidence_level": "SQLITE(thousands of threads; zstd decoded via CLI)",
            })
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return rows


# --------------------------------------------------------------------------- resolve
def resolve_path(root, session=None):
    db = _db_path(root)
    if not db:
        return None
    if not session:
        rows = list_sessions(root)
        return rows[0]["path"] if rows else None
    sid = session
    if "#" in sid:
        return sid
    if sid.startswith("zed:"):
        sid = sid[4:]
    return "%s#%s" % (db, sid)


# --------------------------------------------------------------------------- load
def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    if path:
        if "#" in path:
            db_path, tid = path.rsplit("#", 1)
        elif path.endswith(".db"):
            raise ValueError("Zed session path must be '<threads.db>#<thread-id>'")
        else:
            db_path, tid = path, session
    else:
        db_path = _db_path(root)
        tid = session[4:] if isinstance(session, str) and session.startswith("zed:") else session
    if not db_path or not os.path.isfile(db_path):
        raise FileNotFoundError("Zed threads.db not found (root=%r)" % root)
    if not tid:
        raise ValueError("Zed session id is required")
    con = _connect(db_path)
    try:
        cols = _columns(con)
        extra = []
        for col in ("parent_id", "folder_paths", "created_at", "updated_at", "summary"):
            extra.append(col if col in cols else "NULL AS %s" % col)
        sql = "SELECT data_type, data, %s FROM threads WHERE id = ?" % ", ".join(extra)
        row = con.execute(sql, (tid,)).fetchone()
    except sqlite3.Error as exc:
        con.close()
        raise FileNotFoundError("Zed thread %r not readable: %s" % (tid, exc))
    finally:
        try:
            con.close()
        except sqlite3.Error:
            pass
    if not row:
        raise FileNotFoundError("Zed thread not found: %r in %s" % (tid, db_path))
    data_type, data, parent_id, folder_paths, created_at, updated_at, summary = row
    doc = decode_thread_data(data_type, data)
    cwd = _first_folder(folder_paths)
    ir = new_ir(SOURCE, tid, "%s#%s" % (db_path, tid), cwd=cwd,
                created_at_ms=iso_to_ms(created_at) or iso_to_ms(updated_at))
    updated_ms = iso_to_ms(updated_at) or iso_to_ms(doc.get("updated_at")) or ir["created_at_ms"]
    touch_ts(ir, updated_ms)
    ir["updated_at_ms"] = max(ir.get("updated_at_ms") or 0, updated_ms or 0) or ir.get("created_at_ms")
    if not ir.get("cwd"):
        ir["cwd"] = cwd or None
    model = doc.get("model") if isinstance(doc.get("model"), dict) else {}
    ir["model"] = (model.get("model") if isinstance(model, dict) else "") or ""
    ir["provider"] = (model.get("provider") if isinstance(model, dict) else "") or "zed"
    _parse_messages(doc, ir, updated_ms or ir["created_at_ms"])
    usage = doc.get("cumulative_token_usage") or doc.get("request_token_usage")
    normalized = normalize_usage(usage)
    if normalized:
        for ev in reversed(ir["events"]):
            if ev.get("kind") == "assistant_message":
                ev["usage"] = normalized
                break
    if parent_id:
        ir["parent_session_id"] = parent_id
        warn(ir, "Zed subagent/sibling thread (parent_id=%s); imported as a standalone session"
             % str(parent_id)[:32])
    finalize(ir, fallback_title=(summary or "").strip() or tid)
    if data_type and str(data_type).strip().lower() == "zstd":
        warn(ir, "Zed thread payload was zstd-compressed (decoded via zstd CLI)")
    return ir
