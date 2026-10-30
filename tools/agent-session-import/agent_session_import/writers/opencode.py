"""OpenCode writer: batch-4 constructed DB for batch-4 IRs; batch-5.1 JSON projection otherwise."""
from ..readers import native_batch5_1


def write_into(ir, root, sid, target_cwd=None, compress=True):
    extra = ir.get("extra") or {}
    if extra.get("constructed") or extra.get("evidence_level") == "FIXTURE-CONSTRUCTED":
        from . import native_batch4
        return native_batch4.write("opencode", ir, root, sid, target_cwd=target_cwd)
    return native_batch5_1.write("opencode", ir, root, sid, target_cwd=target_cwd)
