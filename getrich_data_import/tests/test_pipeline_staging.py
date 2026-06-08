from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from getrich_data_import.orchestration.pipeline import ImportPipeline
from getrich_data_import.staging import file_sha256, parquet_schema_fingerprint


class _Tx:
    def __init__(self, engine: "_Engine") -> None:
        self.engine = engine
        self.conn = _Conn(engine)

    def __enter__(self):
        self.engine.events.append(("begin", None))
        return self.conn

    def __exit__(self, exc_type, _exc, _tb):
        self.engine.events.append(("rollback" if exc_type else "commit", None))
        return False


class _Rows:
    def __init__(self, rows) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def scalars(self):
        return []

    def __iter__(self):
        return iter(self._rows)


class _Conn:
    def __init__(self, engine: "_Engine") -> None:
        self.engine = engine

    def execute(self, sql, params=None):
        self.engine.sqls.append((str(sql), params))
        if "FROM staging.parquet_file" in str(sql):
            return _Rows(self.engine.staged_files)
        return _Rows([])


class _Engine:
    def __init__(self, staged_files) -> None:
        self.staged_files = staged_files
        self.events: list[tuple[str, object]] = []
        self.sqls: list[tuple[str, object]] = []

    def begin(self) -> _Tx:
        return _Tx(self)


class _Source:
    name = "insight"
    provider = "insight"


def _staged_row(
    parquet_path, *, file_id: int = 7, row_count: int = 1
) -> dict[str, object]:
    return {
        "file_id": file_id,
        "source_path": str(parquet_path),
        "content_hash": file_sha256(parquet_path),
        "file_size_bytes": parquet_path.stat().st_size,
        "schema_fingerprint": parquet_schema_fingerprint(parquet_path),
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 2),
        "row_count": row_count,
    }


def test_load_dataset_reads_staged_parquet_and_marks_loaded(
    tmp_path, monkeypatch
) -> None:
    parquet_path = tmp_path / "stock.parquet"
    pd.DataFrame(
        [
            {
                "source_symbol": "000001.SZ",
                "dt": date(2026, 6, 1),
                "trading_day": date(2026, 6, 1),
                "open": 1.0,
                "high": 2.0,
                "low": 1.0,
                "close": 2.0,
                "source": "insight",
            },
            {
                "source_symbol": "000001.SZ",
                "dt": date(2026, 6, 2),
                "trading_day": date(2026, 6, 2),
                "open": 2.0,
                "high": 3.0,
                "low": 2.0,
                "close": 3.0,
                "source": "insight",
            },
        ]
    ).to_parquet(parquet_path)
    engine = _Engine([_staged_row(parquet_path, row_count=2)])
    settings = SimpleNamespace(
        batch_rows=1000,
        quality=SimpleNamespace(
            price_jump_warn_pct=0.2, fail_on_error=True, expected_minutes_per_day=None
        ),
    )
    captured = {}

    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.insert_job_run",
        lambda *_args, **_kwargs: 42,
    )
    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.finish_job_run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.attach_instrument_ids",
        lambda _conn, frame, source: frame.assign(
            instrument_id=1, asset="stock", exchange="SZ", symbol="000001.SZ"
        ),
    )

    def fake_upsert_dataframe(_conn, frame, **kwargs):
        captured["kwargs"] = kwargs
        captured["frame"] = frame.copy()
        return len(frame)

    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.upsert_dataframe",
        fake_upsert_dataframe,
    )

    pipeline = ImportPipeline(settings=settings, engine=engine, source=_Source())  # type: ignore[arg-type]
    result = pipeline.load_dataset(
        dataset_name="stock_bar_1d",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
    )

    assert result.rows_written == 1
    assert captured["kwargs"]["schema"] == "market"
    assert captured["kwargs"]["table"] == "stock_bar_1d"
    assert captured["frame"]["trading_day"].tolist() == [date(2026, 6, 1)]
    assert any("UPDATE staging.parquet_file" in sql for sql, _params in engine.sqls)
    select_params = [
        params for sql, params in engine.sqls if "FROM staging.parquet_file" in sql
    ][0]
    assert select_params["statuses"] == ["written"]


def test_load_dataset_reload_includes_loaded_files(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "stock.parquet"
    pd.DataFrame(
        [
            {
                "source_symbol": "000001.SZ",
                "dt": date(2026, 6, 1),
                "trading_day": date(2026, 6, 1),
                "open": 1.0,
                "high": 2.0,
                "low": 1.0,
                "close": 2.0,
                "source": "insight",
            }
        ]
    ).to_parquet(parquet_path)
    engine = _Engine([_staged_row(parquet_path)])
    settings = SimpleNamespace(
        batch_rows=1000,
        quality=SimpleNamespace(
            price_jump_warn_pct=0.2, fail_on_error=True, expected_minutes_per_day=None
        ),
    )

    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.insert_job_run",
        lambda *_args, **_kwargs: 42,
    )
    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.finish_job_run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.attach_instrument_ids",
        lambda _conn, frame, source: frame.assign(
            instrument_id=1, asset="stock", exchange="SZ", symbol="000001.SZ"
        ),
    )
    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.upsert_dataframe",
        lambda _conn, frame, **_kwargs: len(frame),
    )

    pipeline = ImportPipeline(settings=settings, engine=engine, source=_Source())  # type: ignore[arg-type]
    pipeline.load_dataset(dataset_name="stock_bar_1d", reload=True)

    select_params = [
        params for sql, params in engine.sqls if "FROM staging.parquet_file" in sql
    ][0]
    assert select_params["statuses"] == ["written", "loaded"]


def test_load_dataset_rejects_hash_mismatch_and_marks_failed(
    tmp_path, monkeypatch
) -> None:
    parquet_path = tmp_path / "stock.parquet"
    pd.DataFrame(
        [
            {
                "source_symbol": "000001.SZ",
                "dt": date(2026, 6, 1),
                "trading_day": date(2026, 6, 1),
                "open": 1.0,
                "high": 2.0,
                "low": 1.0,
                "close": 2.0,
                "source": "insight",
            }
        ]
    ).to_parquet(parquet_path)
    staged = _staged_row(parquet_path)
    staged["content_hash"] = "0" * 64
    engine = _Engine([staged])
    settings = SimpleNamespace(
        batch_rows=1000,
        quality=SimpleNamespace(
            price_jump_warn_pct=0.2, fail_on_error=True, expected_minutes_per_day=None
        ),
    )

    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.insert_job_run",
        lambda *_args, **_kwargs: 42,
    )
    monkeypatch.setattr(
        "getrich_data_import.orchestration.pipeline.finish_job_run",
        lambda *_args, **_kwargs: None,
    )

    pipeline = ImportPipeline(settings=settings, engine=engine, source=_Source())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="content hash mismatch"):
        pipeline.load_dataset(dataset_name="stock_bar_1d")

    assert any("status = 'failed'" in sql for sql, _params in engine.sqls)
