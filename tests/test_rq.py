"""
RiceQuant 集成测试
包含配置校验、初始化校验及基础数据查询
"""

from __future__ import annotations

import logging
from typing import cast

import pandas as pd
import rqdatac as rq

from getrich.apps.data.api import RQDataAPI
from getrich.apps.data.etl.fromrq import export_all_instruments, init_rq
from getrich.config import settings, setup_logging

logger = logging.getLogger(__name__)


def test_config() -> None:
    """验证从 settings 正确读取 RiceQuant 配置"""
    logger.info("=" * 60)
    logger.info("Testing RiceQuant Configuration...")

    # 打印当前配置（隐藏敏感信息）
    logger.info("Enabled: %s", settings.ricequant.enabled)
    if settings.ricequant.api_key:
        prefix = settings.ricequant.api_key[:15]
        suffix = settings.ricequant.api_key[-15:]
        logger.info(
            "API Key: %s...%s (Length: %d)", prefix, suffix, len(settings.ricequant.api_key)
        )

    # 验证逻辑
    assert settings.ricequant.enabled is True, "RiceQuant should be enabled"
    assert settings.ricequant.api_key.startswith("tcp://license:"), (
        "API Key should start with tcp://license:"
    )
    assert settings.ricequant.api_key.endswith("@rqdatad-pro.ricequant.com:16011"), (
        "API Key should end with server address"
    )
    assert len(settings.ricequant.api_key) > 100, "API Key should be sufficiently long"

    logger.info("✓ RiceQuant configuration checks PASSED")


def test_init() -> None:
    """验证 RiceQuant 成功连接"""
    logger.info("=" * 60)
    logger.info("Testing RiceQuant Initialization...")
    try:
        init_rq()
        logger.info("✓ RiceQuant initialization PASSED")
    except Exception as e:
        logger.error("✗ RiceQuant initialization FAILED: %s", e)
        raise


def test_query() -> None:
    """验证 RiceQuant 数据查询功能"""
    logger.info("=" * 60)
    logger.info("Testing RiceQuant Data Query...")
    # 确保已初始化
    init_rq()

    # 测试查询停牌信息
    # 使用 test_rq.py 原有的测试用例
    symbol = "149566.XSHE"
    df = cast(pd.DataFrame, rq.is_suspended(symbol, start_date="20260110", end_date="20260120"))

    logger.info("Query result for %s:", symbol)
    print(df.head())

    assert isinstance(df, pd.DataFrame), "Result should be a pandas DataFrame"
    assert not df.empty, "Result should not be empty for this test range"

    logger.info("✓ RiceQuant query PASSED")


def test_export_instruments() -> None:
    """验证 RiceQuant 数据导出功能"""
    logger.info("=" * 60)
    logger.info("Testing RiceQuant Data Export...")
    # Initialize RiceQuant using new API
    api = RQDataAPI()
    api.login()

    # 示例 1: 只保存到数据库
    # export_all_instruments(save_to_db=True)

    # 示例 2: 只保存 parquet
    # export_all_instruments(output_dir=r"E:\data\ricequant", save_to_parquet=True, save_to_db=False)

    # 示例 3: 两者都保存
    export_all_instruments(
        output_dir=r"D:\data\ricequant", save_to_parquet=True, save_to_db=True, api=api
    )
    logger.info("✓ RiceQuant export PASSED")


if __name__ == "__main__":
    # 配置日志
    setup_logging(settings)

    try:
        # test_config()
        # test_init()
        # test_query()
        test_export_instruments()
        logger.info("=" * 60)
        logger.info("ALL RiceQuant integration tests PASSED")
    except Exception as e:
        logger.error("=" * 60)
        logger.error("Tests FAILED: %s", e)
        exit(1)
