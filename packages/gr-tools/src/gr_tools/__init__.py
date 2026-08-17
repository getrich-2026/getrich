"""GetRich 通用工具包。

依赖图最底层的叶子：**不依赖任何一方包**（``gr_data`` / ``gr_api`` 等一律
不许出现在这里），其它包可以自由依赖它。

三个模块：

* :mod:`gr_tools.fs` —— 路径与文件操作
* :mod:`gr_tools.io` —— 按后缀分发的表格读取（csv / parquet / excel / feather）
* :mod:`gr_tools.human` —— 日志与 CLI 输出的人性化格式化
"""

from gr_tools.fs import (
    file_time,
    get_dirs,
    get_files,
    handle_path,
    is_dir,
    is_file,
    list_paths,
    make_dirs,
    move,
    remove,
    rename,
)
from gr_tools.human import bytes_size, datetime_str, lists, ranges, sec2str, track, unit
from gr_tools.io import (
    cast_all_utf8,
    load_data,
    read_directory,
    read_file,
    read_frame,
)


__all__ = [
    "bytes_size",
    "cast_all_utf8",
    "datetime_str",
    "file_time",
    "get_dirs",
    "get_files",
    "handle_path",
    "is_dir",
    "is_file",
    "list_paths",
    "lists",
    "load_data",
    "make_dirs",
    "move",
    "ranges",
    "read_directory",
    "read_file",
    "read_frame",
    "remove",
    "rename",
    "sec2str",
    "track",
    "unit",
]
