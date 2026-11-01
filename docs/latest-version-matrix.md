# Latest-version isolation test — SSH Home (2026-11-01)

> Purpose: close the "we only tested upstream fixtures" gap by installing missing harness CLIs in an
> **isolated `$HOME` on a remote Ubuntu 22.04 x86_64 host** and confirming the **latest** versions.
> Everything below is version/store-format evidence. **It does not raise real-user-session coverage**
> unless explicitly stated; mock-model sessions are labelled **LOCAL-SMOKE** and are not REAL.

## 1. Installed and version-confirmed

All installs used `HOME=/tmp/hb-harness-home` (no sudo, no writes to `/Workspace` or `/Data`).
"Latest" was checked against npm `@latest`, GitHub releases, PyPI JSON, or the official installer's
stable channel on **2026-11-01**.

| Harness | Installed / latest | Latest source | Store path (current) | Notes |
|---|---|---|---|---|
| Qwen Code | **0.26.5** | `@qwen-code/qwen-code` npm @latest | `~/.qwen/projects/*/chats/*.jsonl` | **latest store parsed** (LOCAL-SMOKE) |
| OpenCode | **1.19.5** | `opencode-ai` npm @latest | `~/.local/share/opencode/opencode.db` (SQLite) | **latest store parsed**; new reader support |
| Goose | **1.57.0** | GitHub `aaif-goose/goose` v1.57.0 | `~/.local/share/goose/sessions/sessions.db` (SQLite+WAL) | **latest store parsed** (LOCAL-SMOKE) |
| Kimi Code | **2.4.1** | `@moonshot-ai/kimi-code` npm @latest | `~/.kimi/sessions/<hash>/<id>/{context,wire}.jsonl` | OAuth login required for conversation |
| Gemini CLI | **0.66.0** | `@google/gemini-cli` npm @latest | `~/.gemini/` (project transcripts) | Google auth required |
| GitHub Copilot CLI | **1.0.105** | `@github/copilot` npm @latest | `~/.copilot/session-state/<id>/events.jsonl` | GitHub auth required |
| Cline | **3.0.74** | `cline` npm @latest | Cline task store | provider config needed |
| Continue CLI | **1.5.47** | `@continuedev/cli` npm @latest | `~/.continue/sessions/*.json` | config needed |
| Factory Droid | **1.1.0** | `droid` npm @latest | `~/.factory/...` | login required |
| Amp | **0.0.1793505644-g31e93e** | `@sourcegraph/amp` npm @latest | `~/.local/share/amp/threads/` | Sourcegraph login required |
| iFlow CLI | **0.5.19** | `@iflow-ai/iflow-cli` npm @latest | `~/.iflow/projects/*.jsonl` | OpenAI-compatible auth config required |
| WorkBuddy CLI | **1.0.0** (package 1.0.3) | `@workbuddy/cli` npm @latest | `~/.workbuddy/...` | Tencent account login |
| CodeBuddy | **2.179.1** | `@tencent-ai/codebuddy-code` npm @latest | `~/.codebuddy/...` | Tencent account login; official WorkBuddy CLI per vendor article |
| JetBrains Junie | **3110.7.0** (build 26.9.7) | `@jetbrains/junie` npm @latest | `~/.junie/...` | JetBrains account login |
| Kiro CLI | **2.37.0** | official `cli.kiro.dev/install` stable | `~/.kiro/sessions/...` | AWS Builder ID login |
| TRAE CLI | **0.213.1** | official `trae.cn/trae-cli/install_v2.sh` | `~/.trae/cli/sessions/` (TraeX = codex-rs fork) | login or PAT |
| Crush | **0.99.0** | GitHub `charmbracelet/crush` v0.99.0 | `~/.local/share/crush/` + project `.crush` | provider config; mock not applied yet |
| FX | **0.0.16** | GitHub `vercel-labs/fx` v0.0.16 | `~/.fx/` workspace sessions | provider login required |
| Mistral Vibe | **3.0.4** | PyPI `mistral-vibe` | `~/.vibe/logs/session/` (legacy layout) | Mistral API key required |
| Roo Code CLI (community) | **0.5.8** | `@quantum-ai/roo-code-cli` npm @latest | Roo task store | supports `OPENAI_BASE_URL`; not official Roo, Inc. CLI |
| Grok CLI (community) | **1.0.1** (pkg 0.0.34) | `@vibe-kit/grok-cli` npm @latest | did not create `~/.grok/sessions` | **official Grok Build install is blocked locally/remotely (x.ai timeout)** |

## 2. Installed but runtime blocked

| Harness | Package/latest | Blocker |
|---|---|---|
| Codebuff | **1.0.688** (`codebuff` npm) | runtime binary download from `codebuff.com` times out (ETIMEDOUT) |
| OpenHands CLI | PyPI **openhands-ai 1.11.0**; GitHub app v1.34.0 | latest PyPI wheel has **no console-script entry point**; `openhands` CLI not installed by `uv tool install` |
| Cursor Agent | npm **cursor-agent 1.0.3** | package has no bin; official Cursor Agent installer not used in this run |
| iFlow session smoke | 0.5.19 | CLI requires an auth method in settings; documented env names were not accepted in this isolated run, so no session generated |

## 3. No Linux CLI / desktop-only (cannot install headlessly)

| Harness | Latest known | Why |
|---|---|---|
| ZCode | **3.16.3** (official docs) | Electron GUI/AppImage; current docs have no headless CLI |
| Windsurf | desktop IDE | no public Linux CLI; new cascade store is encrypted protobuf |
| Cherry Studio | desktop GUI | SQLite store is app-internal; no CLI |
| Claude Desktop/Cowork | desktop GUI | transcript is Claude-code JSONL, but the app requires GUI |
| TRAE IDE | desktop IDE | only the separate TRAE CLI 2.0 (`traecli`) was installed |
| Zed | desktop editor | threads.db requires the app; no Linux headless session flow used |
| OpenCraw | — | no public standalone CLI; OSS evidence only / OpenClaw alias |

## 4. Latest-format validation added to the repo

`samples/batch7/` contains current stores written by **real latest binaries** (mock model only, explicitly
not real user conversations):

| Harness | Version | Fixture | Reader result |
|---|---|---|---|
| Qwen Code | 0.26.5 | `samples/batch7/qwen-latest/` | list/load OK (2 events) |
| Goose | 1.57.0 | `samples/batch7/goose-latest/` | list/load OK (3 events) |
| OpenCode | 1.19.5 | `samples/batch7/opencode-latest/opencode.db` | **new SQLite reader**; list/load OK |

Regression tests: `tools/agent-session-import/tests/test_latest_stores.py` (3 tests). Full backend suite:
**144 tests OK** after the OpenCode reader change.

## 5. What this changes — honestly

- **Support/format coverage:** three more current store formats are validated; OpenCode's v1.19 SQLite
  format was previously unsupported and is now parsed.
- **Real-session coverage: unchanged at 22/40.** Latest store smoke sessions are **LOCAL-SMOKE**, not
  real user conversations. The four published numbers (protocol 40/40, fixture-verified 35/40, real
  22/40, REAL-EXAMPLE 2) remain valid.
- **Versions:** all installable public CLIs above were installed with their latest versions; their
  `--version` output is recorded here. Login-gated CLIs cannot be run without the user's credentials;
  blocked installers are listed explicitly rather than being counted as covered.
