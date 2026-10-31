"""Kiro adapter: prefer upstream derived fixture (FIXTURE-LOW); fallback constructed."""
import os

from . import native_batch5, native_batch5_1


def default_root():
    return native_batch5.default_root("kiro")


def list_sessions(root=None):
    if root:
        out = []
        for path in native_batch5_1.fixture_paths("kiro", root):
            try:
                ir = native_batch5_1.load_kiro(path)
            except (OSError, ValueError):
                continue
            out.append({"source": "kiro", "id": ir.get("source_session_id"),
                        "title": (ir.get("title") or os.path.basename(path))[:120],
                        "cwd": ir.get("cwd"), "created_at_ms": ir.get("created_at_ms"),
                        "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
                        "path": path, "lines": len(ir.get("events") or []),
                        "evidence_level": native_batch5_1.EVIDENCE["kiro"], "fixture": True})
        if out:
            return out
    rows = native_batch5_1.list_kiro_sessions()
    return rows or native_batch5.list_sessions("kiro", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    if path is None and session:
        cand = os.path.expanduser(str(session))
        if os.path.isfile(cand):
            path = cand
    if path is None and not session and root:
        paths = native_batch5_1.fixture_paths("kiro", root)
        if paths:
            path = paths[0]
    if path is None and not session:
        paths = native_batch5_1.fixture_paths("kiro")
        if paths:
            path = paths[0]
    if path and path.endswith(".jsonl"):
        return native_batch5_1.load_kiro(path)
    return native_batch5.load_session("kiro", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system)
