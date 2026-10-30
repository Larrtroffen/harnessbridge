"""DSH v4 session writer / verifier / importer.

Authoritative format spec: docs/formats/dsh.md (2026-10, DSH Desktop 0.2.1-rc.3).

Disk layout::

    <dsh-home>/sessions/--<projectKey(cwd)>--/<encodeSegment(sessionId)>/session.v4.jsonl.zstd

The file is a concatenation of at least two independent zstd frames: frame 1 must decode to
exactly one JSONL header line (ending with \\n), frame 2 (and later) hold event lines.
"""
import glob
import json
import os
import re
import shutil
import tempfile
import uuid

from . import __version__
from .common import HOME, dumps, iso_now, json_line, now_ms, zdump, zcat
from .ir import normalize_usage

SURFACE_EVENTS = {
    "system/message",
    "developer/message",
    "user/message",
    "assistant/message",
    "tool/result",
}

# dsh-session/lib/types/known-event-types.js (as documented in docs/formats/dsh.md §5.1)
KNOWN_EVENT_TYPES = {
    "agent-preset/selected", "agent/inbox/spliced", "approval/asked", "approval/decided",
    "approval/policy", "assistant/attempt", "assistant/message", "command/done", "command/run",
    "compaction/end", "compaction/prune", "compaction/start", "compaction/summary",
    "deliverables/presented", "developer/message", "feedback/message-delete",
    "feedback/message-put", "feedback/record", "goal/change", "hook/invoked", "hook/result",
    "image/offload", "job/registered", "job/settled", "llm/retry", "llm/retry-started",
    "model/selection", "permission/preset", "plan/mode", "request/context", "request/header",
    "sandbox/mode", "schedule/change", "session-log-deepseek/delivery-accepted",
    "session/end-seed", "session/title", "session/title-llm-request", "step/end", "step/start",
    "subagent/catalog", "subagent/descriptor", "subagent/model-selection-policy",
    "system/message", "team/member", "team/message/delivered", "team/message/queued",
    "team/task", "todo/write", "tool-workflow/agent-end", "tool-workflow/agent-start",
    "tool-workflow/run-end", "tool-workflow/run-start", "tool/call", "tool/ptc-dispatch",
    "tool/ptc-dispatch-start", "tool/result", "turn/end", "turn/start", "user/message",
    "web/deepseek-search-llm-request", "working-directory/change", "workspace/changes",
}

HEADER_KEYS = {
    "type", "version", "id", "createdAt", "cwd", "parentSession", "isSeeded", "origin",
    "delegationDepth", "agentPreset",
}

ENVELOPE_KEYS = {"type", "seq", "time", "data", "surfaceOp", "sourceEventSeqs", "ignorable"}

_SAFE_RE = re.compile(r"^[A-Za-z0-9._-]$")
_UNSAFE_PATH_RE = re.compile(r"[^A-Za-z0-9._-]")


# --------------------------------------------------------------------------- path codec
def _is_safe(ch):
    return ch in "_-." or (ch.isascii() and ch.isalnum())


def _code_units(s):
    """Iterate UTF-16 code units (4-hex escaping is code-unit based)."""
    for ch in s:
        o = ord(ch)
        if o <= 0xFFFF:
            yield o
        else:
            o -= 0x10000
            yield 0xD800 + (o >> 10)
            yield 0xDC00 + (o & 0x3FF)


def _escape_unit(unit):
    return "~" + format(unit, "04X")


def encode_segment(raw):
    """dsh-session-persistence-jsonl encodeSegment()."""
    if raw is None or raw == "":
        raise ValueError("empty path segment")
    if raw == ".":
        return "~002E"
    if raw == "..":
        return "~002E~002E"
    out = []
    for ch in raw:
        if _is_safe(ch):
            out.append(ch)
        else:
            for unit in _code_units(ch):
                out.append(_escape_unit(unit))
    return "".join(out)


def project_key(cwd):
    """Return the full project directory name: '--' + projectKey(cwd) + '--'."""
    if not isinstance(cwd, str):
        raise ValueError("cwd must be a string for projectKey")
    if cwd == "":
        return "--root--"
    out = []
    sep_run = False
    for ch in cwd:
        if ch in "/\\:":
            if not sep_run:
                out.append("-")
            sep_run = True
        elif _is_safe(ch):
            out.append(ch)
            sep_run = False
        else:
            for unit in _code_units(ch):
                out.append(_escape_unit(unit))
            sep_run = False
    readable = "".join(out).lstrip("-")[:251] or "root"
    return "--" + readable + "--"


