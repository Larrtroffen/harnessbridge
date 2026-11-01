# 未解决 / 使用 fallback 的 Harness Logo

以下 id 在 `manifest.json` 中为 `"fallback": true`（App 使用首字母图标）：

| harness | 原因 |
|---|---|
| pi | badlogic 的 GitHub avatar 是个人照片，不是 Pi 产品 logo；未找到官方独立品牌资产 |
| mini-swe-agent | SWE-agent 的 GitHub avatar 是照片，不是可辨识的产品 mark |
| fx | vercel-labs 的 GitHub avatar 是 Vercel 三角，不是 fx 产品 logo |
| oss | 通用 OSS 采集，无品牌主体 |
| atif | 只是协议规范（Harbor RFC），无独立 logo |

## 说明

- 2026-11-01 已用官方 GitHub 组织/仓库 avatar 补齐 amp、cherry-studio、claude-desktop、codebuff、droid、grok、hermes、iflow、openclaw、opencraw、trae、workbuddy、zcode 等，并替换 claude/codex/aider/devin 的旧第三方图。
- 部分产品没有独立公开品牌 mark，只能用母公司/组织官方标识（如 Claude→Anthropic、Codex→OpenAI、Amp→Sourcegraph、WorkBuddy→CodeBuddy）；这些在 SOURCE.md 中逐项标注，不应理解为产品级官方 logo。
- 商标归各所有者；此处仅作识别用途。若需要严格的官方 press-kit 资产，请由各厂商品牌规范确认后再替换。
