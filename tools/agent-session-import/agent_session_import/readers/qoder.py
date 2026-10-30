"""Qoder (~/.qoder/projects) reader.

Qoder transcripts are a Claude-Code-derived format with three hard differences:

* one assistant row == exactly one content block; rows of the same response share
  ``message.id`` and must be merged in line order;
* ``user`` rows that carry ``tool_result`` are *siblings* of the parent chain (their
  ``parentUuid`` points at the assistant tool_use block), so tool results must be paired
  by ``tool_use_id`` instead of by walking ``parentUuid``;
* the current branch is the chain ending at the last ``active-leaf.leafUuid``.
"""
import glob
import json
import os

from ..common import HOME, count_lines, iso_to_ms, read_jsonl
from ..ir import add_event, finalize, new_ir, text_block, touch_ts, warn

DEFAULT_ROOT = os.path.join(HOME, ".qoder", "projects")

_MAIN_GLOB = "*/*.jsonl"


def default_root():
    return DEFAULT_ROOT


def _main_files(root):
    files = glob.glob(os.path.join(root, _MAIN_GLOB))
    return [f for f in files if os.path.isfile(f) and not f.endswith(".lock")]


def _ms(obj):
    return iso_to_ms(obj.get("timestamp"))


def _texts(content):
    out = []
    if isinstance(content, str):
        if content.strip():
            out.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                out.append(b["text"])
    return out


def _classify_user(o):
    msg = o.get("message") or {}
    content = msg.get("content")
    first = content[0] if isinstance(content, list) and content else None
    if isinstance(first, dict) and first.get("type") == "tool_result":
        return "tool_result"
    if o.get("isCompactSummary"):
        return "compact_summary"
    origin = (o.get("origin") or {}).get("kind")
    if o.get("isMeta") or origin in ("task-notification", "system"):
        return "injected"
    if isinstance(first, dict) and first.get("type") == "image":
        return "image"
    if o.get("humanInput") is not None or origin in ("human", "bridge"):
        return "human"
    if isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip() for b in content
    ) and (o.get("promptId") and not o.get("isVisibleInTranscriptOnly")):
        # defensive: human prompt rows always carry promptId/permissionMode
        return "human"
    if isinstance(content, str) and content.strip():
        return "injected"
    return "other"


def _content_to_ir_blocks(content):
    blocks = []
    if isinstance(content, str):
        if content.strip():
            blocks.append(text_block(content))
        return blocks
    for b in content or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            if isinstance(b.get("text"), str) and b["text"]:
                blocks.append(text_block(b["text"]))
        elif bt == "image":
            blocks.append({"type": "image", "placeholder": "[image attachment not imported]"})
        elif bt in ("tool_result",):
            # inline tool result blocks (rare for user rows): keep as text
            inner = b.get("content")
            for t in _texts(inner):
                blocks.append(text_block(t))
    return blocks


