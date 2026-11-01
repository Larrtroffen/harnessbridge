"""Product-level backend commands for the Swift user app: detect / preview / migrate.

Design goals (docs/user-app-product-spec.md §4):
* user-facing labels only (no IR/reader/writer jargon in the payloads);
* read-only by default; the only real-store write path is ``migrate --mode install``
  for DSH (explicit ``--yes`` required), everything else defaults to export staging;
* one failing harness/session never aborts the whole batch;
* every command supports ``--json`` with a stable schema for the Swift app.
"""
import datetime as _dt
import glob
import json
import os
import shutil
import time

from . import atif, dsh
from .common import HOME
from .readers import get as get_reader

DSH_DEFAULT_HOME = os.path.join(HOME, ".dsh")

# id, display name (user friendly), family, store root resolver, reader key, docs
def _env_home(name, default):
    return os.path.expanduser(os.environ.get(name) or default)


HARNESSES = [
    {
        "id": "dsh", "display_name": "DeepSeek Harness", "family": "dsh",
        "root": lambda: os.path.join(_env_home("DSH_HOME", DSH_DEFAULT_HOME), "sessions"),
        "install_root": lambda: _env_home("DSH_HOME", DSH_DEFAULT_HOME),
        "install_supported": True, "install_experimental": False,
        "how_to_see": "重启 DeepSeek Harness 后可在会话列表看到（导入后可选择注册到项目）",
        "session_dir_hint": "sessions/<projectKey(cwd)>/<session-id>/session.v4.jsonl.zstd",
        "capabilities": {"export": True, "install": True, "install_experimental": False,
                         "preview": True},
        "notes": "目标应用；导入后需要重启 DeepSeek Harness 才能看到新会话",
    },
    {
        "id": "claude", "display_name": "Claude Code", "family": "anthropic",
        "root": lambda: os.path.join(_env_home("CLAUDE_CONFIG_DIR",
                                               os.path.join(HOME, ".claude")), "projects"),
        "install_root": lambda: os.path.join(_env_home("CLAUDE_CONFIG_DIR",
                                                       os.path.join(HOME, ".claude")), "projects"),
        "install_supported": True, "install_experimental": False,
        "how_to_see": "重启 Claude Code 后在 `claude --resume` 的会话列表可见",
        "session_dir_hint": "projects/<cwd-slug>/<uuid>.jsonl",
        "capabilities": {"export": True, "install": True, "install_experimental": False,
                         "preview": True},
        "notes": "Claude Code 原生会话目录；写入后重启 Claude Code 可见",
    },
    {
        "id": "codex", "display_name": "OpenAI Codex", "family": "openai",
        "root": lambda: _env_home("CODEX_HOME", os.path.join(HOME, ".codex")),
        "install_root": lambda: _env_home("CODEX_HOME", os.path.join(HOME, ".codex")),
        "install_supported": True, "install_experimental": True,
        "how_to_see": "运行 `codex resume` 时可能需要重建线程索引；写入为实验性能力",
        "session_dir_hint": "sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl",
        "capabilities": {"export": True, "install": True, "install_experimental": True,
                         "preview": True},
        "notes": "Codex 原生 rollout 目录；state_5 线程索引可能需 Codex 自身重建（实验性）",
    },
    {
        "id": "omp", "display_name": "Oh My Pi (OMP)", "family": "omp",
        "root": lambda: os.environ.get("OMP_SESSION_DIR") or os.path.join(
            _env_home("OMP_HOME", os.path.join(HOME, ".omp")), "agent", "sessions"),
        "install_root": lambda: os.environ.get("OMP_SESSION_DIR") or os.path.join(
            _env_home("OMP_HOME", os.path.join(HOME, ".omp")), "agent", "sessions"),
        "install_supported": True, "install_experimental": False,
        "how_to_see": "重启 OMP 后在会话列表可见",
        "session_dir_hint": "sessions/<cwd-slug>/<ISO>_<uuid>.jsonl",
        "capabilities": {"export": True, "install": True, "install_experimental": False,
                         "preview": True},
        "notes": "OMP 原生 sessions 目录；写入后重启 OMP 可见",
    },
    {
        "id": "qoder", "display_name": "Qoder", "family": "qoder",
        "root": lambda: os.path.join(_env_home("QODER_CONFIG_DIR",
                                               _env_home("QODER_HOME", os.path.join(HOME, ".qoder"))),
                                     "projects"),
        "install_root": lambda: os.path.join(_env_home("QODER_CONFIG_DIR",
                                                       _env_home("QODER_HOME", os.path.join(HOME, ".qoder"))),
                                             "projects"),
        "install_supported": True, "install_experimental": True,
        "how_to_see": "重启 Qoder 后在历史会话可见（无公开 CLI，实验性）",
        "session_dir_hint": "projects/<cwd-slug>/<uuid>.jsonl",
        "capabilities": {"export": True, "install": True, "install_experimental": True,
                         "preview": True},
        "notes": "Qoder 没有公开的会话恢复 CLI；按原生文件格式写入（实验性）",
    },
    {
        "id": "pi", "display_name": "Pi", "family": "pi",
        "root": lambda: os.environ.get("PI_SESSION_DIR") or os.path.join(
            _env_home("PI_HOME", os.path.join(HOME, ".pi")), "agent", "sessions"),
        "install_root": lambda: os.environ.get("PI_SESSION_DIR") or os.path.join(
            _env_home("PI_HOME", os.path.join(HOME, ".pi")), "agent"),
        "install_supported": True, "install_experimental": True,
        "how_to_see": "重启 Pi 后在会话列表可见（实验性）",
        "session_dir_hint": "agent/sessions/<cwd-slug>/<ISO>_<uuid>.jsonl",
        "capabilities": {"export": True, "install": True, "install_experimental": True,
                         "preview": True},
        "notes": "Pi 树状会话；写入为实验性能力",
    },
    {
        "id": "gemini", "display_name": "Gemini CLI", "family": "google",
        "root": lambda: os.path.join(_env_home("GEMINI_HOME", os.path.join(HOME, ".gemini")), "tmp"),
        "install_root": lambda: _env_home("GEMINI_HOME", os.path.join(HOME, ".gemini")),
        "install_supported": True, "install_experimental": True,
        "how_to_see": "重启 Gemini CLI 后在 /resume 会话列表可见（实验性）",
        "session_dir_hint": "tmp/<project-hash>/chats/session-<ts>-<id>.json",
        "capabilities": {"export": True, "install": True, "install_experimental": True,
                         "preview": True},
        "notes": "Gemini CLI 会话（JSONL patch 流）；写入为实验性能力",
    },
    {
        "id": "goose", "display_name": "Goose", "family": "block",
        "root": lambda: os.path.join(_env_home("GOOSE_PATH_ROOT",
                                               os.path.join(HOME, ".local", "share", "goose")),
                                     "sessions"),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "Goose 会话库为 SQLite，本工具仅支持导出",
        "session_dir_hint": "sessions/sessions.db",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "Goose SQLite 会话；只读导出（不支持写入）",
    },
    {
        "id": "workbuddy", "display_name": "WorkBuddy", "family": "workbuddy",
        "root": lambda: get_reader("workbuddy").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "WorkBuddy 原生 JSONL 会话库；本工具仅支持读取/导出（reader-only）",
        "session_dir_hint": "projects/**/*.jsonl",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "WorkBuddy 原生 JSONL（agenttrace 格式交叉验证）；无经验证的原生 writer，reader-only/export-only",
    },
    {
        "id": "windsurf", "display_name": "Windsurf", "family": "codeium",
        "root": lambda: get_reader("windsurf").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "Windsurf/Codeium Cascade JSONL 会话；本工具仅支持读取/导出（reader-only）",
        "session_dir_hint": "~/.windsurf/**/*.jsonl（或 ~/.codeium/windsurf/sessions）",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "Windsurf JSONL（sessionport WindsurfStore 交叉验证）；无经验证 writer，reader-only/export-only",
    },
    {
        "id": "trae", "display_name": "TRAE", "family": "bytedance",
        "root": lambda: get_reader("trae").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "TRAE CLI (TraeX) 原生 rollout 优先读取；无原生会话时读取 codeg ACP transcript 兜底（reader-only）",
        "session_dir_hint": "~/.trae/cli/sessions/**/rollout-*.jsonl；兜底 <codeg-home>/acp-transcripts/codeg-trae-cli/<session-id>.jsonl",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "TRAE CLI 2.0 (TraeX) 是 codex-rs fork，写 Codex rollout JSONL（复用 Codex reader）；无原生会话时回退 codeg ACP transcript v1；reader-only/export-only",
    },
    {
        "id": "zcode", "display_name": "ZCode (Z.ai)", "family": "zhipu",
        "root": lambda: get_reader("zcode").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "ZCode 无公开原生消息存储契约；读取 codeg ACP transcript 兜底（reader-only）",
        "session_dir_hint": "<codeg-home>/acp-transcripts/codeg-zcode-acp/<session-id>.jsonl",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "ACP transcript 兜底（codeg acp_transcript v1）；reader-only，原生 ZCode ACP bridge 未实现",
    },
    {
        "id": "cherry-studio", "display_name": "Cherry Studio", "family": "cherry",
        "root": lambda: get_reader("cherry-studio").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "Cherry Studio 本地会话库 schema 未公开；仅支持读取/导出 OSS traj-session 采集",
        "session_dir_hint": "traj-session/1 captures（cherry-studio__*.jsonl）",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "OSS 采集读出（reader-only/export-only）；本地 SQLite schema 未核实",
    },
    {
        "id": "claude-desktop", "display_name": "Claude Desktop", "family": "anthropic",
        "root": lambda: get_reader("claude-desktop").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "Claude Desktop/Cowork 无公开 transcript 存储；仅支持读取/导出 OSS 稀疏采集",
        "session_dir_hint": "traj-session/1 captures（claude-desktop__*.jsonl）",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "OSS 稀疏采集（COLLECTED-SPARSE）读出；reader-only/export-only，无原生 store 写入",
    },
    {
        "id": "opencraw", "display_name": "OpenCraw (OpenClaw alias?)", "family": "openclaw",
        "root": lambda: get_reader("opencraw").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "OSS 采集标签（疑为 OpenClaw 拼写别名）；reader-only，不重复计入覆盖",
        "session_dir_hint": "traj-session/1 captures（opencraw__*.jsonl）",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "opencraw 疑为 openclaw 别名（harness_evidence: system_prompt:openclaw）；不新增去重计数",
    },
    {
        "id": "iflow", "display_name": "iFlow CLI", "family": "iflow",
        "root": lambda: get_reader("iflow").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "iFlow CLI 原生 JSONL 会话库（Claude Code 兼容格式）；本工具仅支持读取/导出（reader-only）",
        "session_dir_hint": "$IFLOW_HOME/projects/<project>/<sessionId>.jsonl（默认 ~/.iflow/projects）",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "iFlow CLI 原生 JSONL（Claude Code 兼容：uuid/parentUuid/message.content blocks，agentsview MIT fixture 交叉验证）；ACP JSON 兜底；reader-only/export-only（claude writer 可复用但未注册）",
    },
    {
        "id": "zed", "display_name": "Zed", "family": "zed",
        "root": lambda: get_reader("zed").default_root(),
        "install_root": None,
        "install_supported": False, "install_experimental": False,
        "how_to_see": "Zed 编辑器 Agent Panel 的 threads.db（SQLite）；本工具仅支持读取/导出（reader-only）",
        "session_dir_hint": "~/Library/Application Support/Zed/threads/threads.db（$ZED_HOME 可覆盖）",
        "capabilities": {"export": True, "install": False, "install_experimental": False,
                         "preview": True},
        "notes": "Zed threads.db（data_type=json|zstd；DbThread/Message JSON）；无 CLI resume 且 DB 为 App 私有，writer 高风险不实现，reader-only/export-only",
    },
]
HARNESS_BY_ID = {h["id"]: h for h in HARNESSES}
FILE_SOURCES = {"pi", "gemini", "goose"}  # light scanners: no full reader needed for detect
NEW_READER_SOURCES = {"workbuddy", "windsurf", "trae", "zcode", "cherry-studio",
                      "claude-desktop", "opencraw", "iflow", "zed"}


