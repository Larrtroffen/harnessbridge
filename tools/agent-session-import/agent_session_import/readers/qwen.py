"""Batch-3 qwen reader wrapper (FIXTURE evidence)."""
from . import native_batch3


def default_root():
    return native_batch3.default_root("qwen")


def list_sessions(root=None):
    return native_batch3.list_sessions("qwen", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return native_batch3.load_session("qwen", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
