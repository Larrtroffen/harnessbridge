# copilot fixtures 来源

| 文件 | 证据等级 | 来源仓库 | 原始路径 | commit | license | 说明 |
|---|---|---|---|---|---|---|
| `schema_drift.jsonl` | FIXTURE | jazzyalex/agent-sessions | `samples/batch5-style fixture (schema_drift.jsonl)` | 8ca7aa603fe5 | MIT | agent-sessions synthetic stage fixtures |
| `large.jsonl` | FIXTURE | jazzyalex/agent-sessions | `samples/batch5-style fixture (large.jsonl)` | 8ca7aa603fe5 | MIT | agent-sessions synthetic stage fixtures |
| `subdir_v1/aaaabbbb-1111-2222-3333-ccccddddeeee/events.jsonl` | FIXTURE | jazzyalex/agent-sessions | `samples/batch5-style fixture (subdir_v1/aaaabbbb-1111-2222-3333-ccccddddeeee/events.jsonl)` | 8ca7aa603fe5 | MIT | agent-sessions synthetic stage fixtures |
| `copilot-attrs-map.jsonl` | FIXTURE | luoyuctl/agenttrace | `testdata/copilot-attrs-map.jsonl` | master | MIT | agenttrace testdata（真实解析器回归 fixture） |
| `generated-copilot-session.jsonl` | CONSTRUCTED | luoyuctl/agenttrace | `testdata/generated/copilot-session.jsonl` | master | MIT | agenttrace testdata（生成型） |

> 仅用于格式分析与互转测试；不含凭据/个人路径（如源文件含用户名路径，使用前请再脱敏）。