def session_id_for(source, source_session_id):
    """Deterministic, unique DSH session id (idempotent re-imports map to the same id)."""
    key = "asi:%s:%s" % (source, source_session_id)
    return "session-" + str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def generation_path(sessions_root, cwd, session_id, version=4):
    return os.path.join(
        sessions_root,
        project_key(cwd),
        encode_segment(session_id),
        "session.v%d.jsonl.zstd" % version,
    )


# --------------------------------------------------------------------------- event builder
class _Builder:
    def __init__(self, base_time):
        self.events = []
        self.seq = 0
        self.cursor = int(base_time or 0)

    def _time(self, ts):
        t = self.cursor
        if isinstance(ts, (int, float)) and not isinstance(ts, bool):
            t = max(int(ts), 0)
        if t < self.cursor:
            t = self.cursor
        self.cursor = t
        return t

    def emit(self, etype, ts, data, surface=False, source_event_seqs=None):
        ev = {"type": etype, "seq": self.seq, "time": self._time(ts), "data": data}
        if surface:
            ev["surfaceOp"] = "append"
        if source_event_seqs:
            ev["sourceEventSeqs"] = list(source_event_seqs)
        self.seq += 1
        self.events.append(ev)
        return ev["seq"]


def _user_content(blocks):
    content = []
    for b in blocks or []:
        bt = b.get("type")
        if bt == "text" and isinstance(b.get("text"), str) and b["text"].strip():
            content.append({"type": "text", "text": b["text"]})
        elif bt == "image":
            content.append({"type": "text", "text": b.get("placeholder") or "[image attachment not imported]"})
    return content


def _assistant_content(blocks, call_id_fallback):
    content = []
    for b in blocks or []:
        bt = b.get("type")
        if bt == "text":
            text = b.get("text")
            if isinstance(text, str) and text.strip():
                content.append({"type": "text", "text": text})
        elif bt == "reasoning":
            text = b.get("text")
            if isinstance(text, str) and text.strip():
                content.append({"type": "reasoning", "text": text})
        elif bt == "tool-call":
            cid = b.get("id") or call_id_fallback()
            args = b.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            content.append(
                {
                    "type": "tool-call",
                    "id": str(cid),
                    "name": (b.get("name") or "tool"),
                    "arguments": args,
                }
            )
    return content


def _tool_result_content(content):
    if isinstance(content, str) and content:
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": ""}]


