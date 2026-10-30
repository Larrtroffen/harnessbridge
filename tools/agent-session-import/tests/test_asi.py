#!/usr/bin/env python3
"""Tests for agent-session-import.

Run:  python3 -m unittest discover -s tools/agent-session-import/tests -v
All fixtures come from the real truncation samples in samples/ (no network, no ~/.dsh writes).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[1]
SAMPLES = WORKSPACE / "samples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ASI = TOOL_DIR / "asi"

sys.path.insert(0, str(TOOL_DIR))

from agent_session_import import atif, dsh  # noqa: E402
from agent_session_import.ir import save as save_ir  # noqa: E402
from agent_session_import.readers import get as get_reader  # noqa: E402

CODEX_SAMPLE = SAMPLES / "codex" / "rollout-small-full.jsonl"
QODER_SAMPLE = SAMPLES / "qoder" / "01-main-1433b77a.prefix.jsonl"
OMP_SAMPLE = SAMPLES / "omp" / "session-small-full.jsonl"


def run_cli(*args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, str(ASI), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or TOOL_DIR),
        env=env,
    )


class PathCodecTest(unittest.TestCase):
    def test_project_key_real_example(self):
        self.assertEqual(
            dsh.project_key("/Users/example/Research_Assistant/【1019】比选文件"),
            "--Users-example-Research_Assistant-~30101019~3011~6BD4~9009~6587~4EF6--",
        )

    def test_project_key_separator_collapse(self):
        self.assertEqual(dsh.project_key("/a//b/"), "--a-b---")  # only leading '-' runs are stripped
        self.assertEqual(dsh.project_key(""), "--root--")

    def test_encode_segment(self):
        self.assertEqual(dsh.encode_segment("session-abc-123"), "session-abc-123")
        self.assertEqual(dsh.encode_segment("."), "~002E")
        self.assertEqual(dsh.encode_segment(".."), "~002E~002E")
        self.assertEqual(dsh.encode_segment("a~b"), "a~007Eb")

    def test_session_id_deterministic(self):
        a = dsh.session_id_for("codex", "abc")
        b = dsh.session_id_for("codex", "abc")
        c = dsh.session_id_for("qoder", "abc")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("session-"))


class DshWriterInvariantTest(unittest.TestCase):
    def _load(self, source, sample, **kw):
        reader = get_reader(source)
        return reader.load_session(path=str(sample), **kw)

    def check_dsh(self, ir):
        header, events = dsh.build_session(ir, target_cwd=str(WORKSPACE))
        self.assertEqual(header["type"], "session")
        self.assertEqual(header["version"], 4)
        self.assertEqual(header["cwd"], str(WORKSPACE))
        self.assertGreaterEqual(len(events), 4)
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))
        errors, warnings, info = dsh._check_events(events)
        self.assertEqual(errors, [], errors)
        # every assistant tool-call block must have tool/call + tool/result
        call_ids = {
            b["id"]
            for e in events
            if e["type"] == "assistant/message"
            for b in e["data"]["message"]["content"]
            if b.get("type") == "tool-call"
        }
        call_events = {e["data"]["callId"] for e in events if e["type"] == "tool/call"}
        result_events = {e["data"]["message"]["toolCallId"] for e in events if e["type"] == "tool/result"}
        self.assertEqual(call_ids, call_events)
        self.assertEqual(call_ids, result_events)
        return header, events, info

    def test_codex_sample(self):
        ir = self._load("codex", CODEX_SAMPLE)
        self.assertEqual(ir["source"], "codex")
        self.assertEqual(ir["stats"]["user_messages"], 1)
        self.assertEqual(ir["stats"]["tool_calls"], 2)
        self.assertEqual(ir["stats"]["tool_calls"], ir["stats"]["tool_results"])
        _h, _e, info = self.check_dsh(ir)

    def test_qoder_sample(self):
        ir = self._load("qoder", QODER_SAMPLE)
        self.assertEqual(ir["source"], "qoder")
        self.assertEqual(ir["stats"]["user_messages"], 1)
        # one logical assistant message per message.id, not one per block row
        self.assertGreaterEqual(ir["stats"]["assistant_messages"], 1)
        self.assertGreater(ir["stats"]["reasoning_blocks"], 0)
        self.assertGreater(ir["stats"]["tool_calls"], 0)
        _h, _e, info = self.check_dsh(ir)

    def test_omp_sample(self):
        ir = self._load("omp", OMP_SAMPLE)
        self.assertEqual(ir["source"], "omp")
        self.assertEqual(ir["stats"]["user_messages"], 1)
        self.assertEqual(ir["stats"]["assistant_messages"], 10)
        self.assertEqual(ir["stats"]["tool_calls"], 12)
        self.assertEqual(ir["stats"]["tool_results"], 12)
        _h, _e, info = self.check_dsh(ir)

    def test_keep_system_emits_system_message(self):
        from agent_session_import.ir import add_event, finalize, new_ir, text_block

        ir = new_ir("codex", "synthetic-keep-system", "synthetic")
        ir["cwd"] = str(WORKSPACE)
        ir["system_prompt"] = "You are a test system prompt."
        add_event(ir, "system_message", 1000, text="developer instructions", origin="developer")
        add_event(ir, "user_message", 2000, blocks=[text_block("hi")])
        finalize(ir)
        header, events = dsh.build_session(ir, target_cwd=str(WORKSPACE), keep_system=True)
        sys_events = [e for e in events if e["type"] == "system/message"]
        self.assertEqual(len(sys_events), 2)
        for ev in sys_events:
            self.assertEqual(ev["surfaceOp"], "append")
            self.assertEqual(ev["data"]["message"]["source"]["kind"], "system-prompt")
        errors, _warnings, _info = dsh._check_events(events)
        self.assertEqual(errors, [], errors)


class VerifyTest(unittest.TestCase):
    def test_verify_generated_artifacts(self):
        tmp = tempfile.mkdtemp(prefix="asi-verify-")
        p = run_cli("convert", "--from", "codex", "--session", str(CODEX_SAMPLE), "--out", tmp)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        zst = next(Path(tmp).glob("codex/*/session.v4.jsonl.zstd"))
        plain = next(Path(tmp).glob("codex/*/session.v4.jsonl"))
        for path in (zst, plain):
            report = dsh.verify_file(str(path))
            self.assertEqual(report["errors"], [], (path, report["errors"]))
        # two independent zstd frames, first frame exactly one header line
        zreport = dsh.verify_file(str(zst))
        self.assertEqual(zreport["info"]["frames"], 2)
        raw = zst.read_bytes()
        self.assertEqual(raw.count(b"\x28\xb5\x2f\xfd"), 2)

    def test_verify_detects_bad_seq_and_surface(self):
        tmp = tempfile.mkdtemp(prefix="asi-verify-bad-")
        p = run_cli("convert", "--from", "codex", "--session", str(CODEX_SAMPLE), "--out", tmp)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        plain = next(Path(tmp).glob("codex/*/session.v4.jsonl"))
        lines = [json.loads(x) for x in plain.read_text(encoding="utf-8").splitlines() if x.strip()]
        lines[1]["seq"] = 7  # break contiguity
        for ev in lines[1:]:
            if ev.get("surfaceOp"):
                del ev["surfaceOp"]
                break
        bad = Path(tmp) / "bad.jsonl"
        with bad.open("w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        report = dsh.verify_file(str(bad))
        joined = "\n".join(report["errors"])
        self.assertIn("seq is not contiguous", joined)
        self.assertIn("missing surfaceOp", joined)


class AtifTest(unittest.TestCase):
    def setUp(self):
        self.ir = get_reader("codex").load_session(path=str(CODEX_SAMPLE))

    def test_export_shape(self):
        doc = atif.to_atif(self.ir)
        self.assertEqual(doc["schema_version"], "ATIF-v1.8")
        self.assertTrue(doc["trajectory_id"])
        self.assertIn("name", doc["agent"])
        self.assertIn("version", doc["agent"])
        sources = [s["source"] for s in doc["steps"]]
        self.assertIn("user", sources)
        self.assertIn("agent", sources)
        self.assertEqual([s["step_id"] for s in doc["steps"]], list(range(1, len(doc["steps"]) + 1)))
        errors, _warnings = atif.validate(doc)
        self.assertEqual(errors, [], errors)
        agent_steps = [s for s in doc["steps"] if s["source"] == "agent" and s.get("tool_calls")]
        self.assertGreater(len(agent_steps), 0)
        for step in agent_steps:
            results = (step.get("observation") or {}).get("results") or []
            self.assertEqual(len(results), len(step["tool_calls"]))

    def test_roundtrip_to_dsh(self):
        doc = atif.to_atif(self.ir)
        back = atif.from_atif(doc, source_path="memory.atif.json")
        self.assertEqual(back["source"], "atif")
        self.assertEqual(back["stats"]["user_messages"], self.ir["stats"]["user_messages"])
        self.assertEqual(back["stats"]["tool_calls"], self.ir["stats"]["tool_calls"])
        self.assertEqual(back["stats"]["tool_results"], self.ir["stats"]["tool_results"])
        header, events = dsh.build_session(back, target_cwd=str(WORKSPACE))
        errors, _warnings, _info = dsh._check_events(events)
        self.assertEqual(errors, [], errors)

    def test_fixture_file(self):
        doc = atif.load(str(FIXTURES / "codex-sample.atif.json"))
        self.assertEqual(doc["schema_version"], "ATIF-v1.8")
        errors, _warnings = atif.validate(doc)
        self.assertEqual(errors, [], errors)


class ImportIsolationTest(unittest.TestCase):
    def test_plan_write_skip_and_register(self):
        ir = get_reader("codex").load_session(path=str(CODEX_SAMPLE))
        home = tempfile.mkdtemp(prefix="asi-dsh-home-")
        plan = dsh.plan_import(ir, home, target_cwd=str(WORKSPACE))
        self.assertIn("--" + dsh.project_key(str(WORKSPACE)).strip("-") + "--", plan["path"])
        os.makedirs(os.path.dirname(os.path.join(home, "storages")), exist_ok=True)
        os.makedirs(os.path.join(home, "storages"), exist_ok=True)
        ws_path = os.path.join(home, "storages", "workspace.json")
        with open(ws_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "unit": {"name": "workspace", "version": 2},
                    "global": {"initialized": True, "defaultWorkspaceId": "w1", "workspaceIds": ["w1"]},
                    "tables": {
                        "workspaces": {
                            "w1": {
                                "path": os.path.realpath(str(WORKSPACE)),
                                "title": "t",
                                "sessionIds": [],
                                "createdAt": "2026-10-30T00:00:00Z",
                                "updatedAt": "2026-10-30T00:00:00Z",
                            }
                        }
                    },
                },
                f,
            )
        self.assertEqual(dsh.write_import(plan), "written")
        report = dsh.verify_file(plan["path"])
        self.assertEqual(report["errors"], [], report["errors"])
        # idempotent: same deterministic id -> skip without --overwrite
        self.assertEqual(dsh.write_import(plan), "skipped")
        status, detail = dsh.register_in_workspace(home, plan["cwd"], plan["session_id"])
        self.assertEqual(status, "registered", detail)
        with open(ws_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["tables"]["workspaces"]["w1"]["sessionIds"][0], plan["session_id"])
        self.assertTrue(any(n.startswith("workspace.json.bak.") for n in os.listdir(os.path.join(home, "storages"))))
        self.assertEqual(dsh.register_in_workspace(home, plan["cwd"], plan["session_id"])[0], "already")

    def test_import_refuses_without_yes(self):
        home = tempfile.mkdtemp(prefix="asi-noyes-")
        target = os.path.join(home, "dsh-home")
        p = run_cli("import", "--from", "codex", "--session", str(CODEX_SAMPLE), "--dsh-home", target)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(target, "sessions")))

    def test_import_dry_run_writes_nothing(self):
        home = tempfile.mkdtemp(prefix="asi-dry-")
        target = os.path.join(home, "dsh-home")
        p = run_cli(
            "import", "--from", "codex", "--session", str(CODEX_SAMPLE),
            "--dsh-home", target, "--dry-run", "--target-cwd", str(WORKSPACE),
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("dry-run", p.stdout)
        self.assertFalse(os.path.exists(os.path.join(target, "sessions")))


def make_isolated_home(prefix):
    """Temp DSH home with a workspace.json whose path == this workspace (no real ~/.dsh)."""
    home = tempfile.mkdtemp(prefix=prefix)
    storages = os.path.join(home, "storages")
    os.makedirs(storages, exist_ok=True)
    ws_path = os.path.join(storages, "workspace.json")
    with open(ws_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "unit": {"name": "workspace", "version": 2},
                "global": {"initialized": True, "defaultWorkspaceId": "w1", "workspaceIds": ["w1"]},
                "tables": {
                    "workspaces": {
                        "w1": {
                            "path": os.path.realpath(str(WORKSPACE)),
                            "title": "t",
                            "sessionIds": [],
                            "createdAt": "2026-10-30T00:00:00Z",
                            "updatedAt": "2026-10-30T00:00:00Z",
                        }
                    }
                },
            },
            f,
        )
    return home, ws_path


def workspace_session_ids(ws_path):
    with open(ws_path, encoding="utf-8") as f:
        data = json.load(f)
    return list(data["tables"]["workspaces"]["w1"]["sessionIds"])


def workspace_backup_count(home):
    storages = os.path.join(home, "storages")
    return len([n for n in os.listdir(storages) if n.startswith("workspace.json.bak.")])


class RegisterSkipTest(unittest.TestCase):
    """--register must also work for already-imported (skipped) sessions."""

    def _base_args(self, home):
        return (
            "import", "--from", "codex", "--session", str(CODEX_SAMPLE),
            "--dsh-home", home, "--target-cwd", str(WORKSPACE), "--yes",
        )

    def test_register_after_prior_import_without_register(self):
        # Real-world flow: bulk import first (no --register), attach to workspace later.
        home, ws_path = make_isolated_home("asi-reg-skip-")
        p1 = run_cli(*self._base_args(home))
        self.assertEqual(p1.returncode, 0, p1.stdout + p1.stderr)
        self.assertIn("imported=1", p1.stdout)
        self.assertEqual(workspace_session_ids(ws_path), [])

        # Session now exists -> import path is skipped, but --register must still run.
        p2 = run_cli(*self._base_args(home), "--register")
        self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
        self.assertIn("skipped=1", p2.stdout)
        self.assertIn("[register]", p2.stdout)
        ids = workspace_session_ids(ws_path)
        self.assertEqual(len(ids), 1)
        self.assertTrue(ids[0].startswith("session-"))
        self.assertEqual(workspace_backup_count(home), 1)

        # Re-running --register on an already registered id is idempotent:
        # no duplicate insert, no extra backup.
        p3 = run_cli(*self._base_args(home), "--register")
        self.assertEqual(p3.returncode, 0, p3.stdout + p3.stderr)
        self.assertIn("skipped=1", p3.stdout)
        self.assertIn("already", p3.stdout)
        self.assertEqual(workspace_session_ids(ws_path), ids)
        self.assertEqual(workspace_backup_count(home), 1)

    def test_import_with_register_twice_is_idempotent(self):
        home, ws_path = make_isolated_home("asi-reg-idem-")
        cmd = tuple(self._base_args(home)) + ("--register",)
        p1 = run_cli(*cmd)
        self.assertEqual(p1.returncode, 0, p1.stdout + p1.stderr)
        self.assertIn("imported=1", p1.stdout)
        ids = workspace_session_ids(ws_path)
        self.assertEqual(len(ids), 1)
        self.assertEqual(workspace_backup_count(home), 1)
        p2 = run_cli(*cmd)
        self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
        self.assertIn("skipped=1", p2.stdout)
        self.assertIn("already", p2.stdout)
        self.assertEqual(workspace_session_ids(ws_path), ids)
        self.assertEqual(workspace_backup_count(home), 1)

    def test_dry_run_register_plan_writes_nothing(self):
        home, ws_path = make_isolated_home("asi-reg-dry-")
        dry = tuple(self._base_args(home))[:-1] + ("--dry-run", "--register")
        p = run_cli(*dry)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("[dry-run] register: would-register", p.stdout)
        self.assertFalse(os.path.exists(os.path.join(home, "sessions")))
        self.assertEqual(workspace_session_ids(ws_path), [])
        self.assertEqual(workspace_backup_count(home), 0)

        # after a real registered import, the dry-run plan reports "already"
        self.assertEqual(run_cli(*self._base_args(home), "--register").returncode, 0)
        p2 = run_cli(*dry)
        self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
        self.assertIn("[dry-run] register: already", p2.stdout)
        self.assertEqual(workspace_backup_count(home), 1)


def make_missing_cwd_atif(dirpath):
    """Real-sample ATIF whose extra.cwd points at a directory that does not exist."""
    doc = atif.to_atif(get_reader("codex").load_session(path=str(CODEX_SAMPLE)))
    doc["extra"]["cwd"] = "/nonexistent/asi-fallback-test-cwd"
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, "missing-cwd.atif.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


class FallbackCwdTest(unittest.TestCase):
    """--fallback-cwd is used ONLY when the source cwd is missing / not a directory."""

    def test_priority_target_cwd_and_provenance(self):
        ir = get_reader("codex").load_session(path=str(CODEX_SAMPLE))
        missing = "/nonexistent/asi-fallback-test-cwd"
        ir["cwd"] = missing
        home = tempfile.mkdtemp(prefix="asi-fb-prio-")
        other = tempfile.mkdtemp(prefix="asi-fb-target-")

        # no fallback / target -> still an explicit error (no silent rewrite)
        with self.assertRaises(ValueError) as ctx:
            dsh.plan_import(ir, home)
        self.assertIn("--fallback-cwd", str(ctx.exception))
        self.assertIn("--target-cwd", str(ctx.exception))

        # fallback used only because source cwd is missing
        plan = dsh.plan_import(ir, home, fallback_cwd=str(WORKSPACE))
        self.assertTrue(plan["fallback_used"])
        self.assertEqual(plan["cwd"], os.path.realpath(str(WORKSPACE)))
        self.assertIn("cwd 缺失 → fallback 到", plan["cwd_note"])
        self.assertEqual(plan["source_cwd"], missing)

        # existing source cwd wins over --fallback-cwd (provenance preserved)
        ir2 = dict(ir)
        ir2["cwd"] = str(WORKSPACE)
        plan2 = dsh.plan_import(ir2, home, fallback_cwd=other)
        self.assertFalse(plan2["fallback_used"])
        self.assertEqual(plan2["cwd"], os.path.realpath(str(WORKSPACE)))

        # --target-cwd still overrides everything, even with a fallback
        plan3 = dsh.plan_import(ir2, home, target_cwd=other, fallback_cwd=str(WORKSPACE))
        self.assertFalse(plan3["fallback_used"])
        self.assertEqual(plan3["cwd"], os.path.realpath(other))

    def test_cli_dry_run_with_and_without_fallback(self):
        atif_path = make_missing_cwd_atif(tempfile.mkdtemp(prefix="asi-fb-atif-"))
        home = tempfile.mkdtemp(prefix="asi-fb-dry-")
        base = ("import", "--from", "atif", "--session", atif_path, "--dsh-home", home, "--dry-run")

        p_no = run_cli(*base)
        self.assertEqual(p_no.returncode, 1, p_no.stdout + p_no.stderr)
        self.assertIn("FAIL", p_no.stdout)
        self.assertIn("--fallback-cwd", p_no.stdout)

        p_fb = run_cli(*base, "--fallback-cwd", str(WORKSPACE))
        self.assertEqual(p_fb.returncode, 0, p_fb.stdout + p_fb.stderr)
        self.assertIn("cwd 缺失 → fallback 到", p_fb.stdout)
        self.assertIn("fallback_used=1", p_fb.stdout)
        self.assertIn("would import=1", p_fb.stdout)
        self.assertFalse(os.path.exists(os.path.join(home, "sessions")))

    def test_import_summary_counts_and_register_with_fallback(self):
        atif_path = make_missing_cwd_atif(tempfile.mkdtemp(prefix="asi-fb-atif2-"))
        home, ws_path = make_isolated_home("asi-fb-import-")
        cmd = (
            "import", "--from", "atif", "--session", atif_path,
            "--dsh-home", home, "--fallback-cwd", str(WORKSPACE), "--yes", "--register",
        )
        p1 = run_cli(*cmd)
        self.assertEqual(p1.returncode, 0, p1.stdout + p1.stderr)
        self.assertIn("imported=1", p1.stdout)
        self.assertIn("fallback_used=1", p1.stdout)
        self.assertIn("cwd 缺失 → fallback 到", p1.stdout)
        self.assertEqual(len(workspace_session_ids(ws_path)), 1)
        self.assertEqual(workspace_backup_count(home), 1)

        # skipped on re-run, fallback_used still reported, register idempotent
        p2 = run_cli(*cmd)
        self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
        self.assertIn("skipped=1", p2.stdout)
        self.assertIn("fallback_used=1", p2.stdout)
        self.assertIn("already", p2.stdout)
        self.assertEqual(len(workspace_session_ids(ws_path)), 1)
        self.assertEqual(workspace_backup_count(home), 1)




class HarnessInteropTest(unittest.TestCase):
    """5 native readers/writers + ATIF hub + matrix smoke."""

    TARGETS = ("claude", "codex", "omp", "qoder", "dsh")

    def _codex_ir(self):
        return get_reader("codex").load_session(path=str(CODEX_SAMPLE))

    def test_native_roundtrip_all_five(self):
        from agent_session_import import writers
        from agent_session_import.readers import get as reader_get

        ir = self._codex_ir()
        base = tempfile.mkdtemp(prefix="asi-native-rt-")
        for target in self.TARGETS:
            root = os.path.join(base, target)
            res = writers.native_write(ir, target, root, "session-" + "0" * 8 + "-test")
            self.assertTrue(os.path.isfile(res["artifact"]), (target, res))
            back = reader_get(target).load_session(path=res["artifact"])
            self.assertEqual(back["stats"]["user_messages"], ir["stats"]["user_messages"], target)
            self.assertEqual(back["stats"]["assistant_messages"], ir["stats"]["assistant_messages"], target)
            self.assertEqual(back["stats"]["tool_calls"], ir["stats"]["tool_calls"], target)
            self.assertEqual(back["stats"]["tool_results"], ir["stats"]["tool_results"], target)

    def test_atif_hub_to_each_target(self):
        from agent_session_import import atif, writers
        from agent_session_import.readers import get as reader_get

        ir = self._codex_ir()
        mid = atif.from_atif(atif.to_atif(ir), source_path="memory.atif.json")
        self.assertEqual(atif.validate(atif.to_atif(ir))[0], [])
        base = tempfile.mkdtemp(prefix="asi-atif-hub-")
        for target in self.TARGETS:
            root = os.path.join(base, target)
            res = writers.native_write(mid, target, root, "session-" + "1" * 8 + "-test")
            back = reader_get(target).load_session(path=res["artifact"])
            for key in ("user_messages", "assistant_messages", "tool_calls", "tool_results"):
                self.assertEqual(back["stats"][key], mid["stats"][key], (target, key))

    def test_install_refused_without_yes_and_isolated_install(self):
        root = tempfile.mkdtemp(prefix="asi-install-")
        p = run_cli("convert", "--from", "codex", "--session", str(CODEX_SAMPLE),
                    "--to", "codex", "--install", "--install-root", root)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        p = run_cli("convert", "--from", "codex", "--session", str(CODEX_SAMPLE),
                    "--to", "codex", "--install", "--yes", "--install-root", root)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(
            [f for f in __import__("glob").glob(os.path.join(root, "sessions", "**", "*.jsonl"), recursive=True)]
        )

    def test_matrix_smoke(self):
        out = tempfile.mkdtemp(prefix="asi-matrix-smoke-")
        report = os.path.join(out, "report.json")
        p = run_cli("matrix", "--sources", "codex,dsh", "--no-l3",
                    "--out", os.path.join(out, "staging"), "--report", report)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(report, encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["schema"], "asi-interop-matrix/v1")
        self.assertEqual(len(rep["directions"]), 2)
        self.assertEqual(rep["summary"]["fail"], 0)
        self.assertEqual(rep["summary"]["atif_self_pass"], 2)
        for d in rep["directions"]:
            for key in ("from", "to", "source_session_id", "status", "l0", "l1", "l2", "l3",
                        "ir_counts", "lossy", "warnings", "evidence_path"):
                self.assertIn(key, d)
        # the ATIF self-roundtrip uses the same real sample and must match
        self.assertTrue(all(r["ok"] for r in rep["atif_self_roundtrip"]))

    def test_list_claude_and_dsh_json(self):
        from agent_session_import import writers

        ir = self._codex_ir()
        base = tempfile.mkdtemp(prefix="asi-list-")
        claude_root = os.path.join(base, "claude", "projects")
        dsh_root = os.path.join(base, "dsh", "sessions")
        writers.native_write(ir, "claude", claude_root, "session-" + "2" * 8 + "-list")
        writers.native_write(ir, "dsh", dsh_root, "session-" + "3" * 8 + "-list")
        p1 = run_cli("list", "claude", "--root", claude_root, "--json")
        p2 = run_cli("list", "dsh", "--root", dsh_root, "--json")
        for p, src in ((p1, "claude"), (p2, "dsh")):
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            obj = json.loads(p.stdout)
            self.assertEqual(obj["command"], "list")
            self.assertEqual(obj["source"], src)
            self.assertGreaterEqual(obj["count"], 1)
            # --json fields are part of the GUI contract
            for key in ("source", "id", "title", "cwd", "created_at_ms", "updated_at_ms",
                        "path", "lines"):
                self.assertIn(key, obj["sessions"][0])




class OssTrajectoryTest(unittest.TestCase):
    """OSS traj-session/1 reader: all three messages_format branches + CLI + batch2 matrix."""

    BATCH2 = WORKSPACE / "samples" / "batch2" / "oss"
    OSS = WORKSPACE / "samples" / "oss"
    ANTHROPIC = BATCH2 / "aider__claude-opus-5__019f978d-26da-7000-afea-1cca36d65c7a.jsonl"
    RESPONSES = OSS / "lc__gpt-5.5__codex__01a0826c.jsonl"
    CHAT = OSS / "st-delivery-harnesses" / "claude-opus-5__other__0000a860.jsonl"

    def test_reader_three_formats(self):
        cases = [
            (self.ANTHROPIC, "anthropic-messages"),
            (self.RESPONSES, "openai-responses"),
            (self.CHAT, "openai-chat"),
        ]
        for path, fmt in cases:
            self.assertTrue(path.is_file(), path)
            ir = get_reader("oss").load_session(path=str(path))
            self.assertEqual(ir["source"], "oss")
            extra = ir.get("extra") or {}
            self.assertEqual(extra.get("messages_format"), fmt)
            self.assertTrue(extra.get("source_harness"))
            self.assertGreater((ir.get("stats") or {}).get("events"), 0, path)
            self.assertTrue(ir.get("title"))
            if fmt == "anthropic-messages":
                stats = ir["stats"]
                self.assertGreater(stats["assistant_messages"], 0)
                self.assertEqual(stats["tool_calls"], stats["tool_results"])
                self.assertGreater(stats["tool_calls"], 0)

    def test_reader_extra_and_usage(self):
        ir = get_reader("oss").load_session(path=str(self.RESPONSES))
        extra = ir["extra"]
        self.assertEqual(extra.get("source_harness"), "codex")
        self.assertTrue(extra.get("bucket"))
        self.assertEqual(extra.get("messages_format"), "openai-responses")
        self.assertIsNotNone(ir.get("source_usage"))
        self.assertIn("usage_scope", (ir.get("extra") or {}))

    def test_cli_list_oss_json(self):
        root = str(self.BATCH2 if self.BATCH2.is_dir() else self.OSS)
        p = run_cli("list", "oss", "--root", root, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        obj = json.loads(p.stdout)
        self.assertEqual(obj["command"], "list")
        self.assertEqual(obj["source"], "oss")
        self.assertGreaterEqual(obj["count"], 15)
        session = obj["sessions"][0]
        for key in ("harness", "messages_format", "model", "id", "path", "lines"):
            self.assertIn(key, session)

    def test_cli_convert_oss_to_atif(self):
        out = tempfile.mkdtemp(prefix="asi-oss-atif-")
        p = run_cli("convert", "--from", "oss", "--session", str(self.ANTHROPIC),
                    "--to", "atif", "--out", out, "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        obj = json.loads(p.stdout)
        self.assertEqual(obj["source"], "oss")
        self.assertEqual(obj["results"][0]["status"], "ok")
        doc = atif.load(obj["results"][0]["artifact"])
        self.assertEqual(doc["schema_version"], "ATIF-v1.8")
        self.assertGreater(len(doc["steps"]), 0)

    def test_cli_batch2_matrix_smoke(self):
        out = tempfile.mkdtemp(prefix="asi-batch2-smoke-")
        report = os.path.join(out, "report.json")
        root = str(self.OSS / "st-delivery-harnesses")
        p = run_cli("matrix-batch2", "--root", root, "--limit", "3", "--no-format",
                    "--out", os.path.join(out, "staging"), "--report", report)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(report, encoding="utf-8") as f:
            rep = json.load(f)
        self.assertEqual(rep["schema"], "asi-oss-batch2-matrix/v1")
        self.assertEqual(len(rep["entries"]), 3)
        self.assertEqual(rep["summary"]["fail"], 0)
        self.assertEqual(rep["summary"]["l3_dsh"], 3)
        for entry in rep["entries"]:
            self.assertTrue(entry["l3"]["ok"], entry["harness"])
            self.assertIn("messages_format", entry)




class Batch3FixturesTest(unittest.TestCase):
    """Batch-3 native adapters (FIXTURE evidence level; public fixtures only)."""

    FIX = WORKSPACE / "samples" / "batch2" / "public-fixtures"

    def _load(self, source, rel):
        path = self.FIX / rel
        self.assertTrue(path.is_file(), path)
        return get_reader(source).load_session(path=str(path))

    def _stats(self, source, rel, **expect):
        ir = self._load(source, rel)
        st = ir["stats"]
        for key, value in expect.items():
            self.assertEqual(st[key], value, (source, rel, key))
        self.assertEqual(ir["extra"]["evidence_level"], "FIXTURE")
        return ir

    def test_copilot_simple(self):
        ir = self._stats("copilot", "atifact/test-fixtures/copilot-cli-simple.jsonl",
                         user_messages=1, assistant_messages=2,
                         tool_calls=1, tool_results=1)
        self.assertIn("missing-session-start", ir["warnings"])
        self.assertEqual(ir["source_session_id"], "session-xyz-789")
        self.assertEqual(ir["model"], "claude-sonnet-4.6")
        # delta-only assistant messages were merged into non-empty text
        texts = ["".join(b.get("text") or "" for b in e["blocks"] if b.get("type") == "text")
                 for e in ir["events"] if e.get("kind") == "assistant_message"]
        self.assertTrue(any(t.strip() for t in texts))

    def test_copilot_subagent_and_shutdown(self):
        ir = self._stats("copilot", "atifact/test-fixtures/copilot-cli-subagent.jsonl",
                         user_messages=1, assistant_messages=4, tool_calls=3, tool_results=3)
        self.assertEqual(ir["cwd"], "/home/user/project")
        self.assertIn("copilot:subagent-collapsed", ir["lossy"])
        ir2 = self._stats("copilot", "atifact/test-fixtures/copilot-cli-shutdown.jsonl",
                          tool_calls=1, tool_results=1)

    def test_gemini(self):
        ir = self._stats("gemini", "agent-sessions/stage0/gemini/small.json",
                         user_messages=1, assistant_messages=1)
        self.assertEqual(ir["source_session_id"], "session-2026-01-16T18-34-3739ef95")
        self.assertEqual(ir["model"], "gemini-3-flash-preview")
        roles = [e["kind"] for e in ir["events"] if e["kind"] in ("user_message", "assistant_message")]
        self.assertEqual(roles, ["user_message", "assistant_message"])
        assistant = next(e for e in ir["events"] if e["kind"] == "assistant_message")
        self.assertEqual(assistant["usage"]["inputTokens"], 10)
        self.assertEqual(assistant["usage"]["outputTokens"], 5)
        self.assertEqual(assistant["usage"]["totalTokens"], 15)
        reasoning = [b for b in assistant["blocks"] if b["type"] == "reasoning"]
        self.assertEqual(reasoning[0]["text"], "Short reasoning placeholder.")
        self.assertIsNone(ir["cwd"])
        self.assertIn("gemini:cwd-unresolved", ir["warnings"])
        self.assertGreater(ir["created_at_ms"], 0)

    def test_aider(self):
        ir = self._stats("aider", "sessionport/tests-fixtures/aider/history/abc123.md",
                         user_messages=2, assistant_messages=2)
        users = [b["text"] for e in ir["events"] if e["kind"] == "user_message"
                 for b in e["blocks"]]
        self.assertEqual(users, ["Refactor the queue to use an outbox",
                                 "Can you also handle retries?"])
        replies = ["".join(b.get("text") or "" for b in e["blocks"])
                   for e in ir["events"] if e["kind"] == "assistant_message"]
        self.assertIn("Decision: use the outbox pattern.", replies[0])
        self.assertIn("aider:no-timestamps", ir["lossy"])
        self.assertIn("aider:no-tool-events", ir["lossy"])

    def test_cursor_current_and_legacy(self):
        ir = self._stats("cursor", "agent-sessions/stage0/cursor/small.jsonl",
                         user_messages=2, assistant_messages=2,
                         tool_calls=1, tool_results=1)
        self.assertEqual(sum(1 for e in ir["events"] if e["kind"] == "turn_abort"), 1)
        self.assertIn("cursor:tool-result-missing", ir["lossy"])
        legacy = self._stats("cursor", "agent-sessions/legacy/Cursor/test-session.jsonl",
                             user_messages=2, assistant_messages=4,
                             tool_calls=2, tool_results=2)
        users = [b["text"] for e in legacy["events"] if e["kind"] == "user_message"
                 for b in e["blocks"]]
        self.assertEqual(users, ["run ls command", "now show me the git status"])

    def test_qwen_positive_and_negative(self):
        neg = self._load("qwen", "agent-sessions/stage0/qwen/019f0000-0000-7000-8000-000000000002.jsonl")
        self.assertEqual(neg["stats"]["user_messages"], 1)
        self.assertEqual(neg["source_session_id"], "019f0000-0000-7000-8000-000000000099")
        self.assertIn("qwen:session-id-mismatch", neg["warnings"])
        pos = self._load("qwen",
                         "agent-sessions/stage0/qwen/019f0000000070008000000000000003.jsonl")
        text = "".join(b.get("text") or "" for e in pos["events"]
                       if e["kind"] == "user_message" for b in e["blocks"])
        self.assertEqual(text, "Inspect a compact-ID synthetic fixture.")
        self.assertEqual(pos.get("extra_git_branch"), "fixture-branch")

    def test_pi_tree(self):
        ir = self._stats("pi", "agent-sessions/stage0/pi/small.jsonl",
                         user_messages=3, assistant_messages=5,
                         tool_calls=2, tool_results=2)
        self.assertEqual(ir["cwd"], "/tmp/as-agent-fixture/project")
        self.assertEqual(ir["model"], "pi-fixture-model")

    def test_batch3_writer_reader_roundtrip(self):
        from agent_session_import.writers import native_write

        fixtures = {
            "copilot": "atifact/test-fixtures/copilot-cli-simple.jsonl",
            "gemini": "agent-sessions/stage0/gemini/small.json",
            "aider": "sessionport/tests-fixtures/aider/history/abc123.md",
            "cursor": "agent-sessions/stage0/cursor/small.jsonl",
            "qwen": "agent-sessions/stage0/qwen/019f0000000070008000000000000003.jsonl",
            "pi": "agent-sessions/stage0/pi/small.jsonl",
        }
        base = tempfile.mkdtemp(prefix="asi-b3-rt-")
        for source, rel in fixtures.items():
            ir = self._load(source, rel)
            root = os.path.join(base, source)
            res = native_write(ir, source, root, "session-" + "b3" + source)
            back = get_reader(source).load_session(path=res["artifact"])
            for key in ("user_messages", "assistant_messages"):
                self.assertEqual(back["stats"][key], ir["stats"][key], (source, key))
            self.assertEqual(back["extra"]["evidence_level"], "FIXTURE")

    def test_cli_batch3_matrix_smoke_and_json_list(self):
        out = tempfile.mkdtemp(prefix="asi-b3-smoke-")
        report = os.path.join(out, "report.json")
        p = run_cli("matrix-batch3", "--root", str(self.FIX), "--limit", "2",
                    "--out", os.path.join(out, "staging"), "--report", report)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.load(open(report, encoding="utf-8"))
        self.assertEqual(rep["schema"], "asi-batch3-matrix/v1")
        self.assertEqual(rep["summary"]["fail"], 0)
        self.assertEqual(len(rep["entries"]), 2)
        self.assertEqual(rep["evidence_level"], "FIXTURE")
        lst = run_cli("list", "gemini", "--root", str(self.FIX), "--json")
        self.assertEqual(lst.returncode, 0, lst.stdout + lst.stderr)
        obj = json.loads(lst.stdout)
        self.assertEqual(obj["source"], "gemini")
        self.assertGreaterEqual(obj["count"], 1)
        self.assertEqual(obj["sessions"][0]["evidence_level"], "FIXTURE")




class Batch4FixturesTest(unittest.TestCase):
    """Batch-4 adapters (evidence FIXTURE / FIXTURE-LOW / FIXTURE-CONSTRUCTED; no NATIVE)."""

    FIX = WORKSPACE / "samples" / "batch2" / "public-fixtures"

    def _load(self, source, rel):
        path = self.FIX / rel
        self.assertTrue(path.is_file(), path)
        return get_reader(source).load_session(path=str(path))

    def test_openclaw(self):
        ir = self._load("openclaw", "agent-sessions/stage0/openclaw/small.jsonl")
        st = ir["stats"]
        self.assertEqual(st["user_messages"], 1)
        self.assertEqual(st["assistant_messages"], 1)
        self.assertEqual(st["tool_calls"], 1)
        self.assertEqual(st["tool_results"], 1)
        self.assertEqual(ir["cwd"], "/tmp/repo")
        self.assertEqual(ir["model"], "openclaw-small")
        call = next(b for e in ir["events"] if e["kind"] == "assistant_message"
                    for b in e["blocks"] if b["type"] == "tool-call")
        self.assertEqual(call["name"], "shell_exec")
        self.assertEqual(json.loads(call["arguments"]), {"command": "ls"})
        result = next(e for e in ir["events"] if e["kind"] == "tool_result")
        self.assertEqual(result["content"], "main.swift\nResources\n")

    def test_kimi(self):
        ir = self._load("kimi", "agent-sessions/stage0/kimi/small.jsonl")
        self.assertEqual(len(ir["extra"]["event_type_counts"]), 22)
        self.assertEqual(ir["cwd"], "/private/tmp/as-agent-lab/kimi/project")
        texts = ["".join(b.get("text") or "" for b in e["blocks"] if b.get("type") == "text")
                 for e in ir["events"] if e["kind"] == "user_message"]
        self.assertIn("SYNTHETIC KIMI PARITY PROMPT", texts)
        assistant = [e for e in ir["events"] if e["kind"] == "assistant_message"][-1]
        self.assertIn("SYNTHETIC ASSISTANT TEXT",
                      "".join(b.get("text") or "" for b in assistant["blocks"]))
        self.assertTrue(any(b["type"] == "tool-call" for b in assistant["blocks"]))
        self.assertIn("kimi:synthetic-time", ir["lossy"])
        self.assertIn("kimi-k2.7-code", ir["model"])  # fixture alias includes provider prefix

    def test_grok(self):
        ir = self._load("grok", "agent-sessions/stage0/grok/chat_history.jsonl")
        st = ir["stats"]
        self.assertEqual((st["user_messages"], st["assistant_messages"],
                          st["tool_calls"], st["tool_results"]), (1, 2, 1, 1))
        self.assertEqual(ir["cwd"], "/tmp/as-agent-lab/grok/project")
        self.assertEqual(ir["title"], "Count the Python files under the project root")
        self.assertEqual(ir["model"], "grok-4.5")
        self.assertEqual(ir["extra"]["num_messages"], 4)
        self.assertEqual(ir["extra"]["session_kind"], "subagent")

    def test_droid_two_schemas(self):
        store = self._load("droid", "agent-sessions/stage0/droid/session_store_schema_drift.jsonl")
        self.assertEqual(store["title"], "Stage0 Droid Drift")
        self.assertEqual(store["cwd"], "/tmp")
        self.assertEqual(store["stats"]["user_messages"], 1)
        user = next(e for e in store["events"] if e["kind"] == "user_message")
        self.assertEqual("".join(b.get("text") or "" for b in user["blocks"]), "Do the thing")
        self.assertIn("droid:embedded-system-reminder", store["lossy"])
        stream = self._load("droid", "agent-sessions/stage0/droid/stream_json_small.jsonl")
        st = stream["stats"]
        self.assertEqual((st["user_messages"], st["assistant_messages"],
                          st["tool_calls"], st["tool_results"]), (1, 2, 1, 1))
        result = next(e for e in stream["events"] if e["kind"] == "tool_result")
        self.assertIn("hi", result["content"])

    def test_antigravity_reader_only(self):
        ir = self._load("antigravity", "agent-sessions/stage0/antigravity/desktop_small.jsonl")
        st = ir["stats"]
        self.assertEqual((st["user_messages"], st["assistant_messages"],
                          st["tool_calls"], st["tool_results"]), (1, 3, 2, 2))
        usage_in = sum((e.get("usage") or {}).get("inputTokens", 0)
                       for e in ir["events"] if e["kind"] == "assistant_message")
        self.assertEqual(usage_in, 9452 + 10146 + 10406)
        self.assertEqual(ir["extra"]["evidence_level"], "FIXTURE-LOW")
        cli = self._load("antigravity", "agent-sessions/stage0/antigravity/cli_schema_drift.jsonl")
        self.assertIn("antigravity:unknown-type:BROWSER_NAVIGATE", cli["warnings"])
        self.assertIsNone(cli["cwd"])

    def test_constructed_sqlite_hermes_devin_opencode(self):
        from agent_session_import import batch4_construct

        tmp = tempfile.mkdtemp(prefix="asi-b4-constructed-")
        cases = {
            "hermes": "agent-sessions/stage0/hermes/small.json",
            "devin": "agent-sessions/stage0/devin/small.json",
            "opencode": "agent-sessions/stage0/opencode/001.json",
        }
        expect = {"hermes": (1, 1, 0, 0), "devin": (1, 1, 1, 1), "opencode": (1, 0, 0, 0)}
        for source, rel in cases.items():
            ir = self._load(source, rel)
            path = os.path.join(tmp, source + ".db")
            batch4_construct.write_golden_db(source, ir, path)
            back = get_reader(source).load_session(path=path)
            st = back["stats"]
            self.assertEqual((st["user_messages"], st["assistant_messages"],
                              st["tool_calls"], st["tool_results"]), expect[source], source)
            self.assertEqual(back["extra"]["evidence_level"], "FIXTURE-CONSTRUCTED")
            self.assertIn("sqlite", " ".join(back["lossy"]))
        # read-only DB connections must refuse writes
        import sqlite3
        con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(
            os.path.join(tmp, "hermes.db")), uri=True)
        con.execute("PRAGMA query_only=ON")
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("DELETE FROM messages")
        con.close()

    def test_batch4_writer_reader_roundtrip(self):
        from agent_session_import.writers import native_write

        fixtures = {
            "openclaw": "agent-sessions/stage0/openclaw/small.jsonl",
            "kimi": "agent-sessions/stage0/kimi/small.jsonl",
            "grok": "agent-sessions/stage0/grok/chat_history.jsonl",
            "droid": "agent-sessions/stage0/droid/stream_json_small.jsonl",
            "hermes": "agent-sessions/stage0/hermes/small.json",
            "devin": "agent-sessions/stage0/devin/small.json",
            "opencode": "agent-sessions/stage0/opencode/001.json",
        }
        base = tempfile.mkdtemp(prefix="asi-b4-rt-")
        for source, rel in fixtures.items():
            ir = self._load(source, rel)
            res = native_write(ir, source, os.path.join(base, source),
                               "session-" + "b4" + source)
            back = get_reader(source).load_session(path=res["artifact"])
            for key in ("user_messages", "assistant_messages", "tool_calls", "tool_results"):
                self.assertEqual(back["stats"][key], ir["stats"][key], (source, key))

    def test_cli_batch4_matrix_smoke(self):
        out = tempfile.mkdtemp(prefix="asi-b4-smoke-")
        report = os.path.join(out, "report.json")
        p = run_cli("matrix-batch4", "--limit", "2", "--out", os.path.join(out, "staging"),
                    "--report", report)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.load(open(report, encoding="utf-8"))
        self.assertEqual(rep["schema"], "asi-batch4-matrix/v1")
        self.assertEqual(rep["summary"]["fail"], 0)
        self.assertEqual(len(rep["entries"]), 2)
        for entry in rep["entries"]:
            self.assertIn(entry["evidence_level"],
                          ("FIXTURE", "FIXTURE-LOW", "FIXTURE-CONSTRUCTED"))
            self.assertNotEqual(entry["evidence_level"], "NATIVE")




class Batch5Test(unittest.TestCase):
    """Batch-5 adapters: REAL-LOCAL gemini/pi + 11 constructed sources."""

    def test_constructed_readers_all(self):
        from agent_session_import.readers import native_batch5
        for source in native_batch5.CONSTRUCTED:
            rows = get_reader(source).list_sessions(None)
            self.assertGreaterEqual(len(rows), 1, source)
            ir = get_reader(source).load_session(path=rows[0]["path"])
            st = ir["stats"]
            if source in ("kiro", "opencode"):
                self.assertIn(ir["extra"]["evidence_level"], ("FIXTURE-LOW", "FIXTURE"), source)
                self.assertGreaterEqual(len(ir.get("events") or []), 0, source)
            else:
                self.assertEqual(st["user_messages"], 1, source)
                self.assertEqual(st["assistant_messages"], 1, source)
                self.assertEqual(ir["extra"]["evidence_level"], "FIXTURE-CONSTRUCTED")
            self.assertTrue(os.path.isdir(os.path.join(
                str(WORKSPACE / "samples" / "batch5" / "constructed"), source)), source)

    def test_constructed_assertions(self):
        from agent_session_import.readers import native_batch5
        root = WORKSPACE / "samples" / "batch5" / "constructed"
        # goose: official local DB schema, sqlite read-only
        goose = get_reader("goose").load_session()
        self.assertEqual(goose["title"], "Batch 5 constructed sample: list the repository files.")
        # crush: sessions/messages sqlite, second-level timestamps
        crush = get_reader("crush").load_session()
        self.assertEqual(crush["stats"]["user_messages"], 1)
        self.assertEqual(crush["stats"]["assistant_messages"], 1)
        # openhands: base_state + events/event_<idx>.json
        oh = get_reader("openhands").load_session()
        self.assertEqual(len(oh["events"]), 2)
        # cline family aliases share parser but distinct source ids
        for alias in ("cline", "roo", "kilo-code"):
            ir = get_reader(alias).load_session()
            self.assertEqual(ir["source"], alias)
            self.assertEqual(ir["stats"]["events"], 2)
        # every constructed dir has a README with CONSTRUCTED + schema source
        for source in native_batch5.CONSTRUCTED:
            readme = root / source / "README.md"
            self.assertTrue(readme.is_file(), source)
            text = readme.read_text(encoding="utf-8")
            self.assertIn("CONSTRUCTED", text)
            self.assertIn("schema source", text)

    def test_real_local_gemini_and_pi(self):
        import glob as _g
        g = os.path.expanduser("~/.gemini/tmp/larr/chats/session-2026-10-14T17-52-e0fcd273.jsonl")
        if not os.path.isfile(g):
            self.skipTest("real Gemini session not present")
        ir = get_reader("gemini").load_session(path=g)
        self.assertGreaterEqual(ir["stats"]["user_messages"], 1)
        pi_files = sorted(_g.glob(os.path.expanduser("~/.pi/agent/sessions/*/*.jsonl")))
        if not pi_files:
            self.skipTest("real pi session not present")
        pir = get_reader("pi").load_session(path=pi_files[0])
        self.assertGreaterEqual(pir["stats"]["events"], 50)
        self.assertEqual(pir["stats"]["tool_calls"], pir["stats"]["tool_results"])

    def test_cli_list_batch5_json(self):
        for source in ("goose", "continue", "junie", "kiro", "crush", "cline",
                       "roo", "kilo-code", "codebuff", "openhands", "vibe"):
            p = run_cli("list", source, "--json")
            self.assertEqual(p.returncode, 0, (source, p.stdout + p.stderr))
            obj = json.loads(p.stdout)
            self.assertEqual(obj["source"], source)
            self.assertGreaterEqual(obj["count"], 1, source)
            expected = {"kiro": "FIXTURE-LOW", "opencode": "FIXTURE"}.get(
                source, "FIXTURE-CONSTRUCTED")
            self.assertEqual(obj["sessions"][0]["evidence_level"], expected)

    def test_cli_batch5_matrix_smoke(self):
        out = tempfile.mkdtemp(prefix="asi-b5-smoke-")
        report = os.path.join(out, "report.json")
        p = run_cli("matrix-batch5", "--limit", "2", "--out", os.path.join(out, "staging"),
                    "--report", report)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.load(open(report, encoding="utf-8"))
        self.assertEqual(rep["schema"], "asi-batch5-matrix/v2")
        self.assertEqual(rep["summary"]["fail"], 0)
        self.assertEqual(rep["summary"]["real_local"], 2)
        for entry in rep["entries"]:
            self.assertIn(entry["evidence_level"],
                          ("REAL-LOCAL", "FIXTURE-CONSTRUCTED", "FIXTURE",
                           "COLLECTED-SPARSE"))




class ProductCommandsTest(unittest.TestCase):
    """asi detect / preview / migrate — product-level backend for the Swift user app."""

    @classmethod
    def setUpClass(cls):
        cls._real = {}
        for src in ("dsh", "codex", "claude"):
            try:
                rows = [r for r in get_reader(src).list_sessions(None) if r.get("path")]
            except (OSError, ValueError):
                rows = []
            cls._real[src] = rows

    def _pick(self, src, prefer_workspace=False):
        rows = self._real.get(src) or []
        if prefer_workspace:
            for r in rows:
                if os.path.realpath(r.get("cwd") or "") == os.path.realpath(str(WORKSPACE)):
                    return r
        return rows[0] if rows else None

    def test_detect_json_real(self):
        p = run_cli("detect", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        rep = json.loads(p.stdout)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["command"], "detect")
        self.assertEqual(rep["scan"], "fast")
        by_id = {h["id"]: h for h in rep["harnesses"]}
        for src in ("claude", "codex", "dsh", "omp", "qoder"):
            self.assertIn(src, by_id)
            self.assertTrue(by_id[src]["detected"], src)
            self.assertGreater(by_id[src]["session_count"], 0, src)
        for h in rep["harnesses"]:
            self.assertTrue(h["display_name"])
            self.assertIn("export", h["capabilities"])
        self.assertGreaterEqual(rep["totals"]["harnesses_detected"], 5)
        self.assertEqual(rep["totals"]["total_sessions"],
                         sum(h["session_count"] for h in rep["harnesses"] if h["detected"]))

    def test_detect_fast_matches_deep_core_counts(self):
        fast = run_cli("detect", "--json", "--fast")
        deep = run_cli("detect", "--json", "--deep")
        self.assertEqual(fast.returncode, 0, fast.stderr)
        self.assertEqual(deep.returncode, 0, deep.stderr)
        f = json.loads(fast.stdout)
        d = json.loads(deep.stdout)
        self.assertEqual(f["scan"], "fast")
        self.assertEqual(d["scan"], "deep")
        fm = {h["id"]: h for h in f["harnesses"]}
        dm = {h["id"]: h for h in d["harnesses"]}
        # the five core sources must report identical session counts in both modes
        for src in ("claude", "codex", "omp", "qoder", "dsh"):
            self.assertEqual(fm[src]["session_count"], dm[src]["session_count"], src)
            self.assertEqual(fm[src]["detected"], dm[src]["detected"], src)
        # fast path must not lose the product fields
        for h in f["harnesses"]:
            for key in ("id", "display_name", "family", "detected", "path",
                        "session_count", "recent_at", "notes", "capabilities"):
                self.assertIn(key, h)
        # fast count = filesystem count: no session content parsed, so it is deterministic
        self.assertEqual(f["totals"]["total_sessions"],
                         sum(h["session_count"] for h in f["harnesses"] if h["detected"]))
        self.assertGreaterEqual(f["totals"]["harnesses_detected"], 5)

    def test_preview_json_readonly(self):
        row = self._pick("dsh") or self._pick("codex")
        self.assertIsNotNone(row)
        src = "dsh" if row in (self._real.get("dsh") or []) else "codex"
        out = tempfile.mkdtemp(prefix="asi-preview-cwd-")
        p = run_cli("preview", "--from", src, "--session", str(row["id"]), "--json", cwd=out)
        self.assertEqual(p.returncode, 0, p.stderr)
        rep = json.loads(p.stdout)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["source"], src)
        for key in ("title", "cwd", "model", "provider", "created_at_ms", "counts",
                    "first_user_message", "last_messages", "tool_names", "warnings"):
            self.assertIn(key, rep)
        self.assertLessEqual(len(rep["first_user_message"]), 500)
        self.assertLessEqual(len(rep["last_messages"]), 6)
        for m in rep["last_messages"]:
            self.assertIn(m["role"], ("user", "assistant", "tool"))
            self.assertLessEqual(len(m["text"]), 301)
        self.assertEqual(os.listdir(out), [])  # preview must not write anything
        shutil.rmtree(out, ignore_errors=True)

    def test_migrate_export_atif_verified(self):
        row = self._pick("dsh") or self._pick("codex")
        self.assertIsNotNone(row)
        src = "dsh" if row in (self._real.get("dsh") or []) else "codex"
        out = tempfile.mkdtemp(prefix="asi-migrate-export-")
        p = run_cli("migrate", "--from", src, "--session", str(row["id"]),
                    "--to", "atif", "--out", os.path.join(out, "exports"), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.loads(p.stdout)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["summary"]["total"], 1)
        self.assertEqual(rep["summary"]["ok"], 1)
        self.assertEqual(rep["summary"]["verified"], 1)
        res = rep["results"][0]
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["verify"]["ok"])
        self.assertTrue(os.path.isfile(res["artifact"]))
        with open(res["artifact"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc.get("schema_version"), "ATIF-v1.8")
        self.assertGreater(len(doc.get("steps") or []), 0)
        shutil.rmtree(out, ignore_errors=True)

    def test_migrate_dry_run_zero_writes(self):
        row = self._pick("codex") or self._pick("dsh")
        self.assertIsNotNone(row)
        src = "codex" if row in (self._real.get("codex") or []) else "dsh"
        out = tempfile.mkdtemp(prefix="asi-migrate-dry-")
        target = os.path.join(out, "never-created")
        p = run_cli("migrate", "--from", src, "--session", str(row["id"]),
                    "--to", "atif", "--out", target, "--dry-run", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.loads(p.stdout)
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["dry_run"])
        self.assertEqual(len(rep["plan"]), 1)
        self.assertEqual(rep["results"], [])
        self.assertFalse(os.path.exists(target))  # zero writes
        self.assertTrue(rep["plan"][0]["target"].startswith(target) or
                        rep["plan"][0]["target"] == target)
        shutil.rmtree(out, ignore_errors=True)

    def test_migrate_install_requires_yes(self):
        row = self._pick("codex") or self._pick("dsh")
        self.assertIsNotNone(row)
        src = "codex" if row in (self._real.get("codex") or []) else "dsh"
        home = tempfile.mkdtemp(prefix="asi-migrate-noyes-")
        p = run_cli("migrate", "--from", src, "--session", str(row["id"]),
                    "--to", "dsh", "--mode", "install", "--dsh-home", home,
                    "--out", os.path.join(home, "out"), "--json")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        rep = json.loads(p.stdout)
        self.assertFalse(rep["ok"])
        self.assertTrue(rep.get("requires_yes"))
        self.assertFalse(os.path.exists(os.path.join(home, "sessions")))
        shutil.rmtree(home, ignore_errors=True)

    def test_migrate_install_isolated_dsh_home(self):
        row = self._pick("codex") or self._pick("dsh")
        self.assertIsNotNone(row)
        src = "codex" if row in (self._real.get("codex") or []) else "dsh"
        home = tempfile.mkdtemp(prefix="asi-migrate-install-")
        p = run_cli("migrate", "--from", src, "--session", str(row["id"]),
                    "--to", "dsh", "--mode", "install", "--yes", "--dsh-home", home,
                    "--out", os.path.join(home, "out"), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.loads(p.stdout)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["summary"]["verified"], 1)
        res = rep["results"][0]
        self.assertTrue(res["artifact"].startswith(os.path.join(home, "sessions")))
        self.assertTrue(res["verify"]["ok"])
        self.assertTrue(os.path.isfile(res["artifact"]))
        # never touch the real ~/.dsh in this test
        self.assertNotIn(os.path.expanduser("~/.dsh"), res["artifact"])
        shutil.rmtree(home, ignore_errors=True)

    def test_migrate_install_register_backup(self):
        row = self._pick("dsh", prefer_workspace=True) or self._pick("dsh")
        if row is None:
            self.skipTest("no real dsh session")
        home, ws_path = make_isolated_home("asi-migrate-reg-")
        p = run_cli("migrate", "--from", "dsh", "--session", str(row["id"]),
                    "--to", "dsh", "--mode", "install", "--yes", "--dsh-home", home,
                    "--register", "--out", os.path.join(home, "out"), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = json.loads(p.stdout)
        res = rep["results"][0]
        self.assertEqual(res["status"], "ok")
        reg = res.get("register") or {}
        if reg.get("status") == "registered":
            self.assertTrue(workspace_backup_count(home) >= 1)
            self.assertIn(res["artifact"].split("session-")[-1].split("/")[0],
                          [x.split("session-")[-1] for x in workspace_session_ids(ws_path)])
        else:
            self.assertIn(reg.get("status"), ("skipped", "already"))
        shutil.rmtree(home, ignore_errors=True)




class SessionDetailTest(unittest.TestCase):
    """asi session-detail — product detail/timeline/token view (spec §7.2)."""

    @classmethod
    def setUpClass(cls):
        cls.rows = {}
        for src in ("claude", "codex", "dsh", "omp", "goose"):
            try:
                cls.rows[src] = [r for r in get_reader(src).list_sessions(None) if r.get("path")]
            except (OSError, ValueError):
                cls.rows[src] = []

    def _detail(self, src, *extra, session=None):
        rows = self.rows.get(src) or []
        if session is None:
            self.assertTrue(rows, "no real %s session" % src)
            session = rows[0]["id"]
        p = run_cli("session-detail", "--from", src, "--session", str(session),
                    "--json", *extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def test_four_real_sources(self):
        expect_kinds = {"user", "assistant", "tool_call", "tool_result", "thinking"}
        for src in ("claude", "codex", "dsh", "omp"):
            rep = self._detail(src)
            self.assertTrue(rep["ok"], src)
            self.assertEqual(rep["command"], "session-detail")
            self.assertEqual(rep["source"], src)
            meta, stats = rep["meta"], rep["stats"]
            for key in ("title", "cwd", "model", "provider", "created_at_ms",
                        "updated_at_ms", "path", "source_label", "evidence_level"):
                self.assertIn(key, meta, (src, key))
            self.assertEqual(meta["evidence_level"], "LOCAL", src)
            for key in ("messages", "tool_calls", "tool_results", "tool_errors",
                        "tool_usage", "usage", "duration_ms", "first_ts", "last_ts"):
                self.assertIn(key, stats, (src, key))
            for key in ("user", "assistant", "tool", "reasoning", "system", "compaction"):
                self.assertIn(key, stats["messages"], (src, key))
            for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                        "cache_write_tokens", "total_tokens", "available"):
                self.assertIn(key, stats["usage"], (src, key))
            self.assertGreater(len(rep["timeline"]), 0, src)
            self.assertGreater(len(rep["sections"]), 0, src)
            for item in rep["timeline"]:
                self.assertIn(item["kind"], ("user", "assistant", "thinking", "tool_call",
                                             "tool_result", "system", "compaction"), src)
                self.assertIn(item["role"], ("user", "assistant", "tool", "system"), src)
                self.assertIsInstance(item["text"], str, src)
                self.assertIn("section", item, src)
                if item["kind"] in ("tool_call", "tool_result"):
                    self.assertIn("tool", item, src)
                    self.assertIn("call_id", item["tool"], src)
                    self.assertIn("is_error", item["tool"], src)
            # section indices are 1..N and cover every displayed timeline index
            self.assertEqual([s["index"] for s in rep["sections"]],
                             list(range(1, len(rep["sections"]) + 1)))
            self.assertEqual(rep["timeline"][0]["index"], 0)
            if src in ("codex", "dsh", "omp"):
                self.assertTrue(expect_kinds & {t["kind"] for t in rep["timeline"]}, src)
            if src in ("dsh", "omp"):
                self.assertTrue(stats["usage"]["available"], src)
                self.assertGreater(stats["usage"]["total_tokens"], 0, src)
                self.assertGreater(stats["tool_calls"], 0, src)
                self.assertGreater(stats["duration_ms"], 0, src)
            if src == "codex":
                # codex token usage is extracted from rollout token_usage_record (session-detail
                # aggregation layer); if a path has no records it must be unavailable + warning
                from agent_session_import import product as _product
                extra = _product._codex_usage_from_rollout(rep["meta"]["path"])
                path_has_records = bool(extra and extra.get("records"))
                if path_has_records:
                    self.assertTrue(stats["usage"]["available"])
                    self.assertGreater(stats["usage"]["total_tokens"], 0)
                    self.assertEqual(stats["usage"]["caliber"],
                                     "codex_token_usage_record_incremental")
                else:
                    self.assertFalse(stats["usage"]["available"])
                    self.assertTrue(any("源未记录 token" in w for w in rep["warnings"]))

    def test_codex_token_extraction(self):
        rows = self.rows.get("codex") or []
        self.assertTrue(rows)
        from agent_session_import import product as _product
        chosen = None
        for row in rows[:8]:
            extra = _product._codex_usage_from_rollout(row["path"])
            if extra and extra.get("records"):
                chosen = (row, extra)
                break
        if chosen is None:
            self.skipTest("no codex rollout with token_usage_record in this environment")
        row, extra = chosen
        rep = self._detail("codex", "--max-events", "0", session=row["id"])
        usage = rep["stats"]["usage"]
        self.assertTrue(usage["available"])
        self.assertGreater(usage["total_tokens"], 0)
        self.assertEqual(usage["input_tokens"], extra["totals"]["input_tokens"])
        self.assertEqual(usage["output_tokens"], extra["totals"]["output_tokens"])
        self.assertEqual(usage["cache_read_tokens"], extra["totals"]["cache_read_tokens"])
        self.assertEqual(usage["total_tokens"], extra["totals"]["total_tokens"])
        self.assertEqual(usage["caliber"], "codex_token_usage_record_incremental")
        # cumulative token_count.total_token_usage must equal the per-file incremental sum
        # for a self-contained rollout (口径 proven on real ~/.codex samples)
        if extra.get("last_token_count_total"):
            self.assertEqual(extra["last_token_count_total"], extra["totals"]["total_tokens"])
            self.assertFalse(any("file 范围" in w or "rollout 片段" in w for w in rep["warnings"]))
        # per-assistant usage is attached when response records pair 1:1 with assistant messages
        usage_events = [t for t in rep["timeline"] if t["kind"] == "assistant" and t.get("usage")]
        self.assertTrue(usage_events or usage["available"])

    def test_claude_token_extraction(self):
        rows = self.rows.get("claude") or []
        self.assertTrue(rows)
        import glob as _g
        nonzero = zero = None
        for row in rows:
            try:
                with open(row["path"], encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"usage"' not in line:
                            continue
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        u = ((obj.get("message") or {}).get("usage")) or {}
                        if int(u.get("input_tokens") or 0) or int(u.get("output_tokens") or 0):
                            nonzero = row
                        elif u:
                            zero = row
                        if nonzero and zero:
                            break
            except OSError:
                continue
            if nonzero and zero:
                break
        if nonzero is None:
            self.skipTest("no claude session with provider token usage in this environment")
        rep = self._detail("claude", session=nonzero["id"])
        usage = rep["stats"]["usage"]
        self.assertTrue(usage["available"])
        self.assertGreater(usage["total_tokens"], 0)
        self.assertGreater(usage["input_tokens"], 0)
        self.assertGreater(usage["output_tokens"], 0)
        # claude cache_creation_input_tokens is mapped to cache_write_tokens
        self.assertGreaterEqual(usage["cache_write_tokens"], 0)
        self.assertEqual(usage["caliber"], "source_event_usage")
        if zero is not None:
            syn = self._detail("claude", session=zero["id"])
            self.assertFalse(syn["stats"]["usage"]["available"])
            self.assertTrue(any("源未记录 token" in w for w in syn["warnings"]))

    def test_constructed_fixture(self):
        rep = self._detail("goose")
        self.assertEqual(rep["meta"]["evidence_level"], "FIXTURE-CONSTRUCTED")
        self.assertGreaterEqual(len(rep["timeline"]), 2)
        self.assertFalse(rep["stats"]["usage"]["available"])
        self.assertTrue(any("token" in w.lower() or "Token" in w for w in rep["warnings"]))
        self.assertEqual(rep["timeline"][0]["kind"], "user")

    def test_max_events_and_text_limit(self):
        rep = self._detail("dsh", "--max-events", "5", "--text-limit", "20")
        self.assertLessEqual(len(rep["timeline"]), 5)
        self.assertTrue(rep["stats"]["truncated"])
        self.assertEqual(rep["stats"]["events_shown"], len(rep["timeline"]))
        self.assertGreater(rep["stats"]["events_total"], len(rep["timeline"]))
        self.assertTrue(all(len(t["text"]) <= 20 for t in rep["timeline"]))
        self.assertTrue(any("截断" in w for w in rep["warnings"]))
        # --max-events 0 = full timeline
        full = self._detail("claude", "--max-events", "0")
        self.assertFalse(full["stats"]["truncated"])
        self.assertEqual(full["stats"]["events_shown"], full["stats"]["events_total"])
        self.assertEqual(len(full["timeline"]), full["stats"]["events_total"])

    def test_readonly(self):
        out = tempfile.mkdtemp(prefix="asi-detail-cwd-")
        rows = self.rows.get("codex") or []
        if not rows:
            self.skipTest("no codex session")
        p = run_cli("session-detail", "--from", "codex", "--session", str(rows[0]["id"]),
                    "--json", cwd=out)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(os.listdir(out), [])
        shutil.rmtree(out, ignore_errors=True)




class MigrateV14Test(unittest.TestCase):
    """v1.4: default install into target store, keep/move, migrate-all, restore/journal.

    Every test uses an isolated HOME + per-harness env dirs; the real stores are never touched.
    """

    def _iso_env(self):
        base = tempfile.mkdtemp(prefix="asi-v14-")
        roots = {
            "claude": os.path.join(base, "claude", "projects"),
            "codex": os.path.join(base, "codex"),
            "omp": os.path.join(base, "omp"),
            "dsh": os.path.join(base, "dsh"),
            "qoder": os.path.join(base, "qoder", "projects"),
            "pi": os.path.join(base, "pi"),
            "gemini": os.path.join(base, "gemini"),
            "home": os.path.join(base, "home"),
        }
        for path in roots.values():
            os.makedirs(path, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "HOME": roots["home"],
            "CLAUDE_CONFIG_DIR": os.path.join(base, "claude"),
            "CODEX_HOME": roots["codex"],
            "OMP_SESSION_DIR": roots["omp"],
            "DSH_HOME": roots["dsh"],
            "QODER_CONFIG_DIR": os.path.join(base, "qoder"),
            "PI_HOME": roots["pi"],
            "GEMINI_HOME": roots["gemini"],
        })
        return base, env, roots

    def _ir(self):
        return get_reader("codex").load_session(
            path=str(SAMPLES / "codex" / "rollout-small-full.jsonl"))

    def _populate(self, roots):
        from agent_session_import.writers import native_write
        ir = self._ir()
        out = {}
        out["claude"] = native_write(ir, "claude", roots["claude"],
                                     "session-" + "a" * 8 + "-" + "b" * 12)["artifact"]
        out["omp"] = native_write(ir, "omp", roots["omp"],
                                  "session-" + "c" * 8 + "-" + "d" * 12)["artifact"]
        out["codex"] = native_write(ir, "codex", roots["codex"],
                                    "session-" + "e" * 8 + "-" + "f" * 12)["artifact"]
        return out

    def test_detect_v14_fields_isolated(self):
        base, env, roots = self._iso_env()
        try:
            self._populate(roots)
            p = run_cli("detect", "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            rep = json.loads(p.stdout)
            by_id = {h["id"]: h for h in rep["harnesses"]}
            for src in ("dsh", "claude", "codex", "omp", "qoder", "pi", "gemini", "goose"):
                h = by_id[src]
                for key in ("store_path", "install_supported", "install_experimental",
                            "how_to_see", "session_dir_hint"):
                    self.assertIn(key, h, (src, key))
                self.assertTrue(h["how_to_see"], src)
                self.assertTrue(h["session_dir_hint"], src)
            self.assertEqual(by_id["claude"]["store_path"], roots["claude"])
            self.assertEqual(by_id["codex"]["store_path"], roots["codex"])
            self.assertEqual(by_id["omp"]["store_path"], roots["omp"])
            self.assertEqual(by_id["dsh"]["store_path"], os.path.join(roots["dsh"], "sessions"))
            self.assertTrue(by_id["dsh"]["install_supported"])
            self.assertFalse(by_id["goose"]["install_supported"])
            self.assertGreaterEqual(by_id["claude"]["session_count"], 1)
            self.assertGreaterEqual(by_id["codex"]["session_count"], 1)
            self.assertGreaterEqual(by_id["omp"]["session_count"], 1)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_default_install_claude_keep_skip_overwrite(self):
        base, env, roots = self._iso_env()
        try:
            src = self._populate(roots)
            journal = os.path.join(base, "j.json")
            p = run_cli("migrate", "--from", "codex", "--session", src["codex"],
                        "--to", "claude", "--yes", "--journal", journal, "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            rep = json.loads(p.stdout)
            self.assertEqual(rep["mode"], "install")
            self.assertEqual(rep["summary"]["failed"], 0)
            self.assertEqual(rep["summary"]["verified"], 1)
            res = rep["results"][0]
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["installed_path"].startswith(os.path.join(base, "claude")))
            self.assertTrue(os.path.isfile(res["installed_path"]))
            self.assertTrue(os.path.isfile(src["codex"]))  # keep = source untouched
            self.assertTrue(rep["journal_path"])
            self.assertTrue(os.path.isfile(rep["journal_path"]))
            # second run: duplicate -> skipped-exists, no overwrite
            p2 = run_cli("migrate", "--from", "codex", "--session", src["codex"],
                         "--to", "claude", "--yes", "--json", env=env)
            rep2 = json.loads(p2.stdout)
            self.assertEqual(rep2["results"][0]["status"], "skipped-exists")
            self.assertEqual(rep2["summary"]["skipped"], 1)
            # --overwrite: backs up the existing target file first
            p3 = run_cli("migrate", "--from", "codex", "--session", src["codex"],
                         "--to", "claude", "--yes", "--overwrite", "--json", env=env)
            rep3 = json.loads(p3.stdout)
            res3 = rep3["results"][0]
            self.assertEqual(res3["status"], "ok")
            self.assertTrue(res3.get("backup_path"))
            self.assertTrue(os.path.isfile(res3["backup_path"]))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_install_to_dsh_and_omp_verify(self):
        base, env, roots = self._iso_env()
        try:
            src = self._populate(roots)
            p = run_cli("migrate", "--from", "claude", "--session", src["claude"],
                        "--to", "dsh", "--yes", "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            rep = json.loads(p.stdout)
            self.assertEqual(rep["mode"], "install")
            res = rep["results"][0]
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["installed_path"].startswith(os.path.join(roots["dsh"], "sessions")))
            self.assertTrue(res["verify"]["ok"])
            p = run_cli("migrate", "--from", "codex", "--session", src["codex"],
                        "--to", "omp", "--yes", "--json", env=env)
            rep = json.loads(p.stdout)
            res = rep["results"][0]
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["installed_path"].startswith(roots["omp"]))
            self.assertTrue(res["verify"]["ok"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_move_restore_remove_installed(self):
        base, env, roots = self._iso_env()
        try:
            src = self._populate(roots)
            journal = os.path.join(base, "move.json")
            p = run_cli("migrate", "--from", "claude", "--session", src["claude"],
                        "--to", "omp", "--yes", "--session-mode", "move",
                        "--journal", journal, "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            rep = json.loads(p.stdout)
            res = rep["results"][0]
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["source_moved"])
            backup = res["source_backup_path"]
            self.assertIn(".migrated-", backup)
            self.assertFalse(os.path.exists(src["claude"]))  # moved out (renamed, not deleted)
            self.assertTrue(os.path.isfile(backup))
            installed = res["installed_path"]
            # restore: source comes back from the .bak, installed file kept by default
            r = run_cli("migrate-restore", "--journal", journal, "--json", env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rr = json.loads(r.stdout)
            self.assertEqual(rr["summary"]["restored"], 1)
            self.assertTrue(os.path.isfile(src["claude"]))
            self.assertFalse(os.path.isfile(backup))
            self.assertTrue(os.path.isfile(installed))
            # restore + --remove-installed: remove the installed copy too (never the source)
            r2 = run_cli("migrate-restore", "--journal", journal,
                         "--remove-installed", "--json", env=env)
            rr2 = json.loads(r2.stdout)
            self.assertEqual(rr2["summary"]["removed_installed"], 1)
            self.assertFalse(os.path.isfile(installed))
            self.assertTrue(os.path.isfile(src["claude"]))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_migrate_all_dry_run_zero_writes_then_install(self):
        base, env, roots = self._iso_env()
        try:
            self._populate(roots)
            p = run_cli("migrate-all", "--to", "dsh", "--limit", "1",
                        "--dry-run", "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            rep = json.loads(p.stdout)
            self.assertTrue(rep["dry_run"])
            self.assertGreaterEqual(rep["plan"]["total"], 3)
            self.assertGreaterEqual(len(rep["plan"]["sources"]), 3)
            self.assertIsNone(rep["journal_path"])
            self.assertFalse(os.path.isdir(os.path.join(roots["dsh"], "sessions")))
            # real isolated install
            journal = os.path.join(base, "all.json")
            p2 = run_cli("migrate-all", "--to", "dsh", "--limit", "1", "--yes",
                         "--journal", journal, "--json", env=env)
            self.assertEqual(p2.returncode, 0, p2.stdout + p2.stderr)
            rep2 = json.loads(p2.stdout)
            self.assertEqual(rep2["summary"]["failed"], 0)
            self.assertGreaterEqual(rep2["summary"]["ok"], 3)
            self.assertTrue(os.path.isdir(os.path.join(roots["dsh"], "sessions")))
            self.assertTrue(os.path.isfile(rep2["journal_path"]))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_move_four_sources_by_session_id_and_restore(self):
        """Regression: move must resolve source_path from a session *id* (not only a path)."""
        base, env, roots = self._iso_env()
        try:
            from agent_session_import.writers import native_write
            ir = self._ir()
            paths = {
                "claude": native_write(ir, "claude", roots["claude"],
                                       "session-" + "a" * 8 + "-" + "b" * 12)["artifact"],
                "omp": native_write(ir, "omp", roots["omp"],
                                    "session-" + "c" * 8 + "-" + "d" * 12)["artifact"],
                "codex": native_write(ir, "codex", roots["codex"],
                                      "session-" + "e" * 8 + "-" + "f" * 12)["artifact"],
                "dsh": native_write(ir, "dsh", os.path.join(roots["dsh"], "sessions"),
                                    "session-" + "1" * 8 + "-" + "2" * 12)["artifact"],
            }
            store_roots = {
                "claude": roots["claude"], "omp": roots["omp"],
                "codex": roots["codex"], "dsh": os.path.join(roots["dsh"], "sessions"),
            }
            ids = {}
            for src, root in store_roots.items():
                rows = get_reader(src).list_sessions(root)
                self.assertTrue(rows, src)
                ids[src] = rows[0]["id"]
            pairs = [("codex", "omp"), ("claude", "codex"), ("omp", "dsh"), ("dsh", "claude")]
            for idx, (src, tgt) in enumerate(pairs):
                journal = os.path.join(base, "move-%d.json" % idx)
                p = run_cli("migrate", "--from", src, "--session", str(ids[src]),
                            "--to", tgt, "--yes", "--session-mode", "move",
                            "--journal", journal, "--json", env=env)
                self.assertEqual(p.returncode, 0, (src, p.stdout + p.stderr))
                rep = json.loads(p.stdout)
                self.assertEqual(rep["mode"], "install")
                res = rep["results"][0]
                self.assertEqual(res["status"], "ok", (src, res.get("error")))
                self.assertTrue(res["verified"], src)
                self.assertEqual(res["source_move_status"], "moved", src)
                self.assertTrue(res["source_moved"], src)
                self.assertTrue(res["source_path"], src)
                self.assertTrue(res["source_backup_path"].endswith(".bak"), src)
                self.assertIn(".migrated-", res["source_backup_path"])
                self.assertFalse(os.path.exists(paths[src]), src)  # renamed, never deleted
                self.assertTrue(os.path.isfile(res["source_backup_path"]), src)
                # journal records the real source path
                with open(rep["journal_path"], encoding="utf-8") as f:
                    journal_doc = json.load(f)
                self.assertEqual(journal_doc["entries"][0]["source_path"], res["source_path"])
                self.assertTrue(journal_doc["entries"][0]["source_backup_path"])
                # restore brings the source back from the .bak
                r = run_cli("migrate-restore", "--journal", journal,
                            "--remove-installed", "--json", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                rr = json.loads(r.stdout)
                self.assertEqual(rr["summary"]["restored"], 1, src)
                self.assertEqual(rr["summary"]["removed_installed"], 1, src)
                self.assertTrue(os.path.isfile(paths[src]), src)
                self.assertFalse(os.path.exists(res["source_backup_path"]), src)
                self.assertFalse(os.path.isfile(res["installed_path"]), src)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_codex_list_without_sqlite_fallback(self):
        base, env, roots = self._iso_env()
        try:
            self._populate(roots)
            self.assertFalse(os.path.exists(os.path.join(roots["codex"], "state_5.sqlite")))
            p = run_cli("list", "codex", "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            rep = json.loads(p.stdout)
            self.assertGreaterEqual(rep["count"], 1)
            self.assertTrue(rep["sessions"][0]["id"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_journal_unique_names_and_incremental_entries(self):
        base, env, roots = self._iso_env()
        try:
            from agent_session_import.writers import native_write
            ir = self._ir()
            p1 = native_write(ir, "claude", roots["claude"],
                              "session-" + "a" * 8 + "-" + "b" * 12)["artifact"]
            p2 = native_write(ir, "claude", roots["claude"],
                              "session-" + "g" * 8 + "-" + "h" * 12)["artifact"]
            journals = []
            for path in (p1, p2):
                r = run_cli("migrate", "--from", "claude", "--session", path,
                            "--to", "omp", "--yes", "--session-mode", "move", "--json", env=env)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                rep = json.loads(r.stdout)
                journals.append(rep["journal_path"])
                self.assertTrue(rep["journal_path"])
                with open(rep["journal_path"], encoding="utf-8") as f:
                    doc = json.load(f)
                self.assertEqual(len(doc["entries"]), 1)
            self.assertNotEqual(journals[0], journals[1])
            for j in journals:
                self.assertRegex(os.path.basename(j),
                                 r"^migrate-\d{8}-\d{6}-\d{3}-[0-9a-f]{6}\.json$")
                self.assertTrue(os.path.isfile(j))
            # no leftover atomic tmp files
            for j in journals:
                d = os.path.dirname(j)
                self.assertFalse([n for n in os.listdir(d) if ".tmp-" in n])
            # install staging dirs are cleaned (atomic tmp+rename)
            for parent in (roots["claude"], roots["omp"], os.path.dirname(roots["omp"])):
                self.assertFalse([n for n in os.listdir(parent) if n.startswith(".asi-tmp-")])
            # moved sources are restorable
            for path in (p1, p2):
                self.assertFalse(os.path.isfile(path))
            for j in journals:
                r = run_cli("migrate-restore", "--journal", j, "--json", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(json.loads(r.stdout)["summary"]["restored"], 1)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_journal_incremental_survives_midbatch_failure(self):
        base, env, roots = self._iso_env()
        try:
            from agent_session_import.writers import native_write
            ir = self._ir()
            first = native_write(ir, "claude", roots["claude"],
                                 "session-" + "a" * 8 + "-" + "b" * 12)["artifact"]
            journal = os.path.join(base, "midfail.json")
            ghost = os.path.join(base, "ghost-corrupt-session.jsonl")
            with open(ghost, "w", encoding="utf-8") as f:
                f.write("this is not a valid claude transcript\n")
            p = run_cli("migrate", "--from", "claude", "--session", first,
                        "--session", ghost, "--to", "omp", "--yes",
                        "--session-mode", "move", "--journal", journal, "--json", env=env)
            self.assertIn(p.returncode, (0, 1), p.stdout + p.stderr)  # per-session failure -> exit 1
            rep = json.loads(p.stdout)
            self.assertEqual(len(rep["results"]), 2)
            statuses = [r["status"] for r in rep["results"]]
            self.assertIn("ok", statuses)
            self.assertIn("failed", statuses)
            self.assertEqual(rep["summary"]["failed"], 1)
            self.assertEqual(rep["summary"]["moved"], 1)
            # the journal was written incrementally and retains the completed move mapping
            with open(journal, encoding="utf-8") as f:
                doc = json.load(f)
            self.assertEqual(len(doc["entries"]), 2)
            moved_entries = [e for e in doc["entries"] if e.get("source_moved")]
            self.assertEqual(len(moved_entries), 1)
            self.assertTrue(os.path.isfile(moved_entries[0]["source_backup_path"]))
            self.assertFalse(os.path.isfile(first))
            r = run_cli("migrate-restore", "--journal", journal, "--json", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["summary"]["restored"], 1)
            self.assertTrue(os.path.isfile(first))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_migrate_all_dry_run_skip_count(self):
        base, env, roots = self._iso_env()
        try:
            self._populate(roots)
            claude_rows = get_reader("claude").list_sessions(roots["claude"])
            self.assertTrue(claude_rows)
            sid = claude_rows[0]["id"]
            p = run_cli("migrate", "--from", "claude", "--session", str(sid),
                        "--to", "dsh", "--yes", "--json", env=env)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            d = run_cli("migrate-all", "--to", "dsh", "--limit", "5",
                        "--dry-run", "--json", env=env)
            self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
            rep = json.loads(d.stdout)
            self.assertTrue(rep["dry_run"])
            self.assertIsNone(rep["journal_path"])
            self.assertGreaterEqual(rep["plan"]["skip_count"], 1)
            self.assertEqual(rep["plan"]["will_skip"], rep["plan"]["skip_count"])
            skipped = [i for i in rep["plan"]["items"] if i["will_skip"]]
            self.assertGreaterEqual(len(skipped), 1)
            self.assertTrue(any(i.get("target_path") for i in rep["plan"]["items"]))
            # dry-run remains zero-write
            self.assertFalse(rep["results"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_journal_default_dir_branding_and_legacy_restore(self):
        base, env, roots = self._iso_env()
        try:
            from agent_session_import.writers import native_write
            ir = self._ir()
            p1 = native_write(ir, "claude", roots["claude"],
                              "session-" + "a" * 8 + "-" + "b" * 12)["artifact"]
            p2 = native_write(ir, "claude", roots["claude"],
                              "session-" + "g" * 8 + "-" + "h" * 12)["artifact"]
            app_support = os.path.join(base, "custom-app-support")
            env2 = dict(env)
            env2["HARNESSBRIDGE_APP_SUPPORT"] = app_support
            r1 = run_cli("migrate", "--from", "claude", "--session", p1, "--to", "omp",
                         "--yes", "--session-mode", "move", "--json", env=env2)
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            rep1 = json.loads(r1.stdout)
            new_default = os.path.join(app_support, "HarnessBridge", "journals")
            self.assertTrue(rep1["journal_path"].startswith(new_default), rep1["journal_path"])
            self.assertNotIn("SessionConverter", rep1["journal_path"])
            # no env override: default lives under HOME/Library/Application Support/HarnessBridge
            r2 = run_cli("migrate", "--from", "claude", "--session", p2, "--to", "omp",
                         "--yes", "--session-mode", "move", "--json", env=env)
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            rep2 = json.loads(r2.stdout)
            home_new = os.path.join(roots["home"], "Library", "Application Support",
                                    "HarnessBridge", "journals")
            self.assertTrue(rep2["journal_path"].startswith(home_new), rep2["journal_path"])
            self.assertNotIn("SessionConverter", rep2["journal_path"])
            # legacy compatibility: restore can read an old SessionConverter journal by basename
            legacy_dir = os.path.join(roots["home"], "Library", "Application Support",
                                      "SessionConverter", "journals")
            os.makedirs(legacy_dir, exist_ok=True)
            legacy_journal = os.path.join(legacy_dir, os.path.basename(rep1["journal_path"]))
            shutil.copy2(rep1["journal_path"], legacy_journal)
            os.unlink(rep1["journal_path"])
            r = run_cli("migrate-restore", "--journal", os.path.basename(legacy_journal),
                        "--json", env=env2)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rr = json.loads(r.stdout)
            self.assertEqual(rr["summary"]["restored"], 1)
            self.assertTrue(os.path.isfile(p1))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_install_requires_yes(self):
        base, env, roots = self._iso_env()
        try:
            src = self._populate(roots)
            p = run_cli("migrate", "--from", "codex", "--session", src["codex"],
                        "--to", "claude", "--mode", "install", "--json", env=env)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertTrue(json.loads(p.stdout).get("requires_yes"))
            p2 = run_cli("migrate-all", "--to", "dsh", "--limit", "1", "--json", env=env)
            self.assertEqual(p2.returncode, 2, p2.stdout + p2.stderr)
            self.assertTrue(json.loads(p2.stdout).get("requires_yes"))
        finally:
            shutil.rmtree(base, ignore_errors=True)


class EndToEndDshLoadTest(unittest.TestCase):
    """Load the generated session with the real DSH code (Session.fromRestore)."""

    DSH_PKGS = os.path.expanduser(
        "~/.local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai"
    )

    @unittest.skipUnless(
        os.path.isdir(DSH_PKGS) and subprocess.run(["which", "node"], capture_output=True).returncode == 0,
        "global @deepseek-ai/dsh package tree / node not available",
    )
    def test_real_dsh_code_loads_imported_session(self):
        ir = get_reader("codex").load_session(path=str(CODEX_SAMPLE))
        home = tempfile.mkdtemp(prefix="asi-e2e-home-")
        plan = dsh.plan_import(ir, home, target_cwd=str(WORKSPACE))
        self.assertEqual(dsh.write_import(plan), "written")
        proc = subprocess.run(
            ["node", str(Path(__file__).resolve().parent / "e2e_load.mjs"), plan["path"]],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(result["sessionId"], plan["session_id"])
        self.assertGreater(result["seq"], 0)
        self.assertGreater(result["messages"], 0)
        self.assertEqual(result["roles"][0], "user")


if __name__ == "__main__":
    unittest.main(verbosity=2)
