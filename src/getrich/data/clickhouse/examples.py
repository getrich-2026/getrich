"""
ClickHouse 新架构使用示例

展示如何使用重构后的 ClickHouseClient、ClickHouseConnectionPool 和 ClickHouseTable。
"""
import time
import threading
from typing import List
import pandas as pd
from .database import ClickHouseClient
from .pool import ClickHouseConnectionPool
from .table.bar import MinBarTable


def example_1_simple():
    """示例 1:简单使用(每个表独立连接)"""
    print("\n=== 示例 1:简单使用 ===")

    # 创建表实例，自动创建客户端
    table = MinBarTable(table_name='min_bar')

    # 创建表
    table.create()

    # 检查表是否存在
    if table.exists():
        print(f"表 '{table.table_name}' 已存在")

    # 获取记录数
    count = table.count()
    print(f"表中有 {count} 条记录")

    # 关闭连接
    table.close()


def example_2_shared_client():
    """示例 2:共享客户端(推荐，多表操作)"""
    print("\n=== 示例 2:共享客户端 ===")

    # 创建一个客户端
    client = ClickHouseClient(
        host='192.168.1.232',
        database='default'
    )

    # 多个表共享同一个客户端
    min_bar_table = MinBarTable(table_name='min_bar', client=client)
    # tick_table = TickTable(table_name='tick_data', client=client)

    # 创建表
    min_bar_table.create()
    # tick_table.create()

    # 数据操作
    if min_bar_table.exists():
        count = min_bar_table.count()
        print(f"min_bar 表有 {count} 条记录")

    # 统一关闭连接
    client.close()
    print("客户端连接已关闭")


def example_3_context_manager():
    """示例 3:上下文管理器(最佳实践)"""
    print("\n=== 示例 3:上下文管理器 ===")

    # 使用上下文管理器自动管理连接
    with ClickHouseClient() as client:
        table = MinBarTable(table_name='min_bar', client=client)

        # 创建表
        table.create()

        # 查询数据
        if table.exists():
            count = table.count()
            print(f"表中有 {count} 条记录")

            # 查询最近的数据
            df = table.read(
                start_date='20250101',
                end_date='20250131',
                limit=10
            )
            if df is not None and not df.empty:
                print(f"查询到 {len(df)} 条记录")

    # 连接会自动关闭
    print("连接已自动关闭")


def example_4_configuration():
    """示例 4:配置管理"""
    print("\n=== 示例 4:配置管理 ===")

    # 创建客户端
    client = ClickHouseClient()

    # 查看当前配置
    config = client.get_config()
    print(f"当前配置:{config}")

    # 检查连接状态
    print(f"连接状态:{client.is_connected()}")

    # 运行时修改配置(会重新连接)
    client.configure(database='test_db', reconnect=True)

    # 查看新配置
    new_config = client.get_config()
    print(f"新配置:{new_config}")

    client.close()


def example_5_data_operations():
    """示例 5:数据操作"""
    print("\n=== 示例 5:数据操作 ===")

    with ClickHouseClient() as client:
        table = MinBarTable(table_name='min_bar', client=client)

        # 确保表存在
        table.create()

        # 1. 插入数据
        sample_data = {
            'date': [20250101],
            'time': [93000000],
            'pre_close': [50000],
            'open': [50100],
            'high': [50200],
            'low': [50000],
            'close': [50150],
            'volume': [1000],
            'turnover': [50150000],
            'open_interest': [5000],
            'pre_settle_price': [50000],
            'settle_price': [50150],
            'symbol': ['TEST2501'],
            'local_time': [pd.Timestamp.now()]
        }
        df = pd.DataFrame(sample_data)

        if table.insert(df):
            print("数据插入成功")

        # 2. 查询数据
        result = table.query(
            f"SELECT * FROM {table.table_name} WHERE symbol = 'TEST2501' LIMIT 1"
        )
        if result is not None and not result.empty:
            print(f"查询结果:\n{result}")

        # 3. 统计记录数
        count = table.count(condition="symbol = 'TEST2501'")
        print(f"TEST2501 有 {count} 条记录")

        # 4. 优化表
        if table.optimize():
            print("表优化成功")