def build_session(ir, session_id=None, target_cwd=None, keep_system=False):
    """IR -> (header, events). Raises ValueError when the session cannot be laid out."""
    cwd = target_cwd or ir.get("cwd")
    if not cwd or not os.path.isabs(cwd):
        raise ValueError(
            "session %s has no absolute cwd; pass --target-cwd" % (ir.get("source_session_id") or "?")
        )
    sid = session_id or session_id_for(ir.get("source"), ir.get("source_session_id"))
    created = int(ir.get("created_at_ms") or now_ms())
    header = {
        "type": "session",
        "version": 4,
        "id": sid,
        "createdAt": created,
        "cwd": cwd,
        "isSeeded": False,
        "delegationDepth": 0,
        "agentPreset": "standard",
    }
    title = (ir.get("title") or "").strip()
    title_emitted = False
    system_prompt = ir.get("system_prompt") if keep_system else None
    abort_reason = None
    for ev in ir.get("events") or []:
        if ev.get("kind") == "turn_abort":
            abort_reason = ev.get("reason") or "interrupted"

    b = _Builder(created)
    b.emit("permission/preset", created, {"preset": "workspace-write"})
    b.emit("sandbox/mode", created, {"mode": "workspace-write"})
    b.emit("approval/policy", created, {"policy": "ask"})

    state = {
        "turn": 0,
        "step": 0,
        "in_turn": False,
        "step_open": False,
        "step_has_assistant": False,
        "step_calls": [],
        "ended": False,
    }
    calls = {}  # callId -> {seq, name, resolved}
    buffered_system = []
    counter = [0]

    def fallback_call_id():
        counter[0] += 1
        return "call_asi_%04d" % counter[0]

    def start_step():
        state["step"] += 1
        b.emit("step/start", created, {"turn": state["turn"], "step": state["step"]})
        state["step_open"] = True
        state["step_has_assistant"] = False
        state["step_calls"] = []

    def ensure_step():
        if not state["in_turn"]:
            start_turn()
        elif not state["step_open"]:
            start_step()

    def flush_system():
        nonlocal system_prompt
        if system_prompt:
            text = system_prompt
            system_prompt = None
            b.emit(
                "system/message",
                created,
                {
                    "turn": state["turn"],
                    "step": state["step"],
                    "message": {
                        "role": "system",
                        "content": [{"type": "text", "text": text}],
                        "source": {"kind": "system-prompt"},
                        "id": str(uuid.uuid4()),
                    },
                },
                surface=True,
            )
        for item in buffered_system:
            b.emit(
                "system/message",
                item["ts"],
                {
                    "turn": state["turn"],
                    "step": state["step"],
                    "message": {
                        "role": "system",
                        "content": [{"type": "text", "text": item["text"]}],
                        "source": {"kind": "system-prompt"},
                        "id": str(uuid.uuid4()),
                    },
                },
                surface=True,
            )
        buffered_system.clear()

    def start_turn():
        state["turn"] += 1
        state["step"] = 0
        state["in_turn"] = True
        state["step_open"] = False
        b.emit("turn/start", created, {"turn": state["turn"]})
        start_step()
        flush_system()

    def close_step():
        if not state["step_open"]:
            return
        for cid in state["step_calls"]:
            info = calls.get(cid)
            if info and not info["resolved"]:
                rseq = b.emit(
                    "tool/result",
                    info.get("time"),
                    {
                        "turn": state["turn"],
                        "step": state["step"],
                        "message": {
                            "role": "tool",
                            "source": {"kind": "tool", "callId": cid},
                            "toolCallId": cid,
                            "content": [{"type": "text", "text": "[tool result missing in source session]"}],
                            "isError": False,
                            "id": str(uuid.uuid4()),
                        },
                    },
                    surface=True,
                    source_event_seqs=[info["seq"]],
                )
                info["resolved"] = rseq
        b.emit("step/end", created, {"turn": state["turn"], "step": state["step"]})
        state["step_open"] = False

    def close_turn(reason="completed"):
        if not state["in_turn"]:
            return
        close_step()
        b.emit("turn/end", created, {"turn": state["turn"], "reason": {"kind": reason}})
        state["in_turn"] = False

    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = ev.get("ts")
        if kind == "user_message":
            blocks = ev.get("blocks") or []
            content = _user_content(blocks)
            if not content:
                continue
            if state["in_turn"]:
                close_turn()
            start_turn()
            useq = b.emit(
                "user/message",
                ts,
                {
                    "content": content,
                    "source": {"kind": "user"},
                    "role": "user",
                    "id": ev.get("source_id") or str(uuid.uuid4()),
                },
                surface=True,
            )
            if title and not title_emitted:
                b.emit(
                    "session/title",
                    ts,
                    {"title": title, "messageSeqs": [useq], "source": {"kind": "fallback"}},
                )
                title_emitted = True
        elif kind == "assistant_message":
            blocks = ev.get("blocks") or []
            content = _assistant_content(blocks, fallback_call_id)
            if not content:
                continue
            if not state["in_turn"]:
                start_turn()
            if state["step_open"] and state["step_has_assistant"]:
                close_step()
                start_step()
            elif not state["step_open"]:
                start_step()
            data = {
                "turn": state["turn"],
                "step": state["step"],
                "message": {
                    "role": "assistant",
                    "content": content,
                    "source": {
                        "kind": "model",
                        "provider": ev.get("provider") or ir.get("provider") or "imported",
                        "model": ev.get("model") or ir.get("model") or "unknown",
                    },
                    "id": ev.get("source_id") or str(uuid.uuid4()),
                },
                "stream": [],
            }
            usage = normalize_usage(ev.get("usage"))
            if usage:
                data["usage"] = usage
            b.emit("assistant/message", ts, data, surface=True)
            state["step_has_assistant"] = True
            for blk in content:
                if blk.get("type") != "tool-call":
                    continue
                cid = blk["id"]
                cseq = b.emit(
                    "tool/call",
                    ts,
                    {
                        "turn": state["turn"],
                        "step": state["step"],
                        "callId": cid,
                        "name": blk["name"],
                        "arguments": blk["arguments"],
                    },
                )
                calls[cid] = {"seq": cseq, "name": blk["name"], "resolved": False, "time": ts}
                state["step_calls"].append(cid)
        elif kind == "tool_result":
            cid = ev.get("call_id") or ""
            if not cid:
                continue
            if not state["in_turn"]:
                start_turn()
            elif not state["step_open"]:
                start_step()
            info = calls.get(cid)
            if info is None:
                # result without a recorded call: synthesize the durable tool/call first
                cseq = b.emit(
                    "tool/call",
                    ts,
                    {
                        "turn": state["turn"],
                        "step": state["step"],
                        "callId": cid,
                        "name": ev.get("name") or "tool",
                        "arguments": "{}",
                    },
                )
                info = {"seq": cseq, "name": ev.get("name") or "tool", "resolved": False, "time": ts}
                calls[cid] = info
                state["step_calls"].append(cid)
            if info.get("resolved"):
                continue  # duplicate result; keep the first one
            rseq = b.emit(
                "tool/result",
                ts,
                {
                    "turn": state["turn"],
                    "step": state["step"],
                    "message": {
                        "role": "tool",
                        "source": {"kind": "tool", "callId": cid},
                        "toolCallId": cid,
                        "content": _tool_result_content(ev.get("content")),
                        "isError": bool(ev.get("is_error")),
                        "id": str(uuid.uuid4()),
                    },
                    "meta": {"cwd": cwd},
                },
                surface=True,
                source_event_seqs=[info["seq"]],
            )
            info["resolved"] = rseq
        elif kind == "system_message":
            if not keep_system:
                continue
            text = ev.get("text")
            if not isinstance(text, str) or not text:
                continue
            if not state["in_turn"]:
                buffered_system.append({"ts": ts, "text": text})
            else:
                ensure_step()
                b.emit(
                    "system/message",
                    ts,
                    {
                        "turn": state["turn"],
                        "step": state["step"],
                        "message": {
                            "role": "system",
                            "content": [{"type": "text", "text": text}],
                            "source": {"kind": "system-prompt"},
                            "id": ev.get("source_id") or str(uuid.uuid4()),
                        },
                    },
                    surface=True,
                )
        elif kind == "compaction":
            # compaction/* payloads are not required for loading; DSH rebuilds its own
            # compaction state.  Keep the information in the IR JSON for reference.
            continue
        else:
            continue

    if state["in_turn"]:
        close_turn("interrupted" if abort_reason else "completed")
    b.emit("session/end-seed", created, {})
    return header, b.events


