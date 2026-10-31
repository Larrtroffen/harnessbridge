"""External-fixture native-format loaders (``research/external/fixtures/<harness>/``).

These adapters are **additive**: the batch3/batch4/batch5 readers keep owning their
original sample roots; when an *explicit* root points at an external-fixture
harness directory, discovery falls back to this module and formats that the batch
readers did not implement are loaded here.

Covers formats missing from the batch readers:
* Antigravity native SQLite ``steps(idx, step_payload)`` where each payload is a
  ``gemini_coder.Step`` protobuf (subset decoding, field numbers mirroring
  ``spacering-net/codeg`` ``src-tauri/src/parsers/antigravity.rs``, Apache-2.0).
* OpenHands Harbor trajectory export (JSON array of
  ``{id,timestamp,source,message,action,observation,cause}`` records).
* Mistral Vibe 2.x directory layout (``meta.json`` + ``messages.jsonl``; verified
  from ``mistralai/mistral-vibe`` ``vibe/core/session/*`` and
  ``tests/stubs/historical_session.py``).
* Cline-family task files (``api_conversation_history.json`` /
  ``<id>.messages.json``) as found in flat external fixture directories.
* OpenCode legacy ``storage/`` JSON tree and ``sqlite_v2`` JSON dumps.

All loaders return the shared IR. Evidence level is decided by the caller; this
module only exposes ``FORMAT_NOTES``.
"""
import glob
import json
import os
import sqlite3

from ..common import iso_to_ms
from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts

# Formats this module implements (per source).
FORMAT_NOTES = {
    "antigravity": "native-sqlite+gemini_coder.Step-protobuf(subset)",
    "openhands": "harbor-trajectory-export",
    "vibe": "vibe-2.x-dir(meta.json+messages.jsonl)",
    "opencode": "opencode-legacy-storage-tree / sqlite_v2-json",
    "cline": "cline-family-task-json",
    "roo": "cline-family-task-json",
    "kilo-code": "cline-family-task-json",
}


def workspace_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def external_root(source):
    env = os.environ.get("ASI_EXTERNAL_FIXTURES")
    base = env or os.path.join(workspace_root(), "research", "external", "fixtures")
    cand = os.path.join(base, source)
    return cand if os.path.isdir(cand) else None


def is_external_root(root, source):
    """True when an explicit root is the external-fixture harness directory."""
    if not root or not os.path.isdir(root):
        return False
    norm = os.path.normcase(os.path.abspath(os.path.expanduser(root)))
    ext = external_root(source)
    if ext and norm == os.path.normcase(os.path.abspath(ext)):
        return True
    return os.sep + os.path.join("research", "external", "fixtures") + os.sep in norm


# --------------------------------------------------------------------------- io helpers
def _read_lines(path):
    rows, bad = [], 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows, bad


