"""Batch-3 native-format readers (FIXTURE evidence level).

Six harnesses are parsed from public fixtures under
``samples/batch2/public-fixtures/`` (see docs/formats/batch3-fixtures.md §3):

* ``copilot`` GitHub Copilot CLI  — event JSONL (``type``/``data``/``timestamp``)
* ``gemini`` Gemini CLI           — single JSON ``{kind,sessionId,messages[]}``
* ``aider`` Aider                 — Markdown history (``#### user prompt`` blocks)
* ``cursor`` Cursor CLI           — transcript JSONL, current (``turn_ended``) + legacy schemas
* ``qwen`` Qwen Code            — Claude-Code-derived JSONL envelope (``uuid/parentUuid/message.parts``)
* ``pi`` Pi (pi.dev)             — OMP-family tree JSONL (``id/parentId``)

Evidence level is **FIXTURE** only: these are public synthetic/trimmed fixtures, not real
user sessions; no native CLI load is claimed.
"""
import glob
import hashlib
import json
import os
import re

from ..common import HOME, iso_to_ms
from ..ir import (MISSING_RESULT_TEXT, add_event, finalize, new_ir, normalize_usage,
                  text_block, touch_ts, warn)

FIXTURE_EVIDENCE = "FIXTURE"
SOURCE_LABELS = {
    "copilot": "GitHub Copilot CLI",
    "gemini": "Gemini CLI",
    "aider": "Aider",
    "cursor": "Cursor CLI",
    "qwen": "Qwen Code",
    "pi": "Pi (pi.dev)",
}
EXTRA_PATTERNS = {
    "copilot": ("**/copilot-cli-*.jsonl", "**/stage0/copilot/*.jsonl"),
    "gemini": ("**/stage0/gemini/*.json", "**/gemini/**/*.json"),
    "aider": ("**/aider/history/*.md", "**/history/*.md"),
    "cursor": ("**/agent-sessions/stage0/cursor/*.jsonl",
               "**/agent-sessions/legacy/*ursor/*.jsonl",
               "**/sessionport/**/cursor/**/*.jsonl"),
    "qwen": ("**/stage0/qwen/*.jsonl", "**/qwen/**/*.jsonl"),
    "pi": ("**/stage0/pi/*.jsonl", "**/pi/**/*.jsonl"),
}
PRIMARY_FILES = {
    "copilot": ("atifact/test-fixtures/copilot-cli-simple.jsonl",
                "agent-sessions/stage0/copilot/small.jsonl"),
    "gemini": ("agent-sessions/stage0/gemini/small.json",),
    "aider": ("sessionport/tests-fixtures/aider/history/abc123.md",),
    "cursor": ("agent-sessions/stage0/cursor/small.jsonl",
               "agent-sessions/legacy/Cursor/test-session.jsonl"),
    "qwen": ("agent-sessions/stage0/qwen/019f0000000070008000000000000003.jsonl",
             "agent-sessions/stage0/qwen/019f0000-0000-7000-8000-000000000002.jsonl"),
    "pi": ("agent-sessions/stage0/pi/small.jsonl",),
}


def _find_workspace_fixtures():
    base = os.path.abspath(os.getcwd())
    for _ in range(6):
        cand = os.path.join(base, "samples", "batch2", "public-fixtures")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(base)
        if parent == base:
            break
        base = parent
    return ""


def default_root(source):
    env = os.environ.get("ASI_BATCH3_ROOT") or os.environ.get("ASI_FIXTURES_ROOT")
    if env and os.path.isdir(env):
        return env
    base = _find_workspace_fixtures()
    if base:
        return base
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
            real = os.path.normcase(os.path.realpath(path))
            if real in seen:
                continue
            seen.add(real)
            out.append(path)
    if source == "aider":
        out = [p for p in out if p.endswith(".md")]
    out.sort()
    return out


def _primary_paths(source):
    root = default_root(source)
    out = []
    for rel in PRIMARY_FILES.get(source, ()):
        cand = os.path.join(root, rel)
        if os.path.isfile(cand):
            out.append(cand)
    return out


