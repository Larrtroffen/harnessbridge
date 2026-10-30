"""DSH v4 native writer (IR -> session.v4.jsonl[.zstd])."""
import os

from .. import dsh as _dsh


def write_compat(ir, root, sid, target_cwd=None, compress=True):
    """convert-style artifact: session.v4.jsonl[.zstd] directly in root (no project dir)."""
    cwd = target_cwd or ir.get("cwd")
    header, events = _dsh.build_session(ir, session_id=sid, target_cwd=cwd)
    plain, frames = _dsh.render(header, events, compress=compress)
    plain_path = os.path.join(root, "session.v4.jsonl")
    with open(plain_path, "wb") as f:
        f.write(plain)
    artifact = plain_path
    if frames is not None:
        artifact = os.path.join(root, "session.v4.jsonl.zstd")
        with open(artifact, "wb") as f:
            f.write(frames)
        os.chmod(artifact, 0o600)
    return {
        "artifact": artifact,
        "native_root": root,
        "relpath": os.path.basename(artifact),
        "events": len(events),
        "session_id": header["id"],
        "cwd": header["cwd"],
    }


def write_native(ir, sessions_root, sid, target_cwd=None, compress=True):
    """Write <sessions_root>/<projectKey(cwd)>/<encodeSegment(sid)>/session.v4.jsonl[.zstd]."""
    cwd = target_cwd or ir.get("cwd")
    header, events = _dsh.build_session(ir, session_id=sid, target_cwd=cwd)
    plain, frames = _dsh.render(header, events, compress=compress)
    path = _dsh.generation_path(sessions_root, header["cwd"], header["id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(frames if frames is not None else plain)
    os.chmod(path, 0o600)
    rel = os.path.relpath(path, sessions_root)
    return {"artifact": path, "native_root": sessions_root, "relpath": rel,
            "session_id": header["id"], "cwd": header["cwd"], "events": len(events)}


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return write_native(ir, root, sid, target_cwd=target_cwd, compress=compress)
