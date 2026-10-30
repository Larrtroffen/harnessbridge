"""Batch-4 readers (FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED evidence).

* wave 1 (JSON/JSONL fixtures): openclaw, kimi, grok, droid, antigravity
* wave 2 (constructed SQLite golden DBs): hermes, devin, opencode

Evidence level is never NATIVE: public fixtures are synthetic/trimmed; the wave-2 DBs are
constructed by this repo (column names partly unverified, see docs/formats/batch4-fixtures.md).
"""
import glob
import json
import os
import re
import sqlite3

from ..common import iso_to_ms
from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts

EVIDENCE = {
    "openclaw": "FIXTURE",
    "kimi": "FIXTURE",
    "grok": "FIXTURE",
    "droid": "FIXTURE",
    "antigravity": "FIXTURE-LOW",
    "hermes": "FIXTURE-CONSTRUCTED",
    "devin": "FIXTURE-CONSTRUCTED",
    "opencode": "FIXTURE-CONSTRUCTED",
}
LABELS = {
    "openclaw": "OpenClaw", "kimi": "Kimi Code", "grok": "Grok Build",
    "droid": "Factory Droid", "antigravity": "Google Antigravity",
    "hermes": "Hermes", "devin": "Devin CLI", "opencode": "OpenCode",
}
EXTRA_PATTERNS = {
    "openclaw": ("**/stage0/openclaw/*.jsonl",),
    "kimi": ("**/stage0/kimi/*.jsonl",),
    "grok": ("**/stage0/grok/chat_history.jsonl",),
    "droid": ("**/stage0/droid/*.jsonl",),
    "antigravity": ("**/stage0/antigravity/*.jsonl",),
    "hermes": ("**/stage0/hermes/*.json",),
    "devin": ("**/stage0/devin/*.json",),
    "opencode": ("**/stage0/opencode/*.json",),
}
PRIMARY = {
    "openclaw": ("agent-sessions/stage0/openclaw/small.jsonl",),
    "kimi": ("agent-sessions/stage0/kimi/small.jsonl",),
    "grok": ("agent-sessions/stage0/grok/chat_history.jsonl",),
    "droid": ("agent-sessions/stage0/droid/stream_json_small.jsonl",
              "agent-sessions/stage0/droid/session_store_schema_drift.jsonl"),
    "antigravity": ("agent-sessions/stage0/antigravity/desktop_small.jsonl",
                    "agent-sessions/stage0/antigravity/cli_schema_drift.jsonl"),
    "hermes": ("agent-sessions/stage0/hermes/small.json",),
    "devin": ("agent-sessions/stage0/devin/small.json",),
    "opencode": ("agent-sessions/stage0/opencode/001.json",
                 "agent-sessions/stage0/opencode/002.json",
                 "sessionport/tests-fixtures/opencode/storage/session/abc.json"),
}


def default_root(source):
    env = os.environ.get("ASI_BATCH4_ROOT") or os.environ.get("ASI_FIXTURES_ROOT")
    if env and os.path.isdir(env):
        return env
    base = os.path.abspath(os.getcwd())
    for _ in range(6):
        cand = os.path.join(base, "samples", "batch2", "public-fixtures")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(base)
        if base == parent:
            break
        base = parent
    return os.path.join(os.getcwd(), "samples", "batch2", "public-fixtures")