def _read_json(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _finish(ir, source, path, fmt, **extra):
    ir.setdefault("extra", {}).update({
        "external_fixture": True,
        "fixture_path": path,
        "source_format": fmt,
    })
    ir["extra"].update(extra)
    finalize(ir)
    return ir


def _blocks_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    out.append(b["text"])
                elif isinstance(b.get("content"), str):
                    out.append(b["content"])
        return "\n".join(out)
    if isinstance(content, dict):
        for key in ("text", "content", "output", "data"):
            if isinstance(content.get(key), str):
                return content[key]
    return ""


def _first_user_title(ir):
    for ev in ir["events"]:
        if ev.get("kind") == "user_message":
            text = "".join(b.get("text") or "" for b in ev.get("blocks") or []
                           if isinstance(b, dict))
            if text.strip():
                return text.strip().splitlines()[0][:80]
    return ""


# --------------------------------------------------------------------------- discovery
_JSONL = ("**/*.jsonl",)
_JSON = ("**/*.json",)
_DB = ("**/*.db", "**/*.sqlite")

# Per-source discovery: (patterns, filename filter, preferred names in order)
DISCOVERY = {
    "qwen": (_JSONL, lambda p: os.path.basename(p) not in ("system_telemetry.jsonl",)
             and not os.path.basename(p).startswith("generated-"), ()),
    "copilot": (_JSONL, lambda p: os.path.basename(p) not in ("SOURCE.md",)
                and not os.path.basename(p).endswith("-attrs-map.jsonl"), ()),
    "roo": (("**/*api_conversation_history.json", "**/*.messages.json"),
            lambda p: "constructed/README" not in p.replace(os.sep, "/"), ("api_conversation_history.json",)),
    "cline": (("**/*.messages.json", "**/cli_tool/*.messages.json"),
              lambda p: os.path.basename(p) != "SOURCE.md", ("",)),
    "kilo-code": (("**/*.messages.json", "**/api_conversation_history.json"),
                  lambda p: os.path.basename(p) != "SOURCE.md", ("",)),
    "kiro": (("**/sessions/cli/*.jsonl", "**/sessions/**/session.jsonl"),
             lambda p: True, ("session.jsonl",)),
    "antigravity": (_JSONL + _DB, lambda p: True, ("cli_small.jsonl",)),
    "grok": (("**/chat_history.jsonl",), lambda p: True, ("chat_history.jsonl",)),
    "fx": (("**/sessions/**/session.json", "**/schema4/session.json"),
           lambda p: True, ("session.json",)),
    "openhands": (("**/*trajectory*.json", "**/base_state.json"),
                  lambda p: True, ("trajectory", "base_state")),
    "mini-swe-agent": (("**/*trajectory*.json",), lambda p: True, ("trajectory",)),
    "codebuddy": (("**/*.jsonl",), lambda p: os.path.basename(p) not in ("SOURCE.md",), ()),
    "kimi": (("**/assistant_tools.jsonl", "**/wire.jsonl", "**/generated-kimi-wire.jsonl"),
             lambda p: True, ("assistant_tools", "wire")),
    "openclaw": (("**/large.jsonl", "**/schema_drift.jsonl", "**/*.jsonl"),
                 lambda p: os.path.basename(p) not in ("sessions.json",), ()),
    "devin": (("**/sessions.db", "**/schema_drift.json"), lambda p: True, ("sessions.db",)),
    "continue": (("**/sessions/*.json",), lambda p: os.path.basename(p) != "sessions.json", ()),
    "crush": (_DB, lambda p: True, ()),
    "goose": (_DB, lambda p: True, ("sessions.db",)),
    "junie": (("**/events.jsonl",), lambda p: True, ("events.jsonl",)),
    "codebuff": (("**/chat-messages.json",), lambda p: True, ("chat-messages.json",)),
    "vibe": (("**/logs/session/session_*.json", "**/meta.json"),
             lambda p: True, ("session_", "meta.json")),
    "opencode": (("**/sqlite_v2/session_v2/*.json", "**/storage_legacy/session/*/*.json",
                  "**/storage_v2/session/*/*.json"),
                 lambda p: True, ("ses_",)),
    "hermes": (("**/state.db", "**/*.json"), lambda p: True, ("state.db",)),
}


def files(source, root=None):
    """Discover fixture files for ``source`` under an explicit/external root."""
    spec = DISCOVERY.get(source)
    root = os.path.expanduser(root or external_root(source) or "")
    if not root or not os.path.isdir(root):
        return []
    patterns, flt, preferred = spec if spec else (("**/*",), lambda p: True, ())
    found = []
    for pattern in patterns:
        found.extend(glob.glob(os.path.join(root, pattern), recursive=True))
    out, seen = [], set()
    for path in found:
        if not os.path.isfile(path) or not flt(path):
            continue
        key = os.path.normcase(os.path.realpath(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    def rank(p):
        base = os.path.basename(p)
        for i, name in enumerate(preferred):
            if name and (name in base):
                return (i, base)
        return (len(preferred), base)
    out.sort(key=rank)
    return out


# --------------------------------------------------------------------------- antigravity
def _varint(buf, pos):
    shift = result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _pb_fields(buf):
    """Yield (field_number, wire_type, value) for a protobuf message."""
    pos = 0
    out = []
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            val, pos = _varint(buf, pos)
        elif wire == 1:
            val, pos = buf[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = _varint(buf, pos)
            val, pos = buf[pos:pos + length], pos + length
        elif wire == 5:
            val, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError("unsupported wire type %d" % wire)
        out.append((field, wire, val))
    return out


def _pb_str(buf):
    return buf.decode("utf-8", "replace") if isinstance(buf, (bytes, bytearray)) else str(buf)


def _pb_msg(buf):
    try:
        return {f: v for f, w, v in _pb_fields(buf) if w == 2}
    except ValueError:
        return {}


def _pb_int(val):
    return val if isinstance(val, int) else 0


def _ag_timestamp(buf):
    fields = {f: v for f, w, v in _pb_fields(buf)}
    return _pb_int(fields.get(1, 0)) * 1000 + _pb_int(fields.get(2, 0)) // 1000000


def _ag_tool_call(buf):
    f = _pb_msg(buf)
    return {"id": _pb_str(f.get(1, b"")), "name": _pb_str(f.get(2, b"")),
            "arguments": _pb_str(f.get(3, b""))}


def _ag_tool_meta(step_fields):
    md = step_fields.get(5)
    if not md:
        return None
    md_fields = {f: v for f, w, v in _pb_fields(md)}
    tc = md_fields.get(4)
    if not tc:
        return None
    call = _ag_tool_call(tc)
    ts = md_fields.get(1)
    created = _ag_timestamp(ts) if ts else None
    return {"call": call, "created_at": created}


def _ag_step_tool_result(step_fields):
    """Return (kind, content, is_error) for tool-observation arms."""
    status = _pb_int(step_fields.get(4, 0))
    is_error = status == 7
    if 28 in step_fields:  # run_command
        f = _pb_msg(step_fields[28])
        out = _pb_msg(f.get(21, b"")) if f.get(21) else {}
        text = _pb_str(out.get(1)) or _pb_str(f.get(4)) or _pb_str(f.get(5))
        cmd = _pb_str(f.get(23)) or _pb_str(f.get(1))
        return "run_command", json.dumps({"command": cmd, "exit_code": _pb_int(f.get(6, 0)),
                                          "output": text}, ensure_ascii=False), is_error
    if 14 in step_fields:  # view_file
        f = _pb_msg(step_fields[14])
        return "view_file", json.dumps({"path": _pb_str(f.get(1)), "content": _pb_str(f.get(4))},
                                       ensure_ascii=False), is_error
    if 15 in step_fields:  # list_directory
        f = _pb_msg(step_fields[15])
        children = [_pb_str(_pb_msg(x).get(1, b"")) for x in
                    [v for k, w, v in _pb_fields(step_fields[15]) if k == 2 and w == 2]]
        return "list_directory", json.dumps({"path": _pb_str(f.get(1)), "children": children},
                                            ensure_ascii=False), is_error
    if 13 in step_fields:  # grep_search
        f = _pb_msg(step_fields[13])
        return "grep_search", json.dumps({"query": _pb_str(f.get(1)),
                                          "output": _pb_str(f.get(3))}, ensure_ascii=False), is_error
    if 23 in step_fields:  # write_to_file
        f = _pb_msg(step_fields[23])
        return "write_to_file", json.dumps({"path": _pb_str(f.get(1))}, ensure_ascii=False), is_error
    if 47 in step_fields:  # mcp_tool
        f = _pb_msg(step_fields[47])
        return "mcp_tool", json.dumps({k: _pb_str(v) for k, v in f.items()
                                       if isinstance(v, (bytes, bytearray))}, ensure_ascii=False), is_error
    return None


def load_antigravity_db(path, keep_system=False):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("?", "%3F"), uri=True)
    con.row_factory = sqlite3.Row
    try:
        try:
            rows = [dict(r) for r in con.execute("SELECT idx, step_payload FROM steps ORDER BY idx")]
        except sqlite3.Error:
            rows = []  # brand-new sessions pre-create the db empty
    finally:
        con.close()
    ir = new_ir("antigravity", os.path.basename(path)[:-3], path)
    calls = {}
    user_texts = []
    for row in rows:
        payload = row.get("step_payload")
        if not payload:
            continue
        try:
            fields = {f: v for f, w, v in _pb_fields(bytes(payload))}
        except (ValueError, TypeError):
            ir["warnings"].append("antigravity:pb-decode-failed@%s" % row.get("idx"))
            continue
        meta = _ag_tool_meta(fields)
        ts = (meta or {}).get("created_at")
        if fields.get(5):
            md = {f: v for f, w, v in _pb_fields(fields[5])}
            ts = _ag_timestamp(md[1]) if md.get(1) else ts
        if 19 in fields:  # user_input
            u = _pb_msg(fields[19])
            text = _pb_str(u.get(1)) or _pb_str(u.get(2))
            if not text:
                items = [_pb_str(_pb_msg(x).get(1, b"")) for x in
                         [v for k, w, v in _pb_fields(fields[19]) if k == 3 and w == 2]]
                text = "\n".join(items)
            if text.strip():
                user_texts.append(text)
                add_event(ir, "user_message", ts, blocks=[text_block(text)])
                touch_ts(ir, ts)
        elif 20 in fields:  # planner_response
            p = _pb_msg(fields[20])
            blocks = []
            thinking = _pb_str(p.get(3))
            if thinking.strip() and thinking != "...":
                blocks.append({"type": "reasoning", "text": thinking})
            response = _pb_str(p.get(1))
            if response.strip():
                blocks.append(text_block(response))
            for raw in [v for k, w, v in _pb_fields(fields[20]) if k == 7 and w == 2]:
                tc = _ag_tool_call(raw)
                calls[tc["id"]] = tc["name"]
                blocks.append({"type": "tool-call", "id": tc["id"], "name": tc["name"],
                               "arguments": tc["arguments"] or "{}"})
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model="", provider="antigravity")
                touch_ts(ir, ts)
        else:
            result = _ag_step_tool_result(fields)
            if result:
                kind, content, is_error = result
                call_id = (meta or {}).get("call", {}).get("id") or ""
                name = (meta or {}).get("call", {}).get("name") or kind
                add_event(ir, "tool_result", ts, call_id=call_id, name=name,
                          content=content, is_error=is_error)
                touch_ts(ir, ts)
    if not ir["events"]:
        ir["warnings"].append("antigravity:empty-steps")
    if user_texts and not ir["title"]:
        ir["title"] = user_texts[0].strip().splitlines()[0][:80]
    # cwd and mode come from the sibling .meta sidecar
    meta_path = os.path.splitext(path)[0] + ".meta"
    if os.path.isfile(meta_path):
        try:
            meta = _read_json(meta_path)
            ir["cwd"] = meta.get("cwd")
            ir["extra_mode_id"] = meta.get("mode_id")
        except ValueError:
            ir["warnings"].append("antigravity:meta-unreadable")
    ir["lossy"] = ["antigravity:protobuf-subset(no images/links/unknown-arms)"]
    return _finish(ir, "antigravity", path, FORMAT_NOTES["antigravity"])


# --------------------------------------------------------------------------- openhands
def load_openhands_harbor(path, keep_system=False):
    doc = _read_json(path)
    records = doc if isinstance(doc, list) else doc.get("steps") or doc.get("trajectory") or []
    ir = new_ir("openhands", os.path.basename(path), path)
    calls = {}
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        ts = iso_to_ms(rec.get("timestamp")) or (i * 1000)
        source = rec.get("source") or ""
        message = rec.get("message")
        action = rec.get("action")
        observation = rec.get("observation")
        args = rec.get("args") if isinstance(rec.get("args"), dict) else {}
        cause = rec.get("cause")
        call_id = ("oh-%d" % rec.get("id")) if rec.get("id") is not None else ("oh-%d" % i)
        action_name = action if isinstance(action, str) else (
            (action or {}).get("action") if isinstance(action, dict) else None)
        obs_name = observation if isinstance(observation, str) else (
            (observation or {}).get("observation") if isinstance(observation, dict) else None)
        if message and isinstance(message, str):
            text = message
            if action_name == "system":
                if keep_system:
                    add_event(ir, "system_message", ts, text=text, origin="openhands-system")
            elif source in ("agent", "assistant"):
                add_event(ir, "assistant_message", ts, blocks=[text_block(text)],
                          model="", provider="openhands")
            elif source == "user":
                add_event(ir, "user_message", ts, blocks=[text_block(text)])
        if action_name and action_name not in ("system", "message", "recall", "finish"):
            name = action_name
            call_args = {"message": message or ""} if not args else args
            calls[call_id] = name
            add_event(ir, "assistant_message", ts, blocks=[{
                "type": "tool-call", "id": call_id, "name": name,
                "arguments": json.dumps(call_args, ensure_ascii=False)}],
                model="", provider="openhands")
        if obs_name:
            content = args.get("content") or args.get("output") or args.get("observation")
            if content is None:
                content = message or ""
            if isinstance(content, list):
                content = "\n".join(str(c.get("text") or c) if isinstance(c, dict) else str(c)
                                    for c in content)
            elif not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            add_event(ir, "tool_result", ts, call_id=call_id,
                      name=calls.get(call_id) or obs_name, content=content,
                      is_error=bool(rec.get("error")))
        touch_ts(ir, ts)
    if not ir["events"]:
        ir["warnings"].append("openhands:no-records")
    ir["title"] = _first_user_title(ir) or "OpenHands trajectory"
    ir["warnings"].append("openhands:harbor-real-example-not-native-store")
    return _finish(ir, "openhands", path, FORMAT_NOTES["openhands"])


# --------------------------------------------------------------------------- vibe 2.x
def load_vibe_dir(path, keep_system=False):
    d = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    meta_path = os.path.join(d, "meta.json")
    msgs_path = os.path.join(d, "messages.jsonl")
    if not os.path.isfile(msgs_path) and os.path.isdir(path):
        for sub in sorted(glob.glob(os.path.join(str(path), "**", "messages.jsonl"), recursive=True)):
            d = os.path.dirname(sub)
            meta_path = os.path.join(d, "meta.json")
            msgs_path = sub
            break
    if os.path.isfile(path) and path.endswith(".json") and not os.path.isfile(msgs_path):
        # a direct legacy single-file session: let the batch5 loader handle it
        raise ValueError("not a vibe 2.x directory")
    meta = _read_json(meta_path) if os.path.isfile(meta_path) else {}
    ir = new_ir("vibe", str(meta.get("session_id") or os.path.basename(d)), msgs_path)
    ir["cwd"] = (meta.get("environment") or {}).get("working_directory")
    ir["created_at_ms"] = iso_to_ms(meta.get("start_time")) or 0
    ir["updated_at_ms"] = iso_to_ms(meta.get("end_time")) or ir["created_at_ms"]
    active = (meta.get("config") or {}).get("active_model")
    if active:
        ir["model"] = str(active)
    calls = {}
    rows, bad = _read_lines(msgs_path)
    for row in rows:
        role = row.get("role")
        ts = None
        if isinstance(row.get("timestamp"), (int, float)):
            ts = int(row["timestamp"])
        if ts is None:
            ts = ir["created_at_ms"]
        blocks = []
        content = row.get("content")
        if isinstance(content, str) and content.strip():
            blocks.append(text_block(content))
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict):
                    if b.get("type") in ("text",) and b.get("text"):
                        blocks.append(text_block(b["text"]))
                    elif b.get("type") in ("thinking", "reasoning") and b.get("text"):
                        blocks.append({"type": "reasoning", "text": b["text"]})
        reasoning = row.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip() and not any(
                b.get("type") == "reasoning" for b in blocks):
            blocks.insert(0, {"type": "reasoning", "text": reasoning})
        for tc in row.get("tool_calls") or []:
            cid = tc.get("id") or ""
            args = tc.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            calls[cid] = tc.get("name") or "tool"
            blocks.append({"type": "tool-call", "id": cid, "name": tc.get("name") or "tool",
                           "arguments": args})
        if role == "user":
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif role == "assistant":
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=ir.get("model") or "", provider="vibe")
        elif role in ("tool", "toolResult", "tool_result"):
            content = row.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False) if content is not None else ""
            add_event(ir, "tool_result", ts, call_id=row.get("tool_call_id") or "",
                      name=row.get("name") or calls.get(row.get("tool_call_id")) or "tool",
                      content=content, is_error=False)
        touch_ts(ir, ts)
    if not ir["events"]:
        ir["warnings"].append("vibe:no-messages")
    return _finish(ir, "vibe", path, FORMAT_NOTES["vibe"])


