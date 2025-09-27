# A股的tick数据模拟器，方便开发测试使用
import asyncio
import json
import time
import random
from datetime  import datetime, timedelta
from typing import List, Dict, Optional
import logging

class AShareTickDataSimulator:
    """
    A股实时tick数据模拟器
    """
    def __init__(self, stock_count: int = 5000):
        self.stock_count = stock_count
        self.stocks = self._generate_stocks() #  生成股票池
        self.is_running = False
        self.callbacks = []

        # 交易时间配置
        self.trading_hours = {
            'morning_open': '09:30:00',
            'morning_close': '11:30:00',
            'afternoon_open': '13:00:00',
            'afternoon_close': '23:00:00'
        }

        # 初始化日志
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _generate_stocks(self) -> List[Dict]:
        """
        生成股票池
        """
        stocks = []
        # 生成上证股票（60开头）
        sh_count = min(2500, self.stock_count//2)  # 上证股票数量
        for i  in range(1, sh_count+1):
            stock_code = f"60{str(i).zfill(4)}.SH"
            base_price = random.uniform(5, 100)
            stocks.append({
                'code': stock_code,
                'base_price': base_price,
                'prev_close': round(base_price, 2),
                'volatility': random.uniform(0.01, 0.05)  # 波动率
            })
        # 生成深证股票（000001-399999）
        sz_count = self.stock_count - sh_count
        for i in range(1, sz_count + 1):
            stock_code = f"00{str(i).zfill(4)}.SZ"
            base_price = random.uniform(5, 100)
            stocks.append({
                'code': stock_code,
                'base_price': base_price,
                'prev_close': round(base_price, 2),
                'volatility': random.uniform(0.01, 0.05)
            })

        return stocks

    def _is_trading_time(self) -> bool:
        """
        判断当前是否为交易时间
        """
        now = datetime.now()
        current_time = now.strftime('%H:%M:%S')
        current_weekday = now.weekday()

        # 周末不交易
        if current_weekday >= 5:
            return False

        # 检查是否在交易时段内
        morning_open = self.trading_hours['morning_open']
        morning_close = self.trading_hours['morning_close']
        afternoon_open = self.trading_hours['afternoon_open']
        afternoon_close = self.trading_hours['afternoon_close']

        return (morning_open <= current_time <= morning_close) or \
            (afternoon_open <= current_time <= afternoon_close)

    def _generate_tick_data(self, stock_info: Dict) -> Dict:
        """生成单只股票的tick数据"""
        base_price = stock_info['base_price']
        volatility = stock_info['volatility']
        prev_close = stock_info['prev_close']

        # 生成价格波动
        price_change = random.uniform(-volatility, volatility)
        current_price = base_price * (1 + price_change)
        current_price = max(0.01, current_price)  # 价格不能为负

        # 更新基础价格（模拟价格趋势）
        stock_info['base_price'] = current_price

        # 生成买卖五档价格
        spread = 0.01  # 最小价格变动单位
        bid_prices = []
        ask_prices = []

        for i in range(1, 6):
            bid_price = current_price * (1 - i * 0.001)  # 买价递减
            ask_price = current_price * (1 + i * 0.001)  # 卖价递增
            bid_prices.append(round(bid_price, 2))
            ask_prices.append(round(ask_price, 2))

        # 生成买卖五档数量
        bid_sizes = [random.randint(100, 100000) for _ in range(5)]
        ask_sizes = [random.randint(100, 100000) for _ in range(5)]

        # 计算最高最低价（基于当日价格范围）
        if not hasattr(stock_info, 'day_high'):
            stock_info['day_high'] = current_price * 1.1
            stock_info['day_low'] = current_price * 0.9

        day_high = max(stock_info['day_high'], current_price)
        day_low = min(stock_info['day_low'], current_price)
        stock_info['day_high'] = day_high
        stock_info['day_low'] = day_low

        tick_data = {
            'code': stock_info['code'],
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
            'prev_close': prev_close,
            'last': round(current_price, 2),
            'open': round(prev_close * random.uniform(0.95, 1.05), 2),
            'high': round(day_high, 2),
            'low': round(day_low, 2),
            'close': '',  # 收盘时更新
            'bid1': bid_prices[0],
            'bid2': bid_prices[1],
            'bid3': bid_prices[2],
            'bid4': bid_prices[3],
            'bid5': bid_prices[4],
            'bid_size1': bid_sizes[0],
            'bid_size2': bid_sizes[1],
            'bid_size3': bid_sizes[2],
            'bid_size4': bid_sizes[3],
            'bid_size5': bid_sizes[4],
            'ask1': ask_prices[0],
            'ask2': ask_prices[1],
            'ask3': ask_prices[2],
            'ask4': ask_prices[3],
            'ask5': ask_prices[4],
            'ask_size1': ask_sizes[0],
            'ask_size2': ask_sizes[1],
            'ask_size3': ask_sizes[2],
            'ask_size4': ask_sizes[3],
            'ask_size5': ask_sizes[4],
            'volume': random.randint(1000, 1000000),
            'amount': round(current_price * random.randint(1000, 1000000), 2)
        }

        return tick_data

    def add_callback(self, callback):
        """
        添加回调函数
        """
        self.callbacks.append(callback)

    async def _push_tick_data(self, tick_data: Dict):
        """推送tick数据到所有回调函数"""
        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(tick_data)
                else:
                    callback(tick_data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    async def _simulate_stock_group(self, stock_group: List[Dict], interval: float):
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

    async def start(self, ticks_per_second: int = 10):
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
        stock_groups = [self.stocks[i:i + group_size]
                        for i in range(0, len(self.stocks), group_size)]

        # 创建并发的模拟任务
        tasks = []
        for group in stock_groups:
            task = asyncio.create_task(self._simulate_stock_group(group, interval))
            tasks.append(task)

        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            self.logger.error(f"Simulator error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        """停止模拟器"""
        self.is_running = False
        self.logger.info("Stopping simulator...")

# 使用示例
# 使用示例
async def example_callback(tick_data: Dict):
    """示例回调函数 - 处理接收到的tick数据"""
    # 这里可以替换为实际的数据处理逻辑，比如:
    # - 存储到数据库
    # - 发送到消息队列
    # - 实时分析计算
    # print(f"Received tick data for {tick_data['code']}: {tick_data['last']}")
    print(tick_data)


async def main():
    # 创建模拟器实例
    simulator = AShareTickDataSimulator(stock_count=5)  # 测试时使用100只股票

    # 添加数据回调
    simulator.add_callback(example_callback)

    # 启动模拟器（在后台运行）
    simulator_task = asyncio.create_task(simulator.start(ticks_per_second=5000))

    try:
        # 让模拟器运行一段时间
        await asyncio.sleep(60)
    except KeyboardInterrupt:
        print("Stopping simulator...")
    finally:
        simulator.stop()
        await simulator_task



if __name__ == "__main__":
    asyncio.run(main())