def example_6_batch_operations():
    """示例 6:批量操作"""
    print("\n=== 示例 6:批量操作 ===")

    with ClickHouseClient() as client:
        table = MinBarTable(table_name='min_bar', client=client)
        table.create()

        # 生成大量测试数据
        n_rows = 10000
        sample_data = {
            'date': [20250101] * n_rows,
            'time': list(range(93000000, 93000000 + n_rows)),
            'pre_close': [50000] * n_rows,
            'open': [50100] * n_rows,
            'high': [50200] * n_rows,
            'low': [50000] * n_rows,
            'close': [50150] * n_rows,
            'volume': [1000] * n_rows,
            'turnover': [50150000] * n_rows,
            'open_interest': [5000] * n_rows,
            'pre_settle_price': [50000] * n_rows,
            'settle_price': [50150] * n_rows,
            'symbol': ['BATCH_TEST'] * n_rows,
            'local_time': [pd.Timestamp.now()] * n_rows
        }
        df = pd.DataFrame(sample_data)

        # 分批插入(每批 2000 条)
        print(f"开始插入 {n_rows} 条记录...")
        if table.insert(df, batch_size=2000):
            print("批量插入成功")

        # 验证
        count = table.count(condition="symbol = 'BATCH_TEST'")
        print(f"插入了 {count} 条记录")


def example_7_migration():
    """示例 7:从旧代码迁移"""
    print("\n=== 示例 7:迁移示例 ===")

    # 旧代码(仍然支持)
    print("旧代码风格(向后兼容):")
    table_old = MinBarTable(
        table_name='min_bar',
        host='192.168.1.232',
        database='default'
    )
    table_old.create()
    print(f"表存在:{table_old.exists()}")
    table_old.close()

    # 新代码(推荐)
    print("\n新代码风格(推荐):")
    with ClickHouseClient(host='192.168.1.232', database='default') as client:
        table_new = MinBarTable(table_name='min_bar', client=client)
        table_new.create()
        print(f"表存在:{table_new.exists()}")

    print("\n两种方式都可以工作，但新方式更高效！")


def example_8_connection_pool():
    """示例 8:连接池基础用法"""
    print("\n=== 示例 8:连接池基础用法 ===")

    # 创建连接池
    pool = ClickHouseConnectionPool(
        host='192.168.1.232',
        database='default',
        min_size=2,
        max_size=10
    )

    # 使用连接池创建表实例
    table = MinBarTable(table_name='min_bar', pool=pool)

    # 执行操作（自动从池中获取和释放连接）
    table.create()
    count = table.count()
    print(f"表中有 {count} 条记录")

    # 查看连接池统计
    stats = pool.get_stats()
    print("\n连接池统计:")
    print(f"  总连接数: {stats['total_connections']}")
    print(f"  活动连接: {stats['active_connections']}")
    print(f"  空闲连接: {stats['idle_connections']}")
    print(f"  获取请求: {stats['get_requests']}")

    # 关闭连接池
    pool.close_all()
    print("连接池已关闭")


def example_9_pool_context_manager():
    """示例 9:连接池上下文管理器"""
    print("\n=== 示例 9:连接池上下文管理器 ===")

    # 使用上下文管理器自动管理连接池
    with ClickHouseConnectionPool(
        host='192.168.1.232',
        database='default',
        min_size=3,
        max_size=10
    ) as pool:
        # 创建多个表实例，共享连接池
        table1 = MinBarTable(table_name='min_bar', pool=pool)
        table2 = MinBarTable(table_name='min_bar_1m', pool=pool)

        # 并发操作
        count1 = table1.count()
        count2 = table2.count()

        print(f"表1记录数: {count1}")
        print(f"表2记录数: {count2}")

        # 查看统计
        stats = pool.get_stats()
        print("\n连接池统计:")
        print(f"  获取请求: {stats['get_requests']}")
        print(f"  释放次数: {stats['releases']}")

    # 连接池自动关闭
    print("连接池已自动关闭")


def example_10_multi_thread_pool():
    """示例 10:多线程使用连接池"""
    print("\n=== 示例 10:多线程使用连接池 ===")

    pool = ClickHouseConnectionPool(
        host='192.168.1.232',
        database='default',
        min_size=3,
        max_size=15
    )

    def worker(thread_id: int, iterations: int):
        """工作线程函数"""
        table = MinBarTable(table_name='min_bar', pool=pool)
        for i in range(iterations):
            count = table.count()
            print(f"线程 {thread_id} - 第 {i+1} 次查询: {count} 条记录")
            time.sleep(0.1)

    # 创建多个线程
    threads: List[threading.Thread] = []
    thread_count = 5
    iterations_per_thread = 3

    print(f"启动 {thread_count} 个线程，每个线程执行 {iterations_per_thread} 次查询...")

    for i in range(thread_count):
        thread = threading.Thread(target=worker, args=(i, iterations_per_thread))
        threads.append(thread)
        thread.start()

    # 等待所有线程完成
    for thread in threads:
        thread.join()

    # 查看最终统计
    stats = pool.get_stats()
    print("\n多线程完成后统计:")
    print(f"  总请求: {stats['get_requests']}")
    print(f"  总释放: {stats['releases']}")
    print(f"  最大连接数: {stats['total_connections']}")
    print(f"  当前活动: {stats['active_connections']}")

    pool.close_all()
    print("多线程连接池示例完成")


