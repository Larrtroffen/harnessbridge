# 未解决 / 需回退的 Harness Logo

以下 5 个 id 在 `manifest.json` 中为 `"fallback": true`（App 端请用首字母图标），原因如下：

| harness | 名称 | 原因 |
|---|---|---|
| codebuff | Codebuff | 官方站点 favicon/apple-touch 返回 HTML 而非图片；仓库无品牌资产；许可未标注 |
| fx | vercel-labs fx | 仓库仅有测试用 fixture，无品牌 logo 资产 |
| mini-swe-agent | mini-swe-agent | 官方仓库未发现 logo/icon 资产 |
| oss | Open Source（通用） | 无品牌主体，不应借用 OSI 等第三方商标 |
| atif | ATIF | 只是协议规范（Harbor RFC），无独立 logo；若需要可另行评估 Harbor 项目图标 |

## 需注意的许可/质量风险（已收录但建议复核）

- **Zed**：仓库 license 为 NOASSERTION（GPL-3.0 / Apache-2.0 混合）。打包进 App 前请确认 GPL 合规性。
- **Crush**：FSL-1.1-MIT；允许非 Competing Use，再分发需附带许可条款链接（已在 SOURCE.md 注明）。
- **Devin**：官方 favicon，许可未标注；分辨率低（16–48px），放大到 256 会略糊，建议后续换官方品牌资产。
- **Aider**：来源为品牌色底方形图，去背后保留图形，但来源本身未提供透明版本。
- 所有厂商 logo 均含**商标权**；若 App 对外分发，建议在产品"关于/致谢"页列出本清单与商标声明。
