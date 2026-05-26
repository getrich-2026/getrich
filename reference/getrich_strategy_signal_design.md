# GetRich 策略与信号模块 — 前端展示与接口设计文档

> 文档版本：v1.2  
> 更新日期：2026-05-22  
> 项目代号：GetRich  
> 协议规范：RESTful API + WebSocket（实时信号推送）  
> 后端存储：PostgreSQL（全量业务数据）

---

## 目录

1. [设计概述与架构选型](#一、设计概述与架构选型)
2. [接口通用规范](#二接口通用规范)
3. [数据模型与表结构](#三数据模型与表结构)
4. [策略模块接口](#四策略模块接口)
5. [信号模块接口](#五信号模块接口)
6. [支付回调接口](#六、支付回调接口)
7. [WebSocket 实时推送](#七websocket-实时推送)
8. [前端页面设计](#八前端页面设计)
9. [附录：数据字典与枚举](#九附录数据字典与枚举)

---

## 一、设计概述与架构选型

### 1.1 业务场景

GetRich 平台聚焦 **A 股、期货、期权** 三大资产类别的量化策略展示与信号分发。核心用户路径为：

```
浏览策略列表 → 查看策略详情（绩效/回测/持仓） → 订阅策略 → 接收实时信号 → 查看信号详情 → 执行反馈
```

### 1.2 技术选型

| 层级 | 技术选择 | 选型理由 |
|------|----------|----------|
| 前端框架 | React 19 + TypeScript 5.9 | 类型安全，生态成熟 |
| 状态管理 | @tanstack/react-query 5 | 异步状态管理 + 缓存自动失效 |
| 图表库 | ECharts 5 | 金融图表支持最完善（K线、资金曲线、热力图） |
| HTTP 客户端 | Axios | 拦截器 + 重试机制 |
| 实时通信 | WebSocket（原生） | 信号推送延迟 <100ms |
| 后端框架 | FastAPI (Python 3.10+) | 异步高性能，类型提示原生支持 |
| 数据库 | PostgreSQL 16 | 全量业务数据：策略元数据、用户关系、订阅状态、时序净值曲线、历史信号、交易记录 |
| 缓存 | Redis 7（P1 待实现） | 热点策略排行、信号未读计数、WebSocket 会话管理 |
| 消息队列 | Redis Streams（P1 待实现） | 信号广播、异步通知 |

### 1.3 核心设计原则

1. **读写分离**：PostgreSQL 承载所有持久化数据（净值曲线、信号历史、订阅、元数据）；Redis 缓存层（P1 待实现）后续承载高频热点读（排行榜、未读计数）  
2. **分层缓存**：当前由前端 React Query 缓存列表（staleTime 30s）；Redis 缓存层（P1 待实现）后续补充策略摘要（TTL 5min）、排行榜（TTL 1min）  
3. **渐进加载**：策略详情页分 3 次请求——基础信息（<100ms）→ 绩效指标（<200ms）→ 净值曲线（<500ms）  
4. **信号实时性**：信号产生 → Redis Streams 广播 → WebSocket 推送，端到端延迟目标 <500ms  

### 1.4 实现流程总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          数据生产层                                      │
│  策略引擎 ──→ 信号产生 ──→ 信号持久化(PG)                            │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ publish
┌──────────────────────────▼──────────────────────────────────────────────┐
│                          推送层                                          │
│  WebSocket Hub ──→ 按用户订阅关系分发 ──→ 客户端实时接收                   │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────────┐
│                          API 层 (FastAPI)                                │
│  /strategies/*   /signals/*   /user/subscriptions/*                      │
│  ├─ PostgreSQL (元数据/订阅/时序数据)                                      │
│  └─ Redis       (缓存/计数)                                              │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────────┐
│                          前端展示层 (React)                               │
│  策略列表页 ──→ 策略详情页 ──→ 信号列表页 ──→ 信号详情页                    │
│  ├─ React Query (数据获取 + 缓存)                                        │
│  ├─ ECharts     (净值曲线/回撤/月度收益热力图)                             │
│  └─ WebSocket   (信号实时推送)                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、接口通用规范

### 2.1 基础信息

| 项目 | 说明 |
|------|------|
| 基础 URL | `https://api.getrich.millerquant.com/v1` |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |
| 时间格式 | ISO 8601（例：`2026-04-15T09:30:00+08:00`） |
| 日期格式 | `YYYY-MM-DD` |
| 金额精度 | 价格保留 4 位小数，收益率保留 4 位小数（百分比展示时 ×100） |

### 2.2 请求头规范

```http
Content-Type: application/json
Authorization: Bearer {access_token}       # 预留：当前暂未强制校验（使用 X-User-Id mock）
X-Request-ID: {uuid}
X-Client-Version: 1.0.0
X-Device-Type: web|ios|android
```

> **当前认证状态**：JWT Bearer Token 方案已定义但尚未落地。开发/测试环境目前通过 `X-User-Id` 请求头 mock 用户身份。前端 `client.ts` 在 `VITE_DEMO_USER_ID` 模式下自动注入该头。

### 2.3 统一响应结构

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "timestamp": 1744694400,
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 2.4 错误码体系

| 错误码 | 说明 | 处理建议 |
|--------|------|----------|
| 0 | 成功 | — |
| 1001 | 参数校验失败 | 检查请求参数格式 |
| 1002 | 未授权 | 重新登录获取 token |
| 1003 | 权限不足 | 升级会员等级 |
| 1004 | 资源不存在 | 确认 ID 是否正确 |
| 1005 | 请求频率超限 | 降频或稍后重试 |
| 1006 | 服务内部错误 | 联系技术支持 |
| 2001 | Token 已过期 | 使用 refresh_token 刷新 |
| 2002 | Token 无效 | 重新登录 |
| 3001 | 订阅额度已满 | 取消部分订阅或升级套餐 |
| 3002 | 策略已下架 | 选择其他策略 |
| 3003 | 信号数据不可用 | 策略暂停运行，等待恢复 |
| 4001 | 时序数据查询超时 | 缩小时间范围重试 |

### 2.5 分页规范

**请求参数：**

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| page | int | 页码，从 1 开始 | 1 |
| page_size | int | 每页数量，上限 100 | 20 |

**响应结构：**

```json
{
  "list": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 256,
    "total_pages": 13,
    "has_more": true
  }
}
```

---

## 三、数据模型与表结构

### 3.1 PostgreSQL 表（业务元数据）

#### 3.1.1 strategies — 策略主表

```sql
CREATE TABLE strategies (
    id              VARCHAR(32)     PRIMARY KEY,        -- 策略ID，如 "STR_FUT_001"
    name            VARCHAR(128)    NOT NULL,           -- 策略名称
    description     TEXT,                               -- 策略简介（Markdown）
    detail_html     TEXT,                               -- 策略详细说明（富文本）
    category_id     VARCHAR(16)     NOT NULL,           -- 分类ID
    asset_class     VARCHAR(16)     NOT NULL,           -- 资产类别: stock/future/option
    market          VARCHAR(16)     NOT NULL DEFAULT 'cn', -- 市场: cn/hk/us
    risk_level      VARCHAR(8)      NOT NULL,           -- 风险等级: low/medium/high
    status          VARCHAR(16)     NOT NULL DEFAULT 'active', -- 状态: active/paused/archived
    creator_id      VARCHAR(32)     NOT NULL,           -- 策略作者ID
    cover_image     VARCHAR(512),                       -- 策略封面图URL
    
    -- 订阅定价
    subscription_monthly  DECIMAL(10,2)  DEFAULT 0,     -- 月订阅价格（0 = 免费）
    subscription_yearly   DECIMAL(10,2)  DEFAULT 0,     -- 年订阅价格
    
    -- 标签与配置
    tags            JSONB           DEFAULT '[]',       -- 标签列表 ["趋势跟踪","股指期货"]
    config          JSONB           DEFAULT '{}',       -- 策略配置参数（对外展示部分）
    
    -- 统计冗余字段（由定时任务刷新）
    subscriber_count    INT         DEFAULT 0,
    total_signal_count  INT         DEFAULT 0,
    
    -- 回测区间
    backtest_start  DATE,
    backtest_end    DATE,
    
    -- 版本管理
    version         VARCHAR(16)     NOT NULL,          -- 记录版本（变更）
    version_reason  VARCHAR(16)     NOT NULL,          -- 变更原因
    
    -- 时间戳
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ                         -- 首次发布时间
);

-- 索引
CREATE INDEX idx_strategies_category ON strategies(category_id);
CREATE INDEX idx_strategies_asset ON strategies(asset_class);
CREATE INDEX idx_strategies_status ON strategies(status);
CREATE INDEX idx_strategies_tags ON strategies USING GIN(tags);
```

#### 3.1.2 strategy_categories — 策略分类表

```sql
CREATE TABLE strategy_categories (
    id          VARCHAR(16)     PRIMARY KEY,
    name        VARCHAR(64)     NOT NULL,
    description VARCHAR(256),
    icon_url    VARCHAR(512),
    sort_order  INT             DEFAULT 0,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
```

#### 3.1.3 signals — 信号主表

```sql
CREATE TABLE signals (
    id              VARCHAR(32)     PRIMARY KEY,        -- 信号ID，如 "SIG_20260415_001"
    strategy_id     VARCHAR(32)     NOT NULL REFERENCES strategies(id),
    
    -- 信号核心字段
    signal_type     VARCHAR(16)     NOT NULL,           -- 类型: entry/exit/adjust/alert
    action          VARCHAR(8)      NOT NULL,           -- 操作: buy/sell/hold/close
    direction       VARCHAR(8),                         -- 方向: long/short（期货/期权专用）
    
    -- 标的信息
    symbol          VARCHAR(32)     NOT NULL,           -- 合约/股票代码
    symbol_name     VARCHAR(64),                        -- 标的名称
    exchange        VARCHAR(16),                        -- 交易所: SSE/SZSE/CFFEX/SHFE/DCE/CZCE
    
    -- 价格与数量
    trigger_price   DECIMAL(16,4),                      -- 触发价格
    target_price    DECIMAL(16,4),                      -- 目标价格
    stop_loss_price DECIMAL(16,4),                      -- 止损价格
    suggested_quantity  INT,                            -- 建议数量/手数
    position_pct    DECIMAL(5,4),                       -- 建议仓位比例（0.0000~1.0000）
    
    -- 信号质量
    confidence      DECIMAL(3,2)    NOT NULL DEFAULT 0.50, -- 置信度 0.00~1.00
    urgency         VARCHAR(8)      DEFAULT 'normal',   -- 紧急程度: low/normal/high/critical
    
    -- 触发上下文
    reason          TEXT,                               -- 触发原因（简述）
    reason_detail   JSONB           DEFAULT '{}',       -- 详细触发数据（指标快照等）
    
    -- 期权专用字段
    option_type     VARCHAR(4),                         -- call/put
    strike_price    DECIMAL(16,4),                      -- 行权价
    expiry_date     DATE,                               -- 到期日
    greeks          JSONB,                              -- Delta/Gamma/Theta/Vega 快照
    
    -- 状态追踪
    status          VARCHAR(16)     DEFAULT 'active',   -- active/expired/cancelled
    expired_at      TIMESTAMPTZ,                        -- 信号过期时间
    
    -- 时间戳
    trigger_time    TIMESTAMPTZ     NOT NULL,           -- 信号产生时间（策略引擎时间）
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    
    -- 关联信号（用于 entry/exit 配对）
    parent_signal_id VARCHAR(32)    REFERENCES signals(id)
);

-- 核心索引
CREATE INDEX idx_signals_strategy ON signals(strategy_id, trigger_time DESC);
CREATE INDEX idx_signals_symbol ON signals(symbol, trigger_time DESC);
CREATE INDEX idx_signals_type_action ON signals(signal_type, action);
CREATE INDEX idx_signals_status ON signals(status);
CREATE INDEX idx_signals_trigger_time ON signals(trigger_time DESC);
```

#### 3.1.4 user_subscriptions — 用户订阅关系表

```sql
CREATE TABLE user_subscriptions (
    id              VARCHAR(32)     PRIMARY KEY,
    user_id         VARCHAR(32)     NOT NULL,
    strategy_id     VARCHAR(32)     NOT NULL REFERENCES strategies(id),
    
    status          VARCHAR(16)     NOT NULL DEFAULT 'active', -- active/expired/cancelled
    plan_type       VARCHAR(16)     NOT NULL,           -- monthly/yearly/lifetime
    auto_renew      BOOLEAN         DEFAULT TRUE,
    
    start_date      DATE            NOT NULL,
    expire_date     DATE            NOT NULL,
    
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    
    UNIQUE(user_id, strategy_id)
);

CREATE INDEX idx_subscriptions_user ON user_subscriptions(user_id, status);
CREATE INDEX idx_subscriptions_strategy ON user_subscriptions(strategy_id);
```

#### 3.1.5 user_signal_reads — 用户信号已读状态表

```sql
CREATE TABLE user_signal_reads (
    user_id         VARCHAR(32)     NOT NULL,
    signal_id       VARCHAR(32)     NOT NULL REFERENCES signals(id),
    read_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_executed     BOOLEAN         DEFAULT FALSE,
    executed_price  DECIMAL(16,4),
    executed_at     TIMESTAMPTZ,
    note            TEXT,
    
    PRIMARY KEY(user_id, signal_id)
);
```

### 3.2 PostgreSQL 时序表（历史数据）

#### 3.2.1 strategy_equity_curve — 策略净值曲线

```sql
CREATE TABLE strategy_equity_curve (
    strategy_id     VARCHAR(32)     NOT NULL REFERENCES strategies(id),
    trade_date      DATE            NOT NULL,
    nav             FLOAT8          NOT NULL,   -- 单位净值（基准 1.0）
    cumulative_return  FLOAT8,                  -- 累计收益率
    daily_return    FLOAT8,                     -- 当日收益率
    drawdown        FLOAT8,                     -- 当前回撤幅度（负值）
    benchmark_nav   FLOAT8,                     -- 基准净值（如沪深300）
    position_ratio  FLOAT8,                     -- 当日仓位比例

    PRIMARY KEY (strategy_id, trade_date)
);

CREATE INDEX idx_equity_curve_strategy ON strategy_equity_curve(strategy_id, trade_date DESC);
```

#### 3.2.2 strategy_performance_snapshot — 策略绩效快照

```sql
CREATE TABLE strategy_performance_snapshot (
    strategy_id         VARCHAR(32)     NOT NULL REFERENCES strategies(id),
    snapshot_date       DATE            NOT NULL,   -- 快照日期

    -- 收益指标
    total_return        FLOAT8,
    annualized_return   FLOAT8,
    ytd_return          FLOAT8,         -- 今年以来收益
    recent_1m_return    FLOAT8,         -- 近1月
    recent_3m_return    FLOAT8,         -- 近3月
    recent_6m_return    FLOAT8,         -- 近6月
    recent_1y_return    FLOAT8,         -- 近1年

    -- 风险指标
    max_drawdown        FLOAT8,
    annualized_volatility FLOAT8,
    downside_deviation  FLOAT8,

    -- 风险调整指标
    sharpe_ratio        FLOAT8,
    sortino_ratio       FLOAT8,
    calmar_ratio        FLOAT8,
    information_ratio   FLOAT8,

    -- 交易统计
    total_trades        INTEGER,
    win_rate            FLOAT8,
    profit_factor       FLOAT8,
    avg_win             FLOAT8,
    avg_loss            FLOAT8,
    max_consecutive_wins  INTEGER,
    max_consecutive_losses INTEGER,
    avg_holding_days    FLOAT8,

    -- 风控指标
    var_95              FLOAT8,         -- 95% VaR（日度）
    cvar_95             FLOAT8,         -- 95% CVaR
    beta                FLOAT8,         -- 相对基准 Beta
    alpha               FLOAT8,         -- Jensen's Alpha

    PRIMARY KEY (strategy_id, snapshot_date)
);

CREATE INDEX idx_perf_snapshot_strategy ON strategy_performance_snapshot(strategy_id, snapshot_date DESC);
```

#### 3.2.3 strategy_monthly_returns — 月度收益矩阵

```sql
CREATE TABLE strategy_monthly_returns (
    strategy_id     VARCHAR(32)     NOT NULL REFERENCES strategies(id),
    year            SMALLINT        NOT NULL,
    month           SMALLINT        NOT NULL,
    monthly_return  FLOAT8          NOT NULL,

    PRIMARY KEY (strategy_id, year, month)
);
```

#### 3.2.4 signal_market_snapshot — 信号触发时刻行情快照

```sql
CREATE TABLE signal_market_snapshot (
    signal_id       VARCHAR(32)     NOT NULL REFERENCES signals(id),
    symbol          VARCHAR(32)     NOT NULL,
    snapshot_time   TIMESTAMPTZ     NOT NULL,

    -- OHLCV
    open            FLOAT8,
    high            FLOAT8,
    low             FLOAT8,
    close           FLOAT8,
    volume          BIGINT,
    turnover        FLOAT8,         -- 成交额

    -- 技术指标快照
    ma5             FLOAT8,
    ma10            FLOAT8,
    ma20            FLOAT8,
    ma60            FLOAT8,
    rsi_14          FLOAT8,
    macd            FLOAT8,
    macd_signal     FLOAT8,
    macd_hist       FLOAT8,
    atr_14          FLOAT8,
    bollinger_upper FLOAT8,
    bollinger_lower FLOAT8,

    -- 市场微结构（期货专用）
    open_interest   BIGINT,         -- 持仓量
    basis           FLOAT8,         -- 基差

    -- 期权专用
    implied_vol     FLOAT8,         -- 隐含波动率
    delta           FLOAT8,
    gamma           FLOAT8,
    theta           FLOAT8,
    vega            FLOAT8,

    PRIMARY KEY (signal_id, symbol, snapshot_time)
);

CREATE INDEX idx_market_snapshot_signal ON signal_market_snapshot(signal_id);
```

### 3.3 Redis 缓存结构（P1 待实现）

> 当前尚未接入 Redis，以下为规划中的缓存方案。上线后根据 PostgreSQL 负载观察结果决定是否实施。

| Key 模式 | 数据类型 | TTL | 说明 |
|----------|----------|-----|------|
| `str:summary:{strategy_id}` | Hash | 5min | 策略摘要（避免高频查数据库） |
| `str:rank:{sort_field}` | Sorted Set | 1min | 策略排行榜 |
| `sig:unread:{user_id}` | Hash | — | 各策略未读信号计数 |
| `sig:unread_total:{user_id}` | String | — | 总未读数 |
| `ws:session:{user_id}` | String | 心跳续期 | WebSocket 会话 ID |
| `str:perf:{strategy_id}` | String(JSON) | 10min | 绩效指标快照 |

---

## 四、策略模块接口

### 4.1 获取策略分类列表

**GET** `/strategies/categories`

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "categories": [
      {
        "id": "CAT_TREND",
        "name": "趋势跟踪",
        "description": "基于价格趋势与动量的策略",
        "icon_url": "https://cdn.getrich.com/icons/trend.svg",
        "strategy_count": 18
      },
      {
        "id": "CAT_MR",
        "name": "均值回归",
        "description": "利用价格偏离均值后的回归特性",
        "icon_url": "https://cdn.getrich.com/icons/mr.svg",
        "strategy_count": 12
      },
      {
        "id": "CAT_ARB",
        "name": "套利策略",
        "description": "跨期、跨品种、期现套利",
        "icon_url": "https://cdn.getrich.com/icons/arb.svg",
        "strategy_count": 8
      },
      {
        "id": "CAT_FACTOR",
        "name": "多因子选股",
        "description": "基于量价、基本面、另类因子的选股模型",
        "icon_url": "https://cdn.getrich.com/icons/factor.svg",
        "strategy_count": 22
      },
      {
        "id": "CAT_OPTION",
        "name": "期权策略",
        "description": "波动率交易、组合策略、对冲",
        "icon_url": "https://cdn.getrich.com/icons/option.svg",
        "strategy_count": 6
      }
    ]
  }
}
```

---

### 4.2 获取策略列表

**GET** `/strategies`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category_id | string | 否 | 分类 ID |
| asset_class | string | 否 | 资产类别：`stock`/`future`/`option`/`all` |
| risk_level | string | 否 | 风险等级：`low`/`medium`/`high`/`all` |
| sort | string | 否 | 排序字段：`annualized_return`/`sharpe`/`max_drawdown`/`subscribers`/`newest`，默认 `sharpe` |
| sort_order | string | 否 | `desc`（默认）/`asc` |
| keyword | string | 否 | 搜索关键词（匹配名称、标签、描述） |
| status | string | 否 | 状态：`active`/`all`，默认 `active` |
| page | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "id": "STR_FUT_001",
        "name": "股指期货跨期套利",
        "description": "基于 IF/IH/IC 不同月份合约价差的统计套利策略，利用价差偏离历史均值时的回归特性进行交易。",
        "category": {
          "id": "CAT_ARB",
          "name": "套利策略"
        },
        "asset_class": "future",
        "market": "cn",
        "risk_level": "medium",
        "status": "active",
        "cover_image": "https://cdn.getrich.com/strategy/str_fut_001_cover.png",
        "tags": ["股指期货", "跨期套利", "统计套利"],
        "performance": {
          "annualized_return": 0.1710,
          "max_drawdown": -0.1190,
          "sharpe_ratio": 1.85,
          "win_rate": 0.6250,
          "total_trades": 156,
          "recent_1m_return": 0.0234,
          "ytd_return": 0.0812
        },
        "backtest_period": {
          "start": "2020-01-01",
          "end": "2026-04-14"
        },
        "subscriber_count": 1258,
        "is_subscribed": false,
        "subscription_price": {
          "monthly": 99.00,
          "yearly": 899.00
        },
        "last_signal_time": "2026-04-14T14:30:00+08:00",
        "updated_at": "2026-04-15T08:00:00+08:00"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 66,
      "total_pages": 4,
      "has_more": true
    },
    "filters_summary": {
      "total_strategies": 66,
      "by_asset_class": {
        "stock": 28,
        "future": 24,
        "option": 14
      }
    }
    "order": {
      "field": "sharpe",
      "direction": "desc"
    }
  }
}
```

---

### 4.3 获取策略详情

**GET** `/strategies/{strategy_id}`

> 这是策略详情页的核心接口，返回完整信息。前端可拆分为多次请求以实现渐进加载。

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "id": "STR_FUT_001",
    "name": "股指期货跨期套利",
    "description": "基于 IF/IH/IC 不同月份合约价差的统计套利策略...",
    "detail_html": "<div>策略的详细介绍富文本...</div>",
    "category": {
      "id": "CAT_ARB",
      "name": "套利策略"
    },
    "asset_class": "future",
    "market": "cn",
    "risk_level": "medium",
    "status": "active",
    "tags": ["股指期货", "跨期套利", "统计套利"],

    "creator": {
      "id": "AU_001",
      "name": "MillerQuant 研究团队",
      "avatar": "https://cdn.getrich.com/avatar/mq_team.jpg",
      "bio": "专注期货量化策略研究，团队核心成员均有 5 年以上实盘经验"
    },

    "performance": {
      "total_return": 0.5610,
      "annualized_return": 0.1710,
      "ytd_return": 0.0812,
      "recent_1m_return": 0.0234,
      "recent_3m_return": 0.0567,
      "recent_6m_return": 0.1023,
      "recent_1y_return": 0.1890,
      "max_drawdown": -0.1190,
      "annualized_volatility": 0.0924,
      "downside_deviation": 0.0651,
      "sharpe_ratio": 1.85,
      "sortino_ratio": 2.63,
      "calmar_ratio": 1.44,
      "information_ratio": 1.12,
      "win_rate": 0.6250,
      "profit_factor": 1.78,
      "total_trades": 156,
      "avg_win": 0.0245,
      "avg_loss": -0.0123,
      "max_consecutive_wins": 8,
      "max_consecutive_losses": 4,
      "avg_holding_days": 3.2,
      "var_95": -0.0250,
      "cvar_95": -0.0320,
      "beta": 0.15,
      "alpha": 0.1450
    },

    "backtest_period": {
      "start": "2020-01-01",
      "end": "2026-04-14"
    },

    "config_display": {
      "universe": "IF/IH/IC 当月 & 次月合约",
      "rebalance_freq": "日内",
      "benchmark": "中证500指数",
      "initial_capital": 1000000,
      "slippage": "1 tick",
      "commission": "万分之 0.23"
    },

    "subscriber_count": 1258,
    "total_signal_count": 156,
    "is_subscribed": true,
    "subscription_info": {
      "subscription_id": "SUB_001",
      "plan_type": "yearly",
      "start_date": "2026-01-01",
      "expire_date": "2026-12-31",
      "auto_renew": true
    },
    "subscription_price": {
      "monthly": 99.00,
      "yearly": 899.00
    },

    "recent_signals": [
      {
        "id": "SIG_20260414_003",
        "action": "buy",
        "direction": "long",
        "symbol": "IF2506",
        "trigger_price": 3650.00,
        "trigger_time": "2026-04-14T14:30:00+08:00",
        "confidence": 0.85
      }
    ],

    "updated_at": "2026-04-15T08:00:00+08:00",
    "published_at": "2020-03-15T10:00:00+08:00"
  }
}
```

---

### 4.4 获取策略净值曲线

**GET** `/strategies/{strategy_id}/equity-curve`

> 数据源：PostgreSQL `strategy_equity_curve` 表。前端使用 ECharts 渲染。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| period | string | 否 | 预设区间：`1m`/`3m`/`6m`/`1y`/`3y`/`all`，默认 `all` |
| start_date | string | 否 | 自定义开始日期（优先于 period） |
| end_date | string | 否 | 自定义结束日期 |
| include_benchmark | boolean | 否 | 是否包含基准曲线，默认 `true` |
| include_drawdown | boolean | 否 | 是否包含回撤曲线，默认 `true` |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "strategy_id": "STR_FUT_001",
    "period": {
      "start": "2020-01-01",
      "end": "2026-04-14"
    },
    "equity_curve": [
      {
        "date": "2020-01-02",
        "nav": 1.0012,
        "cumulative_return": 0.0012,
        "daily_return": 0.0012,
        "position_ratio": 0.65
      }
    ],
    "benchmark_curve": [
      {
        "date": "2020-01-02",
        "nav": 1.0008
      }
    ],
    "drawdown_curve": [
      {
        "date": "2020-01-02",
        "drawdown": 0.0
      }
    ],
    "total_points": 1540
  }
}
```

---

### 4.5 获取月度收益矩阵

**GET** `/strategies/{strategy_id}/monthly-returns`

> 前端渲染为热力图（年 × 月），用于直观展示策略的收益分布。

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "strategy_id": "STR_FUT_001",
    "matrix": [
      {
        "year": 2024,
        "months": [0.032, -0.015, 0.041, 0.018, -0.008, 0.025, 0.012, -0.021, 0.035, 0.028, -0.005, 0.019],
        "yearly_return": 0.168
      },
      {
        "year": 2025,
        "months": [0.021, 0.015, -0.012, 0.038, 0.009, -0.003, 0.027, 0.014, 0.031, -0.011, 0.022, 0.016],
        "yearly_return": 0.175
      },
      {
        "year": 2026,
        "months": [0.028, 0.019, 0.025, null, null, null, null, null, null, null, null, null],
        "yearly_return": 0.074
      }
    ]
  }
}
```

---

### 4.6 获取策略回测报告

**GET** `/strategies/{strategy_id}/backtest-report`

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "strategy_id": "STR_FUT_001",
    "summary": {
      "backtest_start": "2020-01-01",
      "backtest_end": "2026-04-14",
      "initial_capital": 1000000,
      "final_capital": 1561000,
      "total_return": 0.5610,
      "annualized_return": 0.1710,
      "max_drawdown": -0.1190,
      "max_drawdown_start": "2022-03-15",
      "max_drawdown_end": "2022-06-20",
      "max_drawdown_recovery": "2022-09-10",
      "sharpe_ratio": 1.85
    },
    "risk_analysis": {
      "var_95": -0.0250,
      "cvar_95": -0.0320,
      "beta": 0.15,
      "alpha": 0.1450,
      "max_single_day_loss": -0.0385,
      "max_single_day_gain": 0.0420
    },
    "trade_analysis": {
      "total_trades": 156,
      "win_rate": 0.6250,
      "avg_trade_return": 0.0036,
      "avg_holding_days": 3.2,
      "profit_factor": 1.78
    },
    "annual_performance": [
      {"year": 2020, "return": 0.142, "max_drawdown": -0.089, "sharpe": 1.62, "trades": 24},
      {"year": 2021, "return": 0.185, "max_drawdown": -0.072, "sharpe": 2.15, "trades": 28},
      {"year": 2022, "return": 0.098, "max_drawdown": -0.119, "sharpe": 1.23, "trades": 32},
      {"year": 2023, "return": 0.165, "max_drawdown": -0.068, "sharpe": 1.95, "trades": 26},
      {"year": 2024, "return": 0.168, "max_drawdown": -0.075, "sharpe": 1.88, "trades": 24},
      {"year": 2025, "return": 0.175, "max_drawdown": -0.062, "sharpe": 2.08, "trades": 22}
    ]
  }
}
```

---

### 4.7 获取策略历史交易记录

**GET** `/strategies/{strategy_id}/trades`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| start_date | string | 否 | 开始日期 |
| end_date | string | 否 | 结束日期 |
| action | string | 否 | 筛选：`all`/`buy`/`sell` |
| result | string | 否 | 结果筛选：`all`/`win`/`loss` |
| page | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "trade_id": "TRD_001",
        "entry_signal_id": "SIG_20260410_001",
        "exit_signal_id": "SIG_20260412_002",
        "symbol": "IF2506",
        "direction": "long",
        "entry_price": 3620.00,
        "entry_time": "2026-04-10T09:35:00+08:00",
        "exit_price": 3680.00,
        "exit_time": "2026-04-12T14:30:00+08:00",
        "quantity": 1,
        "pnl": 18000.00,
        "return_pct": 0.0166,
        "holding_days": 2,
              }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 156,
      "total_pages": 8,
      "has_more": true
    }
  }
}
```

---

### 4.8 订阅策略

**POST** `/strategies/{strategy_id}/subscribe`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| plan_type | string | 是 | `monthly`/`yearly` |
| auto_renew | boolean | 否 | 自动续费，默认 `true` |
| payment_source | string | 是 | `wechat`/`alipay`/`bank` |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "subscription_id": "SUB_002",
    "status": "pending_payment",
    "plan_type": "yearly",
    "start_date": "2026-04-15",
    "expire_date": "2027-04-15",
    "payment": {
      "order_id": "ORD_20260415_001",
      "amount": 899.00,
      "payment_source": "wechat",
      "expire_time": "2026-04-15T11:30:00+08:00"
    }
  }
}
```

---

### 4.9 取消订阅

**POST** `/strategies/{strategy_id}/unsubscribe`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| reason | string | 否 | 取消原因 |

---
### 4.10 获取策略历史信号列表

**GET** `/strategies/{strategy_id}/signals`

> 返回指定策略的历史信号，登录用户附带 is_read/is_executed。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 否 | 信号类型：`entry`/`exit`/`adjust`/`alert`/`all` |
| action | string | 否 | 操作方向：`buy`/`sell`/`hold`/`close`/`all` |
| status | string | 否 | 状态：`active`/`expired`/`cancelled`/`all` |
| page | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "id": "SIG_20260415_001",
        "signal_type": "entry",
        "action": "buy",
        "symbol": "IF2506",
        "trigger_price": 3650.00,
        "confidence": 0.85,
        "urgency": "high",
        "trigger_time": "2026-04-15T09:31:00+08:00",
        "is_read": false,
        "is_executed": false,
        "status": "active"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 89,
      "total_pages": 5,
      "has_more": true
    }
  }
}
```

---
### 4.11 查询策略订阅状态

**GET** `/strategies/{strategy_id}/subscription`

> 返回当前用户对该策略的最新有效订阅信息。

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "is_subscribed": true,
    "subscription_id": "SUB_001",
    "status": "active",
    "plan_type": "yearly",
    "start_date": "2026-01-01",
    "expire_date": "2026-12-31",
    "auto_renew": true,
    "subscription_price": {
      "monthly": 99.00,
      "yearly": 899.00
    }
  }
}
```

---
### 4.12 获取策略维度推送配置

**GET** `/strategies/{strategy_id}/signal-settings`

> 返回策略维度的推送设置，未配置时继承全局配置。

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "strategy_id": "STR_FUT_001",
    "enabled": true,
    "channels": {
      "app_push": true,
      "wechat_service": true
    },
    "urgency_filter": ["normal", "high", "critical"],
    "confidence_threshold": 0.5,
    "notify_entry_only": false
  }
}
```

---
### 4.13 更新策略维度推送配置

**PUT** `/strategies/{strategy_id}/signal-settings`

> 支持部分更新，仅传需修改的字段。未传入字段保持原值。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| enabled | boolean | 否 | 是否启用推送 |
| channels | object | 否 | 推送渠道开关 |
| urgency_filter | string[] | 否 | 紧急度过滤 |
| confidence_threshold | float | 否 | 置信度阈值（0~1） |
| notify_entry_only | boolean | 否 | 仅入场通知 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "strategy_id": "STR_FUT_001",
    "updated": true
  }
}
```

---

## 五、信号模块接口

### 5.1 获取用户信号流（聚合）

**GET** `/signals`

> 聚合当前用户所有已订阅策略的信号，按时间倒序排列。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| strategy_id | string | 否 | 筛选指定策略 |
| signal_type | string | 否 | `entry`/`exit`/`adjust`/`alert`/`all` |
| action | string | 否 | `buy`/`sell`/`hold`/`close`/`all` |
| asset_class | string | 否 | `stock`/`future`/`option`/`all` |
| is_read | boolean | 否 | 是否已读筛选 |
| confidence_min | float | 否 | 最低置信度筛选（0.0~1.0） |
| start_date | string | 否 | 开始日期 |
| end_date | string | 否 | 结束日期 |
| page | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "id": "SIG_20260415_001",
        "strategy": {
          "id": "STR_FUT_001",
          "name": "股指期货跨期套利"
        },
        "signal_type": "entry",
        "action": "buy",
        "direction": "long",
        "symbol": "IF2506",
        "symbol_name": "沪深300股指期货2506",
        "exchange": "CFFEX",
        "trigger_price": 3650.00,
        "target_price": 3700.00,
        "stop_loss_price": 3620.00,
        "confidence": 0.85,
        "urgency": "high",
        "reason": "IF 当月-次月价差偏离 2σ，触发均值回归开仓",
        "trigger_time": "2026-04-15T09:31:00+08:00",
        "is_read": false,
        "is_executed": false,
        "status": "active"
      },
      {
        "id": "SIG_20260415_002",
        "strategy": {
          "id": "STR_OPT_001",
          "name": "50ETF 波动率套利"
        },
        "signal_type": "entry",
        "action": "buy",
        "direction": "long",
        "symbol": "10006545",
        "symbol_name": "50ETF购4月3200",
        "exchange": "SSE",
        "trigger_price": 0.0520,
        "confidence": 0.72,
        "urgency": "normal",
        "reason": "隐含波动率低于历史 20 分位，买入跨式组合",
        "option_type": "call",
        "strike_price": 3.200,
        "expiry_date": "2026-04-23",
        "greeks": {
          "delta": 0.45,
          "gamma": 0.12,
          "theta": -0.008,
          "vega": 0.15
        },
        "trigger_time": "2026-04-15T09:35:00+08:00",
        "is_read": false,
        "is_executed": false,
        "status": "active"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 89,
      "total_pages": 5,
      "has_more": true
    },
    "unread_count": 12
  }
}
```

---

### 5.2 获取信号详情

**GET** `/signals/{signal_id}`

> 信号详情页的核心接口，除信号本身数据外，还包含触发时刻的行情快照和历史类似信号表现。

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "id": "SIG_20260415_001",

    "strategy": {
      "id": "STR_FUT_001",
      "name": "股指期货跨期套利",
      "category": "套利策略",
      "risk_level": "medium"
    },

    "signal_type": "entry",
    "action": "buy",
    "direction": "long",
    "symbol": "IF2506",
    "symbol_name": "沪深300股指期货2506",
    "exchange": "CFFEX",

    "trigger_price": 3650.00,
    "target_price": 3700.00,
    "stop_loss_price": 3620.00,
    "suggested_quantity": 1,
    "position_pct": 0.15,

    "confidence": 0.85,
    "urgency": "high",
    "reason": "IF 当月-次月价差偏离 2σ，触发均值回归开仓",
    "reason_detail": {
      "spread_current": 12.4,
      "spread_mean": 5.2,
      "z_score": 2.0,
      "trigger_rule": "z_score > 2.0 且持仓量放大"
    },

    "trigger_time": "2026-04-15T09:31:00+08:00",
    "status": "active",
    "expired_at": "2026-04-15T15:00:00+08:00",

    "market_snapshot": {
      "symbol": "IF2506",
      "snapshot_time": "2026-04-15T09:31:00+08:00",
      "open": 3645.00,
      "high": 3658.00,
      "low": 3640.00,
      "close": 3650.00,
      "volume": 25680,
      "open_interest": 124500,
      "indicators": {
        "ma5": 3642.00,
        "ma20": 3618.00,
        "rsi_14": 62.3,
        "atr_14": 35.6
      }
    },

    "historical_performance": {
      "similar_signals_count": 23,
      "win_rate": 0.7391,
      "avg_return": 0.0185,
      "avg_holding_days": 2.8
    },

    
    "user_state": {
      "is_read": true,
      "read_at": "2026-04-15T09:32:00+08:00",
      "is_executed": false,
      "executed_price": null,
      "executed_at": null,
      "note": null
    }
  }
}
```

---

### 5.3 标记信号已读

**POST** `/signals/{signal_id}/read`

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "signal_id": "SIG_20260415_001",
    "is_read": true,
    "read_at": "2026-04-15T09:32:00+08:00",
    "remaining_unread": 11
  }
}
```

---

### 5.4 记录信号执行反馈

**POST** `/signals/{signal_id}/execute`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| executed_price | decimal | 否 | 实际执行价格 |
| executed_quantity | int | 否 | 实际执行数量 |
| executed_at | string | 否 | 执行时间（ISO 8601），不传则取当前时间 |
| note | string | 否 | 执行备注 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "signal_id": "SIG_20260415_001",
    "is_executed": true,
    "executed_price": 3652.00,
    "executed_at": "2026-04-15T09:33:00+08:00",
    "slippage": 2.00,
    "slippage_pct": 0.0005
  }
}
```

---

### 5.5 获取未读信号统计

**GET** `/signals/unread-summary`

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "total_unread": 12,
    "by_strategy": [
      {
        "strategy_id": "STR_FUT_001",
        "strategy_name": "股指期货跨期套利",
        "unread_count": 5,
        "latest_signal_time": "2026-04-15T09:31:00+08:00"
      },
      {
        "strategy_id": "STR_OPT_001",
        "strategy_name": "50ETF 波动率套利",
        "unread_count": 3,
        "latest_signal_time": "2026-04-15T09:35:00+08:00"
      },
      {
        "strategy_id": "STR_STK_002",
        "strategy_name": "多因子选股 Alpha",
        "unread_count": 4,
        "latest_signal_time": "2026-04-14T15:00:00+08:00"
      }
    ],
    "by_urgency": {
      "critical": 1,
      "high": 3,
      "normal": 6,
      "low": 2
    }
  }
}
```

---

### 5.6 获取信号推送配置

**GET** `/user/signal-settings`

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "push_enabled": true,
    "channels": {
      "app_push": true,
      "sms": false,
      "email": true,
      "wechat_service": true,
      "websocket": true
    },
    "global_settings": {
      "confidence_threshold": 0.60,
      "urgency_filter": ["normal", "high", "critical"],
      "quiet_hours": {
        "enabled": true,
        "start": "22:00",
        "end": "08:30"
      },
      "trading_hours_only": true
    },
    "strategy_overrides": [
      {
        "strategy_id": "STR_FUT_001",
        "push_enabled": true,
        "confidence_threshold": 0.50,
        "notify_entry_only": false
      }
    ]
  }
}
```

---

### 5.7 更新信号推送配置

**PUT** `/user/signal-settings`

**请求参数：** 与 5.7 响应 `data` 结构一致，支持部分更新（仅传需修改的字段）。

---
### 5.8 获取用户订单列表

**GET** `/user/orders`

> 分页返回当前用户的全部订单，含订单行项目。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | 订单状态：`pending`/`paid`/`cancelled`/`refunded`/`all` |
| page | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "order_id": "ORD_20260415_001",
        "status": "paid",
        "total_amount": 899.00,
        "payment_source": "wechat",
        "created_at": "2026-04-15T10:00:00+08:00",
        "paid_at": "2026-04-15T10:02:30+08:00",
        "items": [
          {
            "item_type": "strategy_subscription",
            "item_id": "STR_FUT_001",
            "item_name": "股指期货跨期套利（年订阅）",
            "plan_type": "yearly",
            "amount": 899.00
          }
        ]
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 5,
      "total_pages": 1,
      "has_more": false
    }
  }
}
```

---

## 六、支付回调接口

### 6.1 支付结果回调

**POST** `/webhooks/payment`

> 由支付平台（微信/支付宝/银行）异步回调。
> - 以 `payment_ref` 去重（幂等），重复回调直接返回 200。
> - 验签：HMAC-SHA256（Header: `X-Webhook-Signature`）。
> - 成功后：orders.status=paid，user_strategy_subscriptions.status=active。

**请求头：**

| 头 | 必填 | 说明 |
|----|------|------|
| X-Webhook-Signature | 是 | HMAC-SHA256 签名（Hex 编码） |

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| order_id | string | 是 | 系统订单 ID |
| payment_ref | string | 是 | 第三方支付流水号（幂等键） |
| status | string | 是 | `success`/`failed`/`refunded` |
| amount | float | 是 | 实际支付金额 |
| payment_source | string | 是 | `wechat`/`alipay`/`bank`/`apple_pay`/`stripe` |
| paid_at | string | 否 | 支付完成时间 |

**响应数据：**

```json
{
  "code": 0,
  "data": {
    "order_id": "ORD_20260415_001",
    "processed": true
  }
}
```

---

## 七、WebSocket 实时推送

### 7.1 连接规范

| 项目 | 说明 |
|------|------|
| 连接地址 | `wss://ws.getrich.millerquant.com/v1` |
| 认证方式 | URL Query 参数：`?token={access_token}` |
| 心跳间隔 | 客户端每 **30 秒** 发送 ping，服务端 60 秒无心跳断开 |
| 重连策略 | 指数退避：1s → 2s → 4s → 8s → 16s → 30s（上限） |
| 消息压缩 | 支持 `permessage-deflate` |

### 7.2 消息格式

```json
{
  "type": "signal_push",
  "seq": 1234,
  "timestamp": 1744694460000,
  "data": {}
}
```

### 7.3 消息类型

| type | 方向 | 说明 |
|------|------|------|
| `ping` | C → S | 心跳 |
| `pong` | S → C | 心跳响应 |
| `subscribe` | C → S | 订阅频道 |
| `unsubscribe` | C → S | 取消订阅 |
| `signal_push` | S → C | 新交易信号推送 |
| `signal_update` | S → C | 信号状态更新（过期/取消） |
| `strategy_status` | S → C | 策略状态变更（暂停/恢复） |
| `error` | S → C | 错误消息 |

### 7.4 订阅信号频道

**客户端发送：**

```json
{
  "type": "subscribe",
  "channel": "signals",
  "data": {
    "strategy_ids": ["STR_FUT_001", "STR_OPT_001"],
    "min_confidence": 0.60,
    "urgency_filter": ["high", "critical"]
  }
}
```

**服务端确认：**

```json
{
  "type": "subscribe_ack",
  "channel": "signals",
  "data": {
    "subscribed_strategies": ["STR_FUT_001", "STR_OPT_001"],
    "active_filters": {
      "min_confidence": 0.60,
      "urgency_filter": ["high", "critical"]
    }
  }
}
```

### 7.5 信号推送消息

**服务端推送：**

```json
{
  "type": "signal_push",
  "seq": 5678,
  "timestamp": 1744694460000,
  "data": {
    "signal_id": "SIG_20260415_001",
    "strategy_id": "STR_FUT_001",
    "strategy_name": "股指期货跨期套利",
    "signal_type": "entry",
    "action": "buy",
    "direction": "long",
    "symbol": "IF2506",
    "symbol_name": "沪深300股指期货2506",
    "trigger_price": 3650.00,
    "target_price": 3700.00,
    "stop_loss_price": 3620.00,
    "confidence": 0.85,
    "urgency": "high",
    "reason": "IF 当月-次月价差偏离 2σ，触发均值回归开仓",
    "trigger_time": "2026-04-15T09:31:00+08:00"
  }
}
```

### 7.6 信号状态更新

```json
{
  "type": "signal_update",
  "seq": 5679,
  "timestamp": 1744730400000,
  "data": {
    "signal_id": "SIG_20260415_001",
    "status": "expired",
    "reason": "收盘未触及目标价，信号自动过期"
  }
}
```

---

## 八、前端页面设计

### 8.1 策略列表页

**页面路由：** `/strategies`

**布局结构：**

```
┌─────────────────────────────────────────────────────────────────┐
│  筛选栏：[资产类别] [分类标签] [风险等级] [排序方式] [关键词搜索] │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  策略卡片 A   │  │  策略卡片 B   │  │  策略卡片 C   │          │
│  │ ·封面图/缩略净值│ │              │  │              │          │
│  │ ·名称 + 标签   │ │              │  │              │          │
│  │ ·年化收益 夏普  │ │              │  │              │          │
│  │ ·最大回撤 胜率  │ │              │  │              │          │
│  │ ·订阅人数 价格  │ │              │  │              │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ─── 更多策略 (加载更多 / 分页) ───                               │
└─────────────────────────────────────────────────────────────────┘
```

**关键交互：**

- 排序切换实时刷新，使用 React Query 缓存上一次结果实现 optimistic update
- 策略卡片 hover 显示迷你净值曲线（ECharts tooltip）
- 标签支持多选筛选
- 无限滚动加载（移动端）/ 分页（桌面端）

**接口依赖：** `GET /strategies` + `GET /strategies/categories`

---

### 8.2 策略详情页

**页面路由：** `/strategies/{strategy_id}`

**渐进加载策略：**

| 加载阶段 | 接口 | 目标耗时 | 渲染内容 |
|----------|------|----------|----------|
| 第 1 阶段 | `GET /strategies/{id}` | <100ms | 基础信息、绩效摘要、订阅状态 |
| 第 2 阶段 | `GET /strategies/{id}/equity-curve` | <500ms | 净值曲线图 + 回撤图 |
| 第 3 阶段 | `GET /strategies/{id}/monthly-returns` | <300ms | 月度收益热力图 |
| 按需加载 | `GET /strategies/{id}/backtest-report` | <500ms | 完整回测报告（点击展开） |
| 按需加载 | `GET /strategies/{id}/trades` | <300ms | 历史交易记录表格（点击 Tab 切换） |

**布局结构：**

```
┌─────────────────────────────────────────────────────────────────┐
│  策略头部区域                                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 策略名称              [已订阅✓/订阅按钮]  [分享]           │    │
│  │ 分类标签 · 风险等级 · 资产类别 · 更新时间                   │    │
│  │ 策略简介文字（2-3行）                                      │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  绩效指标卡片区（6宫格）                                         │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│  │年化收益│ │最大回撤│ │夏普比率│ │胜率   │ │盈亏比 │ │今年收益│       │
│  │17.1% │ │-11.9%│ │ 1.85 │ │62.5% │ │ 1.78 │ │8.12% │       │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘       │
├─────────────────────────────────────────────────────────────────┤
│  净值曲线区域                                                    │
│  [1M] [3M] [6M] [1Y] [3Y] [ALL] [自定义]                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              📈 净值曲线 + 基准对比                        │    │
│  │                                                         │    │
│  │              📉 回撤曲线（联动 X 轴）                     │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  月度收益热力图                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │      Jan   Feb   Mar   Apr   May  ...  Dec   Year      │    │
│  │ 2024  ■■■   □□    ■■■■  ■■    □     ...  ■■   16.8%    │    │
│  │ 2025  ■■    ■     □□    ■■■   ■     ...  ■    17.5%    │    │
│  │ 2026  ■■■   ■■    ■■■   ...                   7.4%     │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  Tab 区域  [策略说明] [回测报告] [历史交易] [最近信号]             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  当前 Tab 对应的内容区域                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  底部操作栏（固定）                                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  月订阅 ¥99/月 │ 年订阅 ¥899/年（省¥289） │ [立即订阅]   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

**ECharts 图表配置要点：**

- 净值曲线：双 Y 轴（左：净值，右：仓位比例），dataZoom 支持区间拖拽
- 回撤曲线：面积图，红色填充，与净值曲线 X 轴联动
- 月度热力图：绿色（正收益）→ 红色（负收益），色阶 -5% ~ +5%
- 所有图表支持响应式，移动端自动简化 tooltip

---

### 8.3 信号列表页

**页面路由：** `/signals`

**布局结构：**

```
┌─────────────────────────────────────────────────────────────────┐
│  未读统计栏                                                      │
│  "12 条未读信号" [全部标记已读]                                    │
│  按策略分组：套利(5) · 波动率(3) · 选股(4)                        │
├─────────────────────────────────────────────────────────────────┤
│  筛选栏：[策略] [信号类型] [操作方向] [资产类别] [置信度≥]          │
├─────────────────────────────────────────────────────────────────┤
│  信号卡片列表                                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 🔴 未读  09:31  [HIGH]                                  │    │
│  │ 股指期货跨期套利 → 买入做多 IF2506                         │    │
│  │ 触发价 3650.00  目标 3700.00  止损 3620.00               │    │
│  │ 置信度 85%  原因：价差偏离2σ                              │    │
│  │                              [查看详情] [标记已执行]       │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ⚪ 已读  09:35                                          │    │
│  │ 50ETF波动率套利 → 买入 50ETF购4月3200                     │    │
│  │ 触发价 0.0520  置信度 72%                                │    │
│  │ Greeks: Δ0.45 Γ0.12 Θ-0.008 ν0.15                      │    │
│  │                              [查看详情] [标记已执行]       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

**实时更新：** WebSocket 收到 `signal_push` 消息后，React Query 自动 invalidate 信号列表缓存，新信号以动画插入列表顶部。

**接口依赖：** `GET /signals` + `GET /signals/unread-summary` + WebSocket `signal_push`

---

### 8.4 信号详情页

**页面路由：** `/signals/{signal_id}`

**布局结构：**

```
┌─────────────────────────────────────────────────────────────────┐
│  信号头部                                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 买入做多 IF2506（沪深300股指期货2506）    [HIGH] 85%      │    │
│  │ 策略：股指期货跨期套利  ·  入场信号  ·  2026-04-15 09:31  │    │
│  │ 状态：🟢 有效（15:00过期）                                │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  价格面板                                                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ 触发价格  │  │ 目标价格  │  │ 止损价格  │  │ 建议仓位  │       │
│  │ 3650.00  │  │ 3700.00  │  │ 3620.00  │  │  15%     │       │
│  │          │  │ +1.37%   │  │ -0.82%   │  │  1手     │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
├─────────────────────────────────────────────────────────────────┤
│  触发原因                                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ IF 当月-次月价差偏离 2σ，触发均值回归开仓                    │    │
│  │ ───详细数据───                                           │    │
│  │ 当前价差: 12.4  |  均值: 5.2  |  标准差: 3.6              │    │
│  │ Z-Score: 2.0   |  触发规则: z_score > 2.0 且持仓量放大    │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  触发时刻行情快照                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 开 3645  |  高 3658  |  低 3640  |  收 3650              │    │
│  │ 成交量 25,680手  |  持仓量 124,500手  |  基差 -8.2        │    │
│  │ MA5 3642 | MA20 3618 | RSI 62.3 | ATR 35.6              │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  历史类似信号表现                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 过去 23 次相似信号：胜率 73.9% | 平均收益 1.85%           │    │
│  │ 平均持有 2.8 天 | 最好 +4.20% | 最差 -1.80%              │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  关联信号（同策略近期信号）                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ SIG_20260410_001  买入 IF2506 @3620 → 平仓 @3680 +1.66% │    │
│  └─────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  底部操作栏（固定）                                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  [标记已执行]  执行价格 [____]  备注 [____]  [提交]       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

**期权信号详情页额外区域：**

```
├─────────────────────────────────────────────────────────────────┤
│  期权特有信息                                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 合约类型: 认购(Call)  |  行权价: 3.200  |  到期日: 04-23  │    │
│  │ 隐含波动率: 18.5%  |  距到期: 8天                         │    │
│  │ ────── Greeks ──────                                    │    │
│  │ Delta  0.45  |  Gamma  0.12  |  Theta  -0.008           │    │
│  │ Vega   0.15  |  Rho    0.02                              │    │
│  └─────────────────────────────────────────────────────────┘    │
```

**接口依赖：** `GET /signals/{signal_id}` + `POST /signals/{signal_id}/execute`

---

## 九、附录：数据字典与枚举

### A. 资产类别（asset_class）

| 值 | 说明 |
|------|------|
| `stock` | 股票（A 股） |
| `future` | 期货（商品 + 金融期货） |
| `option` | 期权（ETF 期权 + 股指期权） |

### B. 信号类型（signal_type）

| 值 | 说明 |
|------|------|
| `entry` | 入场信号（新开仓） |
| `exit` | 离场信号（平仓） |
| `adjust` | 调仓信号（加减仓、移仓换月） |
| `alert` | 预警信号（关注但不需立即行动） |

### C. 操作方向（action）

| 值 | 说明 |
|------|------|
| `buy` | 买入 |
| `sell` | 卖出 |
| `hold` | 持有（不操作） |
| `close` | 平仓 |

### D. 多空方向（direction）

| 值 | 说明 | 适用 |
|------|------|------|
| `long` | 做多 | 期货、期权 |
| `short` | 做空 | 期货、期权 |
| — | 默认做多 | 股票 |

### E. 紧急程度（urgency）

| 值 | 说明 | 前端表现 |
|------|------|----------|
| `low` | 低 | 灰色标签 |
| `normal` | 普通 | 蓝色标签 |
| `high` | 高 | 橙色标签 + 震动提醒 |
| `critical` | 紧急 | 红色标签 + 声音提醒 + 弹窗 |

### F. 风险等级（risk_level）

| 值 | 说明 |
|------|------|
| `low` | 低风险（年化波动率 <10%） |
| `medium` | 中风险（年化波动率 10%~25%） |
| `high` | 高风险（年化波动率 >25%） |

### G. 策略状态（strategy status）

| 值 | 说明 |
|------|------|
| `active` | 运行中（正常产生信号） |
| `paused` | 暂停（临时停止信号，保留订阅） |
| `archived` | 已归档（下架，不可新增订阅） |

### H. 信号状态（signal status）

| 值 | 说明 |
|------|------|
| `active` | 有效（可执行） |
| `expired` | 已过期（超过有效期未执行） |
| `cancelled` | 已取消（策略引擎主动撤销） |

### I. 交易所代码（exchange）

| 值 | 全称 |
|------|------|
| `SSE` | 上海证券交易所 |
| `SZSE` | 深圳证券交易所 |
| `CFFEX` | 中国金融期货交易所 |
| `SHFE` | 上海期货交易所 |
| `DCE` | 大连商品交易所 |
| `CZCE` | 郑州商品交易所 |
| `GFEX` | 广州期货交易所 |
| `INE` | 上海国际能源交易中心 |

### J. 限流策略

| 接口类型 | 限流规则 |
|----------|----------|
| 策略列表/详情 | 120 次/分钟 |
| 信号列表/详情 | 120 次/分钟 |
| 净值曲线/回测 | 30 次/分钟 |
| 订阅/执行操作 | 10 次/分钟 |
| WebSocket | 1 连接/用户 |

---

### K. 接口清单速查表

| 序号 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 4.1 | GET | `/strategies/categories` | 策略分类列表 |
| 4.2 | GET | `/strategies` | 策略列表（筛选/排序/分页） |
| 4.3 | GET | `/strategies/{id}` | 策略详情 |
| 4.4 | GET | `/strategies/{id}/equity-curve` | 净值曲线 |
| 4.5 | GET | `/strategies/{id}/monthly-returns` | 月度收益矩阵 |
| 4.6 | GET | `/strategies/{id}/backtest-report` | 回测报告 |
| 4.7 | GET | `/strategies/{id}/trades` | 历史交易记录 |
| 4.8 | GET | `/strategies/{id}/signals` | 策略历史信号列表 |
| 4.9 | POST | `/strategies/{id}/subscribe` | 订阅策略 |
| 4.10 | POST | `/strategies/{id}/unsubscribe` | 取消订阅 |
| 4.11 | GET | `/strategies/{id}/subscription` | 查询订阅状态 |
| 4.12 | GET | `/strategies/{id}/signal-settings` | 策略级推送配置（读） |
| 4.13 | PUT | `/strategies/{id}/signal-settings` | 策略级推送配置（写） |
| 5.1 | GET | `/signals` | 用户信号流 |
| 5.2 | GET | `/signals/{id}` | 信号详情 |
| 5.3 | POST | `/signals/{id}/read` | 标记已读 |
| 5.4 | POST | `/signals/{id}/execute` | 记录执行反馈 |
| 5.5 | GET | `/signals/unread-summary` | 未读统计 |
| 5.6 | GET | `/user/signal-settings` | 推送配置查询 |
| 5.7 | PUT | `/user/signal-settings` | 推送配置更新 |
| 5.8 | GET | `/user/orders` | 用户订单列表 |
| 6.1 | POST | `/webhooks/payment` | 支付结果回调 |

---

*文档结束 — GetRich Strategy & Signal Module Design v1.1*
