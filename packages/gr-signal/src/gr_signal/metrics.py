"""实盘信号链路的 Prometheus 指标。

这些指标原先定义在 ``gr_api.metrics`` 里，导致 gr-signal 反向 import gr-api
（DECISIONS.md D-004 记录的问题），单独安装 gr-signal 直接 ImportError。
``LIVE_*`` 描述的是实盘运行状况，属于本包，因此定义收归这里。

prometheus_client 用的是**进程级全局 REGISTRY**，所以只要 gr-signal 被导入，
这些指标照样会出现在 gr-api 的 ``/metrics`` 响应里，无需 gr-api 显式引用。
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram


# Total wall-clock time for one ``LiveSignalRunner.run_once()`` cycle.
# Buckets span sub-millisecond (no-op tick) to 30s (worst-case
# ClickHouse stall). Anything > 30s is the live pipeline's
# "stalled" alert threshold.
LIVE_RUN_ONCE_SECONDS = Histogram(
    "getrich_live_run_once_seconds",
    "Wall-clock time of one LiveSignalRunner.run_once() cycle",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Number of signals successfully written to the PG ``signals`` table.
# Incremented once per row in ``EvalSignalWriter.persist`` (or
# equivalent writer), so a 1-tick cycle with 3 signals = +3.
LIVE_SIGNALS_PERSISTED_TOTAL = Counter(
    "getrich_live_signals_persisted_total",
    "Number of signals successfully persisted to PostgreSQL",
)

# Risk alerts emitted by the LiveRiskMonitor, bucketed by severity
# (info / warning / critical). The alerting policy in monitoring.md
# §5.2 says "critical" alerts must trigger Email + Webhook, so the
# rate of criticals is the most operationally important sub-bucket.
LIVE_ALERTS_EMITTED_TOTAL = Counter(
    "getrich_live_alerts_emitted_total",
    "Number of risk alerts emitted by LiveRiskMonitor, by severity",
    ["severity"],
)

# Granular timing for the 3 load steps inside build_context().
# ``bars`` is the SELECT against md_bars_1m, ``factors`` is the
# SELECT against factors_long, ``account`` is the account state
# loader. A spike in any one bucket is a leading indicator of a
# dependency issue (e.g. ClickHouse slow query).
LIVE_DATA_LOAD_SECONDS = Histogram(
    "getrich_live_data_load_seconds",
    "Time spent loading data for one live tick, by step",
    ["step"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Strategy.on_bar() exceptions, bucketed by strategy_id. A
# non-zero rate here is a P0 (strategy is silently not running).
# ``strategy_id`` label cardinality is bounded by the number of
# registered strategies (typically < 1000) so this is safe.
LIVE_STRATEGY_ERRORS_TOTAL = Counter(
    "getrich_live_strategy_errors_total",
    "Exceptions raised by Strategy.on_bar(), by strategy_id",
    ["strategy_id"],
)
