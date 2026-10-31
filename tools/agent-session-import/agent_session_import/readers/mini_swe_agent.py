"""Batch-5.1 mini_swe_agent adapter (upstream fixture; evidence FIXTURE)."""
import os


def default_root():
    return os.path.join(os.getcwd(), "samples", "batch5")


def list_sessions(root=None):
    from . import native_batch5_1 as impl
    import os as _os
    out = []
    for path in impl.fixture_paths("mini-swe-agent", root):
        try:
            ir = load_session(path=path)
        except (OSError, ValueError):
            continue
        out.append({"source": "mini-swe-agent", "id": ir.get("source_session_id"),
                    "title": (ir.get("title") or _os.path.basename(path))[:120],
                    "cwd": ir.get("cwd"), "created_at_ms": ir.get("created_at_ms"),
                    "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
                    "path": path, "lines": len(ir.get("events") or []),
                    "evidence_level": impl.EVIDENCE["mini-swe-agent"], "fixture": True})
    return out


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    from . import native_batch5_1 as impl
    if not path:
        cand = os.path.expanduser(session) if session else None
        if cand and os.path.isfile(cand):
            path = cand
        else:
            paths = impl.fixture_paths("mini-swe-agent", root)
            path = paths[0] if paths else None
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("mini-swe-agent fixture not found")
    return getattr(impl, "load_mini_swe")(path)
