import os

from lntools.utils import track_simple

from getrich.apps.data.table import MinBarTable
from getrich.libs.clickhouse import ClickHouseConnectionPool


def export_cs_min_bars(pool: ClickHouseConnectionPool, output_dir: str, years: list[int]) -> None:
    """
    导出所有股票 (CS) 的分钟线数据，按半年一个文件。
    """
    min_table = MinBarTable(pool=pool)

    # 查询 ref.instruments 中 type='CS' 的所有 symbols
    SQL_GET_SYMBOLS = """
        SELECT DISTINCT symbol
        FROM ref.instruments
        WHERE type = 'CS'
    """
    symbols_df = min_table.query(SQL_GET_SYMBOLS)
    cs_symbols = symbols_df["symbol"].tolist()
    print(f"Found {len(cs_symbols)} CS symbols in ref.instruments")

    # 按半年度导出数据
    periods = []
    for y in years:
        periods.append((y, 1, f"{y}-01-01", f"{y}-06-30", "H1"))  # 上半年
        # periods.append((y, 2, f"{y}-07-01", f"{y}-12-31", "H2"))  # 下半年

    for year, _, start_date, end_date, period_label in track_simple(
        periods, msg="Exporting CS min bars"
    ):
        params = {"symbols": cs_symbols, "start": start_date, "end": end_date}

        SQL_QUERY = """
            SELECT *
            FROM market_data.bars_1m
            WHERE symbol IN ({symbols:Array(String)})
            AND dt >= {start:Date}
            AND dt <= {end:Date}
            ORDER BY symbol, local_time
        """

        df = min_table.query(SQL_QUERY, params=params)

        if not df.empty:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"min_bars_CS_{year}_{period_label}.parquet")
            df.to_parquet(output_path)
            print(f"Exported {len(df)} records for {year} {period_label} to {output_path}")
        else:
            print(f"No CS data found for {year} {period_label}")


def export_indices_futures_min_bars(
    pool: ClickHouseConnectionPool, output_dir: str, years: list[int]
) -> None:
    """
    导出指定的宽基指数和对应的股指期货分钟线数据。
    """
    min_table = MinBarTable(pool=pool)

    # 宽基指数 symbols
    indices = ["000300.XSHG", "000016.XSHG", "000905.XSHG", "000852.XSHG"]

    # 获取股指期货 symbols (IC, IH, IF, IM)
    SQL_GET_FUTURES = """
        SELECT DISTINCT symbol
        FROM ref.instruments
        WHERE type = 'Future'
        AND (symbol LIKE 'IC%' OR symbol LIKE 'IH%' OR symbol LIKE 'IF%' OR symbol LIKE 'IM%')
    """
    futures_df = min_table.query(SQL_GET_FUTURES)
    futures_symbols = futures_df["symbol"].tolist()

    all_symbols = indices + futures_symbols
    print(f"Found {len(indices)} indices and {len(futures_symbols)} future symbols")

    for year in track_simple(years, msg="Exporting Indices and Futures min bars"):
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"

        params = {"symbols": all_symbols, "start": start_date, "end": end_date}

        SQL_QUERY = """
            SELECT *
            FROM market_data.bars_1m
            WHERE symbol IN ({symbols:Array(String)})
            AND dt >= {start:Date}
            AND dt <= {end:Date}
            ORDER BY symbol, local_time
        """

        df = min_table.query(SQL_QUERY, params=params)

        if not df.empty:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"min_bars_Indices_Futures_{year}.parquet")
            df.to_parquet(output_path)
            print(f"Exported {len(df)} records for {year} to {output_path}")
        else:
            print(f"No Indices/Futures data found for {year}")


if __name__ == "__main__":
    DATA_DIR = "E:/data"
    YEARS = [2026]

    with ClickHouseConnectionPool(min_size=2, max_size=10) as pool:
        # 1. 导出股票数据 (CS)
        # export_cs_min_bars(pool, DATA_DIR, YEARS)

        # 2. 导出指数和期货数据
        export_indices_futures_min_bars(pool, DATA_DIR, YEARS)
