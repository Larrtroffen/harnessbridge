# OpenCode v1.19.5 — real DeepSeek SQLite store (LOCAL-DEEPSEEK)

| field | value |
|---|---|
| harness | OpenCode (`opencode`) |
| tool version | **1.19.5** (`npm view opencode-ai version` at 2026-11-01) |
| install | isolated `$HOME`; `npm install -g opencode-ai@latest` |
| model | **DeepSeek `deepseek-flash`** via a custom OpenAI-compatible provider with Base URL `https://api.deepseek.com/v1` and API key from env |
| source store | `~/.local/share/opencode/opencode.db` (SQLite; `session` / `message` / `part`) |
| generation | `opencode run "Reply with the single word: pong"` |
| evidence | **LOCAL-DEEPSEEK** — real latest tool + real model response; NOT a real user session / not REAL coverage |
| license | OpenCode MIT; generated sample data handled as test fixture |
| notes | IR stats: 2 events (1 user, 1 assistant "pong"); v1.19 SQLite format |
