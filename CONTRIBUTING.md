# Contributing to HarnessBridge

Thanks for helping! HarnessBridge is a local-first macOS app + Python CLI for moving agent sessions between harnesses. Contributions are welcome in any of these areas:

- new harness readers/writers (with fixtures and evidence);
- format corrections as harnesses evolve;
- docs, translations (EN/zh-CN), screenshots;
- bug reports with reproducible steps and redacted logs.

**中文摘要**：欢迎贡献新 Harness adapter、格式修正、文档/翻译与 Bug 报告。请先读本文件与行为准则；提交前跑后端单元测试与 App `--self-test`；**测试必须使用临时 HOME/env，绝不能写真实用户 store**；提交 PR 时说明证据等级与限制。

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues are handled per [SECURITY.md](SECURITY.md).

## Repository layout

```text
tools/agent-session-import/asi              CLI entry point (Python 3 stdlib)
tools/agent-session-import/agent_session_import/
    readers/ writers/ targets.py common.py product.py cli.py …
tools/HarnessBridgeApp/                     SwiftUI app (SwiftPM); build.sh
samples/                                    sanitized fixtures/captures
docs/                                       architecture, CLI, compatibility, internals
.github/                                    CI, release, issue/PR templates
```

## Development setup

Requirements: macOS 13+ (or Linux for CLI-only work), Python 3.10+, Xcode Command Line Tools, optionally `zstd`.

```bash
git clone https://github.com/Larrtroffen/harnessbridge.git
cd harnessbridge

# CLI smoke
python3 tools/agent-session-import/asi --version
python3 tools/agent-session-import/asi --help
python3 tools/agent-session-import/asi detect --json

# App build (writes nothing to real harness stores)
cd tools/HarnessBridgeApp
swift build -c release
./build.sh
open dist/HarnessBridge.app
```

## Tests

### Backend unit tests

```bash
python3 -m unittest discover -s tools/agent-session-import/tests -p 'test_*.py' -v
```

- Tests must be **hermetic**: temporary `HOME` plus env-overridden stores (`DSH_HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `OMP_SESSION_DIR`, `QODER_CONFIG_DIR`, `PI_HOME`, `GEMINI_HOME`, `GOOSE_PATH_ROOT`).
- Never write to a real user store, never assert on a developer's local session counts.
- Prefer fixtures under `tools/agent-session-import/tests/fixtures/` or `samples/`.

### App self-test / diagnose

```bash
APP=tools/HarnessBridgeApp/dist/HarnessBridge.app/Contents/MacOS/HarnessBridge
"$APP" --self-test     # 31 checks; install/move/restore cases use an isolated HOME
"$APP" --diagnose
```

The self-test depends on the CLI and its fixtures. On machines with real harness stores it also exercises local detection; CI treats the self-test as a non-blocking smoke test because hosted runners have no harness data.

## Adding a harness adapter

1. **Reader** (`agent_session_import/readers/<id>.py`): implement default root, `list_sessions(root)`, `load_session(...)`, register in the harness catalog.
2. **Writer** (`agent_session_import/writers/`): emit the native layout; only declare `install_supported`/`install_experimental` when you can verify the written artifact by reading it back.
3. **Fixture**: add a sanitized, redistributable sample under `samples/` (or the test fixtures directory) and document provenance/license.
4. **Evidence**: update [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) and the coverage ledger/catalog with the new harness: read/write capability, evidence level (NATIVE/REAL-LOCAL/COLLECTED/FIXTURE/CONSTRUCTED), lossy notes.
5. **Tests**: unit tests for parse/write round-trips using the fixture; if direct install is supported, add an isolated install+verify test.
6. **Docs**: mention the harness in README support table if it's stable, or in COMPATIBILITY only if experimental.

## Privacy and data rules

- **Never commit real user sessions, API keys, credentials, or absolute personal paths** from a real store. Use `~/`-relative examples and redact IDs/messages.
- Fixtures must be synthetic or explicitly licensed/redistributable; state their source.
- If you find sensitive content in the repository, report it privately and do not open a public issue with the content.

## Pull requests

- Keep changes focused; one topic per PR when possible.
- Describe: what changed, why, how it was tested, and doc/evidence updates.
- Run the backend tests and (if app code changes) `./build.sh` + `--self-test` before submitting.
- Do not reformat unrelated files; avoid large binary additions without discussion.
- By contributing you agree your contributions are licensed under the project's MIT License.

## Commit messages

Use short imperative summaries, e.g. `cli: add qwen-code reader`, `app: fix move result status`, `docs: clarify gatekeeper step`. Reference issue numbers when relevant.

## Reporting bugs

Use the GitHub issue templates. Include:
- macOS version, Apple/Intel, app version (`HarnessBridge → About` or `--version`);
- the command/flows attempted (redacted);
- relevant error output or `--json` excerpts, with personal paths/ids redacted;
- whether it concerns a real store write (that's high priority).

Please do **not** attach real session files; a minimal synthetic fixture is ideal.

## Releases

Maintainers tag `v*`; GitHub Actions builds the arm64 app, ad-hoc signs it, creates `HarnessBridge-<version>-macos-arm64.dmg`/`.zip`, publishes SHA-256 sums, and drafts a release. See `.github/workflows/release.yml` and `RELEASE_NOTES/`.

## Questions

Open a discussion/issue, or read the [FAQ](docs/FAQ.md). Thanks for making session migration safer for everyone.
