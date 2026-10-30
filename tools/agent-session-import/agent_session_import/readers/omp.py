"""OMP / oh-my-pi (~/.omp/agent/sessions) reader.

Each session file is a *tree* event stream: every entry has an ``id`` and a ``parentId``;
the first two lines are always ``title`` and ``session`` metadata (the ``title`` line may be
rewritten in place, so line order != time order).  The current branch is the path from the
newest leaf (no children, max timestamp) back to the root via ``parentId``.

Line layout: ``<root>/<project-slug>/<ISO>_<uuid>.jsonl`` for main sessions; nested
``<session-id>/<Child>.jsonl`` files are sub-agent transcripts and are NOT main sessions.
"""
import glob
import json
import os

from ..common import HOME, count_lines, iso_to_ms, read_jsonl
from ..ir import add_event, finalize, new_ir, text_block, touch_ts, warn

DEFAULT_ROOT = os.path.join(HOME, ".omp", "agent", "sessions")

_MAIN_GLOB = "*/*.jsonl"


def default_root():
    return DEFAULT_ROOT


def _main_files(root):
    return [f for f in glob.glob(os.path.join(root, _MAIN_GLOB)) if os.path.isfile(f)]


def _head_meta(path):
    """Read the first two lines (title, session) only."""
    title = None
    header = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(3):
                line = f.readline()
                if not line:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                t = o.get("type")
                if t == "title":
                    title = o
                elif t == "session":
                    header = o
    except OSError:
        return None, None
    return title, header


def _content_blocks(content):
    """OMP message.content[] -> IR blocks."""
    blocks = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            txt = b.get("text")
            if isinstance(txt, str) and txt:
                blocks.append(text_block(txt))
        elif bt == "thinking":
            txt = b.get("thinking") or b.get("text") or ""
            if isinstance(txt, str) and txt:
                blocks.append({"type": "reasoning", "text": txt})
        elif bt == "toolCall":
            cid = b.get("id") or ""
            args = b.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            blocks.append({"type": "tool-call", "id": cid, "name": b.get("name") or "tool", "arguments": args})
        elif bt in ("image", "image_url"):
            blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
    return blocks


def _result_content(msg):
    texts = []
    for b in msg.get("content") or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            texts.append(b["text"])
        elif b.get("type") == "image":
            texts.append("[image attachment not imported]")
    if texts:
        return "\n".join(texts)
    return ""


