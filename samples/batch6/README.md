# Batch 6 — external fixture 入库（fixture-verified coverage）

本目录只收录**许可清晰**的上游/外部样本（MIT / Apache-2.0 / REAL-EXAMPLE），用于
`asi matrix-batch6` 的 fixture-verified format coverage 验证；**不是真实用户会话**。

## 证据等级（不可混淆）

| 等级 | 来源 | 能否计入真实会话覆盖（REAL） |
|---|---|---|
| **REAL-EXAMPLE** | Harbor RFC 0001 §V 公开真实轨迹样例（openhands / mini-swe-agent） | ❌ 单列，不计入 REAL |
| **FIXTURE** | 上游/第三方仓库针对真实 schema 的测试 fixture（agent-sessions/agenttrace/codeg/Harbor） | ❌ |
| **FIXTURE-LOW** | Codeg 派生/裁剪、reader-only 转录（kiro/codebuddy/antigravity） | ❌ |
| **CONSTRUCTED** | 本仓库按 schema 构造（`samples/batch5/constructed/`） | ❌ |

- 真实会话覆盖仍以 NATIVE/REAL-LOCAL/COLLECTED 为准（当前 21/40）；**外部 fixture 不得冒充真实会话**。
- Crush（FSL）与 Zed（GPL 混合）**未复制**任何上游文件。
- 每个 harness 子目录保留上游 `SOURCE.md`（来源仓库/commit/许可证/逐文件等级）。
- 文件均 ≤200KB，不含密钥/凭据；如源文件含用户名路径，仅作格式分析用途。

## 收录（13 个 harness）

`copilot qwen openclaw kimi grok antigravity devin codebuddy fx kiro roo`（FIXTURE/FIXTURE-LOW）
+ `openhands mini-swe-agent`（REAL-EXAMPLE）。

来源仓库：luoyuctl/agenttrace（MIT）、jazzyalex/agent-sessions（MIT, 8ca7aa603fe5）、
spacering-net/codeg（Apache-2.0, 54f07a112433）、harbor-framework/harbor（Apache-2.0, 7e0354ce0900）。