def render(header, events, compress=True):
    """Return (plain_jsonl_bytes, zstd_bytes_or_None)."""
    header_bytes = json_line(header)
    events_bytes = b"".join(json_line(e) for e in events)
    plain = header_bytes + events_bytes
    if not compress:
        return plain, None
    frames = zdump(header_bytes)
    if events_bytes:
        frames += zdump(events_bytes)
    return plain, frames


def write_session_file(path, header, events, compress=True):
    """Write a single session file atomically.  Returns (path, nbytes)."""
    plain, frames = render(header, events, compress=compress)
    data = frames if compress else plain
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".asi-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path, len(data)


# --------------------------------------------------------------------------- import
def resolve_target_cwd(ir, target_cwd=None, fallback_cwd=None):
    """Resolve the header cwd for an import.

    Priority: ``--target-cwd`` (global override) > source session cwd (provenance) >
    ``--fallback-cwd`` (only used when the source cwd is absent / not a directory).

    Returns ``(cwd, cwd_note, fallback_used)`` or raises ValueError when no usable cwd
    exists and neither --target-cwd nor --fallback-cwd was supplied.
    """
    if target_cwd:
        cand = os.path.expanduser(target_cwd)
        if not os.path.isdir(cand):
            raise ValueError("--target-cwd does not exist or is not a directory: %s" % cand)
        return os.path.realpath(cand), "target-cwd override", False
    src = ir.get("cwd")
    src_ok = bool(src) and os.path.isdir(os.path.expanduser(src))
    if src_ok:
        return os.path.realpath(os.path.expanduser(src)), "source cwd preserved", False
    reason = (
        "source session has no cwd recorded"
        if not src
        else "source cwd does not exist on this machine (%s)" % src
    )
    if fallback_cwd:
        cand = os.path.expanduser(fallback_cwd)
        if not os.path.isdir(cand):
            raise ValueError("--fallback-cwd does not exist or is not a directory: %s" % cand)
        resolved = os.path.realpath(cand)
        return resolved, "%s; cwd 缺失 → fallback 到 %s" % (reason, resolved), True
    raise ValueError(
        "%s; pass --fallback-cwd <existing dir> to import it anyway, or "
        "--target-cwd <existing dir> to override the cwd for every session" % reason
    )


def plan_import(ir, dsh_home, target_cwd=None, fallback_cwd=None, keep_system=False):
    cwd, cwd_note, fallback_used = resolve_target_cwd(ir, target_cwd, fallback_cwd)
    sid = session_id_for(ir.get("source"), ir.get("source_session_id"))
    header, events = build_session(ir, session_id=sid, target_cwd=cwd, keep_system=keep_system)
    sessions_root = os.path.join(os.path.expanduser(dsh_home), "sessions")
    path = generation_path(sessions_root, cwd, sid)
    return {
        "session_id": sid,
        "cwd": cwd,
        "cwd_note": cwd_note,
        "fallback_used": fallback_used,
        "source_cwd": ir.get("cwd"),
        "header": header,
        "events": events,
        "sessions_root": sessions_root,
        "path": path,
        "session_dir": os.path.dirname(path),
    }


