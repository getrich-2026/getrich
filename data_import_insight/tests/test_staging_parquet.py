from __future__ import annotations

from datetime import date

import pandas as pd

from getrich_data_import.staging import write_staging_parquet


def test_write_staging_parquet_writes_file_and_manifest(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "source_symbol": ["000001.SZ", "000002.SZ"],
            "trading_day": [date(2026, 6, 1), date(2026, 6, 1)],
            "close": [10.0, 20.0],
        }
    )

    staged = write_staging_parquet(
        frame,
        root_dir=tmp_path,
        provider="insight",
        dataset_name="stock_bar_1d",
        asset="stock",
        freq="1d",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        partition_key="batch_00001",
    )

    assert staged.path.exists()
    assert staged.row_count == 2
    assert staged.file_size_bytes > 0
    assert len(staged.content_hash) == 64
    assert len(staged.schema_fingerprint) == 64

    row = staged.manifest_row(
        provider="insight",
        dataset_name="stock_bar_1d",
        asset="stock",
        freq="1d",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        fetch_run_id=1,
        metadata={"columns": list(frame.columns)},
    )
    assert row["source_path"] == str(staged.path)
    assert row["status"] == "written"
    assert row["metadata"] == '{"columns": ["source_symbol", "trading_day", "close"]}'
