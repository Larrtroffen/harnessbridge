"""Small stdlib-only helpers shared by readers / writers."""
import datetime as _dt
import json
import os
import shutil
import subprocess
import time

HOME = os.path.expanduser("~")


def find_zstd():
    """Return a usable zstd CLI path, or None."""
    p = shutil.which("zstd")
    if p:
        return p
    for cand in ("/opt/homebrew/bin/zstd", "/usr/local/bin/zstd", "/usr/bin/zstd"):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


ZSTD = find_zstd()


def now_ms():
    return int(time.time() * 1000)


def iso_to_ms(value):
    """ISO-8601 string (or epoch number) -> epoch milliseconds int. None on failure."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Heuristic: values below 1e12 are unix seconds, above are epoch ms.
        v = float(value)
        return int(v * 1000) if v < 1e12 else int(v)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return int(dt.timestamp() * 1000)


def iter_jsonl(path, bad_sink=None):
    """Yield (line_no, obj) for parseable JSON lines; malformed lines go to bad_sink."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except (json.JSONDecodeError, ValueError):
                if bad_sink is not None:
                    bad_sink.append(i)


def read_jsonl(path, bad_sink=None):
    return list(iter_jsonl(path, bad_sink))


def count_lines(path):
    """Count non-empty lines without JSON parsing (cheap-ish)."""
    n = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            n += chunk.count(b"\n")
    return n + (0 if os.path.getsize(path) == 0 else 0)


def zdump(data: bytes, level=19) -> bytes:
    """Compress one independent zstd frame with the CLI."""
    if ZSTD is None:
        raise RuntimeError("zstd CLI not found; install zstd (brew install zstd)")
    p = subprocess.run(
        [ZSTD, "-q", "-c", f"-{level}"],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError("zstd failed: " + p.stderr.decode("utf-8", "replace")[:400])
    return p.stdout


def zcat(data: bytes) -> bytes:
    if ZSTD is None:
        raise RuntimeError("zstd CLI not found; install zstd (brew install zstd)")
    p = subprocess.run(
        [ZSTD, "-q", "-d", "-c"],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError("zstd -d failed: " + p.stderr.decode("utf-8", "replace")[:400])
    return p.stdout


def json_line(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def dumps(obj, indent=None) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=indent)


def iso_now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def first_line(text, limit=80):
    if not isinstance(text, str):
        return ""
    for ln in text.splitlines():
        ln = ln.strip()
        if ln:
            return ln[:limit]
    return ""


def text_placeholder_for_image(src=None):
    """Images are not downloaded (Qoder URLs expire); degrade to a text placeholder."""
    return "[image attachment not imported]"
