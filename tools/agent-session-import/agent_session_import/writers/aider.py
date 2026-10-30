"""Batch-3 aider writer wrapper (format-level, staging only)."""
from . import native_batch3


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch3.write("aider", ir, root, sid, target_cwd=target_cwd)
