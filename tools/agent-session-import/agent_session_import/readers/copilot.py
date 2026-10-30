"""Batch-3 copilot reader wrapper (FIXTURE evidence)."""
from . import native_batch3


def default_root():
    return native_batch3.default_root("copilot")


def list_sessions(root=None):
    return native_batch3.list_sessions("copilot", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return native_batch3.load_session("copilot", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