def write_import(plan, overwrite=False):
    """Write a planned session into the DSH sessions root. Returns status string."""
    path = plan["path"]
    session_dir = plan["session_dir"]
    if os.path.exists(path) and not overwrite:
        return "skipped"
    sessions_root = plan["sessions_root"]
    root_existed = os.path.isdir(sessions_root)
    created_root = not root_existed
    created_dir = not os.path.isdir(session_dir)
    if not root_existed:
        os.makedirs(sessions_root, mode=0o700)
    try:
        write_session_file(path, plan["header"], plan["events"], compress=True)
    except BaseException:
        if created_dir:
            shutil.rmtree(session_dir, ignore_errors=True)
        if created_root:
            shutil.rmtree(sessions_root, ignore_errors=True)
        raise
    return "written"


def _workspace_document(dsh_home):
    """Load workspace.json.  Returns (path, data_or_None, error_message)."""
    ws_path = os.path.join(os.path.expanduser(dsh_home), "storages", "workspace.json")
    if not os.path.isfile(ws_path):
        return ws_path, None, "workspace.json not found (%s)" % ws_path
    try:
        with open(ws_path, "r", encoding="utf-8") as f:
            return ws_path, json.load(f), ""
    except (OSError, ValueError) as exc:
        return ws_path, None, "cannot read workspace.json: %s" % exc


def _matching_workspace(data, cwd):
    """Return the workspace whose realpath(path) == realpath(cwd), else None."""
    workspaces = ((data.get("tables") or {}).get("workspaces")) or {}
    target = os.path.realpath(cwd)
    for _wid, w in workspaces.items():
        try:
            if w.get("path") and os.path.realpath(w["path"]) == target:
                return w
        except OSError:
            continue
    return None


def registration_plan(dsh_home, cwd, session_id):
    """Read-only classification of what --register would do (used by --dry-run)."""
    _ws_path, data, err = _workspace_document(dsh_home)
    if data is None:
        return "skipped", err
    match = _matching_workspace(data, cwd)
    if match is None:
        return "skipped", "no workspace with path==%s; session would appear under Ungrouped" % cwd
    ids = match.get("sessionIds") or []
    if session_id in ids:
        return "already", "already registered in workspace %r" % match.get("title")
    return "would-register", "front-insert into workspace %r sessionIds" % match.get("title")


