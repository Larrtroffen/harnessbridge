# roo fixtures 来源

| 文件 | 证据等级 | 来源仓库 | 原始路径 | commit | license | 说明 |
|---|---|---|---|---|---|---|
| `constructed/README.md` | CONSTRUCTED | (本仓库) | `samples/batch5/constructed/roo/README.md` | n/a | internal | converter-dev 按 schema 构造；不得冒充真实会话 |
| `constructed/data/sessions/b5roo/b5roo.messages.json` | CONSTRUCTED | (本仓库) | `samples/batch5/constructed/roo/data/sessions/b5roo/b5roo.messages.json` | n/a | internal | converter-dev 按 schema 构造；不得冒充真实会话 |
| `constructed/data/sessions/b5roo/b5roo.json` | CONSTRUCTED | (本仓库) | `samples/batch5/constructed/roo/data/sessions/b5roo/b5roo.json` | n/a | internal | converter-dev 按 schema 构造；不得冒充真实会话 |
| `cline-family-api_conversation_history.json` | FIXTURE | luoyuctl/agenttrace | `testdata/cline-task/api_conversation_history.json` | master | MIT | agenttrace testdata（真实解析器回归 fixture） |
| `cline-family-ui_messages.json` | FIXTURE | luoyuctl/agenttrace | `testdata/cline-task/ui_messages.json` | master | MIT | agenttrace testdata（真实解析器回归 fixture） |
| `cline-family-task_metadata.json` | FIXTURE | luoyuctl/agenttrace | `testdata/cline-task/task_metadata.json` | master | MIT | agenttrace testdata（真实解析器回归 fixture） |

> 仅用于格式分析与互转测试；不含凭据/个人路径（如源文件含用户名路径，使用前请再脱敏）。
