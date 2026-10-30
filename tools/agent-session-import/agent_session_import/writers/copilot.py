"""Batch-3 copilot writer wrapper (format-level, staging only)."""
from . import native_batch3


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch3.write("copilot", ir, root, sid, target_cwd=target_cwd)
