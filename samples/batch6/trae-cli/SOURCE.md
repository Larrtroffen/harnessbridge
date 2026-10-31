# TRAE CLI (TraeX) fixtures（task-62）

| 文件 | 证据等级 | 来源 | 原始路径 | commit | license | 说明 |
|---|---|---|---|---|---|---|
| `sessions/2026/09/01/rollout-2026-09-01T10-00-00-019fcf70-1111-7000-8000-000000000001.jsonl` | FIXTURE | kenn-io/agentsview | `internal/parser/testdata/traex/history_mutation_session.jsonl` | `2ea69b892d5f` | MIT | TRAE CLI 2.0 (TraeX) = codex-rs fork → Codex rollout JSONL；含 session_meta/turn_context/response_item 等 |
| `archived_sessions/rollout-2026-08-01T18-07-04-019fbcca-9fd4-7d20-83dc-0762b2f839b3.jsonl` | FIXTURE | kenn-io/agentsview | `internal/parser/testdata/traex/rollout_subagent.jsonl` | `2ea69b892d5f` | MIT | 同上，含 subagent 链接 |

- 目录形状按 agentsview README：`~/.trae/cli/sessions/`、`~/.trae/cli/archived_sessions/`；
  本 fixture 用 `<trae-cli>/sessions/YYYY/MM/DD/rollout-*.jsonl`（Codex 布局）验证 native-first 路径。
- 不含凭据/真实用户数据。
