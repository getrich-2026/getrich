# 监控与告警

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。

## 计划内容

- Flower（Celery 任务监控）
- `pg_notify` 跨进程事件推送
- 告警通道（Log / Webhook / Email）
- Prometheus 指标导出
- 健康检查 `/health`
- 关键 SLO：worker 队列深度、SSE 推送延迟、API P99
