"""Batch-3 pi writer wrapper (format-level, staging only)."""
from . import native_batch3


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch3.write("pi", ir, root, sid, target_cwd=target_cwd)