def _read_jsonl(path):
    bad = 0
    rows = []
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


def _sid_from_path(path):
    base = os.path.basename(path)
    for suffix in (".jsonl", ".json", ".md", ".txt"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base or "fixture-session"


def _finish(ir, source, path, evidence, extra=None):
    ir["extra"] = {
        "evidence_level": FIXTURE_EVIDENCE,
        "fixture": True,
        "source_harness": SOURCE_LABELS.get(source, source),
        "source_format": source,
        "fixture_path": path,
        "fixture_origin": "public-fixtures (samples/batch2/public-fixtures)",
    }
    if extra:
        ir["extra"].update(extra)
    finalize(ir)
    return ir


# --------------------------------------------------------------------------- copilot
_COPILOT_IGNORED = {
    "assistant.turn_start", "assistant.turn_end", "tool.execution_start",
    "assistant.reasoning", "assistant.reasoning_delta", "assistant.message_delta",
    "session.mcp_server_status_changed", "session.mcp_servers_loaded",
    "session.skills_loaded", "session.tools_updated", "session.shutdown",
    "result", "subagent.started", "subagent.completed", "hook.start",
    "session.resume", "session.info", "session.usage_checkpoint",
    "session.usage_record", "session.truncation", "model.changed",
    "system.message", "system.notification", "abort",
}


def _copilot_args(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except ValueError:
            return {"_raw": raw}
        return val if isinstance(val, dict) else {"_raw": raw}
    return {}


def _load_copilot(path, keep_system=False):
    rows, bad = _read_jsonl(path)
    ir = new_ir("copilot", _sid_from_path(path), path)
    warnings = ir["warnings"]
    lossy = set()
    deltas = {}
    calls = {}
    trimmed_requests = []
    pending_completes = []
    session_meta = {}
    shutdown = {}
    result = {}
    for row in rows:
        etype = row.get("type")
        data = row.get("data") or {}
        ts = iso_to_ms(row.get("timestamp"))
        if etype == "session.start":
            session_meta = data
            ir["cwd"] = (data.get("context") or {}).get("cwd") or ir.get("cwd")
            ir["model"] = data.get("selectedModel") or ir.get("model")
            ir["created_at_ms"] = iso_to_ms(data.get("startTime")) or ts
            ir["source_session_id"] = data.get("sessionId") or ir["source_session_id"]
            touch_ts(ir, ts)
        elif etype == "user.message":
            add_event(ir, "user_message", ts, blocks=[text_block(data.get("content") or "")])
            touch_ts(ir, ts)
        elif etype == "assistant.message_delta":
            mid = data.get("messageId") or ""
            deltas.setdefault(mid, []).append(data.get("deltaContent") or "")
        elif etype == "assistant.message":
            mid = data.get("messageId") or ""
            content = data.get("content") or ""
            if not content and mid in deltas:
                content = "".join(deltas[mid])
                lossy.add("copilot:delta-merge")
            blocks = []
            reasoning = data.get("reasoningText") or ""
            if reasoning:
                blocks.append({"type": "reasoning", "text": reasoning})
            if content.strip():
                blocks.append(text_block(content))
            for tr in data.get("toolRequests") or []:
                cid = tr.get("toolCallId") or ""
                if not cid or "trimmed" in cid:
                    cid = "copilot-placeholder-%d" % len(trimmed_requests)
                    trimmed_requests.append(cid)
                    warnings.append("copilot:tool-id-trimmed")
                args = _copilot_args(tr.get("arguments"))
                calls[cid] = tr.get("name") or "tool"
                blocks.append({"type": "tool-call", "id": cid,
                               "name": tr.get("name") or "tool",
                               "arguments": json.dumps(args, ensure_ascii=False)})
            if data.get("parentToolCallId"):
                lossy.add("copilot:subagent-collapsed")
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=ir.get("model") or "", provider="copilot")
                touch_ts(ir, ts)
        elif etype == "tool.execution_complete":
            cid = data.get("toolCallId") or ""
            result_obj = data.get("result") or {}
            content = result_obj.get("content") or result_obj.get("detailedContent") or ""
            if not cid or "trimmed" in cid or cid not in calls:
                pending_completes.append((ts, content, not data.get("success", True)))
            else:
                add_event(ir, "tool_result", ts, call_id=cid,
                          name=calls.get(cid) or "tool", content=content,
                          is_error=not data.get("success", True))
            touch_ts(ir, ts)
        elif etype == "session.shutdown":
            shutdown = data
            touch_ts(ir, ts)
        elif etype == "result":
            result = row
            ts2 = iso_to_ms(row.get("timestamp"))
            touch_ts(ir, ts2)
            if row.get("sessionId"):
                ir["source_session_id"] = row["sessionId"]
            ir["source_usage"] = row.get("usage")
            usage = normalize_usage({"input_tokens": 0, "output_tokens": 0})  # placeholder
            del usage
        elif etype == "abort":
            add_event(ir, "turn_abort", ts, reason=str(data.get("reason") or "aborted"))
            touch_ts(ir, ts)
        elif etype == "session.tools_updated":
            if data.get("model"):
                ir["model"] = data["model"]
        elif etype == "session.model_change":
            if data.get("newModel") or data.get("model"):
                ir["model"] = data.get("newModel") or data.get("model")
        elif etype in _COPILOT_IGNORED:
            pass
        elif etype and etype.startswith("assistant.reasoning"):
            pass
        else:
            warnings.append("copilot:unknown-event:%s" % etype)
    # pair trimmed/missing completes with trimmed requests in order (fixture clips ids)
    unmatched_placeholders = [cid for cid in trimmed_requests
                              if not any(ev.get("call_id") == cid
                                         for ev in ir["events"] if ev.get("kind") == "tool_result")]
    for ts, content, is_error in pending_completes:
        if unmatched_placeholders:
            cid = unmatched_placeholders.pop(0)
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or "tool", content=content, is_error=is_error)
        else:
            warnings.append("copilot:orphan-tool-complete")
    if not session_meta:
        warnings.append("missing-session-start")
    if not result:
        warnings.append("missing-result")
    if shutdown:
        ir["extra_shutdown"] = shutdown
    ir["lossy"] = sorted(lossy)
    if not ir.get("cwd"):
        warnings.append("copilot:cwd-unresolved")
    return ir


