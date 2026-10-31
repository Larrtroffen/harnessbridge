"""ZCode (Z.ai) reader via codeg's ACP transcript fallback (reader-only)."""
from . import codeg_acp

SOURCE = "zcode"
AGENT_DIR = "codeg-zcode-acp"


def default_root():
    return codeg_acp.transcripts_root()


def list_sessions(root=None):
    rows = codeg_acp.list_sessions(root or default_root(), AGENT_DIR)
    for row in rows:
        row["source"] = SOURCE
    return rows


def resolve_path(root, session=None):
    return codeg_acp.resolve_path(root or default_root(), AGENT_DIR, session)


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    return codeg_acp.load_session(SOURCE, AGENT_DIR, root=root or default_root(),
                                  session=session, path=path, keep_system=keep_system, **kwargs)
