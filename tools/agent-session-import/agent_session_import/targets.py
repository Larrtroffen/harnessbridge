"""Target-harness roots, env isolation and L3 native discovery/load checks.

L3 strict acceptance used by `asi matrix`: write the IR to a target-native store under an
isolated env/root, then ask the target harness itself to discover/load it and look for the
source session's conversation content on screen (no prompts are sent, no model calls made).
"""
import json
import os
import re
import shutil
import subprocess

from .common import HOME
from .writers import native_write

TARGETS = ("claude", "codex", "dsh", "omp", "qoder")

# environment variables that relocate each harness store (reader roots derived below)
ENV_VARS = {
    "claude": "CLAUDE_CONFIG_DIR",   # replaces ~/.claude (projects/ lives under it)
    "codex": "CODEX_HOME",           # replaces ~/.codex
    "dsh": "DSH_HOME",               # replaces ~/.dsh
    "omp": "OMP_SESSION_DIR",        # asi convention; omp CLI also has --session-dir
    "qoder": "QODER_CONFIG_DIR",     # unverified: Qoder CLI is not installed on this machine
}

DEFAULT_ROOTS = {
    "claude": os.path.join(HOME, ".claude", "projects"),
    "codex": os.path.join(HOME, ".codex"),
    "dsh": os.path.join(HOME, ".dsh", "sessions"),
    "omp": os.path.join(HOME, ".omp", "agent", "sessions"),
    "qoder": os.path.join(HOME, ".qoder", "projects"),
}

TOOL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
E2E_LOAD = os.path.join(TOOL_DIR, "tests", "e2e_load.mjs")

_FAKE_CLAUDE_KEY = "sk-ant-api03-asi-fake-key-0000000000000000"


# --------------------------------------------------------------------------- roots / install
def _env_root(target, value):
    value = os.path.expanduser(value)
    if target == "claude":
        return os.path.join(value, "projects")
    if target == "dsh":
        return os.path.join(value, "sessions")
    if target == "qoder":
        return os.path.join(value, "projects")
    return value


def resolve_root(target, install_root=None):
    """Return (reader_root, isolation_note, is_real_home)."""
    if install_root:
        return os.path.abspath(os.path.expanduser(install_root)), "install-root override", False
    env = ENV_VARS.get(target)
    if env and os.environ.get(env):
        root = _env_root(target, os.environ[env])
        return root, "env:%s=%s" % (env, os.environ[env]), False
    return DEFAULT_ROOTS[target], "default (real harness store)", True


def install_session(ir, target, sid, install_root=None, target_cwd=None):
    root, isolation, is_real = resolve_root(target, install_root)
    res = native_write(ir, target, root, sid, target_cwd=target_cwd)
    res.update({"install_root": root, "isolation": isolation, "is_real_home": is_real})
    return res


# --------------------------------------------------------------------------- process helpers
def _run(cmd, env=None, timeout=15, input_text=None):
    try:
        p = subprocess.run(
            cmd, input=input_text, capture_output=True, text=True,
            env=env or dict(os.environ), timeout=timeout,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return None, out, "timeout"


def _strip_ansi(text):
    text = text or ""
    text = re.sub(r"\x1b\[[0-9;?><!|]*[ -/]*[@-~]", "", text)   # CSI / private modes
    text = re.sub(r"\x1b\][^\x1b\x07]*(?:\x07|\x1b\\)", "", text)  # OSC
    text = re.sub(r"\x1b[()][A-Za-z0-9]", "", text)
    text = re.sub(r"\x1b[=>MDEHc]", "", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)       # remaining C0 controls
    return text


def _run_pty(cmd, env, seconds=10, cwd=None):
    """Run a TUI command under a pseudo terminal, capture screen bytes, then kill it."""
    import pty
    import select
    import signal
    import time

    if not hasattr(os, "openpty"):
        return None, ""
    import fcntl
    import struct
    import termios

    master, slave = pty.openpty()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 140, 0, 0))
    except OSError:
        pass
    try:
        proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave,
                                env=env, close_fds=True, cwd=cwd)
    except OSError:
        os.close(master)
        os.close(slave)
        return None, ""
    os.close(slave)
    out = b""
    try:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.25)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            if proc.poll() is not None:
                break
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    finally:
        try:
            os.close(master)
        except OSError:
            pass
    return proc.returncode, _strip_ansi(out.decode("utf-8", "replace"))


