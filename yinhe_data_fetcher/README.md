# yinhe_data_fetcher

基于 **AmazingData** (中国银河证券量化 SDK) 的本地化行情数据抓取系统。
落盘格式统一为 **Parquet**, 所有数据写入 `./data/` 目录。

---

## 特性

- **职责分离**:
  - `config.yaml` 只管 *运行时开关* (账号 / 存储 / 限流 / 启用哪些 fetcher / 全局起始日)
  - 业务参数 (security_types, period, 起始日期, 切块大小) 硬编码在对应 fetcher 类里
- **两大类 Fetcher 父类**:
  - `FullReplaceFetcher` - 每次跑都整块覆盖 (交易日历 / 历史代码表 / 复权因子)
  - `IncrementalFetcher` - 读取本地最后一条时间, 只拉后续数据并追加 (K线)
- **基类 / 实现解耦**: `src/fetchers/base/` 放抽象基类, `src/fetchers/impl/` 放具体类, 一个文件一个 class
- **注册式扩展**: 新增接口只需继承父类 + 追加到 `src/registry.py`
- **限流友好**: code × date 双维度切块 + 请求间 sleep + 指数退避重试
- **两种运行模式**: `init` (首次建库) / `update` (每日增量, 建议 cron 触发)
- **全局起始日期裁剪**: `config.yaml` 的 `start_date` 一键抬高所有 fetcher 的下限 (取 `max(类默认, config 值)`)

---

## 平台要求 (重要)

AmazingData SDK 自带的 `tgw` 运行时 **只提供 Linux x86_64 和 Windows x86_64 的二进制**
(检查 `site-packages/tgw/` 可见 `linux_pyXX_x64_package/` 和 `win_pyXX_x64_package/`), 并且官方标称 Python 3.8。

| 平台                   | 能否运行                                          |
| ---------------------- | ------------------------------------------------- |
| Linux x86_64           | ✓ 推荐 (Python 3.8 最佳, 3.10/3.11/3.12/3.13 也有预编译包) |
| Windows x86_64         | ✓                                                 |
| **macOS (Intel/ARM)**  | **✗ 官方不支持, `import tgw` 就会失败**         |

> macOS arm64 (Apple Silicon) 的用户请使用 Docker / 远端 Linux 服务器运行。本项目代码本身纯 Python,
> 在任何平台上 `python main.py list` (不触发登录) 都可以跑。

---

## 目录结构

```
yinhe_data_fetcher/
├── main.py                 # 主程序入口 (CLI)
├── config.yaml             # 运行时开关 (账号/存储/限流/启用项/start_date)
├── pyproject.toml          # uv 环境和依赖配置
├── .python-version         # Python 版本固定 (3.13)
├── .venv/                  # uv 虚拟环境 (uv sync 生成)
├── data/                   # Parquet 输出 (自动创建)
├── logs/                   # 运行日志
└── src/
    ├── config.py           # 配置加载
    ├── logger.py
    ├── client.py           # AmazingData 登录 + 客户端封装
    ├── utils.py            # 日期 / 切块 / Parquet IO / 重试
    ├── runner.py           # 编排器
    ├── registry.py         # NAME -> Python class
    └── fetchers/
        ├── base/                      # >>> 抽象基类 (不包含任何业务参数) <<<
        │   ├── base.py                    # BaseFetcher (ABC)
        │   ├── full_replace.py            # FullReplaceFetcher
        │   ├── incremental.py             # IncrementalFetcher
        │   └── kline.py                   # KlineFetcher (K线共享逻辑, 仍是抽象类)
        └── impl/                      # >>> 具体实现 (一个文件一个 class) <<<
            ├── calendar.py                # 交易日历
            ├── hist_code_list.py          # 历史代码表
            ├── backward_factor.py         # 复权因子
            ├── kline_day.py               # 日线
            ├── kline_min5.py              # 5 分钟线
            └── kline_min1.py              # 1 分钟线
```

---

## 环境准备

### 1. 使用 uv 创建 Python 3.13 环境

