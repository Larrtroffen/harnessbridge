# Goose v1.57.0 — real DeepSeek store (LOCAL-DEEPSEEK)

| field | value |
|---|---|
| harness | Goose (`goose`) |
| tool version | **1.57.0** (GitHub `aaif-goose/goose` release `v1.57.0`) |
| install | isolated `$HOME`; `goose-x86_64-unknown-linux-gnu.tar.gz` from official release |
| model | **DeepSeek `deepseek-flash`** via OpenAI-compatible `https://api.deepseek.com` |
| source store | `~/.local/share/goose/sessions/sessions.db` (SQLite; keep WAL/shm siblings) |
| generation | `GOOSE_PROVIDER=openai GOOSE_MODEL=deepseek-flash OPENAI_HOST=https://api.deepseek.com OPENAI_API_KEY=… goose run -t "Reply with the single word: pong"` |
| evidence | **LOCAL-DEEPSEEK** — real latest tool + real model response; NOT a real user session / not REAL coverage |
| license | Goose Apache-2.0; generated sample data handled as test fixture |
| notes | IR stats: 3 events (user context + user prompt + assistant "pong") |
