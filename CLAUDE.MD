# GetRich 量化研究系统 - 项目规范

## 项目概述
量化交易研究系统，专注于因子研究、高频交易策略开发和回测系统。

---

## 技术栈

| 类别 | 首选 | 备选 |
|------|------|------|
| DataFrame | `polars` | `pandas`（仅限 ETL 或库兼容） |
| 数值计算 | `numpy` 向量化 | `numba.jit`（不可避免的循环） |
| 存储格式 | `parquet` | `csv`（简单交换） |
| 数据库 | ClickHouse (`clickhouse-connect`) | — |
| Python | 3.10+ | — |

---

## 代码规范

### 类型提示
- **强制**：所有函数必须有完整的类型注解
- 使用 `from __future__ import annotations` 支持延迟求值

### 文档
- 使用 **Google-style docstrings**
- 核心函数需标注算法复杂度 `Time: O(n), Space: O(1)`

### 代码完整性
每个代码块必须：
1. 包含所有 `import` 语句
2. 包含 `if __name__ == "__main__":` 入口
3. 提供可直接运行的 **MRE**（使用 `np.random` 或 `pl.DataFrame` 生成假数据）
4. 包含 `assert` 验证逻辑正确性

### 异常处理
主动处理边界情况：`NaN`, `Inf`, 除零, 空 DataFrame

---

## 量化领域约定

### 时间处理
- 所有时间戳必须 **timezone-aware**
- 默认时区：`Asia/Shanghai (UTC+8)`

### 金融精度
- 货币计算（非向量化）：使用 `decimal.Decimal`
- 收益率计算：明确区分 `log-return` vs `simple-return`

### 标准命名
```
open, high, low, close, volume, vwap, oi (Open Interest)
```

### 风控检查
交易执行逻辑**必须**包含 Pre-trade Check：
- 限价单价格带检查
- 最大持仓限制
- 成交量异常检测

---

## ClickHouse 规范

### 建表模板
```sql
CREATE TABLE {table_name} (
    dt DateTime64(3, 'Asia/Shanghai'),
    symbol LowCardinality(String),
    -- 数值列必须指定压缩
    price Float64 CODEC(ZSTD(1)),
    vol Float64 CODEC(ZSTD(1))
) ENGINE = MergeTree()      -- 或 ReplacingMergeTree (状态表)
PARTITION BY toYYYYMM(dt)   -- 必须：按月/日分区
ORDER BY (symbol, dt)       -- 必须：主键优化查询
TTL dt + INTERVAL 5 YEAR;   -- 必须：数据生命周期
```

### 强制要求
- [ ] `PARTITION BY` - 按日或月
- [ ] `ORDER BY` - 符合查询模式
- [ ] `TTL` - 数据过期策略
- [ ] `CODEC(ZSTD(1))` - 数值列压缩

---

## 输出风格

### 语言规则
| 场景 | 语言 |
|------|------|
| 代码注释（复杂逻辑） | 中文 |
| 变量名/函数名 | English |
| 日志/运行时输出 | **English ONLY**（便于 grep） |
| 对话交流 | 中文 |

### 回复格式
1. **先给方案，再解释**
2. 明确标注约束条件：`Assumes sorted index` / `Memory heavy`
3. pandas→polars 迁移时提供性能对比（`time.perf_counter`）

---

## 常用命令

```bash
# 运行测试
pytest tests/ -v

# 类型检查
mypy src/ --strict

# 格式化
ruff format src/
ruff check src/ --fix

# 本地开发安装
pip install -e .
```

---

## 项目结构参考

```
getrich/
├── CLAUDE.md
├── src/
│   ├── factors/      # 因子计算
│   ├── backtest/     # 回测引擎
│   ├── data/         # 数据层
│   └── utils/        # 工具函数
├── tests/
├── notebooks/
└── scripts/
```