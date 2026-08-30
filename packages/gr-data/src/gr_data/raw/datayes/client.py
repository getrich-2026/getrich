"""通联数据（DataYes）HTTP client。

## 为什么自研而不用官方 SDK

官方给的 `dataapi_linux36.py` 用 `eval()` 解析返回体、单连接非线程安全、
没有任何退避与错误分级。返回体是我们从网络上拿到的数据，`eval` 等于把它当代码执行。

## 协议要点（`datayes_api_调用及返回说明.md`）

- `GET {base_url}/api/equity/getDy1d*.json`，header `Authorization: Bearer <token>`
- **HTTP 200 不代表成功**：真正的状态在返回体的 `retCode` 里，必须逐个判。
- 单次最多返回 10 万条。官方**没有说明**超限是报错还是静默截断（U23），
  因此本 client 按最坏情况（静默截断）防御：逼近上限就当查询过大处理。
- 只用 `.json`，不用 `.csv` —— CSV 是 GB2312 编码，还带 BOM 与 Excel 防转义壳。

## 错误分级

分级的意义在于**区分「重试有用」和「重试只是白等」**：

| retCode | 语义 | 处置 |
|---|---|---|
| 1 | 成功 | — |
| -1 | 无数据 | **不是异常**。非交易日、区间内无记录都会返回它 |
| -2/-9/-12/-13/-14 | 参数/路径错 | 代码缺陷，`PermanentError`，不重试 |
| -3/-4/-5/-8/-16 | 服务侧临时故障 | 普通异常，交给 `retry_call` 指数退避 |
| -7 | 查询超时 | 结果集太大，**把区间折半重试**，原样重试注定再超时 |
| -6/-11/-15 | 配额/流量耗尽 | `PermanentError`，立刻停整批，继续调用只是白烧配额 |
| 403 | 未购买该表 | `PermanentError`，只中断当前表；权限生效要约 1 分钟，重试无意义 |

三个 `PermanentError` 子类是刻意复用 `common/retry.py` 的既有机制：
`retry_call` 已经对 `PermanentError` 做「立即抛出、不退避」，因此分级一旦
落在类型上，重试行为就自动正确，不需要再写一套重试。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any, Protocol

import pandas as pd

from gr_data.common.retry import PermanentError, sleep_s
from gr_data.logging import get_logger


DEFAULT_BASE_URL = "https://api.wmcloud.com/data/v1"

#: 官方声明的单次返回上限。
ROW_LIMIT = 100_000
#: 逼近上限即视为「查询范围过大」的哨兵。留 5% 余量是因为官方没说超限的行为，
#: 等真的撞上 100000 时已经分不清「刚好这么多」和「被截断了」。
ROW_LIMIT_ALARM = 95_000

_RETRYABLE = {-3, -4, -5, -8, -16}
_PARAM_ERRORS = {-2, -9, -12, -13, -14}
_QUOTA_ERRORS = {-6, -11, -15}

log = get_logger("raw.datayes.client")


class DatayesParamError(PermanentError):
    """参数或 API 路径错误 —— 代码缺陷，重试不会变好。"""


class QuotaExhaustedError(PermanentError):
    """调用次数或流量已达上限 —— 必须立刻停止整批抓取。"""


class NotAuthorizedError(PermanentError):
    """未购买该表的权限（HTTP 403 / retCode 403）—— 只中断当前 dataset。"""


class DatayesQueryTooLargeError(RuntimeError):
    """查询结果集过大（retCode -7，或行数逼近 10 万上限）。

    不是 PermanentError：把区间切小之后同一个查询就能成功，
    所以由 `query_range` 捕获后做区间折半，而不是向上抛。
    """


class DatayesClient(Protocol):
    """fetcher 依赖的最小接口，便于注入 Fake。"""

    def query(self, api_path: str, **params: Any) -> pd.DataFrame: ...

    def query_range(
        self, api_path: str, begin: date, end: date, *, chunk_days: int = 10, **params: Any
    ) -> pd.DataFrame: ...


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


def _chunks(begin: date, end: date, days: int) -> Iterator[tuple[date, date]]:
    cur = begin
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


class DatayesHttpClient:
    """真实 HTTP 实现。延迟建连接，缺 token 抛 `PermanentError`。"""

    def __init__(
        self,
        token: str = "",
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 60.0,
        sleep_between_requests: float = 1.0,
    ):
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # 可被 -16（调用过频）就地调大，属于自适应降速，不写回配置
        self._sleep = sleep_between_requests
        self._client: Any = None

    # -- 连接 ---------------------------------------------------------------
    def _session(self) -> Any:
        if self._client is None:
            if not self._token.strip():
                raise PermanentError(
                    "缺少 DataYes token，请设置环境变量 DATAYES_TOKEN "
                    "并在 config.yaml 的 providers.datayes.token_env 中引用。"
                )
            try:
                import httpx
            except ImportError as e:  # pragma: no cover - 依赖已在 pyproject 里
                raise PermanentError("未安装 httpx。") from e
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    # httpx 会自动解压，不复刻官方示例里的手工 gunzip
                    "Accept-Encoding": "gzip, deflate",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- 单次查询 -----------------------------------------------------------
    def query(self, api_path: str, **params: Any) -> pd.DataFrame:
        """单次调用。返回体的 `retCode` 决定成败，不是 HTTP 状态码。"""
        resp = self._session().get(api_path, params={k: v for k, v in params.items() if v != ""})
        sleep_s(self._sleep)

        if resp.status_code == 403:
            raise NotAuthorizedError(f"{api_path} 未授权（HTTP 403），需在数据商城购买该表权限")
        resp.raise_for_status()

        try:
            body = resp.json()
        except json.JSONDecodeError as e:
            # 不 eval、不猜，原样报错并截断打印，避免把整个响应体灌进日志
            raise RuntimeError(f"{api_path} 返回非 JSON：{resp.text[:200]!r}") from e

        return self._unwrap(api_path, body, params)

    def _unwrap(self, api_path: str, body: dict, params: dict) -> pd.DataFrame:
        code = body.get("retCode")
        msg = body.get("retMsg", "")
        # 日志里只带参数、不带 token，也不带完整 payload
        ctx = f"{api_path} params={ {k: v for k, v in params.items()} }"

        if code == 1:
            df = pd.DataFrame(body.get("data") or [])
            if len(df) >= ROW_LIMIT_ALARM:
                raise DatayesQueryTooLargeError(
                    f"{ctx} 返回 {len(df)} 行，逼近单次上限 {ROW_LIMIT}；"
                    "官方未说明超限是报错还是静默截断，按截断处理并切小区间重试"
                )
            return df

        if code == -1:
            # 无数据不是异常：非交易日、区间内没有记录都会走到这里
            log.info("%s 无数据返回", ctx)
            return pd.DataFrame()

        if code == 403 or "privilege" in str(msg).lower():
            raise NotAuthorizedError(f"{ctx} 未授权：{msg}")
        if code in _QUOTA_ERRORS:
            raise QuotaExhaustedError(f"{ctx} 配额耗尽（retCode={code}）：{msg}")
        if code in _PARAM_ERRORS:
            raise DatayesParamError(f"{ctx} 参数或路径错误（retCode={code}）：{msg}")
        if code == -7:
            raise DatayesQueryTooLargeError(f"{ctx} 查询超时（retCode=-7）：{msg}")
        if code == -16:
            # 调用过频：就地降速，本次仍作为可重试异常抛出
            self._sleep *= 1.5
            log.warning("%s 调用过频，sleep 上调到 %.2fs", ctx, self._sleep)

        raise RuntimeError(f"{ctx} 调用失败（retCode={code}）：{msg}")

    # -- 区间查询 -----------------------------------------------------------
    def query_range(
        self, api_path: str, begin: date, end: date, *, chunk_days: int = 10, **params: Any
    ) -> pd.DataFrame:
        """按 `chunk_days` 切分区间逐段取数，遇到结果集过大就把该段折半。

        不用官方的 `pagenum`/`pagesize`：分页行为官方只给了一句示例，与
        「超限可能静默截断」叠加之后无法自证完整；按日期切分则可以和
        `meta.trading_calendar` 逐日对账。分页留作单表权限受限时的兜底。
        """
        frames = [
            self._query_span(api_path, lo, hi, **params)
            for lo, hi in _chunks(begin, end, chunk_days)
        ]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0, ignore_index=True)

    def _query_span(self, api_path: str, lo: date, hi: date, **params: Any) -> pd.DataFrame:
        try:
            return self.query(api_path, beginDate=_fmt(lo), endDate=_fmt(hi), **params)
        except DatayesQueryTooLargeError:
            if lo >= hi:
                # 单日仍然过大，切无可切 —— 这时必须抛出去，
                # 静默返回空表会让下游以为这天没有数据
                raise
            mid = lo + (hi - lo) // 2
            log.warning("%s [%s, %s] 结果集过大，折半重试", api_path, _fmt(lo), _fmt(hi))
            left = self._query_span(api_path, lo, mid, **params)
            right = self._query_span(api_path, mid + timedelta(days=1), hi, **params)
            frames = [f for f in (left, right) if not f.empty]
            return pd.concat(frames, axis=0, ignore_index=True) if frames else pd.DataFrame()
