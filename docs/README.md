# 文档目录与维护约定

读者：寻找说明的项目维护者，以及需要按任务加载上下文的 Agent。
文档按用途组织；不要求每次任务读完所有文档。根 README 负责项目入口，本页负责找文档。

## 按读者与任务找入口

| 读者／任务 | 文档 | 内容边界 |
|---|---|---|
| 首次运行项目的人 | [根 README](../README.md) | 项目概况、启动入口 |
| Codex／Antigravity 执行任务 | [AGENTS.md](../AGENTS.md) | 现行项目规则，不放历史状态 |
| 接续任务的 Agent | [NOTES.md](../.agents/brain/NOTES.md) | 当前方向、阻塞、验证边界；会话开始读 |
| Agent／维护者解释取舍 | [DECISIONS.md](../.agents/brain/DECISIONS.md) | 按主题查业务与架构关键取舍；不收集实现技巧或单次排错 |
| 前端开发者 | [前端指南](guides/frontend-dev.md) | 启动、代理、配置与排障 |
| 策略／数据维护者 | [选股导入](guides/pick-import.md) | 文件格式、CLI、入池日期 |
| 诊断页面接入者 | [诊断 API](guides/diagnosis-api.md) | 调用流程与状态，模型真源在代码／OpenAPI |
| 数据库开发者 | [数据字典](guides/data-dictionary.md) | 生成字典与注释门禁，不手抄 schema |
| 安排工作的人 | [待决问题](plans/backlog.md) | 缺口、证据、待定选择、验收条件 |
| 追溯历史的维护者 | [数据字典旧计划](history/data-dictionary-plan.md)、[诊断旧审查](history/diagnosis-api-review.md) | 已完成快照，不作为当前指令或待办 |

## 项目介绍页与 GitHub Pages

面向项目访客的 [静态首页](index.html) 提供项目简介、模块概览与文档入口；开发说明仍以现有 Markdown 为准。页面使用内嵌 CSS，无需构建、外部字体或后端服务，文档链接直接指向 GitHub 的 `dev` 分支。

本地预览，从仓库根运行 `python3 -m http.server 8088 --bind 127.0.0.1 --directory docs`，然后打开 `http://127.0.0.1:8088/`；也可以用浏览器直接打开 `docs/index.html`。

发布时，先将页面文件推送至选定分支，再在仓库 **Settings → Pages → Build and deployment** 中选择 **Deploy from a branch**，分支选择含该页面的分支（当前开发分支为 `dev`），目录选择 **/docs**。`docs/.nojekyll` 使其直接按静态文件发布，无需恢复旧 MkDocs 工作流。文档更新后页面入口保持有效，模块简介变化时同步更新 HTML。

默认项目网址为 `https://getrich-2026.github.io/getrich/`，实际发布成功与否以 Pages 设置和部署记录为准。GitHub Free 支持公开仓库的 Pages；私有仓库是否支持取决于账户方案，详见 [GitHub 官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)。

## 留在模块旁的文档

这些文件与代码／配置共同维护，通过本页发现，不为了集中目录而搬走。

| 位置 | 读者与用途 |
|---|---|
| [gr-data README](../packages/gr-data/README.md) | 数据开发者：provider、抓取、入库与排障 |
| [deploy README](../deploy/README.md) | 运维维护者：复制部署模板与外部实例边界 |
| [回测前端 README](../apps/backtest-web/README.md) | 维护旧应用的人：局部说明；应用暂停维护 |
| [gr-factor 测试说明](../packages/gr-factor/tests/README.md) | 修复数值模块的人：测试入口占位 |
| [旧 SQL 归档说明](../packages/gr-db/archive/README.md) | 数据库维护者：辨别历史 SQL，不能当现行迁移 |
| `packages/gr-data/reference/design/` | 接入维护者：供应商资料；按 provider 查，不默认全读 |
| 相邻仓库 `getrich-design/` | 产品／架构设计者：需求与供应商接口设计；落地前核对本仓代码和 DDL |

`CLAUDE.md` 与 `.agents/rules/project.md` 只负责工具入口，不另存编码规则。
`archive/` 和 `packages/gr-db/archive/` 的代码归档保持原位；删除需单独授权。

## 新增与更新文档

1. **先写清读者与用途**：文件开头说明给谁读、解决什么问题、状态（现行／待决／历史）。状态或实测数据带日期与验证范围。
2. **先找已有位置**：规则改 AGENTS；当前状态改 NOTES；未决问题改 backlog；操作步骤改相应指南；取舍原因改 DECISIONS。没有独立读者或用途时优先补现有文档。
3. **新增只为独立用途**：`guides/<topic>.md` 放可重复使用的操作说明；`plans/<topic>.md` 仅在任务已有明确范围、需跨会话实施时建立，写验收条件；不为每次修复创建计划或总结。
4. **完成后收敛**：从计划中抽取仍需要的使用说明和决策，清掉 NOTES／backlog 的完成项；有追溯价值的计划移到 history 并标明被什么取代，其余经授权删除。
5. **保留一份真源**：DDL、响应模型、CI 命令以代码和配置为准；指南引用它们。生成 HTML／JSON 不当作手工维护文档，不把机器地址、凭证状态或旧测试数字写成永恒事实。
6. **方便读取**：一个文件一个用途；用明确标题、短段落、主题索引和相对链接。Agent 先读规则与短状态，再按需查指南／决策；人从 README／本页按任务进入。
7. **移动必须修引用**：同步 Markdown 链接、指令入口和注释中的路径；已记账 SQL 不为改文档路径而变更 checksum。经用户授权删除／合并决策并重编号时，同步索引、锚点与现行引用；已记账 SQL 的旧编号在决策文档说明映射，避免改变 checksum。

2026-09-18 按用户授权精简关键决策并重编号；后续日常维护以追加／明确取代为主。决定是否新增条目时，先问维护者是否需要理解这个取舍，以及改选另一方案是否会影响业务结果、数据可信度或架构边界。
