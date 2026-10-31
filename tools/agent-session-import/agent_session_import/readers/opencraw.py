"""OpenCraw reader / OpenClaw-alias candidate (export-only).

The OSS capture labelled ``opencraw`` (``samples/batch2/oss``) carries
``harness_evidence: system_prompt:openclaw`` and the same OpenClaw system
prompt — it is almost certainly a misspelling/alias of **OpenClaw**. We do
**not** add a new coverage label: this reader exists only so the legacy OSS
label can be opened, and the canonical support for OpenClaw remains
``readers/openclaw.py``. Alias merge is pending Lead confirmation.

Reader consumes normalized ``traj-session/1`` captures (``OPENCRAW_OSS_DIR`` /
``OPENCRAW_HOME`` override); no native writer.
"""
import os

from . import oss_label

SOURCE = "opencraw"
ALIAS_OF = "openclaw"


def default_root():
    return oss_label.default_root(("OPENCRAW_OSS_DIR", "OPENCRAW_HOME"),
                                  os.path.join(os.path.expanduser("~"), ".opencraw"))


def list_sessions(root=None):
    return oss_label.list_sessions(SOURCE, root or default_root())


def resolve_path(root, session=None):
    return oss_label.resolve_path(SOURCE, root or default_root(), session)


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    ir = oss_label.load_session(SOURCE, root=root or default_root(), session=session,
                                path=path, keep_system=keep_system, **kwargs)
    ir["extra"]["alias_of"] = ALIAS_OF
    ir["extra"]["alias_note"] = "opencraw appears to be an OSS misspelling of openclaw; no new coverage count"
    return ir