# --------------------------------------------------------------------------- gemini
def _apply_patch(doc, patch):
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(doc.get(key), dict):
            _apply_patch(doc[key], value)
        else:
            doc[key] = value
    return doc


def _load_gemini(path, keep_system=False):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    try:
        doc = json.loads(text)
    except ValueError:
        # real Gemini CLI chat files are JSONL: header + {"$set":{...}} patch stream
        doc = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and "$set" in obj:
                _apply_patch(doc, obj["$set"])
            elif isinstance(obj, dict):
                doc.update(obj)
        if not doc:
            raise
    ir = new_ir("gemini", doc.get("sessionId") or _sid_from_path(path), path)
    warnings = ir["warnings"]
    lossy = set()
    if doc.get("kind") != "chat":
        warnings.append("gemini:kind-%r" % (doc.get("kind"),))
    ir["created_at_ms"] = iso_to_ms(doc.get("startTime"))
    ir["updated_at_ms"] = iso_to_ms(doc.get("lastUpdated")) or ir["created_at_ms"]
    ir["cwd"] = None
    warnings.append("gemini:cwd-unresolved")
    lossy.add("gemini:title-derived")
    for msg in doc.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("type")
        ts = iso_to_ms(msg.get("timestamp"))
        if mtype == "user":
            raw = msg.get("content")
            blocks = []
            if isinstance(raw, str) and raw.strip():
                blocks = [text_block(raw)]
            elif isinstance(raw, list):
                for b in raw:
                    if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip():
                        blocks.append(text_block(b["text"]))
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks, source_id=msg.get("id"))
        elif mtype in ("gemini", "model", "assistant"):
            blocks = []
            thoughts = [t.get("description") for t in msg.get("thoughts") or []
                        if isinstance(t, dict) and t.get("description")]
            if thoughts:
                blocks.append({"type": "reasoning", "text": "\n".join(thoughts)})
                lossy.add("gemini:thoughts-merged")
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                blocks.append(text_block(content))
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip():
                        blocks.append(text_block(b["text"]))
            tool_calls = msg.get("toolCalls") or []
            pending_results = []
            for tc in tool_calls:
                cid = tc.get("id") or tc.get("toolCallId") or ""
                args = tc.get("args", tc.get("arguments", tc.get("input")))
                if not isinstance(args, str):
                    args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                blocks.append({"type": "tool-call", "id": cid,
                               "name": tc.get("name") or "tool", "arguments": args})
                out = tc.get("result", tc.get("output"))
                if out is not None:
                    pending_results.append((cid, tc.get("name") or "tool",
                                            out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)))
                else:
                    lossy.add("gemini:toolcalls-schema-unverified")
            if blocks:
                model = msg.get("model") or ""
                if not ir.get("model") and model:
                    ir["model"] = model
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=model or ir.get("model") or "", provider="gemini",
                          usage=normalize_usage(msg.get("tokens")))
                for cid, name, content in pending_results:
                    add_event(ir, "tool_result", ts, call_id=cid, name=name,
                              content=content, is_error=False)
        touch_ts(ir, ts)
    ir["provider"] = "gemini"
    title = ""
    for ev in ir["events"]:
        if ev.get("kind") == "user_message":
            title = "".join(b.get("text") or "" for b in ev["blocks"])
            break
    ir["title"] = (title.strip().splitlines()[0][:80] if title.strip() else "")
    ir["lossy"] = sorted(lossy)
    return ir


