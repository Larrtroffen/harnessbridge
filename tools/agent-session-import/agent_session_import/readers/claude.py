"""Claude Code (~/.claude/projects/<slug>/<uuid>.jsonl) reader.

Claude Code 2.1.x transcript layout (verified on real sessions on this machine):
rows are append-only JSONL.  Conversation rows are ``user`` / ``assistant`` / ``system``;
assistant rows carry a full ``message`` object (content array with text/thinking/tool_use
blocks); tool results are ``user`` rows with a ``tool_result`` content block paired by
``tool_use_id``.  Tree/branch state uses ``uuid``/``parentUuid``; the committed leaf is
given by the ``last-prompt`` rows' ``leafUuid`` (last occurrence wins).  Titles come from
``custom-title``/``ai-title`` rows (fallback: first human prompt).  Other row types are
bookkeeping (attachment, file-history-*, mode, permission-mode, atis-latch, agent-name,
cost-state, queue-operation) and are ignored.
"""
import glob
import json
import os
import re

from ..common import HOME, count_lines, iso_to_ms, read_jsonl
from ..ir import add_event, finalize, new_ir, text_block, touch_ts, warn

DEFAULT_ROOT = os.path.join(HOME, ".claude", "projects")

_BOOKKEEPING = {
    "attachment", "file-history-snapshot", "file-history-delta", "mode", "permission-mode",
    "atis-latch", "agent-name", "cost-state", "queue-operation", "summary",
}
_INJECTED_PREFIXES = (
    "[Request interrupted by user",
    "[SYSTEM NOTIFICATION",
    "This session is being continued from a previous conversation",
)


def default_root():
    return DEFAULT_ROOT