# --------------------------------------------------------------------------- index
def list_sessions(root=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    out = []
    for path in _main_files(root):
        title_row, header = _head_meta(path)
        sid = (header or {}).get("id") or os.path.basename(path).rsplit("_", 1)[-1][:-6]
        title = (title_row or {}).get("title") or (header or {}).get("title") or ""
        created = iso_to_ms((header or {}).get("timestamp"))
        try:
            lines = count_lines(path)
        except OSError:
            lines = 0
        out.append(
            {
                "source": "omp",
                "id": sid,
                "title": title[:120],
                "cwd": (header or {}).get("cwd"),
                "created_at_ms": created,
                "updated_at_ms": int(os.path.getmtime(path) * 1000),
                "path": path,
                "lines": lines,
                "model": "",
            }
        )
    out.sort(key=lambda r: r["updated_at_ms"] or 0, reverse=True)
    return out


def resolve_path(root, session=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        for path in _main_files(root):
            if session in os.path.basename(path):
                return path
        for path in _main_files(root):
            _title, header = _head_meta(path)
            if (header or {}).get("id") == session:
                return path
    files = _main_files(root)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


# --------------------------------------------------------------------------- convert
def load_session(root=None, session=None, path=None, keep_system=False):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("omp session not found for session=%r root=%s" % (session, root))

    bad = []
    rows = read_jsonl(path, bad)
    title = None
    header = None
    entries = []
    for idx, o in rows:
        t = o.get("type")
        if t == "title":
            title = o
        elif t == "session":
            header = o
        else:
            o["_line"] = idx
            entries.append(o)

    ir = new_ir("omp", (header or {}).get("id") or os.path.basename(path).rsplit("_", 1)[-1][:-6], path)
    ir["cwd"] = (header or {}).get("cwd")
    created = iso_to_ms((header or {}).get("timestamp"))
    ir["created_at_ms"] = created
    ir["updated_at_ms"] = created

    # ---- build tree and pick newest leaf ----
    by_id = {}
    children = {}
    for e in entries:
        eid = e.get("id")
        if not eid:
            continue
        by_id[eid] = e
        children.setdefault(eid, [])
        pid = e.get("parentId")
        if pid:
            children.setdefault(pid, []).append(eid)
    leaves = [e for e in entries if e.get("id") and not children.get(e["id"])]

    def sort_key(e):
        return (e.get("timestamp") or "", e.get("_line") or 0)

    leaf = max(leaves, key=sort_key) if leaves else (max(entries, key=sort_key) if entries else None)
    path_entries = []
    cur = leaf
    guard = 0
    while cur is not None and guard < 1000000:
        path_entries.append(cur)
        pid = cur.get("parentId")
        cur = by_id.get(pid) if pid else None
        guard += 1
    path_entries.reverse()

    current_model = ""
    first_provider = ""
    skipped = 0
    for e in path_entries:
        t = e.get("type")
        ts = iso_to_ms(e.get("timestamp"))
        touch_ts(ir, ts)
        if t == "message":
            msg = e.get("message") or {}
            role = msg.get("role")
            if role == "user":
                blocks = _content_blocks(msg.get("content"))
                if blocks:
                    add_event(ir, "user_message", ts, blocks=blocks)
            elif role == "assistant":
                blocks = _content_blocks(msg.get("content"))
                if blocks:
                    add_event(
                        ir,
                        "assistant_message",
                        ts,
                        blocks=blocks,
                        model=msg.get("model") or current_model or "",
                        provider=msg.get("provider") or first_provider or "omp",
                        usage=msg.get("usage"),
                    )
                    first_provider = first_provider or msg.get("provider") or ""
            elif role == "toolResult":
                add_event(
                    ir,
                    "tool_result",
                    ts,
                    call_id=msg.get("toolCallId") or "",
                    name=msg.get("toolName") or "tool",
                    content=_result_content(msg),
                    is_error=bool(msg.get("isError")),
                )
            elif role == "developer":
                if keep_system:
                    text = "\n".join(
                        b.get("text", "") for b in msg.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"
                    )
                    if text:
                        add_event(ir, "system_message", ts, text=text, origin="developer")
            else:
                skipped += 1
        elif t == "custom_message":
            if keep_system:
                content = e.get("content")
                if isinstance(content, str) and content:
                    add_event(ir, "system_message", ts, text=content, origin=e.get("customType") or "custom_message")
            else:
                skipped += 1
        elif t == "compaction":
            add_event(
                ir,
                "compaction",
                ts,
                summary=e.get("summary") or "",
                extra={
                    "shortSummary": e.get("shortSummary"),
                    "tokensBefore": e.get("tokensBefore"),
                    "tokensAfter": e.get("tokensAfter"),
                    "method": e.get("method"),
                },
            )
        elif t == "session_init":
            if keep_system and isinstance(e.get("systemPrompt"), str):
                ir["system_prompt"] = e["systemPrompt"]
        elif t == "model_change":
            current_model = e.get("model") or current_model
        elif t == "title_change":
            if e.get("title"):
                title = {"title": e["title"]}
        else:
            skipped += 1

    if not ir.get("cwd") and header and header.get("cwd"):
        ir["cwd"] = header["cwd"]
    fallback_title = (title or {}).get("title") or (header or {}).get("title") or ""
    finalize(ir, fallback_title=fallback_title, model=current_model, provider=first_provider or "omp")
    if bad:
        warn(ir, "%d malformed JSONL line(s) skipped" % len(bad))
    if skipped:
        warn(ir, "%d non-conversation tree entry(ies) on active path skipped" % skipped)
    unpaired = ir["stats"]["unpaired_tool_calls"]
    if unpaired:
        warn(ir, "%d tool call(s) had no result on active path (placeholder will be written)" % unpaired)
    return ir
