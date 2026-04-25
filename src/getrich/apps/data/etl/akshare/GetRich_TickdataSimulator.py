# pyright: reportMissingParameterType=false
# pyright: reportMissingTypeArgument=false
# A股的tick数据模拟器
import asyncio
import inspect
import logging
import random
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

import pandas as pd


class AShareTickDataSimulator:
    """
    A股实时tick数据模拟器
    """

    def __init__(self, stock_count: int = 5000) -> None:
        self.stock_count: int = stock_count

        self.is_running: bool = False
        self.callbacks: list[
            Callable[[dict[str, Any]], Any] | Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]
        ] = []

        # 交易时间配置
        self.trading_hours = {
            "morning_open": "09:30:00",
            "morning_close": "11:30:00",
            "afternoon_open": "13:00:00",
            "afternoon_close": "15:00:00",
        }

        # 初始化日志
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.stocks: list[dict[str, Any]] = self._generate_stocks()  # 生成股票池

    def _generate_stocks(self) -> list[dict[str, Any]]:
        """
        生成股票池, 优先从AKShare获取真实数据
        """
        stocks = []

        try:
            # 尝试从AKShare获取实时数据
            import akshare as ak

            self.logger.info("尝试从AKShare获取实时股票数据...")
            # 获取A股实时行情数据
            df: pd.DataFrame = ak.stock_zh_a_spot_em()
            if not df.empty:
                self.logger.info("成功获取 %d 只股票数据", len(df))
                # 过滤有效数据（昨收大于0）
                df = df[df["昨收"] > 0]
                # 限制股票数量不超过设定值
                if len(df) > self.stock_count:
                    df = df.head(self.stock_count)
                for _, row in df.iterrows():
                    stock_code = row["代码"]
                    prev_close = row["昨收"]

                    # 确定交易所后缀
                    if stock_code.startswith(("60", "68", "69")):
                        code_suffix = ".SH"
                    elif stock_code.startswith(("00", "30", "39")):
                        code_suffix = ".SZ"
                    else:
                        continue
                    full_code = stock_code + code_suffix

                    # 根据股票类型设置不同的涨跌停幅度
                    if stock_code.startswith(("68", "30")):
                        volatility = 0.2
                    elif stock_code.startswith("ST"):
                        volatility = 0.05
                    else:
                        volatility = 0.1
                    stocks.append(
                        {
                            "code": full_code,
                            "base_price": prev_close,
                            "prev_close": prev_close,
                            "volatility": volatility,
                            "day_high": prev_close * (1 + volatility),
                            "day_low": prev_close * (1 - volatility),
                        }
                    )
                self.logger.info("成功生成 %d 只股票数据", len(stocks))
                return stocks
        except ImportError:
            self.logger.warning("未安装AKShare，将使用随机数据")
        except Exception as e:
            self.logger.warning("从AKShare获取实时数据失败: %s", e)
        # 如果从AKShare获取数据失败，使用随机数据
        self.logger.info("使用随机数据生成股票池...")
        # 生成上证股票（60开头）
        sh_count = min(2500, self.stock_count // 2)  # 上证股票数量
        for i in range(1, sh_count + 1):
            stock_code = f"60{str(i).zfill(4)}.SH"
            base_price = random.uniform(5, 100)
            prev_close = round(base_price, 2)
            stocks.append(
                {
                    "code": stock_code,
                    "base_price": base_price,
                    "prev_close": prev_close,
                    "volatility": 0.1,
                    "day_high": prev_close * 1.1,
                    "day_low": prev_close * 0.9,
                }
            )
        # 生成深证股票（000001-399999）
        sz_count = self.stock_count - sh_count
        for i in range(1, sz_count + 1):
            stock_code = f"00{str(i).zfill(4)}.SZ"
            base_price = random.uniform(5, 100)
            prev_close = round(base_price, 2)
            stocks.append(
                {
                    "code": stock_code,
                    "base_price": base_price,
                    "prev_close": prev_close,
                    "volatility": 0.1,
                    "day_high": prev_close * 1.1,
                    "day_low": prev_close * 0.9,
                }
            )
        # 添加一些创业板和科创板的模拟数据
        gem_count = min(500, self.stock_count // 10)
        for i in range(1, gem_count + 1):
            stock_code = f"30{str(i).zfill(4)}.SZ"  # 创业板
            base_price = random.uniform(5, 100)
            prev_close = round(base_price, 2)

            stocks.append(
                {
                    "code": stock_code,
                    "base_price": base_price,
                    "prev_close": prev_close,
                    "volatility": 0.20,  # 创业板涨跌停20%
                    "day_high": prev_close * 1.20,  # 涨停价
                    "day_low": prev_close * 0.80,  # 跌停价
                }
            )

        star_count = min(300, self.stock_count // 15)
        for i in range(1, star_count + 1):
            stock_code = f"68{str(i).zfill(4)}.SH"  # 科创板
            base_price = random.uniform(5, 100)
            prev_close = round(base_price, 2)

            stocks.append(
                {
                    "code": stock_code,
                    "base_price": base_price,
                    "prev_close": prev_close,
                    "volatility": 0.20,  # 科创板涨跌停20%
                    "day_high": prev_close * 1.20,  # 涨停价
                    "day_low": prev_close * 0.80,  # 跌停价
                }
            )

        return stocks

    def _is_trading_time(self) -> bool:
        """
        判断当前是否为交易时间
        """
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_weekday = now.weekday()

        # 周末不交易
        if current_weekday >= 7:
            return False

        # 检查是否在交易时段内
        morning_open = self.trading_hours["morning_open"]
        morning_close = self.trading_hours["morning_close"]
        afternoon_open = self.trading_hours["afternoon_open"]
        afternoon_close = self.trading_hours["afternoon_close"]

        return (morning_open <= current_time <= morning_close) or (
            afternoon_open <= current_time <= afternoon_close
        )

    def _generate_tick_data(self, stock_info: dict[str, Any]) -> dict[str, Any]:
        """生成单只股票的tick数据"""
        base_price = stock_info["base_price"]
        volatility = stock_info["volatility"]
        prev_close = stock_info["prev_close"]
        day_high_limit = stock_info["day_high"]  # 涨停价
        day_low_limit = stock_info["day_low"]  # 跌停价

        # 生成价格波动
        price_change = random.uniform(-volatility, volatility)  # 价格波动范围
        current_price = base_price * (1 + price_change)
        current_price = max(day_low_limit, min(day_high_limit, current_price))
        current_price = max(0.01, current_price)  # 价格不能为负

        # 更新基础价格（模拟价格趋势）
        stock_info["base_price"] = current_price

        # 生成买卖五档价格
        # spread = 0.01  # 最小价格变动单位
        bid_prices = []
        ask_prices = []

        for i in range(1, 6):
            bid_price = current_price * (1 - i * 0.001)  # 买价递减
            ask_price = current_price * (1 + i * 0.001)  # 卖价递增
            # 确保买卖价在涨跌停范围内
            bid_price = max(day_low_limit, bid_price)
            ask_price = min(day_high_limit, ask_price)

            bid_prices.append(round(bid_price, 2))
            ask_prices.append(round(ask_price, 2))

        # 生成买卖五档数量
        bid_sizes = [random.randint(100, 100000) for _ in range(5)]
        ask_sizes = [random.randint(100, 100000) for _ in range(5)]
        # 更新当日最高最低价
        if "current_day_high" not in stock_info:
            stock_info["current_day_high"] = current_price
            stock_info["current_day_low"] = current_price
        stock_info["current_day_high"] = max(stock_info["current_day_high"], current_price)
        stock_info["current_day_low"] = min(stock_info["current_day_low"], current_price)

        tick_data = {
            "code": stock_info["code"],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "prev_close": prev_close,
            "last": round(current_price, 2),
            "open": round(prev_close * random.uniform(0.95, 1.05), 2),
            "high": round(stock_info["current_day_high"], 2),
            "low": round(stock_info["current_day_low"], 2),
            "close": "",  # 收盘时更新
            "bid1": bid_prices[0],
            "bid2": bid_prices[1],
            "bid3": bid_prices[2],
            "bid4": bid_prices[3],
            "bid5": bid_prices[4],
            "bid_size1": bid_sizes[0],
            "bid_size2": bid_sizes[1],
            "bid_size3": bid_sizes[2],
            "bid_size4": bid_sizes[3],
            "bid_size5": bid_sizes[4],
            "ask1": ask_prices[0],
            "ask2": ask_prices[1],
            "ask3": ask_prices[2],
            "ask4": ask_prices[3],
            "ask5": ask_prices[4],
            "ask_size1": ask_sizes[0],
            "ask_size2": ask_sizes[1],
            "ask_size3": ask_sizes[2],
            "ask_size4": ask_sizes[3],
            "ask_size5": ask_sizes[4],
            "volume": random.randint(1000, 1000000),
            "amount": round(current_price * random.randint(1000, 1000000), 2),
        }

        return tick_data

    def add_callback(
        self,
        callback: Callable[[dict[str, Any]], Any]
        | Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> None:
        """
        添加回调函数
        """
        self.callbacks.append(callback)

    async def _push_tick_data(self, tick_data: dict[str, Any]) -> None:
        """推送tick数据到所有回调函数"""
        for callback in self.callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(tick_data)
                else:
                    callback(tick_data)
            except Exception as e:
                self.logger.error("Callback error: %s", e)

    async def _simulate_stock_group(
        self, stock_group: list[dict[str, Any]], interval: float
    ) -> None:
        """模拟一组股票的tick数据流"""
        while self.is_running:
            if not self._is_trading_time():
                await asyncio.sleep(60)  # 非交易时间每分钟检查一次
                continue

            tasks = []
            for stock_info in stock_group:
                tick_data = self._generate_tick_data(stock_info)
                tasks.append(self._push_tick_data(tick_data))

            # 并发推送所有股票的tick数据
            await asyncio.gather(*tasks, return_exceptions=True)

            # 控制推送频率
            await asyncio.sleep(interval)

    async def start(self, ticks_per_second: int = 10) -> None:
        """
        启动模拟器
        ticks_per_second: 每秒推送的tick次数
        """
        if self.is_running:
            self.logger.warning("Simulator is already running")
            return

        self.is_running = True
        self.logger.info("Starting A-share tick data simulator...")

        # 计算每批次的间隔时间
        interval = 1.0 / ticks_per_second

        # 将股票分成多个组进行并发处理，提高性能
        group_size = max(1, len(self.stocks) // 50)  # 分成50组
        stock_groups = [
            self.stocks[i : i + group_size] for i in range(0, len(self.stocks), group_size)
        ]

        # 创建并发的模拟任务
        tasks = []
        for group in stock_groups:
            task = asyncio.create_task(self._simulate_stock_group(group, interval))
            tasks.append(task)

        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            self.logger.error("Simulator error: %s", e)
        finally:
            self.is_running = False

    def stop(self) -> None:
        """停止模拟器"""
        self.is_running = False
        self.logger.info("Stopping simulator...")


# 使用示例
# 使用示例
async def example_callback(tick_data: dict[str, Any]) -> None:
    """示例回调函数 - 处理接收到的tick数据"""
    # 这里可以替换为实际的数据处理逻辑，比如:
    # - 存储到数据库
    # - 发送到消息队列
    # - 实时分析计算
    # print(f"Received tick data for {tick_data['code']}: {tick_data['last']}")
    print(tick_data)


async def main() -> None:
    # 创建模拟器实例
    simulator = AShareTickDataSimulator(stock_count=5000)  # 测试时使用100只股票

    # 添加数据回调
    simulator.add_callback(example_callback)

    # 启动模拟器（在后台运行）
    simulator_task = asyncio.create_task(simulator.start(ticks_per_second=5))

    try:
        # 让模拟器运行一段时间
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        print("Stopping simulator...")
    finally:
        simulator.stop()
        await simulator_task


if __name__ == "__main__":
    asyncio.run(main())


"""
使用方法
# 基本使用
simulator = AShareTickDataSimulator(stock_count=5000)

# 添加自定义数据处理函数
def my_data_handler(tick_data):
    # 你的数据处理逻辑
    pass

simulator.add_callback(my_data_handler)

# 启动模拟器
await simulator.start(ticks_per_second=10)  # 每秒10次推送
"""
