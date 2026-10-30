"""Native target writers (IR -> harness-native session store).

Staging layout used by ``convert`` (``<out>/<source>/<session-id>/``)::

    dsh    -> session.v4.jsonl (+ session.v4.jsonl.zstd)      [root = the dir]
    codex  -> sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl      [root = the dir = CODEX_HOME]
    qoder  -> projects/<slug>/<id>.jsonl                       [root = the dir = ~/.qoder]
    omp    -> sessions/<slug>/<iso>_<id>.jsonl                 [root = the dir = ~/.omp/agent]
    claude -> projects/<slug>/<uuid>.jsonl                     [root = the dir = ~/.claude]

``native_write(ir, target, root, ...)`` writes into a harness store root directly (used by
``asi matrix`` with temp roots and by ``--install`` with the real/env-overridden root).
"""
import os

from . import aider as _aider
from . import codebuddy as _codebuddy
from . import fx as _fx
from . import mini_swe_agent as _mini_swe
from . import cline as _cline
from . import codebuff as _codebuff
from . import continue_ as _continue_
from . import crush as _crush
from . import devin as _devin
from . import droid as _droid
from . import claude as _claude
from . import copilot as _copilot
from . import cursor as _cursor
from . import gemini as _gemini
from . import codex as _codex
from . import dsh as _dsh
from . import goose as _goose
from . import grok as _grok
from . import junie as _junie
from . import kilo_code as _kilo_code
from . import kiro as _kiro
from . import hermes as _hermes
from . import kimi as _kimi
from . import omp as _omp
from . import openhands as _openhands
from . import openclaw as _openclaw
from . import opencode as _opencode
from . import pi as _pi
from . import qwen as _qwen
from . import qoder as _qoder
from . import roo as _roo
from . import vibe as _vibe

NATIVE_TARGETS = ("dsh", "codex", "qoder", "omp", "claude",
                 "copilot", "gemini", "aider", "cursor", "qwen", "pi",
                 "openclaw", "kimi", "grok", "droid",
                 "hermes", "devin", "opencode",
                 "goose", "continue", "junie", "kiro", "crush", "cline", "roo",
                 "kilo-code", "codebuff", "openhands", "vibe",
                 "codebuddy", "fx", "mini-swe-agent")

WRITERS = {
    "claude": _claude,
    "copilot": _copilot,
    "gemini": _gemini,
    "aider": _aider,
    "cursor": _cursor,
    "qwen": _qwen,
    "pi": _pi,
    "openclaw": _openclaw,
    "kimi": _kimi,
    "grok": _grok,
    "droid": _droid,
    "hermes": _hermes,
    "devin": _devin,
    "opencode": _opencode,
    "goose": _goose,
    "continue": _continue_,
    "junie": _junie,
    "kiro": _kiro,
    "crush": _crush,
    "cline": _cline,
    "roo": _roo,
    "kilo-code": _kilo_code,
    "codebuff": _codebuff,
    "openhands": _openhands,
    "vibe": _vibe,
    "codebuddy": _codebuddy,
    "fx": _fx,
    "mini-swe-agent": _mini_swe,
    "dsh": _dsh,
    "codex": _codex,
    "qoder": _qoder,
    "omp": _omp,
}


def get(target):
    if target not in WRITERS:
        raise ValueError("no native writer for target %r (available: %s)" % (target, ", ".join(WRITERS)))
    return WRITERS[target]


def write_ir_to(ir, target, out_dir, sid, target_cwd=None, compress=True):
    """Write native artifacts for a single session inside ``out_dir`` (staging/convert)."""
    if target == "atif":
        raise ValueError("ATIF is handled by atif.to_atif, not by writers")
    os.makedirs(out_dir, exist_ok=True)
    if target == "dsh":
        res = _dsh.write_compat(ir, out_dir, sid, target_cwd=target_cwd, compress=compress)
    else:
        res = get(target).write_into(ir, out_dir, sid, target_cwd=target_cwd, compress=compress)
    res["target"] = target
    return res


def native_write(ir, target, root, sid, target_cwd=None, compress=True):
    """Write a session into a harness store root (native layout, no extra nesting)."""
    writer = get(target)
    os.makedirs(root, exist_ok=True)
    return writer.write_into(ir, root, sid, target_cwd=target_cwd, compress=compress)
