#!/usr/bin/env python3
"""Latest-version real store fixtures (batch 7, LOCAL-DEEPSEEK).

These are stores written by the latest harness versions installed in an isolated
HOME on a remote Linux host, with the real DeepSeek API. They validate that our
readers track current on-disk formats; they are NOT real user sessions and must
not be reported as REAL coverage.
"""
import sys
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[1]
BATCH7 = WORKSPACE / "samples" / "batch7"
sys.path.insert(0, str(TOOL_DIR))

from agent_session_import.readers import get  # noqa: E402


class LatestStoreTest(unittest.TestCase):
    def test_qwen_0265_store(self):
        root = BATCH7 / "qwen-latest"
        if not root.is_dir():
            self.skipTest("batch7 qwen fixture missing")
        rows = get("qwen").list_sessions(str(root))
        self.assertGreaterEqual(len(rows), 1)
        ir = get("qwen").load_session(root=str(root), session=rows[0]["id"])
        self.assertGreaterEqual(len(ir["events"]), 1)
        self.assertTrue(any(e["kind"] == "user_message" for e in ir["events"]))

    def test_goose_1570_store(self):
        root = BATCH7 / "goose-latest"
        if not root.is_dir():
            self.skipTest("batch7 goose fixture missing")
        rows = get("goose").list_sessions(str(root))
        self.assertGreaterEqual(len(rows), 1)
        ir = get("goose").load_session(root=str(root), session=rows[0]["id"])
        self.assertGreaterEqual(len(ir["events"]), 1)
        self.assertTrue(any(e["kind"] == "assistant_message" for e in ir["events"]))

    def test_opencode_1195_sqlite_store(self):
        root = BATCH7 / "opencode-latest"
        if not root.is_dir():
            self.skipTest("batch7 opencode fixture missing")
        rows = get("opencode").list_sessions(str(root))
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["layout"], "opencode-sqlite-store")
        ir = get("opencode").load_session(root=str(root), session=rows[0]["id"])
        self.assertTrue(any(e["kind"] == "user_message" for e in ir["events"]))
        # v1.19 writes step-start/step-finish messages too; they must not become
        # thousands of empty IR assistant messages.
        self.assertLess(len(ir["events"]), 50)

    def test_iflow_0519_store(self):
        root = BATCH7 / "iflow-latest"
        if not root.is_dir():
            self.skipTest("batch7 iflow fixture missing")
        rows = get("iflow").list_sessions(str(root))
        self.assertGreaterEqual(len(rows), 1)
        ir = get("iflow").load_session(root=str(root), session=rows[0]["id"])
        self.assertGreaterEqual(len(ir["events"]), 2)
        self.assertTrue(any(e["kind"] == "assistant_message" for e in ir["events"]))


if __name__ == "__main__":
    unittest.main()
