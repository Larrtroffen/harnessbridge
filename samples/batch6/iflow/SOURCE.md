# iFlow fixtures（task-62）

| 文件 | 证据等级 | 来源 | 原始路径 | commit | license | 说明 |
|---|---|---|---|---|---|---|
| `projects/-Users-fixture-iflow-demo/session-5de701fc-7454-4858-a249-95cac4fd3b51.jsonl` | FIXTURE（上游测试样本） | kenn-io/agentsview | `internal/parser/testdata/iflow/session-5de701fc-7454-4858-a249-95cac4fd3b51.jsonl` | `2ea69b892d5f` | MIT | iFlow CLI 原生 JSONL（Claude Code 兼容 schema：uuid/parentUuid/message.content blocks/tool_use/usage/cwd/version）；工具名 iFlow 风格（read_file），模型 glm-4.7 |

- 复制的来源文件同时保存在 `research/external/fixtures/iflow/`（task-56 产物）。
- 不含凭据；仅含上游测试数据（含 Windows 路径 `C:\exp\...`）。
- 用途：`readers/iflow.py` list/load 回归测试。
