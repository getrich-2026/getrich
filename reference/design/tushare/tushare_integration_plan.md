# Tushare Pro 接入 —— 详细功能与开发方案

> 配套文档：API 目录见 [`tushare_api_design.md`](./tushare_api_design.md)；架构与约定见 [`../../../docs/architecture.md`](../../../docs/architecture.md)、[`../../../AGENTS.md`](../../../AGENTS.md)。
> 本文是**设计 / 开发方案**，不含已落地代码。实现按文末分阶段计划推进。

## 1. 背景与定位

Tushare Pro 作为第 4 个数据 provider 接入 `getrich-database`（已有 yinhe / ricequant / insight）。沿用项目「分层优先、再按 provider 切纵切片」的架构：在 `raw`（SDK→parquet）与 `ingest`（parquet→canonical→PostgreSQL）各加一个 tushare 纵切片，DDL 在 `db/ddl` 扩展。

**定位（经决策）**：Tushare **全表覆盖**——既写全部标的（stock/etf/index/future/option）日频行情、复权因子、instruments、calendar 等既有 canonical 表，也独占基本面/宏观/参考/筹码情绪等全新数据域。**哪个 provider 实际入哪张表由配置决定**：目的是当 Tushare 某张表质量更优时，可平滑切成主源。

口径仍是「先存 parquet 再入库」，不引入 SDK→DB 直连。

## 2. 决策记录（本方案的前提）

| # | 决策点 | 结论 |
|---|---|---|
| D1 | 定位：是否覆盖既有行情主表 | **全量开发，配置选源**。代码层 Tushare 能写所有表；运行时入哪张由 config 决定 |
| D2 | 配置选源 vs 单一来源铁律 | **单 owner + 显式转移**。`ops.table_ownership` 每表仍唯一 owner；切主源走 `OwnershipManager` force/release，需人工确认 |
| D3 | 港股（HK） | **本期暂不纳入**。不改 `meta.instruments` 的 CHECK 约束，HK 留作后续独立迭代 |
| D4 | 财报/基本面表列设计 | **核心列 + `raw_payload` JSONB**。沿用 insight DDL 范式，PK `(instrument_id, end_date, report_type, source)` |
| D5 | 数据域范围 | **全部**：基本面/财报、宏观、参考/基础信息、筹码/情绪，以及所有标的日频行情 + 复权因子 |
| D6 | 新域 schema 组织 | **四个业务 schema**：`finance` / `macro` / `reference` / `sentiment` |
| D7 | 复权因子落地 | **填 `*_bar_1d.adj_factor` canonical 列 + 另建 `market.adj_factor_ts` 明细表** |
| D8 | canonical 行情表单位 | **严格换算对齐**。换算系数需先核对 yinhe 现有 raw 口径（见 §6.2，标为实现前待办） |
| D9 | 依赖 / token / 交易所归一 / 限流（低分歧默认项） | 按推荐：`tushare` 加为主依赖（PyPI）；token 走 `TUSHARE_TOKEN` 环境变量；`BJ→XBSE` 交易所归一；限流走 config `rate_limit`。如需改动请提出 |

## 3. 数据域 → 目标表 → 所有权 映射

> 「所有权」列：**既有**=已被某 provider 占有，Tushare 接管需显式转移（D2）；**新建**=Tushare 独占，零冲突。

### 3.1 行情与基础信息（既有 canonical 表，配置选源）

| Tushare 接口 | 目标表 | 现 owner | 备注 |
|---|---|---|---|
| `daily` | `market.stock_bar_1d` | yinhe | 单位换算（§6.2） |
| `index_daily` | `market.index_bar_1d` | yinhe | |
| `fund_daily` | `market.etf_bar_1d` | yinhe | 仅 ETF 子集 |
| `fut_daily` | `market.future_bar_1d` | —（未填） | 含 `open_interest/settle/pre_settle` |
| `opt_daily` | `market.option_bar_1d` | —（未填） | |
| `adj_factor` | `market.*_bar_1d.adj_factor` 列 + `market.adj_factor_ts` | yinhe / 新建 | §6.3 |
| `stock_basic` | `meta.instruments` + `meta.symbol_map`（+ `reference.stock_basic`） | yinhe | 扩展列入 reference |
| `trade_cal` | `meta.trading_calendar` | yinhe | |
| `fut_basic` | `meta.future_contracts` | — | |
| `opt_basic` | `meta.option_contracts` | — | |
| `index_basic` / `fund_basic` | `meta.instruments` | yinhe | |

### 3.2 基本面 / 财报（新建 `finance` schema）