# --------------------------------------------------------------------------- aider
_AIDER_HEAD = re.compile(r"^####\s+(.*\S)\s*$")


def _load_aider(path, keep_system=False):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    ir = new_ir("aider", _sid_from_path(path), path)
    warnings = ir["warnings"]
    blocks = []  # (user_text, [assistant lines])
    preamble = []
    for line in lines:
        m = _AIDER_HEAD.match(line)
        if m:
            blocks.append([m.group(1), []])
        elif blocks:
            blocks[-1][1].append(line)
        elif line.strip():
            preamble.append(line)
    if preamble:
        warnings.append("aider:preamble-orphan")
    for user_text, reply_lines in blocks:
        add_event(ir, "user_message", 0, blocks=[text_block(user_text)])
        reply = "\n".join(reply_lines).strip()
        if not reply:
            warnings.append("aider:empty-reply")
            reply = ""
        add_event(ir, "assistant_message", 0, blocks=[text_block(reply)],
                  model="", provider="aider")
    ir["lossy"] = ["aider:no-timestamps", "aider:no-tool-events"]
    if blocks:
        ir["title"] = blocks[0][0][:120]
    return ir


# --------------------------------------------------------------------------- cursor
_CURSOR_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.S)


def _load_cursor(path, keep_system=False, keep_wrappers=False):
    rows, bad = _read_jsonl(path)
    ir = new_ir("cursor", _sid_from_path(path), path)
    warnings = ir["warnings"]
    lossy = {"cursor:no-timestamps"}
    call_no = {}
    turn_aborts = 0
    for i, row in enumerate(rows):
        role = row.get("role")
        if role:
            content = ((row.get("message") or {}).get("content")) or []
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            if role == "user":
                blocks = []
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        text = b.get("text") or ""
                        if not keep_wrappers:
                            m = _CURSOR_QUERY.search(text)
                            if m:
                                text = m.group(1)
                                lossy.add("cursor:user-query-unwrapped")
                        if text.strip():
                            blocks.append(text_block(text))
                if blocks:
                    add_event(ir, "user_message", 0, blocks=blocks)
            elif role == "assistant":
                blocks = []
                for bi, b in enumerate(content):
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "text":
                        text = b.get("text") or ""
                        if text.strip():
                            blocks.append(text_block(text))
                    elif bt in ("tool_use", "tool_call"):
                        cid = b.get("id") or "cursor:%s:%d:%d" % (ir["source_session_id"], i, bi)
                        call_no[cid] = b.get("name") or "tool"
                        args = b.get("input", b.get("arguments"))
                        if not isinstance(args, str):
                            args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                        blocks.append({"type": "tool-call", "id": cid,
                                       "name": b.get("name") or "tool", "arguments": args})
                if blocks:
                    add_event(ir, "assistant_message", 0, blocks=blocks,
                              model="", provider="cursor")
                    for b in blocks:
                        if b.get("type") == "tool-call":
                            add_event(ir, "tool_result", 0, call_id=b["id"], name=b["name"],
                                      content="[cursor:tool-result-missing]", is_error=True)
                            lossy.add("cursor:tool-result-missing")
        elif row.get("type") == "turn_ended":
            if row.get("status") == "error":
                turn_aborts += 1
                add_event(ir, "turn_abort", 0, reason=str(row.get("error") or "error"))
        else:
            warnings.append("cursor:unknown-row")
    if "Cursor" in path and "subagent" in os.path.basename(path):
        warnings.append("cursor:subagent-undetectable")
    ir["lossy"] = sorted(lossy)
    return ir


