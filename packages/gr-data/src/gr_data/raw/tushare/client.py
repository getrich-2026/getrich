"""Tushare Pro 客户端封装。

定义 ``TushareClient`` 协议与真实 SDK 实现 ``TushareProClient``。

真实 SDK 用法::

    import tushare as ts
    pro = ts.pro_api(token)
    pro.stock_basic(exchange="", list_status="L", fields=...) -> DataFrame
    pro.trade_cal(exchange="SSE", start_date="20240101", end_date="20240131") -> DataFrame
    pro.daily(trade_date="20240102", fields=...) -> DataFrame

Tushare 的所有接口都通过 ``pro.<api_name>(**params)`` 调用，形态统一，
因此这里只暴露一个泛化的 ``query(api_name, **params)``，而不是逐个接口写方法。

两个必须尊重的供应商约束（见 reference/design/tushare/tushare_api_design.md）：

- **单次返回行数上限**：多数接口单次最多 5000~6000 行。超出需要按
  ``offset`` 翻页，否则会**静默截断**——这是最危险的一类数据缺失，
  因为接口不会报错。``query_all`` 负责翻页直到取空。
- **调用频次上限**：按积分分级限频，超限返回异常。限频由调用方
  （fetcher）通过 ``RawContext.sleep_between_requests`` 控制。
- **offset 上限 100000**：实测 offset=100000 可用、100001 报
  「查询数据失败，请确认参数」。即单次查询最多只能翻出约 10 万行，
  再多的数据**取不到**。因此调用方必须把查询切小（见 fetchers/market.py
  按交易日调用的说明），而不是指望翻页翻到底。
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from gr_data.common.retry import PermanentError


# 各接口单次返回上限。Tushare 未在响应中给出截断标志，只能靠行数推断，
# 因此这里必须与官方文档保持一致；调小是安全的，调大会导致漏数据。
# 单次查询可翻出的最大 offset。超过即报错，不是截断——但报错信息是通用的
# 「查询数据失败」，很容易被误判成参数写错，所以这里主动拦截并给出可执行的提示。
MAX_OFFSET = 100000

DEFAULT_PAGE_LIMIT = 5000
PAGE_LIMITS: dict[str, int] = {
    "daily": 6000,
    "adj_factor": 6000,
    "daily_basic": 6000,
    "stk_limit": 5800,
    "suspend_d": 5000,
    "index_daily": 5000,
    "fut_daily": 5000,
    "trade_cal": 5000,
    "stock_basic": 5000,
    "index_basic": 5000,
    "fut_basic": 5000,
}


class TushareClient(Protocol):
    def query(self, api_name: str, **params: Any) -> pd.DataFrame: ...

    def query_all(self, api_name: str, **params: Any) -> pd.DataFrame: ...


class TushareProClient:
    """真实 Tushare Pro SDK 封装。延迟 init。"""

    def __init__(self, token: str = ""):
        self._token = token
        self._pro: Any = None

    def _sdk(self) -> Any:
        if self._pro is None:
            if not self._token.strip():
                raise PermanentError(
                    "缺少 Tushare token，请设置环境变量 TUSHARE_TOKEN "
                    "并在 config.yaml 的 providers.tushare.token_env 中引用。"
                )
            try:
                import tushare as ts  # type: ignore
            except ImportError as e:  # pragma: no cover - 依赖真实 SDK
                raise PermanentError("未安装 tushare SDK。") from e
            self._pro = ts.pro_api(self._token)
        return self._pro

    def query(self, api_name: str, **params: Any) -> pd.DataFrame:
        """单次调用，不翻页。返回结果可能被供应商截断。"""
        df = getattr(self._sdk(), api_name)(**params)
        return df if df is not None else pd.DataFrame()

    def query_all(self, api_name: str, **params: Any) -> pd.DataFrame:
        """按 offset 翻页取全量。

        以「返回行数 < limit」作为终止条件——Tushare 不返回总数，也不标记
        是否截断，这是唯一可靠的判据。
        """
        limit = PAGE_LIMITS.get(api_name, DEFAULT_PAGE_LIMIT)
        frames: list[pd.DataFrame] = []
        offset = 0
        while True:
            page = self.query(api_name, limit=limit, offset=offset, **params)
            if page.empty:
                break
            frames.append(page)
            if len(page) < limit:
                break
            offset += len(page)
            if offset > MAX_OFFSET:
                # 到这里说明查询范围本身就太大了。继续翻只会撞供应商的通用报错，
                # 悄悄返回已取到的部分则是静默丢数据——两者都不可接受。
                raise RuntimeError(
                    f"{api_name} 查询结果超过 Tushare 的 offset 上限 {MAX_OFFSET} 行"
                    f"（params={ {k: v for k, v in params.items() if k != 'fields'} }）。"
                    "请把查询范围切小，例如按单个交易日调用。"
                )
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0, ignore_index=True)
