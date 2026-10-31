"""WorkBuddy native reader (JSONL event log; format cross-checked with agenttrace).

Layout (observed by agenttrace ``parse_workbuddy_jsonl``):
    ``~/.workbuddy/projects/**/*.jsonl`` (``WORKBUDDY_HOME`` override may point at the
    projects root or at an individual session file).
Each session is one JSONL file; line ``type`` is ``message`` / ``reasoning`` /
``function_call`` / ``function_call_result`` and carries ``sessionId``, ``cwd``,
``timestamp`` and ``providerData.model``.

Evidence: reader implementation for the native format; no local store is
available on this machine, so detection remains ``detected=false`` until the
store/env exists. Reader-only: there is no native writer yet.
"""
import glob
import json
import os

from ..ir import add_event, finalize, new_ir, normalize_usage, text_block, touch_ts, warn


def default_root():
    home = os.path.expanduser("~")
    override = os.environ.get("WORKBUDDY_HOME") or os.environ.get("WORKBUDDY_SESSION_DIR")
    if override:
        return os.path.expanduser(override)
    return os.path.join(home, ".workbuddy", "projects")


def _files(root):
    root = os.path.expanduser(root or default_root())
    if os.path.isfile(root):
        return [root]
    if not os.path.isdir(root):
        return []
    return sorted(f for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
                  if os.path.isfile(f))


def _docs(path):
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                rows.append({"__parse_error__": line[:80]})
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _text(content):
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    out.append(b["text"])
                elif b.get("type") == "input_text" and isinstance(b.get("text"), str):
                    out.append(b["text"])
    elif isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
    return "\n".join(out)


def _model(rows):
    for row in rows:
        data = row.get("providerData")
        if isinstance(data, dict) and isinstance(data.get("model"), str) and data["model"]:
            return data["model"]
        if isinstance(row.get("model"), str) and row["model"]:
            return row["model"]
    return ""


def _session_id(rows, path):
    for row in rows:
        if isinstance(row.get("sessionId"), str) and row["sessionId"]:
            return row["sessionId"]
    return os.path.splitext(os.path.basename(path))[0]


def _usage(rows):
    for row in rows:
        raw = None
        if isinstance(row.get("message"), dict):
            raw = row["message"].get("usage")
        if raw is None and isinstance(row.get("providerData"), dict):
            raw = row["providerData"].get("usage")
        usage = normalize_usage(raw)
        if usage:
            return usage
    return None


def list_sessions(root=None):
    root = os.path.expanduser(root or default_root())
    out = []
    for path in _files(root):
        rows = _docs(path)
        if not rows or any("__parse_error__" in r for r in rows):
            # tolerate a single malformed file: keep the rest of the store listable
            rows = [r for r in rows if "__parse_error__" not in r]
            if not rows:
                continue
        cwd = next((r.get("cwd") for r in rows if isinstance(r.get("cwd"), str)), None)
        ts = [r.get("timestamp") for r in rows if isinstance(r.get("timestamp"), (int, float))]
        title = ""
        for row in rows:
            if row.get("type") == "message" and row.get("role") in ("user", "human"):
                text = _text(row.get("content")).strip()
                if text:
                    title = text.splitlines()[0][:120]
                    break
        out.append({
            "source": "workbuddy",
            "id": _session_id(rows, path),
            "title": title or os.path.basename(path),
            "cwd": cwd,
            "created_at_ms": int(min(ts)) if ts else int(os.path.getmtime(path) * 1000),
            "updated_at_ms": int(max(ts)) if ts else int(os.path.getmtime(path) * 1000),
            "path": path,
            "lines": len(rows),
            "model": _model(rows),
        })
    out.sort(key=lambda r: (r.get("updated_at_ms") or 0, r.get("id") or ""), reverse=True)
    return out


def resolve_path(root, session=None):
    root = os.path.expanduser(root or default_root())
    for row in list_sessions(root):
        if str(row.get("id")) == str(session) or os.path.basename(row.get("path") or "") == str(session):
            return row["path"]
    if session and os.path.isfile(os.path.expanduser(str(session))):
        return os.path.expanduser(str(session))
    return None


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or default_root())
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("workbuddy session not found for %r under %s" % (session, root))
    rows = _docs(path)
    sid = _session_id(rows, path)
    cwd = next((r.get("cwd") for r in rows if isinstance(r.get("cwd"), str)), None)
    timestamps = [r.get("timestamp") for r in rows if isinstance(r.get("timestamp"), (int, float))]
    ir = new_ir("workbuddy", sid, path, cwd=cwd,
                created_at_ms=int(min(timestamps)) if timestamps else None)
    ir["provider"] = "workbuddy"
    ir["model"] = _model(rows)
    warnings = ir["warnings"]
    last_assistant = None
    for row in rows:
        if "__parse_error__" in row:
            warn(ir, "skipped malformed workbuddy line")
            continue
        ts = row.get("timestamp") if isinstance(row.get("timestamp"), (int, float)) else None
        touch_ts(ir, ts)
        rtype = row.get("type")
        if rtype == "message":
            role = row.get("role") or ""
            text = _text(row.get("content")).strip()
            if not text:
                continue
            if role in ("user", "human"):
                add_event(ir, "user_message", ts, blocks=[text_block(text)])
            elif role == "assistant":
                add_event(ir, "assistant_message", ts, blocks=[text_block(text)])
                last_assistant = ir["events"][-1]
            elif role in ("system", "developer") and keep_system:
                add_event(ir, "system_message", ts, text=text)
        elif rtype == "reasoning":
            text = _text(row.get("content") if row.get("content") else row.get("rawContent")).strip()
            if text:
                add_event(ir, "assistant_message", ts,
                          blocks=[{"type": "reasoning", "text": text}])
                last_assistant = ir["events"][-1]
        elif rtype == "function_call":
            args = row.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            add_event(ir, "assistant_message", ts, blocks=[{
                "type": "tool-call",
                "id": str(row.get("callId") or ""),
                "name": str(row.get("name") or "tool"),
                "arguments": args,
            }])
            last_assistant = ir["events"][-1]
        elif rtype == "function_call_result":
            output = row.get("output")
            if isinstance(output, str):
                result_text = output
            else:
                result_text = json.dumps(output if output is not None else "", ensure_ascii=False)
            add_event(ir, "tool_result", ts,
                      call_id=str(row.get("callId") or ""),
                      name=str(row.get("name") or "tool"),
                      content=result_text,
                      is_error=str(row.get("status") or "completed").lower() not in ("completed", "success", "ok"))
        else:
            warn(ir, "unsupported workbuddy record type: %r" % (rtype,))
    usage = _usage(rows)
    if usage:
        ir["source_usage"] = usage
        if last_assistant is not None:
            last_assistant["usage"] = usage
    ir["extra"] = {
        "evidence_level": "NATIVE-FORMAT (store unavailable on this machine)",
        "native_layout": "~/.workbuddy/projects/**/*.jsonl",
        "format_source": "agenttrace parser.rs::parse_workbuddy_jsonl (MIT)",
        "reader_only": True,
    }
    finalize(ir)
    return ir