def _files(source, root):
    root = os.path.expanduser(root or default_root(source))
    if os.path.isfile(root):
        return [root]
    out, seen = [], set()
    for pattern in EXTRA_PATTERNS.get(source, ("**/*",)):
        for path in glob.glob(os.path.join(root, pattern), recursive=True):
            if not os.path.isfile(path):
                continue
            key = os.path.realpath(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    # grok needs its sibling summary.json; DB sources accept .db/.sqlite
    out.sort()
    return out


def _primary(source):
    root = default_root(source)
    return [os.path.join(root, rel) for rel in PRIMARY.get(source, ())
            if os.path.isfile(os.path.join(root, rel))]


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


def _finish(ir, source, path, extra=None):
    ir["extra"] = {
        "evidence_level": EVIDENCE[source],
        "fixture": True,
        "constructed": EVIDENCE[source] == "FIXTURE-CONSTRUCTED",
        "source_harness": LABELS[source],
        "source_format": source,
        "fixture_path": path,
    }
    if EVIDENCE[source] == "FIXTURE-CONSTRUCTED":
        ir["extra"]["constructed_note"] = (
            "constructed golden DB; column names partly unverified "
            "(docs/formats/batch4-fixtures.md §3); must not be treated as upstream fixture")
    if extra:
        ir["extra"].update(extra)
    finalize(ir)
    return ir


def _blocks_text(ev):
    return "\n".join(b.get("text") or b.get("placeholder") or "" for b in ev.get("blocks") or [])


# --------------------------------------------------------------------------- openclaw (pi family)
def _load_openclaw(path, keep_system=False):
    rows, bad = _read_lines(path)
    ir = new_ir("openclaw", os.path.basename(path)[:-6], path)
    warnings = ir["warnings"]
    header, entries = None, []
    for row in rows:
        if row.get("type") == "session":
            header = row
        elif row.get("type") == "model_change":
            ir["model"] = row.get("modelId") or ir.get("model")
            ir.setdefault("extra_provider", row.get("provider"))
        elif row.get("type") == "message":
            entries.append(row)
    if header:
        ir["source_session_id"] = header.get("id") or ir["source_session_id"]
        ir["cwd"] = header.get("cwd")
        ir["created_at_ms"] = iso_to_ms(header.get("timestamp"))
        if header.get("version") != 3:
            warnings.append("openclaw:schema-version-%r" % (header.get("version"),))
    by_id = {e.get("id"): e for e in entries if e.get("id")}
    parent = {e.get("id"): e.get("parentId") for e in entries if e.get("id")}
    child = set(p for p in parent.values() if p)
    leaves = [e for e in entries if e.get("id") and e["id"] not in child]
    leaf = max(leaves, key=lambda e: (e.get("timestamp") or "", e.get("id") or "")) if leaves else (entries[-1] if entries else None)
    chain, cur, guard = [], leaf, 0
    while cur is not None and guard < 10000:
        chain.append(cur)
        pid = cur.get("parentId")
        cur = by_id.get(pid) if pid else None
        guard += 1
    chain.reverse()
    if len(chain) < len(entries):
        # openclaw fixture uses the session id / tool-call id as parentId targets, so the
        # parent chain is not a complete node path; fall back to authoritative file order.
        chain = list(entries)
    for e in chain:
        msg = e.get("message") or {}
        role = msg.get("role")
        ts = msg.get("timestamp") if isinstance(msg.get("timestamp"), int) else iso_to_ms(e.get("timestamp"))
        if role == "user":
            blocks = [text_block(b.get("text") or "") for b in msg.get("content") or []
                      if isinstance(b, dict) and b.get("type") == "text"]
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif role == "assistant":
            blocks = []
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    blocks.append(text_block(b["text"]))
                elif b.get("type") in ("toolCall", "tool_call"):
                    args = b.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    blocks.append({"type": "tool-call", "id": b.get("id") or "",
                                   "name": b.get("name") or "tool", "arguments": args})
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=msg.get("model") or ir.get("model") or "",
                          provider=msg.get("provider") or "openclaw",
                          usage=normalize_usage(msg.get("usage")))
        elif role == "toolResult":
            content = ""
            for b in msg.get("content") or []:
                if isinstance(b, dict):
                    content = b.get("content") or b.get("text") or content
            add_event(ir, "tool_result", ts, call_id=msg.get("toolCallId") or "",
                      name=msg.get("toolName") or "tool", content=content,
                      is_error=bool(msg.get("isError")))
        touch_ts(ir, ts)
    if not ir.get("title"):
        for ev in ir["events"]:
            if ev.get("kind") == "user_message":
                text = _blocks_text(ev)
                ir["title"] = text.strip().splitlines()[0][:80] if text.strip() else ""
                break
    return _finish(ir, "openclaw", path)