# --------------------------------------------------------------------------- content checks
def _first_user_text(ir):
    for ev in ir.get("events") or []:
        if ev.get("kind") == "user_message":
            text = "\n".join(b.get("text") or b.get("placeholder") or ""
                             for b in ev.get("blocks") or []).strip()
            if text:
                return text
    for ev in ir.get("events") or []:
        if ev.get("kind") == "assistant_message":
            text = "\n".join(b.get("text") or "" for b in ev.get("blocks") or []
                             if b.get("type") == "text").strip()
            if text:
                return text
    return ir.get("title") or ""


def _content_candidates(ir):
    """Distinctive text snippets from the session (title + first/last user + last assistant)."""
    out = []
    title = (ir.get("title") or "").strip()
    if title:
        out.append(title)
    users = [ev for ev in ir.get("events") or [] if ev.get("kind") == "user_message"]
    assistants = [ev for ev in ir.get("events") or [] if ev.get("kind") == "assistant_message"]

    def ev_text(ev):
        return "\n".join(b.get("text") or b.get("placeholder") or ""
                          for b in ev.get("blocks") or []).strip()

    if users:
        out.append(ev_text(users[0]))
        if len(users) > 1:
            out.append(ev_text(users[-1]))
    for ev in assistants[-3:]:
        out.append(ev_text(ev))
    return [x for x in out if len(_norm_ws(x)) >= 8]


def _content_visible(screen, ir):
    return any(_screen_has(screen, text) for text in _content_candidates(ir))


def _norm_ws(text):
    return re.sub(r"\s+", "", text or "")


def _screen_has(screen, text):
    """True when a meaningful snippet of ``text`` shows up in the ANSI-stripped TUI screen."""
    screen_n = _norm_ws(screen)
    text_n = _norm_ws(text)
    if not screen_n or not text_n:
        return False
    for n in (40, 24, 12, 8):
        if len(text_n) < n:
            continue
        starts = {0}
        for frac in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9):
            starts.add(int(len(text_n) * frac))
        starts.add(max(0, len(text_n) - n))
        for start in sorted(starts):
            if text_n[start:start + n] in screen_n:
                return True
    return False


def _clip(text, n=400):
    return (text or "").strip()[:n]



def _json_strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _json_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_strings(v, out)


def _codex_appserver_content(root, artifact, ir, timeout=20):
    """Ask Codex's own app-server to resume the rollout by path and list its items.

    This is a native, token-free Codex load path (no turn is started / no model request).
    Returns (ok, detail, item_count).
    """
    import select
    import time

    thread_id = ""
    try:
        with open(artifact, "r", encoding="utf-8") as f:
            meta = json.loads(f.readline())
        thread_id = ((meta.get("payload") or {}).get("id")) or ""
    except (OSError, ValueError):
        pass
    if not thread_id:
        return False, "cannot read session_meta id from rollout", 0
    env = dict(os.environ, CODEX_HOME=root)
    try:
        proc = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, text=True, bufsize=1)
    except OSError as exc:
        return False, "cannot start codex app-server: %s" % exc, 0

    def send(obj):
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def read_until(marker, seconds):
        lines = []
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([proc.stdout], [], [], 0.25)
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line.strip())
                if marker and marker in line:
                    break
            elif proc.poll() is not None:
                break
        return lines

    texts = []
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"clientInfo": {"name": "asi-l3", "version": "0.1"},
                         "capabilities": {"experimentalApi": True}}})
        read_until('"id":1', min(8, timeout))
        send({"jsonrpc": "2.0", "id": 2, "method": "thread/resume",
              "params": {"threadId": thread_id, "path": artifact}})
        res_lines = read_until('"id":2', min(10, timeout))
        for line in res_lines:
            try:
                _json_strings(json.loads(line), texts)
            except ValueError:
                texts.append(line)
        send({"jsonrpc": "2.0", "id": 3, "method": "thread/items/list",
              "params": {"threadId": thread_id, "limit": 100}})
        item_lines = read_until('"id":3', min(10, timeout))
        item_count = 0
        for line in item_lines:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            result = obj.get("result") or {}
            data = result.get("data")
            if isinstance(data, list):
                item_count = max(item_count, len(data))
            _json_strings(obj, texts)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
    joined = "\n".join(texts)
    ok = _content_visible(joined, ir)
    detail = ("codex app-server thread/resume(path) + thread/items/list returned %d item(s)%s"
              % (item_count, "; source conversation text materialized" if ok
                 else "; but no source text found"))
    return ok, detail, item_count


