# Qwen Code v0.26.5 — real DeepSeek store (LOCAL-DEEPSEEK)

| field | value |
|---|---|
| harness | Qwen Code (`qwen`) |
| tool version | **0.26.5** (`npm view @qwen-code/qwen-code version` at 2026-11-01) |
| install | isolated `$HOME=/tmp/hb-harness-home` on SSH Home (Ubuntu 22.04 x86_64), `npm install -g @qwen-code/qwen-code@latest` |
| model | **DeepSeek `deepseek-flash`** via OpenAI-compatible `https://api.deepseek.com/v1` |
| source store | `~/.qwen/projects/<project>/chats/<session>.jsonl` |
| generation | `OPENAI_API_KEY=… OPENAI_BASE_URL=https://api.deepseek.com/v1 OPENAI_MODEL=deepseek-flash qwen -p "Reply with the single word: pong" --yolo` |
| evidence | **LOCAL-DEEPSEEK** — real latest tool version + real model response; NOT a real user conversation and NOT counted as REAL coverage |
| license | Qwen Code Apache-2.0; generated sample data handled as test fixture |
| notes | IR stats: 3 events (2 user/system, 1 assistant "pong") |