# --------------------------------------------------------------------------- qwen
def _qwen_parts(msg, ir, ts, calls):
    blocks = []
    parts = (msg or {}).get("parts") or []
    if isinstance((msg or {}).get("content"), str):
        parts = [{"text": msg["content"]}]
    for part in parts:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str) and part["text"].strip():
            blocks.append(text_block(part["text"]))
        elif part.get("thinking") or part.get("reasoning"):
            txt = part.get("thinking") or part.get("reasoning")
            if isinstance(txt, str) and txt.strip():
                blocks.append({"type": "reasoning", "text": txt})
        elif part.get("functionCall") or part.get("toolCall"):
            tc = part.get("functionCall") or part.get("toolCall")
            cid = tc.get("id") or tc.get("toolCallId") or ""
            args = tc.get("args", tc.get("arguments", tc.get("input")))
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            calls[cid] = tc.get("name") or "tool"
            blocks.append({"type": "tool-call", "id": cid,
                           "name": tc.get("name") or "tool", "arguments": args})
        elif part.get("functionResponse") or part.get("toolResult"):
            tr = part.get("functionResponse") or part.get("toolResult")
            cid = tr.get("id") or tr.get("toolUseId") or tr.get("tool_call_id") or ""
            resp = tr.get("response", tr.get("output", tr.get("content")))
            if not isinstance(resp, str):
                resp = json.dumps(resp, ensure_ascii=False) if resp is not None else ""
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or "tool", content=resp, is_error=False)
    return blocks