| Tushare 接口 | 目标表 |
|---|---|
| `income` | `finance.income` |
| `balancesheet` | `finance.balance_sheet` |
| `cashflow` | `finance.cash_flow` |
| `fina_indicator` | `finance.fina_indicator` |
| `forecast` | `finance.earnings_forecast` |
| `express` | `finance.earnings_express` |
| `dividend` | `finance.dividend` |
| `fina_mainbz` | `finance.main_business` |

### 3.3 宏观（新建 `macro` schema）

| Tushare 接口 | 目标表 |
|---|---|
| `cn_gdp` | `macro.gdp` |
| `cn_cpi` | `macro.cpi` |
| `cn_ppi` | `macro.ppi` |
| `cn_m` | `macro.money_supply` |
| `cn_pmi` | `macro.pmi` |
| `cn_sf` | `macro.social_finance` |
| `shibor` | `macro.shibor` |
| `lpr` | `macro.lpr` |

### 3.4 参考 / 基础信息（新建 `reference` schema）

| Tushare 接口 | 目标表 |
|---|---|
| `stock_basic`（扩展列） | `reference.stock_basic` |
| `index_weight` | `reference.index_weight` |
| `suspend_d` | `reference.suspend` |
| `share_float` | `reference.share_float` |
| `moneyflow_hsgt` | `reference.hsgt_moneyflow` |
| `stk_limit` | `reference.price_limit` |
| `namechange` | `reference.name_change` |

### 3.5 筹码 / 情绪（新建 `sentiment` schema）

| Tushare 接口 | 目标表 |
|---|---|
| `top_list` / `top_inst` | `sentiment.top_list` / `sentiment.top_inst` |
| `margin` / `margin_detail` | `sentiment.margin` / `sentiment.margin_detail` |
| `block_trade` | `sentiment.block_trade` |
| `stk_holdernumber` | `sentiment.holder_number` |
| `moneyflow` | `sentiment.moneyflow` |
| `hk_hold` | `sentiment.hk_hold`（北向持股，非港股行情，本期可纳入） |

## 4. DDL 设计

新增 DDL 文件（编号续在现有 `70_ownership.sql` 之后）：

| 文件 | 内容 |
|---|---|
| `db/ddl/80_finance.sql` | `finance` schema + 8 张财报表 |
| `db/ddl/81_macro.sql` | `macro` schema + 宏观表 |
| `db/ddl/82_reference.sql` | `reference` schema + 参考表 |
| `db/ddl/83_sentiment.sql` | `sentiment` schema + 筹码情绪表 |
| `db/ddl/84_market_ext.sql` | `market.adj_factor_ts` 明细表 |

### 4.1 财报表范式（核心列 + JSONB，D4）

以利润表为例，其余财报表同构：

```sql
CREATE SCHEMA IF NOT EXISTS finance;

CREATE TABLE IF NOT EXISTS finance.income (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    end_date       DATE NOT NULL,           -- 报告期（事件时间）
    report_type    VARCHAR(8) NOT NULL,     -- 合并/母公司/单季 等
    ann_date       DATE,                    -- 公告日（publish time，防未来函数）
    f_ann_date     DATE,                    -- 实际披露日
    -- 高频查询核心列（示例，按接口补全）
    total_revenue  NUMERIC(24,4),
    revenue        NUMERIC(24,4),
    operate_profit NUMERIC(24,4),
    total_profit   NUMERIC(24,4),
    n_income       NUMERIC(24,4),
    -- 完整原始行
    raw_payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, end_date, report_type, source)
);
SELECT create_hypertable('finance.income', 'end_date',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);
```

要点：
- **事件时间 vs 披露时间分离**（AGENTS.md）：`end_date` 是报告期；`ann_date/f_ann_date` 是公告/披露时间，下游做防未来函数过滤时用披露时间。
- PK 含 `source`，与 insight 既有范式一致，允许多源并存于明细层（canonical 主表仍受 ownership 约束）。
- 核心列只铺高频字段，字段随接口漂移时优先扩 JSONB，避免频繁改 DDL。

### 4.2 复权因子明细表（D7）

```sql
CREATE TABLE IF NOT EXISTS market.adj_factor_ts (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day   DATE NOT NULL,
    adj_factor    NUMERIC(18,8) NOT NULL,   -- Tushare 原始单值因子
    source        VARCHAR(32) NOT NULL,
    raw_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source),
    CONSTRAINT chk_adj_factor_ts_positive CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.adj_factor_ts', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);
```

同时回填 `market.*_bar_1d.adj_factor` 列（与 yinhe「复权因子」语义一致，可直接互换）。

### 4.3 宏观 / 参考 / 筹码情绪表