def _now_ms():
    return int(time.time() * 1000)


def _ts_of(row):
    for key in ("updated_at_ms", "created_at_ms"):
        v = row.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return 0


def _session_path_exists(source, row):
    """True when a reader row points at a real file (or a virtual container path)."""
    path = row.get("path") or ""
    if path and os.path.isfile(path):
        return True
    if "#" in path:
        container, _sep, member = path.rpartition("#")
        return os.path.isfile(container) and bool(member)
    return False


def _file_scan(source, root):
    if not os.path.isdir(root):
        return []
    if source == "pi":
        files = glob.glob(os.path.join(root, "*", "*.jsonl"))
    elif source == "gemini":
        files = glob.glob(os.path.join(root, "*", "chats", "session-*.json*"))
    else:  # goose: read-only sqlite count
        db = os.path.join(root, "sessions.db")
        if not os.path.isfile(db):
            return []
        try:
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3F"), uri=True)
            try:
                n = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            n = 0
        st = os.stat(db)
        return [{"id": "sessions.db", "path": db, "created_at_ms": int(st.st_mtime * 1000),
                 "updated_at_ms": int(st.st_mtime * 1000)} for _ in range(n)]
    rows = []
    for path in sorted(files):
        try:
            st = os.stat(path)
        except OSError:
            continue
        rows.append({"id": os.path.basename(path), "path": path,
                     "created_at_ms": int(st.st_mtime * 1000),
                     "updated_at_ms": int(st.st_mtime * 1000)})
    return rows


def _fast_scan(source, root):
    """Filesystem-only session counting for detect --fast.

    No session content is parsed (no JSON decode / zstd decompress): only directory
    listing, file-name matching and mtime approximation is used.
    """
    import sqlite3

    def _max_mtime(paths):
        best = 0
        for p in paths:
            try:
                best = max(best, int(os.stat(p).st_mtime * 1000))
            except OSError:
                continue
        return best

    if source == "codex":
        db = os.path.join(root, "state_5.sqlite")
        if os.path.isfile(db):
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3F"), uri=True)
            try:
                rows = con.execute(
                    "select rollout_path, updated_at_ms, updated_at from threads").fetchall()
            except sqlite3.Error:
                rows = []
            finally:
                con.close()
            paths = [r[0] for r in rows if r[0] and os.path.isfile(r[0])]
            recent = 0
            for r in rows:
                for v in (r[1], (int(r[2]) * 1000 if r[2] else 0)):
                    if v:
                        recent = max(recent, int(v))
            return len(paths), recent or _max_mtime(paths)
        files = glob.glob(os.path.join(root, "sessions", "**", "rollout-*.jsonl"),
                          recursive=True)
        files = [f for f in files if os.path.isfile(f)]
        return len(files), _max_mtime(files)
    if source == "dsh":
        count = 0
        files = []
        try:
            projs = [os.path.join(root, d) for d in os.listdir(root)]
        except OSError:
            projs = []
        for proj in projs:
            if not os.path.isdir(proj):
                continue
            try:
                sess_dirs = [os.path.join(proj, d) for d in os.listdir(proj)]
            except OSError:
                continue
            for sess in sess_dirs:
                if not os.path.isdir(sess):
                    continue
                try:
                    names = os.listdir(sess)
                except OSError:
                    continue
                hits = [os.path.join(sess, n) for n in names
                        if n.startswith("session.")]
                if hits:
                    count += 1
                    files.extend(hits)
        return count, _max_mtime(files)
    if source == "gemini":
        files = glob.glob(os.path.join(root, "*", "chats", "session-*.json*"))
        files = [f for f in files if os.path.isfile(f)]
        return len(files), _max_mtime(files)
    if source in NEW_READER_SOURCES:
        try:
            rows = get_reader(source).list_sessions(root)
        except (OSError, ValueError, KeyError, RuntimeError):
            return 0, 0
        recent = max((_ts_of(r) for r in rows), default=0)
        paths = [r.get("path") for r in rows if r.get("path")]
        return len(rows), recent or _max_mtime(paths)
    if source == "goose":
        db = os.path.join(root, "sessions.db")
        if not os.path.isfile(db):
            return 0, 0
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3F"), uri=True)
            try:
                count = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            count = 0
        return int(count), int(os.stat(db).st_mtime * 1000)
    # claude / omp / qoder / pi: one transcript file per session in <root>/*/*.jsonl
    files = glob.glob(os.path.join(root, "*", "*.jsonl"))
    files = [f for f in files if os.path.isfile(f) and not f.endswith(".lock")]
    return len(files), _max_mtime(files)


def detect(fast=True):
    """Detect locally available harnesses.  Each harness is isolated; failures are notes.

    ``fast=True`` (default) only lists directories/files (no session parsing);
    ``fast=False`` (``asi detect --deep``) uses the precise readers (slower).
    Session counts are intentionally identical for the five core sources.
    """
    out = []
    total_sessions = 0
    detected_count = 0
    for spec in HARNESSES:
        source = spec["id"]
        rec = {
            "id": source,
            "display_name": spec["display_name"],
            "name": spec["display_name"],
            "family": spec["family"],
            "detected": False,
            "path": None,
            "session_count": 0,
            "recent_at": 0,
            "notes": spec.get("notes") or "",
            "capabilities": spec["capabilities"],
            "store_path": spec["root"](),
            "install_supported": bool(spec.get("install_supported")),
            "install_experimental": bool(spec.get("install_experimental")),
            "how_to_see": spec.get("how_to_see") or "",
            "session_dir_hint": spec.get("session_dir_hint") or "",
            "docs_url": "docs/usage.md#产品级命令",
        }
        try:
            root = spec["root"]()
            root = os.path.expanduser(root)
            rec["path"] = root
            if fast:
                count, recent = _fast_scan(source, root)
                rec["session_count"] = count
                rec["recent_at"] = recent
                rec["detected"] = os.path.isdir(root) and (count > 0 or source in FILE_SOURCES)
            else:
                if source in FILE_SOURCES:
                    rows = _file_scan(source, root)
                else:
                    rows = get_reader(source).list_sessions(root)
                rows = [r for r in rows if _session_path_exists(source, r)]
                rec["session_count"] = len(rows)
                recent = max((_ts_of(r) for r in rows), default=0)
                if not recent:
                    recent = max((int(os.stat(r["path"]).st_mtime * 1000) for r in rows
                                  if os.path.isfile(r["path"])), default=0)
                rec["recent_at"] = recent
                rec["detected"] = os.path.isdir(root) and (bool(rows) or source in FILE_SOURCES)
            if rec["detected"]:
                detected_count += 1
                total_sessions += rec["session_count"]
            elif rec["session_count"] == 0:
                rec["notes"] = (rec["notes"] + "；未发现会话").strip("；")
        except (OSError, ValueError, RuntimeError) as exc:  # one bad harness must not fail detect
            rec["notes"] = (rec["notes"] + "；检测失败: %s" % exc).strip("；")
            rec["detected"] = False
        out.append(rec)
    return {
        "ok": True,
        "command": "detect",
        "generated_at": _now_ms(),
        "fast": bool(fast),
        "scan": "fast" if fast else "deep",
        "harnesses": out,
        "totals": {"harnesses_detected": detected_count, "total_sessions": total_sessions},
    }


