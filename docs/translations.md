# Translations / 翻译

> **本页是 i18n 占位**：GetRich 文档目前**只提供中文版**。
> 英文 / 其它语种的全文翻译尚未启动，参见下方路线图。

## 当前状态

| 语言 | 状态 | 入口 | 维护者 |
|---|---|---|---|
| 中文（zh） | ✅ 当前唯一版本 | [首页](index.md) | GetRich 团队 |
| 英文（en） | 🚧 占位 | _无_ | 招募中 |
| 日文（ja） | ⏳ 未规划 | — | — |
| 繁体（zh-Hant） | ⏳ 未规划 | — | — |

> 招募翻译志愿者请开 issue 标 `area:docs` + `i18n`。

## 为什么暂时只做中文

- 量化研究的术语在中文圈最精准（"回测"、"因子"、"持仓"、"信号"）
  与英文 alpha / beta / drawdown 不是 1:1 直接对应
- 项目早期人力有限，先把 80+ 篇中文文档打磨完
- 双语维护成本 ~2x（任何代码 / SQL 改动都要同步翻译，CI 要做交叉检查）

## i18n 启动条件

当以下 3 个条件都满足时启动英文版：

1. ✅ 中文版稳定 6 个月以上，PR 数量下降到 < 5 / 月
2. ✅ 至少 2 名 native English speaker 愿意长期维护
3. ✅ CI 加双语链接完整性校验（mkdocs-static-i18n 插件）

## 技术选型（预研）

候选方案：

| 方案 | 优点 | 缺点 | 评估 |
|---|---|---|---|
| `mkdocs-static-i18n` | 官方推荐，与 Material 兼容 | 文档相对少 | ⭐ 首选 |
| 2 套独立 mkdocs.yml | 简单 | 维护成本高 | 备选 |
| Crowdin / Transifex SaaS | 自动翻译协作 | 月费 + 流程重 | 暂不考虑 |

## 临时方案：浏览器翻译

英文用户可暂时用浏览器内置翻译（Chrome / Edge / Firefox 都支持）：

- 优点：即时，无需服务端工作
- 缺点：技术术语翻译不准（如"bar"翻成"条"，"factor"翻成"因素" vs "因子"）
- 推荐：阅读时切到中英对照，专业术语以原文为准

## 翻译规范（未来）

翻译启动时遵循：

1. **技术术语保真**：backtest / factor / signal / strategy / portfolio
   等核心概念不翻译，**首次出现**加括号 `（回测）`。
2. **代码 / SQL / 路径不翻译**：`OrderIntent`、`.on_bar(ctx)`、`signals` 表名都保留
3. **CLI 标志不翻译**：`--strategy-id`、`mkdocs build --strict` 原样保留
4. **章节标题人工对照**：`## 1. 全景` ↔ `## 1. Overview`，**禁止**机翻

## 贡献

想做英文版翻译的伙伴：

1. 在 [GitHub Issues](https://github.com/getrich/getrich/issues) 开一个
   `i18n-en` 类型 issue 认领章节
2. 等 i18n 启动 PR 合入后按章节跟进
3. 翻译完一篇发一个 PR，按 `docs(i18n-en): translate <chapter>` 命名

## 进一步阅读

- 引擎文档：[engine/index.md](engine/index.md)
- 平台文档：[platform/architecture.md](platform/architecture.md)
- 运维文档：[operations/runbook.md](operations/runbook.md)
