import pandas as pd

from getrich.apps.data.table import MinBarTable
from getrich.libs.clickhouse import ClickHouseConnectionPool

if __name__ == "__main__":
    with ClickHouseConnectionPool() as pool:
        min_table = MinBarTable(pool=pool)
        # min_table.optimize()
        result = pd.DataFrame()

        for y in range(2013, 2019):
            strat = f"{y}-01-01"
            endt = f"{y}-12-31"
            #     df = min_table.read(
            #         start_date=strat,
            #         end_date=endt,
            #         symbols=["000016.XSHG", "000300.XSHG", "000905.XSHG", "000852.XSHG"],
            #         order_by="symbol, local_time",
            #     )
            #     result = pd.concat([result, df]) if not result.empty else df

            # result.to_parquet("D:/data/min_bars_index.parquet")

            params = {"prefixes": ["IC", "IH", "IM", "IF"], "start": strat, "end": endt}

            sql = """
                SELECT *
                FROM market_data.bars_1m
                WHERE left(symbol, 2) IN ({prefixes:Array(String)})
                AND dt >= {start:Date}
                AND dt <= {end:Date}
                ORDER BY symbol, local_time
            """
            df = min_table.query(sql, params=params)
            if not df.empty:
                result = pd.concat([result, df]) if not result.empty else df

        # result.to_parquet("D:/data/min_bars_futures.parquet")
        print(result.head())
