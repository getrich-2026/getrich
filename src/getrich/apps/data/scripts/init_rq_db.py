from pathlib import Path

from lntools.utils import Logger

from getrich.libs.clickhouse.database import ClickHouseClient

log = Logger(module_name="InitRQDB")


def init_rq_db():
    """
    初始化数据库：执行 init_schema.sql 和 ricequant.sql。
    """
    client = ClickHouseClient()

    # 获取 schemas 目录的绝对路径
    current_dir = Path(__file__).parent
    schemas_dir = current_dir.parent / "schemas"

    if not schemas_dir.exists():
        log.error(f"Schemas directory not found: {schemas_dir}")
        return

    # 指定要执行的文件
    # 注意: init_schema.sql 中的 ref.instruments 视图依赖于 ricequant.sql 中定义的 rq.*_local 表
    target_files = ["ricequant.sql", "init_schema.sql"]

    for file_name in target_files:
        sql_file = schemas_dir / file_name
        if not sql_file.exists():
            log.error(f"SQL file not found: {sql_file}")
            continue

        log.info(f"Executing schema file: {file_name}")
        success = client.execute_sql_file(str(sql_file))
        if success:
            log.info(f"Successfully executed: {file_name}")
        else:
            log.error(f"Failed to execute: {file_name}")
            # 如果 init_schema.sql 失败，通常后面也会失败
            if file_name == "init_schema.sql":
                break


if __name__ == "__main__":
    init_rq_db()
