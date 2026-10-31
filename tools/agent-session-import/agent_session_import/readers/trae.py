"""TRAE reader: native TRAE CLI (TraeX = codex-rs fork) first, codeg ACP fallback second.

TRAE CLI 2.0 ("TraeX") is a closed-source fork of ``codex-rs``: it writes the same
Codex **rollout JSONL** layout under ``<TRAE_HOME>/cli/sessions/`` and
``<TRAE_HOME>/cli/archived_sessions/`` (agentsview ``internal/parser/traex.go``),
and resumes with ``traex resume``.  When that native layout is present this
reader delegates to ``readers.codex`` and relabels the IR as ``trae``.

When no native rollout is found it keeps the previous codeg ACP transcript
fallback (``<codeg-home>/acp-transcripts/codeg-trae-cli/``) — codeg records the
ACP wire for agents whose native store it does not parse.

Root resolution:
* ``$TRAE_HOME`` (``~/.trae``), ``$TRAE_CLI_HOME`` (the ``cli`` dir itself);
* default ``~/.trae/cli``;
* explicit ``root=`` may be the ``cli`` dir (contains ``sessions/``), the Trae
  home (contains ``cli/sessions``), or a codeg transcripts root.
"""
import os

from . import codeg_acp, codex
from ..common import iso_to_ms, read_jsonl

SOURCE = "trae"
AGENT_DIR = "codeg-trae-cli"
NATIVE_SESSIONS = "sessions"
NATIVE_ARCHIVED = "archived_sessions"


def _trae_home():
    return os.path.expanduser(
        os.environ.get("TRAE_HOME") or os.environ.get("TRAE_CLI_HOME")
        or os.path.join("~", ".trae"))


def _cli_home(root=None):
    """Return the TRAE CLI home (the dir that contains ``sessions/``) or None."""
    candidates = []
    if root:
        root = os.path.expanduser(str(root))
        candidates.append(root)
        candidates.append(os.path.join(root, "cli"))
    else:
        env = os.environ.get("TRAE_CLI_HOME")
        if env:
            candidates.append(os.path.expanduser(env))
        home = _trae_home()
        candidates.append(home)
        candidates.append(os.path.join(home, "cli"))
    for cand in candidates:
        if os.path.isdir(os.path.join(cand, NATIVE_SESSIONS)) or \
                os.path.isdir(os.path.join(cand, NATIVE_ARCHIVED)):
            return cand
    return None


def native_root(root=None):
    return _cli_home(root)


def default_root():
    """Native CLI home when it exists, otherwise the codeg ACP transcripts root."""
    native = _cli_home()
    if native:
        return native
    return codeg_acp.transcripts_root()


def _acp_root(root=None):
    """Pick the codeg ACP transcripts root, ignoring a non-codeg explicit root."""
    if root:
        root = os.path.expanduser(str(root))
        if os.path.isdir(os.path.join(root, AGENT_DIR)):
            return root
    return codeg_acp.transcripts_root()


def _archived_files(cli):
    import glob
    return sorted(glob.glob(os.path.join(cli, NATIVE_ARCHIVED, "**", "*.jsonl"),
                            recursive=True))


def _archived_rows(cli):
    rows = []
    for path in _archived_files(cli):
        meta = {}
        try:
            for _i, obj in read_jsonl(path):
                if obj.get("type") == "session_meta":
                    meta = obj.get("payload") or {}
                    break
        except OSError:
            continue
        sid = meta.get("id") or os.path.basename(path)
        rows.append({
            "source": SOURCE,
            "id": sid,
            "title": "",
            "cwd": meta.get("cwd"),
            "created_at_ms": iso_to_ms(meta.get("timestamp")),
            "updated_at_ms": int(os.path.getmtime(path) * 1000),
            "path": path,
            "lines": 0,
            "model": "",
            "archived": 1,
            "layout": "traex-codex-rollout",
        })
    return rows


