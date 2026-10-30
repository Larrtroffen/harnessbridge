# CLI reference — `asi`

`asi` (Agent Session Import) is the Python 3 command-line engine behind HarnessBridge. It reads, converts, migrates, verifies and restores agent sessions. The macOS app calls the same CLI; every JSON envelope shown here is what the app consumes.

> This page is a practical cheat sheet. For exhaustive field names, adapter notes and batch-by-batch acceptance data see [`usage.md`](usage.md) (Chinese, internal reference) and [`atif-interop-protocol.md`](atif-interop-protocol.md).

## Requirements

- Python **3.10+** (standard library only — no `pip install`).
- Optional: `zstd` CLI (`brew install zstd`) for compressed DeepSeek Harness artifacts; use `--no-zstd` to skip.
- macOS/Linux. The CLI has no GUI/app dependency. Windows is not covered by CI.
- Run from the repository root or use the absolute path:

```bash
python3 tools/agent-session-import/asi --help
python3 tools/agent-session-import/asi --version   # asi 0.1.0
```

All commands accept `--json`; human-readable output is the default. Paths in JSON are absolute, real local paths.

## Environment overrides

Every store root is environment-overridable — this is how the test suite avoids real user data and how you can point the CLI at a copied store:

| Variable | Used by | Default |
|---|---|---|
| `HOME` | journal/App-support defaults | your home |
| `DSH_HOME` | DeepSeek Harness | `~/.dsh` |
| `CLAUDE_CONFIG_DIR` | Claude Code | `~/.claude` |
| `CODEX_HOME` | Codex | `~/.codex` |
| `OMP_SESSION_DIR` | OMP | `~/.omp/agent/sessions` |
| `QODER_CONFIG_DIR` | Qoder | `~/.qoder` |
| `PI_HOME` | Pi | `~/.pi` |
| `GEMINI_HOME` | Gemini CLI | `~/.gemini` |
| `GOOSE_PATH_ROOT` | Goose | `~/.local/share/goose` |

## Command map

| Command | Purpose | Writes? |
|---|---|---|
| `asi detect` | Discover harnesses, store paths, session counts, install capabilities | No |
| `asi list` | List importable sessions of a source | No |
| `asi preview` | Preview a session (recent messages) | No |
| `asi session-detail` | Full timeline/sections/usage for the app detail view | No |
| `asi convert` | Convert/export to DSH JSONL, ATIF, IR or a native format | Only with `--out` / `--install --yes` |
| `asi import` | Import into a DSH home (`--dsh-home`) | Yes (`--yes`) |
| `asi migrate` | Product-level migration: convert → install → verify (export fallback) | Yes (install: `--yes`) |
| `asi migrate-all` | One-click migration from all other harnesses to one target | Yes (`--yes`) |
| `asi migrate-restore` | Undo source moves recorded in a journal | Yes (reverse renames) |
| `asi verify` | Validate DSH artifacts | No |
| `asi matrix*` | Run interop regression matrices (maintainers) | No (writes reports under tests/artifacts) |

## `asi detect`

```bash
asi detect --json            # fast filesystem scan (default, <2s)
asi detect --json --deep     # reads indexes/content; slower but complete
```

Each harness entry includes:

```json
{
  "id": "dsh",
  "name": "DeepSeek Harness",
  "detected": true,
  "session_count": 246,
  "path": "/Users/you/.dsh/sessions",
  "capabilities": {"export": true, "install": true, "install_experimental": false, "preview": true},
  "store_path": "/Users/you/.dsh/sessions",
  "install_supported": true,
  "install_experimental": false,
  "how_to_see": "重启 DeepSeek Harness 后可在会话列表看到…",
  "session_dir_hint": "sessions/<projectKey(cwd)>/<session-id>/session.v4.jsonl.zstd"
}
```

Use `store_path` + `install_supported` to decide where a migration will write, and `how_to_see` to tell users how to open the migrated session.

## `asi list`

```bash
asi list claude --json
asi list codex --limit 20 --json
asi list dsh --json --dsh-home /tmp/isolated-dsh
```

Envelope: `{ "ok": true, "command": "list", "source": "claude", "count": 3, "sessions": [{ "id", "title", "cwd", "path", "lines", "model", "created_at_ms", "updated_at_ms" }] }`.

`--root` overrides the source root (useful for copied/detached stores). Codex threads can include archived ones via `--include-archived`.

## `asi preview` / `asi session-detail`

```bash
asi preview --from claude --session <id> --json
asi session-detail --from qoder --session <id> --json --max-events 2000 --text-limit 400
```

- `preview` returns a compact recent-message summary (read-only).
- `session-detail` returns stable fields for the app's detail page: session metadata, ordered timeline, grouped sections, paired tool calls/results, and token usage where the source provides it (`usage.available=false` when the source does not — we never invent token counts).

## `asi convert` (export/convert)

```bash
# to a folder (safest path; no harness store touched)
asi convert --from codex --session <id> --to atif --out ~/Documents/HarnessBridgeOut --json
asi convert --from claude --all --to dsh --out /tmp/export --limit 5 --json

# optionally install into the target store (DSH currently, requires confirmation)
asi convert --from claude --session <id> --to dsh --install --yes --install-root /tmp/isolated-dsh --json
```

`--to` accepts `dsh`, `atif`, `ir` or a native writer name (see `asi convert --help` for the exact list; `antigravity` has no writer). `--no-zstd` skips the compressed DSH artifact.

## `asi import`

Writes sessions into a **DSH home** using the legacy `import` path:

