# OpenCode v1.19.5 — latest SQLite store smoke sample (LOCAL-SMOKE)

| field | value |
|---|---|
| harness | OpenCode (`opencode`) |
| tool version | **1.19.5** (`npm view opencode-ai version` at 2026-11-01) |
| install | isolated `$HOME`; `npm install -g opencode-ai@latest` |
| source store | `~/.local/share/opencode/opencode.db` (SQLite; `session` / `message` / `part`) |
| generation | `opencode run "Say hello in one line"` with a custom OpenAI-compatible provider pointing at the local mock endpoint |
| evidence | **LOCAL-SMOKE** — real current SQLite format, NOT a real user session / not REAL coverage |
| license | OpenCode MIT; generated sample data handled as test fixture |
| notes | v1.19 moved the primary store to SQLite `opencode.db`; the reader supports this in addition to legacy storage/v2 JSON fixtures |
