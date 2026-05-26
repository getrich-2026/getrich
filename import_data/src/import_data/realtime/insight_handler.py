from __future__ import annotations

from datetime import datetime

from import_data.core.logger import Logger
from import_data.realtime.bridge import CallbackBridge
from import_data.realtime.models import BarEvent

try:
    from import_data.etl.transforms import get_symbol_type
except ImportError:

    def get_symbol_type(symbol: str) -> str:  # type: ignore[misc]
        return "unknown"


# Insight SDK 延迟导入，未安装时降级为 mock 模式
try:
    import insight as _insight_sdk  # 实际包名待确认

    HAS_INSIGHT = True
except ImportError:
    _insight_sdk = None  # type: ignore[assignment]
    HAS_INSIGHT = False


_SUFFIX_MAP: dict[str, str] = {
    "SH": "SH",
    "SZ": "SZ",
    "BJ": "BJ",
    "SHF": "SHF",
    "DCE": "DCE",
    "ZCE": "CZC",
    "GFE": "GFE",
    "CF": "CFE",
    "INE": "INE",
}


def normalize_insight_symbol(htsc_code: str) -> str:
    """将 Insight htsc_code 格式转换为项目统一 symbol 格式。

    示例：IF2503.CF -> IF2503.CFE，M2505.ZCE -> M2505.CZC
    需按实际 Insight SDK 的代码格式调整此映射表。
    """
    if "." not in htsc_code:
        return htsc_code
    code, suffix = htsc_code.rsplit(".", 1)
    return f"{code}.{_SUFFIX_MAP.get(suffix, suffix)}"


class InsightBarHandler:
    """Insight SDK 的 1 分钟 K 线回调适配器。

    职责：
    - 将 SDK 原始 bar 对象转换为 BarEvent（字段映射、类型转换）
    - 通过 CallbackBridge 将事件投递到 asyncio 事件循环

    ⚠️ _convert() 中的字段映射（属性名、价格缩放）为占位实现，
    需按 Insight SDK 实际 bar 对象文档填充。
    """

    def __init__(self, bridge: CallbackBridge) -> None:
        self._bridge = bridge
        self._logger = Logger("InsightBarHandler")

    def on_bar(self, bar: object) -> None:
        """SDK 在后台线程调用此方法。必须非阻塞、无 IO。"""
        try:
            event = self._convert(bar)
            self._bridge.put_nowait_threadsafe(event)
        except Exception as e:
            self._logger.error(f"on_bar conversion error: {e}")

    def _convert(self, bar: object) -> BarEvent:
        """将 SDK bar 对象转换为标准 BarEvent。

        TODO: 以下字段名为占位，需按 Insight SDK 实际属性名替换：
        - bar.htsc_code 或 bar.symbol  -> symbol
        - bar.time                     -> bar_time (datetime)
        - bar.open/high/low/close      -> 价格（确认是否需要 /10000 缩放）
        - bar.volume                   -> 成交量（手数 or 股数？）
        - bar.value 或 bar.amount      -> 成交额
        - bar.open_interest            -> 持仓量（股票为 0）
        - bar.settle / bar.pre_settle  -> 期货结算价（股票为 0）
        """
        raw_symbol: str = getattr(bar, "htsc_code", getattr(bar, "symbol", ""))
        symbol = normalize_insight_symbol(raw_symbol)
        bar_time: datetime = getattr(bar, "time")

        return BarEvent(
            symbol=symbol,
            type=get_symbol_type(symbol),
            dt=bar_time.date(),
            bar_time=bar_time.replace(tzinfo=None),
            pre_close=float(getattr(bar, "pre_close", 0) or 0),
            open=float(getattr(bar, "open", 0) or 0),
            high=float(getattr(bar, "high", 0) or 0),
            low=float(getattr(bar, "low", 0) or 0),
            close=float(getattr(bar, "close", 0) or 0),
            volume=float(getattr(bar, "volume", 0) or 0),
            amount=float(getattr(bar, "value", getattr(bar, "amount", 0)) or 0),
            open_interest=float(getattr(bar, "open_interest", 0) or 0),
            settle=float(getattr(bar, "settle", 0) or 0),
            pre_settle=float(getattr(bar, "pre_settle", 0) or 0),
            local_time=datetime.now(),
            provider="insight",
        )

    def subscribe(self, symbols: list[str]) -> None:
        """向 Insight SDK 注册 1 分钟 K 线订阅并绑定回调。

        TODO: 以下为占位实现，按 Insight SDK 文档替换调用形式。
        常见形式参考：
          _insight_sdk.subscribe(symbols, frequency="1m", on_bar=self.on_bar)
          _insight_sdk.subscribe_kline(symbols, period=60, callback=self.on_bar)
        """
        if not HAS_INSIGHT:
            self._logger.warning(
                "Insight SDK not installed (import insight failed), running in mock mode. "
                "To enable real data: install the Insight SDK package."
            )
            return

        # TODO: 替换为实际 Insight SDK 订阅 API
        # _insight_sdk.subscribe(symbols, frequency="1m", callback=self.on_bar)
        self._logger.info(
            f"Subscribing to {len(symbols)} symbols via Insight SDK (TODO: fill actual API)"
        )


if __name__ == "__main__":
    print(normalize_insight_symbol("IF2503.CF"))   # -> IF2503.CFE
    print(normalize_insight_symbol("M2505.ZCE"))   # -> M2505.CZC
    print(normalize_insight_symbol("600000.SH"))   # -> 600000.SH
    print(normalize_insight_symbol("600000"))      # -> 600000
