"""Batch-3 qwen writer wrapper (format-level, staging only)."""
from . import native_batch3


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch3.write("qwen", ir, root, sid, target_cwd=target_cwd)
