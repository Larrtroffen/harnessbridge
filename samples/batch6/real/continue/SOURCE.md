# Continue 真实会话样本（REAL）

| 项 | 值 |
|---|---|
| 文件 | `session-28fdaafd.json` |
| 来源仓库 | https://github.com/oleg121203/Developer |
| 原始路径 | `.continue/sessions/28fdaafd-5b3a-4342-90db-c3581e27b607.json` |
| commit | `74e48d0692fe9990c5d09aa3ae1d02b3658b2f71` |
| 许可 | **Apache-2.0**（仓库 `LICENSE`；GitHub API license.spdx_id=Apache-2.0，与 Lead 先前「无 license」的判断不同） |
| 证据等级 | **REAL**（真实用户在本机运行 Continue 产生的会话；非 fixture/非 generated） |
| 大小 | 8675 B（原始 9,688 B；截断：无） |
| 处理 | 脱敏 `/Users/<user>`、`/home/<user>` 路径、email、常见 key 形态；保留 `history[]` 结构与 2 轮真实对话（标题：Fixing Python code formatting issues） |
| 备注 | 该仓库共含 58 个真实 `.continue/sessions/*.json`（可选更多样本）；不含密钥；`workspaceDirectory` 为 `/workspace`（CI 环境），无个人路径 |

> 用途：Continue session JSON 结构 golden sample（`sessionId/title/workspaceDirectory/history[]`）。使用请保留 Apache-2.0 许可与出处。
