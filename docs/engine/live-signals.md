# 实盘信号生成

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。

## 计划内容

- 从回测到实盘的鸿沟
- `SignalProducer` 包 `Strategy` / `SignalStrategy`
- Signal schema
- `EvalSignalWriter` 写 PG `signals` 表
- `LiveDataProvider` 注入 factor / extra_freqs
- `LiveSignalRunner.run_once`
- `LiveRiskMonitor`（Log/Webhook/Email AlertChannel）
- sub-account 路由
- CLI 入口 `getrich-signals` + systemd timer
