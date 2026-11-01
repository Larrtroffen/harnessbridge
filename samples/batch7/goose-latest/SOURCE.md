# Goose v1.57.0 — latest-store smoke sample (LOCAL-SMOKE)

| field | value |
|---|---|
| harness | Goose (`goose`) |
| tool version | **1.57.0** (GitHub `aaif-goose/goose` release `v1.57.0`, 2026-10-28) |
| install | isolated `$HOME`; downloaded `goose-x86_64-unknown-linux-gnu.tar.gz` from the official release |
| source store | `~/.local/share/goose/sessions/sessions.db` (SQLite; WAL included) |
| generation | `GOOSE_PROVIDER=openai GOOSE_MODEL=mock-model OPENAI_HOST=http://127.0.0.1:18765 goose run -t "Say hello in one line"` with a local mock endpoint |
| evidence | **LOCAL-SMOKE** — real latest SQLite schema, NOT a real user session / not REAL coverage |
| license | Goose Apache-2.0; generated sample data is handled as test fixture |
| notes | `sessions.db` 1 page + 222 KB WAL; main DB file alone is not enough, keep the `-wal`/`-shm` siblings |