# --------------------------------------------------------------------------- kimi code
def _load_kimi(path, keep_system=False):
    rows, bad = _read_lines(path)
    ir = new_ir("kimi", os.path.basename(path)[:-6], path)
    warnings = ir["warnings"]
    lossy = set()
    types = {}
    config = {}
    cwd = None
    calls = {}
    last_ts = 0
    for row in rows:
        etype = row.get("type")
        types[etype] = types.get(etype, 0) + 1
        ts = row.get("time")
        if not isinstance(ts, int):
            ts = None
        if ts:
            last_ts = ts
            touch_ts(ir, ts)
        elif etype in ("agent.message.appended", "turn.prompt"):
            ts = last_ts
            lossy.add("kimi:synthetic-time")
        if etype == "metadata":
            if row.get("protocol_version"):
                ir["extra_version"] = row["protocol_version"]
            ir["created_at_ms"] = row.get("created_at") or ir["created_at_ms"]
        elif etype == "config.update":
            config = row
            if row.get("modelAlias"):
                ir["model"] = row["modelAlias"]
        elif etype == "profile.bind":
            cwd = ((row.get("environmentDisclosure") or {}).get("cwd")) or cwd
        elif etype == "agent.message.appended":
            msg = ((row.get("message") or {}).get("message")) or {}
            meta = (row.get("message") or {}).get("meta") or {}
            role = msg.get("role")
            content = msg.get("content") or []
            if role == "user":
                blocks = [text_block(b.get("text") or "") for b in content
                          if isinstance(b, dict) and b.get("type") == "text"]
                if blocks:
                    add_event(ir, "user_message", ts, blocks=blocks)
            elif role == "assistant":
                blocks = []
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "think":
                        blocks.append({"type": "reasoning", "text": b.get("think") or ""})
                    elif b.get("type") == "text":
                        blocks.append(text_block(b.get("text") or ""))
                for tc in msg.get("toolCalls") or []:
                    cid = tc.get("id") or ""
                    args = tc.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {"_raw": args}
                    calls[cid] = tc.get("name") or "tool"
                    blocks.append({"type": "tool-call", "id": cid,
                                   "name": tc.get("name") or "tool",
                                   "arguments": json.dumps(args, ensure_ascii=False)})
                if blocks:
                    model = (meta.get("model") or {}).get("model") or ir.get("model") or ""
                    provider = (meta.get("model") or {}).get("provider") or "kimi"
                    add_event(ir, "assistant_message", ts, blocks=blocks, model=model,
                              provider=provider,
                              usage=normalize_usage(meta.get("usage")))
            elif role == "tool":
                add_event(ir, "tool_result", ts, call_id=msg.get("toolCallId") or "",
                          name=calls.get(msg.get("toolCallId")) or "tool",
                          content=msg.get("content") if isinstance(msg.get("content"), str)
                          else json.dumps(msg.get("content"), ensure_ascii=False),
                          is_error=False)
        elif etype in ("turn.prompt",):
            # fallback channel only when no agent.message.appended exists (checked later)
            pass
        elif etype in ("turn.steer", "turn.cancel", "permission.set_mode", "plugin.session_start",
                       "runtime.set_binding", "prompt.completed", "changeNotifier.snapshot",
                       "llm.request", "llm.tools_snapshot", "token_counting.measured",
                       "token_counting.turn_recorded", "context.append_message",
                       "context.append_loop_event", "agent.turn.started", "agent.turn.ended",
                       "tools.set_active_tools"):
            pass
        else:
            warnings.append("kimi:unknown-event:%s" % etype)
    appended = types.get("agent.message.appended", 0)
    if not appended:
        # fallback channel: turn.prompt + loop events
        lossy.add("kimi:fallback-channel")
        for row in rows:
            ts = row.get("time") if isinstance(row.get("time"), int) else 0
            if row.get("type") == "turn.prompt":
                text = "".join(b.get("text") or "" for b in row.get("input") or []
                               if isinstance(b, dict))
                if text:
                    add_event(ir, "user_message", ts, blocks=[text_block(text)])
            elif row.get("type") == "context.append_loop_event":
                ev = row.get("event") or {}
                et = ev.get("type")
                if et == "content.part":
                    part = ev.get("part") or {}
                    if part.get("type") == "think":
                        add_event(ir, "assistant_message", ts,
                                  blocks=[{"type": "reasoning", "text": part.get("think") or ""}],
                                  model=ir.get("model") or "", provider="kimi")
                    elif part.get("type") == "text":
                        add_event(ir, "assistant_message", ts,
                                  blocks=[text_block(part.get("text") or "")],
                                  model=ir.get("model") or "", provider="kimi")
                elif et == "tool.call":
                    cid = ev.get("toolCallId") or ""
                    calls[cid] = ev.get("name") or "tool"
                    add_event(ir, "assistant_message", ts,
                              blocks=[{"type": "tool-call", "id": cid,
                                       "name": ev.get("name") or "tool",
                                       "arguments": json.dumps(ev.get("arguments") or {}, ensure_ascii=False)}],
                              model=ir.get("model") or "", provider="kimi")
                elif et == "tool.result":
                    cid = ev.get("toolCallId") or ""
                    add_event(ir, "tool_result", ts, call_id=cid,
                              name=calls.get(cid) or "tool",
                              content=str(ev.get("content") or ""), is_error=False)
    ir["cwd"] = cwd
    if not ir.get("created_at_ms"):
        ir["created_at_ms"] = 0
    ir["lossy"] = sorted(lossy)
    ir["event_types"] = types
    if not cwd:
        warnings.append("kimi:cwd-missing")
    return _finish(ir, "kimi", path, {"event_type_counts": types,
                                      "protocol_version": ir.get("extra_version")})


# --------------------------------------------------------------------------- grok (2 files)
def _grok_summary_for(path):
    base = os.path.basename(path)
    if base == "chat_history.jsonl":
        same = os.path.join(os.path.dirname(path), "summary.json")
    else:
        same = os.path.join(os.path.dirname(os.path.dirname(path)), "summary.json")
    return _read_json(same) if os.path.isfile(same) else {}