# --------------------------------------------------------------------------- preview
def _find_session(source, session, root=None):
    if session and os.path.isfile(os.path.expanduser(session)):
        return None, os.path.expanduser(session)
    reader = get_reader(source)
    rows = reader.list_sessions(root)
    if session:
        for row in rows:
            if str(row.get("id")) == str(session) or \
                    os.path.basename(row.get("path") or "") == str(session):
                return row, row["path"]
        raise ValueError("会话不存在: %r（可先运行 asi detect / asi list %s）" % (session, source))
    if not rows:
        raise ValueError("%s 没有可预览的会话" % source)
    return rows[0], rows[0]["path"]


def _blocks_text(blocks, limit=300):
    parts = []
    for b in blocks or []:
        t = b.get("text")
        if isinstance(t, str) and t.strip():
            parts.append(t.strip())
    text = "\n".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def preview(source, session=None, root=None, limit=6, keep_system=False):
    row, path = _find_session(source, session, root=root)
    ir = get_reader(source).load_session(root=root, session=session, path=path,
                                         keep_system=keep_system)
    events = ir.get("events") or []
    counts = {
        "user_messages": (ir.get("stats") or {}).get("user_messages", 0),
        "assistant_messages": (ir.get("stats") or {}).get("assistant_messages", 0),
        "tool_calls": (ir.get("stats") or {}).get("tool_calls", 0),
        "tool_results": (ir.get("stats") or {}).get("tool_results", 0),
    }
    first_user = ""
    tool_names = []
    last = []
    provider = ir.get("provider") or ""
    model = ir.get("model") or ""
    for ev in events:
        kind = ev.get("kind")
        blocks = ev.get("blocks") or []
        if kind == "user_message" and not first_user:
            first_user = _blocks_text(blocks, 500)
        if kind == "assistant_message":
            provider = ev.get("provider") or provider
            model = ev.get("model") or model
        if kind in ("user_message", "assistant_message"):
            for b in blocks:
                if b.get("type") == "tool-call" and b.get("name"):
                    if b["name"] not in tool_names:
                        tool_names.append(b["name"])
        if kind in ("user_message", "assistant_message", "tool_result"):
            role = {"user_message": "user", "assistant_message": "assistant",
                    "tool_result": "tool"}[kind]
            text = _blocks_text(blocks) if kind != "tool_result" else str(ev.get("content") or "")
            text = (text or "")[:300]
            last.append({"role": role, "text": text, "ts": ev.get("ts") or 0})
    tool_names = [n for n in tool_names if n][:24]
    warnings = list(ir.get("warnings") or [])
    return {
        "ok": True,
        "command": "preview",
        "source": source,
        "session_id": ir.get("source_session_id") or (row or {}).get("id") or session,
        "title": ir.get("title") or (row or {}).get("title") or "",
        "cwd": ir.get("cwd"),
        "model": model,
        "provider": provider,
        "created_at_ms": ir.get("created_at_ms") or (row or {}).get("created_at_ms") or 0,
        "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
        "counts": counts,
        "first_user_message": first_user,
        "last_messages": last[-limit:] if limit else [],
        "tool_names": tool_names,
        "warnings": warnings,
        "path": path,
    }


# --------------------------------------------------------------------------- migrate
def _safe(name):
    import re
    return (re.sub(r"[^A-Za-z0-9._-]", "_", str(name)) or "session")[:120]


def _selected_sessions(source, sessions, all_limit, limit, root=None):
    if sessions:
        picks = []
        for item in sessions:
            item = os.path.expanduser(str(item))
            picks.append({"id": item, "path": item if os.path.isfile(item) else None,
                          "ref": item})
        return picks
    rows = get_reader(source).list_sessions(root)
    if limit:
        rows = rows[:limit]
    elif all_limit:
        rows = rows[:all_limit]
    return [{"id": r.get("id"), "path": r.get("path"), "ref": r.get("id")} for r in rows]


import datetime as _dt

# --------------------------------------------------------------------------- v1.4 migrate helpers
JOURNAL_VERSION = 1
_COMPANION = "SessionConverter"          # legacy brand (read compatibility only)
_APP_BRAND = "HarnessBridge"


def _uuid_sid(sid):
    sid = str(sid or "session")
    return sid[8:] if sid.startswith("session-") else sid


def _spec(source):
    return HARNESS_BY_ID.get(source)


def source_root(source):
    spec = _spec(source)
    if spec is None:
        return None
    return spec["root"]()


def install_supported(target):
    spec = _spec(target)
    return bool(spec and spec.get("install_supported"))


def install_target_root(target):
    spec = _spec(target)
    if spec is None:
        return None
    fn = spec.get("install_root")
    return fn() if fn else None


def _require_install_store(target, dsh_home=None):
    if not install_supported(target):
        raise ValueError("%s 没有可写入的本地会话库，请改用 --mode export" % target)
    root = install_target_root(target)
    if target == "dsh":
        base = os.path.abspath(os.path.expanduser(dsh_home or
                                                  (os.environ.get("DSH_HOME") or DSH_DEFAULT_HOME)))
        if not os.path.isdir(base):
            raise ValueError("DSH 数据目录不存在：%s（请先启动 DSH，或改用 --mode export）" % base)
        return base
    if not root or not os.path.isdir(root):
        raise ValueError("目标 store 不存在：%s（请先启动 %s，或改用 --mode export）"
                         % (root, _spec(target)["display_name"]))
    return root


def _stamp(ms):
    ts = float(ms or 0) / 1000.0
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def predict_install_path(target, ir, sid, target_cwd=None, dsh_home=None, fallback_cwd=None):
    """Best-effort destination path for duplicate detection / dry-run plans."""
    cwd = target_cwd or ir.get("cwd") or ""
    created = int(ir.get("created_at_ms") or 0)
    if target == "dsh":
        home = os.path.abspath(os.path.expanduser(dsh_home or
                                                  (os.environ.get("DSH_HOME") or DSH_DEFAULT_HOME)))
        plan = dsh.plan_import(ir, home, target_cwd=target_cwd,
                               fallback_cwd=fallback_cwd or os.getcwd())
        return plan["path"]
    root = install_target_root(target)
    if target == "claude":
        from .writers import claude as _w
        return os.path.join(root, _w.slugify(cwd), _uuid_sid(sid) + ".jsonl")
    if target == "omp":
        from .writers import omp as _w
        slug = _w._slug(cwd, os.path.expanduser("~"))
        name = "%s_%s.jsonl" % (_stamp(created), _uuid_sid(sid))
        return os.path.join(root, slug, name)
    if target == "qoder":
        from .writers import qoder as _w
        return os.path.join(root, _w.slugify(cwd), _uuid_sid(sid) + ".jsonl")
    if target == "codex":
        dt = _dt.datetime.fromtimestamp(created / 1000.0, tz=_dt.timezone.utc)
        return os.path.join(root, "sessions", dt.strftime("%Y"), dt.strftime("%m"),
                            dt.strftime("%d"),
                            "rollout-%s-%s.jsonl" % (dt.strftime("%Y-%m-%dT%H-%M-%S"),
                                                     _uuid_sid(sid)))
    if target == "pi":
        from .writers import native_batch3 as _w
        uid = _w._uuid_sid(sid)
        dt = _dt.datetime.fromtimestamp(created / 1000.0, tz=_dt.timezone.utc)
        stamp = dt.strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z" if created else "1970-01-01T00-00-00-000Z"
        return os.path.join(root, "sessions", _w._slug(cwd), "%s_%s.jsonl" % (stamp, uid))
    if target == "gemini":
        import hashlib
        from .writers import native_batch3 as _w
        project_hash = hashlib.sha256((cwd or "").encode("utf-8")).hexdigest()
        dt = _dt.datetime.fromtimestamp(created / 1000.0, tz=_dt.timezone.utc) if created else None
        stamp = dt.strftime("%Y-%m-%dT%H-%M-%S") if dt else "1970-01-01T00-00-00"
        return os.path.join(root, "tmp", project_hash, "chats",
                            "session-%s-%s.json" % (stamp, _uuid_sid(sid)[:6]))
    raise ValueError("%s 不支持直接安装" % target)


def _backup_path(path):
    return path + ".asi-backup-" + str(int(time.time() * 1000))