# --------------------------------------------------------------------------- cline family
def _cline_blocks(blocks, ir, calls, ts):
    """Emit one cline-family message's content; user blocks may be tool results."""
    out = []
    text_parts = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text":
            if (b.get("text") or "").strip():
                text_parts.append(b["text"])
        elif btype == "thinking":
            txt = b.get("thinking") or b.get("text") or ""
            if txt.strip():
                out.append({"type": "reasoning", "text": txt})
        elif btype in ("tool_use", "tool_call"):
            cid = b.get("id") or b.get("tool_use_id") or ""
            name = b.get("name") or "tool"
            args = b.get("input", b.get("arguments"))
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            calls[cid] = name
            out.append({"type": "tool-call", "id": cid, "name": name, "arguments": args})
        elif btype in ("tool_result", "tool_result_block"):
            cid = b.get("tool_use_id") or b.get("id") or ""
            content = b.get("content")
            if isinstance(content, list):
                content = "\n".join(str(c.get("text") or c) if isinstance(c, dict) else str(c)
                                    for c in content)
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or "tool", content=content if isinstance(content, str)
                      else json.dumps(content, ensure_ascii=False), is_error=bool(b.get("is_error")))
    if text_parts:
        out.insert(0, text_block("\n".join(text_parts)))
    return out


