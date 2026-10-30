# Compatibility & evidence

HarnessBridge deliberately separates three numbers that are easy to confuse:

| Metric | Value | Meaning |
|---|---|---|
| **Protocol coverage** | **40 / 40** | Distinct harness formats with an adapter and at least FIXTURE / CONSTRUCTED / REAL-LOCAL evidence (the project's original 30–40 target) |
| **Real-conversation coverage** | **21 / 40** | Formats validated with real (or collected) conversations: NATIVE 5 + COLLECTED 14 + REAL-LOCAL 1 + COLLECTED-SPARSE 1. FIXTURE/CONSTRUCTED do **not** count here |
| **Shipped surfaces** | **35 import sources / 31 writer targets** | What the current `asi` CLI exposes (`asi --help` lists the exact enum values) |

The authoritative, generated numbers live in [the coverage ledger](coverage-ledger.md); per-batch evidence is in [the interop protocol](atif-interop-protocol.md) and `docs/usage.md` §8–§15. The ledger is machine-checked (`tools/coverage-report.py --check`).

> We do not claim "100% lossless" and we do not claim every covered harness can be resumed natively. Coverage means an adapter and evidence exist; native *loadability* is a stricter, separately tracked property.

## Direct-install support

Direct install writes into a harness's own local session store. Support level is returned by `asi detect --json` (`install_supported` / `install_experimental`).

| Target | Store (env override) | Level | After migrating |
|---|---|---|---|
| **DeepSeek Harness (DSH)** | `~/.dsh/sessions` (`DSH_HOME`) | ✅ Stable | Restart DSH; optional `--register` puts it in a project |
| **Claude Code** | `~/.claude/projects` (`CLAUDE_CONFIG_DIR`) | ✅ Stable | Restart Claude Code; `claude --resume` |
| **OMP** | `~/.omp/agent/sessions` (`OMP_SESSION_DIR`) | ✅ Stable | Restart OMP |
| **Codex** | `~/.codex` (`CODEX_HOME`) | 🧪 Experimental | `codex resume`; the thread index may need rebuilding |
| **Qoder** | `~/.qoder/projects` (`QODER_CONFIG_DIR`) | 🧪 Experimental | Restart Qoder |
| **Pi** | `~/.pi/agent/sessions` (`PI_HOME`) | 🧪 Experimental | Restart Pi |
| **Gemini CLI** | `~/.gemini/tmp` (`GEMINI_HOME`) | 🧪 Experimental | Restart Gemini CLI; `/resume` |
| **Goose** | SQLite (`GOOSE_PATH_ROOT`) | 📦 Export-only | Use `--mode export` |

Experimental means: the writer follows our best understanding of the native layout and is verified by reading the artifact back, but the vendor may change formats/indexes and the target tool may require a restart or index rebuild. Treat it as best-effort, and keep a backup.

## Evidence levels

| Level | Definition | Counts as “real”? |
|---|---|---|
| **NATIVE** | Real local install + real local store + native load/resume check (L3) | ✅ |
| **REAL-LOCAL** | Real local install + real local sessions, native load not verified | ✅ |
| **COLLECTED** | Real user conversations from open-source `traj-session/1` captures (B2 L0–L2 + DSH L3) | ✅ |
| **COLLECTED-SPARSE** | Real capture but very sparse sample | ✅ (flagged) |
| **FIXTURE** | Upstream public fixture in native format; F-level verification | ❌ |
| **FIXTURE-LOW** | Low-confidence/derived fixture | ❌ |
| **CONSTRUCTED** | Format constructed from documentation/spec, no upstream sample | ❌ |

Per-batch summary (from the ledger):

| Batch | Scope | Evidence | Result |
|---|---|---|---|
| B1 | Claude Code, Codex, OMP, Qoder, DeepSeek Harness → ATIF → DSH | NATIVE + real local | L3 pass for the main 5-harness matrix |
| B2 | OSS `traj-session/1` captures (15+ labels) → IR → ATIF → harnesses | COLLECTED (+SPARSE) | B2 L0–L2, DSH L3 |
| B3 | 6 native fixture adapters | FIXTURE | matrix pass |
| B4 | 8 adapters | FIXTURE / FIXTURE-LOW / CONSTRUCTED | matrix pass |
| B5 / B5.1 | 17 rows, REAL-LOCAL + constructed upgrades | REAL-LOCAL 2, FIXTURE 3, FIXTURE-LOW 2, CONSTRUCTED 10, COLLECTED-SPARSE 1 | **pass 16 / partial 1 / fail 0** (`fx` partial: orphan tool_results + text-only writer, declared lossy) |

## Harness coverage by evidence

**Native local readers (real local store):** Claude Code, Codex, OMP, Qoder, DeepSeek Harness.

**Real-local writers:** Gemini CLI, Pi.

**Collected / OSS-captured (group):** OpenHands, Gemini CLI, Codex, Claude Code, and other `traj-session/1` labels in `samples/batch2/` (see `docs/batch2-samples.md`).

**Fixture / constructed coverage (protocol adapters):** Copilot CLI, Aider, Cursor CLI, Qwen Code, OpenClaw, Kimi Code, Grok Build, Factory Droid, Antigravity (reader only), Hermes, Devin CLI, OpenCode, Goose, Continue, JetBrains Junie, Kiro CLI, Crush, Cline, Roo Code, Kilo Code, Codebuff, Mistral Vibe, CodeBuddy, FX (`fx`), mini-swe-agent, Zed (research), plus ATIF / IR as generic targets.

This list is a summary, not the canonical count. The canonical per-harness evidence rows — including the `partial` flags and fixture provenance — are maintained in [`docs/coverage-ledger.md`](coverage-ledger.md), [`docs/harness-catalog.md`](harness-catalog.md) and the batch documents.

## Known limitations

### Conversion fidelity

- **Not every harness feature has an ATIF/IR equivalent.** Images/audio content, harness-private system events, some tool-result pairings and vendor-specific metadata may be dropped or represented as text; conversions can be marked `lossy` with warnings.
- **`fx` (Vercel Labs FX)** is a declared partial: orphan `tool_results` cannot be represented and the writer persists text events only.
- **Token accounting is source-dependent.** Some harnesses do not expose usage; HarnessBridge reports `usage.available=false` instead of estimating.
- **ATIF is a trajectory log, not a resume format.** Migrated sessions provide conversation history, not the source agent's private runtime state.

### Direct install / move

- **DSH move** renames the main `session.v4.jsonl.zstd`; the session directory and journal entry are kept as recovery evidence.
- **Directory / multi-file source sessions** are reported `source_move_status: "unsupported"` and left completely untouched.
- **Move depends on knowing the source file path.** Counts and paths come from the harness reader; exotic stores may be unreadable and are skipped rather than guessed.
- **Experimental targets** (Codex/Qoder/Pi/Gemini) may require a target-side restart, index rebuild or may change behaviour between harness versions.
- **Overwrites** are opt-in (`--overwrite`) and back up the previous target as `*.asi-backup-<timestamp>`; the default is skip.
- **Concurrent writers** to the same target session are not locked against each other; avoid running two migrations into the same target store simultaneously.

### Platform

- **Prebuilt DMG**: Apple Silicon (arm64), macOS 13+. Ad-hoc signed, not notarized. Intel Macs must build from source.
- **CLI**: Python 3.10+ stdlib; optional `zstd` CLI. Windows untested/uncovered by CI.
- **Harness versions drift.** Formats are reverse-engineered; a vendor update can break a reader/writer. Issues with a format/version are very welcome (include a redacted fixture when possible).

## Testing policy

- All install/move/restore tests run against a **temporary HOME + env-overridden stores**; the suite asserts that real stores are untouched.
- Evidence artifacts (matrix JSON) and fixtures are tracked under `tools/agent-session-import/tests/` and `samples/`.
- App `--self-test` covers isolated install/keep/move+restore/migrate-all dry-run/cancellation; see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Roadmap impact

Missing native writers (e.g. Zed, Antigravity writer) and real fixtures (Windsurf, Kilo real store, CodeBuddy upstream) are tracked as future work in the coverage ledger's remaining-gaps section. If you can supply a sanitized real sample, that is the fastest way to promote a harness from FIXTURE to REAL.
