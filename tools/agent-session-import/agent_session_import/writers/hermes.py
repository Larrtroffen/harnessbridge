"""hermes batch-4 writer (staging only; evidence FIXTURE-CONSTRUCTED)."""
from . import native_batch4


def write_into(ir, root, sid, target_cwd=None, compress=True):
    return native_batch4.write("hermes", ir, root, sid, target_cwd=target_cwd)
