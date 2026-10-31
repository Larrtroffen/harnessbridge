#!/usr/bin/env python3
"""Task-62 tests: iFlow + Zed native readers, TRAE CLI (TraeX) native-first reader.

Run:  python3 -m unittest tools/agent-session-import/tests/test_new_harnesses.py -v

Fixtures live in ``samples/batch6/{iflow,zed,trae-cli}/`` (see each SOURCE.md for
provenance/licence).  Nothing here writes a real user store.  Real-store-only
assertions are skipped when the fixture/app DB is absent.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[1]
BATCH6 = WORKSPACE / "samples" / "batch6"

sys.path.insert(0, str(TOOL_DIR))

from agent_session_import import dsh  # noqa: E402
from agent_session_import import atif  # noqa: E402
from agent_session_import.common import ZSTD  # noqa: E402
from agent_session_import.readers import get as get_reader  # noqa: E402
from agent_session_import.readers import iflow, trae, zed  # noqa: E402


class _Base(unittest.TestCase):
    def assert_ir_sane(self, ir, source):
        self.assertEqual(ir["source"], source)
        self.assertTrue(ir["events"], "no events parsed")
        self.assertTrue(ir["title"])
        stats = ir["stats"]
        self.assertEqual(stats["events"], len(ir["events"]))
        for ev in ir["events"]:
            self.assertIn(ev["kind"], ("user_message", "assistant_message", "tool_result",
                                       "system_message", "compaction"))

    def assert_dsh_builds(self, ir):
        header, events = dsh.build_session(ir, target_cwd=str(WORKSPACE))
        self.assertEqual(header["type"], "session")
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))
        errors, _warnings, _info = dsh._check_events(events)
        self.assertEqual(errors, [], errors)
        self.assertGreaterEqual(len(events), 4)

    def assert_atif_valid(self, ir):
        doc = atif.to_atif(ir)
        errors, _warnings = atif.validate(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(doc["agent"]["name"], ir["source"])
        self.assertTrue(doc["steps"])


# --------------------------------------------------------------------------- iFlow
class IFlowReaderTest(_Base):
    ROOT = BATCH6 / "iflow" / "projects"

    def test_registered(self):
        self.assertIs(get_reader("iflow"), iflow)
        from agent_session_import import SOURCES
        self.assertIn("iflow", SOURCES)

    def test_list_sessions(self):
        if not self.ROOT.is_dir():
            self.skipTest("iflow fixture missing")
        rows = iflow.list_sessions(root=str(self.ROOT))
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["source"], "iflow")
        self.assertTrue(row["id"].startswith("session-"))
        self.assertEqual(row["cwd"], r"C:\exp\docker-image-retagger")
        self.assertEqual(row["model"], "glm-4.7")
        self.assertGreater(row["lines"], 10)

    def test_load_session(self):
        if not self.ROOT.is_dir():
            self.skipTest("iflow fixture missing")
        rows = iflow.list_sessions(root=str(self.ROOT))
        ir = iflow.load_session(root=str(self.ROOT), session=rows[0]["id"])
        self.assert_ir_sane(ir, "iflow")
        stats = ir["stats"]
        self.assertEqual(stats["user_messages"], 1)
        self.assertGreaterEqual(stats["assistant_messages"], 1)
        # iFlow repeats incremental tool_use rows; the reader dedupes by call id.
        self.assertEqual(stats["tool_calls"], 6)
        self.assertEqual(stats["unpaired_tool_calls"], 0)
        self.assertTrue(any("duplicated incremental tool_use" in w for w in ir["warnings"]))
        texts = " ".join(
            b.get("text", "")
            for ev in ir["events"] if ev["kind"] in ("user_message", "assistant_message")
            for b in ev.get("blocks", []) if b.get("type") == "text")
        self.assertIn("DOCKER_API_VERSION", texts)

    def test_convert_chain(self):
        if not self.ROOT.is_dir():
            self.skipTest("iflow fixture missing")
        rows = iflow.list_sessions(root=str(self.ROOT))
        ir = iflow.load_session(root=str(self.ROOT), session=rows[0]["id"])
        self.assert_atif_valid(ir)
        self.assert_dsh_builds(ir)

    def test_acp_json_fallback(self):
        """ACP JSON best-effort fallback (schema unpublished; reader warns)."""
        with tempfile.TemporaryDirectory() as tmp:
            acp = os.path.join(tmp, "acp", "sessions")
            os.makedirs(acp)
            with open(os.path.join(acp, "s1.json"), "w", encoding="utf-8") as f:
                json.dump({"sessionId": "s1", "cwd": "/tmp/x", "title": "acp demo",
                           "messages": [{"role": "user", "content": "hello"},
                                        {"role": "assistant", "content": "world"}]}, f)
            os.makedirs(os.path.join(tmp, "projects"))
            old = os.environ.get("IFLOW_HOME")
            os.environ["IFLOW_HOME"] = tmp
            try:
                rows = iflow.list_sessions(root=os.path.join(tmp, "projects"))
                self.assertEqual([r["id"] for r in rows], ["s1"])
                ir = iflow.load_session(root=os.path.join(tmp, "projects"), session="s1")
                self.assert_ir_sane(ir, "iflow")
                self.assertTrue(any("ACP JSON schema is not published" in w
                                    for w in ir["warnings"]))
            finally:
                if old is None:
                    os.environ.pop("IFLOW_HOME", None)
                else:
                    os.environ["IFLOW_HOME"] = old


# --------------------------------------------------------------------------- Zed
class ZedReaderTest(_Base):
    ROOT = BATCH6 / "zed" / "threads"
    DB = ROOT / "threads.db"

    def setUp(self):
        if not self.DB.is_file():
            self.skipTest("zed fixture missing")

    def test_registered(self):
        self.assertIs(get_reader("zed"), zed)
        from agent_session_import import SOURCES
        self.assertIn("zed", SOURCES)

    def test_list_sessions(self):
        rows = zed.list_sessions(root=str(self.ROOT))
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"thread-fixture-json", "thread-fixture-zstd"})
        for row in rows:
            self.assertEqual(row["source"], "zed")
            self.assertEqual(row["cwd"], "/Users/fixture/demo-project")
            self.assertGreater(row["lines"], 0)
            self.assertTrue(row["path"].startswith(str(self.DB) + "#"))

    def test_load_json_thread(self):
        ir = zed.load_session(path="%s#thread-fixture-json" % self.DB)
        self.assert_ir_sane(ir, "zed")
        stats = ir["stats"]
        self.assertEqual(stats["user_messages"], 2)
        self.assertEqual(stats["assistant_messages"], 1)
        self.assertEqual(stats["reasoning_blocks"], 1)
        self.assertEqual(stats["tool_calls"], 1)
        self.assertEqual(stats["tool_results"], 1)
        results = [ev for ev in ir["events"] if ev["kind"] == "tool_result"]
        self.assertEqual(results[0]["call_id"], "call_zed_1")
        self.assertEqual(results[0]["name"], "list_directory")
        self.assertIn("README.md", results[0]["content"])
        self.assertEqual(ir["cwd"], "/Users/fixture/demo-project")
        self.assertEqual(ir["model"], "claude-fixture")
        self.assertEqual(ir["updated_at_ms"], 1793404810000)  # 2026-10-31T00:00:10Z

    def test_load_zstd_thread(self):
        if ZSTD is None:
            self.skipTest("zstd CLI not installed")
        ir = zed.load_session(path="%s#thread-fixture-zstd" % self.DB)
        self.assert_ir_sane(ir, "zed")
        self.assertEqual(ir["stats"]["user_messages"], 1)
        self.assertEqual(ir["stats"]["assistant_messages"], 1)
        self.assertIn("zstd-compressed", " ".join(
            b.get("text", "") for ev in ir["events"] if ev["kind"] == "assistant_message"
            for b in ev.get("blocks", []) if b.get("type") == "text"))
        self.assertTrue(any("zstd-compressed" in w for w in ir["warnings"]))

    def test_resolve_and_convert(self):
        path = zed.resolve_path(str(self.ROOT), "zed:thread-fixture-json")
        self.assertEqual(path, "%s#thread-fixture-json" % self.DB)
        ir = zed.load_session(path=path)
        self.assert_atif_valid(ir)
        self.assert_dsh_builds(ir)


# --------------------------------------------------------------------------- TRAE CLI
class TraeCliReaderTest(_Base):
    ROOT = BATCH6 / "trae-cli"

    def setUp(self):
        if not self.ROOT.is_dir():
            self.skipTest("trae-cli fixture missing")

    def test_native_list(self):
        rows = trae.list_sessions(root=str(self.ROOT))
        self.assertGreaterEqual(len(rows), 2)
        layouts = {r.get("layout") for r in rows}
        self.assertEqual(layouts, {"traex-codex-rollout"})
        self.assertTrue(any(r.get("archived") for r in rows))
        for row in rows:
            self.assertEqual(row["source"], "trae")

    def test_native_load_rollout(self):
        rows = trae.list_sessions(root=str(self.ROOT))
        target = next(r for r in rows if r.get("archived"))
        ir = trae.load_session(root=str(self.ROOT), session=target["id"])
        self.assertEqual(ir["source"], "trae")
        self.assertEqual(ir["provider"], "trae")
        self.assertGreaterEqual(len(ir["events"]), 6)
        self.assertEqual(ir["stats"]["user_messages"], 1)
        self.assertGreaterEqual(ir["stats"]["tool_calls"], 1)
        self.assertTrue(any("codex-rs fork" in w for w in ir["warnings"]))
        self.assert_atif_valid(ir)

    def test_load_by_path(self):
        rows = trae.list_sessions(root=str(self.ROOT))
        target = next(r for r in rows if r.get("archived"))
        ir = trae.load_session(path=target["path"])
        self.assertEqual(ir["source"], "trae")
        self.assertGreaterEqual(len(ir["events"]), 6)

    def test_acp_fallback_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = os.path.join(tmp, "acp-transcripts", "codeg-trae-cli")
            os.makedirs(agent)
            header = {"v": 1, "kind": "header", "agent": "codeg-trae-cli",
                      "session_id": "s1", "cwd": "/repo", "started_at_ms": 1735689600000}
            lines = [
                header,
                {"t": 1735689600100, "k": "prompt", "p": [{"type": "text", "text": "hi"}]},
                {"t": 1735689600200, "k": "update",
                 "p": {"sessionUpdate": "agent_message_chunk", "content": [{"type": "text", "text": "hello"}]}},
                {"t": 1735689600300, "k": "turn_end", "p": {"stopReason": "end_turn"}},
            ]
            path = os.path.join(agent, "s1.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(json.dumps(line) + "\n")
            old = os.environ.get("CODEG_ACP_ROOT")
            os.environ["CODEG_ACP_ROOT"] = os.path.join(tmp, "acp-transcripts")
            empty = os.path.join(tmp, "no-native")
            os.makedirs(empty)
            try:
                rows = trae.list_sessions(root=empty)
                self.assertEqual([r["id"] for r in rows], ["s1"])
                self.assertEqual(rows[0]["layout"], "codeg-acp-transcript")
                ir = trae.load_session(root=empty, session="s1")
                self.assertEqual(ir["source"], "trae")
                self.assertTrue(ir["events"])
            finally:
                if old is None:
                    os.environ.pop("CODEG_ACP_ROOT", None)
                else:
                    os.environ["CODEG_ACP_ROOT"] = old


# --------------------------------------------------------------------------- detect
class DetectTest(unittest.TestCase):
    def test_detect_includes_iflow_and_zed(self):
        from agent_session_import import product
        old_iflow, old_zed = os.environ.get("IFLOW_HOME"), os.environ.get("ZED_HOME")
        os.environ["IFLOW_HOME"] = str(BATCH6 / "iflow")
        os.environ["ZED_HOME"] = str(BATCH6 / "zed")
        try:
            report = product.detect(fast=False)
        finally:
            for key, old in (("IFLOW_HOME", old_iflow), ("ZED_HOME", old_zed)):
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
        by_id = {h["id"]: h for h in report["harnesses"]}
        for source in ("iflow", "zed"):
            self.assertIn(source, by_id, list(by_id))
            self.assertTrue(by_id[source]["detected"], by_id[source])
            self.assertGreater(by_id[source]["session_count"], 0)
            self.assertFalse(by_id[source]["install_supported"])
            self.assertTrue(by_id[source]["capabilities"]["export"])


if __name__ == "__main__":
    unittest.main()