def register_in_workspace(dsh_home, cwd, session_id):
    """Idempotently front-insert session_id into the workspace.json entry whose path == cwd.

    Backs up workspace.json first; edits only the matching workspace; atomic replace.
    Requires DSH to be stopped (in-memory state is authoritative while running).
    Idempotent: if the id is already registered, nothing is written and no backup is made.
    """
    ws_path, data, err = _workspace_document(dsh_home)
    if data is None:
        return "skipped", err
    match = _matching_workspace(data, cwd)
    if match is None:
        return "skipped", "no workspace with path==%s; session will appear under Ungrouped" % cwd
    ids = match.setdefault("sessionIds", [])
    if session_id in ids:
        return "already", "session already registered in workspace %r" % match.get("title")
    backup = ws_path + ".bak." + str(int(now_ms()))
    shutil.copy2(ws_path, backup)
    ids.insert(0, session_id)
    match["updatedAt"] = iso_now()
    fd, tmp = tempfile.mkstemp(prefix=".asi-workspace-", dir=os.path.dirname(ws_path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, ws_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return "registered", "backup: %s" % backup


# --------------------------------------------------------------------------- verify
def _frames(data):
    """Return list of (start, end) candidate zstd frame byte ranges at magic positions."""
    magic = b"\x28\xb5\x2f\xfd"
    pos = []
    i = 0
    while True:
        j = data.find(magic, i)
        if j < 0:
            break
        pos.append(j)
        i = j + 4
    return pos


def _split_first_frame(data):
    """Try to isolate the first frame at a magic boundary and decompress it."""
    magic = b"\x28\xb5\x2f\xfd"
    if not data.startswith(magic):
        return None
    pos = []
    i = 1
    while i < len(data):
        j = data.find(magic, i)
        if j < 0:
            break
        pos.append(j)
        i = j + 4
    for p in pos[:8]:
        try:
            dec = zcat(data[:p])
        except RuntimeError:
            continue
        return dec, p
    return None


def _check_header(header):
    errors = []
    if not isinstance(header, dict):
        return ["header is not a JSON object"]
    extra = set(header) - HEADER_KEYS
    if extra:
        errors.append("header has forbidden extra key(s): %s" % ", ".join(sorted(extra)))
    for key in ("type", "version", "id", "createdAt", "isSeeded", "delegationDepth"):
        if key not in header:
            errors.append("header missing required key %r" % key)
    if header.get("type") != "session":
        errors.append("header.type must be 'session'")
    if header.get("version") != 4:
        errors.append("header.version must be 4")
    if not isinstance(header.get("id"), str) or not header.get("id"):
        errors.append("header.id must be a non-empty string")
    if not isinstance(header.get("createdAt"), int) or isinstance(header.get("createdAt"), bool) or header.get("createdAt", -1) < 0:
        errors.append("header.createdAt must be a non-negative integer (epoch ms)")
    if "cwd" in header:
        cwd = header["cwd"]
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            errors.append("header.cwd must be an absolute path string")
    if not isinstance(header.get("isSeeded"), bool):
        errors.append("header.isSeeded must be a boolean")
    if not isinstance(header.get("delegationDepth"), int) or header.get("delegationDepth", -1) < 0:
        errors.append("header.delegationDepth must be a non-negative integer")
    for retired in ("sandboxMode", "approvalPolicy"):
        if retired in header:
            errors.append("header contains retired field %r" % retired)
    return errors


def _check_events(events):
    errors, warnings = [], []
    if not events:
        return errors, warnings, {}
    seq_ok = True
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            errors.append("event #%d is not an object" % i)
            continue
        if ev.get("seq") != i:
            seq_ok = False
    if not seq_ok:
        errors.append("event seq is not contiguous from 0")
    surface_seqs = []
    calls = {}      # callId -> seq
    results = {}    # callId -> seq
    block_calls = []  # (seq, callId)
    for i, ev in enumerate(events):
        etype = ev.get("type")
        seq = ev.get("seq")
        if not isinstance(etype, str) or not etype:
            errors.append("event #%d missing type" % i)
            continue
        if etype not in KNOWN_EVENT_TYPES and ev.get("ignorable") is not True:
            errors.append("event #%d unknown type %r without ignorable:true" % (i, etype))
        bad_keys = set(ev) - ENVELOPE_KEYS
        if bad_keys:
            errors.append("event seq=%s has unknown envelope key(s): %s" % (seq, ",".join(sorted(bad_keys))))
        if not isinstance(ev.get("time"), int) or ev.get("time", -1) < 0:
            errors.append("event seq=%s invalid time" % seq)
        if not isinstance(ev.get("data"), dict):
            errors.append("event seq=%s data must be an object" % seq)
            continue
        data = ev["data"]
        if etype in SURFACE_EVENTS:
            surface_seqs.append(seq)
            if ev.get("surfaceOp") != "append":
                errors.append("surface event %s seq=%s missing surfaceOp:'append'" % (etype, seq))
            if "sourceEventSeqs" in ev and etype != "assistant/message" and etype != "tool/result":
                pass  # allowed by envelope schema for tool/result
        else:
            if "surfaceOp" in ev:
                errors.append("log-only event %s seq=%s must not carry surfaceOp" % (etype, seq))
        if etype == "user/message":
            if data.get("role") != "user":
                errors.append("user/message seq=%s role must be 'user'" % seq)
            if not isinstance(data.get("id"), str) or not data.get("id"):
                errors.append("user/message seq=%s missing id" % seq)
            if not isinstance(data.get("source"), dict) or not data["source"].get("kind"):
                errors.append("user/message seq=%s missing source.kind" % seq)
            if not isinstance(data.get("content"), list):
                errors.append("user/message seq=%s content must be a list" % seq)
        elif etype == "assistant/message":
            for key in ("turn", "step"):
                if not isinstance(data.get(key), int):
                    errors.append("assistant/message seq=%s missing int %s" % (seq, key))
            if not isinstance(data.get("stream"), list):
                errors.append("assistant/message seq=%s stream must be a list" % seq)
            msg = data.get("message")
            if not isinstance(msg, dict):
                errors.append("assistant/message seq=%s missing message" % seq)
                continue
            if msg.get("role") != "assistant":
                errors.append("assistant/message seq=%s message.role must be 'assistant'" % seq)
            src = msg.get("source") or {}
            if src.get("kind") != "model" or not src.get("provider") or not src.get("model"):
                errors.append("assistant/message seq=%s source must be model+provider+model" % seq)
            if not isinstance(msg.get("id"), str) or not msg.get("id"):
                errors.append("assistant/message seq=%s missing message id" % seq)
            if not isinstance(msg.get("content"), list):
                errors.append("assistant/message seq=%s message.content must be a list" % seq)
                continue
            for blk in msg["content"]:
                if isinstance(blk, dict) and blk.get("type") == "tool-call":
                    cid = blk.get("id")
                    if not isinstance(cid, str) or not cid:
                        errors.append("assistant/message seq=%s tool-call block missing id" % seq)
                        continue
                    if not isinstance(blk.get("arguments"), str):
                        errors.append("assistant/message seq=%s tool-call arguments must be a JSON string" % seq)
                    block_calls.append((seq, cid))
            usage = data.get("usage")
            if usage is not None:
                if not isinstance(usage, dict):
                    errors.append("assistant/message seq=%s usage must be an object" % seq)
                else:
                    for key in ("inputTokens", "outputTokens"):
                        if not isinstance(usage.get(key), int):
                            errors.append("assistant/message seq=%s usage.%s must be int" % (seq, key))
        elif etype == "tool/call":
            for key in ("callId", "name"):
                if not isinstance(data.get(key), str) or not data.get(key):
                    errors.append("tool/call seq=%s missing %s" % (seq, key))
            for key in ("turn", "step"):
                if not isinstance(data.get(key), int):
                    errors.append("tool/call seq=%s missing int %s" % (seq, key))
            if not isinstance(data.get("arguments"), str):
                errors.append("tool/call seq=%s arguments must be a string" % seq)
            cid = data.get("callId")
            if cid:
                if cid in calls:
                    errors.append("duplicate tool/call callId %r (seq %s and %s)" % (cid, calls[cid], seq))
                calls[cid] = seq
        elif etype == "tool/result":
            for key in ("turn", "step"):
                if not isinstance(data.get(key), int):
                    errors.append("tool/result seq=%s missing int %s" % (seq, key))
            msg = data.get("message") or {}
            src = msg.get("source") or {}
            cid = msg.get("toolCallId")
            if msg.get("role") != "tool":
                errors.append("tool/result seq=%s message.role must be 'tool'" % seq)
            if src.get("kind") != "tool" or not src.get("callId"):
                errors.append("tool/result seq=%s message.source must be tool+callId" % seq)
            elif cid and src.get("callId") != cid:
                errors.append("tool/result seq=%s source.callId != toolCallId" % seq)
            if not isinstance(cid, str) or not cid:
                errors.append("tool/result seq=%s missing toolCallId" % seq)
            if not isinstance(msg.get("content"), list):
                errors.append("tool/result seq=%s message.content must be a list" % seq)
            refs = ev.get("sourceEventSeqs")
            if refs is not None:
                if not isinstance(refs, list) or not refs:
                    errors.append("tool/result seq=%s sourceEventSeqs must be a non-empty list" % seq)
                else:
                    for r in refs:
                        if not isinstance(r, int) or not (0 <= r < seq):
                            errors.append("tool/result seq=%s sourceEventSeqs references %r" % (seq, r))
                    if cid and cid in calls and calls[cid] not in refs:
                        warnings.append(
                            "tool/result seq=%s sourceEventSeqs should reference tool/call seq %s"
                            % (seq, calls[cid])
                        )
            if cid:
                if cid in results:
                    errors.append("duplicate tool/result for callId %r" % cid)
                results[cid] = seq
        elif etype == "session/title":
            if not isinstance(data.get("title"), str):
                errors.append("session/title seq=%s title must be a string" % seq)
            if not isinstance(data.get("messageSeqs"), list) or not all(
                isinstance(x, int) for x in data.get("messageSeqs")
            ):
                errors.append("session/title seq=%s messageSeqs must be an int list" % seq)
            src = data.get("source") or {}
            if src.get("kind") not in ("fallback", "user", "provider"):
                warnings.append("session/title seq=%s source.kind %r not in fallback/user/provider" % (seq, src.get("kind")))
        elif etype == "turn/end":
            params = data.get("reason") or {}
            kind = params.get("kind")
            if kind not in ("completed", "blocked", "interrupted", "max-tokens", "forked", "error", "aborted"):
                errors.append("turn/end seq=%s invalid reason %r" % (seq, kind))
            if not isinstance(data.get("turn"), int):
                errors.append("turn/end seq=%s missing int turn" % seq)
        elif etype in ("turn/start", "step/start", "step/end"):
            if not isinstance(data.get("turn"), int):
                errors.append("%s seq=%s missing int turn" % (etype, seq))
            if etype != "turn/start" and not isinstance(data.get("step"), int):
                errors.append("%s seq=%s missing int step" % (etype, seq))
        elif etype in ("permission/preset", "sandbox/mode", "approval/policy", "session/end-seed"):
            pass

    for seq, cid in block_calls:
        if cid not in calls:
            errors.append("assistant tool-call %r (seq %s) has no matching tool/call event" % (cid, seq))
        elif cid not in results:
            errors.append("assistant tool-call %r (seq %s) has no matching tool/result" % (cid, seq))
    for cid, cseq in calls.items():
        if cid not in results:
            errors.append("tool/call %r (seq %s) has no matching tool/result" % (cid, cseq))
    for cid, rseq in results.items():
        if cid not in calls:
            errors.append("tool/result %r (seq %s) has no matching tool/call" % (cid, rseq))

    has_turn_start = any(ev.get("type") == "turn/start" for ev in events)
    if surface_seqs and not has_turn_start:
        warnings.append("no turn/start event: session will load but be hidden as blank in the sidebar")
    if events and events[-1].get("type") != "session/end-seed":
        warnings.append("last event is not session/end-seed (DSH appends one in memory)")
    return errors, warnings, {"events": len(events), "surface": len(surface_seqs), "tool_calls": len(calls), "tool_results": len(results)}


def verify_file(path):
    """Verify one DSH session artifact (zstd file, plain jsonl, or session dir)."""
    report = {"path": path, "errors": [], "warnings": [], "info": {}}
    if os.path.isdir(path):
        found = None
        for name in ("session.v4.jsonl.zstd", "session.v4.jsonl"):
            cand = os.path.join(path, name)
            if os.path.isfile(cand):
                found = cand
                break
        if not found:
            report["errors"].append("no session.v4.jsonl[.zstd] in directory %s" % path)
            return report
        path = found
        report["path"] = path
    if not os.path.isfile(path):
        report["errors"].append("file not found: %s" % path)
        return report
    if path.endswith(".zstd"):
        with open(path, "rb") as f:
            raw = f.read()
        pos = _frames(raw)
        report["info"]["zstd_magic_count"] = len(pos)
        if not raw.startswith(b"\x28\xb5\x2f\xfd"):
            report["errors"].append("file does not start with a zstd frame magic")
            return report
        split = _split_first_frame(raw)
        if split is None:
            report["errors"].append("could not isolate/decrypt the first zstd frame at a magic boundary")
            return report
        dec, start_of_second = split
        nl = dec.count(b"\n")
        if nl != 1 or not dec.endswith(b"\n"):
            report["errors"].append("first zstd frame must decode to exactly one header line with trailing LF")
        if len(pos) < 2:
            report["errors"].append("file has only one zstd frame; events must be in separate frame(s)")
        try:
            whole = zcat(raw)
        except RuntimeError as exc:
            report["errors"].append(str(exc))
            return report
        report["info"]["frames"] = len(pos)
        report["info"]["header_frame_bytes"] = start_of_second
        lines = [ln for ln in whole.split(b"\n") if ln.strip()]
    else:
        with open(path, "rb") as f:
            lines = [ln for ln in f.read().split(b"\n") if ln.strip()]
    if not lines:
        report["errors"].append("empty session file")
        return report
    try:
        header = json.loads(lines[0])
    except ValueError as exc:
        report["errors"].append("header line is not valid JSON: %s" % exc)
        return report
    report["errors"].extend(_check_header(header))
    events = []
    for i, line in enumerate(lines[1:], 1):
        try:
            events.append(json.loads(line))
        except ValueError as exc:
            report["errors"].append("event line %d is not valid JSON: %s" % (i, exc))
    e_errors, e_warnings, info = _check_events(events)
    report["errors"].extend(e_errors)
    report["warnings"].extend(e_warnings)
    report["info"].update(info)
    report["header"] = {k: header.get(k) for k in ("id", "cwd", "createdAt", "version")}

    # physical identity: session dir / project dir must match header id/cwd
    session_dir = os.path.dirname(os.path.abspath(path))
    project_dir = os.path.dirname(session_dir)
    session_dir_name = os.path.basename(session_dir)
    project_dir_name = os.path.basename(project_dir)
    hid = header.get("id")
    hcwd = header.get("cwd")
    in_dsh_layout = project_dir_name.startswith("--") and project_dir_name.endswith("--")
    if in_dsh_layout:
        if hid and session_dir_name != encode_segment(hid):
            report["errors"].append(
                "corrupt session log: session dir %r != encodeSegment(header.id) %r"
                % (session_dir_name, encode_segment(hid))
            )
        if hcwd:
            expected = project_key(hcwd)
            if project_dir_name != expected:
                report["errors"].append(
                    "corrupt session log: project dir %r != projectKey(header.cwd) %r"
                    % (project_dir_name, expected)
                )
    return report


def discover_artifacts(paths):
    """Expand files/dirs into DSH session artifact files."""
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            direct = [os.path.join(p, n) for n in ("session.v4.jsonl.zstd", "session.v4.jsonl")]
            direct = [d for d in direct if os.path.isfile(d)]
            if direct:
                out.extend(direct)
                continue
            for name in ("session.v4.jsonl.zstd", "session.v4.jsonl"):
                out.extend(sorted(glob.glob(os.path.join(p, "**", name), recursive=True)))
        else:
            out.append(p)
    return out
