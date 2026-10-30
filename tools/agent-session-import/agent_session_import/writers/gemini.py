"""Batch-3 gemini writer wrapper (format-level, staging only)."""
from . import native_batch3


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch3.write("gemini", ir, root, sid, target_cwd=target_cwd)
