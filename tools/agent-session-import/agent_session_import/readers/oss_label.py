"""Reader for per-label OSS captures (``traj-session/1``) and export-only labels.

Several labels already have normalized OSS captures (``samples/batch2/oss``)
but no public local store schema. Rather than guessing a native layout, these
readers consume the normalized capture for that label. ``root`` must point at a
directory containing ``<label>__*.jsonl``/``*.json`` captures (test fixture or an
exported capture); there is intentionally no default native store for them.

This is **reader/export-only**: no native writer is claimed.
"""
import os

from . import oss_traj


def default_root(env_names=(), fallback=""):
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return os.path.expanduser(value)
    return os.path.expanduser(fallback)


def list_sessions(label, root=None):
    root = os.path.expanduser(root or "")
    if not root or not os.path.isdir(root):
        return []
    rows = [r for r in oss_traj.list_sessions(root)
            if str(r.get("harness") or "").lower() == label.lower()]
    for row in rows:
        row["source"] = label
    return rows


def resolve_path(label, root, session=None):
    for row in list_sessions(label, root):
        if str(row.get("id")) == str(session) or os.path.basename(row.get("path") or "") == str(session):
            return row["path"]
    if session and os.path.isfile(os.path.expanduser(str(session))):
        return os.path.expanduser(str(session))
    return None


def load_session(label, root=None, session=None, path=None, keep_system=False, **kwargs):
    root = os.path.expanduser(root or "")
    path = path or resolve_path(label, root, session)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("%s capture not found for %r under %s" % (label, session, root or "<no root>"))
    ir = oss_traj.load_session(root=root or os.path.dirname(path), path=path,
                               keep_system=keep_system, **kwargs)
    ir["source"] = label
    ir["extra"] = dict(ir.get("extra") or {})
    ir["extra"]["capture_harness"] = label
    ir["extra"]["reader_only"] = True
    return ir
