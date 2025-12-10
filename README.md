# GetRich: 零售级量化信号与交易平台 (MVP 架构设计)

版本: v1.1 (Adapted for Remote Data Center)
维护者: Get Rich Team
更新日期: 2025-11-19

## 1. 项目愿景
"Signal-as-a-Service" (信号即服务)。
面向散户提供极其简化的量化投资建议（涨/跌/观望），底层由专业的基金经理策略驱动。不仅展示历史回测，更强调实时的盘中信号推送与未来的自动化交易执行。

## 2. 核心架构 (The "Slim" Architecture)

本项目采用 混合部署架构：核心数据仓库 (ClickHouse) 部署在共享的 Ubuntu 虚拟机上，业务服务 (Data/Strategy/Web) 既可以在本地开发运行，也可以在服务器通过 Docker 容器化部署。

### 2.1 系统拓扑
```graph TD
    % 基础设施 (VM)
    subgraph "Ubuntu VM (Shared Infra)"
        CH[(ClickHouse Server\nPort: 8123)]
    end

    % 业务容器群
    subgraph "Docker Compose Group"
        DataSvc(getrich-data) -->|Batch Write| CH
        StratSvc(getrich-strategy) -->|Read/Write| CH
        Gateway(getrich-gateway) -->|Query| CH
        
        Redis[(Redis Cache\nPub/Sub)]
        StratSvc -->|Pub| Redis
        Redis -->|Sub| Gateway
    end

    % 外部
    External[外部行情源] --> DataSvc
    Gateway <-->|WS/HTTP| Web[前端网页]
    User((散户)) --> Web

```

### 2.2 服务职责清单
| 服务名称 | 目录路径 | 核心职责 | 技术栈 |
| -------- | -------- | -------- | ------ |
| Data Service | /apps/data | 负责清洗、落地行情数据。直接连接 VM 上的 ClickHouse。 | Python, Pandas, ClickHouse-Connect |
| Strategy Service | /apps/strategy | 本地模式：连接远程 CH 回测；生产模式：Docker 运行实时计算。 | Python, NumPy, Talib |
| Gateway Service | /apps/gateway | 统一后端网关。处理 REST API (历史查询) 和 WebSocket (实时推送)。 | Python FastAPI, Redis-py |
| Web Frontend | /apps/web | 用户交互界面。K线展示、信号订阅、仪表盘。 | React, Next.js, Tailwind, Lightweight-Charts |

## 2.3. 技术栈选型 (Tech Stack)
- 编程语言: Python 3.11+ (后端/策略), TypeScript (前端)
- 数据库 (OLAP): ClickHouse (核心数据仓库)
- 缓存/消息总线: Redis (最新信号缓存 + Pub/Sub 消息队列)
- Web 框架: FastAPI (高性能异步框架)
- 前端库: React + TradingView Lightweight Charts
- 部署: Docker Compose (单机编排) -> K8s (未来)

## 3. 环境与配置 (Environment Setup) [重要]

由于采用外部数据源模式，正确配置环境变量至关重要。

### 3.1 配置文件 (.env)

请复制 .env.example 为 .env（此文件不应提交 Git），并根据运行环境修改：
```ini
# .env 示例

# --- 数据库配置 (核心) ---
# [场景 A: 本地开发] 填写 Ubuntu 虚拟机的局域网 IP (例如 192.168.50.10)
# [场景 B: 服务器部署] 填写宿主机 IP (例如 172.17.0.1) 或保持 VM 局域网 IP
CLICKHOUSE_HOST=192.168.x.x
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=your_password
CLICKHOUSE_DB=default

# --- Redis 配置 ---
# 生产环境下 Redis 运行在 Docker 容器名为 "redis" 的主机上
# 本地开发若无 Docker Redis，可填 localhost
REDIS_HOST=redis
REDIS_PORT=6379
```

### 3.2 开发工作流 (Workflow)

1. Local Dev (个人电脑):

    - 修改本地 .env 指向虚拟机 IP。
    - 使用 Jupyter 或 Python 脚本连接远程 ClickHouse 进行策略研发。
    - 禁止在本地长时间运行实时写入脚本（避免数据污染），仅做回测和代码调试。
    - 代码 Commit & Push 到 Git。

