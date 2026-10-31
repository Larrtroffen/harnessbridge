"""Reader for codeg's ACP transcript fallback format.

Some agents have no public native session store (TRAE CLI, ZCode, custom ACP
agents). codeg records the raw ACP wire for them instead:
``<codeg-home>/acp-transcripts/<registry-id>/<session-id>.jsonl`` (codeg
``src-tauri/src/acp_transcript.rs``). This reader reads that layout so
``asi list/convert --from trae|zcode`` can recover the conversation when the
user has codeg installed.

File layout (codeg, schema v1 — Apache-2.0):
    line 0: {"v":1,"kind":"header","agent":"codeg-trae-cli","session_id":"…",
             "cwd":"/repo","started_at_ms":1735689600000}
    then:   {"t":1735689600100,"k":"prompt","p":[{"type":"text","text":"hi"}]}
            {"t":…,"k":"update","p":{"sessionUpdate":"agent_message_chunk", …}}
            {"t":…,"k":"turn_end","p":{"stopReason":"end_turn","usage":{…}}}

Unknown lines/updates are skipped (with a warning); this is a **reader-only**
fallback, not a native TRAE/ZCode store parser.
"""
import glob
import json
import os

from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts, warn


def transcripts_root():
    """Mirror codeg ``paths::codeg_acp_transcripts_root()``."""
    env = os.environ
    if env.get("CODEG_ACP_ROOT"):
        return os.path.expanduser(env["CODEG_ACP_ROOT"])
    if env.get("CODEG_HOME"):
        return os.path.join(os.path.expanduser(env["CODEG_HOME"]), "acp-transcripts")
    if env.get("CODEG_DATA_DIR"):
        return os.path.join(os.path.expanduser(env["CODEG_DATA_DIR"]), "acp-transcripts")
    return os.path.join(os.path.expanduser("~"), ".codeg", "acp-transcripts")


def _agent_files(root, agent_dir):
    root = os.path.expanduser(root or transcripts_root())
    agent_root = os.path.join(root, agent_dir)
    if os.path.isdir(agent_root):
        root = agent_root
    if not os.path.isdir(root):
        return []
    return sorted(f for f in glob.glob(os.path.join(root, "*.jsonl")) if os.path.isfile(f))


def _parse_lines(path):
    header, entries = None, []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("kind") == "header":
                header = obj
            elif isinstance(obj.get("k"), str):
                entries.append(obj)
    return header, entries


def _block_text(block):
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    bt = block.get("type")
    if bt in ("text", "input_text", "output_text"):
        return block.get("text") or ""
    if bt == "resource_link":
        name, uri = block.get("name") or "", block.get("uri") or ""
        return "[%s](%s)" % (name or uri, uri) if uri else name
    if bt == "resource":
        res = block.get("resource") or block
        uri = res.get("uri") or ""
        return "[%s](%s)" % (uri, uri) if uri else ""
    if bt in ("image", "audio"):
        return "[%s attachment not imported]" % bt
    return ""


def _prompt_blocks(payload):
    blocks = []
    for item in payload if isinstance(payload, list) else [payload]:
        if isinstance(item, str):
            if item.strip():
                blocks.append(text_block(item))
        elif isinstance(item, dict):
            bt = item.get("type")
            if bt == "text":
                if isinstance(item.get("text"), str) and item["text"].strip():
                    blocks.append(text_block(item["text"]))
            elif bt in ("image", "audio"):
                blocks.append({"type": "image",
                               "placeholder": "[%s attachment not imported]" % bt})
            elif bt in ("resource", "resource_link"):
                text = _block_text(item)
                if text:
                    blocks.append(text_block(text))
    return blocks


