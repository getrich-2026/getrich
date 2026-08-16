"""pytest 共享 fixtures。

- tmp_raw_root: 临时 raw_root，隔离 /opt/raw_parquet。
- Fake SDK：实现各 provider client 协议，返回真实形状数据，无需真实 SDK/网络。
- pg_conn: 基于 docker 的 PostgreSQL+TimescaleDB 连接；不可用时整组测试 skip。
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths


@pytest.fixture
def tmp_raw_root(tmp_path: Path) -> RawPaths:
    return RawPaths(tmp_path / "raw")


# --------------------------------------------------------------------------- #
# Fake SDKs
# --------------------------------------------------------------------------- #
class FakeYinheClient:
    """实现 raw.yinhe.client.YinheClient 协议。"""

    def __init__(self):
        self.market = "cn"

    def get_calendar(self, market: str) -> list[int]:
        return [20240102, 20240103, 20240104]

    def get_code_list(self, security_type: str) -> list[str]:
        return {
            "EXTRA_STOCK_A_SH_SZ": ["600000.SH", "000001.SZ"],
            "EXTRA_ETF": ["510300.SH"],
            "EXTRA_IDNEX_A_SH_SZ": ["000300.SH"],
        }.get(security_type, [])

    def get_backward_factor(self, codes: list[str]) -> pd.DataFrame:
        return pd.DataFrame({"code": codes, "factor": [1.0] * len(codes)})

    def query_kline(self, codes, begin_date, end_date, period):
        out = {}
        for c in codes:
            out[c] = pd.DataFrame(
                {
                    "kline_time": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                    "open": [10.0, 10.5],
                    "high": [10.8, 10.9],
                    "low": [9.9, 10.2],
                    "close": [10.5, 10.7],
                    "pre_close": [9.8, 10.5],
                    "volume": [1000, 1200],
                    "amount": [10500.0, 12840.0],
                }
            )
        return out


class FakeRicequantClient:
    def __init__(self):
        self.market = "cn"

    def all_instruments(self, type: str, market: str = "cn") -> pd.DataFrame:
        data = {
            "CS": [("600000.XSHG", "浦发银行", "XSHG"), ("000001.XSHE", "平安银行", "XSHE")],
            "ETF": [("510300.XSHG", "300ETF", "XSHG")],
            "Index": [("000300.XSHG", "沪深300", "XSHG")],
        }.get(type, [])
        return pd.DataFrame(
            [
                {
                    "order_book_id": o,
                    "symbol": s,
                    "exchange": e,
                    "status": "Active",
                    "listed_date": "2010-01-01",
                    "de_listed_date": "0000-00-00",
                }
                for o, s, e in data
            ]
        )

    def get_trading_dates(self, start_date, end_date, market="cn"):
        return [pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-03").date()]

    def get_price(
        self, symbols, start_date, end_date, frequency="1d", adjust_type="none", market="cn"
    ):
        rows = []
        for s in symbols:
            for d in ["2024-01-02", "2024-01-03"]:
                rows.append(
                    {
                        "order_book_id": s,
                        "date": pd.Timestamp(d),
                        "open": 10.0,
                        "high": 10.8,
                        "low": 9.9,
                        "close": 10.5,
                        "prev_close": 9.8,
                        "volume": 1000,
                        "total_turnover": 10500.0,
                    }
                )
        return pd.DataFrame(rows).set_index(["order_book_id", "date"])


class FakeInsightClient:
    def __init__(self):
        self.market = "cn"

    def get_all_basic_info(self, security_type: str, exchange: list[str]) -> pd.DataFrame:
        data = {
            "StockA": [("600000.SH", "浦发银行"), ("000001.SZ", "平安银行")],
            "FundETF": [("510300.SH", "300ETF")],
            "IndexCN": [("000300.SH", "沪深300")],
        }.get(security_type, [])
        return pd.DataFrame(
            [{"htsc_code": c, "security_name": n, "exchange": "XSHG"} for c, n in data]
        )

    def get_trading_days(self, exchange: str, trading_day: list[int]) -> pd.DataFrame:
        return pd.DataFrame({"TradingDate": ["2024-01-02", "2024-01-03"], "IfTradingDay": [1, 1]})

    def get_kline(self, htsc_code, time, frequency, fq) -> pd.DataFrame:
        rows = []
        for c in htsc_code:
            for d in ["2024-01-02", "2024-01-03"]:
                rows.append(
                    {
                        "htsc_code": c,
                        "time": pd.Timestamp(d),
                        "open": 10.0,
                        "high": 10.8,
                        "low": 9.9,
                        "close": 10.5,
                        "pre_close": 9.8,
                        "volume": 1000,
                        "value": 10500.0,
                    }
                )
        return pd.DataFrame(rows)


class FakeTushareClient:
    """实现 raw.tushare.client.TushareClient 协议。

    按 start_date/end_date 过滤，以便测试按月分区的抓取逻辑：只有
    2024-01 区间会返回数据，其余月份返回空表。
    """

    STOCKS = ("600000.SH", "000001.SZ")
    INDEXES = ("000300.SH",)
    FUTURES = ("CU2401.SHF",)
    DAYS = ("20240102", "20240103")

    def __init__(self):
        self.calls: list[str] = []

    def _days_in(self, params) -> list[str]:
        """逐日接口按 trade_date 调用；参考类接口仍支持区间。"""
        if "trade_date" in params:
            d = params["trade_date"]
            return [d] if d in self.DAYS else []
        start = params.get("start_date", "00000000")
        end = params.get("end_date", "99999999")
        return [d for d in self.DAYS if start <= d <= end]

    def query(self, api_name: str, **params) -> pd.DataFrame:
        self.calls.append(api_name)
        return getattr(self, f"_{api_name}")(**params)

    def query_all(self, api_name: str, **params) -> pd.DataFrame:
        # Fake 不分页；翻页逻辑由 test_tushare_client 单独覆盖
        params.pop("limit", None)
        params.pop("offset", None)
        params.pop("fields", None)
        return self.query(api_name, **params)

    # ---- reference ----
    def _stock_basic(self, list_status="L", **_) -> pd.DataFrame:
        if list_status != "L":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "symbol": "600000",
                    "name": "浦发银行",
                    "exchange": "SSE",
                    "curr_type": "CNY",
                    "list_status": "L",
                    "list_date": "19991110",
                    "delist_date": None,
                },
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "exchange": "SZSE",
                    "curr_type": "CNY",
                    "list_status": "L",
                    "list_date": "19910403",
                    "delist_date": None,
                },
            ]
        )

    def _index_basic(self, market="SSE", **_) -> pd.DataFrame:
        if market != "SSE":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": "000300.SH",
                    "name": "沪深300",
                    "fullname": "沪深300指数",
                    "market": "SSE",
                    "list_date": "20050408",
                    "exp_date": None,
                }
            ]
        )

    def _fut_basic(self, exchange="SHFE", fut_type="1", **_) -> pd.DataFrame:
        if (exchange, fut_type) != ("SHFE", "1"):
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": "CU2401.SHF",
                    "symbol": "CU2401",
                    "exchange": "SHFE",
                    "name": "沪铜2401",
                    "fut_code": "CU",
                    "multiplier": 5.0,
                    "list_date": "20230117",
                    "delist_date": "20240115",
                }
            ]
        )

    def _trade_cal(self, exchange="SSE", **params) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "exchange": exchange,
                    "cal_date": "20240102",
                    "is_open": 1,
                    "pretrade_date": "20231229",
                },
                {
                    "exchange": exchange,
                    "cal_date": "20240103",
                    "is_open": 1,
                    "pretrade_date": "20240102",
                },
                {
                    "exchange": exchange,
                    "cal_date": "20240106",
                    "is_open": 0,
                    "pretrade_date": "20240105",
                },
            ]
        )

    # ---- 逐日数据集 ----
    def _daily(self, **params) -> pd.DataFrame:
        rows = [
            {
                "ts_code": c,
                "trade_date": d,
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "pre_close": 9.8,
                "pct_chg": 7.14,
                "vol": 1000.0,
                "amount": 10500.0,
            }
            for c in self.STOCKS
            for d in self._days_in(params)
        ]
        return pd.DataFrame(rows)

    def _adj_factor(self, **params) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ts_code": c, "trade_date": d, "adj_factor": 1.25}
                for c in self.STOCKS
                for d in self._days_in(params)
            ]
        )

    def _stk_limit(self, **params) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": c,
                    "trade_date": d,
                    "pre_close": 9.8,
                    "up_limit": 10.78,
                    "down_limit": 8.82,
                }
                for c in self.STOCKS
                for d in self._days_in(params)
            ]
        )

    def _suspend_d(self, **params) -> pd.DataFrame:
        days = self._days_in(params)
        if not days:
            return pd.DataFrame()
        # 仅 600000.SH 在首日停牌
        return pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": days[0],
                    "suspend_type": "S",
                    "suspend_reason": "重大事项",
                }
            ]
        )

    def _index_daily(self, **params) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": c,
                    "trade_date": d,
                    "open": 3400.0,
                    "high": 3450.0,
                    "low": 3380.0,
                    "close": 3420.0,
                    "pre_close": 3390.0,
                    "pct_chg": 0.88,
                    "vol": 200000.0,
                    "amount": 250000.0,
                }
                for c in self.INDEXES
                for d in self._days_in(params)
            ]
        )

    def _fut_daily(self, **params) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": c,
                    "trade_date": d,
                    "pre_close": 68000.0,
                    "pre_settle": 68100.0,
                    "open": 68200.0,
                    "high": 68900.0,
                    "low": 68000.0,
                    "close": 68500.0,
                    "settle": 68400.0,
                    "vol": 5000.0,
                    "amount": 34250.0,
                    "oi": 12000.0,
                }
                for c in self.FUTURES
                for d in self._days_in(params)
            ]
        )


@pytest.fixture
def fake_yinhe():
    return FakeYinheClient()


@pytest.fixture
def fake_ricequant():
    return FakeRicequantClient()


@pytest.fixture
def fake_insight():
    return FakeInsightClient()


@pytest.fixture
def fake_tushare():
    return FakeTushareClient()


# --------------------------------------------------------------------------- #
# PostgreSQL (docker)
# --------------------------------------------------------------------------- #
PG_IMAGE = os.environ.get("GETRICH_TEST_PG_IMAGE", "timescale/timescaledb:latest-pg17-oss")
_CONTAINER = f"getrich-test-pg-{uuid.uuid4().hex[:8]}"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


@pytest.fixture(scope="session")
def pg_dsn():
    """启动一次性 PG 容器，返回 dsn dict；docker 不可用则 skip。"""
    if not _docker_available():
        pytest.skip("docker 不可用，跳过 PostgreSQL 集成测试")

    port = 55432
    proc = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            _CONTAINER,
            "-e",
            "POSTGRES_PASSWORD=test",
            "-e",
            "POSTGRES_DB=getrich",
            "-p",
            f"{port}:5432",
            PG_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"无法启动 PG 容器: {proc.stderr.strip()}")

    dsn = {
        "host": "localhost",
        "port": port,
        "dbname": "getrich",
        "user": "postgres",
        "password": "test",
    }
    try:
        import psycopg

        deadline = time.time() + 60
        last_err = None
        while time.time() < deadline:
            try:
                conn = psycopg.connect(
                    f"host=localhost port={port} dbname=getrich user=postgres password=test",
                    connect_timeout=3,
                )
                conn.close()
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(1)
        else:
            pytest.skip(f"PG 容器未就绪: {last_err}")
        yield dsn
    finally:
        subprocess.run(["docker", "stop", _CONTAINER], capture_output=True)


@pytest.fixture
def pg_conn(pg_dsn):
    """已应用全部 DDL 的干净连接。"""
    import psycopg
    from gr_data.common import migrate as mig

    conn = psycopg.connect(
        f"host={pg_dsn['host']} port={pg_dsn['port']} dbname={pg_dsn['dbname']} "
        f"user={pg_dsn['user']} password={pg_dsn['password']}",
        autocommit=False,
    )
    mig.migrate(conn)
    # 每个测试前清空业务数据，保证隔离（容器为 session 级，importer 会 commit）。
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE
              meta.instruments, meta.symbol_map, meta.trading_calendar,
              market.stock_bar_1d, market.etf_bar_1d, market.index_bar_1d,
              market.future_bar_1d,
              realtime.tick_buffer, ops.table_ownership, ops.etl_job_run
            RESTART IDENTITY CASCADE
            """
        )
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