def slugify(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


def _main_files(root):
    return [f for f in glob.glob(os.path.join(root, "*", "*.jsonl")) if os.path.isfile(f)]


def _ms(o):
    return iso_to_ms(o.get("timestamp"))


def _texts(content):
    out = []
    if isinstance(content, str):
        if content.strip():
            out.append(content)
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                out.append(b["text"])
    return out


def _content_blocks(content):
    blocks = []
    if isinstance(content, str):
        if content.strip():
            blocks.append(text_block(content))
        return blocks
    for b in content or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text" and isinstance(b.get("text"), str) and b["text"].strip():
            blocks.append(text_block(b["text"]))
        elif bt == "image":
            blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
    return blocks


def _classify_user(o):
    msg = o.get("message") or {}
    content = msg.get("content")
    first = content[0] if isinstance(content, list) and content else None
    if isinstance(first, dict) and first.get("type") == "tool_result":
        return "tool_result"
    if o.get("isCompactSummary"):
        return "compact_summary"
    if o.get("isMeta"):
        return "injected"
    origin = (o.get("origin") or {}).get("kind")
    if origin in ("task-notification", "system"):
        return "injected"
    texts = "\n".join(_texts(content)).lstrip()
    if texts.startswith(_INJECTED_PREFIXES):
        return "injected"
    if isinstance(first, dict) and first.get("type") == "image":
        return "image"
    if origin in ("human", "bridge") or o.get("humanInput") is not None:
        return "human"
    if isinstance(content, str) and content.strip():
        # Claude Code 2.1.x stores human prompts as a plain string in some rows
        return "human" if o.get("promptId") and not o.get("isMeta") else "injected"
    if texts.strip():
        return "human"
    return "other"


# --------------------------------------------------------------------------- list
def list_sessions(root=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    out = []
    for path in _main_files(root):
        sid = os.path.basename(path)[:-6]
        title = ""
        cwd = None
        created = None
        model = ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= 400:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    t = o.get("type")
                    if cwd is None and o.get("cwd"):
                        cwd = o.get("cwd")
                    if created is None and o.get("timestamp") is not None:
                        created = _ms(o)
                    if t in ("custom-title", "ai-title") and not title:
                        title = o.get("customTitle") or o.get("title") or ""
                    if t == "assistant" and not model:
                        model = (o.get("message") or {}).get("model") or ""
                    if t == "last-prompt" and not title and o.get("lastPrompt"):
                        title = o["lastPrompt"]
        except OSError:
            continue
        try:
            lines = count_lines(path)
        except OSError:
            lines = 0
        out.append({
            "source": "claude", "id": sid, "title": (title or sid[:8])[:120], "cwd": cwd,
            "created_at_ms": created, "updated_at_ms": int(os.path.getmtime(path) * 1000),
            "path": path, "lines": lines, "model": model,
        })
    out.sort(key=lambda r: r["updated_at_ms"] or 0, reverse=True)
    return out


def resolve_path(root, session=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    if session:
        cand = os.path.expanduser(session)
        if os.path.isfile(cand):
            return cand
        hits = glob.glob(os.path.join(root, "*", session + ".jsonl"))
        if hits:
            return hits[0]
        for path in _main_files(root):
            if session in os.path.basename(path):
                return path
    files = _main_files(root)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


# --------------------------------------------------------------------------- convert
def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("claude transcript not found for session=%r root=%s" % (session, root))
    bad = []
    rows = read_jsonl(path, bad)
    sid = os.path.basename(path)[:-6]
    ir = new_ir("claude", sid, path)

    by_uuid = {}
    parent_of = {}
    groups = []
    group_mid = {}
    user_rows = []
    leaf_uuids = []
    title = ""
    last_prompt = ""
    first_ts = None
    for idx, o in rows:
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        uuid = o.get("uuid")
        if uuid:
            by_uuid[uuid] = (idx, o)
            parent_of[uuid] = o.get("parentUuid")
        if ir.get("cwd") is None and o.get("cwd"):
            ir["cwd"] = o["cwd"]
        if first_ts is None and o.get("timestamp") is not None:
            first_ts = _ms(o)
        if t == "assistant":
            msg = o.get("message") or {}
            mid = msg.get("id")
            g = group_mid.get(mid) if mid else None
            if g is None:
                g = {"id": mid, "idx": idx, "rows": [], "blocks": [],
                     "model": "", "usage": None}
                groups.append(g)
                if mid:
                    group_mid[mid] = g
            g["rows"].append((idx, o))
            g["idx"] = min(g["idx"], idx)
            g["model"] = msg.get("model") or g["model"]
            if msg.get("usage"):
                g["usage"] = msg["usage"]
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "thinking":
                    txt = b.get("thinking") or ""
                    if isinstance(txt, str) and txt.strip():
                        g["blocks"].append({"type": "reasoning", "text": txt})
                elif bt == "text":
                    txt = b.get("text")
                    if isinstance(txt, str) and txt.strip():
                        g["blocks"].append(text_block(txt))
                elif bt == "tool_use":
                    cid = b.get("id") or ""
                    args = b.get("input")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    g["blocks"].append({"type": "tool-call", "id": cid,
                                        "name": b.get("name") or "tool", "arguments": args})
        elif t == "user":
            user_rows.append((idx, o))
        elif t in ("custom-title", "ai-title"):
            v = o.get("customTitle") or o.get("title")
            if isinstance(v, str) and v:
                title = v
        elif t == "last-prompt":
            if o.get("leafUuid"):
                leaf_uuids.append(o["leafUuid"])
            if isinstance(o.get("lastPrompt"), str):
                last_prompt = o["lastPrompt"]
        elif t == "system" and keep_system and o.get("subtype") == "compact_boundary":
            add_event(ir, "compaction", _ms(o), summary=o.get("content") or "",
                      extra={"compactMetadata": o.get("compactMetadata")})
        touch_ts(ir, _ms(o))

    final_path = set()
    leaf = leaf_uuids[-1] if leaf_uuids else None
    if leaf and leaf in by_uuid:
        cur, guard = leaf, 0
        while cur and guard < 1000000:
            final_path.add(cur)
            cur = parent_of.get(cur)
            guard += 1
    if not final_path and by_uuid:
        cand = max(by_uuid.values(), key=lambda t: t[0])
        cur, guard = cand[1].get("uuid"), 0
        while cur and guard < 1000000:
            final_path.add(cur)
            cur = parent_of.get(cur)
            guard += 1

    kept_groups = [g for g in groups if any((o.get("uuid") in final_path) for _i, o in g["rows"])]
    kept_calls = {}
    for g in kept_groups:
        for b in g["blocks"]:
            if b["type"] == "tool-call":
                kept_calls[b["id"]] = b["name"]

    timeline = []
    for g in kept_groups:
        if not g["blocks"]:
            continue
        ts = _ms(g["rows"][-1][1]) or _ms(g["rows"][0][1])
        timeline.append((g["idx"], {"kind": "assistant_message", "ts": ts,
                                    "blocks": g["blocks"], "model": g["model"] or "",
                                    "provider": "claude", "usage": g["usage"]}))
    injected = compact = 0
    for idx, o in user_rows:
        cls = _classify_user(o)
        msg = o.get("message") or {}
        content = msg.get("content")
        if cls == "tool_result":
            first = content[0]
            cid = first.get("tool_use_id") or ""
            if cid not in kept_calls:
                continue
            inner = first.get("content")
            if isinstance(inner, str):
                text = inner
            else:
                text = "\n".join(_texts(inner)) or "[non-text tool result omitted]"
            timeline.append((idx, {"kind": "tool_result", "ts": _ms(o), "call_id": cid,
                                   "name": kept_calls.get(cid) or "tool", "content": text,
                                   "is_error": bool(first.get("is_error"))}))
        elif cls in ("human", "image"):
            if o.get("uuid") and o["uuid"] not in final_path:
                continue
            blocks = _content_blocks(content)
            if not blocks:
                continue
            timeline.append((idx, {"kind": "user_message", "ts": _ms(o), "blocks": blocks}))
        elif cls == "compact_summary":
            compact += 1
            if keep_system:
                text = "\n".join(_texts(content))
                if text:
                    add_event(ir, "system_message", _ms(o), text=text, origin="compact_summary")
        else:
            injected += 1
            if keep_system:
                text = "\n".join(_texts(content))
                if text:
                    add_event(ir, "system_message", _ms(o), text=text, origin=cls)
    timeline.sort(key=lambda t: t[0])
    for _idx, ev in timeline:
        kind = ev.pop("kind")
        add_event(ir, kind, ev.pop("ts", None), **ev)

    if not ir.get("cwd"):
        for g in kept_groups:
            c = g["rows"][0][1].get("cwd")
            if c:
                ir["cwd"] = c
                break
    if not ir["created_at_ms"] and first_ts:
        ir["created_at_ms"] = first_ts
    if not ir.get("model"):
        for g in kept_groups:
            if g["model"]:
                ir["model"] = g["model"]
                break
    finalize(ir, fallback_title=title or last_prompt)
    if bad:
        warn(ir, "%d malformed JSONL line(s) skipped" % len(bad))
    if injected:
        warn(ir, "%d injected/meta user row(s) skipped (use --keep-system to keep)" % injected)
    if compact:
        warn(ir, "%d compaction summary row(s) skipped (use --keep-system to keep)" % compact)
    result_ids = {ev["call_id"] for ev in ir["events"] if ev.get("kind") == "tool_result"}
    missing = [cid for cid in kept_calls if cid not in result_ids]
    if missing:
        warn(ir, "%d tool call(s) had no result in the selected branch (placeholder will be written)"
             % len(missing))
    return ir
