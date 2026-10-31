# Zed fixtures（task-62，CONSTRUCTED）

| 文件 | 证据等级 | 内容 | 来源 |
|---|---|---|---|
| `threads/threads.db` | CONSTRUCTED（schema 来自上游源码事实） | 2 条 thread：`thread-fixture-json`（data_type=json）与 `thread-fixture-zstd`（data_type=zstd，zstd CLI 压缩）；含 user/assistant/thinking/tool_use/tool_results/compaction 结构 | 按 zed-industries/zed `crates/agent/src/db.rs` 表结构与 `DbThread`/`Message` serde 结构构造；schema 事实参考 kenn-io/agentsview `internal/parser/zed*.go`（MIT） |

> Zed 仓库许可证为 NOASSERTION（LICENSE-APACHE + LICENSE-GPL）：本 fixture 为**自构样本**，
> 未复制 Zed 源码/资产，仅使用表结构与字段名事实。
> 消息 JSON 为按 Rust serde（externally-tagged enum）推断的格式；真实 Zed DB 由用户 App 写入，
> 若字段/枚举有漂移，reader 会跳过未知 variant 并给出 warning（不冒充真实会话）。
