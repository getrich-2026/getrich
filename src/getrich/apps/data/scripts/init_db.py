from pathlib import Path

from lntools import Logger

from getrich.libs.db.database import ClickHouseClient

log = Logger(module_name="InitDB")


def init_db():
    """
    初始化数据库：读取 schemas 目录下的所有 .sql 文件并执行。
    """
    client = ClickHouseClient()

    # 获取 schemas 目录的绝对路径
    # 假设当前脚本在 src/getrich/apps/data/scripts/init_db.py
    # schemas 在 src/getrich/apps/data/schemas/
    current_dir = Path(__file__).parent
    schemas_dir = current_dir.parent / "schemas"

    if not schemas_dir.exists():
        log.error(f"Schemas directory not found: {schemas_dir}")
        return

    log.info(f"Looking for SQL files in: {schemas_dir}")

    # 获取所有 .sql 文件并排序（确保执行顺序）
    sql_files = sorted(schemas_dir.glob("*.sql"))

    if not sql_files:
        log.warning("No .sql files found in schemas directory.")
        return

    for sql_file in sql_files:
        log.info(f"Executing schema file: {sql_file.name}")
        success = client.execute_sql_file(str(sql_file))
        if success:
            log.info(f"Successfully executed: {sql_file.name}")
        else:
            log.error(f"Failed to execute: {sql_file.name}")
            # 根据需求决定是否中断，这里选择中断以避免后续依赖错误
            break


if __name__ == "__main__":
    init_db()
