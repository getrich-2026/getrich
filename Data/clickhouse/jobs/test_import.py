"""
测试分钟线数据导入功能
"""
from datetime import datetime
from Data.clickhouse.jobs.daily_import import MinBarImportJob
from lntools import Logger

logger = Logger(module_name="test_import")

# 配置
HDB_PATH = r"E:\BaiduNetdiskDownload\data\bar\bar\min_bar"

CLICKHOUSE_CONF = {
    'host': 'localhost',
    'port': 8123,
    'database': 'default',
    'user': 'default',
    'password': 'getrich',
    'table_name': 'min_bar'
}


def test_get_latest_date():
    """测试获取数据库最新日期"""
    logger.info("=" * 60)
    logger.info("测试: 获取数据库最新日期")
    logger.info("=" * 60)

    importer = MinBarImportJob(
        hdb_base_path=HDB_PATH,
        clickhouse_config=CLICKHOUSE_CONF,
        max_workers=2
    )

    latest_date = importer.get_latest_date_in_db()

    if latest_date:
        logger.info(f"数据库最新日期: {latest_date.strftime('%Y-%m-%d')}")
    else:
        logger.info("数据库为空")

    importer.close()


def test_import_single_day():
    """测试导入单个日期的数据"""
    logger.info("=" * 60)
    logger.info("测试: 导入单个日期数据")
    logger.info("=" * 60)

    importer = MinBarImportJob(
        hdb_base_path=HDB_PATH,
        clickhouse_config=CLICKHOUSE_CONF,
        max_workers=2
    )

    # 导入 2025年1月1日的数据
    target_date = datetime(2025, 1, 1)
    logger.info(f"导入日期: {target_date.strftime('%Y-%m-%d')}")

    importer.run_incremental_import(target_date=target_date)
    importer.close()


def test_import_year():
    """测试导入一年的数据"""
    logger.info("=" * 60)
    logger.info("测试: 导入一年数据")
    logger.info("=" * 60)

    importer = MinBarImportJob(
        hdb_base_path=HDB_PATH,
        clickhouse_config=CLICKHOUSE_CONF,
        max_workers=4
    )

    # 导入 2005 年的数据
    importer.run_full_import(
        start_year=2005,
        end_year=2005,
        symbols=None,
        skip_existing=True
    )

    importer.close()


def test_incremental_import():
    """测试增量导入"""
    logger.info("=" * 60)
    logger.info("测试: 增量导入")
    logger.info("=" * 60)

    importer = MinBarImportJob(
        hdb_base_path=HDB_PATH,
        clickhouse_config=CLICKHOUSE_CONF,
        max_workers=4
    )

    # 自动导入最新日期之后的数据
    importer.run_incremental_import()
    importer.close()


if __name__ == '__main__':
    # 选择要运行的测试
    import sys

    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if test_name == 'latest':
            test_get_latest_date()
        elif test_name == 'single':
            test_import_single_day()
        elif test_name == 'year':
            test_import_year()
        elif test_name == 'incremental':
            test_incremental_import()
        else:
            logger.error(f"未知的测试: {test_name}")
            logger.info("可用测试: latest, single, year, incremental")
    else:
        logger.info("使用方法:")
        logger.info("  python test_import.py latest       - 测试获取最新日期")
        logger.info("  python test_import.py single       - 测试导入单个日期")
        logger.info("  python test_import.py year         - 测试导入一年数据")
        logger.info("  python test_import.py incremental  - 测试增量导入")
