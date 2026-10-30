"""DSH v4 reader: session.v4.jsonl(.zstd) -> IR.

Folds surface events back into a linear conversation: user/message -> user_message,
assistant/message (content parts text/reasoning/tool-call) -> assistant_message,
tool/result -> tool_result (callId pairing), session/title -> title; log-only events
(job/*, request/*, turn/step, policies, session/end-seed ...) are ignored.
"""
import glob
import json
import os
import re

from .. import dsh as _dsh
from ..common import HOME, count_lines
from ..ir import MISSING_RESULT_TEXT, add_event, finalize, new_ir, text_block, touch_ts, warn

DEFAULT_ROOT = os.path.join(HOME, ".dsh", "sessions")

_GEN_RE = re.compile(r"^session(?:\.v(\d+))?\.jsonl(\.zstd)?$")


def default_root():
    return DEFAULT_ROOT


def _best_generation(session_dir):
    cands = []
    try:
        names = os.listdir(session_dir)
    except OSError:
        return None
    for name in names:
        m = _GEN_RE.match(name)
        if not m:
            continue
        ver = int(m.group(1)) if m.group(1) else 0
        cands.append((ver, os.path.join(session_dir, name)))
    if not cands:
        return None
    cands.sort()
    return cands[-1][1]


def _session_files(root):
    files = []
    for proj in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(proj):
            continue
        for sess in sorted(glob.glob(os.path.join(proj, "*"))):
            if not os.path.isdir(sess):
                continue
            best = _best_generation(sess)
            if best:
                files.append(best)
    return files


def read_lines(path):
    """Return (header, [event dicts]) for a DSH session file."""
    with open(path, "rb") as f:
        raw = f.read()
    data = _dsh.zcat(raw) if path.endswith(".zstd") else raw
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    if not lines:
        raise ValueError("empty session file: %s" % path)
    objs = [json.loads(ln.decode("utf-8")) for ln in lines]
    return objs[0], objs[1:]


def _read_header_only(path):
    with open(path, "rb") as f:
        raw = f.read()
    if path.endswith(".zstd"):
        split = _dsh._split_first_frame(raw)
        if split is None:
            raise ValueError("cannot isolate header frame")
        dec = split[0]
        line = dec.split(b"\n")[0]
        return json.loads(line.decode("utf-8"))
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.readline())


def list_sessions(root=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    out = []
    for path in _session_files(root):
        try:
            header, events = read_lines(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        title = ""
        updated = header.get("createdAt")
        model = ""
        for ev in events:
            etype = ev.get("type")
            if etype == "session/title":
                t = (ev.get("data") or {}).get("title")
                if t:
                    title = t
            elif etype == "assistant/message" and not model:
                msg = (ev.get("data") or {}).get("message") or {}
                model = (msg.get("source") or {}).get("model") or ""
            tm = ev.get("time")
            if isinstance(tm, (int, float)) and (updated is None or tm > updated):
                updated = tm
        out.append(
            {
                "source": "dsh",
                "id": header.get("id"),
                "title": title,
                "cwd": header.get("cwd"),
                "created_at_ms": header.get("createdAt"),
                "updated_at_ms": updated,
                "path": path,
                "lines": len(events),
                "model": model,
            }
        )
    out.sort(key=lambda r: r.get("updated_at_ms") or 0, reverse=True)
    return out


def resolve_path(root, session=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        for path in _session_files(root):
            if os.path.basename(os.path.dirname(path)) in (session, _dsh.encode_segment(session)):
                return path
        for path in _session_files(root):
            try:
                if _read_header_only(path).get("id") == session:
                    return path
            except (OSError, ValueError):
                continue
    rows = list_sessions(root)
    return rows[0]["path"] if rows else None


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("dsh session not found for session=%r root=%s" % (session, root))
    header, events = read_lines(path)
    events.sort(key=lambda ev: ev.get("seq", 0))
    ir = new_ir("dsh", header.get("id") or "", path)
    ir["cwd"] = header.get("cwd")
    ir["created_at_ms"] = header.get("createdAt")
    calls = {}
    results = set()
    title = ""
    last_time = header.get("createdAt")
    turn_reason = None
    for ev in events:
        etype = ev.get("type")
        data = ev.get("data") or {}
        ts = ev.get("time")
        touch_ts(ir, ts)
        if isinstance(ts, (int, float)):
            last_time = ts
        if etype == "user/message":
            blocks = []
            for b in data.get("content") or []:
                bt = b.get("type")
                if bt == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                    blocks.append(text_block(b["text"]))
                elif bt == "image":
                    blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
            if blocks:
                add_event(ir, "user_message", ts, blocks=blocks, source_id=data.get("id"))
        elif etype == "assistant/message":
            msg = data.get("message") or {}
            src = msg.get("source") or {}
            blocks = []
            for b in msg.get("content") or []:
                bt = b.get("type")
                if bt == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                    blocks.append(text_block(b["text"]))
                elif bt == "reasoning" and isinstance(b.get("text"), str) and b["text"].strip():
                    blocks.append({"type": "reasoning", "text": b["text"]})
                elif bt == "tool-call":
                    args = b.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    cid = b.get("id") or ""
                    calls[cid] = b.get("name") or "tool"
                    blocks.append({"type": "tool-call", "id": cid,
                                   "name": b.get("name") or "tool", "arguments": args})
            if blocks:
                add_event(ir, "assistant_message", ts, blocks=blocks,
                          model=src.get("model") or "", provider=src.get("provider") or "",
                          usage=data.get("usage"), source_id=msg.get("id"))
        elif etype == "tool/result":
            msg = data.get("message") or {}
            cid = msg.get("toolCallId") or ""
            content = []
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text":
                    content.append(b.get("text") or "")
            results.add(cid)
            add_event(ir, "tool_result", ts, call_id=cid,
                      name=calls.get(cid) or "tool", content="\n".join(content),
                      is_error=bool(msg.get("isError") or data.get("error")))
        elif etype == "system/message" and keep_system:
            msg = data.get("message") or {}
            text = "\n".join(
                b.get("text") or "" for b in msg.get("content") or [] if isinstance(b, dict)
            )
            if text:
                add_event(ir, "system_message", ts, text=text, origin="dsh-system")
        elif etype == "session/title":
            t = data.get("title")
            if isinstance(t, str) and t:
                title = t
        elif etype == "turn/end":
            reason = data.get("reason") or {}
            kind = reason.get("kind")
            if kind in ("interrupted", "error", "cancelled", "aborted", "max-tokens", "forked"):
                turn_reason = kind
    # placeholder results keep the writer invariant (each tool call has a result)
    missing = [cid for cid in calls if cid not in results]
    for cid in missing:
        add_event(ir, "tool_result", last_time, call_id=cid, name=calls[cid],
                  content=MISSING_RESULT_TEXT, is_error=False)
    if turn_reason:
        add_event(ir, "turn_abort", last_time, reason=turn_reason)
    ir["title"] = title
    finalize(ir, fallback_title=title or None)
    if missing:
        warn(ir, "%d tool call(s) had no tool/result in source; placeholder kept" % len(missing))
    return ir
