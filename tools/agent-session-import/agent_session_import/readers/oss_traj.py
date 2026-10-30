"""OSS trajectory reader: ``traj-session/1`` normalized capture -> IR.

OSS 采集轨迹是「API 网关/代理 request-level 录制 → 归一化管线」的会话级单 JSON，
与任何 harness 的原生 session 格式都不相同构（见 docs/oss-trajectory-inventory.md §5）。
三种 messages 编码按 ``messages_format`` 分支解析：

* ``anthropic-messages``: content blocks ``text`` / ``thinking`` / ``tool_use`` / ``tool_result``
* ``openai-responses``: items ``message`` / ``reasoning`` / ``function_call`` /
  ``function_call_output`` (also ``custom_tool_call*``)
* ``openai-chat``: ``role`` + ``content``(str|parts) + assistant ``tool_calls`` + ``role:"tool"``

``meta_data`` / 同目录 ``*.meta.json`` 中的 harness 判定证据保留在 IR ``extra`` 中。
"""
import glob
import json
import os
import re

from ..common import HOME, iso_to_ms
from ..ir import (MISSING_RESULT_TEXT, add_event, blocks_text, finalize, new_ir,
                  normalize_usage, text_block, touch_ts, warn)

DEFAULT_ROOT_CANDIDATES = (
    os.environ.get("ASI_OSS_ROOT") or "",
)


def default_root():
    """samples/batch2/oss if present, else samples/oss (search cwd and its parents)."""
    for cand in DEFAULT_ROOT_CANDIDATES:
        if cand and os.path.isdir(cand):
            return cand
    base = os.path.abspath(os.getcwd())
    for _ in range(5):
        for sub in (("samples", "batch2", "oss"), ("samples", "oss")):
            cand = os.path.join(base, *sub)
            if os.path.isdir(cand):
                return cand
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    return os.path.join(os.getcwd(), "samples", "batch2", "oss")


def _is_meta(path):
    return path.endswith(".meta.json") or path.endswith("/meta.json")


def _candidate_files(root):
    files = []
    for pattern in ("**/*.jsonl", "**/*.json", "*/*.jsonl", "*/*.json"):
        files.extend(glob.glob(os.path.join(root, pattern), recursive=("**" in pattern)))
    out = []
    seen = set()
    for path in sorted(files):
        if not os.path.isfile(path) or _is_meta(path):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        out.append(path)
    return out