本项目使用 `uv` 管理环境和依赖，Python 版本固定为 **3.13**（由 `.python-version` 控制）。

```bash
cd /path/to/yinhe_data_fetcher

# 首次同步环境
uv sync
```

后续如需更新依赖:

```bash
uv sync --refresh
```

### 2. 安装 AmazingData SDK 和 tgw

`tgw` 和 `AmazingData` wheel 不在标准 PyPI，需手动安装：

```bash
# tgw 可以从 PyPI 获取（如果网络配置允许）
uv run pip install tgw

# AmazingData wheel 由营业部提供，需放在项目根目录，然后：
uv run pip install AmazingData-0.0.6-py3-none-any.whl
```

如果 `tgw` 安装失败，可能需要从营业部获取本地 wheel 文件，改为：

```bash
uv run pip install /path/to/tgw-*.whl
```

> **Python 版本说明**: yinhe_data_fetcher 使用 Python 3.13。
> 官方标称 3.8 最佳，但 `tgw` 预编译包支持 Python 3.8 ~ 3.13 在 Linux x86_64 和 Windows x86_64 上可用。

### 3. 账号

`config.yaml` 里已填入:
- 账号: `228200018953`
- 初始密码: `228200018953@2026`
- 服务器 IP(电信): `101.230.159.234`
- 服务器 IP(联通): `140.206.44.234`
- 端口: `8600`

---

## 使用方法

### 列出当前启用的 fetcher

```bash
uv run python main.py list
```

输出示例:
```
name               type           enabled  class
------------------------------------------------------------------------
calendar           full_replace   True     CalendarFetcher
hist_code_list     full_replace   True     HistCodeListFetcher
backward_factor    full_replace   True     BackwardFactorFetcher
kline_day          incremental    True     KlineDayFetcher
kline_min5         incremental    False    KlineMin5Fetcher
kline_min1         incremental    False    KlineMin1Fetcher
```

### 全量初始化 (第一次建库)

```bash
python main.py init
```

默认依次执行: `calendar` -> `hist_code_list` -> `backward_factor` -> `kline_day`。

> 首次 init 耗时很长 (可能数小时), 建议在 tmux / screen 里跑。

### 每日增量更新

```bash
python main.py update
```

建议加到定时任务 (每日 18:00 收盘后):

```cron
0 18 * * 1-5 cd /path/to/yinhe_data_fetcher && uv run python main.py update >> logs/cron.log 2>&1
```

### 只跑指定 fetcher

```bash
python main.py update --only kline_day
python main.py init   --only calendar --only hist_code_list
```

### 指定其他配置文件

```bash
python main.py -c config.prod.yaml update
```

---

## config.yaml 字段速查

```yaml
amazing_data:                       # SDK 登录信息
  username / password / host / port

storage:
  data_dir: "./data"                # parquet 产物根目录
  wipe_on_init: false               # init 时是否清空 incremental fetcher 的旧数据

# 全局起始日期 (int8, 例 20260101)
# - 所有 fetcher 都只拉 >= start_date 的数据
# - 会覆盖 fetcher 类里的 INIT_START_DATE / START_DATE (取两者较大值)
# - 留空 (null) 则用类里的默认值
start_date: 20260101

logging:
  level: "INFO"
  file:  "./logs/yinhe_data_fetcher.log"

rate_limit:
  sleep_between_requests_sec: 1.5   # 每次请求后固定 sleep
  max_retries: 5                    # 失败重试次数
  retry_backoff_base_sec: 3.0       # 指数退避基数 base * 2^(attempt-1)
  sleep_between_fetchers_sec: 5     # 两个 fetcher 之间额外等待

fetchers:                           # 只有 enabled 开关, 没有业务参数
  calendar:          { enabled: true  }
  hist_code_list:    { enabled: true  }
  backward_factor:   { enabled: true  }
  kline_day:         { enabled: true  }
  kline_min5:        { enabled: false }
  kline_min1:        { enabled: false }
```

### 业务参数在哪里?

看 `src/fetchers/impl/*.py`。例如 1 分钟 K 线:

