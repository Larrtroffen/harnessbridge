"""Cherry Studio reader (export-only; local store schema not public).

Cherry Studio is an Electron desktop client. Its local chat DB is not a public
contract, so this reader consumes a normalized OSS capture
(``traj-session/1``) for the ``cherry-studio`` label instead of guessing a
SQLite schema. No native writer is claimed.

``root`` = directory containing ``cherry-studio__*.jsonl`` (+ optional
``*.meta.json``); override default with ``CHERRY_STUDIO_HOME`` /
``CHERRY_STUDIO_OSS_DIR``.
"""
import os

from . import oss_label

SOURCE = "cherry-studio"


def default_root():
    return oss_label.default_root(("CHERRY_STUDIO_OSS_DIR", "CHERRY_STUDIO_HOME"),
                                  os.path.join(os.path.expanduser("~"), ".cherry-studio"))


def list_sessions(root=None):
    return oss_label.list_sessions(SOURCE, root or default_root())


def resolve_path(root, session=None):
    return oss_label.resolve_path(SOURCE, root or default_root(), session)


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return oss_label.load_session(SOURCE, root=root or default_root(), session=session,
                                  path=path, keep_system=keep_system, **kwargs)
