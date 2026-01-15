from lntools.utils import track_simple

from getrich.apps.data.table import MinBarTable
from getrich.libs.clickhouse import ClickHouseConnectionPool

if __name__ == "__main__":
    with ClickHouseConnectionPool(min_size=2, max_size=10) as pool:
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
    for y in range(2026, 2027):
        periods.append((y, 1, f"{y}-01-01", f"{y}-06-30", "H1"))  # 上半年
        # periods.append((y, 2, f"{y}-07-01", f"{y}-12-31", "H2"))  # 下半年

    for year, _, start_date, end_date, period_label in track_simple(
        periods, msg="Exporting data by half-year"
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
            output_path = f"D:/data/min_bars_CS_{year}_{period_label}.parquet"
            df.to_parquet(output_path)
            print(f"Exported {len(df)} records for {year} {period_label} to {output_path}")
        else:
            print(f"No data found for {year} {period_label}")