def _load_qwen(path, keep_system=False):
    rows, bad = _read_jsonl(path)
    ir = new_ir("qwen", _sid_from_path(path), path)
    warnings = ir["warnings"]
    lossy = set()
    filename_id = _sid_from_path(path)
    calls = {}
    prev_uuid = None
    for row in rows:
        rec_sid = row.get("sessionId")
        if rec_sid:
            if not ir.get("source_session_id") or ir["source_session_id"] == filename_id:
                ir["source_session_id"] = rec_sid
            if rec_sid.replace("-", "") != filename_id.replace("-", ""):
                warnings.append("qwen:session-id-mismatch")
        ir["cwd"] = ir.get("cwd") or row.get("cwd")
        if row.get("version"):
            ir["extra_version"] = row["version"]
        ts = iso_to_ms(row.get("timestamp"))
        typ = row.get("type")
        msg = row.get("message") or {}
        role = msg.get("role") or typ
        if typ == "user" or role == "user":
            blocks = _qwen_parts(msg, ir, ts, calls)
            if not blocks:
                text = row.get("content")
                if isinstance(text, str) and text.strip():
                    blocks = [text_block(text)]
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks, source_id=row.get("uuid"))
        elif typ in ("assistant", "model", "gemini") or role == "assistant":
            blocks = _qwen_parts(msg, ir, ts, calls)
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=row.get("model") or msg.get("model") or "",
                          provider="qwen")
        elif typ == "tool_result" or role == "tool":
            cid = (row.get("toolUseId") or row.get("tool_call_id")
                   or row.get("toolCallId") or "")
            content = row.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False) if content is not None else ""
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or "tool", content=content, is_error=False)
        if row.get("gitBranch"):
            ir["extra_git_branch"] = row["gitBranch"]
        sp = row.get("systemPayload") or {}
        if isinstance(sp, dict) and sp.get("displayText"):
            if keep_system:
                add_event(ir, "system_message", ts, text=sp["displayText"], origin="qwen-system")
            else:
                ir["extra_system_payload"] = sp["displayText"]
        pu = row.get("parentUuid")
        if pu and prev_uuid and pu != prev_uuid:
            lossy.add("qwen:branch-linearized")
        prev_uuid = row.get("uuid") or prev_uuid
        touch_ts(ir, ts)
    if not ir.get("cwd"):
        warnings.append("qwen:cwd-missing")
    ir["lossy"] = sorted(lossy)
    return ir


# --------------------------------------------------------------------------- pi
def _load_pi(path, keep_system=False):
    rows, bad = _read_jsonl(path)
    ir = new_ir("pi", _sid_from_path(path), path)
    warnings = ir["warnings"]
    lossy = set()
    header = None
    entries = []
    for row in rows:
        t = row.get("type")
        if t == "session":
            header = row
        elif t == "title":
            continue
        else:
            entries.append(row)
    if header:
        ir["source_session_id"] = header.get("id") or ir["source_session_id"]
        ir["cwd"] = header.get("cwd")
        ir["created_at_ms"] = iso_to_ms(header.get("timestamp"))
    by_id = {}
    child_parent = {}
    for e in entries:
        eid = e.get("id")
        if not eid:
            continue
        by_id[eid] = e
        child_parent[eid] = e.get("parentId")
    leaves = [e for e in entries if e.get("id") and
              not any(p == e["id"] for p in child_parent.values())]
    leaf = max(leaves, key=lambda e: (e.get("timestamp") or "", e.get("id") or "")) if leaves else (
        entries[-1] if entries else None)
    path_entries = []
    cur = leaf
    guard = 0
    while cur is not None and guard < 100000:
        path_entries.append(cur)
        pid = cur.get("parentId")
        cur = by_id.get(pid) if pid else None
        guard += 1
    path_entries.reverse()
    for e in path_entries:
        t = e.get("type")
        ts = iso_to_ms(e.get("timestamp"))
        if t == "message":
            msg = e.get("message") or {}
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                blocks = []
                if isinstance(content, str):
                    if content.strip():
                        blocks.append(text_block(content))
                else:
                    for b in content or []:
                        if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                            blocks.append(text_block(b["text"]))
                        elif isinstance(b, dict) and b.get("type") in ("image", "image_url"):
                            blocks.append({"type": "image",
                                           "placeholder": "[image attachment not imported]"})
                if blocks:
                    add_event(ir, "user_message", ts, blocks=blocks)
            elif role == "assistant":
                blocks = []
                for b in content or []:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "thinking":
                        txt = b.get("thinking") or ""
                        if isinstance(txt, str) and txt.strip():
                            blocks.append({"type": "reasoning", "text": txt})
                    elif bt == "text":
                        txt = b.get("text") or ""
                        if isinstance(txt, str) and txt.strip():
                            blocks.append(text_block(txt))
                    elif bt == "toolCall":
                        cid = b.get("id") or ""
                        args = b.get("arguments")
                        if not isinstance(args, str):
                            args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                        blocks.append({"type": "tool-call", "id": cid,
                                       "name": b.get("name") or "tool", "arguments": args})
                if blocks:
                    if msg.get("model"):
                        ir["model"] = msg["model"]
                    add_event(ir, "assistant_message", ts, blocks=blocks,
                              model=msg.get("model") or ir.get("model") or "",
                              provider=msg.get("provider") or "pi",
                              usage=normalize_usage(msg.get("usage")))
            elif role == "toolResult":
                blocks = []
                for b in content or []:
                    if isinstance(b, dict) and b.get("type") == "text":
                        blocks.append(b.get("text") or "")
                add_event(ir, "tool_result", ts, call_id=msg.get("toolCallId") or "",
                          name=msg.get("toolName") or "tool",
                          content="\n".join(blocks), is_error=bool(msg.get("isError")))
            elif role == "system":
                if keep_system:
                    text = msg.get("content")
                    if isinstance(text, str) and text.strip():
                        add_event(ir, "system_message", ts, text=text, origin="pi-system")
            else:
                warnings.append("pi:unknown-role:%r" % (role,))
        elif t == "compaction":
            add_event(ir, "compaction", ts, summary=e.get("summary") or "")
        elif t == "model_change":
            ir["model"] = e.get("modelId") or e.get("model") or ir.get("model")
        touch_ts(ir, ts)
    if not ir.get("title"):
        for ev in ir["events"]:
            if ev.get("kind") == "user_message":
                text = "".join(b.get("text") or "" for b in ev["blocks"])
                ir["title"] = text.strip().splitlines()[0][:80] if text.strip() else ""
                break
    ir["lossy"] = sorted(lossy)
    return ir


