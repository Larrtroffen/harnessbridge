#!/usr/bin/env python3
"""Reader tests for the 7 OSS/native labels added in task-59.

Covers WorkBuddy / Windsurf native-format readers, codeg ACP-transcript fallback
readers (TRAE / ZCode), and OSS capture readers (Cherry Studio / Claude Desktop /
OpenCraw alias). Public fixtures live under ``samples/batch6/external``; the
private OSS captures under ``samples/batch2`` are only used when present and are
skipped otherwise (never copied into public fixtures).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[1]
SAMPLES = WORKSPACE / "samples"
ASI = TOOL_DIR / "asi"

sys.path.insert(0, str(TOOL_DIR))

from agent_session_import import SOURCES  # noqa: E402
from agent_session_import.product import HARNESS_BY_ID  # noqa: E402
from agent_session_import.readers import get as get_reader  # noqa: E402
from agent_session_import.readers import opencraw  # noqa: E402

PUBLIC = SAMPLES / "batch6" / "external"
PRIVATE_OSS = SAMPLES / "batch2" / "oss"
PRIVATE_OSS_ADD = SAMPLES / "batch2" / "oss-add"

NEW_SOURCES = ("workbuddy", "windsurf", "trae", "zcode", "cherry-studio",
               "claude-desktop", "opencraw")


def run_cli(*args, env=None):
    return subprocess.run([sys.executable, str(ASI), *args],
                          capture_output=True, text=True, cwd=str(TOOL_DIR), env=env)


class RegistrationTest(unittest.TestCase):
    def test_sources_readers_and_product_entries(self):
        for source in NEW_SOURCES:
            self.assertIn(source, SOURCES)
            self.assertFalse(get_reader(source) is None)
            spec = HARNESS_BY_ID[source]
            self.assertFalse(spec["install_supported"], source)
            self.assertIsNone(spec["install_root"], source)
            self.assertTrue(spec["capabilities"]["export"], source)
            self.assertIn("session_dir_hint", spec)

    def test_opencraw_alias_candidate(self):
        self.assertEqual(opencraw.SOURCE, "opencraw")
        self.assertEqual(opencraw.ALIAS_OF, "openclaw")
        # no new coverage label: it is a reader alias candidate only
        ir = None
        root = PUBLIC / "oss"
        if root.is_dir():
            rows = get_reader("opencraw").list_sessions(root)
            if rows:
                ir = get_reader("opencraw").load_session(root=root, session=rows[0]["id"])
        if ir:
            self.assertEqual(ir["extra"].get("alias_of"), "openclaw")


class _FixtureCase(unittest.TestCase):
    def _list_load_convert(self, source, root, session_id=None, min_events=1):
        root = str(root)
        rows = get_reader(source).list_sessions(root)
        self.assertGreaterEqual(len(rows), 1, "%s fixture missing under %s" % (source, root))
        sid = session_id or rows[0]["id"]
        ir = get_reader(source).load_session(root=root, session=sid)
        self.assertGreaterEqual(len(ir["events"]), min_events)
        self.assertTrue(ir.get("title"))
        with tempfile.TemporaryDirectory() as out:
            p = run_cli("convert", "--from", source, "--root", root,
                        "--session", str(sid), "--to", "atif", "--out", out, "--json")
            self.assertEqual(p.returncode, 0, p.stderr or p.stdout)
            rep = json.loads(p.stdout)
            self.assertTrue(rep.get("ok"), rep)
            artifacts = list(Path(out).rglob("*.atif.json"))
            self.assertTrue(artifacts, "no ATIF artifact produced: %s" % rep)
        return rows, ir


class WorkBuddyTest(_FixtureCase):
    ROOT = PUBLIC / "workbuddy"

    def test_native_list_load_convert(self):
        rows, ir = self._list_load_convert("workbuddy", self.ROOT, "s1", min_events=3)
        self.assertEqual(rows[0]["model"], "glm-5.2")
        kinds = [e["kind"] for e in ir["events"]]
        self.assertIn("user_message", kinds)
        self.assertIn("assistant_message", kinds)
        self.assertIn("tool_result", kinds)


class WindsurfTest(_FixtureCase):
    ROOT = PUBLIC / "windsurf"

    def test_native_list_load_convert(self):
        rows, ir = self._list_load_convert("windsurf", self.ROOT, "s1", min_events=2)
        self.assertEqual(rows[0]["title"], "Add a health endpoint")
        self.assertIn("user_message", [e["kind"] for e in ir["events"]])


class TraeZcodeAcpTest(_FixtureCase):
    ROOT = PUBLIC / "codeg-acp"

    def test_trae_acp_list_load_convert(self):
        rows, ir = self._list_load_convert("trae", self.ROOT, "trae-test-1", min_events=3)
        self.assertTrue(rows[0]["cwd"])
        kinds = [e["kind"] for e in ir["events"]]
        self.assertIn("tool_result", kinds)

    def test_zcode_acp_list_load_convert(self):
        _, ir = self._list_load_convert("zcode", self.ROOT, "zcode-test-1", min_events=2)
        self.assertIn("reasoning", json.dumps(ir["events"], ensure_ascii=False))

    def test_agents_do_not_cross_read(self):
        trae_rows = get_reader("trae").list_sessions(self.ROOT)
        zcode_rows = get_reader("zcode").list_sessions(self.ROOT)
        self.assertEqual({r["id"] for r in trae_rows}, {"trae-test-1"})
        self.assertEqual({r["id"] for r in zcode_rows}, {"zcode-test-1"})


class OssCaptureReaderTest(_FixtureCase):
    ROOT = PUBLIC / "oss"

    def test_cherry_studio_capture(self):
        _, ir = self._list_load_convert("cherry-studio", self.ROOT, "cherry-test-1")
        self.assertEqual(ir["source"], "cherry-studio")

    def test_claude_desktop_capture(self):
        _, ir = self._list_load_convert("claude-desktop", self.ROOT, "claude-desktop-test-1")
        self.assertEqual(ir["source"], "claude-desktop")
        self.assertTrue(ir["extra"].get("reader_only"))

    def test_opencraw_capture_alias_metadata(self):
        _, ir = self._list_load_convert("opencraw", self.ROOT, "opencraw-test-1")
        self.assertEqual(ir["extra"].get("alias_of"), "openclaw")


@unittest.skipUnless(PRIVATE_OSS.is_dir(), "private OSS captures not present (samples/batch2/oss)")
class PrivateOssCaptureTest(unittest.TestCase):
    def test_cherry_and_opencraw_private_captures(self):
        for source in ("cherry-studio", "opencraw"):
            rows = get_reader(source).list_sessions(str(PRIVATE_OSS))
            self.assertGreaterEqual(len(rows), 1, source)
            ir = get_reader(source).load_session(root=str(PRIVATE_OSS), session=rows[0]["id"])
            self.assertGreaterEqual(len(ir["events"]), 1)


@unittest.skipUnless(PRIVATE_OSS_ADD.is_dir(), "private oss-add captures not present")
class PrivateClaudeDesktopCaptureTest(unittest.TestCase):
    def test_claude_desktop_private_capture(self):
        rows = get_reader("claude-desktop").list_sessions(str(PRIVATE_OSS_ADD))
        self.assertGreaterEqual(len(rows), 1)
        ir = get_reader("claude-desktop").load_session(root=str(PRIVATE_OSS_ADD),
                                                       session=rows[0]["id"])
        self.assertGreaterEqual(len(ir["events"]), 1)


class DetectRegistrationTest(unittest.TestCase):
    def test_detect_reports_new_sources_export_only(self):
        p = run_cli("detect", "--json", "--fast")
        self.assertEqual(p.returncode, 0, p.stderr)
        rep = json.loads(p.stdout)
        by_id = {h["id"]: h for h in rep["harnesses"]}
        for source in NEW_SOURCES:
            self.assertIn(source, by_id)
            self.assertFalse(by_id[source]["install_supported"], source)
            self.assertIn("store_path", by_id[source])


if __name__ == "__main__":
    unittest.main()
