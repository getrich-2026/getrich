# 许可证

> **本节声明 GetRich 项目的开源许可证、第三方依赖许可、商业使用条款、商标声明。** 在 fork、贡献、商业集成前请仔细阅读。

---

## 1. 项目许可证

**MIT License** —— 最宽松的 OSI-approved 开源许可证之一。

| 字段 | 值 |
|---|---|
| 名称 | MIT License |
| OSI 批准 | ✅ |
| SPDX 标识符 | `MIT` |
| `pyproject.toml` 声明 | `license = { text = "MIT" }` |
| 分类器 | `"License :: OSI Approved :: MIT License"` |

### 1.1 MIT 允许的事

- ✅ 商业使用（含 SaaS、转售、嵌入产品）
- ✅ 修改源码
- ✅ 分发（源码或二进制形式）
- ✅ 私有使用
- ✅ 在其他许可证下再分发（**前提是保留原版权声明**）

### 1.2 MIT 要求的事

- 在所有副本/分发中**保留版权声明**（`Copyright (c) 2026 GetRich 团队`）
- 在所有副本/分发中**保留许可证全文**

### 1.3 MIT 禁止的事

- 任何形式的**作者/贡献者担保**：本软件按"原样"提供，**无任何明示或暗示的担保**

### 1.4 完整 LICENSE 文件

仓库根目录的 `LICENSE` 文件已生成（`git ls-files LICENSE` 应可见）。标准 MIT 全文：

```
MIT License

Copyright (c) 2026 GetRich 团队

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> ⚠️ **当前状态**：仓库根没有 `LICENSE` 文件。建议在 **#1127 收尾时一并补上**（用上面这段直接保存为 `LICENSE`）。

---

## 2. 第三方依赖许可

GetRich 的核心依赖（部分）：

### 2.1 Python 运行时

| 依赖 | 许可证 | 用途 |
|---|---|---|
| Python 3.12 | PSF License | 运行时 |
| `uv` | Apache-2.0 / MIT | 包管理 |

### 2.2 后端核心

| 依赖 | 许可证 | 用途 |
|---|---|---|
| FastAPI | MIT | HTTP 框架 |
| Pydantic | MIT | 数据验证 |
| orjson | MIT/Apache-2.0 | JSON 序列化 |
| psycopg3 | LGPL-3.0 | PG 异步驱动 |
| clickhouse-driver | MIT | CH 同步驱动 |
| polars | MIT | DataFrame |
| numpy | BSD-3-Clause | 数值计算 |
| pandas | BSD-3-Clause | 财务时序（仅 Reporter） |
| Celery | BSD-3-Clause | 异步任务 |
| Redis (broker) | BSD-3-Clause | 消息队列 |
| Bleach | Apache-2.0 | HTML 消毒（XSS 防御） |
| bleach[css] | Apache-2.0 | CSS 允许列表 |

> **LGPL 注意**：`psycopg3` 是 LGPL-3.0。如果以二进制形式分发 GetRich，**必须随包附带 psycopg3 源码链接**（用户可以替换它）。源码分发不受影响。

### 2.3 前端

| 依赖 | 许可证 | 用途 |
|---|---|---|
| React 19 | MIT | UI 框架 |
| Vite 7 | MIT | 构建工具 |
| TypeScript 5.9 | Apache-2.0 | 类型系统 |
| TanStack Query | MIT | 数据请求 / 缓存 |
| React Hook Form | MIT | 表单管理 |
| Zod | MIT | schema 验证 |
| shadcn/ui | MIT | 基础组件 |
| Radix UI | MIT | 无样式行为组件 |
| ECharts | Apache-2.0 | 时序/权益曲线 |
| Recharts | MIT | 通用图表 |
| DOMPurify | MPL-2.0 / Apache-2.0 | XSS 消毒 |
| Vitest | MIT | 单元测试 |

### 2.4 数据库

| 依赖 | 许可证 | 用途 |
|---|---|---|
| PostgreSQL | PostgreSQL License | 业务主库 |
| ClickHouse | Apache-2.0 | 时序存储 |
| DuckDB | MIT | 临时分析 |

> **PostgreSQL License** 是 BSD 风格的宽松许可证，不影响 MIT 项目。

### 2.5 完整依赖清单

```bash
# Python
uv pip list --format=columns | head -100

