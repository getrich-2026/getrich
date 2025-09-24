import sys
from types import ModuleType
import importlib.util
import pandas as pd
import pytest

FILEPATH = "/home/ln/project/getrich/Data/database/database.py"


class DummyLog:
    def __init__(self):
        self.messages = []

    def error(self, msg):
        self.messages.append(("error", str(msg)))

    def warning(self, msg):
        self.messages.append(("warning", str(msg)))


class FakeClient:
    def __init__(self):
        self.last_command = None
        self.closed = False
        self.query_df_ret = None
        self.insert_df_calls = []
        self.insert_calls = []

    def command(self, sql):
        self.last_command = sql

    def query_df(self, sql):
        self.last_command = sql
        return self.query_df_ret

    def insert_df(self, table, df):
        self.insert_df_calls.append((table, df.copy()))

    def insert(self, table, data, column_names=None):
        self.insert_calls.append((table, data, column_names))

    def close(self):
        self.closed = True


def _ensure_dummy_modules(fake_client=None):
    # 确保包结构存在，支持相对导入 .utils
    for name in ("Data", "Data.database"):
        if name not in sys.modules:
            mod = ModuleType(name)
            mod.__path__ = []  # 标记为包
            sys.modules[name] = mod

    # 注入 Data.database.utils.log
    utils_name = "Data.database.utils"
    utils_mod = ModuleType(utils_name)
    utils_mod.log = DummyLog()
    sys.modules[utils_name] = utils_mod

    # 注入 clickhouse_connect.get_client
    ch_mod = ModuleType("clickhouse_connect")

    def _get_client(**kwargs):
        return fake_client if fake_client is not None else FakeClient()

    ch_mod.get_client = _get_client
    sys.modules["clickhouse_connect"] = ch_mod

    return utils_mod.log


def _load_db_module(fake_client=None):
    # 每次加载前移除旧模块，确保干净环境
    for name in ("Data.database.database",):
        if name in sys.modules:
            del sys.modules[name]

    _ensure_dummy_modules(fake_client=fake_client)

    spec = importlib.util.spec_from_file_location("Data.database.database", FILEPATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["Data.database.database"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_execute_sql_success():
    fake = FakeClient()
    mod = _load_db_module(fake_client=fake)
    DB = mod.ClickHouseDB
    db = DB()
    ok = db.execute_sql("CREATE TABLE t(a Int32) ENGINE=Memory")
    assert ok is True
    assert fake.last_command == "CREATE TABLE t(a Int32) ENGINE=Memory"


def test_execute_sql_no_client():
    mod = _load_db_module(fake_client=FakeClient())
    DB = mod.ClickHouseDB
    db = DB()
    db.client = None
    ok = db.execute_sql("SELECT 1")
    assert ok is False


def test_read_data_with_condition():
    fake = FakeClient()
    expect_df = pd.DataFrame({"a": [1, 2]})
    fake.query_df_ret = expect_df
    mod = _load_db_module(fake_client=fake)
    DB = mod.ClickHouseDB
    db = DB()
    df = db.read_data("t_ticks", columns="a", condition="a > 0")
    assert df.equals(expect_df)
    assert "SELECT a FROM t_ticks WHERE a > 0" == fake.last_command


def test_insert_data_dataframe_and_list():
    fake = FakeClient()
    mod = _load_db_module(fake_client=fake)
    DB = mod.ClickHouseDB
    db = DB()

    # DataFrame 插入
    df = pd.DataFrame({"a": [1, 2]})
    ok_df = db.insert_data("t1", df)
    assert ok_df is True
    assert fake.insert_df_calls and fake.insert_df_calls[0][0] == "t1"

    # list 插入
    rows = [(1, "x"), (2, "y")]
    ok_list = db.insert_data("t2", rows, column_names=["id", "name"])
    assert ok_list is True
    assert fake.insert_calls and fake.insert_calls[0] == ("t2", rows, ["id", "name"])


def test_upsert_data_composite_key_builds_delete_then_insert(monkeypatch):
    fake = FakeClient()
    mod = _load_db_module(fake_client=fake)
    DB = mod.ClickHouseDB
    db = DB()

    # 捕获 execute_sql 与 insert_data 调用
    issued_sql = []

    def fake_exec(sql):
        issued_sql.append(sql)
        return True

    called_insert = {"called": False}

    def fake_insert(table, data, column_names=None):
        called_insert["called"] = True
        return True

    monkeypatch.setattr(db, "execute_sql", fake_exec)
    monkeypatch.setattr(db, "insert_data", fake_insert)

    data = pd.DataFrame(
        {
            "symbol": ["AU", "AG"],
            "ts": [1, 2],
            "v": [10.0, 20.0],
        }
    )

    ok = db.upsert_data("t_kline", data, key_columns=["symbol", "ts"])
    assert ok is True
    assert called_insert["called"] is True

    # 校验 DELETE 语句（复合键）
    assert len(issued_sql) == 1
    assert (
        issued_sql[0]
        == "ALTER TABLE t_kline DELETE WHERE (symbol, ts) IN (('AU', 1), ('AG', 2))"
    )


def test_upsert_data_invalid_when_empty_or_missing_keys():
    fake = FakeClient()
    mod = _load_db_module(fake_client=fake)
    DB = mod.ClickHouseDB
    db = DB()

    # 空 DataFrame
    empty = pd.DataFrame(columns=["k"])
    assert db.upsert_data("t", empty, key_columns=["k"]) is False

    # 缺少关键列
    df = pd.DataFrame({"a": [1]})
    assert db.upsert_data("t", df, key_columns=["k"]) is False


if __name__ == "__main__":
    # 直接调用所有测试函数
    test_execute_sql_success()
    # test_execute_sql_no_client()
    # test_read_data_with_condition()
    # test_insert_data_dataframe_and_list()
    # # 需要 monkeypatch，跳过 test_upsert_data_composite_key_builds_delete_then_insert
    # test_upsert_data_invalid_when_empty_or_missing_keys()
    print("All tests executed.")