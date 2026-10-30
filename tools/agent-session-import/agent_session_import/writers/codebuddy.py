"""Batch-5.1 codebuddy writer (staging only)."""
from ..readers import native_batch5_1 as impl


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return impl.write("codebuddy", ir, root, sid, target_cwd=target_cwd)