```python
# src/fetchers/impl/kline_min1.py
class KlineMin1Fetcher(KlineFetcher):
    NAME = "kline_min1"
    PERIOD = "min1"
    SECURITY_TYPES = ["EXTRA_STOCK_A_SH_SZ"]
    INIT_START_DATE = 20240101
    CODE_CHUNK_SIZE = 5
    DATE_CHUNK_DAYS = 5
```

当 `config.yaml` 里 `start_date: 20260101` 时, 该 fetcher 的有效起点是 `max(20240101, 20260101) = 20260101`。

---

## 数据落盘格式

| fetcher           | 位置                                                         | 说明                              |
| ----------------- | ------------------------------------------------------------ | --------------------------------- |
| `calendar`        | `data/calendar/calendar_<market>.parquet`                    | 交易日历 (int8 date index)        |
| `hist_code_list`  | `data/hist_code_list/hist_code_list_<type>.parquet`          | 每个 security_type 一个文件       |
| `backward_factor` | `data/backward_factor/backward_factor_<type>_chunkNNNN.parquet` | 按 code 切块, 矩阵形式            |
| `kline_day`       | `data/kline_day/<code>.parquet`                              | 每个股票一个文件, 可持续 append   |
| `kline_min5`      | `data/kline_min5/<code>.parquet`                             | 同上                              |
| `kline_min1`      | `data/kline_min1/<code>.parquet`                             | 同上                              |

增量写入使用 `utils.write_parquet(append=True)`, 会读旧文件按 index 去重后合并再整体覆写。

---

## 添加一个新的接口

1. 选一个父类:
   - 每次都整块重算 → `FullReplaceFetcher`
   - 有时间轴, 只拉增量 → `IncrementalFetcher`
   - 新增一种 K 线 period → `KlineFetcher`

2. 在 `src/fetchers/impl/` 下新建一个文件 (**一个 class 一个文件**), 用类常量声明业务参数:

   ```python
   # src/fetchers/impl/my_data.py
   from ..base import IncrementalFetcher

   class MyFetcher(IncrementalFetcher):
       NAME = "my_data"                          # data/ 子目录名 + config key
       SECURITY_TYPES = ["EXTRA_STOCK_A"]
       INIT_START_DATE = 20130101
       CODE_CHUNK_SIZE = 50
       DATE_CHUNK_DAYS = 60

       def _iter_update_keys(self):              # 增量 fetcher 必备
           ...
       def _last_local_date(self, key):          # 增量 fetcher 必备
           ...
       def _fetch_one(self, task):               # 调用 AmazingData API
           ...
       def _save_chunk(self, task, result):      # 落盘 parquet
           ...
   ```

3. 在 `src/fetchers/impl/__init__.py` 和 `src/registry.py` 的 `REGISTRY_CLASSES` 列表里 import + 追加这个类。

4. 在 `config.yaml` 的 `fetchers:` 节点加一行 `my_data: { enabled: true }`。

全过程不需要碰 `src/fetchers/base/` 下的任何文件。

---

## 限流策略

运行时参数在 `config.yaml > rate_limit`:

- `sleep_between_requests_sec` - 每次请求后固定 sleep (默认 1.5s)
- `max_retries` + `retry_backoff_base_sec` - 失败指数退避重试
- `sleep_between_fetchers_sec` - 不同 fetcher 切换时额外等待

切块粒度是业务参数, 写在各 fetcher 类的 `CODE_CHUNK_SIZE` / `DATE_CHUNK_DAYS` 常量上
(例如 `KlineMin1Fetcher` 默认 `CODE_CHUNK_SIZE=5, DATE_CHUNK_DAYS=5`)。

---

## 已知问题

- `tgw/__init__.py` 用 `'win' in sys.platform` 判断平台, 而 macOS 的 `sys.platform == 'darwin'` 恰好包含子串 `win`,
  导致它错误地尝试加载 Windows `.pyd`, 报 `ModuleNotFoundError: No module named '_tgw'`。
  这是 SDK 本身的 bug, **只能换 Linux/Windows 机器运行**。
