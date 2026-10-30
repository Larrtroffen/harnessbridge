"""Batch-3 cursor reader wrapper (FIXTURE evidence)."""
from . import native_batch3


def default_root():
    return native_batch3.default_root("cursor")


def list_sessions(root=None):
    return native_batch3.list_sessions("cursor", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return native_batch3.load_session("cursor", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
