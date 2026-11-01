# Qwen Code v0.26.5 — latest-store smoke sample (LOCAL-SMOKE)

| field | value |
|---|---|
| harness | Qwen Code (`qwen`) |
| tool version | **0.26.5** (`npm view @qwen-code/qwen-code version` at 2026-11-01) |
| install | isolated `$HOME=/tmp/hb-harness-home` on SSH Home (Ubuntu 22.04 x86_64), `npm install -g @qwen-code/qwen-code@latest` |
| source store | `~/.qwen/projects/<project>/chats/<session>.jsonl` |
| generation | `qwen -p "Say hello in one line" --yolo` against a **local mock OpenAI-compatible server**; model `mock-model` |
| evidence | **LOCAL-SMOKE** — real current tool/store format, but NOT a real user conversation and NOT counted as REAL coverage |
| license | consumer of the generated data: project MIT; Qwen Code itself Apache-2.0 |
| notes | the local mock returned a short response; the session contains the real user/system records written by 0.26.5 |