def load_cline_task(path, source="cline", keep_system=False):
    base = os.path.basename(path)
    d = os.path.dirname(os.path.abspath(path))
    meta = {}
    meta_candidates = [os.path.join(d, "task_metadata.json")]
    for cand in sorted(glob.glob(os.path.join(workspace_root(), "research", "external",
                                               "fixtures", source, "**", "task_metadata.json"),
                                 recursive=True)):
        meta_candidates.append(cand)
    for cand in meta_candidates:
        if os.path.isfile(cand):
            try:
                meta = _read_json(cand)
                break
            except ValueError:
                pass
    doc = _read_json(path)
    if isinstance(doc, dict):
        messages = doc.get("messages") or doc.get("apiConversationHistory") or []
        uid = (doc.get("sessionId") or doc.get("taskId") or meta.get("taskId")
               or os.path.basename(d))
        model = ((doc.get("modelInfo") or {}).get("id") if isinstance(doc.get("modelInfo"), dict) else None) \
            or doc.get("model") or meta.get("modelId")
    elif isinstance(doc, list):
        messages = doc
        uid = meta.get("taskId") or os.path.basename(d)
        model = meta.get("modelId")
    else:
        messages, uid, model = [], os.path.basename(d), None
    ir = new_ir(source, str(uid), path)
    ir["cwd"] = meta.get("workspace") or meta.get("cwd")
    ir["model"] = model or ""
    ir["created_at_ms"] = meta.get("createdAt") or 0
    calls = {}
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        ts = m.get("ts") or m.get("timestamp")
        if isinstance(ts, str):
            ts = iso_to_ms(ts)
        ts = int(ts) if isinstance(ts, (int, float)) else (ir["created_at_ms"] + i * 1000)
        content = m.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        built = _cline_blocks(blocks, ir, calls, ts)
        role = m.get("role")
        if role == "user":
            add_event(ir, "user_message", ts, blocks=built or [text_block("")])
        elif role == "assistant":
            add_event(ir, "assistant_message", ts, blocks=built,
                      model=ir.get("model") or "", provider=source)
        touch_ts(ir, ts)
    if not ir["title"]:
        ir["title"] = _first_user_title(ir)
    return _finish(ir, source, path, "%s-task-json" % source)


