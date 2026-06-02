# import_data PostgreSQL 初始化

本目录只初始化数据导入层需要的 PostgreSQL 对象：

- `re`：交易日历、跨供应商标的代码映射、统一标的表 `instruments`。
- `md`：行情数据 PostgreSQL 副本（分钟线 `bars_1m`、日线 `bars_1d`）。OLAP 主力走 ClickHouse，此 schema 用于小范围查询与数据校验。

前端策略、信号、订阅、用户状态等业务表以 `sql/init/frontend_signal/` 为准，不在这里重复初始化。

执行顺序：

1. `00_schemas.sql`
2. `01_ref_tables.sql`
3. `03_ref_instruments_view.sql`
4. `04_md_tables.sql`
