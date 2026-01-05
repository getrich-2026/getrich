# TODO
# 1. 从.env 文件中读取数据库配置
# 2. 修改ClickhouseClient类的初始化方法，使用读取到的配置参数进行连接
# 3. 确保日志记录功能正常工作
# 4. 修改_init__.py 文件，确保配置模块正确导入和使用
from .settings import get_clickhouse_config

__all__ = ["get_clickhouse_config"]