# --------------------------------------------------------------------------- opencode
def load_opencode_storage(path, keep_system=False):
    """Assemble a legacy ``storage/`` tree (or sqlite_v2 JSON dumps) into one IR."""
    norm = path.replace(os.sep, "/")
    if "/storage_legacy/session/" in norm or "/storage_v2/session/" in norm:
        session = _read_json(path)
        marker = "/storage_legacy/" if "/storage_legacy/session/" in norm else "/storage_v2/"
        root = path[:norm.index(marker)] + marker.rstrip("/")
        sid = session.get("id")
        ir = new_ir("opencode", str(sid), path)
        ir["title"] = session.get("title") or ""
        ir["cwd"] = session.get("directory") or session.get("path")
        tm = session.get("time") or {}
        ir["created_at_ms"] = int(tm.get("created") or 0)
        ir["updated_at_ms"] = int(tm.get("updated") or 0)
        msg_dir = os.path.join(root, "message", str(sid))
        part_root = os.path.join(root, "part")
        calls, messages = [], []
        for mf in sorted(glob.glob(os.path.join(msg_dir, "*.json"))):
            try:
                messages.append(_read_json(mf))
            except ValueError:
                continue
        for m in messages:
            role = m.get("role")
            mid = m.get("id")
            ts = int(((m.get("time") or {}).get("created")) or 0)
            blocks = []
            part_files = sorted(glob.glob(os.path.join(part_root, str(mid), "*.json")))
            if not part_files:
                # batch fixture keeps flat part files carrying messageID
                for pf in sorted(glob.glob(os.path.join(part_root, "*.json"))):
                    try:
                        cand = _read_json(pf)
                    except ValueError:
                        continue
                    if cand.get("messageID") == mid:
                        part_files.append(pf)
            for pf in part_files:
                try:
                    part = _read_json(pf)
                except ValueError:
                    continue
                ptype = part.get("type")
                if ptype == "text" and (part.get("text") or "").strip():
                    blocks.append(text_block(part["text"]))
                elif ptype == "tool":
                    state = part.get("state") or {}
                    blocks.append({"type": "tool-call", "id": part.get("id") or "",
                                   "name": part.get("tool") or "tool",
                                   "arguments": json.dumps(state.get("input") or {}, ensure_ascii=False)})
                    if state.get("output"):
                        add_event(ir, "tool_result", ts, call_id=part.get("id") or "",
                                  name=part.get("tool") or "tool",
                                  content=str(state.get("output")), is_error=False)
            if blocks:
                add_event(ir, "user_message" if role == "user" else "assistant_message",
                          ts, blocks=blocks, model=m.get("modelID") or "",
                          provider="opencode")
                touch_ts(ir, ts)
        if not ir["events"]:
            ir["warnings"].append("opencode:storage-tree-messages-missing")
        return _finish(ir, "opencode", path, "opencode-legacy-storage-tree")
    # sqlite_v2 JSON dumps: session_v2 file + sibling session_message/*.json
    d = os.path.dirname(os.path.abspath(path))
    if "session_v2" in d:
        from . import native_batch5_1
        return native_batch5_1.load_opencode_fixture(path)
    raise ValueError("unsupported opencode fixture: %s" % path)


