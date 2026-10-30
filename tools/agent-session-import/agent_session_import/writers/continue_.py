"""Batch-5 continue writer (staging only; evidence FIXTURE-CONSTRUCTED)."""
from ..readers import native_batch5


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch5.write("continue", ir, root, sid, target_cwd=target_cwd)
