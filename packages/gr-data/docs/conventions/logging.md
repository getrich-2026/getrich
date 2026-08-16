# 日志规范

- 统一入口 `common/logging.py`：`get_logger(name)` / `configure_logging(...)`。
- **禁止 `print()` 做运行日志**（铁律）。
- 命名空间 `gr_data.<layer>.<provider>.<dataset>`，由各基类自动构造。
- 两种格式：人读文本（默认）/ JSON 行（`logging.json: true`），便于采集。
- 可同时输出控制台与文件（`logging.dir`）。
- 日志须能还原：处理了哪个 provider / dataset / 范围 / 目标。
- **不记录密钥或完整 payload**；凭证只用环境变量名引用。
- 结构化字段用 `logger.info("...", extra={"context": {...}})`。

## 配置（config.yaml）
```yaml
logging:
  level: INFO
  dir: logs        # 为空则只输出控制台
  json: false
  console: true
```