def _native_rows(root=None):
    cli = _cli_home(root)
    if not cli:
        return []
    rows = codex.list_sessions(root=cli)
    out = []
    for row in rows:
        row = dict(row)
        row["source"] = SOURCE
        path = row.get("path") or ""
        row["archived"] = int(row.get("archived") or
                              (1 if os.sep + NATIVE_ARCHIVED + os.sep in path else 0))
        row["layout"] = "traex-codex-rollout"
        out.append(row)
    seen = {r["id"] for r in out}
    for row in _archived_rows(cli):
        if row["id"] not in seen:
            out.append(row)
            seen.add(row["id"])
    return out


def list_sessions(root=None):
    rows = _native_rows(root)
    if rows:
        return rows
    rows = codeg_acp.list_sessions(_acp_root(root), AGENT_DIR)
    for row in rows:
        row["source"] = SOURCE
        row["layout"] = "codeg-acp-transcript"
    return rows


def _resolve_archived(cli, session):
    if not session:
        return None
    for path in _archived_files(cli):
        if session in os.path.basename(path):
            return path
        try:
            for _i, obj in read_jsonl(path):
                if obj.get("type") == "session_meta":
                    if session in ((obj.get("payload") or {}).get("id"), path):
                        return path
                    break
        except OSError:
            continue
    return None


def _matches(path, session):
    """True when a rollout file actually belongs to ``session`` (never 'newest' fallback)."""
    if not path or not session:
        return False
    if session in os.path.basename(path):
        return True
    try:
        for _i, obj in read_jsonl(path):
            if obj.get("type") == "session_meta":
                return session in ((obj.get("payload") or {}).get("id"),)
    except OSError:
        return False
    return False


def resolve_path(root, session=None):
    cli = _cli_home(root)
    if cli:
        native = codex.resolve_path(root=cli, session=session)
        if native and os.path.isfile(native) and (not session or _matches(native, session)):
            return native
        archived = _resolve_archived(cli, session)
        if archived:
            return archived
        if not session and native and os.path.isfile(native):
            return native
    try:
        return codeg_acp.resolve_path(_acp_root(root), AGENT_DIR, session)
    except (OSError, ValueError, KeyError):
        return None


def _is_codeg_acp(path):
    """True when ``path`` is a codeg ACP transcript (header kind=header)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                import json as _json
                obj = _json.loads(line)
                return isinstance(obj, dict) and obj.get("kind") == "header" and "agent" in obj
    except (OSError, ValueError):
        return False
    return False


def load_session(root=None, session=None, path=None, keep_system=False, **kwargs):
    if _is_codeg_acp(path):
        return codeg_acp.load_session(SOURCE, AGENT_DIR,
                                      root=codeg_acp.transcripts_root(), session=session,
                                      path=path, keep_system=keep_system, **kwargs)
    cli = _cli_home(root)
    native_path = path
    if not native_path and cli:
        native_path = _resolve_archived(cli, session)
        if not native_path:
            candidate = codex.resolve_path(root=cli, session=session)
            if candidate and os.path.isfile(candidate) and (not session or _matches(candidate, session)):
                native_path = candidate
    if native_path and os.path.isfile(native_path):
        cli = cli or os.path.dirname(os.path.dirname(os.path.abspath(native_path)))
        ir = codex.load_session(root=cli, session=session, path=native_path,
                                keep_system=keep_system)
        ir["source"] = SOURCE
        ir["provider"] = "trae"
        if not ir.get("source_session_id"):
            ir["source_session_id"] = session or ""
        ir.setdefault("warnings", []).append(
            "TRAE CLI (TraeX) is a codex-rs fork; parsed with the Codex rollout reader "
            "and relabelled as trae")
        return ir
    # No native rollout: codeg ACP transcript fallback (previous behaviour).
    return codeg_acp.load_session(SOURCE, AGENT_DIR,
                                  root=_acp_root(root),
                                  session=session, path=path,
                                  keep_system=keep_system, **kwargs)