2. Server Deploy (Ubuntu VM):
    - SSH 登入虚拟机。
    - git pull 拉取最新代码。
    - 修改服务器端的 .env (通常只需配置一次)。
    - docker-compose up -d --build 重启服务。
  
## 4. 数据库设计 (ClickHouse Schema)
所有涉及存储的代码必须遵循以下 Schema 定义。

### 4.1 基础行情表 (Market Data)
设计原则: 使用 MergeTree 引擎，按月/年分区，高压缩比，建表语句参考如下。

```sql
-- 1. 分钟线表 (Minute Bars)
CREATE TABLE IF NOT EXISTS market_data.bars_1m (
    symbol LowCardinality(String),
    dt Date CODEC(Delta, ZSTD(1)),      -- 用于分区
    ts DateTime CODEC(Delta, ZSTD(1)),  -- K线结束时间
    pre_close Float64 DEFAULT 0 CODEC(ZSTD(1)), -- 前收盘价
    open Float64 DEFAULT 0 CODEC(ZSTD(1)),      -- 开盘价
    high Float64 DEFAULT 0 CODEC(ZSTD(1)),      -- 最高价
    low Float64 DEFAULT 0 CODEC(ZSTD(1)),       -- 最低价
    close Float64 DEFAULT 0 CODEC(ZSTD(1)),     -- 收盘价
    volume Float64 DEFAULT 0 CODEC(ZSTD(1)),    -- 成交量
    amount Float64 DEFAULT 0 CODEC(ZSTD(1)),    -- 成交额
    open_interest Float64 DEFAULT 0 CODEC(ZSTD(1)), -- 持仓量(期货)
    settle Float64 DEFAULT 0 CODEC(ZSTD(1)),    -- 结算价
    pre_settle Float64 DEFAULT 0 CODEC(ZSTD(1)), -- 前结算价
    updated_at DateTime('Asia/Shanghai') DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, ts)
SETTINGS index_granularity = 8192, min_bytes_for_wide_part = 0, min_rows_for_wide_part = 0, enable_mixed_granularity_parts = 1;

-- 1.1 日线 (宽表，包含常用衍生字段)
CREATE TABLE IF NOT EXISTS market_data.bars_1d (
    symbol LowCardinality(String),
    dt Date CODEC(Delta, ZSTD(1)),

    pre_close Float64 DEFAULT 0 CODEC(ZSTD(1)),
    open Float64 DEFAULT 0 CODEC(ZSTD(1)),
    high Float64 DEFAULT 0 CODEC(ZSTD(1)),
    low Float64 DEFAULT 0 CODEC(ZSTD(1)),
    close Float64 DEFAULT 0 CODEC(ZSTD(1)),
    volume Float64 DEFAULT 0 CODEC(ZSTD(1)),
    amount Float64 DEFAULT 0 CODEC(ZSTD(1)),
    
    pct_chg Float64 DEFAULT 0 CODEC(ZSTD(1)),
    pct_chg_log Float64 DEFAULT 0 CODEC(ZSTD(1)),
    adj_factor Float64 DEFAULT 1 CODEC(ZSTD(1)),

    limit_up Float64 DEFAULT 0 CODEC(ZSTD(1)),
    limit_down Float64 DEFAULT 0 CODEC(ZSTD(1)),
    turnover_rate Float32 DEFAULT 0 CODEC(ZSTD(1)),
    total_shares Float64 DEFAULT 0 CODEC(ZSTD(1)),
    float_shares Float64 DEFAULT 0 CODEC(ZSTD(1)),

    open_interest Float64 DEFAULT 0 CODEC(ZSTD(1)),
    settle Float64 DEFAULT 0 CODEC(ZSTD(1)),
    pre_settle Float64 DEFAULT 0 CODEC(ZSTD(1)),

    trading_status Enum8('UNKNOWN'=0, 'NORMAL'=1, 'HALTED'=2) DEFAULT 'UNKNOWN',
    updated_at DateTime('Asia/Shanghai') DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
SETTINGS index_granularity = 8192, min_bytes_for_wide_part = 0, min_rows_for_wide_part = 0, enable_mixed_granularity_parts = 1;

-- 2. Tick 数据表 (带 TTL 自动清理)
-- 重点: 定期删除旧Tick数据，节省空间
CREATE TABLE IF NOT EXISTS market_data.ticks (
    symbol LowCardinality(String),
    ts DateTime64(3) CODEC(Delta, ZSTD),
    price Float32,
    volume Float64,
    bid1_price Float32,
    ask1_price Float32,
    -- ... 其他盘口字段
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts) -- 按天分区
ORDER BY (symbol, ts)
TTL ts + INTERVAL 30 DAY DELETE -- 30天后自动过期
SETTINGS ttl_only_drop_parts = 1; -- 强制整分区删除，零IO开销
```

