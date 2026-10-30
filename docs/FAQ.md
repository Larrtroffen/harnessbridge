# FAQ — Frequently asked questions

## General

### What exactly does HarnessBridge do?

It moves an **agent session's conversation history** from one AI coding harness to another. For example: read a Claude Code session, convert it through the open ATIF v1.8 format, and write it into DeepSeek Harness's local store — after which DSH can list it as a session.

It is not a cloud sync service, not a proxy, and not an account/backup product. Everything is local files.

### Does it modify or delete my original sessions?

By default, **no** — sources are read-only.

With `--session-mode move` (opt-in, second confirmation in the app), the source session file is **renamed** to `*.migrated-<timestamp>.bak` in the same directory *after* the target install has been verified. It is never deleted. You can restore it at any time (`asi migrate-restore --journal …` or the app's restore button).

### Is conversion lossless?

Not always. The hub format (ATIF v1.8) cannot represent every harness-specific concept (images/audio content, private events, some tool-call pairings, vendor metadata). Conversions report `lossy` entries and warnings instead of pretending otherwise. Simple text/tool sessions round-trip well; rich sessions may lose details.

### What is ATIF and why does it matter?

ATIF = **Agent Trajectory Interchange Format**, an open specification from the Harbor project (RFC 0001, v1.8, Apache-2.0). Using a public hub format means converted history is inspectable and not locked to this tool's internal model. Note: ATIF is a *trajectory log* format, not an agent *resume/checkpoint* format.

## Installation & first launch

### macOS says it cannot verify the developer / app is damaged

The release DMG is **ad-hoc signed, not Apple-notarized** (no Developer ID yet). Gatekeeper blocks it on first launch. Options:

- Right-click the app → **Open** → Open, or
- Remove the quarantine flag:
  ```bash
  xattr -dr com.apple.quarantine /Applications/HarnessBridge.app
  ```

If you prefer to avoid the warning, build from source. We plan notarization in a future release.

### Requirements?

- App: macOS 13+, Apple Silicon for the prebuilt DMG; build from source on Intel.
- CLI: Python 3.10+ (stdlib only), optional `zstd` CLI for DSH artifacts.

### Why is the DMG only arm64? / Can I run it on Intel?

The public prebuilt is `HarnessBridge-1.5.0-macos-arm64.dmg` (CI builds on Apple-silicon runners). Intel Macs can `git clone` and run `./build.sh` locally with Xcode Command Line Tools.

## Using the app

### I migrated a session but the target tool doesn't show it

- **DeepSeek Harness**: restart DSH. If you used “register to project”, restart and open the corresponding project/workspace.
- **Claude Code**: restart `claude`, then `claude --resume`.
- **OMP / Qoder / Pi**: restart the tool.
- **Gemini CLI**: restart, then `/resume`.
- **Codex**: `codex resume`; Codex may need to rebuild its thread index (experimental target).

Also check the result page: `installed_path`, `verified` and per-item `status` tell you exactly what was written. `skipped-exists` means the target already had that session id (use `--overwrite` if you really want to replace it; it backs up first).

### The app says an item was skipped — why?

The target store already contains a session with the same id. The default policy is **skip, never overwrite**. Use the advanced overwrite option / `--overwrite` to replace; the CLI then renames the old target file to `*.asi-backup-<timestamp>` first.

### How do I undo a “move” migration?

Open **迁移历史 (History)** or the result page and click **恢复被移出的会话**, or run:

```bash
asi migrate-restore --journal "<journal path from the result>" --json
```

This renames `*.migrated-*.bak` back to the original path. The installed target copy is kept by default; add `--remove-installed` to remove it as well.

### Where are data, history and journals stored?

- App data (history, detect cache, app-side journals): `~/Library/Application Support/HarnessBridge/`
- CLI/backend migration journals: use the `journal_path` returned by the command; in v1.5.0 the backend default is `~/Library/Application Support/HarnessBridge/journals/` (legacy companion folder, planned to be renamed to HarnessBridge)
- Default export folder: `~/Documents/HarnessBridgeOut/`
- CLI export defaults: `./asi-out/`, `./asi-migrate/` (current working directory)
- Moved source backups: next to the original session file, `*.migrated-*.bak`

The app has **no network access and no telemetry**; everything stays on your Mac.

### How do I uninstall / clean up completely?

1. Quit HarnessBridge and trash `/Applications/HarnessBridge.app`.
2. Optionally delete: `~/Library/Application Support/HarnessBridge/` and `~/Documents/HarnessBridgeOut/`.
3. If you used move and want the original sessions back, restore them first from the app history / journal — **do not delete the journals or `.bak` files before restoring**.
4. Migrated sessions that were installed into a harness store remain there until you remove them with that tool (or `asi migrate-restore --remove-installed`).

## CLI & automation

### Do the app and CLI behave the same?

Yes — the app is a front-end over the same CLI. Safety rules (`--yes`, dry-run, backups, journal) are implemented once in the CLI.

### `migrate` without `--yes` fails. Is that a bug?

No. Any real-store write requires explicit confirmation. `--dry-run` is the way to preview. A missing `--yes` returns a `requires_yes` error and a non-zero exit code; it does not write anything.

### How do I test safely without touching my real stores?

Use `--dry-run`, and/or point the CLI at isolated directories with env overrides:

```bash
export HOME=/tmp/hb-test
export DSH_HOME=$HOME/.dsh
export CLAUDE_CONFIG_DIR=$HOME/.claude
asi detect --json
```

This is exactly how the test suite runs. Never commit or share secrets/personal paths from real stores.

### A migration was cancelled or interrupted. Is my data still recoverable?

The journal is written atomically and incrementally: every completed session is already recorded. Completed source moves keep their `.bak` mapping and can be restored. Re-running the migration skips sessions that are already installed (or use `--overwrite` to refresh).

### Why does the detail page say token usage is unavailable?

The source harness did not expose usage for that session (or it is a synthetic/imported artifact with no token accounting). HarnessBridge reports `usage.available=false` rather than estimating numbers.

## Compatibility & contributions

### Why do some targets say “experimental”?

The writer follows our best understanding of that tool's local format and verifies by reading the artifact back, but the vendor can change formats/indexes, and the tool may need a restart or index rebuild. Experimental = best-effort; keep backups and treat version updates with care.

### A harness isn't supported. Can you add it?

Yes — that's the main contribution path. Add a reader/writer plus a sanitized fixture, document evidence/limitations in `docs/COMPATIBILITY.md`, and send a PR. Redacted real samples are the fastest way to promote a format from FIXTURE to REAL.

### Is this the same as `mandyyyyii/HarnessBridge` on GitHub?

No. This project is `Larrtroffen/harnessbridge`; the other repository is an unrelated project that happens to share the name. There is no affiliation.

### What license is the project under? Can I use it commercially?

MIT. See [LICENSE](../LICENSE). Harness names/logos are trademarks of their owners; the MIT license covers this project's code and docs, not third-party marks or fixtures. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

### Windows support?

The CLI is pure Python and may run on Windows, but it is untested and not covered by CI (paths/quoting differ). The app is macOS-only.
