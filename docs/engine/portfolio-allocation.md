# 组合与权重分配

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。相关设计契约见 [设计契约 / 21 组合构建](../design-contracts/21-portfolio-construction.md)。

## 计划内容

- `WeightAllocator` 协议与 6 个内置实现
- `Constraints`（max_single_weight / gross_exposure / long_only）
- `SignalPreprocessor` 链（MissingValue → Winsorize → Standardize → Neutralize）
- `RebalanceRule` 与 `LotSize`
- `Portfolio.build_orders` 全流程