### 4.2 信号与预测表 (Signals)
```sql
-- 3. 原始信号表 (用于回测分析和风控)
CREATE TABLE IF NOT EXISTS strategy.signals_raw (
    strategy_id String,
    symbol LowCardinality(String),
    ts DateTime,
    signal_type Enum8('NONE'=0, 'BUY'=1, 'SELL'=2),
    strength Float32 COMMENT '信号强度 0-1',
    price_at_signal Float32,
    metadata String COMMENT 'JSON格式的调试信息'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (strategy_id, symbol, ts);

-- 4. 前端展示表 (For UI Display)
-- 经过聚合的、面向用户的建议
CREATE TABLE IF NOT EXISTS app.ui_predictions (
    symbol LowCardinality(String),
    ts DateTime,
    direction Enum8('NEUTRAL'=0, 'BULLISH'=1, 'BEARISH'=2),
    confidence Float32 COMMENT '置信度',
    primary_message String COMMENT '展示文案, e.g. 均线金叉，看涨',
    valid_until DateTime COMMENT '有效期'
) ENGINE = ReplacingMergeTree(ts) -- 保留最新版本
PARTITION BY toYYYYMM(ts)
ORDER BY (symbol, ts);
```

## 5. 策略开发接口 (Strategy Interface)
AI 在生成策略代码时，必须继承基类，参考如下。
```python
# libs/strategy_core/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional

@dataclass
class Signal:
    symbol: str
    timestamp: datetime
    direction: str  # 'BUY', 'SELL', 'HOLD'
    strength: float # 0.0 - 1.0
    meta: Dict[str, Any] # 额外信息

class BaseStrategy(ABC):
    def __init__(self, config: Dict):
        self.config = config
        self.state = {}

    @abstractmethod
    async def on_bar(self, bar: Dict) -> Optional[Signal]:
        """
        分钟线/日线驱动。
        bar: {'symbol': '...', 'close': 10.0, 'ts': ...}
        """
        pass

    @abstractmethod
    async def on_tick(self, tick: Dict) -> Optional[Signal]:
        """
        Tick 驱动（可选实现）。
        """
        pass

    def load_history(self, lookback_days: int):
        """从 ClickHouse 加载初始化所需的历史数据"""
        pass
```

## 6. 项目目录结构 (Repo Structure)
```
getrich-monorepo/
├── apps/
│   ├── data/            # 数据入库服务 (Ingestion)
│   ├── strategy/        # 策略引擎 (Strategy Engine)
│   ├── gateway/         # 后端 API & WS (FastAPI)
│   └── web/             # 前端 (React)
├── libs/                # 共享库
│   ├── db/              # ClickHouse 连接客户端 (含 env 读取)
│   ├── messaging/       # Redis 封装
│   └── strategy_core/   # 策略基类定义
├── deploy/
│   └── docker-compose.yml
├── .env.example         # 环境变量模板
├── pyproject.toml       # Python 依赖管理 (Poetry)
└── README.md            # 本文档
```

## 7. 启动指南 (Quick Start)

前置条件
 - Server: Ubuntu 虚拟机已安装 ClickHouse，并配置 users.xml 允许 ```<ip>::/0``` 访问。
 - Local: 已安装 Docker, Python 3.11+。

步骤 1: 环境配置
```
# 复制配置模板
cp .env.example .env

# 编辑 .env (本地开发填 VM IP，服务器填宿主机 IP)
vim .env 
```

步骤 2: 启动业务服务
```
# 启动 Redis 及业务容器 (Data/Strategy/Gateway/Web)
# 注意：此命令不会启动 ClickHouse，因为假定它已在外部运行
docker-compose up -d --build

# 查看日志确保连接成功
docker-compose logs -f strategy-service
```

步骤 3: 初始化数据库 (仅首次)
```
# 在本地或服务器运行一次即可
python apps/data/scripts/init_db.py
```