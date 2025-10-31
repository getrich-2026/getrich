import duckdb
import pandas as pd

# 创建一个内存数据库连接
con = duckdb.connect(database=':memory:')

# 执行SQL查询
con.execute("CREATE TABLE items(id INTEGER, name VARCHAR)")
con.execute("INSERT INTO items VALUES (1, '苹果'), (2, '香蕉'), (3, '橙子')")

# 查询数据
result = con.execute("SELECT * FROM items").fetchall()
print(result)
# 输出: [(1, '苹果'), (2, '香蕉'), (3, '橙子')]

# 也可以与pandas结合使用
df = con.execute("SELECT * FROM items").df()
print(df)