def _load_grok(path, keep_system=False):
    summary = _grok_summary_for(path)
    info = summary.get("info") or {}
    ir = new_ir("grok", info.get("id") or os.path.basename(path), path)
    lossy = {"grok:row-ts-derived"}
    ir["cwd"] = info.get("cwd") or summary.get("git_root_dir")
    ir["title"] = (summary.get("generated_title") or summary.get("session_summary") or "")[:120]
    ir["model"] = summary.get("current_model_id") or ""
    ir["created_at_ms"] = iso_to_ms(summary.get("created_at"))
    ir["updated_at_ms"] = iso_to_ms(summary.get("updated_at") or summary.get("last_active_at"))
    rows, bad = _read_lines(path)
    calls = {}
    ts_base = ir.get("created_at_ms") or 0
    for i, row in enumerate(rows):
        t = row.get("type")
        ts = ts_base + i * 1000
        if t == "system":
            if keep_system:
                add_event(ir, "system_message", ts, text=str(row.get("content") or ""),
                          origin="grok-system")
        elif t == "user":
            blocks = [text_block(b.get("text") or "") for b in row.get("content") or []
                      if isinstance(b, dict) and b.get("type") == "text"]
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif t == "assistant":
            blocks = []
            content = row.get("content")
            if isinstance(content, str) and content.strip():
                blocks.append(text_block(content))
            for tc in row.get("tool_calls") or []:
                cid = tc.get("id") or ""
                args = tc.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {"_raw": args}
                calls[cid] = tc.get("name") or "tool"
                blocks.append({"type": "tool-call", "id": cid,
                               "name": tc.get("name") or "tool",
                               "arguments": json.dumps(args, ensure_ascii=False)})
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=row.get("model_id") or ir.get("model") or "",
                          provider="grok")
        elif t == "tool_result":
            add_event(ir, "tool_result", ts, call_id=row.get("tool_call_id") or "",
                      name=calls.get(row.get("tool_call_id")) or "tool",
                      content=str(row.get("content") or ""), is_error=False)
        touch_ts(ir, ts)
    extra = {"num_messages": summary.get("num_messages"),
             "num_chat_messages": summary.get("num_chat_messages"),
             "session_kind": summary.get("session_kind")}
    if summary.get("session_kind") == "subagent":
        ir["warnings"].append("grok:subagent-session")
    ir["lossy"] = sorted(lossy)
    return _finish(ir, "grok", path, extra)


# --------------------------------------------------------------------------- droid (two schemas)
_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def _load_droid(path, keep_system=False, keep_system_reminder=False):
    rows, bad = _read_lines(path)
    ir = new_ir("droid", os.path.basename(path)[:-6], path)
    lossy = set()
    first = rows[0].get("type") if rows else ""
    if first == "session_start":
        header = rows[0]
        ir["source_session_id"] = header.get("id") or ir["source_session_id"]
        ir["title"] = header.get("title") or ""
        ir["cwd"] = header.get("cwd")
        ir["extra_version"] = header.get("version")
        for row in rows[1:]:
            if row.get("type") != "message":
                continue
            msg = row.get("message") or {}
            role = msg.get("role")
            blocks = []
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                text = b.get("text") or ""
                if not keep_system_reminder and role == "user":
                    new = _SYSTEM_REMINDER.sub("", text).strip()
                    if new != text:
                        lossy.add("droid:embedded-system-reminder")
                    text = new
                if text.strip():
                    blocks.append(text_block(text))
            if blocks:
                add_event(ir, "user_message" if role == "user" else "assistant_message",
                          iso_to_ms(row.get("timestamp")), blocks=blocks,
                          model="", provider="droid") if role == "user" else add_event(
                    ir, "assistant_message", iso_to_ms(row.get("timestamp")), blocks=blocks,
                    model="", provider="droid")
    else:
        calls = {}
        for row in rows:
            t = row.get("type")
            ts = iso_to_ms(row.get("timestamp"))
            if t == "message":
                if row.get("role") == "user":
                    add_event(ir, "user_message", ts, blocks=[text_block(row.get("text") or "")])
                elif row.get("role") == "assistant":
                    add_event(ir, "assistant_message", ts,
                              blocks=[text_block(row.get("text") or "")],
                              model="", provider="droid")
            elif t == "tool_call":
                cid = row.get("toolCallId") or ""
                calls[cid] = row.get("toolName") or "tool"
                add_event(ir, "assistant_message", ts,
                          blocks=[{"type": "tool-call", "id": cid,
                                   "name": row.get("toolName") or "tool",
                                   "arguments": json.dumps(row.get("parameters") or {}, ensure_ascii=False)}],
                          model="", provider="droid")
            elif t == "tool_result":
                cid = row.get("toolCallId") or ""
                value = row.get("value") or {}
                add_event(ir, "tool_result", ts, call_id=cid,
                          name=calls.get(cid) or "tool",
                          content=str(value.get("stdout") or ""),
                          is_error=bool(value.get("exitCode")))
            elif t == "completion":
                add_event(ir, "assistant_message", ts,
                          blocks=[text_block(row.get("finalText") or "")],
                          model="", provider="droid")
            if row.get("session_id"):
                ir["source_session_id"] = row["session_id"]
        if not ir.get("cwd"):
            ir["warnings"].append("droid:cwd-missing")
    ir["lossy"] = sorted(lossy)
    return _finish(ir, "droid", path, {"schema": "session_store_v2" if first == "session_start" else "cli_stream_json"})


