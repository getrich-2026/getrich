# import_data PostgreSQL 初始化

本目录只初始化数据导入层需要的 PostgreSQL 对象：

- `ref`：交易日历、跨供应商标的代码映射、统一标的视图。
- `rq`：RiceQuant 标的信息落地表。

前端策略、信号、订阅、用户状态等业务表以 `sql/init/frontend_signal/` 为准，不在这里重复初始化。

执行顺序：

1. `00_schemas.sql`
2. `01_ref_tables.sql`
3. `02_rq_instruments.sql`
4. `03_ref_instruments_view.sql`