宏观表多为**时间序列、无 instrument 维度**，PK 用 `(period, source)` 或 `(stat_date, source)`；参考/筹码情绪表多带 instrument 维度，PK `(instrument_id, trading_day/end_date, source)`。统一带 `raw_payload JSONB` + `source` + `updated_at`，时间列做 hypertable。具体列在各阶段实现时按接口字段定稿。

## 5. 代码模块结构

```
src/getrich_data/
├── raw/tushare/
│   ├── __init__.py          # REGISTRY: dataset -> fetcher 类；build TushareClient
│   ├── client.py            # TushareClient：封装 ts.set_token/pro_api，限流、重试、5000行翻页
│   └── fetchers/
│       ├── market.py        # daily/index_daily/fund_daily/fut_daily/opt_daily/adj_factor
│       ├── reference.py     # stock_basic/trade_cal/fut_basic/opt_basic/index_weight/...
│       ├── finance.py       # income/balancesheet/cashflow/fina_indicator/...
│       ├── macro.py         # cn_gdp/cn_cpi/.../shibor/lpr
│       └── sentiment.py     # top_list/margin/block_trade/...
└── ingest/tushare/
    ├── __init__.py          # REGISTRY + GROUPS（importer 注册与分组）
    ├── adapter.py           # 读 /opt/raw_parquet/tushare/ parquet（不归一化）
    ├── symbols.py           # split_code：后缀→canonical exchange（SH/SZ/BJ→XSHG/XSHE/XBSE）
    └── importers/
        ├── reference.py     # InstrumentsImporter/SymbolMapImporter/CalendarImporter/...
        ├── market.py        # *Bars1dImporter/AdjFactorImporter
        ├── finance.py
        ├── macro.py
        └── sentiment.py
```

接线点（需改既有文件）：
- `src/getrich_data/raw/__init__.py`：`PROVIDERS` 加 `"tushare"`；`_registry`/`_build_client` 加分支。
- `src/getrich_data/ingest/__init__.py`：`PROVIDERS` 加 `"tushare"`；`_registry_groups` 加分支。
- `src/getrich_data/cli.py`：`raw`/`ingest` 子命令 `choices` 加 `"tushare"`（`raw.py:115`、`ingest.py:121`）。stream 不涉及（Tushare 本期不做实时）。

`BaseFetcher` / `BaseImporter` / `RawContext` / `IngestContext` 复用现有基类，新 importer 设 `PROVIDER="tushare"` + `DATASET` + `CONTRACT` + `NOT_NULL_COLUMNS`，沿用 `run()` 单事务流程（claim → build → 质检 → upsert → 记录 → commit）。instrument_id 解析用 `resolve_by_symbol_map(conn, "tushare")`。

## 6. 归一化与口径规则

### 6.1 代码 / 交易所归一化
Tushare 代码形如 `600000.SH` / `000001.SZ` / `430047.BJ`，与 yinhe/insight 同为带后缀完整串。`split_code` 规则：

| 后缀 | canonical exchange |
|---|---|
| `SH` | `XSHG` |
| `SZ` | `XSHE` |
| `BJ` | `XBSE`（北交所，新增映射） |

`meta.instruments.symbol` 保留完整串（如 `600000.SH`）。既有 symbol 已是该形态，因此 Tushare 行情 importer 可直接 `resolve_by_symbol_map`。

### 6.2 单位换算（D8，⚠️ 实现前待办）
Tushare 原始单位：`vol=手`（1 手=100 股）、`amount=千元`、`pct_chg=%`。canonical 行情表 `volume BIGINT`、`amount NUMERIC(24,4)`。

**写 canonical 表时严格换算对齐到既有 provider 口径；raw parquet 保留原始值不动。**

> ⚠️ **实现前必须先核对 yinhe 现有 `volume/amount` 的实际单位**（代码与文档均未注明，见 `AGENTS.md`「不得静默改单位」），据此定换算系数，禁止凭猜测写死系数。换算规则在 ingest 显式实现并加列注释。

### 6.3 复权因子语义
Tushare `adj_factor` 为单值「每日复权因子」，与 yinhe 的 `bar.adj_factor` 同语义，直接回填 canonical 列；同时原始明细落 `market.adj_factor_ts`（§4.2）。分钟线保持不复权，沿用现有「join 日线 adj_factor」约定。

## 7. 配置与依赖变更

### 7.1 依赖
`pyproject.toml` 主依赖加 `tushare`（PyPI，与其余三家 vendor wheel 不同，可直接 `uv sync` 装）：
```toml
dependencies = [ ..., "tushare>=1.4" ]
```