# --------------------------------------------------------------------------- antigravity (reader-only)
_USER_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
_ENVELOPE = re.compile(r"<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)>.*?</\1>", re.S)


def _load_antigravity(path, keep_system=False, keep_wrappers=False):
    rows, bad = _read_lines(path)
    ir = new_ir("antigravity", os.path.basename(path)[:-6], path)
    lossy = {"antigravity:inferred-pairing"}
    rows = sorted(rows, key=lambda r: r.get("step_index", 0))
    pending_calls = []
    tool_no = 0
    for row in rows:
        ts = iso_to_ms(row.get("created_at"))
        rtype = row.get("type")
        content = row.get("content") or ""
        if rtype == "USER_INPUT":
            if not keep_wrappers:
                m = _USER_REQUEST.search(content)
                if m:
                    content = m.group(1)
                    lossy.add("antigravity:user-envelope")
                content = _ENVELOPE.sub("", content).strip()
            if content:
                add_event(ir, "user_message", ts, blocks=[text_block(content)])
        elif rtype == "PLANNER_RESPONSE":
            blocks = []
            thinking = row.get("thinking")
            if isinstance(thinking, str) and thinking and thinking != "...":
                blocks.append({"type": "reasoning", "text": thinking})
            if isinstance(content, str) and content.strip():
                blocks.append(text_block(content))
            for tc in row.get("tool_calls") or []:
                tool_no += 1
                cid = "ant:%d:%d" % (row.get("step_index", 0), tool_no)
                pending_calls.append(cid)
                blocks.append({"type": "tool-call", "id": cid,
                               "name": tc.get("name") or "tool",
                               "arguments": json.dumps(tc.get("args") or {}, ensure_ascii=False)})
            usage = None
            if any(row.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens")):
                usage = normalize_usage({"input_tokens": row.get("input_tokens") or 0,
                                         "output_tokens": row.get("output_tokens") or 0,
                                         "cache_read_input_tokens": row.get("cache_read_tokens") or 0})
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model="", provider="antigravity", usage=usage)
        elif rtype == "GENERIC":
            if pending_calls:
                cid = pending_calls.pop(0)
                add_event(ir, "tool_result", ts, call_id=cid, name="tool",
                          content=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                          is_error=False)
            elif content:
                ir["warnings"].append("antigravity:generic-without-call")
        else:
            ir["warnings"].append("antigravity:unknown-type:%s" % rtype)
        touch_ts(ir, ts)
    ir["lossy"] = sorted(lossy)
    ir["warnings"].append("antigravity:cwd-missing")
    return _finish(ir, "antigravity", path, {"reader_only": True,
                                             "writer_blocked_reason": "native format is protobuf (.pb) with no public schema"})


# --------------------------------------------------------------------------- constructed SQLite readers
def _open_ro(path):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path).replace("?", "%3F"), uri=True)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