def _load_doc(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    try:
        doc = json.loads(text)
    except ValueError:
        # some exports are JSONL with one session object per line: take the first valid line
        doc = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                break
            except ValueError:
                continue
        if doc is None:
            raise ValueError("not a JSON traj-session document")
    if not isinstance(doc, dict):
        raise ValueError("traj-session document is not an object")
    return doc


def _sibling_meta(path):
    base = path
    for suffix in (".jsonl", ".json"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    meta_path = base + ".meta.json"
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _first_user_text(doc):
    for msg in doc.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "human"):
            text = _content_text(content)
            if text.strip():
                return text.strip().splitlines()[0][:120]
            if isinstance(content, str) and content.strip():
                return content.strip().splitlines()[0][:120]
    return ""


def _content_text(content):
    """Flatten a message content (str or content blocks) to text (ignores tool parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict):
                if b.get("type") in ("text", "input_text", "output_text") and isinstance(b.get("text"), str):
                    out.append(b["text"])
        return "\n".join(out)
    return ""


def _content_parts_to_ir(content):
    """User/tool-result content -> IR text blocks (images degrade to placeholders)."""
    blocks = []
    if isinstance(content, str):
        if content.strip():
            blocks.append(text_block(content))
        return blocks
    for b in content or []:
        if isinstance(b, str):
            if b.strip():
                blocks.append(text_block(b))
            continue
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt in ("text", "input_text", "output_text") and isinstance(b.get("text"), str):
            if b["text"].strip():
                blocks.append(text_block(b["text"]))
        elif bt in ("image", "image_url", "input_image"):
            blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
    return blocks


def _tool_result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = _content_parts_to_ir(content)
        text = "\n".join(b.get("text") or b.get("placeholder") or "" for b in parts)
        return text or "[non-text tool result omitted]"
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


def _iso(o, key):
    return iso_to_ms(o.get(key))


# --------------------------------------------------------------------------- index
def list_sessions(root=None):
    root = os.path.expanduser(root or default_root())
    out = []
    for path in _candidate_files(root):
        try:
            doc = _load_doc(path)
        except (OSError, ValueError):
            continue
        if doc.get("schema_version") not in ("traj-session/1", "traj-session/1.0"):
            continue
        meta = _sibling_meta(path)
        md = doc.get("meta_data") or {}
        src = md.get("source") or meta.get("source") or {}
        msgs = doc.get("messages") or []
        out.append({
            "source": "oss",
            "id": doc.get("session_id") or os.path.basename(path),
            "title": _first_user_text(doc) or (doc.get("model") or "") + " / " + (doc.get("harness") or ""),
            "cwd": md.get("cwd") or None,
            "created_at_ms": _iso(doc, "created_at"),
            "updated_at_ms": _iso(doc, "updated_at") or int(os.path.getmtime(path) * 1000),
            "path": path,
            "lines": len(msgs),
            "model": doc.get("model") or "",
            "provider": doc.get("harness") or "",
            "harness": doc.get("harness") or "other",
            "harness_version": doc.get("harness_version"),
            "harness_confidence": (meta.get("source") or {}).get("harness_confidence")
                                  or md.get("harness_confidence"),
            "messages_format": doc.get("messages_format"),
            "bucket": src.get("bucket"),
            "region": src.get("region"),
            "key_prefix": src.get("key_prefix"),
        })
    out.sort(key=lambda r: (r.get("harness") or "", r.get("id") or ""))
    return out


def resolve_path(root, session=None):
    root = os.path.expanduser(root or default_root())
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        for path in _candidate_files(root):
            if os.path.basename(path).startswith(session) or session in os.path.basename(path):
                return path
        for path in _candidate_files(root):
            try:
                if _load_doc(path).get("session_id") == session:
                    return path
            except (OSError, ValueError):
                continue
    files = _candidate_files(root)
    return files[0] if files else None


# --------------------------------------------------------------------------- format branches
def _parse_anthropic(doc, ir, keep_system, warnings):
    calls = {}
    for m in doc.get("messages") or []:
        if not isinstance(m, dict):
            warnings.append("non-object message skipped")
            continue
        role = m.get("role")
        ts = iso_to_ms(m.get("timestamp")) if m.get("timestamp") else None
        content = m.get("content")
        if role in ("system", "developer"):
            if keep_system:
                text = _content_text(content)
                if text:
                    add_event(ir, "system_message", ts, text=text, origin=role)
            touch_ts(ir, ts)
            continue
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}] if isinstance(content, str) else []
        if role == "assistant":
            out_blocks = []
            for b in blocks:
                if isinstance(b, str):
                    if b.strip():
                        out_blocks.append(text_block(b))
                    continue
                if not isinstance(b, dict):
                    continue
                bt = b.get("type") or ("text" if "text" in b else None)
                if bt in ("text", "input_text", "output_text"):
                    if isinstance(b.get("text"), str) and b["text"].strip():
                        out_blocks.append(text_block(b["text"]))
                elif bt in ("thinking", "reasoning"):
                    txt = b.get("thinking") or b.get("text") or ""
                    if txt.strip():
                        out_blocks.append({"type": "reasoning", "text": txt})
                elif bt in ("tool_use", "tool_call"):
                    cid = b.get("id") or b.get("tool_use_id") or ""
                    args = b.get("input", b.get("arguments"))
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    calls[cid] = b.get("name") or "tool"
                    out_blocks.append({"type": "tool-call", "id": cid,
                                       "name": b.get("name") or "tool", "arguments": args})
                elif bt in ("image", "image_url"):
                    out_blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
            if out_blocks:
                add_event(ir, "assistant_message", ts, blocks=out_blocks,
                          model=doc.get("model") or "", provider=doc.get("harness") or "oss")
                touch_ts(ir, ts)
        elif role in ("user", "human", "tool"):
            user_blocks = []
            for b in blocks:
                if isinstance(b, str):
                    if b.strip():
                        user_blocks.append(text_block(b))
                    continue
                if not isinstance(b, dict):
                    continue
                bt = b.get("type") or ("text" if "text" in b else None)
                if bt == "tool_result":
                    cid = b.get("tool_use_id") or b.get("tool_call_id") or ""
                    add_event(ir, "tool_result", ts, call_id=cid,
                              name=calls.get(cid) or b.get("name") or "tool",
                              content=_tool_result_text(b),
                              is_error=bool(b.get("is_error")))
                elif bt in ("text", "input_text", "output_text"):
                    if isinstance(b.get("text"), str) and b["text"].strip():
                        user_blocks.append(text_block(b["text"]))
                elif bt in ("image", "image_url"):
                    user_blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
            if user_blocks:
                add_event(ir, "user_message", ts, blocks=user_blocks)
                touch_ts(ir, ts)
        else:
            warnings.append("unknown anthropic role skipped: %r" % (role,))


def _parse_openai_responses(doc, ir, keep_system, warnings):
    calls = {}
    pending = []
    pending_ts = [None]

    def flush():
        if not pending:
            pending_ts[0] = None
            return
        add_event(ir, "assistant_message", pending_ts[0], blocks=list(pending),
                  model=doc.get("model") or "", provider=doc.get("harness") or "oss")
        pending.clear()
        pending_ts[0] = None

    def push(ts, block):
        if pending_ts[0] is None:
            pending_ts[0] = ts
        pending.append(block)

    for item in doc.get("messages") or []:
        if not isinstance(item, dict):
            warnings.append("non-object item skipped")
            continue
        itype = item.get("type")
        ts = iso_to_ms(item.get("timestamp")) if item.get("timestamp") else None
        if itype == "message" or (itype is None and "role" in item):
            role = item.get("role")
            texts = _content_parts_to_ir(item.get("content"))
            if role == "assistant":
                for b in texts:
                    push(ts, b)
            elif role in ("user", "human"):
                flush()
                if texts:
                    add_event(ir, "user_message", ts, blocks=texts)
            elif role in ("developer", "system"):
                if keep_system:
                    flush()
                    text = "\n".join(b.get("text") or "" for b in texts if b.get("type") == "text")
                    if text:
                        add_event(ir, "system_message", ts, text=text, origin=role)
            else:
                warnings.append("unknown responses message role skipped: %r" % (role,))
        elif itype in ("reasoning",):
            txt = ""
            for part in item.get("summary") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    txt += part["text"]
            for part in item.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    txt += part["text"]
            if txt.strip():
                push(ts, {"type": "reasoning", "text": txt})
        elif itype in ("function_call", "custom_tool_call"):
            cid = item.get("call_id") or item.get("id") or ""
            name = item.get("name") or "tool"
            args = item.get("arguments", item.get("input"))
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            calls[cid] = name
            push(ts, {"type": "tool-call", "id": cid, "name": name, "arguments": args})
        elif itype in ("function_call_output", "custom_tool_call_output"):
            flush()
            cid = item.get("call_id") or ""
            out = item.get("output", item.get("content"))
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False) if out is not None else ""
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or item.get("name") or "tool",
                      content=out, is_error=False)
        elif itype in ("web_search_call",):
            cid = item.get("id") or ""
            name = "web_search"
            calls[cid] = name
            push(ts, {"type": "tool-call", "id": cid, "name": name,
                      "arguments": json.dumps(item.get("action") or {}, ensure_ascii=False)})
        else:
            warnings.append("unsupported responses item skipped: %r" % (itype,))
        touch_ts(ir, ts)
    flush()


def _parse_openai_chat(doc, ir, keep_system, warnings):
    calls = {}
    for msg in doc.get("messages") or []:
        if not isinstance(msg, dict):
            warnings.append("non-object chat message skipped")
            continue
        role = msg.get("role")
        ts = iso_to_ms(msg.get("timestamp")) if msg.get("timestamp") else None
        content = msg.get("content")
        if role in ("system", "developer"):
            if keep_system:
                text = _content_text(content)
                if text:
                    add_event(ir, "system_message", ts, text=text, origin=role)
        elif role == "user":
            blocks = _content_parts_to_ir(content)
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif role == "assistant":
            blocks = _content_parts_to_ir(content)
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                cid = (tc or {}).get("id") or ""
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                calls[cid] = fn.get("name") or "tool"
                blocks.append({"type": "tool-call", "id": cid,
                               "name": fn.get("name") or "tool", "arguments": args})
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=doc.get("model") or "", provider=doc.get("harness") or "oss")
        elif role == "tool":
            cid = msg.get("tool_call_id") or ""
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or msg.get("name") or "tool",
                      content=_content_text(content), is_error=False)
        else:
            warnings.append("unknown chat role skipped: %r" % (role,))
        touch_ts(ir, ts)


_PARSERS = {
    "anthropic-messages": _parse_anthropic,
    "openai-responses": _parse_openai_responses,
    "openai-chat": _parse_openai_chat,
}


# --------------------------------------------------------------------------- convert
def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or default_root())
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("oss traj-session not found for session=%r root=%s" % (session, root))
    try:
        doc = _load_doc(path)
    except ValueError as exc:
        raise ValueError("bad oss traj-session file %s: %s" % (path, exc))
    if doc.get("schema_version") not in ("traj-session/1", "traj-session/1.0"):
        raise ValueError("not a traj-session/1 document: %r" % (doc.get("schema_version"),))

    sid = doc.get("session_id") or os.path.basename(path)
    ir = new_ir("oss", sid, path)
    ir["model"] = doc.get("model") or ""
    ir["provider"] = doc.get("harness") or "oss"
    created = iso_to_ms(doc.get("created_at"))
    ir["created_at_ms"] = created
    updated = iso_to_ms(doc.get("updated_at")) or created
    ir["updated_at_ms"] = updated or created

    fmt = doc.get("messages_format") or "anthropic-messages"
    parser = _PARSERS.get(fmt)
    warnings = ir["warnings"]
    if parser is None:
        warnings.append("unknown messages_format %r, fallback to anthropic-messages" % (fmt,))
        parser = _parse_anthropic
    parser(doc, ir, keep_system, warnings)

    # system prompt (separate field) is the canonical system text for this source
    sp = doc.get("system_prompt")
    if keep_system and sp is not None:
        if isinstance(sp, str):
            sp_text = sp
        else:
            sp_text = _content_text(sp)
        if sp_text.strip():
            ir["system_prompt"] = sp_text

    meta = _sibling_meta(path)
    md = doc.get("meta_data") or {}
    src = md.get("source") or meta.get("source") or {}
    usage_raw = doc.get("usage")
    ir["source_usage"] = usage_raw
    usage = normalize_usage(usage_raw)
    if usage:
        for ev in reversed(ir["events"]):
            if ev.get("kind") == "assistant_message":
                ev["usage"] = usage
                break
    if not ir.get("title"):
        ir["title"] = ""
    ir["extra"] = {
        "source_harness": doc.get("harness") or "other",
        "harness_version": doc.get("harness_version"),
        "harness_confidence": (meta.get("source") or {}).get("harness_confidence")
                              or md.get("harness_confidence"),
        "harness_evidence": (meta.get("source") or {}).get("harness_evidence") or [],
        "messages_format": fmt,
        "thinking_effort": doc.get("thinking_effort"),
        "model": doc.get("model"),
        "session_id": sid,
        "schema_version": doc.get("schema_version"),
        "bucket": src.get("bucket"),
        "region": src.get("region"),
        "key_prefix": src.get("key_prefix"),
        "supplier": src.get("supplier"),
        "family": src.get("family"),
        "usage_scope": md.get("usage_scope"),
        "quality": md.get("quality"),
        "request_count": md.get("request_count"),
        "tool_calls_meta": md.get("tool_calls"),
        "meta_path": meta.get("session_key"),
    }
    if not doc.get("messages"):
        warnings.append("session has no messages")

    # captured sessions can repeat the cumulative prefix of a conversation across API calls
    # (quality flag ``reconstructed_requests`` / naive merge).  Collapse consecutive duplicate
    # messages and duplicate tool_result rows for the same call id.
    _dedupe_events(ir)
    title_text = _first_user_text(doc)
    finalize(ir, fallback_title=title_text or None)
    return ir


def _dedupe_events(ir):
    seen_results = set()
    out = []
    prev_fp = None
    dropped = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        if kind == "tool_result":
            cid = ev.get("call_id")
            if cid and cid in seen_results:
                dropped += 1
                continue
            if cid:
                seen_results.add(cid)
        if kind in ("assistant_message", "user_message"):
            fp = (kind, json.dumps(ev.get("blocks"), sort_keys=True, ensure_ascii=False))
            if fp == prev_fp:
                dropped += 1
                continue
            prev_fp = fp
        else:
            prev_fp = None
        out.append(ev)
    if dropped:
        ir["events"] = out
        ir.setdefault("warnings", []).append("deduplicated %d repeated capture row(s)" % dropped)