def _install_one(target, ir, sid, *, target_cwd=None, dsh_home=None, fallback_cwd=None,
                 overwrite=False, register=False, keep_system=False):
    """Install one IR into the target native store. Returns a result dict (no journal)."""
    from . import writers
    root = _require_install_store(target, dsh_home)
    path = predict_install_path(target, ir, sid, target_cwd=target_cwd, dsh_home=dsh_home,
                                fallback_cwd=fallback_cwd)
    exists = os.path.exists(path)
    rec = {"target": target, "installed_path": path, "installed_root": root,
           "experimental": bool((_spec(target) or {}).get("install_experimental")),
           "store_existed": True, "backup_path": None,
           "verify": {"ok": False, "checked": 0, "failed": 1}}
    if exists and not overwrite:
        rec.update({"status": "skipped-exists",
                    "verify": {"ok": False, "checked": 1, "failed": 0,
                               "note": "目标已存在同 id 会话（--overwrite 可备份后覆盖）"}})
        return rec
    backup = None
    if exists and overwrite:
        backup = _backup_path(path)
        os.replace(path, backup)
        rec["backup_path"] = backup
    created = False
    store_root = os.path.join(dsh_home, "sessions") if target == "dsh" else root
    try:
        if target == "dsh":
            path = _staged_install("dsh", ir, sid, dsh_home=dsh_home,
                                   target_cwd=target_cwd, fallback_cwd=fallback_cwd,
                                   keep_system=keep_system)
            rec["installed_path"] = path
            created = True
            vrep = dsh.verify_file(path)
            verified = not vrep.get("errors")
            rec["verify"] = {"ok": verified, "checked": 1,
                             "failed": len(vrep.get("errors") or []), "method": "dsh verify_file",
                             "errors": (vrep.get("errors") or [])[:5]}
            rec["session_id"] = sid
            rec["verified"] = verified
            if verified and register:
                try:
                    plan = dsh.plan_import(ir, dsh_home, target_cwd=target_cwd,
                                           fallback_cwd=fallback_cwd or os.getcwd(),
                                           keep_system=keep_system)
                    reg_status, reg_detail = dsh.register_in_workspace(
                        dsh_home, plan["cwd"], plan["session_id"], create=False)
                    rec["register"] = {"status": reg_status, "detail": reg_detail}
                except (OSError, ValueError) as exc:
                    rec["register"] = {"status": "failed", "detail": str(exc)}
            rec["verified"] = verified
        else:
            path = _staged_install(target, ir, sid, root=root, target_cwd=target_cwd)
            rec["installed_path"] = path
            created = True
            verified = False
            method = "reader read-back"
            try:
                back = get_reader(target).load_session(path=path)
                events = (back.get("stats") or {}).get("events") or len(back.get("events") or [])
                verified = bool(events)
            except (OSError, ValueError, RuntimeError):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        verified = bool(f.readline().strip())
                except OSError:
                    verified = False
                method = "file-level"
            rec["verify"] = {"ok": verified, "checked": 1, "failed": 0 if verified else 1,
                             "method": method}
            rec["verified"] = verified
        rec["status"] = "ok" if rec.get("verified") else "failed"
        if not rec.get("verified"):
            # roll back the file(s) created by this run; restore the overwrite backup
            try:
                if os.path.isfile(path):
                    os.unlink(path)
                _cleanup_empty_dirs(path, stop=store_root)
            except OSError:
                pass
            if backup and os.path.exists(backup):
                os.replace(backup, path)
                rec["backup_path"] = None
            rec["error"] = "安装后校验失败，已回滚本次新建文件"
    except (OSError, ValueError, RuntimeError) as exc:
        rec["status"] = "failed"
        rec["error"] = str(exc)[:500]
        if backup and os.path.exists(backup):
            try:
                os.replace(backup, path)
            except OSError:
                pass
            rec["backup_path"] = None
    return rec


def _app_support_root():
    """App support root; ``HARNESSBRIDGE_APP_SUPPORT`` overrides it (tests/portable installs)."""
    env = os.environ.get("HARNESSBRIDGE_APP_SUPPORT")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(HOME, "Library", "Application Support")


def _journal_dir():
    """Default (writer) journal dir: the HarnessBridge brand (public release)."""
    return os.path.join(_app_support_root(), _APP_BRAND, "journals")


def _legacy_journal_dir():
    """Old SessionConverter brand dir: read/continuation compatibility only."""
    return os.path.join(HOME, "Library", "Application Support", _COMPANION, "journals")


def _journal_resolve_for_read(journal_path):
    """Resolve a journal for restore: explicit path first, then new/Legacy default dirs by basename."""
    candidate = os.path.abspath(os.path.expanduser(journal_path or ""))
    if os.path.isfile(candidate):
        return candidate
    base = os.path.basename(candidate)
    if base:
        for d in (_journal_dir(), _legacy_journal_dir()):
            p = os.path.join(d, base)
            if os.path.isfile(p):
                return p
    return candidate


