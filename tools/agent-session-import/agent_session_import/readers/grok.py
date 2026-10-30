"""grok batch-4 reader (evidence: FIXTURE)."""
from . import native_batch4


def default_root():
    return native_batch4.default_root("grok")


def list_sessions(root=None):
    return native_batch4.list_sessions("grok", root=root or default_root())


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return native_batch4.load_session("grok", root=root or default_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