def _update_blocks(payload):
    """Return (text_blocks, tool_calls, tool_results, update_kind)."""
    if not isinstance(payload, dict):
        return [], [], [], ""
    kind = str(payload.get("sessionUpdate") or payload.get("session_update") or "")
    content = payload.get("content")
    items = content if isinstance(content, list) else [content]
    texts, results = [], []
    for item in items:
        if isinstance(item, dict):
            bt = item.get("type")
            if bt == "text":
                if isinstance(item.get("text"), str) and item["text"].strip():
                    texts.append(text_block(item["text"]))
            elif bt in ("content", "text_content"):
                inner = item.get("content")
                if isinstance(inner, dict) and inner.get("type") == "text":
                    if inner.get("text", "").strip():
                        texts.append(text_block(inner["text"]))
            elif bt in ("image", "audio"):
                texts.append({"type": "image",
                              "placeholder": "[%s attachment not imported]" % bt})
            elif bt in ("resource", "resource_link"):
                text = _block_text(item)
                if text:
                    texts.append(text_block(text))
    calls = []
    if kind == "tool_call":
        calls.append({
            "id": str(payload.get("toolCallId") or payload.get("tool_call_id") or ""),
            "name": str(payload.get("title") or payload.get("name") or "tool"),
            "arguments": json.dumps(payload.get("rawInput", payload.get("raw_input", {})),
                                    ensure_ascii=False),
        })
    if kind in ("tool_call_update", "tool_call_progress"):
        status = str(payload.get("status") or "").lower()
        if texts or status in ("completed", "failed", "error"):
            body = "\n".join(b.get("text", "") for b in texts if b.get("type") == "text")
            results.append({
                "call_id": str(payload.get("toolCallId") or payload.get("tool_call_id") or ""),
                "name": str(payload.get("title") or payload.get("name") or "tool"),
                "content": body or "[tool result content omitted]",
                "is_error": status in ("failed", "error"),
            })
    return texts, calls, results, kind


def list_sessions(root=None, agent_dir=""):
    root = os.path.expanduser(root or transcripts_root())
    out = []
    for path in _agent_files(root, agent_dir):
        header, entries = _parse_lines(path)
        if header is None and not entries:
            continue
        sid = (header or {}).get("session_id") or os.path.splitext(os.path.basename(path))[0]
        title = ""
        timestamps = []
        for e in entries:
            if e.get("k") == "prompt" and not title:
                blocks = _prompt_blocks(e.get("p"))
                text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                if text:
                    title = text.splitlines()[0][:120]
            if isinstance(e.get("t"), (int, float)):
                timestamps.append(int(e["t"]))
        started = (header or {}).get("started_at_ms")
        if isinstance(started, (int, float)):
            timestamps.append(int(started))
        out.append({
            "source": "codeg-acp",
            "id": str(sid),
            "title": title or ("%s ACP session %s" % (agent_dir, str(sid)[:8])),
            "cwd": (header or {}).get("cwd"),
            "created_at_ms": min(timestamps) if timestamps else int(os.path.getmtime(path) * 1000),
            "updated_at_ms": max(timestamps) if timestamps else int(os.path.getmtime(path) * 1000),
            "path": path,
            "lines": len(entries),
            "model": "",
        })
    out.sort(key=lambda r: (r.get("updated_at_ms") or 0, r.get("id") or ""), reverse=True)
    return out


def resolve_path(root, agent_dir, session=None):
    root = os.path.expanduser(root or transcripts_root())
    for row in list_sessions(root, agent_dir):
        if str(row.get("id")) == str(session) or os.path.basename(row.get("path") or "") == str(session):
            return row["path"]
    if session:
        cand = os.path.join(root, agent_dir, str(session) + ".jsonl")
        if os.path.isfile(cand):
            return cand
    return None


