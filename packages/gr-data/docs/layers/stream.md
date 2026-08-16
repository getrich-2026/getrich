# stream 层

## 职责
订阅供应商实时行情 → 归一化为 `TickEvent` → 写 `realtime.tick_buffer`（PG）。
受单表单一来源约束（`channel='stream'`）。

## 结构
```
stream/
  base.py          # TickEvent, CallbackBridge, BaseStreamHandler
  writer.py        # PgTickWriter（批量 upsert tick_buffer）
  <provider>/handler.py   # 订阅 + 回调解析为 TickEvent
```

## 链路
SDK 后台线程回调 → `handler._on_tick` 构造 `TickEvent` → `CallbackBridge`（线程安全队列）
→ 主循环 `bridge.drain()` → `PgTickWriter.write()`。

## 接入（生产）
实时 SDK 需真实凭证与长驻进程，部署脚本中：
```python
handler = InsightStreamHandler(conn, sdk=<已登录SDK>, symbol_to_id=<映射>)
handler.claim_ownership()            # 登记 realtime.tick_buffer 归属
handler.subscribe(symbols)           # 注册回调
writer = PgTickWriter(conn)
while True:
    writer.write(handler.bridge.drain())
```

## 新增 provider
继承 `BaseStreamHandler`，设 `PROVIDER`，实现 `subscribe()`（注册回调，回调投 `TickEvent` 入 bridge）。
在 `stream/__init__.py::get_handler` 注册。