def _load_hermes(path, keep_system=False):
    if path.endswith(".json"):
        doc = _read_json(path)
        ir = new_ir("hermes", str(doc.get("session_id") or os.path.basename(path)), path)
        ir["cwd"] = doc.get("cwd")
        ir["model"] = doc.get("model") or ""
        ir["created_at_ms"] = iso_to_ms(doc.get("session_start"))
        ir["updated_at_ms"] = iso_to_ms(doc.get("last_updated")) or ir["created_at_ms"]
        calls = {}
        for msg in doc.get("messages") or []:
            role = msg.get("role")
            content = msg.get("content")
            blocks = []
            if isinstance(content, str) and content.strip():
                blocks = [text_block(content)]
            ts = iso_to_ms(doc.get("session_start"))
            if role == "user" and blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
            elif role == "assistant" and blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=ir["model"], provider="hermes")
            elif role == "tool":
                add_event(ir, "tool_result", ts, call_id=msg.get("tool_call_id") or "",
                          name=msg.get("tool_name") or "tool",
                          content=content if isinstance(content, str) else "", is_error=False)
        ir["lossy"] = ["hermes:json-projection-not-native"]
        return _finish(ir, "hermes", path, {"projection": True, "message_count_meta": doc.get("message_count")})
    ir = new_ir("hermes", os.path.basename(path), path)
    con = _open_ro(path)
    try:
        sessions = [dict(r) for r in con.execute("SELECT * FROM sessions")]
        messages = [dict(r) for r in con.execute("SELECT * FROM messages ORDER BY id")]
        try:
            usage_rows = [dict(r) for r in con.execute("SELECT * FROM session_model_usage")]
        except sqlite3.Error:
            usage_rows = []
    finally:
        con.close()
    lossy = {"hermes:sqlite-columns-unverified"}
    if sessions:
        s = sessions[0]
        ir["source_session_id"] = str(s.get("id") or s.get("session_id") or ir["source_session_id"])
        ir["cwd"] = s.get("cwd")
        ir["title"] = s.get("title") or ""
        ir["created_at_ms"] = int((s.get("created_at") or 0) * (1000 if (s.get("created_at") or 0) < 1e12 else 1))
    model = None
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str) and content.startswith(("[", "{")):
            try:
                content = json.loads(content)
            except ValueError:
                pass
        blocks = []
        if isinstance(content, str):
            if content.strip():
                blocks = [text_block(content)]
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                    blocks.append(text_block(b["text"]))
        if not blocks:
            continue
        ts = iso_to_ms(m.get("timestamp"))
        if role == "user":
            add_event(ir, "user_message", ts, blocks=blocks)
        elif role == "assistant":
            add_event(ir, "assistant_message", ts, blocks=blocks,
                      model=ir.get("model") or "", provider="hermes")
        elif role == "tool":
            add_event(ir, "tool_result", ts, call_id=m.get("tool_call_id") or "",
                      name=m.get("tool_name") or "tool", content=_blocks_text({"blocks": blocks}),
                      is_error=False)
        touch_ts(ir, ts)
    for u in usage_rows:
        usage = normalize_usage(u)
        if usage:
            for ev in reversed(ir["events"]):
                if ev.get("kind") == "assistant_message":
                    ev["usage"] = usage
                    break
            break
    ir["lossy"] = sorted(lossy)
    return _finish(ir, "hermes", path, {"sqlite_unverified_columns": ["sessions.cwd", "sessions.created_at",
                                                                     "messages.role", "messages.content",
                                                                     "messages.timestamp"],
                                        "sqlite_uri_mode": "ro"})


