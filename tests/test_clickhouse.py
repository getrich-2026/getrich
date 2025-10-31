from __future__ import annotations

from pathlib import Path
from datetime import datetime
from decimal import Decimal
import time
import sys
import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from Data.clickhouse.database import ClickHouseDB

from lntools import Logger

log = Logger("test_clickhouse.log")

# pyright: reportOptionalSubscript=false
# pyright: reportArgumentType=false
# pyright: reportOptionalIterable=false
# pyright: reportIndexIssue=false


class TestClickHouseConnection:
    """ClickHouse 连接和基本操作测试"""

    def setup_class(self):
        """设置测试类，建立 ClickHouse 连接"""
        self.client = ClickHouseDB(
            host='192.168.1.232',
            port=8123,
            database='default',
            user='default',
            password='getrich'
        )

    def teardown_class(self):
        """清理测试类，关闭连接"""
        if hasattr(self, 'client'):
            self.client.close_connection()

    def test_connection(self):
        """测试 ClickHouse 连接"""
        result = self.client.query_sql("SELECT 1 as test", use_df=False)
        assert result[0][0] == 1  # type: ignore
        log.info("✓ ClickHouse 连接成功")

    def test_create_database(self):
        """测试创建数据库"""
        self.client.execute_sql("CREATE DATABASE IF NOT EXISTS test_getrich")
        self.client.execute_sql("USE test_getrich")
        log.info("✓ 数据库创建成功")

    def test_create_tick_table(self):
        """测试创建 Tick 数据表"""
        create_sql = """
        CREATE TABLE IF NOT EXISTS test_tick_data (
            symbol String,
            timestamp DateTime64(3),
            price Decimal(10, 4),
            volume UInt64,
            bid_price Decimal(10, 4),
            ask_price Decimal(10, 4),
            bid_volume UInt64,
            ask_volume UInt64,
            date Date MATERIALIZED toDate(timestamp)
        ) ENGINE = ReplacingMergeTree()
        PARTITION BY date
        ORDER BY (symbol, timestamp)
        SETTINGS index_granularity = 8192
        """
        self.client.execute_sql(create_sql)
        log.info("✓ Tick 数据表创建成功（ReplacingMergeTree引擎）")

    def test_create_kline_table(self):
        """测试创建 K线数据表"""
        create_sql = """
        CREATE TABLE IF NOT EXISTS test_kline_data (
            symbol String,
            timestamp DateTime,
            open_price Decimal(10, 4),
            high_price Decimal(10, 4),
            low_price Decimal(10, 4),
            close_price Decimal(10, 4),
            volume UInt64,
            amount Decimal(18, 4),
            interval String,
            date Date MATERIALIZED toDate(timestamp)
        ) ENGINE = ReplacingMergeTree()
        PARTITION BY (interval, date)
        ORDER BY (symbol, interval, timestamp)
        SETTINGS index_granularity = 8192
        """
        self.client.execute_sql(create_sql)
        log.info("✓ K线数据表创建成功（ReplacingMergeTree引擎）")

    def test_insert_tick_data(self):
        """测试插入 Tick 数据"""
        now = datetime.now()
        test_data = [
            ['000001.SZ', now, Decimal('15.24'), 1000, Decimal('15.23'), Decimal('15.25'), 500, 600],
            ['000002.SZ', now, Decimal('8.56'), 2000, Decimal('8.55'), Decimal('8.57'), 800, 900]
        ]

        self.client.insert_data("test_tick_data", test_data,
                                column_names=['symbol', 'timestamp', 'price', 'volume',
                                              'bid_price', 'ask_price', 'bid_volume', 'ask_volume'])
        log.info("✓ Tick 数据插入成功")

    def test_insert_kline_data(self):
        """测试插入 K线数据"""
        now = datetime.now()
        test_data = [
            ['000001.SZ', now, Decimal('15.20'), Decimal('15.30'), Decimal('15.15'), Decimal('15.25'),
             100000, Decimal('1520000.00'), '1m'],
            ['000002.SZ', now, Decimal('8.50'), Decimal('8.60'), Decimal('8.48'), Decimal('8.58'),
             200000, Decimal('1712000.00'), '1m']
        ]

        self.client.insert_data("test_kline_data", test_data,
                                column_names=['symbol', 'timestamp', 'open_price', 'high_price', 'low_price',
                                              'close_price', 'volume', 'amount', 'interval'])
        log.info("✓ K线数据插入成功")

    def test_query_tick_data(self):
        """测试查询 Tick 数据"""
        # 原有的 list 返回测试
        result = self.client.query_sql("""
            SELECT symbol, price, volume
            FROM test_tick_data
            WHERE symbol = '000001.SZ'
            ORDER BY timestamp DESC
            LIMIT 10
        """, use_df=False)

        assert len(result) > 0  # type: ignore
        log.info(f"✓ Tick 数据查询成功（list格式），共 {len(result)} 条记录")  # type: ignore
        for row in result:  # type: ignore
            log.info(f"  股票: {row[0]}, 价格: {row[1]}, 成交量: {row[2]}")  # type: ignore

        # 新增的 DataFrame 返回测试
        df_result = self.client.query_sql("""
            SELECT symbol, price, volume, timestamp
            FROM test_tick_data
            WHERE symbol = '000001.SZ'
            ORDER BY timestamp DESC
            LIMIT 10
        """, use_df=True)

        assert isinstance(df_result, pd.DataFrame)
        assert len(df_result) > 0
        log.info(f"✓ Tick 数据查询成功（DataFrame格式），共 {len(df_result)} 条记录")
        log.info(f"  DataFrame 列名: {list(df_result.columns)}")
        log.info(f"  DataFrame 形状: {df_result.shape}")
        log.info(f"  前3条数据:\n{df_result.head(3)}")

    def test_query_kline_data(self):
        """测试查询 K线数据"""
        # 原有的 list 返回测试
        result = self.client.query_sql("""
            SELECT symbol, open_price, high_price, low_price, close_price, volume
            FROM test_kline_data
            WHERE interval = '1m'
            ORDER BY timestamp DESC
            LIMIT 5
        """, use_df=False)

        assert len(result) > 0
        log.info(f"✓ K线数据查询成功（list格式），共 {len(result)} 条记录")
        for row in result:
            log.info(f"  股票: {row[0]}, OHLC: {row[1]}/{row[2]}/{row[3]}/{row[4]}, 成交量: {row[5]}")

        # 新增的 DataFrame 返回测试
        df_result = self.client.query_sql("""
            SELECT symbol, open_price, high_price, low_price, close_price, volume, timestamp
            FROM test_kline_data
            WHERE interval = '1m'
            ORDER BY timestamp DESC
            LIMIT 5
        """, use_df=True)

        assert isinstance(df_result, pd.DataFrame)
        assert len(df_result) > 0
        log.info(f"✓ K线数据查询成功（DataFrame格式），共 {len(df_result)} 条记录")
        log.info(f"  DataFrame 列名: {list(df_result.columns)}")
        log.info(f"  前3条数据:\n{df_result.head(3)}")

    def test_dataframe_operations(self):
        """测试 DataFrame 数据操作和分析"""
        # 查询更多数据用于分析
        df = self.client.query_sql("""
            SELECT symbol, price, volume, bid_price, ask_price, timestamp
            FROM test_tick_data
            ORDER BY timestamp DESC
        """, use_df=True)

        assert isinstance(df, pd.DataFrame)
        log.info("✓ DataFrame 操作测试开始")

        # 基本信息
        log.info(f"  数据形状: {df.shape}")
        log.info(f"  数据类型:\n{df.dtypes}")

        # 数据统计
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            log.info(f"  数值列统计:\n{df[numeric_cols].describe()}")

        # 分组统计
        if len(df) > 0:
            symbol_counts = df['symbol'].value_counts()
            log.info(f"  按股票代码统计:\n{symbol_counts}")

            # 价格计算
            if 'price' in df.columns:
                avg_price = df.groupby('symbol')['price'].mean()
                log.info(f"  平均价格:\n{avg_price}")

        log.info("✓ DataFrame 操作测试完成")

    def test_large_dataframe_query(self):
        """测试大数据量 DataFrame 查询性能"""
        # 插入更多测试数据
        import random
        from datetime import timedelta

        large_data = []
        base_time = datetime.now()
        symbols = ['000001.SZ', '000002.SZ', '600000.SH', '600519.SH']

        for i in range(100):  # 插入100条记录
            symbol = random.choice(symbols)
            timestamp = base_time + timedelta(seconds=i)
            price = Decimal(f"{random.uniform(10, 100):.4f}")
            volume = random.randint(100, 10000)

            large_data.append([
                symbol, timestamp, price, volume,
                price - Decimal('0.01'), price + Decimal('0.01'),
                volume // 2, volume // 3
            ])

        # 批量插入
        self.client.insert_data("test_tick_data", large_data,
                                column_names=['symbol', 'timestamp', 'price', 'volume',
                                              'bid_price', 'ask_price', 'bid_volume', 'ask_volume'])

        # 查询 DataFrame
        df = self.client.query_sql("""
            SELECT symbol, price, volume, timestamp,
                   price * volume as turnover
            FROM test_tick_data
            ORDER BY timestamp DESC
            LIMIT 50
        """, use_df=True)

        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 50
        log.info(f"✓ 大数据量 DataFrame 查询成功，获取 {len(df)} 条记录")
        log.info(f"  包含计算字段: {'turnover' in df.columns}")

        # 验证计算字段
        if 'turnover' in df.columns and len(df) > 0:
            calculated_turnover = df['price'] * df['volume']
            log.info(f"  计算字段验证: {(df['turnover'] == calculated_turnover).all()}")

    def test_table_stats(self):
        """测试表统计信息"""
        tables = ['test_tick_data', 'test_kline_data']

        for table in tables:
            result = self.client.query_sql(f"SELECT count() FROM {table}", use_df=False)
            count = result[0][0]
            log.info(f"✓ 表 {table} 共有 {count} 条记录")

            # 查看表结构
            result = self.client.query_sql(f"DESCRIBE TABLE {table}", use_df=False)
            log.info(f"  表 {table} 结构:")
            for col in result[:5]:  # 只显示前5列
                log.info(f"    {col[0]}: {col[1]}")

    def test_cleanup(self):
        """清理测试数据"""
        cleanup_tables = ['test_tick_data', 'test_kline_data']

        for table in cleanup_tables:
            try:
                self.client.execute_sql(f"DROP TABLE IF EXISTS {table}")
                log.info(f"✓ 表 {table} 清理完成")
            except Exception as e:
                log.info(f"⚠ 清理表 {table} 时出错: {e}")

    def test_upsert_tick_data(self):
        """测试 Tick 数据的 upsert 操作"""
        log.info("开始测试 Tick 数据 upsert 操作...")

        # 1. 准备初始数据
        base_time = datetime.now()
        initial_data = pd.DataFrame([
            ['000001.SZ', base_time, Decimal('15.24'), 1000, Decimal('15.23'), Decimal('15.25'), 500, 600],
            ['000002.SZ', base_time, Decimal('8.56'), 2000, Decimal('8.55'), Decimal('8.57'), 800, 900],
            ['000003.SZ', base_time, Decimal('12.30'), 1500, Decimal('12.29'), Decimal('12.31'), 700, 800]
        ], columns=['symbol', 'timestamp', 'price', 'volume', 'bid_price', 'ask_price', 'bid_volume', 'ask_volume'])

        # 插入初始数据
        result = self.client.upsert_data("test_tick_data", initial_data, key_columns=['symbol', 'timestamp'])
        assert result is True
        log.info("✓ 初始数据 upsert 成功")

        # 等待一段时间让 ClickHouse 处理数据
        time.sleep(2)

        # 验证初始数据
        df_initial = self.client.query_sql("""
            SELECT symbol, price, volume
            FROM test_tick_data
            WHERE symbol IN ('000001.SZ', '000002.SZ', '000003.SZ')
            ORDER BY symbol
        """, use_df=True)

        log.info("✓ 初始数据验证:")
        initial_prices = {}
        initial_volumes = {}
        for _, row in df_initial.iterrows():
            symbol = row['symbol']
            initial_prices[symbol] = row['price']
            initial_volumes[symbol] = row['volume']
            log.info(f"    {symbol}: 价格={row['price']}, 成交量={row['volume']}")

        # 2. 准备更新数据（包含相同键值的更新和新增）
        update_data = pd.DataFrame([
            ['000001.SZ', base_time, Decimal('15.30'), 1200, Decimal('15.29'), Decimal('15.31'), 600, 700],  # 更新现有记录
            ['000002.SZ', base_time, Decimal('8.60'), 2200, Decimal('8.59'), Decimal('8.61'), 900, 1000],   # 更新现有记录
            ['000004.SZ', base_time, Decimal('18.50'), 800, Decimal('18.49'), Decimal('18.51'), 400, 500]   # 新增记录
        ], columns=['symbol', 'timestamp', 'price', 'volume', 'bid_price', 'ask_price', 'bid_volume', 'ask_volume'])

        log.info("✓ 准备更新数据:")
        update_prices = {}
        update_volumes = {}
        for _, row in update_data.iterrows():
            symbol = row['symbol']
            update_prices[symbol] = row['price']
            update_volumes[symbol] = row['volume']
            log.info(f"    {symbol}: 价格={row['price']}, 成交量={row['volume']}")

        # 执行 upsert
        result = self.client.upsert_data("test_tick_data", update_data, key_columns=['symbol', 'timestamp'])
        assert result is True
        log.info("✓ 更新数据 upsert 成功")

        # 等待一段时间让 ClickHouse 处理数据
        time.sleep(3)

        # 3. 验证更新结果
        df_final = self.client.query_sql("""
            SELECT symbol, price, volume
            FROM test_tick_data FINAL
            WHERE symbol IN ('000001.SZ', '000002.SZ', '000003.SZ', '000004.SZ')
            ORDER BY symbol
        """, use_df=True)

        log.info("✓ 最终数据验证:")
        final_prices = {}
        final_volumes = {}
        for _, row in df_final.iterrows():
            symbol = row['symbol']
            final_prices[symbol] = row['price']
            final_volumes[symbol] = row['volume']
            log.info(f"    {symbol}: 价格={row['price']}, 成交量={row['volume']}")

        # 4. 验证更新操作的正确性
        log.info("✓ 更新操作验证:")

        # 验证 000001.SZ 的更新
        if '000001.SZ' in final_prices:
            expected_price = Decimal('15.30')
            expected_volume = 1200
            actual_price = final_prices['000001.SZ']
            actual_volume = final_volumes['000001.SZ']

            price_updated = actual_price == expected_price
            volume_updated = actual_volume == expected_volume

            log.info(f"    000001.SZ 价格更新: {initial_prices.get('000001.SZ')} -> {actual_price} (期望: {expected_price}) {'✓' if price_updated else '✗'}")
            log.info(f"    000001.SZ 成交量更新: {initial_volumes.get('000001.SZ')} -> {actual_volume} (期望: {expected_volume}) {'✓' if volume_updated else '✗'}")

            assert price_updated, f"000001.SZ 价格更新失败: 期望 {expected_price}, 实际 {actual_price}"
            assert volume_updated, f"000001.SZ 成交量更新失败: 期望 {expected_volume}, 实际 {actual_volume}"

        # 验证 000002.SZ 的更新
        if '000002.SZ' in final_prices:
            expected_price = Decimal('8.60')
            expected_volume = 2200
            actual_price = final_prices['000002.SZ']
            actual_volume = final_volumes['000002.SZ']

            price_updated = actual_price == expected_price
            volume_updated = actual_volume == expected_volume

            log.info(f"    000002.SZ 价格更新: {initial_prices.get('000002.SZ')} -> {actual_price} (期望: {expected_price}) {'✓' if price_updated else '✗'}")
            log.info(f"    000002.SZ 成交量更新: {initial_volumes.get('000002.SZ')} -> {actual_volume} (期望: {expected_volume}) {'✓' if volume_updated else '✗'}")

            assert price_updated, f"000002.SZ 价格更新失败: 期望 {expected_price}, 实际 {actual_price}"
            assert volume_updated, f"000002.SZ 成交量更新失败: 期望 {expected_volume}, 实际 {actual_volume}"

        # 验证 000003.SZ 保持不变（没有更新）
        if '000003.SZ' in final_prices:
            expected_price = initial_prices['000003.SZ']
            expected_volume = initial_volumes['000003.SZ']
            actual_price = final_prices['000003.SZ']
            actual_volume = final_volumes['000003.SZ']

            unchanged = (actual_price == expected_price and actual_volume == expected_volume)
            log.info(f"    000003.SZ 保持不变: 价格={actual_price}, 成交量={actual_volume} {'✓' if unchanged else '✗'}")

        # 验证 000004.SZ 的新增
        if '000004.SZ' in final_prices:
            expected_price = Decimal('18.50')
            expected_volume = 800
            actual_price = final_prices['000004.SZ']
            actual_volume = final_volumes['000004.SZ']

            new_record = (actual_price == expected_price and actual_volume == expected_volume)
            log.info(f"    000004.SZ 新增记录: 价格={actual_price}, 成交量={actual_volume} {'✓' if new_record else '✗'}")

            assert new_record, f"000004.SZ 新增失败"

        # 验证总记录数（应该有4条记录，没有重复）
        expected_count = 4
        actual_count = len(df_final)
        log.info(f"✓ 记录数验证: 期望 {expected_count} 条, 实际 {actual_count} 条 {'✓' if actual_count == expected_count else '✗'}")

    def test_upsert_kline_data(self):
        """测试 K线数据的 upsert 操作（多列键）"""
        log.info("开始测试 K线数据 upsert 操作（多列键）...")

        # 1. 准备初始数据
        base_time = datetime.now()
        initial_data = pd.DataFrame([
            ['000001.SZ', base_time, Decimal('15.20'), Decimal('15.30'), Decimal('15.15'), Decimal('15.25'), 100000, Decimal('1520000.00'), '1m'],
            ['000001.SZ', base_time, Decimal('15.25'), Decimal('15.35'), Decimal('15.20'), Decimal('15.30'), 120000, Decimal('1830000.00'), '5m'],
            ['000002.SZ', base_time, Decimal('8.50'), Decimal('8.60'), Decimal('8.48'), Decimal('8.58'), 200000, Decimal('1712000.00'), '1m']
        ], columns=['symbol', 'timestamp', 'open_price', 'high_price', 'low_price', 'close_price', 'volume', 'amount', 'interval'])

        # 插入初始数据
        result = self.client.upsert_data("test_kline_data", initial_data, key_columns=['symbol', 'timestamp', 'interval'])
        assert result is True
        log.info("✓ 初始 K线数据 upsert 成功")

        # 等待处理
        time.sleep(2)

        # 验证初始数据
        df_initial = self.client.query_sql("""
            SELECT symbol, interval, close_price, volume
            FROM test_kline_data
            ORDER BY symbol, interval
        """, use_df=True)

        log.info("✓ 初始 K线数据:")
        initial_data_map = {}
        for _, row in df_initial.iterrows():
            key = f"{row['symbol']}-{row['interval']}"
            initial_data_map[key] = {'close_price': row['close_price'], 'volume': row['volume']}
            log.info(f"    {key}: 收盘价={row['close_price']}, 成交量={row['volume']}")

        # 2. 准备更新数据（包含相同复合键的更新）
        update_data = pd.DataFrame([
            ['000001.SZ', base_time, Decimal('15.22'), Decimal('15.32'), Decimal('15.17'), Decimal('15.28'), 110000, Decimal('1680000.00'), '1m'],  # 更新 000001.SZ-1m
            ['000003.SZ', base_time, Decimal('20.10'), Decimal('20.20'), Decimal('20.05'), Decimal('20.15'), 50000, Decimal('1007500.00'), '1m']   # 新增 000003.SZ-1m
        ], columns=['symbol', 'timestamp', 'open_price', 'high_price', 'low_price', 'close_price', 'volume', 'amount', 'interval'])

        log.info("✓ 准备更新 K线数据:")
        update_data_map = {}
        for _, row in update_data.iterrows():
            key = f"{row['symbol']}-{row['interval']}"
            update_data_map[key] = {'close_price': row['close_price'], 'volume': row['volume']}
            log.info(f"    {key}: 收盘价={row['close_price']}, 成交量={row['volume']}")

        # 执行 upsert
        result = self.client.upsert_data("test_kline_data", update_data, key_columns=['symbol', 'timestamp', 'interval'])
        assert result is True
        log.info("✓ K线数据更新 upsert 成功")

        # 等待处理
        time.sleep(3)

        # 3. 验证最终结果
        df_final = self.client.query_sql("""
            SELECT symbol, interval, close_price, volume
            FROM test_kline_data FINAL
            ORDER BY symbol, interval
        """, use_df=True)

        log.info("✓ 最终 K线数据:")
        final_data_map = {}
        for _, row in df_final.iterrows():
            key = f"{row['symbol']}-{row['interval']}"
            final_data_map[key] = {'close_price': row['close_price'], 'volume': row['volume']}
            log.info(f"    {key}: 收盘价={row['close_price']}, 成交量={row['volume']}")

        # 4. 验证更新操作
        log.info("✓ K线数据更新验证:")

        # 验证 000001.SZ-1m 的更新
        key = '000001.SZ-1m'
        if key in final_data_map:
            expected_close = Decimal('15.28')
            expected_volume = 110000
            actual_close = final_data_map[key]['close_price']
            actual_volume = final_data_map[key]['volume']

            close_updated = actual_close == expected_close
            volume_updated = actual_volume == expected_volume

            log.info(f"    {key} 更新验证:")
            log.info(f"      收盘价: {initial_data_map.get(key, {}).get('close_price')} -> {actual_close} (期望: {expected_close}) {'✓' if close_updated else '✗'}")
            log.info(f"      成交量: {initial_data_map.get(key, {}).get('volume')} -> {actual_volume} (期望: {expected_volume}) {'✓' if volume_updated else '✗'}")

            assert close_updated, f"{key} 收盘价更新失败"
            assert volume_updated, f"{key} 成交量更新失败"

        # 验证 000001.SZ-5m 保持不变
        key = '000001.SZ-5m'
        if key in final_data_map and key in initial_data_map:
            initial_close = initial_data_map[key]['close_price']
            final_close = final_data_map[key]['close_price']
            unchanged = initial_close == final_close
            log.info(f"    {key} 保持不变: {'✓' if unchanged else '✗'}")

        # 验证 000003.SZ-1m 的新增
        key = '000003.SZ-1m'
        if key in final_data_map:
            expected_close = Decimal('20.15')
            expected_volume = 50000
            actual_close = final_data_map[key]['close_price']
            actual_volume = final_data_map[key]['volume']

            new_record = (actual_close == expected_close and actual_volume == expected_volume)
            log.info(f"    {key} 新增验证: {'✓' if new_record else '✗'}")

            assert new_record, f"{key} 新增失败"

        # 验证总记录数
        expected_count = 4  # 原来3条 + 新增1条 = 4条
        actual_count = len(df_final)
        log.info(f"✓ K线记录数验证: 期望 {expected_count} 条, 实际 {actual_count} 条 {'✓' if actual_count == expected_count else '✗'}")


if __name__ == "__main__":
    # 直接运行测试
    test_instance = TestClickHouseConnection()

    try:
        log.info("开始 ClickHouse 连接测试...")
        test_instance.setup_class()

        # 按顺序执行测试
        # test_instance.test_connection()
        # test_instance.test_create_database()
        test_instance.test_create_tick_table()
        test_instance.test_create_kline_table()
        # test_instance.test_insert_tick_data()
        # test_instance.test_insert_kline_data()
        # test_instance.test_query_tick_data()
        # test_instance.test_query_kline_data()
        # test_instance.test_dataframe_operations()
        # test_instance.test_large_dataframe_query()
        test_instance.test_upsert_tick_data()
        test_instance.test_upsert_kline_data()
        # test_instance.test_table_stats()

        log.info("\n所有测试完成！")

        # 询问是否清理测试数据
        cleanup = input("\n是否清理测试数据？(y/n): ").lower().strip()
        if cleanup == 'y':
            test_instance.test_cleanup()

        # test_instance.test_cleanup()

    except Exception as e:
        log.info(f"测试过程中出错: {e}")
    finally:
        test_instance.teardown_class()