def _tool_result_content(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    texts = _texts(content)
    if texts:
        return "\n".join(texts)
    # image-only results (or other blocks)
    if isinstance(content, list) and content:
        return "[non-text tool result omitted]"
    return ""


# --------------------------------------------------------------------------- index
def list_sessions(root=None):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    out = []
    for path in _main_files(root):
        sid = os.path.basename(path)[:-6]
        title = ""
        cwd = None
        created = None
        model = ""
        bad = 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i < 400:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except ValueError:
                            bad += 1
                            continue
                        t = o.get("type")
                        if cwd is None and o.get("cwd"):
                            cwd = o.get("cwd")
                        if t == "user" and not title:
                            if _classify_user(o) in ("human", "image"):
                                blocks = _content_to_ir_blocks((o.get("message") or {}).get("content"))
                                txt = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                                txt = txt.strip().splitlines()[0] if txt.strip() else ""
                                title = txt[:80]
                        if t == "assistant" and not model:
                            model = (o.get("message") or {}).get("model") or ""
                        if created is None and o.get("timestamp") is not None:
                            created = _ms(o)
                    # count remaining lines cheaply (no JSON parse)
        except OSError:
            continue
        try:
            lines = count_lines(path)
        except OSError:
            lines = 0
        upd = int(os.path.getmtime(path) * 1000)
        out.append(
            {
                "source": "qoder",
                "id": sid,
                "title": title or sid[:8],
                "cwd": cwd,
                "created_at_ms": created,
                "updated_at_ms": upd,
                "path": path,
                "lines": lines,
                "model": model,
                "bad_lines": bad,
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
def load_session(root=None, session=None, path=None, keep_system=False):
    root = os.path.expanduser(root or DEFAULT_ROOT)
    path = path or resolve_path(root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("qoder transcript not found for session=%r root=%s" % (session, root))

    bad = []
    rows = read_jsonl(path, bad)
    ir = new_ir("qoder", os.path.basename(path)[:-6], path)

    by_uuid = {}
    parent_of = {}
    groups = []  # logical assistant messages
    group_by_mid = {}
    user_rows = []
    leaf_uuids = []
    last_prompt = ""
    first_ts = None
    ws_dirs = None

    for idx, o in rows:
        t = o.get("type")
        uuid = o.get("uuid")
        if uuid:
            by_uuid[uuid] = (idx, o)
            parent_of[uuid] = o.get("parentUuid")
        if t == "assistant":
            msg = o.get("message") or {}
            mid = msg.get("id")
            g = group_by_mid.get(mid) if mid else None
            if g is None:
                g = {
                    "id": mid,
                    "idx": idx,
                    "blocks": [],
                    "model": "",
                    "provider": "",
                    "usage": None,
                    "uuids": [],
                }
                groups.append(g)
                if mid:
                    group_by_mid[mid] = g
            g["uuids"].append(uuid)
            g["idx"] = min(g["idx"], idx)
            g["model"] = msg.get("model") or g["model"]
            if msg.get("usage"):
                g["usage"] = msg["usage"]
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "thinking":
                    txt = b.get("thinking") or b.get("text") or ""
                    if isinstance(txt, str) and txt:
                        g["blocks"].append({"type": "reasoning", "text": txt})
                elif bt == "text":
                    txt = b.get("text")
                    if isinstance(txt, str) and txt:
                        g["blocks"].append(text_block(txt))
                elif bt == "tool_use":
                    cid = b.get("id") or ""
                    args = b.get("input")
                    if not isinstance(args, str):
                        args = json.dumps(args if args is not None else {}, ensure_ascii=False)
                    g["blocks"].append(
                        {"type": "tool-call", "id": cid, "name": b.get("name") or "tool", "arguments": args}
                    )
        elif t == "user":
            user_rows.append((idx, o))
            if first_ts is None:
                first_ts = _ms(o) or first_ts
            if not ir.get("cwd") and o.get("cwd"):
                ir["cwd"] = o["cwd"]
        elif t == "active-leaf":
            if o.get("leafUuid"):
                leaf_uuids.append(o["leafUuid"])
        elif t == "last-prompt":
            if isinstance(o.get("lastPrompt"), str):
                last_prompt = o["lastPrompt"]
        elif t == "workspace-directories":
            ws_dirs = o.get("directories") or ws_dirs
        elif t == "system":
            if keep_system and o.get("subtype") == "compact_boundary":
                add_event(
                    ir,
                    "compaction",
                    _ms(o),
                    summary=(o.get("content") or ""),
                    extra={"compactMetadata": o.get("compactMetadata")},
                )
                touch_ts(ir, _ms(o))
        elif t == "attachment":
            continue
        touch_ts(ir, _ms(o))

    # ---- current branch: last active-leaf -> parentUuid chain (fallback: last row) ----
    final_path = set()
    leaf = leaf_uuids[-1] if leaf_uuids else None
    if leaf and leaf in by_uuid:
        cur = leaf
        guard = 0
        while cur and guard < 1000000:
            final_path.add(cur)
            cur = parent_of.get(cur)
            guard += 1
    if not final_path:
        # truncated file / no active-leaf: walk back from the latest parsed node
        cand = max(by_uuid.values(), key=lambda t: t[0]) if by_uuid else None
        cur = cand[1].get("uuid") if cand else None
        guard = 0
        while cur and guard < 1000000:
            final_path.add(cur)
            cur = parent_of.get(cur)
            guard += 1

    # ---- tool_use bookkeeping (call id -> name), only for kept assistant messages ----
    kept_groups = [g for g in groups if any(u in final_path for u in g["uuids"])]
    kept_call_ids = {}
    for g in kept_groups:
        for b in g["blocks"]:
            if b["type"] == "tool-call":
                kept_call_ids[b["id"]] = b["name"]

    # ---- timeline ----
    timeline = []  # (line_idx, event_dict)
    for g in kept_groups:
        if not g["blocks"]:
            continue
        timeline.append(
            (
                g["idx"],
                {
                    "kind": "assistant_message",
                    "ts": _ms(by_uuid[g["uuids"][-1]][1]) or _ms(by_uuid[g["uuids"][0]][1]),
                    "blocks": g["blocks"],
                    "model": g["model"] or "",
                    "provider": "qoder",
                    "usage": g["usage"],
                },
            )
        )
    title_first_user = ""
    injected = 0
    compact_summaries = 0
    for idx, o in user_rows:
        uuid = o.get("uuid")
        cls = _classify_user(o)
        msg = o.get("message") or {}
        content = msg.get("content")
        if cls == "tool_result":
            first = content[0]
            cid = first.get("tool_use_id") or ""
            if cid not in kept_call_ids:
                continue
            ts = _ms(o)
            timeline.append(
                (
                    idx,
                    {
                        "kind": "tool_result",
                        "ts": ts,
                        "call_id": cid,
                        "name": kept_call_ids.get(cid) or "tool",
                        "content": _tool_result_content(first),
                        "is_error": bool(first.get("is_error")),
                    },
                )
            )
        elif cls in ("human", "image"):
            if uuid and uuid not in final_path:
                continue
            blocks = _content_to_ir_blocks(content)
            if not blocks:
                continue
            if cls == "image" and not blocks:
                blocks = [{"type": "image", "placeholder": "[image attachment not imported]"}]
            if not title_first_user:
                txt = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
                if txt:
                    title_first_user = txt.splitlines()[0]
            timeline.append((idx, {"kind": "user_message", "ts": _ms(o), "blocks": blocks}))
        elif cls == "compact_summary":
            compact_summaries += 1
            if keep_system:
                text = "\n".join(_texts(content))
                if text:
                    add_event(ir, "system_message", _ms(o), text=text, origin="compact_summary")
        else:
            injected += 1
            if keep_system and cls in ("injected", "other"):
                text = "\n".join(_texts(content))
                if text:
                    add_event(ir, "system_message", _ms(o), text=text, origin=cls)
    timeline.sort(key=lambda t: t[0])
    for _idx, ev in timeline:
        kind = ev.pop("kind")
        add_event(ir, kind, ev.pop("ts", None), **ev)

    if not ir.get("cwd") and ws_dirs:
        ir["cwd"] = ws_dirs[0]
    if not ir["created_at_ms"] or ir["created_at_ms"] == ir["updated_at_ms"]:
        if first_ts:
            ir["created_at_ms"] = first_ts
    if not ir.get("model"):
        for g in kept_groups:
            if g["model"]:
                ir["model"] = g["model"]
                break
    finalize(ir, fallback_title=last_prompt)
    if bad:
        warn(ir, "%d malformed JSONL line(s) skipped" % len(bad))
    if injected:
        warn(ir, "%d injected/meta user row(s) skipped (use --keep-system to keep)" % injected)
    if compact_summaries:
        warn(ir, "%d compaction summary row(s) skipped (use --keep-system to keep)" % compact_summaries)
    unpaired = ir["stats"]["unpaired_tool_calls"]
    if unpaired:
        warn(ir, "%d tool call(s) had no result in the selected branch (placeholder will be written)" % unpaired)
    return ir
