#!/usr/bin/env python3
"""DSH workspace registration/repair tests (no real ~/.dsh writes)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

from agent_session_import import dsh  # noqa: E402


class DSHWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hb-dsh-ws-")
        self.home = self.tmp.name
        self.cwd = os.path.join(self.home, "project")
        os.makedirs(self.cwd)
        self.ws_id = "11111111-1111-1111-1111-111111111111"
        os.makedirs(os.path.join(self.home, "storages"))
        doc = {
            "unit": {"name": "workspace", "version": 2},
            "global": {"initialized": True,
                       "defaultWorkspaceId": self.ws_id,
                       "workspaceIds": [self.ws_id],
                       "archivedSessionIds": []},
            "tables": {"workspaces": {
                self.ws_id: {"path": os.path.realpath(self.cwd), "title": "project",
                             "sessionIds": [], "createdAt": "2026-01-01T00:00:00Z",
                             "updatedAt": "2026-01-01T00:00:00Z"}}},
        }
        with open(os.path.join(self.home, "storages", "workspace.json"), "w") as f:
            json.dump(doc, f)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_session(self):
        ir = {"source": "test", "source_session_id": "session-abc", "cwd": self.cwd,
              "title": "test title", "created_at_ms": 1735689600000,
              "events": [
                  {"kind": "user_message", "ts": 1735689600000,
                   "blocks": [{"type": "text", "text": "hello"}]},
                  {"kind": "assistant_message", "ts": 1735689600100,
                   "blocks": [{"type": "text", "text": "hi"}]},
              ]}
        plan = dsh.plan_import(ir, self.home)
        self.assertEqual(dsh.write_import(plan), "written")
        return plan

    def test_register_is_idempotent(self):
        plan = self._write_session()
        status, _ = dsh.register_in_workspace(self.home, self.cwd, plan["session_id"])
        self.assertEqual(status, "registered")
        status, _ = dsh.register_in_workspace(self.home, self.cwd, plan["session_id"])
        self.assertEqual(status, "already")
        doc = json.load(open(os.path.join(self.home, "storages", "workspace.json")))
        self.assertIn(plan["session_id"],
                      doc["tables"]["workspaces"][self.ws_id]["sessionIds"])

    def test_repair_registers_orphans(self):
        plan = self._write_session()
        report = dsh.repair_workspaces(self.home)
        self.assertTrue(report["ok"])
        self.assertEqual(report["registered"], 1)
        doc = json.load(open(os.path.join(self.home, "storages", "workspace.json")))
        self.assertIn(plan["session_id"],
                      doc["tables"]["workspaces"][self.ws_id]["sessionIds"])
        report2 = dsh.repair_workspaces(self.home)
        self.assertEqual(report2["registered"], 0)

    def test_register_can_create_workspace(self):
        other = os.path.join(self.home, "other")
        os.makedirs(other)
        status, detail = dsh.register_in_workspace(self.home, other, "session-new", create=True)
        self.assertEqual(status, "registered")
        self.assertIn("created workspace", detail)
        doc = json.load(open(os.path.join(self.home, "storages", "workspace.json")))
        self.assertTrue(any("session-new" in (w.get("sessionIds") or [])
                            for w in doc["tables"]["workspaces"].values()))


if __name__ == "__main__":
    unittest.main()