# --------------------------------------------------------------------------- dispatcher
def load(path, source=None, keep_system=False):
    """Load one external fixture file/dir into IR; raises ValueError if unsupported."""
    p = os.path.expanduser(path)
    base = os.path.basename(p.rstrip(os.sep))
    norm = p.replace(os.sep, "/")
    if os.path.isdir(p):
        if os.path.isfile(os.path.join(p, "meta.json")) or "vibe" in norm:
            return load_vibe_dir(p, keep_system=keep_system)
        if "openhands" in norm:
            raise ValueError("openhands fixture must be a file")
        raise ValueError("unsupported external fixture directory: %s" % p)
    if base == "meta.json" and os.path.isfile(os.path.join(os.path.dirname(p), "messages.jsonl")):
        return load_vibe_dir(os.path.dirname(p), keep_system=keep_system)
    if source == "antigravity" and base.endswith((".db", ".sqlite")):
        return load_antigravity_db(p, keep_system=keep_system)
    if source == "openhands" and norm.endswith(".json"):
        if base == "base_state.json":
            raise ValueError("native LocalFileStore layout is handled by the batch5 loader")
        return load_openhands_harbor(p, keep_system=keep_system)
    if source in ("roo", "cline", "kilo-code"):
        return load_cline_task(p, source=source, keep_system=keep_system)
    if source == "opencode":
        return load_opencode_storage(p, keep_system=keep_system)
    raise ValueError("no external-fixture loader for %s %s" % (source, p))
