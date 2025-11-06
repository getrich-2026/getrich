"""
测试 ClickHouseTable 基类功能
"""
import pandas as pd
from lntools import Logger
from Data.clickhouse.table import MinBarTable

logger = Logger(module_name="test_base_class")


def test_default_config():
    """测试使用默认配置"""
    logger.info("=" * 60)
    logger.info("测试 1: 使用默认配置")
    logger.info("=" * 60)

    # 使用默认配置（从 config.yml 读取）
    table = MinBarTable(table_name='test_min_bar')

    # 输出配置信息
    config = table.get_config()
    logger.info(f"当前配置: {config}")

    # 检查连接
    logger.info(f"连接状态: {'已连接' if table.client else '未连接'}")

    table.close()


def test_custom_config():
    """测试自定义配置"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 2: 使用自定义配置")
    logger.info("=" * 60)

    # 显式指定配置
    table = MinBarTable(
        table_name='test_min_bar',
        host='localhost',
        port=8123,
        user='default',
        password='getrich',
        database='default'
    )

    config = table.get_config()
    logger.info(f"当前配置: {config}")

    table.close()


def test_configure_runtime():
    """测试运行时配置"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 3: 运行时修改配置")
    logger.info("=" * 60)

    # 初始使用默认配置
    table = MinBarTable(table_name='test_min_bar')
    logger.info(f"初始配置: {table.get_config()}")

    # 运行时修改配置
    table.configure(
        host='localhost',
        database='test_db',
        reconnect=False  # 不重新连接
    )
    logger.info(f"修改后配置: {table.get_config()}")

    table.close()


def test_context_manager():
    """测试上下文管理器"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 4: 使用上下文管理器")
    logger.info("=" * 60)

    with MinBarTable(table_name='test_min_bar') as table:
        logger.info(f"在 with 块中，连接状态: {'已连接' if table.client else '未连接'}")

    logger.info("退出 with 块后，连接已自动关闭")


def test_table_operations():
    """测试表操作"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 5: 表操作（创建、插入、查询、删除）")
    logger.info("=" * 60)

    table = MinBarTable(table_name='test_min_bar_ops')

    try:
        # 1. 删除旧表（如果存在）
        logger.info("步骤 1: 删除旧表")
        table.drop(if_exists=True)

        # 2. 检查表是否存在
        logger.info(f"表是否存在: {table.exists()}")

        # 3. 创建表
        logger.info("步骤 2: 创建表")
        if table.create(if_not_exists=True):
            logger.info("表创建成功")

        # 4. 检查表是否存在
        logger.info(f"表是否存在: {table.exists()}")

        # 5. 准备测试数据
        logger.info("步骤 3: 准备测试数据")
        test_data = pd.DataFrame({
            'date': [20250101, 20250101],
            'time': [93100000, 93200000],
            'pre_close': [100000, 100000],
            'open': [101000, 101500],
            'high': [102000, 102500],
            'low': [100500, 101200],
            'close': [101500, 102200],
            'volume': [10000, 12000],
            'turnover': [1015000000, 1226400000],
            'open_interest': [0, 0],
            'pre_settle_price': [0, 0],
            'settle_price': [0, 0],
            'symbol': ['SH.600000.TEST', 'SH.600000.TEST'],
            'local_time': pd.to_datetime(['2025-01-01 09:31:00', '2025-01-01 09:32:00'])
        })

        # 6. 插入数据
        logger.info("步骤 4: 插入数据")
        if table.insert(test_data):
            logger.info(f"成功插入 {len(test_data)} 条记录")

        # 7. 统计记录数
        count = table.count()
        logger.info(f"表中共有 {count} 条记录")

        # 8. 查询数据
        logger.info("步骤 5: 查询数据")
        query = f"SELECT * FROM {table.table_name} LIMIT 5"
        result = table.query(query)
        if result is not None:
            logger.info(f"查询成功，返回 {len(result)} 条记录")
            logger.info(f"\n{result}")

        # 9. 清空表
        logger.info("步骤 6: 清空表")
        if table.truncate():
            logger.info("表已清空")
            logger.info(f"清空后记录数: {table.count()}")

        # 10. 删除表
        logger.info("步骤 7: 删除表")
        if table.drop(if_exists=True):
            logger.info("表已删除")

    except Exception as e:
        logger.error(f"测试失败: {e}")

    finally:
        table.close()


def test_batch_insert():
    """测试批量插入"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 6: 批量插入大数据")
    logger.info("=" * 60)

    table = MinBarTable(table_name='test_min_bar_batch')

    try:
        # 创建表
        table.drop(if_exists=True)
        table.create(if_not_exists=True)

        # 生成大量测试数据
        n_records = 1000
        logger.info(f"生成 {n_records} 条测试数据")

        dates = [20250101] * n_records
        times = list(range(93000000, 93000000 + n_records * 1000, 1000))
        symbols = ['SH.600000.TEST'] * n_records

        large_data = pd.DataFrame({
            'date': dates,
            'time': times,
            'pre_close': [100000] * n_records,
            'open': [101000] * n_records,
            'high': [102000] * n_records,
            'low': [100500] * n_records,
            'close': [101500] * n_records,
            'volume': [10000] * n_records,
            'turnover': [1015000000] * n_records,
            'open_interest': [0] * n_records,
            'pre_settle_price': [0] * n_records,
            'settle_price': [0] * n_records,
            'symbol': symbols,
            'local_time': pd.date_range('2025-01-01 09:30:00', periods=n_records, freq='1s')
        })

        # 批量插入
        logger.info("开始批量插入...")
        if table.insert(large_data, batch_size=200):
            logger.info(f"成功插入 {n_records} 条记录")

        # 验证
        count = table.count()
        logger.info(f"表中共有 {count} 条记录")

        # 清理
        table.drop(if_exists=True)

    except Exception as e:
        logger.error(f"测试失败: {e}")

    finally:
        table.close()


def run_all_tests():
    """运行所有测试"""
    logger.info("开始测试 ClickHouseTable 基类功能\n")

    try:
        test_default_config()
        test_custom_config()
        test_configure_runtime()
        test_context_manager()
        test_table_operations()
        test_batch_insert()

        logger.info("\n" + "=" * 60)
        logger.info("所有测试完成！")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")


if __name__ == '__main__':
    run_all_tests()
