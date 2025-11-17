"""
测试 CodeInfoTable 的创建和使用
"""
from lntools import Logger
import pandas as pd
from Data.clickhouse.table.bar import CodeInfoTable

# 初始化日志
log = Logger(module_name="TestCodeInfo", output_method="console")


def test_code_info_table():
    """测试 CodeInfoTable 的基本功能"""

    # 测试表名
    TABLE_NAME = 'code_info_test'

    try:
        # 1. 创建 CodeInfoTable 实例
        log.info(f"--- Step 1: Initialize CodeInfoTable '{TABLE_NAME}' ---")
        code_info_table = CodeInfoTable(table_name=TABLE_NAME)
        log.info("Successfully connected to ClickHouse")

        # 2. 删除已存在的测试表
        log.info(f"--- Step 2: Drop old test table '{TABLE_NAME}' (if exists) ---")
        code_info_table.drop()

        # 3. 创建新表
        log.info(f"--- Step 3: Create new table '{TABLE_NAME}' ---")
        if not code_info_table.create():
            raise RuntimeError("Failed to create table")

        # 4. 准备测试数据
        log.info("--- Step 4: Prepare sample code info data ---")
        sample_data = {
            'sec_type': [0, 1, 0, 1],
            'sec_name': ['浦发银行', '工商银行', '中国平安', '贵州茅台'],
            'date': [20250101, 20250101, 20250101, 20250101],
            'high_limited': [30350000, 28900000, 45600000, 182500000],
            'low_limited': [22890000, 21800000, 34400000, 137500000],
            'multiplier': [0, 0, 0, 0],
            'margin_ratio': [0, 0, 0, 0],
            'price_tick': [0, 0, 0, 0],
            'capital': [0, 0, 0, 0],
            'cap_change_date': [0, 0, 0, 0],
            'trade_date_in': [20050104, 20060427, 20070301, 20010827],
            'trade_date_out': [20260714, 20260714, 20260714, 20260714],
            'is_halt': [0, 0, 0, 0],
            'margin_unit': [0, 0, 0, 0],
            'margin_ratio_param1': [0, 0, 0, 0],
            'margin_ratio_param2': [0, 0, 0, 0],
            'sec_name_ext': ['', '', '', ''],
            'symbol': ['SH.600000', 'SH.601398', 'SH.601318', 'SH.600519']
        }
        sample_df = pd.DataFrame(sample_data)
        log.info(f"Created DataFrame with {len(sample_df)} records")
        print(sample_df)

        # 5. 插入数据
        log.info(f"--- Step 5: Insert data into '{TABLE_NAME}' ---")
        code_info_table.insert(sample_df)

        # 6. 测试查询功能
        log.info("--- Step 6: Test different query scenarios ---")

        # 场景1: 查询所有数据
        log.info("\nScenario 1: Read all data")
        result1 = code_info_table.read()
        if result1 is not None:
            print(f"Total records: {len(result1)}")
            print(result1)

        # 场景2: 查询单个标的
        log.info("\nScenario 2: Get info for single symbol")
        result2 = code_info_table.get_by_symbol('SH.600000')
        if result2 is not None:
            print("Info for SH.600000:")
            print(result2)

        # 场景3: 查询多个标的
        log.info("\nScenario 3: Read data for multiple symbols")
        result3 = code_info_table.read(symbols=['SH.600000', 'SH.601398'])
        if result3 is not None:
            print(f"Records for multiple symbols: {len(result3)}")
            print(result3[['symbol', 'sec_name', 'trade_date_in']])

        # 场景4: 按证券类型筛选
        log.info("\nScenario 4: Filter by sec_type")
        result4 = code_info_table.read(sec_type=0)
        if result4 is not None:
            print(f"Records with sec_type=0: {len(result4)}")
            print(result4[['symbol', 'sec_name', 'sec_type']])

        # 7. 统计记录数
        log.info("\n--- Step 7: Count records ---")
        count = code_info_table.count()
        log.info(f"Total records in '{TABLE_NAME}': {count}")

        # 8. 清理测试表
        log.info(f"\n--- Step 8: Clean up test table '{TABLE_NAME}' ---")
        code_info_table.drop()

        log.info("CodeInfoTable test completed successfully!")

    except Exception as e:
        log.error(f"Error during test: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if 'code_info_table' in locals():
            code_info_table.close()
            log.info("Connection closed")


if __name__ == '__main__':
    test_code_info_table()
