"""Batch-3 gemini reader wrapper (FIXTURE evidence)."""
from . import native_batch3


def default_root():
    return native_batch3.default_root("gemini")


def list_sessions(root=None):
    return native_batch3.list_sessions("gemini", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return native_batch3.load_session("gemini", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