### 7.2 配置
`config.example.yaml` 的 `providers` 加：
```yaml
providers:
  tushare:
    token_env: TUSHARE_TOKEN     # 仅经环境变量，不入库不入仓
    rate_limit: 200              # 按积分档配置 QPS/分钟限额
    points_tier: ...
enabled:
  raw:    { tushare: [ ... ] }   # 选择性下载哪些 dataset
  ingest: { tushare: [ ... ] }   # 配置选源：决定 tushare 入哪些表
```

**配置选源即在此体现**：把某张既有表的 importer 放进 `enabled.ingest.tushare`，并完成 ownership 转移（§8），即把主源切到 Tushare。

## 8. 所有权与「配置选源」机制（D2）

铁律不变：`ops.table_ownership` 每表唯一 owner。配置只决定「启用哪个 provider 的 importer」，真正写入仍由 `OwnershipManager.claim()` 把关：

- **新域表（finance/macro/reference/sentiment、adj_factor_ts）**：Tushare 首次 `claim` 即零冲突登记，无需转移。
- **既有表（stock_bar_1d、meta.instruments 等，现属 yinhe）**：Tushare `claim` 会撞 `OwnershipError`。切主源需**显式转移**：
  1. `getrich own release <target> <channel>` 释放原 owner，或
  2. 转移流程用 `claim(target, "tushare", force=True)`（高风险，AGENTS.md §11 要求人工确认）。
- CLI `own list/set/release` 已支持归属查看与变更，无需新代码。

> 切主源是**高风险操作**：影响下游口径一致性。须在评估 Tushare 与原 owner 数据一致性后、单独提出并确认，不在批量入库里隐式发生。

## 9. 分阶段开发计划

| 阶段 | 目标 | 风险 | 产出 |
|---|---|---|---|
| **P0** | 骨架：`raw/tushare` + `ingest/tushare` 框架、`client.py`、注册接线、`reference.stock_basic`（零冲突表）跑通 | 低 | 端到端打通 + Fake client 测试 |
| **P1** | 基本面/财报：`finance` schema + 8 表 + fetchers/importers | 中（字段多） | 财报全量入库 |
| **P2** | 宏观：`macro` schema + 表 | 低 | 宏观时序入库 |
| **P3** | 参考 + 筹码情绪：`reference` / `sentiment` schema + 表 | 中 | 全新域完成 |
| **P4** | 行情 + 复权因子（新建/未占用表）：`fut_daily`/`opt_daily`/`adj_factor_ts`、future/option bar | 中（单位换算） | 行情入新表 + 明细 |
| **P5** | 主源切换（既有表 ownership 转移）：stock/index/etf bar、instruments、calendar | **高** | 逐表评估后显式转移，需用户确认 |

每阶段产出独立、可单独入库；P0–P4 全程零所有权冲突，P5 单独评估。

> 港股（HK）不在本计划内（D3）；如后续纳入，单列迭代处理 `meta.instruments` CHECK 约束变更 + `market.hk_bar_1d` + `XHKG`。

## 10. 测试策略

- **Fake `TushareClient`**：模拟 `pro.<api>()→DataFrame`，覆盖翻页（>5000 行）、限流退避、字段缺失兜底。fetcher 测试不依赖真实 token。
- raw 测试：Fake client → parquet 落盘断言（schema/列/单位不变）。
- ingest 测试：parquet fixture → importer.build() → DataFrame 与 `TableContract.columns` 严格对齐；归一化（代码后缀、单位换算）单测。
- 集成测试（`@integration`）：docker PostgreSQL，建表→upsert→ownership 校验。
- `@live_sdk` 标记真实 token 用例，默认 skip。

## 11. 文档与运维

- 新增 `docs/providers/tushare.md`：接口清单、dataset→表映射、单位/复权口径、配置项、运行示例。
- `docs/conventions/symbol-mapping.md` 补 tushare 行 + `BJ→XBSE`。
- 每阶段在 `ITER.md` 记录迭代条目（AGENTS.md 强制）。
- secrets：`TUSHARE_TOKEN` 仅经环境变量，禁止入库/入仓。

## 12. 待办 / 风险清单

1. **单位换算系数**（§6.2）：实现行情 importer 前必须核对 yinhe 现有 `volume/amount` 单位。
2. **主源切换**（P5）：每张既有表转移前需做 Tushare vs 原 owner 数据一致性评估，单独确认。
3. **积分档限流**：`rate_limit` 需按实际 Tushare 账号积分档调参，避免触发风控。
4. **财报核心列选取**：P1 实现时按接口字段确定哪些进实体列、哪些只留 JSONB。
5. 默认项（D9）若需调整（依赖版本、token 变量名、限流策略），在 P0 前提出。
