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

from getrich_data.common.paths import RawPaths


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
                    "open": [10.0, 10.5], "high": [10.8, 10.9], "low": [9.9, 10.2],
                    "close": [10.5, 10.7], "pre_close": [9.8, 10.5],
                    "volume": [1000, 1200], "amount": [10500.0, 12840.0],
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
            [{"order_book_id": o, "symbol": s, "exchange": e,
              "status": "Active", "listed_date": "2010-01-01", "de_listed_date": "0000-00-00"}
             for o, s, e in data]
        )

    def get_trading_dates(self, start_date, end_date, market="cn"):
        return [pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-03").date()]

    def get_price(self, symbols, start_date, end_date, frequency="1d", adjust_type="none", market="cn"):
        rows = []
        for s in symbols:
            for d in ["2024-01-02", "2024-01-03"]:
                rows.append({"order_book_id": s, "date": pd.Timestamp(d),
                             "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.5,
                             "prev_close": 9.8, "volume": 1000, "total_turnover": 10500.0})
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
        return pd.DataFrame([{"htsc_code": c, "security_name": n, "exchange": "XSHG"} for c, n in data])

    def get_trading_days(self, exchange: str, trading_day: list[int]) -> pd.DataFrame:
        return pd.DataFrame({"TradingDate": ["2024-01-02", "2024-01-03"], "IfTradingDay": [1, 1]})

    def get_kline(self, htsc_code, time, frequency, fq) -> pd.DataFrame:
        rows = []
        for c in htsc_code:
            for d in ["2024-01-02", "2024-01-03"]:
                rows.append({"htsc_code": c, "time": pd.Timestamp(d),
                             "open": 10.0, "high": 10.8, "low": 9.9, "close": 10.5,
                             "pre_close": 9.8, "volume": 1000, "value": 10500.0})
        return pd.DataFrame(rows)


@pytest.fixture
def fake_yinhe():
    return FakeYinheClient()


@pytest.fixture
def fake_ricequant():
    return FakeRicequantClient()


@pytest.fixture
def fake_insight():
    return FakeInsightClient()


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
        ["docker", "run", "-d", "--rm", "--name", _CONTAINER,
         "-e", "POSTGRES_PASSWORD=test", "-e", "POSTGRES_DB=getrich",
         "-p", f"{port}:5432", PG_IMAGE],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"无法启动 PG 容器: {proc.stderr.strip()}")

    dsn = {"host": "localhost", "port": port, "dbname": "getrich",
           "user": "postgres", "password": "test"}
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

    from getrich_data.common import migrate as mig

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