def _journal_default():
    """Collision-free default journal name: millisecond + random short suffix."""
    import uuid as _uuid
    dirpath = _journal_dir()
    os.makedirs(dirpath, exist_ok=True)
    now = _dt.datetime.now(_dt.timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S-") + "%03d" % (now.microsecond // 1000)
    while True:
        name = "migrate-%s-%s.json" % (stamp, _uuid.uuid4().hex[:6])
        path = os.path.join(dirpath, name)
        if not os.path.exists(path):
            return path


def _atomic_write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-" + str(os.getpid()) + "-" + str(int(time.time() * 1000))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


def _write_journal(path, payload):
    path = os.path.abspath(os.path.expanduser(path or _journal_default()))
    payload = dict(payload)
    payload.setdefault("journal_version", JOURNAL_VERSION)
    payload.setdefault("created_at", _dt.datetime.now(_dt.timezone.utc).isoformat())
    return _atomic_write_json(path, payload)


def _journal_append(path, base, entries):
    """Incrementally (atomically) persist entries after each completed session."""
    payload = dict(base)
    payload["entries"] = list(entries)
    payload.setdefault("journal_version", JOURNAL_VERSION)
    payload.setdefault("created_at", _dt.datetime.now(_dt.timezone.utc).isoformat())
    return _atomic_write_json(path, payload)


def _cleanup_empty_dirs(path, stop=None):
    """Remove only empty directories we created, never files; stop at store root."""
    d = os.path.dirname(os.path.abspath(path))
    stop = os.path.realpath(stop) if stop else None
    while d and os.path.isdir(d):
        if stop and os.path.realpath(d) == stop:
            break
        try:
            os.rmdir(d)  # fails when non-empty -> safe
        except OSError:
            break
        d = os.path.dirname(d)


def _staged_install(target, ir, sid, *, root=None, dsh_home=None, target_cwd=None,
                    fallback_cwd=None, keep_system=False):
    """Write to a temp staging dir first, then atomically rename into the target store."""
    import shutil
    import tempfile
    if target == "dsh":
        base_home = _require_install_store("dsh", dsh_home)
        parent = os.path.dirname(base_home) or base_home
        tmp_home = tempfile.mkdtemp(prefix=".asi-tmp-", dir=parent)
        try:
            plan = dsh.plan_import(ir, tmp_home, target_cwd=target_cwd,
                                   fallback_cwd=fallback_cwd or os.getcwd(),
                                   keep_system=keep_system)
            dsh.write_import(plan, overwrite=True)
            final = os.path.join(base_home, os.path.relpath(plan["path"], tmp_home))
            os.makedirs(os.path.dirname(final), exist_ok=True)
            os.replace(plan["path"], final)
            return final
        finally:
            shutil.rmtree(tmp_home, ignore_errors=True)
    from . import writers
    root = root or _require_install_store(target)
    parent = os.path.dirname(root) or root
    tmp_root = tempfile.mkdtemp(prefix=".asi-tmp-", dir=parent)
    try:
        res = writers.native_write(ir, target, tmp_root, sid, target_cwd=target_cwd)
        rel = os.path.relpath(res["artifact"], tmp_root)
        final = os.path.join(root, rel)
        os.makedirs(os.path.dirname(final), exist_ok=True)
        os.replace(res["artifact"], final)
        return final
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _move_source_file(source_path, stamp):
    """Rename (never delete) a source session file to *.migrated-<ts>.bak."""
    if not source_path or not os.path.isfile(source_path):
        raise ValueError("源会话文件不存在，无法移出：%r" % (source_path,))
    dst = source_path + ".migrated-" + str(stamp) + ".bak"
    os.replace(source_path, dst)
    return dst


def _resolve_source_path(source, item, root=None):
    """Resolve the real source file for a session ref/id (plan/results/journal contract)."""
    path = item.get("path")
    if path and os.path.isfile(path):
        return os.path.abspath(path)
    session = item.get("id") or item.get("ref")
    if not session:
        return None
    reader = get_reader(source)
    src_root = root if root is not None else source_root(source)
    fn = getattr(reader, "resolve_path", None)
    if fn is not None:
        for args in ((src_root, session), (session,)):
            try:
                res = fn(*args)
            except (TypeError, OSError, ValueError):
                continue
            if res and os.path.isfile(res):
                return os.path.abspath(res)
    try:
        rows = reader.list_sessions(src_root)
    except (OSError, ValueError, RuntimeError):
        return None
    for row in rows:
        rid = str(row.get("id") or "")
        rpath = row.get("path") or ""
        if rid == str(session) or os.path.basename(rpath) == str(session) or \
                os.path.basename(os.path.dirname(rpath)) == str(session):
            if rpath and os.path.isfile(rpath):
                return os.path.abspath(rpath)
    return None


def _apply_move(rec, source_path, stamp):
    """Move (rename, never delete) the source session file; always report explicitly."""
    rec["source_moved"] = False
    rec["source_path"] = source_path
    if not source_path:
        rec["source_move_status"] = "unsupported"
        rec["source_move_error"] = "无法定位源会话文件（source_path=None）；本次未移出源"
        rec.setdefault("warnings", []).append("move 未执行：无法定位源会话文件（该源可能仅有内存/session ref）")
        return rec
    if os.path.isdir(source_path):
        rec["source_move_status"] = "unsupported"
        rec["source_move_error"] = "源会话是目录/多文件会话，暂不支持 move（不会假装已移出）"
        rec.setdefault("warnings", []).append("move 未执行：目录/多文件源暂不支持（源未被修改）")
        return rec
    if not os.path.isfile(source_path):
        rec["source_move_status"] = "failed"
        rec["source_move_error"] = "源会话文件不存在，无法移出：%s" % source_path
        return rec
    try:
        parent = os.path.dirname(os.path.abspath(source_path))
        backup = _move_source_file(source_path, stamp)
        rec["source_moved"] = True
        rec["source_move_status"] = "moved"
        rec["source_backup_path"] = backup
        rec["source_path"] = os.path.abspath(source_path)
        rec["source_dir"] = parent
        rec["source_files"] = [os.path.basename(rec["source_path"])]
        if os.path.isdir(parent):
            try:
                rec["source_dir_kept_empty"] = not any(os.listdir(parent))
            except OSError:
                rec["source_dir_kept_empty"] = False
        if rec.get("source_dir_kept_empty"):
            rec.setdefault("warnings", []).append(
                "move 后源 session 目录为空；为安全起见保留目录（未删除）")
    except (OSError, ValueError) as exc:
        rec["source_move_status"] = "failed"
        rec["source_move_error"] = str(exc)
    return rec


def _session_pair(source, item, root, keep_system=False):
    reader = get_reader(source)
    ir = reader.load_session(root=root, session=item.get("ref"), path=item.get("path"),
                             keep_system=keep_system)
    return ir


def migrate(source, sessions=None, all_limit=None, limit=None, to="dsh", out=None,
            mode=None, target_cwd=None, register=False, dry_run=False, yes=False,
            dsh_home=None, fallback_cwd=None, overwrite=False, keep_system=False, root=None,
            all_sessions=False, session_mode="keep", journal=None):
    dsh_home = os.path.abspath(os.path.expanduser(dsh_home or
                                                  (os.environ.get("DSH_HOME") or DSH_DEFAULT_HOME)))
    out_root = os.path.abspath(os.path.expanduser(out or "asi-migrate"))
    if session_mode not in ("keep", "move"):
        return {"ok": False, "command": "migrate", "error": "session-mode 必须是 keep 或 move"}
    supported = install_supported(to)
    effective_mode = mode if mode in ("install", "export") else ("install" if supported else "export")
    if effective_mode == "install":
        if not supported:
            return {"ok": False, "command": "migrate",
                    "error": "%s 没有可写入的本地会话库，请改用 --mode export" % to}
        if not yes and not dry_run:
            return {"ok": False, "command": "migrate", "error": "install 模式需要 --yes 确认",
                    "requires_yes": True}
        if session_mode == "move":
            pass  # move is two-step-safe (only after verified install); UI must confirm
        try:
            _require_install_store(to, dsh_home)
        except ValueError as exc:
            return {"ok": False, "command": "migrate", "error": str(exc)}
    if not sessions and not all_sessions:
        return {"ok": False, "command": "migrate",
                "error": "请用 --session <id>（可重复）或 --all（可选 --all-limit N）选择会话"}
    src_root = root if root is not None else source_root(source)
    try:
        picks = _selected_sessions(source, sessions, all_limit, limit, root=src_root)
    except (OSError, ValueError) as exc:
        return {"ok": False, "command": "migrate", "error": str(exc), "results": [], "plan": []}
    if not picks:
        return {"ok": True, "command": "migrate", "source": source, "to": to,
                "mode": effective_mode, "session_mode": session_mode, "dry_run": bool(dry_run),
                "out": out_root if effective_mode == "export" else None, "plan": [], "results": [],
                "summary": {"total": 0, "ok": 0, "failed": 0, "skipped": 0, "moved": 0,
                            "verified": 0, "lossy": 0}, "journal_path": None}
    # plans (dry-run needs real IR only for install path prediction)
    plan, plan_irs = [], []
    for item in picks:
        sid = str(item.get("id") or item.get("ref") or "session")
        source_path = _resolve_source_path(source, item, src_root)
        entry = {"source_session_id": sid, "to": to, "mode": effective_mode,
                 "session_mode": session_mode, "source_path": source_path,
                 "source_movable": bool(source_path and os.path.isfile(source_path)),
                 "will_write_real_store": effective_mode == "install"}
        if effective_mode == "install":
            try:
                ir = _session_pair(source, item, src_root, keep_system)
            except (OSError, ValueError) as exc:
                entry.update({"error": "读取源会话失败: %s" % exc, "target": None})
                plan.append(entry)
                plan_irs.append(None)
                continue
            try:
                sid = str(ir.get("source_session_id") or sid)
                entry["source_session_id"] = sid
                target_path = predict_install_path(to, ir, sid, target_cwd=target_cwd,
                                                   dsh_home=dsh_home,
                                                   fallback_cwd=fallback_cwd or os.getcwd())
            except (OSError, ValueError) as exc:
                target_path = None
                entry["error"] = str(exc)
            entry.update({"target": target_path,
                          "target_store": install_target_root(to),
                          "will_skip": bool(target_path and os.path.exists(target_path)
                                            and not overwrite),
                          "will_overwrite": bool(target_path and os.path.exists(target_path)
                                                 and overwrite),
                          "note": "写入真实 store；--session-mode=%s" % session_mode})
            plan_irs.append(ir)
        else:
            entry["target"] = os.path.join(out_root, to, _safe(sid))
            entry["note"] = "只写 --out 导出目录，不修改任何 harness 存储"
            plan_irs.append(None)
        plan.append(entry)
    base = {
        "ok": True, "command": "migrate", "source": source, "to": to,
        "mode": effective_mode, "session_mode": session_mode,
        "dry_run": bool(dry_run),
        "out": out_root if effective_mode == "export" else None,
        "dsh_home": dsh_home if to == "dsh" else None,
        "register": bool(register), "plan": plan, "results": [],
        "summary": {"total": len(picks), "ok": 0, "failed": 0, "skipped": 0, "moved": 0,
                    "verified": 0, "lossy": 0}, "journal_path": None,
    }
    if dry_run:
        return base
    if effective_mode == "export":
        os.makedirs(out_root, exist_ok=True)
    journal_path = None
    journal_entries = []
    journal_base = {
        "command": "migrate", "source": source, "target": to,
        "mode": effective_mode, "session_mode": session_mode,
        "target_store": install_target_root(to),
        "dsh_home": dsh_home if to == "dsh" else None,
    }
    if effective_mode == "install" and journal:
        journal_path = os.path.abspath(os.path.expanduser(journal))
    elif effective_mode == "install":
        journal_path = _journal_default()
    results = []
    stamp = int(time.time() * 1000)
    for item, pl, maybe_ir in zip(picks, plan, plan_irs):
        sid = str(item.get("id") or item.get("ref") or "session")
        rec = {"source_session_id": sid, "status": "failed", "output_dir": None,
               "artifact": None, "mode": effective_mode, "target": to,
               "verify": {"ok": False, "checked": 0, "failed": 1},
               "lossy": [], "warnings": []}
        try:
            if maybe_ir is not None:
                ir = maybe_ir
            else:
                ir = _session_pair(source, item, src_root, keep_system)
            sid = str(ir.get("source_session_id") or sid)
            rec["source_session_id"] = sid
            src_path = _resolve_source_path(source, item, src_root)
            rec["source_path"] = src_path
            rec["title"] = ir.get("title") or ""
            rec["cwd"] = ir.get("cwd")
            rec["warnings"] = list(ir.get("warnings") or [])
            lossy = []
            for ev in ir.get("events") or []:
                if ev.get("kind") == "tool_result" and \
                        str(ev.get("content") or "").strip() == "[tool result missing in source session]":
                    lossy.append("missing_tool_result")
            val = ir.get("lossy")
            if isinstance(val, list):
                lossy.extend(str(v) for v in val)
            elif val:
                lossy.append(str(val))
            rec["lossy"] = sorted(set(lossy))
            if effective_mode == "install":
                installed = _install_one(to, ir, sid, target_cwd=target_cwd, dsh_home=dsh_home,
                                         fallback_cwd=fallback_cwd, overwrite=overwrite,
                                         register=register, keep_system=keep_system)
                rec.update(installed)
                rec["installed_path"] = installed.get("installed_path")
                rec["artifact"] = installed.get("installed_path")
                rec["output_dir"] = installed.get("installed_root")
                rec["verified"] = bool(installed.get("verified"))
                rec["backup_path"] = installed.get("backup_path")
                if installed.get("status") == "skipped-exists":
                    rec["status"] = "skipped-exists"
                elif installed.get("status") == "ok":
                    rec["status"] = "ok"
                    if session_mode == "move":
                        _apply_move(rec, src_path, stamp)
                else:
                    rec["status"] = "failed"
                    rec["error"] = installed.get("error") or "安装失败"
            else:  # export (existing behavior)
                adir = os.path.join(out_root, to, _safe(sid))
                os.makedirs(adir, exist_ok=True)
                if to == "atif":
                    doc = atif.to_atif(ir)
                    path = os.path.join(adir, _safe(sid) + ".atif.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(doc, f, ensure_ascii=False, indent=1)
                        f.write("\n")
                    errs, _warns = atif.validate(doc)
                    rec.update({"output_dir": adir, "artifact": path, "status": "ok",
                                "verify": {"ok": not errs, "checked": 1,
                                           "failed": len(errs), "errors": errs[:5]},
                                "atif_steps": len(doc.get("steps") or [])})
                elif to == "ir":
                    from .ir import save as save_ir
                    path = os.path.join(adir, "ir.json")
                    save_ir(path, ir)
                    rec.update({"output_dir": adir, "artifact": path, "status": "ok",
                                "verify": {"ok": os.path.exists(path), "checked": 1}})
                else:
                    from . import writers
                    res = writers.write_ir_to(ir, to, adir, sid, target_cwd=target_cwd)
                    artifact = res.get("artifact")
                    verify = {"ok": bool(artifact and os.path.exists(artifact)),
                              "checked": 1, "failed": 0}
                    if to == "dsh" and artifact:
                        vrep = dsh.verify_file(artifact)
                        verify = {"ok": not vrep.get("errors"), "checked": 1,
                                  "failed": len(vrep.get("errors") or []),
                                  "errors": (vrep.get("errors") or [])[:5]}
                    rec.update({"output_dir": adir, "artifact": artifact,
                                "status": "ok", "verify": verify})
            if not rec.get("output_dir") and rec.get("artifact"):
                rec["output_dir"] = os.path.dirname(rec["artifact"])
        except (OSError, ValueError, RuntimeError) as exc:
            rec["status"] = "failed"
            rec["error"] = str(exc)[:500]
            rec["verify"] = {"ok": False, "checked": 0, "failed": 1}
        results.append(rec)
        if effective_mode == "install":
            entry = {k: rec.get(k) for k in ("source_session_id", "status", "target",
                                             "installed_path", "verified", "backup_path",
                                             "source_moved", "source_move_status",
                                             "source_move_error", "source_backup_path",
                                             "source_path", "source_dir", "source_files",
                                             "source_dir_kept_empty", "error")}
            journal_entries.append(entry)
            # incremental atomic journal update: completed move mappings survive later failures
            _journal_append(journal_path, journal_base, journal_entries)
    ok_n = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped-exists")
    moved = sum(1 for r in results if r.get("source_moved"))
    failed = sum(1 for r in results if r["status"] == "failed")
    verified = sum(1 for r in results if r["status"] == "ok" and (r.get("verify") or {}).get("ok"))
    lossy_n = sum(1 for r in results if r.get("lossy"))
    if not journal_entries:
        journal_path = None
    base.update({
        "ok": failed == 0,
        "results": results,
        "journal_path": journal_path,
        "summary": {"total": len(results), "ok": ok_n, "failed": failed,
                    "skipped": skipped, "moved": moved, "verified": verified,
                    "lossy": lossy_n},
    })
    return base


# --------------------------------------------------------------------------- migrate-all
def migrate_all(to, sources=None, limit=None, since_days=None, session_mode="keep",
                dry_run=False, yes=False, overwrite=False, target_cwd=None, dsh_home=None,
                journal=None, register=False, keep_system=False):
    if not install_supported(to):
        return {"ok": False, "command": "migrate-all",
                "error": "%s 没有可写入的本地会话库，请改用 --mode export" % to}
    dsh_home = os.path.abspath(os.path.expanduser(dsh_home or
                                                  (os.environ.get("DSH_HOME") or DSH_DEFAULT_HOME)))
    try:
        _require_install_store(to, dsh_home)
    except ValueError as exc:
        return {"ok": False, "command": "migrate-all", "error": str(exc)}
    if session_mode not in ("keep", "move"):
        return {"ok": False, "command": "migrate-all", "error": "session-mode 必须是 keep 或 move"}
    if not dry_run and not yes:
        return {"ok": False, "command": "migrate-all", "error": "migrate-all 需要 --yes 确认",
                "requires_yes": True}
    wanted = set(s.strip() for s in (sources or "").split(",") if s.strip())
    now = int(time.time() * 1000)
    plan_sources, tasks = [], []
    for spec in HARNESSES:
        source = spec["id"]
        if source == to:
            continue
        if wanted and source not in wanted:
            continue
        root = spec["root"]()
        if not os.path.isdir(root):
            continue
        try:
            rows = get_reader(source).list_sessions(root)
        except (OSError, ValueError, RuntimeError):
            continue
        rows = [r for r in rows if _session_path_exists(source, r)]
        if since_days:
            cutoff = now - int(float(since_days) * 86400 * 1000)
            rows = [r for r in rows
                    if int(r.get("updated_at_ms") or r.get("created_at_ms") or 0) >= cutoff]
        selected = rows[:limit] if limit else rows
        if not selected:
            continue
        plan_sources.append({"id": source, "display_name": spec["display_name"],
                             "store_path": root, "session_count": len(rows),
                             "selected": len(selected)})
        for row in selected:
            tasks.append({"source": source, "row": row, "root": root})
    total_planned = len(tasks)
    base = {"ok": True, "command": "migrate-all", "to": to,
            "target_store": install_target_root(to) if to != "dsh" else dsh_home,
            "session_mode": session_mode, "dry_run": bool(dry_run),
            "plan": {"sources": plan_sources, "total": total_planned,
                     "will_write_real_store": not dry_run,
                     "note": "来源=其他已检测 Harness；重复会话默认跳过"},
            "results": [], "journal_path": None,
            "summary": {"total": total_planned, "ok": 0, "failed": 0, "skipped": 0,
                        "moved": 0, "verified": 0}}
    if dry_run:
        items = []
        skip_count = 0
        for task in tasks:
            source, row = task["source"], task["row"]
            sid = str(row.get("id") or os.path.basename(row.get("path") or "session"))
            try:
                ir = get_reader(source).load_session(root=task["root"], session=sid,
                                                    path=row.get("path"))
                target_path = predict_install_path(to, ir, sid, target_cwd=target_cwd,
                                                   dsh_home=dsh_home,
                                                   fallback_cwd=os.getcwd())
                will_skip = bool(target_path and os.path.exists(target_path)
                                 and not overwrite)
            except (OSError, ValueError, RuntimeError):
                target_path, will_skip = None, False
            items.append({"source": source, "source_session_id": sid,
                          "source_path": row.get("path"), "target_path": target_path,
                          "will_skip": will_skip})
            skip_count += 1 if will_skip else 0
        base["plan"].update({"items": items, "skip_count": skip_count,
                             "will_skip": skip_count})
        return base
    journal_path = os.path.abspath(os.path.expanduser(journal)) if journal else _journal_default()
    journal_entries = []
    journal_base = {
        "command": "migrate-all", "target": to, "session_mode": session_mode,
        "target_store": install_target_root(to) if to != "dsh" else dsh_home,
    }
    results = []
    stamp = int(time.time() * 1000)
    for task in tasks:
        source, row = task["source"], task["row"]
        sid = str(row.get("id") or os.path.basename(row.get("path") or "session"))
        rec = {"source": source, "source_session_id": sid, "status": "failed",
               "source_path": row.get("path"), "target": to,
               "source_move_status": None,
               "verify": {"ok": False, "checked": 0, "failed": 1}}
        try:
            ir = get_reader(source).load_session(root=task["root"], session=sid,
                                                path=row.get("path"), keep_system=keep_system)
            installed = _install_one(to, ir, sid, target_cwd=target_cwd, dsh_home=dsh_home,
                                     overwrite=overwrite, register=register,
                                     keep_system=keep_system)
            rec.update(installed)
            rec["installed_path"] = installed.get("installed_path")
            rec["artifact"] = installed.get("installed_path")
            rec["output_dir"] = installed.get("installed_root")
            rec["verified"] = bool(installed.get("verified"))
            if installed.get("status") == "skipped-exists":
                rec["status"] = "skipped-exists"
            elif installed.get("status") == "ok":
                rec["status"] = "ok"
                if session_mode == "move":
                    _apply_move(rec, rec.get("source_path"), stamp)
            else:
                rec["status"] = "failed"
                rec["error"] = installed.get("error") or "安装失败"
        except (OSError, ValueError, RuntimeError) as exc:
            rec["status"] = "failed"
            rec["error"] = str(exc)[:500]
        results.append(rec)
        if True:  # migrate-all always installs
            entry = {k: rec.get(k) for k in ("source_session_id", "status", "target",
                                             "installed_path", "verified", "backup_path",
                                             "source_moved", "source_move_status",
                                             "source_move_error", "source_backup_path",
                                             "source_path", "source_dir", "source_files",
                                             "source_dir_kept_empty", "error")}
            journal_entries.append(entry)
            # incremental atomic journal update: completed move mappings survive later failures
            _journal_append(journal_path, journal_base, journal_entries)
    ok_n = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped-exists")
    failed = sum(1 for r in results if r["status"] == "failed")
    moved = sum(1 for r in results if r.get("source_moved"))
    verified = sum(1 for r in results if r["status"] == "ok" and (r.get("verify") or {}).get("ok"))
    entries = [{k: r.get(k) for k in ("source", "source_session_id", "status",
                                      "installed_path", "verified", "source_moved",
                                      "source_move_status", "source_move_error",
                                      "source_backup_path", "source_path", "error")}
               for r in results]
    for entry in entries:
        if entry.get("source_path"):
            entry["source_dir"] = os.path.dirname(entry["source_path"])
            entry["source_files"] = [os.path.basename(entry["source_path"])]
    base.update({"ok": failed == 0, "results": results, "journal_path": journal_path,
                 "summary": {"total": len(results), "ok": ok_n, "failed": failed,
                             "skipped": skipped, "moved": moved, "verified": verified}})
    return base


# --------------------------------------------------------------------------- migrate-restore
def migrate_restore(journal_path, remove_installed=False, dry_run=False):
    given = journal_path or ""
    path = _journal_resolve_for_read(given)
    if not os.path.isfile(path):
        return {"ok": False, "command": "migrate-restore",
                "error": "迁移日志不存在：%s（已尝试默认目录 %s 与旧目录 %s）"
                         % (given or path, _journal_dir(), _legacy_journal_dir())}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        return {"ok": False, "command": "migrate-restore", "error": "日志无法读取: %s" % exc}
    entries = data.get("entries") or []
    results = []
    for entry in entries:
        rec = {"source": entry.get("source") or data.get("source"),
               "source_session_id": entry.get("source_session_id"),
               "source_path": entry.get("source_path"),
               "source_backup_path": entry.get("source_backup_path"),
               "installed_path": entry.get("installed_path"),
               "status": "skipped", "restored": False, "removed_installed": False}
        backup = entry.get("source_backup_path")
        original = entry.get("source_path")
        if backup and original:
            if not os.path.isfile(backup):
                rec.update({"status": "already-restored" if os.path.isfile(original)
                            else "missing-backup"})
            elif os.path.isfile(original):
                rec.update({"status": "skipped-original-exists"})
            elif dry_run:
                rec.update({"status": "would-restore"})
            else:
                try:
                    os.replace(backup, original)
                    rec.update({"status": "restored", "restored": True})
                except OSError as exc:
                    rec.update({"status": "failed", "error": str(exc)})
        else:
            rec.update({"status": "no-source-backup"})
        installed = entry.get("installed_path")
        if remove_installed and installed and os.path.isfile(installed):
            if dry_run:
                rec["would_remove_installed"] = True
            else:
                try:
                    os.unlink(installed)
                    rec["removed_installed"] = True
                except OSError as exc:
                    rec["remove_installed_error"] = str(exc)
        results.append(rec)
    restored = sum(1 for r in results if r.get("restored"))
    removed = sum(1 for r in results if r.get("removed_installed"))
    failed = sum(1 for r in results if r["status"] == "failed")
    return {"ok": failed == 0, "command": "migrate-restore", "journal": path,
            "dry_run": bool(dry_run),
            "results": results,
            "summary": {"total": len(results), "restored": restored,
                        "removed_installed": removed, "failed": failed,
                        "rest" if False else "skipped": sum(1 for r in results
                                                           if r["status"] not in
                                                           ("restored", "failed"))}}


# --------------------------------------------------------------------------- session-detail
SOURCE_LABELS = {
    "claude": "Claude Code", "codex": "OpenAI Codex", "dsh": "DeepSeek Harness",
    "omp": "Oh My Pi (OMP)", "qoder": "Qoder", "pi": "Pi", "gemini": "Gemini CLI",
    "goose": "Goose", "oss": "OSS 采集样本", "atif": "ATIF 轨迹",
    "copilot": "GitHub Copilot CLI", "aider": "Aider", "cursor": "Cursor CLI",
    "qwen": "Qwen Code", "openclaw": "OpenClaw", "kimi": "Kimi Code",
    "grok": "Grok Build", "droid": "Factory Droid", "antigravity": "Google Antigravity",
    "hermes": "Hermes", "devin": "Devin CLI", "opencode": "OpenCode",
    "continue": "Continue", "junie": "JetBrains Junie", "kiro": "Kiro CLI",
    "crush": "Crush", "cline": "Cline CLI", "roo": "Roo Code",
    "kilo-code": "Kilo Code", "codebuff": "Codebuff", "openhands": "OpenHands",
    "vibe": "Mistral Vibe", "mini-swe-agent": "mini-swe-agent", "fx": "vercel-labs FX",
    "codebuddy": "Tencent CodeBuddy",
}
NATIVE_LOCAL = {"claude", "codex", "dsh", "omp", "qoder"}


def _source_label(source):
    if source in SOURCE_LABELS:
        return SOURCE_LABELS[source]
    if source in HARNESS_BY_ID:
        return HARNESS_BY_ID[source]["display_name"]
    return source


def _evidence_level(source, ir, path):
    extra = ir.get("extra") or {}
    if extra.get("evidence_level"):
        return extra["evidence_level"]
    real_home = os.path.realpath(HOME)
    real_path = os.path.realpath(path or ir.get("source_path") or "")
    if source in NATIVE_LOCAL:
        return "LOCAL" if real_path.startswith(real_home) else "FIXTURE"
    if source == "oss":
        return "COLLECTED"
    if source == "atif":
        return "ATIF"
    if "constructed" in real_path:
        return "FIXTURE-CONSTRUCTED"
    return "FIXTURE"


def _usage_of(ev):
    """Normalize a raw per-event usage dict to the product usage shape."""
    raw = ev.get("usage")
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        from .ir import normalize_usage
        norm = normalize_usage(raw)
    except (ValueError, TypeError):
        norm = None
    if norm is None:
        # some readers keep already-normalized values (inputTokens/outputTokens)
        try:
            inp = int(raw.get("inputTokens") or 0)
            out = int(raw.get("outputTokens") or 0)
        except (TypeError, ValueError):
            return None
        norm = {"inputTokens": inp, "outputTokens": out,
                "cacheReadTokens": int(raw.get("cacheReadTokens") or 0),
                "cacheWriteTokens": int(raw.get("cacheWriteTokens") or 0),
                "totalTokens": int(raw.get("totalTokens") or (inp + out))}
    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    cache_read = _int(norm.get("cacheReadTokens") or raw.get("cached_input_tokens")
                      or raw.get("cache_read_input_tokens") or raw.get("cache_read_tokens")
                      or raw.get("cacheReadTokens"))
    cache_write = _int(norm.get("cacheWriteTokens") or raw.get("cache_write_input_tokens")
                       or raw.get("cache_creation_input_tokens") or raw.get("cache_write_tokens")
                       or raw.get("cacheWriteTokens"))
    inp = _int(norm.get("inputTokens"))
    out = _int(norm.get("outputTokens"))
    total = _int(norm.get("totalTokens")) or (inp + out + cache_read + cache_write)
    row = {"input_tokens": inp, "output_tokens": out,
           "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
           "total_tokens": total}
    # a usage dict whose every counter is 0 carries no real token data (e.g. synthetic fixtures)
    if not any(row.values()):
        return None
    return row


def _resolve_detail_source(source, session, root):
    if source == "atif":
        path = atif.resolve_path(os.path.expanduser(root or "."), session)
        if not path:
            raise ValueError("ATIF 轨迹不存在: %r" % session)
        doc = atif.load(path)
        errs, _warns = atif.validate(doc)
        if errs:
            raise ValueError("ATIF 轨迹无效: " + "; ".join(errs[:3]))
        return atif.from_atif(doc, source_path=path), path
    row, path = _find_session(source, session, root=root)
    ir = get_reader(source).load_session(root=root, session=session, path=path,
                                         keep_system=True)
    return ir, path


def _normalize_codex_usage(raw):
    """Codex token_usage_record.usage -> product usage (incremental per response)."""
    if not isinstance(raw, dict):
        return None
    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    inp = _int(raw.get("input_tokens"))
    out = _int(raw.get("output_tokens"))
    cache_read = _int(raw.get("cached_input_tokens") or raw.get("cache_read_input_tokens"))
    cache_write = _int(raw.get("cache_write_input_tokens"))
    total = _int(raw.get("total_tokens")) or (inp + out + cache_read + cache_write)
    if not (inp or out or cache_read or cache_write or total):
        return None
    return {"input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
            "total_tokens": total}


def _codex_usage_from_rollout(path):
    """Read a Codex rollout: token_usage_record is per-response incremental; token_count
    .total_token_usage is a cumulative thread counter (only used as a cross-check/fallback).

    Empirically (real ~/.codex sessions): sum(token_usage_record.usage) == last
    token_count.info.total_token_usage.total_tokens for a self-contained rollout; on
    resumed/compacted threads token_count may include earlier rollout segments, so the
    per-file sum is the correct file-scoped value.
    """
    if not path or not os.path.isfile(path):
        return None
    records, last_total = [], None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                rtype = row.get("type")
                payload = row.get("payload") or {}
                if rtype == "token_usage_record":
                    u = _normalize_codex_usage(payload.get("usage"))
                    if u:
                        records.append(u)
                elif rtype == "event_msg" and payload.get("type") == "token_count":
                    total = ((payload.get("info") or {}).get("total_token_usage")) or {}
                    try:
                        last_total = int(total.get("total_tokens") or 0)
                    except (TypeError, ValueError):
                        last_total = None
    except OSError:
        return None
    if not records and last_total is None:
        return None
    if records:
        totals = {k: sum(r[k] for r in records) for k in ("input_tokens", "output_tokens",
                                                          "cache_read_tokens",
                                                          "cache_write_tokens",
                                                          "total_tokens")}
        sum_total = totals["total_tokens"]
        match = bool(last_total is not None and last_total == sum_total)
        return {"records": records, "totals": totals, "last_token_count_total": last_total,
                "caliber": "codex_token_usage_record_incremental",
                "crosscheck": "match" if match else "file_scoped"}
    # no per-response records: fall back to the cumulative token_count counter
    return {"records": [], "totals": None, "last_token_count_total": last_total,
            "caliber": "codex_token_count_cumulative"}


def _clip(text, limit):
    text = text or ""
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def session_detail(source, session, root=None, max_events=2000, text_limit=400):
    """Build the product session-detail payload (spec §7.2).  Read-only."""
    max_events = int(max_events or 0)
    text_limit = int(text_limit or 400)
    ir, path = _resolve_detail_source(source, session, root)
    warnings = list(ir.get("warnings") or [])
    codex_extra = None
    if source == "codex":
        codex_extra = _codex_usage_from_rollout(path)
        if codex_extra and codex_extra.get("records"):
            assist = [e for e in ir.get("events") or [] if e.get("kind") == "assistant_message"]
            if len(assist) == len(codex_extra["records"]):
                for ev, u in zip(assist, codex_extra["records"]):
                    ev["usage"] = u
    meta = {
        "title": ir.get("title") or "",
        "cwd": ir.get("cwd"),
        "model": ir.get("model") or "",
        "provider": ir.get("provider") or "",
        "created_at_ms": ir.get("created_at_ms") or 0,
        "updated_at_ms": ir.get("updated_at_ms") or ir.get("created_at_ms") or 0,
        "path": path,
        "source_label": _source_label(source),
        "evidence_level": _evidence_level(source, ir, path),
    }
    # first pass: stats over the whole session
    msg_counts = {"user": 0, "assistant": 0, "tool": 0, "reasoning": 0,
                  "system": 0, "compaction": 0}
    tool_calls = tool_results = tool_errors = 0
    tool_usage = {}
    raw_timeline = []
    usage_acc = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "total_tokens": 0}
    usage_seen = 0
    first_ts = last_ts = 0
    for ev in ir.get("events") or []:
        kind = ev.get("kind")
        ts = ev.get("ts") or 0
        if ts:
            first_ts = ts if not first_ts else min(first_ts, ts)
            last_ts = max(last_ts, ts)
        usage = _usage_of(ev)
        if usage:
            usage_seen += 1
            for k in usage_acc:
                usage_acc[k] += usage[k]
        if kind == "user_message":
            msg_counts["user"] += 1
            text = "\n".join(b.get("text") or "" for b in ev.get("blocks") or []
                              if b.get("type") == "text")
            raw_timeline.append({"ts": ts, "kind": "user", "role": "user",
                                 "text": _clip(text, text_limit), "usage": None})
        elif kind == "assistant_message":
            msg_counts["assistant"] += 1
            used_usage = False
            for b in ev.get("blocks") or []:
                bt = b.get("type")
                if bt == "text":
                    txt = b.get("text") or ""
                    if not txt.strip():
                        continue
                    raw_timeline.append({"ts": ts, "kind": "assistant", "role": "assistant",
                                         "text": _clip(txt, text_limit),
                                         "usage": (usage if not used_usage else None)})
                    used_usage = used_usage or bool(usage)
                elif bt == "reasoning":
                    msg_counts["reasoning"] += 1
                    raw_timeline.append({"ts": ts, "kind": "thinking", "role": "assistant",
                                         "text": _clip(b.get("text") or "", text_limit),
                                         "usage": (usage if not used_usage else None)})
                    used_usage = used_usage or bool(usage)
                elif bt == "tool-call":
                    tool_calls += 1
                    name = b.get("name") or "tool"
                    tool_usage[name] = tool_usage.get(name, 0) + 1
                    raw_timeline.append({
                        "ts": ts, "kind": "tool_call", "role": "assistant",
                        "text": _clip(b.get("arguments") or "", text_limit),
                        "tool": {"name": name, "call_id": b.get("id") or "",
                                 "is_error": False},
                        "usage": (usage if not used_usage else None),
                    })
                    used_usage = used_usage or bool(usage)
        elif kind == "tool_result":
            tool_results += 1
            msg_counts["tool"] += 1
            err = bool(ev.get("is_error"))
            if err:
                tool_errors += 1
            raw_timeline.append({
                "ts": ts, "kind": "tool_result", "role": "tool",
                "text": _clip(str(ev.get("content") or ""), text_limit),
                "tool": {"name": ev.get("name") or "tool",
                         "call_id": ev.get("call_id") or "", "is_error": err},
                "usage": None,
            })
        elif kind == "system_message":
            msg_counts["system"] += 1
            raw_timeline.append({"ts": ts, "kind": "system", "role": "system",
                                 "text": _clip(ev.get("text") or "", text_limit),
                                 "usage": None})
        elif kind == "compaction":
            msg_counts["compaction"] += 1
            text = ev.get("text") or ev.get("summary") or ""
            raw_timeline.append({"ts": ts, "kind": "compaction", "role": "system",
                                 "text": _clip(text, text_limit), "usage": None})
        elif kind == "turn_abort":
            msg_counts["system"] += 1
            raw_timeline.append({"ts": ts, "kind": "system", "role": "system",
                                 "text": _clip("本轮已中止", text_limit), "usage": None})
    total_entries = len(raw_timeline)
    truncated = bool(max_events) and total_entries > max_events
    shown = raw_timeline[:max_events] if truncated else raw_timeline
    # sections: new turn on each user message; also split on >15min gaps
    sections = []
    turn_no = 0
    for idx, entry in enumerate(shown):
        new_section = not sections
        if entry["kind"] == "user" and sections and idx > sections[-1]["start_index"]:
            new_section = True
        if not new_section and entry["ts"] and sections[-1]["last_ts"] and \
                entry["ts"] - sections[-1]["last_ts"] > 15 * 60 * 1000:
            new_section = True
        if new_section:
            has_user = entry["kind"] == "user"
            if has_user:
                turn_no += 1
            kind = "turn" if has_user else "time"
            title = ("第 %d 轮" % turn_no) if has_user else ("第 %d 段" % (len(sections) + 1))
            sections.append({"index": len(sections) + 1, "kind": kind, "title": title,
                             "start_index": idx, "end_index": idx, "ts": entry["ts"],
                             "last_ts": entry["ts"], "tool_calls": 0,
                             "tokens": 0})
        sec = sections[-1]
        sec["end_index"] = idx
        sec["last_ts"] = entry["ts"] or sec["last_ts"]
        entry["section"] = sec["index"]
        if entry.get("tool"):
            sec["tool_calls"] += 1
        if entry.get("usage"):
            sec["tokens"] += entry["usage"]["total_tokens"]
    for sec in sections:
        sec.pop("last_ts", None)
        sec["ts"] = sec["ts"] or 0
    timeline = []
    for idx, entry in enumerate(shown):
        item = {"index": idx, "ts": entry["ts"], "kind": entry["kind"],
                "role": entry["role"], "text": entry.get("text") or "",
                "section": entry["section"]}
        if entry.get("tool"):
            item["tool"] = entry["tool"]
        if entry.get("usage"):
            item["usage"] = entry["usage"]
        timeline.append(item)
    usage_total = {k: int(v) for k, v in usage_acc.items()}
    total_tokens = usage_total["total_tokens"] or (
        usage_total["input_tokens"] + usage_total["output_tokens"])
    available = usage_seen > 0
    usage = {"input_tokens": usage_total["input_tokens"],
             "output_tokens": usage_total["output_tokens"],
             "cache_read_tokens": usage_total["cache_read_tokens"],
             "cache_write_tokens": usage_total["cache_write_tokens"],
             "total_tokens": total_tokens,
             "available": available}
    usage_caliber = "none"
    if available:
        usage_caliber = ("codex_token_usage_record_incremental"
                         if (codex_extra and codex_extra.get("records"))
                         else "source_event_usage")
    elif codex_extra and codex_extra.get("totals"):
        # fallback used only if per-event usage never appeared above
        usage.update(codex_extra["totals"])
        total_tokens = usage["total_tokens"]
        if total_tokens or any(usage[k] for k in ("input_tokens", "output_tokens",
                                                  "cache_read_tokens")):
            available = True
            usage["available"] = True
            usage_caliber = codex_extra.get("caliber") or "codex_token_count_cumulative"
            warnings.append("token 口径：Codex token_count 累计值（无逐响应 token_usage_record）")
    if not available:
        reason = "源未记录 token"
        if source == "claude":
            reason += "（该 Claude Code 会话为 synthetic/未启用计费）"
        warnings.append(reason + "（usage.available=false）")
    elif total_tokens == 0:
        warnings.append("源提供了 Token 字段，但累计值为 0")
    if codex_extra and codex_extra.get("caliber") == "codex_token_usage_record_incremental" \
            and codex_extra.get("crosscheck") == "file_scoped":
        warnings.append("token 口径：逐响应记录求和为本文件范围；token_count 累计值包含更早的 rollout 片段")
    usage["caliber"] = usage_caliber if available else "none"
    if truncated:
        warnings.append("时间线已截断：显示前 %d 条 / 共 %d 条（可用 --max-events 调整，0 表示全量）"
                        % (len(timeline), total_entries))
    stats = {
        "messages": msg_counts,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "tool_errors": tool_errors,
        "tool_usage": [{"name": k, "count": v}
                       for k, v in sorted(tool_usage.items(), key=lambda kv: -kv[1])],
        "usage": usage,
        "duration_ms": max(0, last_ts - first_ts) if (first_ts and last_ts) else 0,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "events_total": total_entries,
        "events_shown": len(timeline),
        "truncated": truncated,
    }
    return {
        "ok": True,
        "command": "session-detail",
        "source": source,
        "session_id": ir.get("source_session_id") or session,
        "meta": meta,
        "stats": stats,
        "sections": sections,
        "timeline": timeline,
        "warnings": warnings,
        "limits": {"max_events": max_events, "text_limit": text_limit},
    }
