"""Kiro adapter: prefer upstream derived fixture (FIXTURE-LOW); fallback constructed."""
from . import native_batch5, native_batch5_1


def default_root():
    return native_batch5.default_root("kiro")


def list_sessions(root=None):
    rows = native_batch5_1.list_kiro_sessions()
    return rows or native_batch5.list_sessions("kiro", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    if path is None and not session:
        paths = native_batch5_1.fixture_paths("kiro")
        if paths:
            path = paths[0]
    if path and path.endswith(".jsonl"):
        return native_batch5_1.load_kiro(path)
    return native_batch5.load_session("kiro", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system)
