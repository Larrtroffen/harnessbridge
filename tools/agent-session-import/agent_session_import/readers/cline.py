"""Batch-5 cline reader (evidence FIXTURE-CONSTRUCTED)."""
from . import native_batch5


def default_root():
    return native_batch5.default_root("cline")


def list_sessions(root=None):
    return native_batch5.list_sessions("cline", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return native_batch5.load_session("cline", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
