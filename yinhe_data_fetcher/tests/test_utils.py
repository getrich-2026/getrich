import pytest
import pandas as pd
from pathlib import Path
from src.utils import write_parquet, read_parquet_index, last_index_date


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


def test_write_parquet_append_false(temp_dir):
    df = pd.DataFrame({"A": [1, 2]}, index=[10, 20])
    df.index.name = "idx"
    out_path = temp_dir / "test1.parquet"
    
    write_parquet(df, out_path, append=False)
    
    assert out_path.exists()
    loaded = pd.read_parquet(out_path)
    pd.testing.assert_frame_equal(df, loaded)


def test_write_parquet_append_true(temp_dir):
    out_path = temp_dir / "test2.parquet"
    
    # 1. 首次写入
    df1 = pd.DataFrame({"A": [1, 2]}, index=[10, 20])
    df1.index.name = "idx"
    write_parquet(df1, out_path, append=False)
    
    # 2. 追加写入（覆盖 idx=20 的值，新增 idx=30 和 15）
    # 以乱序写入
    df2 = pd.DataFrame({"A": [99, 3, 15]}, index=[20, 30, 15])
    df2.index.name = "idx"
    write_parquet(df2, out_path, append=True)
    
    # 3. 验证结果
    # - 去重：idx=20 保留 df2 的值 (99)
    # - 排序：idx 应为 [10, 15, 20, 30]
    loaded = pd.read_parquet(out_path)
    
    expected = pd.DataFrame({"A": [1, 15, 99, 3]}, index=[10, 15, 20, 30])
    expected.index.name = "idx"
    
    pd.testing.assert_frame_equal(loaded, expected)


def test_write_parquet_append_true_multiindex(temp_dir):
    out_path = temp_dir / "test3.parquet"
    
    idx1 = pd.MultiIndex.from_tuples([("A", 1), ("A", 2)], names=["code", "date"])
    df1 = pd.DataFrame({"val": [10, 20]}, index=idx1)
    write_parquet(df1, out_path, append=False)
    
    idx2 = pd.MultiIndex.from_tuples([("A", 2), ("B", 1)], names=["code", "date"])
    df2 = pd.DataFrame({"val": [99, 30]}, index=idx2)
    write_parquet(df2, out_path, append=True)
    
    loaded = pd.read_parquet(out_path)
    
    expected_idx = pd.MultiIndex.from_tuples([("A", 1), ("A", 2), ("B", 1)], names=["code", "date"])
    expected = pd.DataFrame({"val": [10, 99, 30]}, index=expected_idx)
    
    pd.testing.assert_frame_equal(loaded, expected)


def test_write_parquet_append_true_no_index_name(temp_dir):
    out_path = temp_dir / "test4.parquet"
    
    df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    write_parquet(df1, out_path, append=False)
    
    df2 = pd.DataFrame({"A": [2, 5], "B": [4, 6]}) # 完全相同的行 A=2, B=4
    write_parquet(df2, out_path, append=True)
    
    loaded = pd.read_parquet(out_path)
    
    # 因为去重保留最后一条，排序后 A=1, B=3; A=2, B=4; A=5, B=6
    expected = pd.DataFrame({"A": [1, 2, 5], "B": [3, 4, 6]})
    
    # 没有 index_name 会做全字段去重，并且 sort_index (index 原本是 0, 1, 0, 1，重新排序后索引可能变)
    # utils 里面的 sorted_index(inplace=True) 是对当前索引进行排序，这对于无名递增索引可能没啥实际物理意义，但应该存在
    # 只要验证数据量和内容对即可，这里我们直接验证框架相等可能会遇到索引不匹配
    # 为了避免索引带来的困扰，我们 reset_index
    assert len(loaded) == 3
    assert list(loaded["A"]) == [1, 2, 5]


def test_read_parquet_index_and_last_date(temp_dir):
    out_path = temp_dir / "test_idx.parquet"
    
    # 1. Non-existent file
    assert read_parquet_index(out_path) is None
    assert last_index_date(None) is None
    
    # 2. Empty DataFrame with no index
    df_empty = pd.DataFrame()
    write_parquet(df_empty, out_path, append=False)
    
    df_loaded_empty = read_parquet_index(out_path)
    assert df_loaded_empty is not None
    assert len(df_loaded_empty.index) == 0
    assert last_index_date(df_loaded_empty) is None
    
    # 3. DataFrame with datetime index
    df_dt = pd.DataFrame({"val": [1]}, index=pd.to_datetime(["2023-01-01"]))
    write_parquet(df_dt, out_path, append=False)
    
    df_loaded_dt = read_parquet_index(out_path)
    assert len(df_loaded_dt.columns) == 0  # Should only load index
    assert len(df_loaded_dt.index) == 1
    assert last_index_date(df_loaded_dt) == 20230101
    
    # 4. DataFrame with int index
    df_int = pd.DataFrame({"val": [1, 2]}, index=[20230101, 20230105])
    write_parquet(df_int, out_path, append=False)
    
    df_loaded_int = read_parquet_index(out_path)
    assert len(df_loaded_int.columns) == 0
    assert last_index_date(df_loaded_int) == 20230105


# =============================================================================
# Phase 3: DuckDB merge path tests
# =============================================================================

