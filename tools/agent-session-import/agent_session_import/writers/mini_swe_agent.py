"""Batch-5.1 mini-swe-agent writer (staging only)."""
from ..readers import native_batch5_1 as impl


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return impl.write("mini-swe-agent", ir, root, sid, target_cwd=target_cwd)