def load_session(source, agent_dir, root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or transcripts_root())
    path = path or resolve_path(root, agent_dir, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("%s ACP transcript not found for %r under %s" % (source, session, root))
    header, entries = _parse_lines(path)
    sid = (header or {}).get("session_id") or os.path.splitext(os.path.basename(path))[0]
    cwd = (header or {}).get("cwd")
    ir = new_ir(source, sid, path, cwd=cwd,
                created_at_ms=(header or {}).get("started_at_ms"))
    ir["provider"] = "%s (codeg ACP transcript fallback)" % source
    if isinstance((header or {}).get("started_at_ms"), (int, float)):
        ir["created_at_ms"] = int(header["started_at_ms"])
    pending_user, pending_assistant = [], []
    user_ts = assistant_ts = None
    last_assistant = None
    source_usage = None
    model = ""

    def flush_user():
        nonlocal pending_user, user_ts
        if pending_user:
            add_event(ir, "user_message", user_ts, blocks=pending_user)
        pending_user, user_ts = [], None

    def flush_assistant():
        nonlocal pending_assistant, assistant_ts, last_assistant
        if pending_assistant:
            add_event(ir, "assistant_message", assistant_ts, blocks=pending_assistant)
            last_assistant = ir["events"][-1]
        pending_assistant, assistant_ts = [], None

    for e in entries:
        t = e.get("t") if isinstance(e.get("t"), (int, float)) else None
        touch_ts(ir, t)
        kind = e.get("k")
        payload = e.get("p")
        if kind == "prompt":
            flush_user()
            flush_assistant()
            blocks = _prompt_blocks(payload)
            if blocks:
                add_event(ir, "user_message", t, blocks=blocks)
        elif kind == "update":
            texts, calls, results, ukind = _update_blocks(payload)
            if ukind == "user_message_chunk":
                flush_assistant()
                if user_ts is None:
                    user_ts = t
                pending_user.extend(texts)
            elif ukind == "agent_message_chunk":
                flush_user()
                if assistant_ts is None:
                    assistant_ts = t
                pending_assistant.extend(texts)
            elif ukind == "agent_thought_chunk":
                flush_user()
                if assistant_ts is None:
                    assistant_ts = t
                text = "\n".join(b.get("text", "") for b in texts if b.get("type") == "text")
                if text:
                    pending_assistant.append({"type": "reasoning", "text": text})
            elif ukind == "tool_call":
                flush_user()
                flush_assistant()
                if calls:
                    add_event(ir, "assistant_message", t,
                              blocks=[{"type": "tool-call", **calls[0]}])
                    last_assistant = ir["events"][-1]
            elif ukind in ("tool_call_update", "tool_call_progress"):
                for result in results:
                    flush_user()
                    flush_assistant()
                    add_event(ir, "tool_result", t, **result)
            elif ukind == "usage_update":
                source_usage = payload.get("usage") or source_usage
            elif ukind in ("plan", "available_commands_update", "current_mode_update",
                           "session_info_update", "config_option_update"):
                pass
            else:
                warn(ir, "unsupported ACP sessionUpdate skipped: %r" % (ukind,))
        elif kind == "turn_end":
            flush_user()
            flush_assistant()
            if isinstance(payload, dict):
                if payload.get("model"):
                    model = str(payload["model"])
                usage = normalize_usage(payload.get("usage"))
                if usage:
                    source_usage = usage
                    if last_assistant is not None:
                        last_assistant["usage"] = usage
                if payload.get("durationMs") is not None:
                    ir["extra_duration_ms"] = payload.get("durationMs")
        else:
            warn(ir, "unsupported codeg transcript entry kind: %r" % (kind,))
    flush_user()
    flush_assistant()
    if model:
        ir["model"] = model
    if source_usage:
        ir["source_usage"] = source_usage
    ir["extra"] = {
        "evidence_level": "ACP-TRANSCRIPT-FALLBACK (codeg-owned store; not a native TRAE/ZCode store)",
        "native_layout": "<codeg-home>/acp-transcripts/%s/<session-id>.jsonl" % (agent_dir,),
        "format_source": "codeg src-tauri/src/acp_transcript.rs (Apache-2.0)",
        "reader_only": True,
    }
    finalize(ir)
    return ir
