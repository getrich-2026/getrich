# 执行与账户

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。相关设计契约见 [设计契约 / 30 执行引擎](../design-contracts/30-execution-engine.md)、[31 账户与保证金](../design-contracts/31-account-margin.md)、[32 风控](../design-contracts/32-risk-control.md)。

## 计划内容

- `NextBarMatchingModel`（默认 `execution_lag_bars=1`）
- 订单生命周期 PENDING → ACCEPTED → FILLED/REJECTED/EXPIRED
- `OrderType` / `TimeInForce`
- 5 种 `FeeModel` + `SlippageModel`
- `Account` / `Position` 状态
- `MarginCalculator` / `RiskManager`
- 公司行为 `apply_corporate_action`
- Look-ahead 防御清单