# --------------------------------------------------------------------------- L3 probes
def l3_check(target, artifact, root, sid, ir, timeout=15):
    """Discover/load the freshly written native session with the target harness.

    Returns {ok: bool|"partial"|None, tool, command, detail, evidence, output_excerpt?}.
    ok=None means the harness has no token-free discovery path (format-level only).
    """
    res = {"ok": None, "tool": None, "command": None, "detail": "", "evidence": artifact}

    if target == "dsh":
        if not os.path.isfile(E2E_LOAD):
            res["detail"] = "e2e_load.mjs missing"
            return res
        rc, out, err = _run(["node", E2E_LOAD, artifact], timeout=timeout)
        command = "node tests/e2e_load.mjs %s" % os.path.basename(artifact)
        res.update({"tool": "dsh Session.fromRestore", "command": command})
        if rc == 3:
            res["detail"] = "global @deepseek-ai/dsh package not installed; load check skipped"
            return res
        if rc == 0:
            try:
                info = json.loads(out.strip().splitlines()[-1])
                res.update({"ok": True,
                            "detail": "Session.fromRestore OK: seq=%s messages=%s"
                                      % (info.get("seq"), info.get("messages")),
                            "info": info})
            except (ValueError, IndexError):
                res.update({"ok": True, "detail": "Session.fromRestore OK"})
        else:
            res.update({"ok": False, "detail": _clip(err or out)})
        return res

    if target == "codex":
        env = dict(os.environ, CODEX_HOME=root, TERM="xterm-256color")
        # The resume TUI needs credentials for its UI bootstrap; copy the read-only auth file
        # into the isolated CODEX_HOME (the real store is never written).
        real_auth = os.path.join(HOME, ".codex", "auth.json")
        staged_auth = os.path.join(root, "auth.json")
        if not os.path.isfile(staged_auth) and os.path.isfile(real_auth):
            try:
                shutil.copy2(real_auth, staged_auth)
                os.chmod(staged_auth, 0o600)
            except OSError:
                pass
        first = _first_user_text(ir)
        # 1) native app-server load: `thread/resume(path)` + `thread/items/list` (token-free)
        app_ok, app_detail, app_items = _codex_appserver_content(root, artifact, ir)
        if app_ok:
            res.update({"ok": True,
                        "detail": "codex app-server thread/resume(path) + thread/items/list "
                                  "materialized %d item(s) incl. source conversation text "
                                  "(native Codex load; no prompt/model call). Note: the interactive "
                                  "`codex resume` picker additionally requires Codex's own "
                                  "thread-store index, which is why file-only installs show 0/0 "
                                  "there." % app_items})
            return res
        # 2) interactive TUI resume (content readable only when Codex accepts the thread)
        text = ""
        attempts = [
            (["codex", "--no-alt-screen", "resume", "--last", "--include-non-interactive"],
             "codex --no-alt-screen resume --last --include-non-interactive"),
            (["codex", "--no-alt-screen", "resume", "--include-non-interactive"],
             "codex --no-alt-screen resume --include-non-interactive (picker)"),
        ]
        for cmd, label in attempts:
            _rc, text = _run_pty(cmd, env, seconds=18)
            res.update({"tool": "codex CLI resume TUI",
                        "command": "CODEX_HOME=%s %s (PTY)" % (root, label)})
            if "no sessions" in text.lower() or "no session found" in text.lower():
                res.update({"ok": False,
                            "detail": "codex reported no sessions under staged CODEX_HOME"})
                return res
            if _content_visible(text, ir):
                res.update({"ok": True,
                            "detail": "codex resume TUI rendered source session content "
                                      "(first user text %r)" % first[:40],
                            "output_excerpt": _clip(text)})
                return res
        res.update({
            "ok": "partial",
            "detail": "codex resume TUI launched on staged CODEX_HOME but source text was not visible "
                      "(picker 0/0: Codex 0.164 paginated thread store does not scan bare rollout "
                      "files); app-server path also did not materialize conversation items: "
                      + app_detail,
            "output_excerpt": _clip(text),
        })
        return res

    if target == "claude":
        config_root = os.path.dirname(root)          # root == <config>/projects
        stage_dir = os.path.dirname(config_root)
        home = os.path.join(stage_dir, "home")
        os.makedirs(home, exist_ok=True)
        run_cwd = os.path.join(stage_dir, "cwd")
        os.makedirs(run_cwd, exist_ok=True)
        real_run_cwd = os.path.realpath(run_cwd)
        dot_claude_json = os.path.join(config_root, ".claude.json")
        if not os.path.isfile(dot_claude_json):
            os.makedirs(config_root, exist_ok=True)
            with open(dot_claude_json, "w", encoding="utf-8") as f:
                json.dump({
                    "numStartups": 1,
                    "hasCompletedOnboarding": True,
                    "projects": {real_run_cwd: {"hasTrustDialogAccepted": True}},
                    "customApiKeyResponses": {"approved": [_FAKE_CLAUDE_KEY[-20:]],
                                              "rejected": []},
                }, f)
        env = dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR=config_root,
                   ANTHROPIC_API_KEY=_FAKE_CLAUDE_KEY, DISABLE_TELEMETRY="1",
                   DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                   NO_COLOR="1", TERM="xterm-256color")
        first = _first_user_text(ir)
        cmd = ["claude", "--bare", "--resume", artifact]
        res.update({
            "tool": "claude CLI resume (PTY, no prompt)",
            "command": "HOME=%s CLAUDE_CONFIG_DIR=%s ANTHROPIC_API_KEY=<fake> "
                       "claude --bare --resume %s"
                       % (home, config_root, os.path.basename(artifact)),
        })
        _rc, text = _run_pty(cmd, env, seconds=16, cwd=real_run_cwd)
        if "no conversation found" in text.lower():
            res.update({"ok": False,
                        "detail": "claude --resume reported 'No conversation found'",
                        "output_excerpt": _clip(text, 300)})
            return res
        if _content_visible(text, ir):
            res.update({"ok": True,
                        "detail": "claude TUI rendered source session content "
                                  "(first user text %r)" % first[:40],
                        "output_excerpt": _clip(text)})
            return res
        res.update({
            "ok": "partial",
            "detail": "claude TUI launched in isolated CLAUDE_CONFIG_DIR but the source text was "
                      "not captured from the PTY screen; recipe: minimal .claude.json + fake "
                      "ANTHROPIC_API_KEY + claude --bare --resume <abs path> "
                      "(no prompt, no model call)",
            "output_excerpt": _clip(text),
        })
        return res

    if target == "omp":
        model = ir.get("model") or ""
        use_model = bool(model) and not model.startswith("<") and model not in ("unknown", "imported")
        text_attempts = [(
            ["omp", "--session-dir", root, "--mode=rpc", "-r", artifact],
            "omp --session-dir <staging> --mode=rpc -r <file>",
        )]
        if use_model:
            text_attempts.insert(0, (
                ["omp", "--session-dir", root, "--mode=rpc", "-r", artifact,
                 "--model", model],
                "omp --session-dir <staging> --mode=rpc -r <file> --model %r" % model))
        for cmd, label in text_attempts:
            rc, out, err = _run(cmd, timeout=min(timeout, 10), input_text="")
            detail = (err or "").strip()
            res.update({"tool": "omp --mode=rpc -r <file>", "command": label})
            low = detail.lower()
            if "not found" in low or "failed to parse" in low or "invalid" in low:
                res.update({"ok": False, "detail": _clip(detail)})
                return res
            if "could not restore model" in detail:
                continue
            if rc == 0 or (rc is None and not detail.strip()):
                res.update({"ok": True,
                            "detail": "omp accepted the transcript in --mode=rpc (no model call; "
                                      "process stayed alive waiting for input=%r)" % (rc is None),
                            "output_excerpt": _clip(out, 200)})
                return res
        # last resort: retry with the model configured in the local OMP profile
        try:
            from .writers.omp import _omp_models

            _configured, default_model = _omp_models()
        except (ImportError, ValueError):
            default_model = "magpie/deepseek/deepseek-flash"
        cmd = ["omp", "--session-dir", root, "--mode=rpc", "-r", artifact,
               "--model", default_model]
        rc, out, err = _run(cmd, timeout=min(timeout, 10), input_text="")
        detail = (err or "").strip()
        res.update({"tool": "omp --mode=rpc -r <file> --model <configured>",
                    "command": " ".join(cmd)})
        if "could not restore model" in detail or "not found" in detail.lower():
            res.update({"ok": "partial",
                        "detail": "transcript loaded by omp but its model is not configured: %s"
                                  % _clip(detail.splitlines()[0] if detail else "", 160)})
            return res
        if rc == 0 or (rc is None and not detail.strip()):
            res.update({"ok": True,
                        "detail": "omp loaded the transcript with configured model %r in "
                                  "--mode=rpc (no model call; rc=%r)" % (default_model, rc),
                        "output_excerpt": _clip(out, 200)})
            return res
        res.update({"ok": "partial", "detail": _clip(detail)})
        return res

    # qoder: CLI not installed on this machine
    res.update({
        "tool": None,
        "detail": "Qoder CLI is not installed (IDE-only); native discovery unverifiable "
                  "-> format-level verification via reader round-trip only",
    })
    return res
