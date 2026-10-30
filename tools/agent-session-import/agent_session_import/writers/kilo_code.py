"""Batch-5 kilo_code writer (staging only; evidence FIXTURE-CONSTRUCTED)."""
from ..readers import native_batch5


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch5.write("kilo-code", ir, root, sid, target_cwd=target_cwd)