```bash
asi import --from codex --session <id> --dsh-home ~/.dsh --dry-run --json
asi import --from codex --session <id> --dsh-home ~/.dsh --yes --register --json
```

`--dry-run` prints the plan only; `--overwrite` replaces an existing session file; `--register` adds ids to `workspace.json` sessionIds.

## `asi migrate` — the product-level migration

Default mode is **install** when the target supports it; otherwise export. Real-store installs require `--yes`.

```bash
# 1) inspect capabilities first
asi detect --json

# 2) dry-run: plan only, zero writes
asi migrate --from claude --session <id> --to dsh --dry-run --json

# 3) direct install (keep source)
asi migrate --from claude --session <id> --to dsh --yes --register --json

# 4) direct install + move source (recoverable; only after verified install)
asi migrate --from codex --session <id> --to omp --yes --session-mode move --json

# 5) export instead (advanced)
asi migrate --from codex --session <id> --to atif --mode export --out /tmp/export --json
```

Key flags:

| Flag | Meaning |
|---|---|
| `--mode install` / `--mode export` | Direct target store vs folder export (default auto: install if supported) |
| `--session-mode keep` / `move` | Keep source (default) or rename it to `*.migrated-<ts>.bak` after verified install |
| `--journal <path>` | Where to write the recovery journal (authoritative default is returned as `journal_path`; v1.5.0 backend default: `~/Library/Application Support/HarnessBridge/journals/migrate-<ts>-<rand>.json`) |
| `--overwrite` | Back up an existing same-id target (`*.asi-backup-<ts>`) and replace it (default: skip) |
| `--register` | DSH only: also register the session in `workspace.json` |
| `--dry-run` | Print plan only — zero writes, no journal |
| `--yes` | Required for install writes |
| `--session <id-or-path>` (repeatable) / `--all` / `--all-limit N` | Session selection |
| `--root <path>` | Override source root (testing/copied stores) |
| `--target-cwd` / `--fallback-cwd` | Override/fallback cwd mapping for the target |

Example result item (trimmed):

```json
{
  "source_session_id": "b59c58e1-…",
  "status": "ok",
  "verified": true,
  "installed_path": "/Users/you/.dsh/sessions/…/session.v4.jsonl.zstd",
  "source_path": "/Users/you/.claude/projects/…/b59c58e1-….jsonl",
  "source_moved": true,
  "source_move_status": "moved",
  "source_backup_path": "/Users/you/.claude/projects/…/b59c58e1-….jsonl.migrated-1793387793719.bak",
  "journal_path": "/Users/you/Library/Application Support/HarnessBridge/journals/migrate-20261030-191633-719-d25429.json"
}
```

Safety behaviour:
- `skipped-exists` when the target already has the same session id (unless `--overwrite`);
- failure rolls back files/directories created by this run and restores overwrite backups;
- `source_move_status` is `moved` / `unsupported` / `failed` — a requested move that cannot happen is reported as not-moved, never faked;
- every completed session is appended to the journal atomically, so interrupted batches keep their restore map.

## `asi migrate-all`

```bash
# preview (zero writes)
asi migrate-all --to dsh --from claude,codex --limit 10 --since-days 30 --session-mode keep --dry-run --json

# execute (requires --yes)
asi migrate-all --to dsh --limit 10 --session-mode keep --yes --json
```

- Sources default to **all other detected harnesses that have sessions**; `--from id1,id2` narrows them.
- `--limit` is *per source*; `--since-days` filters by session update time.
- Returns `plan.sources[]`, `plan.total`, `plan.skip_count`/`will_skip` (dry-run), `results[]`, `summary{total,ok,failed,skipped,moved,verified}` and `journal_path`.
- Duplicates are skipped; failures do not abort the batch; cancellation (SIGTERM) keeps a valid journal for completed sessions.

## `asi migrate-restore`

```bash
asi migrate-restore --journal /path/to/journal.json --dry-run --json
asi migrate-restore --journal /path/to/journal.json --json
asi migrate-restore --journal /path/to/journal.json --remove-installed --json
```

Reverses the source rename (`*.migrated-*.bak` → original path). By default the installed target copy is **kept**; `--remove-installed` deletes only the file installed by that journal. Results report `restored` / `already-restored` / `skipped-original-exists` / `missing-backup` / `failed`.

## `asi verify`

```bash
asi verify ~/.dsh/sessions/<project>/<session-id>
asi verify /tmp/artifact-root --json
```

Validates DSH artifacts (header, sequence, surfaceOp, tool pairing). Exit code 0 means clean; JSON contains per-check details.

## Exit codes and automation

- `0` — success (including plans and empty result sets).
- non-zero — failure. `migrate`/`migrate-all` without `--yes` return a `requires_yes` error and exit non-zero (2).
- stdout carries JSON when `--json` is passed (a couple of refusal paths print a short human sentence first — tolerate a leading line in strict parsers), stderr carries diagnostics.
- `--dry-run` never modifies the filesystem; safe to run in CI.

## Common recipes

```bash
# Back up a store before trying a migration (read-only copy)
cp -R ~/.dsh/sessions /tmp/dsh-backup-$(date +%s)

# Inspect everything before writing
asi detect --json | python3 -m json.tool
asi list claude --json | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["sessions"]))'

# Move one session and be able to undo it
asi migrate --from claude --session <id> --to omp --yes --session-mode move --json
# …later, using the returned journal_path
asi migrate-restore --journal "<journal_path>" --json
```

See also: [Compatibility](COMPATIBILITY.md) · [FAQ](FAQ.md) · [Architecture](ARCHITECTURE.md)