# --------------------------------------------------------------------------- dispatch
LOADERS = {
    "copilot": _load_copilot,
    "gemini": _load_gemini,
    "aider": _load_aider,
    "cursor": _load_cursor,
    "qwen": _load_qwen,
    "pi": _load_pi,
}


def load_session(source, root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or default_root(source))
    if not path:
        if session:
            cand = os.path.expanduser(session)
            if os.path.isfile(cand):
                path = cand
            else:
                for fpath in _files(source, root):
                    if session in os.path.basename(fpath):
                        path = fpath
                        break
        if not path:
            prim = _primary_paths(source)
            path = prim[0] if prim else (_files(source, root) or [None])[0]
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("%s fixture not found (root=%s session=%r)" % (source, root, session))
    loader = LOADERS.get(source)
    if loader is None:
        raise ValueError("unknown batch3 source %r" % (source,))
    try:
        ir = loader(path, keep_system=keep_system,
                    **{k: v for k, v in kwargs.items() if k in ("keep_wrappers",)})
    except (OSError, ValueError) as exc:
        raise ValueError("%s fixture parse failed (%s): %s" % (source, os.path.basename(path), exc))
    ir["created_at_ms"] = ir.get("created_at_ms") or 0
    return _finish(ir, source, path, FIXTURE_EVIDENCE)


def list_sessions(source, root=None):
    out = []
    root = os.path.expanduser(root or default_root(source))
    for path in _files(source, root):
        try:
            ir = load_session(source, root=root, path=path)
        except (OSError, ValueError):
            continue
        out.append({
            "source": source,
            "id": ir.get("source_session_id") or _sid_from_path(path),
            "title": (ir.get("title") or os.path.basename(path))[:120],
            "cwd": ir.get("cwd"),
            "created_at_ms": ir.get("created_at_ms"),
            "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
            "path": path,
            "lines": len(ir.get("events") or []),
            "model": ir.get("model") or "",
            "evidence_level": FIXTURE_EVIDENCE,
            "fixture": True,
        })
    uniq = {}
    for r in out:
        uniq[os.path.normcase(os.path.realpath(r["path"]))] = r
    return sorted(uniq.values(), key=lambda r: (r.get("source"), os.path.basename(r["path"])))