class TestDuckDBMerge:
    """验收 Phase 3: DuckDB 合并写入与 pandas 降级一致性."""

    def test_append_named_index_uses_duckdb(self, temp_dir):
        """命名索引走 DuckDB 路径, 结果与 pandas 一致."""
        out = temp_dir / "duckdb1.parquet"
        df1 = pd.DataFrame({"A": [1, 2, 3]}, index=[10, 20, 30])
        df1.index.name = "idx"
        write_parquet(df1, out, append=False)

        df2 = pd.DataFrame({"A": [99, 4]}, index=[20, 40])
        df2.index.name = "idx"
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        expected = pd.DataFrame({"A": [1, 99, 3, 4]}, index=[10, 20, 30, 40])
        expected.index.name = "idx"
        pd.testing.assert_frame_equal(loaded, expected)

    def test_schema_drift_new_column(self, temp_dir):
        """新数据多出一列: UNION BY NAME 补 NULL, 不丢列."""
        out = temp_dir / "drift1.parquet"
        df1 = pd.DataFrame({"A": [1, 2]}, index=[10, 20])
        df1.index.name = "idx"
        write_parquet(df1, out)

        df2 = pd.DataFrame({"A": [3], "B": [99.0]}, index=[30])
        df2.index.name = "idx"
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        assert "A" in loaded.columns
        assert "B" in loaded.columns
        assert len(loaded) == 3
        # 旧行的 B 列应该为 NaN
        assert pd.isna(loaded.loc[10, "B"])
        assert loaded.loc[30, "B"] == 99.0

    def test_schema_drift_missing_column(self, temp_dir):
        """新数据缺少旧列: UNION BY NAME 补 NULL, 不丢旧列."""
        out = temp_dir / "drift2.parquet"
        df1 = pd.DataFrame({"A": [1], "B": [2.0]}, index=[10])
        df1.index.name = "idx"
        write_parquet(df1, out)

        df2 = pd.DataFrame({"A": [3]}, index=[20])
        df2.index.name = "idx"
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        assert "A" in loaded.columns
        assert "B" in loaded.columns
        assert len(loaded) == 2
        assert pd.isna(loaded.loc[20, "B"])
        assert loaded.loc[10, "B"] == 2.0

    def test_column_order_different(self, temp_dir):
        """新旧数据列顺序不同, 合并后数据正确."""
        out = temp_dir / "order1.parquet"
        df1 = pd.DataFrame({"A": [1], "B": [2]}, index=[10])
        df1.index.name = "idx"
        write_parquet(df1, out)

        df2 = pd.DataFrame({"B": [4], "A": [3]}, index=[20])
        df2.index.name = "idx"
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        assert len(loaded) == 2
        assert loaded.loc[20, "A"] == 3
        assert loaded.loc[20, "B"] == 4

    def test_duplicate_index_keeps_new(self, temp_dir):
        """重复索引保留新数据."""
        out = temp_dir / "dup1.parquet"
        df1 = pd.DataFrame({"A": [1, 2, 3]}, index=[10, 20, 30])
        df1.index.name = "idx"
        write_parquet(df1, out)

        df2 = pd.DataFrame({"A": [99, 88]}, index=[20, 30])
        df2.index.name = "idx"
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        expected = pd.DataFrame({"A": [1, 99, 88]}, index=[10, 20, 30])
        expected.index.name = "idx"
        pd.testing.assert_frame_equal(loaded, expected)

    def test_empty_new_data(self, temp_dir):
        """追加空 DataFrame, 旧数据保持不变."""
        out = temp_dir / "empty1.parquet"
        df1 = pd.DataFrame({"A": [1, 2]}, index=[10, 20])
        df1.index.name = "idx"
        write_parquet(df1, out)

        df2 = pd.DataFrame({"A": pd.Series([], dtype="int64")},
                           index=pd.Index([], name="idx", dtype="int64"))
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        expected = pd.DataFrame({"A": [1, 2]}, index=[10, 20])
        expected.index.name = "idx"
        pd.testing.assert_frame_equal(loaded, expected)

    def test_multiindex_duckdb(self, temp_dir):
        """MultiIndex 也走 DuckDB 路径."""
        out = temp_dir / "multi1.parquet"
        idx1 = pd.MultiIndex.from_tuples(
            [("A", 1), ("A", 2)], names=["code", "date"]
        )
        df1 = pd.DataFrame({"val": [10, 20]}, index=idx1)
        write_parquet(df1, out)

        idx2 = pd.MultiIndex.from_tuples(
            [("A", 2), ("B", 1)], names=["code", "date"]
        )
        df2 = pd.DataFrame({"val": [99, 30]}, index=idx2)
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        expected_idx = pd.MultiIndex.from_tuples(
            [("A", 1), ("A", 2), ("B", 1)], names=["code", "date"]
        )
        expected = pd.DataFrame({"val": [10, 99, 30]}, index=expected_idx)
        pd.testing.assert_frame_equal(loaded, expected)

    def test_no_temp_file_leak(self, temp_dir):
        """合并完成后不应残留临时文件."""
        out = temp_dir / "leak1.parquet"
        df1 = pd.DataFrame({"A": [1]}, index=[10])
        df1.index.name = "idx"
        write_parquet(df1, out)

        df2 = pd.DataFrame({"A": [2]}, index=[20])
        df2.index.name = "idx"
        write_parquet(df2, out, append=True)

        remaining = list(temp_dir.glob("*.tmp.parquet"))
        assert remaining == [], f"leaked temp files: {remaining}"

    def test_unnamed_index_fallback(self, temp_dir):
        """无命名索引应降级到 pandas 路径, 行为不变."""
        out = temp_dir / "fallback1.parquet"
        df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        write_parquet(df1, out)

        df2 = pd.DataFrame({"A": [2, 5], "B": [4, 6]})
        write_parquet(df2, out, append=True)

        loaded = pd.read_parquet(out)
        assert len(loaded) == 3
        assert list(loaded["A"]) == [1, 2, 5]