# 前端
cd frontend && npm list --all
```

精确许可证在每个包的元数据里（`METADATA` / `package.json`）。

---

## 3. 商业使用条款

### 3.1 ✅ 允许

- **SaaS 部署**：把 GetRich 当作后端向最终用户提供信号服务
- **嵌入自有产品**：作为后端引擎集成到量化交易平台
- **二次开发**：添加私有策略、连接私有 broker、修改任何源码
- **转售**：把 GetRich 作为组件嵌入到商业产品中再分发
- **托管服务**：为客户部署、管理 GetRich

### 3.2 ❌ 不允许（MIT 唯一硬约束）

- 移除源码中的版权声明（`Copyright (c) 2026 GetRich 团队`）
- 把作者/贡献者姓名用于**背书/担保**你的衍生产品

### 3.3 ⚠️ 推荐（合规角度）

- 在你的产品文档/About 页面**保留** "Powered by GetRich" 链接
- 重大修改/分支时**保留源码可用性**（这是 MIT 的精神而非条款）
- 第三方 broker API、行情数据源（通达信/聚宽/ClickHouse）**各自有独立许可证** —— 不在 MIT 范围内

### 3.4 无 SLA / 无技术支持

MIT 协议**不提供**任何形式的：

- 持续维护承诺
- Bug 修复时间保证
- 技术支持
- 数据准确性担保（行情/因子/信号）
- 财务损失担保

> **使用 GetRich 进行实盘交易的所有风险由用户承担。** 详见 [`CLAUDE.md` 免责条款](https://github.com/getrich/getrich/blob/main/CLAUDE.md)。

---

## 4. 商标声明

- **"GetRich"** 名称和 logo 归 GetRich 团队所有
- 在 fork 或衍生项目中使用 GetRich 名称/标识时：
    - ❌ 不能暗示"官方 GetRich 项目"
    - ❌ 不能在域名/产品名中使用 `getrich`（如 `getrich-pro.com`）造成混淆
    - ✅ 应在 README 顶部注明 "Fork of GetRich" + 指向原项目
- 任何"official GetRich"的表述都必须有 GetRich 团队书面授权

### 4.1 第三方商标

| 商标 | 所有者 | 说明 |
|---|---|---|
| PostgreSQL / Postgres | PostgreSQL Community Association | 数据库 |
| ClickHouse | ClickHouse, Inc. | 数据库 |
| React / React Hook Form | Meta Platforms, Inc. | UI |
| ECharts | Apache Software Foundation | 图表 |
| 通达信 | 深圳市财富趋势科技股份有限公司 | A 股行情源 |
| 聚宽 JoinQuant | 聚宽（北京）信息技术有限公司 | 数据源 |

> 上述商标**仅用于标识兼容性**，不代表任何形式的背书或合作。

---

## 5. 贡献者协议

> 提交 PR = 你同意以下条款（基于 GitHub Terms of Service + Apache ICLA 简化版）：

1. 你拥有你贡献的代码，或你已获得合法授权
2. 你授予 GetRich 团队**永久、免版税、全球、非独占**的版权许可
3. GetRich 团队可以用你的贡献做任何事（合并、再许可、商业化）
4. 你的贡献**不包含**第三方的机密信息或受限代码
5. 你的贡献按 MIT 许可证发布

### 5.1 第三方代码引入规则

| 第三方代码类型 | 处理方式 |
|---|---|
| 公有领域（CC0 / Unlicense） | 可直接引入 |
| MIT / BSD / Apache-2.0 | 引入时**保留版权头** |
| LGPL | 动态链接 OK；静态链接需提供替换方案 |
| GPL | **禁止**引入主代码（会传染整个项目） |
| AGPL | **禁止**（网络服务也要求开源） |
| 商业/专有 | **禁止**（除非有书面授权） |

> 引入任何第三方代码时，请在 `pyproject.toml` / `frontend/package.json` 的 `dependencies` 注明，并保留原始 LICENSE。

---

## 6. 第三方数据源条款

> 重要：行情/因子/新闻数据**不包含**在 GetRich 的 MIT 许可证范围内。

| 数据源 | 条款 | 备注 |
|---|---|---|
| **ClickHouse 自建数据** | 用户自有 | 部署时接入 |
| **通达信本地数据** | 商业授权 | 用户自购 |
| **聚宽 JQData** | 商业授权 | 用户自购，遵守 JQData 服务条款 |
| **公开 API（Tushare Pro / AKShare）** | 各异 | 遵守对应服务条款 |
| **Yahoo Finance / Alpha Vantage** | 非商业 | 商业用途需自购 |

> ⚠️ 在生产环境部署前，请确认**你接入的每个数据源**有合法使用权。GetRich 项目方**不为用户的数据源合规性负责**。

---

## 7. 完整法律文档索引

| 文档 | 位置 | 用途 |
|---|---|---|
| `LICENSE`（待补） | 仓库根 | MIT 全文 |
| `pyproject.toml` | 仓库根 | Python 包元数据（含 `license = "MIT"`） |
| `NOTICE`（可选） | 仓库根 | 第三方归属（如果用 Apache 2.0 才需要；MIT 不强制） |
| `SECURITY.md`（待补） | `.github/` | 漏洞报告流程 |
| `CODE_OF_CONDUCT.md`（可选） | `.github/` | 社区行为准则 |

---

## 8. 常见问题

### Q: 我可以在公司内部使用 GetRich 吗？
A: ✅ 完全可以。MIT 允许商业/内部使用。

### Q: 我能改源码再闭源分发吗？
A: ✅ 可以（MIT 允许），但**必须保留** MIT 许可证和版权声明。建议你在衍生项目中明确标注 "Based on GetRich (MIT)"。

### Q: 我 fork 后改了 80%，需要保留原 GetRich 名字吗？
A: 不能用 `GetRich` 作为你的产品名（商标部分）。代码中保留 MIT 声明是必须的，但产品命名请用 `MyQuant` / `FooTrader` 等。

### Q: 商用 GetRich 跑实盘亏损了，能索赔吗？
A: ❌ 不能。MIT 的 "AS IS" 条款明确排除了所有担保。GetRich 项目方**不为你的交易结果负责**。请确保你有独立的回测验证 + 风控 + 实盘小仓位测试。

### Q: 第三方 broker API（中信/华泰/IB）需要额外授权吗？
A: 是的。broker API 由各家券商提供，使用条款独立于 GetRich。请遵守 broker 的 API 服务协议（通常有请求频率限制、不得转售数据等条款）。

### Q: 我用了 polars（MIT），需要单独声明吗？
A: 不需要，MIT 兼容 MIT。完整归属可放在 `THIRD_PARTY_NOTICES.md`（可选）。

---

## 9. 进一步阅读

- 项目铁律：[CLAUDE.md](https://github.com/getrich/getrich/blob/main/CLAUDE.md)
- 部署：[systemd 部署](../operations/systemd.md)
- 兼容性：[数据库拓扑](../operations/database-topology.md)
- GitHub 官方：<https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository>
- SPDX License List：<https://spdx.org/licenses/>
- Open Source Initiative：<https://opensource.org/licenses/MIT>
