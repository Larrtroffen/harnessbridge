"""Claude Desktop / Cowork reader (export-only; sparse OSS evidence).

The desktop app does not write a public, plain transcript store. This reader
consumes a normalized OSS capture (``traj-session/1``) for the
``claude-desktop`` label (``samples/batch2/oss-add`` in this repo), plus an
optional local ``CLAUDE_DESKTOP_HOME`` root for exported captures. Reader-only.
"""
import os

from . import oss_label

SOURCE = "claude-desktop"


def default_root():
    return oss_label.default_root(("CLAUDE_DESKTOP_OSS_DIR", "CLAUDE_DESKTOP_HOME"),
                                  os.path.join(os.path.expanduser("~"), "Library",
                                               "Application Support", "Claude"))


def list_sessions(root=None):
    return oss_label.list_sessions(SOURCE, root or default_root())


def resolve_path(root, session=None):
    return oss_label.resolve_path(SOURCE, root or default_root(), session)


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return oss_label.load_session(SOURCE, root=root or default_root(), session=session,
                                  path=path, keep_system=keep_system, **kwargs)
