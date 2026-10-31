#!/usr/bin/env python3
"""Batch-6 tests: external fixture intake + asi matrix-batch6 (fixture-verified coverage)."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[1]
ARTIFACT = TOOL_DIR / "tests" / "artifacts" / "interop-matrix-batch6.json"
EXTERNAL = WORKSPACE / "samples" / "batch6" / "external"
README = WORKSPACE / "samples" / "batch6" / "README.md"

sys.path.insert(0, str(TOOL_DIR))

from agent_session_import import batch6  # noqa: E402
from agent_session_import.readers import get as get_reader  # noqa: E402


@unittest.skipUnless((WORKSPACE / "samples" / "batch2").is_dir(),
                     "full batch6 matrix needs the internal/private fixture corpus")
class Batch6Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = batch6.run_batch6(report_path=str(ARTIFACT))

    def test_external_fixtures_licensed_and_present(self):
        self.assertTrue(README.is_file())
        readme = README.read_text(encoding="utf-8")
        self.assertIn("CONSTRUCTED", readme)
        self.assertIn("不得冒充真实会话", readme)
        wanted = ["copilot", "qwen", "openclaw", "kimi", "grok", "antigravity", "devin",
                  "codebuddy", "fx", "kiro", "roo", "openhands", "mini-swe-agent"]
        for name in wanted:
            self.assertTrue((EXTERNAL / name).is_dir(), name)
            self.assertTrue((EXTERNAL / name / "SOURCE.md").is_file(), name)
        # FSL/GPL harnesses must not be vendored
        self.assertFalse((EXTERNAL / "crush").exists())
        self.assertFalse((EXTERNAL / "zed").exists())
        # external fixtures can actually be parsed by the corresponding readers
        checks = [
            ("codebuddy", EXTERNAL / "codebuddy" / "item-format.jsonl"),
            ("kiro", EXTERNAL / "kiro" / "sessions"
             / "7787f985-7083-420e-b99d-a74ccce5c00f" / "session.jsonl"),
            ("grok", EXTERNAL / "grok" / "chat_history.jsonl"),
            ("fx", EXTERNAL / "fx" / "schema4" / "session.json"),
            ("mini-swe-agent", EXTERNAL / "mini-swe-agent" / "mini-swe-agent-trajectory.json"),
        ]
        for label, path in checks:
            self.assertTrue(path.is_file(), path)
            ir = get_reader(label).load_session(path=str(path))
            self.assertTrue(ir.get("events"), label)

    def test_matrix_schema_and_summary(self):
        rep = self.report
        self.assertEqual(rep["schema"], "asi-batch6-matrix/v1")
        self.assertEqual(len(rep["canonical"]["labels"]), 40)
        self.assertEqual(len(rep["readers"]), 40)
        self.assertEqual(len(rep["writers"]), len(batch6.NATIVE_TARGETS))
        for key in ("readers_total", "readers_pass", "readers_partial", "readers_fail",
                    "fixture_verified", "fixture_verified_total", "real_sessions",
                    "real_example", "writers_total", "writers_pass", "writers_fail"):
            self.assertIn(key, rep["summary"], key)
        self.assertEqual(rep["summary"]["real_sessions"], 22)
        self.assertEqual(rep["summary"]["fixture_verified_total"], 40)
        self.assertGreater(rep["summary"]["fixture_verified"], 0)
        self.assertEqual(rep["summary"]["fixture_verified"],
                         sum(1 for r in rep["readers"]
                             if r["status"] in ("pass", "partial")
                             and r.get("evidence_level") in batch6.VERIFIED_EVIDENCE))
        self.assertEqual(rep["summary"]["readers_fail"], 0)
        self.assertGreaterEqual(rep["summary"]["fixture_verified"], 30)
        # Continue REAL sample must be recorded as REAL (not CONSTRUCTED/REAL-EXAMPLE)
        cont = [r for r in rep["readers"] if r["harness"] == "continue"]
        self.assertEqual(len(cont), 1)
        self.assertEqual(cont[0].get("evidence_level"), "REAL")
        self.assertTrue(ARTIFACT.is_file())
        on_disk = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema"], rep["schema"])

    def test_reader_checks_no_silent_pass(self):
        for r in self.report["readers"]:
            self.assertIn(r["status"], ("pass", "partial", "fail"))
            if r["status"] == "fail":
                self.assertTrue(r.get("error"), r["harness"])
                self.assertNotIn(r["harness"], (
                    "claude", "codex", "dsh", "omp", "qoder"))
        fails = {f["harness"] for f in self.report["failures"]["readers"]}
        self.assertEqual(fails, {r["harness"] for r in self.report["readers"]
                                 if r["status"] == "fail"})
        constructed = {r["harness"] for r in self.report["readers"]
                       if r.get("evidence_level") == "FIXTURE-CONSTRUCTED"}
        verified = {r["harness"] for r in self.report["readers"]
                    if r["status"] in ("pass", "partial")
                    and r.get("evidence_level") in batch6.VERIFIED_EVIDENCE}
        self.assertFalse(constructed & verified)  # CONSTRUCTED never counts as fixture-verified
        self.assertEqual(len(verified), self.report["summary"]["fixture_verified"])

    def test_writer_checks_recorded(self):
        writers = self.report["writers"]
        self.assertEqual([w["target"] for w in writers], list(batch6.NATIVE_TARGETS))
        for w in writers:
            self.assertIn(w["status"], ("pass", "partial", "fail"))
            if w["status"] == "fail":
                self.assertTrue(w.get("error"), w["target"])
            else:
                self.assertFalse(os.path.isabs(w.get("artifact") or ""),
                                 (w["target"], w.get("artifact")))
        self.assertEqual(len(self.report["failures"]["writers"]),
                         sum(1 for w in writers if w["status"] == "fail"))

    def test_no_real_store_writes_and_temp_cleanup(self):
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "asi-batch6-*")))
        batch6.run_batch6(limit=2, only=["claude", "mini-swe-agent"])
        after = set(glob.glob(os.path.join(tempfile.gettempdir(), "asi-batch6-*")))
        self.assertEqual(before, after)  # staging dirs are always removed
        # writer artifacts were staged under a temp dir and are reported as relative paths
        for w in self.report["writers"]:
            artifact = w.get("artifact")
            self.assertFalse(artifact and os.path.isfile(os.path.join(str(TOOL_DIR), artifact))
                             and "/asi-batch6-" in str(artifact))

    def test_coverage_report_fourth_number(self):
        p = subprocess.run([sys.executable, str(WORKSPACE / "tools" / "coverage-report.py"),
                            "--json"], capture_output=True, text=True,
                           cwd=str(WORKSPACE))
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data.get("fixture_verified"), self.report["summary"]["fixture_verified"])
        chk = subprocess.run([sys.executable, str(WORKSPACE / "tools" / "coverage-report.py"),
                              "--check"], capture_output=True, text=True, cwd=str(WORKSPACE))
        self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)


if __name__ == "__main__":
    unittest.main()
