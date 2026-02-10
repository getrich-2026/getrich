import contextlib
import gc
import shutil
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from lntools.utils import Logger

from getrich.libs.clickhouse.database import ClickHouseClient

log = Logger(module_name="WindImport")


def _import_single_file(client: ClickHouseClient, file_path: Path, db_name: str) -> None:
    """
    导入单个文件的核心逻辑。
    采用 PyArrow 流式读取 + 分块插入策略。
    彻底解决大文件导致的内存溢出 (OOM) 和 OSError 10055 问题。
    """
    table_name = file_path.stem
    full_table_name = f"{db_name}.{table_name}"

    start_time = time.perf_counter()

    # 使用 PyArrow 打开文件，而不是一次性读取
    try:
        parquet_file = pq.ParquetFile(file_path)
    except Exception as e:
        log.error(f"Failed to open parquet file {file_path}: {e}")
        raise e

    try:
        # 获取元数据
        total_rows = parquet_file.metadata.num_rows
        if total_rows == 0:
            log.warning(f"File {file_path.name} is empty, skipping")
            return

        # 设置分块大小：50万行
        BATCH_SIZE = 500_000
        total_batches = (total_rows + BATCH_SIZE - 1) // BATCH_SIZE

        log.info(
            f"File {file_path.name} has {total_rows} rows. Starting streaming import (Batch size: {BATCH_SIZE})..."
        )

        # 流式读取: 每次只读入 BATCH_SIZE 行到内存
        # iter_batches 返回的是 RecordBatch，内存占用极小
        for i, batch in enumerate(parquet_file.iter_batches(batch_size=BATCH_SIZE)):
            # 将 RecordBatch 转换为 Table 以供 ClickHouse 客户端使用
            arrow_table = pa.Table.from_batches([batch])

            # 注意: 流式读取无法进行全局排序 (df.sort("TRADE_DT"))
            # 但 ClickHouse MergeTree 引擎会自动在后台合并数据，因此乱序写入是可以接受的。

            # 块级重试机制
            chunk_retries = 3
            for attempt in range(chunk_retries):
                try:
                    client.client.insert_arrow(  # type: ignore
                        full_table_name,
                        arrow_table,
                        settings={"max_partitions_per_insert_block": 10000},
                    )
                    break  # 成功则跳出重试
                except Exception as e:
                    if attempt < chunk_retries - 1:
                        wait = 5 * (attempt + 1)
                        log.warning(
                            f"  Batch {i + 1}/{total_batches} failed (Attempt {attempt + 1}): {e}. Retrying in {wait}s"
                        )
                        time.sleep(wait)
                        # 尝试重置连接
                        with contextlib.suppress(Exception):
                            client.connect()
                    else:
                        # 重试耗尽，抛出异常
                        raise e

            # 显式清理当前块的内存
            del arrow_table
            del batch
            gc.collect()

            if (i + 1) % 5 == 0 or (i + 1) == total_batches:
                log.info(f"  - Imported batch {i + 1}/{total_batches}")

        elapsed = time.perf_counter() - start_time
        log.info(
            f"Successfully imported {total_rows} rows into {full_table_name} (Time: {elapsed:.2f}s)"
        )
    finally:
        # 确保关闭文件句柄
        # 虽然 ParquetFile 通常会自动关闭，但显式关闭更安全
        # 注意：PyArrow 的 ParquetFile 对象可能没有 close 方法，它依赖于内部的 reader
        # 但我们可以通过删除对象来触发析构
        del parquet_file
        gc.collect()


def import_wind_data_from_parquet(data_dir: str = r"D:\data\wind", db_name: str = "wind") -> None:
    """
    读取指定目录下的所有 parquet 文件并导入到 ClickHouse 对应的表中。
    包含重试机制和错误记录。
    """
    path = Path(data_dir)
    if not path.exists():
        log.error(f"Directory not found: {data_dir}")
        return

    # 准备移动的目标目录
    processed_dir = Path(r"D:\data\readed\wind")
    processed_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有 parquet 文件
    files = list(path.glob("*.parquet"))
    if not files:
        log.warning(f"No .parquet files found in {data_dir}")
        return

    log.info(f"Found {len(files)} parquet files in {data_dir}")

    # 初始化数据库连接
    client = ClickHouseClient()
    if not client.ensure_connection():
        log.error("Could not connect to ClickHouse")
        return

    failed_files: list[Path] = []

    for i, file_path in enumerate(files):
        log.info(f"[{i + 1}/{len(files)}] Processing {file_path.name}")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                _import_single_file(client, file_path, db_name)

                # 成功后移动文件
                try:
                    shutil.move(str(file_path), str(processed_dir / file_path.name))
                    log.info(f"Moved {file_path.name} to {processed_dir}")
                except Exception as move_e:
                    log.error(f"Failed to move file {file_path.name}: {move_e}")

                # 成功后跳出重试循环
                break
            except Exception as e:
                log.warning(
                    f"Error importing {file_path.name} (Attempt {attempt + 1}/{max_retries}): {e}"
                )

                if attempt < max_retries - 1:
                    # 等待一下
                    sleep_time = 10 * (attempt + 1)
                    log.info(f"Waiting {sleep_time}s before retrying...")
                    time.sleep(sleep_time)

                    # 尝试重连数据库，以防是连接问题
                    with contextlib.suppress(Exception):
                        client.connect()
                else:
                    # 最后一次尝试也失败
                    log.error(f"Failed to import {file_path.name} after {max_retries} attempts.")
                    failed_files.append(file_path)

        # 每次处理完一个文件（无论成功失败），稍微休息一下，避免系统过载
        time.sleep(0.5)

    # 最后输出
    if failed_files:
        log.error(f"\n=== Summary: {len(failed_files)} files failed to import ===")
        for f in failed_files:
            log.error(f"  - {f.name}")
    else:
        log.info("\n=== All files imported successfully! ===")


if __name__ == "__main__":
    # Minimal Reproducible Example / Usage
    import_wind_data_from_parquet()