def _load_devin(path, keep_system=False):
    if path.endswith(".json"):
        doc = _read_json(path)
        sess = doc.get("session") or doc
        ir = new_ir("devin", str(sess.get("id") or os.path.basename(path)), path)
        ir["title"] = sess.get("title") or ""
        ir["cwd"] = sess.get("working_directory")
        ir["model"] = sess.get("model") or ""
        created = sess.get("created_at")
        if isinstance(created, (int, float)):
            ir["created_at_ms"] = int(created * 1000 if created < 1e12 else created)
        calls = {}
        for node in doc.get("nodes") or []:
            role = node.get("role")
            content = node.get("content")
            thinking = (node.get("thinking") or {}).get("thinking") if isinstance(node.get("thinking"), dict) else None
            blocks = []
            if isinstance(thinking, str) and thinking.strip():
                blocks.append({"type": "reasoning", "text": thinking})
            if isinstance(content, str) and content.strip():
                blocks.append(text_block(content))
            for tc in node.get("tool_calls") or []:
                cid = tc.get("id") or ""
                calls[cid] = tc.get("name") or "tool"
                blocks.append({"type": "tool-call", "id": cid, "name": tc.get("name") or "tool",
                               "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False)})
            if role == "system":
                if keep_system:
                    add_event(ir, "system_message", ir["created_at_ms"], text=content or "",
                              origin="devin-system")
            elif role == "user" and blocks:
                add_event(ir, "user_message", ir["created_at_ms"], blocks=blocks)
            elif role == "assistant" and blocks:
                add_event(ir, "assistant_message", ir["created_at_ms"], blocks=blocks,
                          model=ir["model"], provider="devin")
            elif role == "tool":
                add_event(ir, "tool_result", ir["created_at_ms"],
                          call_id=node.get("tool_call_id") or "",
                          name=calls.get(node.get("tool_call_id")) or "tool",
                          content=content or "", is_error=False)
        ir["lossy"] = ["devin:json-projection-not-native"]
        return _finish(ir, "devin", path, {"projection": True})
    ir = new_ir("devin", os.path.basename(path), path)
    con = _open_ro(path)
    try:
        sessions = [dict(r) for r in con.execute("SELECT * FROM sessions")]
        nodes = [dict(r) for r in con.execute("SELECT * FROM message_nodes ORDER BY seq")]
    finally:
        con.close()
    lossy = {"devin:sqlite-columns-unverified"}
    if sessions:
        s = sessions[0]
        ir["source_session_id"] = str(s.get("id") or ir["source_session_id"])
        ir["title"] = s.get("title") or ""
        ir["cwd"] = s.get("working_directory")
        ir["model"] = s.get("model") or ""
        for key in ("created_at", "last_activity_at"):
            val = s.get(key)
            if isinstance(val, (int, float)) and val:
                touch_ts(ir, int(val * 1000 if val < 1e12 else val))
        ir["created_at_ms"] = int((s.get("created_at") or 0) * (1000 if (s.get("created_at") or 0) < 1e12 else 1))
    calls = {}
    for n in nodes:
        role = n.get("role")
        content = n.get("content")
        thinking = n.get("thinking")
        blocks = []
        if isinstance(thinking, str) and thinking.strip():
            blocks.append({"type": "reasoning", "text": thinking})
        if isinstance(content, str) and content.strip():
            blocks.append(text_block(content))
        tc_json = n.get("tool_calls")
        if isinstance(tc_json, str):
            try:
                tc_json = json.loads(tc_json)
            except ValueError:
                tc_json = []
        for tc in tc_json or []:
            cid = tc.get("id") or ""
            calls[cid] = tc.get("name") or "tool"
            blocks.append({"type": "tool-call", "id": cid,
                           "name": tc.get("name") or "tool",
                           "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False)})
        ts = iso_to_ms(n.get("timestamp"))
        if role == "system":
            if keep_system:
                add_event(ir, "system_message", ts, text=content or "", origin="devin-system")
        elif role == "user":
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif role == "assistant":
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=ir.get("model") or "", provider="devin")
        elif role == "tool":
            add_event(ir, "tool_result", ts, call_id=n.get("tool_call_id") or "",
                      name=calls.get(n.get("tool_call_id")) or "tool",
                      content=content or "", is_error=False)
        touch_ts(ir, ts)
    ir["lossy"] = sorted(lossy)
    return _finish(ir, "devin", path, {"sqlite_unverified_columns": ["message_nodes.seq", "message_nodes.thinking",
                                                                     "message_nodes.tool_calls",
                                                                     "sessions.working_directory"]})


def _load_opencode(path, keep_system=False):
    if path.endswith(".json"):
        doc = _read_json(path)
        ir = new_ir("opencode", os.path.basename(path), path)
        lossy = {"opencode:orphan-part"}
        parts = doc.get("parts") if isinstance(doc.get("parts"), list) else [doc]
        def ptime(p):
            t = p.get("time")
            if isinstance(t, dict):
                return int(t.get("start") or 0)
            return int(t) if isinstance(t, (int, float)) else 0
        parts = sorted(parts, key=ptime)
        for idx, part in enumerate(parts):
            ptype = part.get("type")
            text = part.get("text")
            ts = ptime(part)
            role = part.get("role") or ("user" if idx == 0 else "assistant")
            if ptype == "text" and isinstance(text, str) and text.strip():
                add_event(ir, "user_message" if role == "user" else "assistant_message",
                          ts, blocks=[text_block(text)])
                ir["warnings"].append("opencode:orphan-part")
            elif ptype == "reasoning" and isinstance(text, str) and text.strip():
                add_event(ir, "assistant_message", ts,
                          blocks=[{"type": "reasoning", "text": text}], model="", provider="opencode")
            elif ptype == "tool":
                state = part.get("state") or {}
                cid = part.get("id") or ""
                add_event(ir, "assistant_message", ts,
                          blocks=[{"type": "tool-call", "id": cid,
                                   "name": state.get("tool") or part.get("tool") or "tool",
                                   "arguments": json.dumps(state.get("input") or {}, ensure_ascii=False)}],
                          model="", provider="opencode")
                add_event(ir, "tool_result", ts, call_id=cid,
                          name=state.get("tool") or "tool",
                          content=str(state.get("output") or ""), is_error=False)
            touch_ts(ir, ts)
        ir["lossy"] = sorted(lossy)
        return _finish(ir, "opencode", path, {"legacy_json_projection": True})
    ir = new_ir("opencode", os.path.basename(path), path)
    con = _open_ro(path)
    try:
        sessions = [dict(r) for r in con.execute("SELECT * FROM session")]
        messages = [dict(r) for r in con.execute("SELECT * FROM message ORDER BY time_created")]
        parts = [dict(r) for r in con.execute("SELECT * FROM part ORDER BY time_created")]
    finally:
        con.close()
    lossy = {"opencode:sqlite-schema-unverified"}
    if sessions:
        s = sessions[0]
        ir["source_session_id"] = str(s.get("id") or ir["source_session_id"])
        ir["title"] = s.get("title") or ""
        ir["cwd"] = s.get("directory")
        ir["created_at_ms"] = s.get("created") or 0
    by_msg = {}
    orphan_tool_parts = []
    for p in parts:
        if p.get("type") == "tool" and not p.get("message_id"):
            orphan_tool_parts.append(p)
            continue
        by_msg.setdefault(p.get("message_id"), []).append(p)
    calls = {}
    for m in messages:
        mid = m.get("id")
        role = m.get("role")
        blocks = []
        for p in by_msg.get(mid, []):
            ptype = p.get("type")
            if ptype == "text" and (p.get("text") or "").strip():
                blocks.append(text_block(p["text"]))
            elif ptype == "reasoning" and (p.get("text") or "").strip():
                blocks.append({"type": "reasoning", "text": p["text"]})
            elif ptype == "tool":
                data = p.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except ValueError:
                        data = {}
                state = (data or {}).get("state") or {}
                cid = (data or {}).get("callID") or (data or {}).get("call_id") or p.get("id") or ""
                name = (data or {}).get("tool") or "tool"
                calls[cid] = name
                blocks.append({"type": "tool-call", "id": cid, "name": name,
                               "arguments": json.dumps(state.get("input") or {}, ensure_ascii=False)})
        ts = m.get("time_created") or 0
        if role == "user":
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks)
        elif role == "assistant":
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=ir.get("model") or "", provider="opencode")
            # tool outputs from tool parts of this message
            for p in by_msg.get(mid, []):
                if p.get("type") != "tool":
                    continue
                data = p.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except ValueError:
                        data = {}
                state = (data or {}).get("state") or {}
                cid = (data or {}).get("callID") or (data or {}).get("call_id") or p.get("id") or ""
                add_event(ir, "tool_result", p.get("time_created") or ts, call_id=cid,
                          name=calls.get(cid) or "tool",
                          content=str(state.get("output") or ""),
                          is_error=bool(state.get("is_error") or state.get("isError")))
        touch_ts(ir, ts)
    for p in orphan_tool_parts:
        data = p.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        state = (data or {}).get("state") or {}
        cid = (data or {}).get("callID") or ""
        add_event(ir, "tool_result", p.get("time_created") or 0, call_id=cid,
                  name=(data or {}).get("tool") or "tool",
                  content=str(state.get("output") or ""),
                  is_error=bool(state.get("is_error") or state.get("isError")))
    ir["lossy"] = sorted(lossy)
    return _finish(ir, "opencode", path, {"sqlite_unverified_columns": ["session.directory", "message.role",
                                                                       "part.data", "part.time_created"],
                                         "sqlite_uri_mode": "ro"})


# --------------------------------------------------------------------------- dispatch
LOADS = {
    "openclaw": _load_openclaw,
    "kimi": _load_kimi,
    "grok": _load_grok,
    "droid": _load_droid,
    "antigravity": _load_antigravity,
    "hermes": _load_hermes,
    "devin": _load_devin,
    "opencode": _load_opencode,
}
DB_SOURCES = {"hermes", "devin", "opencode"}


def load_session(source, root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or default_root(source))
    if not path:
        if session:
            cand = os.path.expanduser(session)
            if os.path.isfile(cand):
                path = cand
            else:
                for f in _files(source, root):
                    if session in os.path.basename(f):
                        path = f
                        break
        if not path:
            prim = _primary(source)
            path = prim[0] if prim else (_files(source, root) or [None])[0]
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("%s fixture not found (root=%s)" % (source, root))
    loader = LOADS[source]
    try:
        ir = loader(path, keep_system=keep_system)
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise ValueError("%s fixture parse failed (%s): %s" % (source, os.path.basename(path), exc))
    return ir


def list_sessions(source, root=None):
    root = os.path.expanduser(root or default_root(source))
    if source in DB_SOURCES and os.path.isdir(root):
        # list constructed DB files (search <root>/**/*.db) + JSON projection fixtures
        db_files = []
        for pattern in ("**/*.db", "**/*.sqlite"):
            db_files.extend(glob.glob(os.path.join(root, pattern), recursive=True))
        files = sorted(set([p for p in db_files if os.path.isfile(p)] + _files(source, root)))
    else:
        files = _files(source, root)
    out, seen = [], set()
    for path in files:
        try:
            ir = load_session(source, root=root, path=path)
        except (OSError, ValueError):
            continue
        key = os.path.realpath(path)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "source": source,
            "id": ir.get("source_session_id"),
            "title": (ir.get("title") or os.path.basename(path))[:120],
            "cwd": ir.get("cwd"),
            "created_at_ms": ir.get("created_at_ms"),
            "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
            "path": path,
            "lines": len(ir.get("events") or []),
            "model": ir.get("model") or "",
            "evidence_level": EVIDENCE[source],
            "fixture": True,
            "constructed": EVIDENCE[source] == "FIXTURE-CONSTRUCTED",
        })
    return out
