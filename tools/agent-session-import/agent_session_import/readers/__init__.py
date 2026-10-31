"""Reader adapters: codex / qoder / omp."""
from . import (aider, antigravity, cherry_studio, claude, claude_desktop, codebuddy, codebuff, cline, codex, continue_, copilot,
                fx, mini_swe_agent,
                iflow,
                kilo_code,
                crush, cursor, devin, droid, dsh, gemini, goose, grok, hermes, junie,
                kiro, kimi, omp, openclaw, opencode, openhands, oss_traj, opencraw, pi,
                qoder, qwen, roo, trae, vibe, windsurf, workbuddy, zcode, zed)

READERS = {"claude": claude, "codex": codex, "dsh": dsh, "omp": omp,
           "oss": oss_traj, "qoder": qoder,
           "copilot": copilot, "gemini": gemini, "aider": aider,
           "cursor": cursor, "qwen": qwen, "pi": pi,
           "openclaw": openclaw, "kimi": kimi, "grok": grok, "droid": droid,
           "antigravity": antigravity, "hermes": hermes, "devin": devin,
           "opencode": opencode,
           "goose": goose, "continue": continue_, "junie": junie, "kiro": kiro,
           "crush": crush, "cline": cline, "roo": roo, "codebuff": codebuff,
           "openhands": openhands, "vibe": vibe, "kilo-code": kilo_code,
           "codebuddy": codebuddy, "fx": fx, "mini-swe-agent": mini_swe_agent,
           "workbuddy": workbuddy, "windsurf": windsurf, "trae": trae, "zcode": zcode,
           "cherry-studio": cherry_studio, "claude-desktop": claude_desktop,
           "opencraw": opencraw, "iflow": iflow, "zed": zed}


def get(source):
    if source not in READERS:
        raise KeyError("unknown source %r (choose from %s)" % (source, ", ".join(READERS)))
    return READERS[source]
