#!/usr/bin/env python3
"""External-fixture adapter tests (``research/external/fixtures/<harness>/``).

Every test loads the harness' external fixture through the public reader, then
(for priority sources) exercises the ``asi`` CLI list / convert / session-detail
paths. Writer roundtrip tests run only for sources that ship a native writer.

Run:  python3 -m unittest discover -s tools/agent-session-import/tests -v
Fixtures are optional: a missing fixture directory skips the corresponding test
(no network, no real harness store, never writes outside a temp dir).
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
FIXTURES = WORKSPACE / "research" / "external" / "fixtures"
ASI = TOOL_DIR / "asi"

sys.path.insert(0, str(TOOL_DIR))

from agent_session_import import writers  # noqa: E402
from agent_session_import.readers import get as get_reader  # noqa: E402

# Lead priority order (task-60): first 10 are expected to be exercised end-to-end.
PRIORITY = ["qwen", "copilot", "roo", "kiro", "antigravity", "grok", "fx",
            "openhands", "mini-swe-agent", "codebuddy"]
SECONDARY = ["kimi", "openclaw", "devin", "continue", "goose", "junie",
             "codebuff", "vibe", "opencode", "hermes", "cline", "kilo-code"]
ALL = PRIORITY + SECONDARY
# Sources whose fixture has no loadable sample yet (license/blocked) -> skip loudly.
SKIP_NO_SAMPLE = {"crush": "FSL-1.1: no fixture file may be vendored (schema-only)"}
# Writers that exist and roundtrip through our reader (antigravity is reader-only).
ROUNDTRIP = ["qwen", "copilot", "roo", "kiro", "fx", "codebuddy", "mini-swe-agent",
             "openhands", "cline", "continue", "junie", "codebuff", "vibe", "grok",
             "kimi", "openclaw", "opencode", "devin", "hermes"]


def fixture_root(harness):
    root = FIXTURES / harness
    return root if root.is_dir() else None


def run_cli(*args, timeout=120):
    return subprocess.run(
        [sys.executable, str(ASI), *args],
        capture_output=True, text=True, cwd=str(TOOL_DIR), timeout=timeout)


def list_sessions(harness, root):
    return get_reader(harness).list_sessions(root=str(root))


def load_first(harness, root):
    rows = list_sessions(harness, root)
    if not rows:
        return None, []
    return get_reader(harness).load_session(root=str(root), path=rows[0]["path"]), rows


def _skip_reason(harness):
    if harness in SKIP_NO_SAMPLE:
        return SKIP_NO_SAMPLE[harness]
    if fixture_root(harness) is None:
        return "fixture directory missing: %s" % (FIXTURES / harness)
    return None


class ExternalFixtureLoadTests(unittest.TestCase):
    """One case per harness: reader loads the external fixture into a sane IR."""

    def _check(self, harness, min_events=1):
        reason = _skip_reason(harness)
        if reason:
            self.skipTest(reason)
        root = fixture_root(harness)
        rows = list_sessions(harness, root)
        self.assertTrue(rows, "%s: external fixture produced no sessions" % harness)
        for row in rows:
            self.assertTrue(row.get("path"))
            self.assertTrue(os.path.isfile(row["path"]), row.get("path"))
        ir, _ = load_first(harness, root)
        self.assertIsNotNone(ir)
        self.assertEqual(ir.get("source"), harness)
        self.assertGreaterEqual(len(ir.get("events") or []), min_events,
                                "%s: expected >=%d events" % (harness, min_events))
        self.assertIsInstance(ir.get("warnings"), list)
        self.assertTrue(ir.get("created_at_ms") is not None)
        kinds = {ev.get("kind") for ev in ir["events"]}
        self.assertTrue(kinds, "%s: no event kinds" % harness)
        # unpaired tool calls are allowed only when the IR declares lossy coverage
        unpaired = 0
        call_ids = set()
        for ev in ir["events"]:
            for block in ev.get("blocks") or []:
                if isinstance(block, dict) and block.get("type") == "tool-call":
                    call_ids.add(block.get("id") or "")
        for ev in ir["events"]:
            if ev.get("kind") == "tool_result":
                call_ids.discard(ev.get("call_id"))
        unpaired = len(call_ids)
        if unpaired:
            self.assertTrue(ir.get("lossy") or ir.get("warnings"),
                            "%s: %d unpaired tool calls without lossy note" % (harness, unpaired))
        return ir

    def test_antigravity_native_sqlite(self):
        """Antigravity reader includes the codeg SQLite + protobuf fixture."""
        root = fixture_root("antigravity")
        if root is None:
            self.skipTest("fixture missing")
        rows = list_sessions("antigravity", root)
        db_rows = [r for r in rows if r["path"].endswith((".db", ".sqlite"))]
        self.assertTrue(db_rows, "antigravity: native .db fixture was not discovered")
        ir = get_reader("antigravity").load_session(path=db_rows[0]["path"])
        self.assertGreaterEqual(len(ir["events"]), 3)
        kinds = [ev["kind"] for ev in ir["events"]]
        self.assertIn("user_message", kinds)
        self.assertIn("assistant_message", kinds)


for _h in ALL:
    def _make(harness):
        def test(self):
            self._check(harness)
        test.__doc__ = "external fixture: %s" % harness
        return test
    setattr(ExternalFixtureLoadTests, "test_load_%s" % _h.replace("-", "_"), _make(_h))


class ExternalCliTests(unittest.TestCase):
    """``asi list`` / ``convert --to ir`` / ``session-detail`` on external fixtures."""

    def _paths(self, harness):
        root = fixture_root(harness)
        rows = list_sessions(harness, root)
        self.assertTrue(rows)
        return root, rows[0]["path"]

    def _check_priority(self, harness):
        reason = _skip_reason(harness)
        if reason:
            self.skipTest(reason)
        root, path = self._paths(harness)
        p = run_cli("list", harness, "--root", str(root), "--json")
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        doc = json.loads(p.stdout)
        self.assertTrue(doc.get("ok"), doc)
        self.assertGreaterEqual(doc.get("count"), 1)
        detail = run_cli("session-detail", "--from", harness, "--session", str(path), "--json")
        self.assertEqual(detail.returncode, 0, detail.stderr[-800:])
        ddoc = json.loads(detail.stdout)
        self.assertTrue(ddoc.get("ok"), ddoc)
        with tempfile.TemporaryDirectory(prefix="asi-ext-conv-") as out:
            conv = run_cli("convert", "--from", harness, "--session", str(path),
                           "--to", "ir", "--out", out, "--json")
            self.assertEqual(conv.returncode, 0, conv.stderr[-800:])
            cdoc = json.loads(conv.stdout)
            self.assertTrue(cdoc.get("ok"), cdoc)
            self.assertEqual(cdoc["summary"]["converted"], 1)
            stats = cdoc["results"][0]["stats"]
            self.assertGreaterEqual(stats["events"], 1,
                                    "%s: convert produced no IR events" % harness)

    def test_cli_priority_harnesses(self):
        for harness in PRIORITY:
            with self.subTest(harness=harness):
                self._check_priority(harness)


class WriterRoundtripTests(unittest.TestCase):
    """IR -> native writer -> our reader must retain at least one event."""

    def test_roundtrip_table(self):
        for harness in ROUNDTRIP:
            with self.subTest(harness=harness):
                reason = _skip_reason(harness)
                if reason:
                    self.skipTest(reason)
                root = fixture_root(harness)
                ir, rows = load_first(harness, root)
                if ir is None:
                    self.skipTest("%s: no session" % harness)
                writer = writers.get(harness)
                out = tempfile.mkdtemp(prefix="asi-rt-%s-" % harness)
                res = writer.write_into(ir, out, ir.get("source_session_id") or "fixture")
                artifact = res.get("artifact") if isinstance(res, dict) else res
                if isinstance(artifact, (list, tuple)):
                    artifact = artifact[0]
                self.assertTrue(os.path.exists(str(artifact)), "%s: no artifact" % harness)
                back = get_reader(harness).load_session(path=str(artifact))
                self.assertGreaterEqual(len(back.get("events") or []), 1,
                                        "%s: writer roundtrip produced no events" % harness)

    def test_antigravity_writer_is_unsupported(self):
        """antigravity is reader-only: writer must be explicitly unsupported."""
        with self.assertRaises(ValueError):
            writers.get("antigravity")


if __name__ == "__main__":
    unittest.main(verbosity=2)