def example_11_direct_pool_usage():
    """示例 11:直接使用连接池获取连接"""
    print("\n=== 示例 11:直接使用连接池 ===")

    pool = ClickHouseConnectionPool(
        host='192.168.1.232',
        database='default',
        min_size=2,
        max_size=5
    )

    # 方式 1: 使用上下文管理器（推荐）
    print("\n方式 1: 上下文管理器")
    with pool.connection() as client:
        result = client.query("SELECT count() as cnt FROM min_bar")
        print(f"总记录数: {result.iloc[0]['cnt']}")

    # 方式 2: 手动获取和释放
    print("\n方式 2: 手动获取和释放")
    client = pool.get_connection()
    try:
        result = client.query("SELECT count() as cnt FROM min_bar")
        print(f"总记录数: {result.iloc[0]['cnt']}")
    finally:
        pool.release_connection(client)

    pool.close_all()
    print("直接连接池使用完成")


def example_12_pool_monitoring():
    """示例 12:连接池监控和维护"""
    print("\n=== 示例 12:连接池监控 ===")

    pool = ClickHouseConnectionPool(
        host='192.168.1.232',
        database='default',
        min_size=2,
        max_size=8,
        max_idle_time=60,
        max_lifetime=300
    )

    # 执行一些操作
    table = MinBarTable(table_name='min_bar', pool=pool)
    for i in range(5):
        count = table.count()
        print(f"第 {i+1} 次查询: {count} 条记录")

    # 查看详细统计
    stats = pool.get_stats()
    print(f"\n连接池详细统计:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 执行维护操作
    print("\n执行维护操作...")
    pool.cleanup()
    pool.shrink()

    print("\n执行健康检查...")
    pool.health_check()

    # 查看维护后统计
    stats = pool.get_stats()
    print("\n维护后统计:")
    print(f"  总连接数: {stats['total_connections']}")
    print(f"  活动连接: {stats['active_connections']}")
    print(f"  空闲连接: {stats['idle_connections']}")

    pool.close_all()
    print("连接池监控完成")


def example_13_three_modes_comparison():
    """示例 13:三种连接模式对比"""
    print("\n=== 示例 13:三种连接模式对比 ===")

    # 模式 1: 独立客户端（表自己管理连接）
    print("\n模式 1: 独立客户端")
    table1 = MinBarTable(
        table_name='min_bar',
        host='192.168.1.232',
        database='default'
    )
    count1 = table1.count()
    print(f"  独立模式记录数: {count1}")
    print(f"  拥有客户端: {table1._owns_client}")
    table1.close()

    # 模式 2: 共享客户端（多表共享一个连接）
    print("\n模式 2: 共享客户端")
    with ClickHouseClient(host='192.168.1.232', database='default') as client:
        table2 = MinBarTable(table_name='min_bar', client=client)
        count2 = table2.count()
        print(f"  共享模式记录数: {count2}")
        print(f"  拥有客户端: {table2._owns_client}")

    # 模式 3: 连接池（高并发场景）
    print("\n模式 3: 连接池")
    with ClickHouseConnectionPool(
        host='192.168.1.232',
        database='default',
        min_size=2,
        max_size=10
    ) as pool:
        table3 = MinBarTable(table_name='min_bar', pool=pool)
        count3 = table3.count()
        print(f"  连接池模式记录数: {count3}")
        print(f"  使用连接池: {table3._use_pool}")

        stats = pool.get_stats()
        print(f"  连接池连接数: {stats['total_connections']}")

    print("\n三种模式对比完成")


def main():
    """运行所有示例"""
    print("=" * 60)
    print("ClickHouse 新架构使用示例")
    print("=" * 60)

    try:
        # 基础示例
        example_1_simple()
        example_2_shared_client()
        example_3_context_manager()
        example_4_configuration()
        # example_5_data_operations()  # 需要实际数据
        # example_6_batch_operations()  # 会插入大量测试数据
        example_7_migration()

        # 连接池示例（新增）
        # example_8_connection_pool()
        # example_9_pool_context_manager()
        # example_10_multi_thread_pool()
        # example_11_direct_pool_usage()
        # example_12_pool_monitoring()
        # example_13_three_modes_comparison()

    except Exception as e:
        print(f"\n错误:{e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("示例运行完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
