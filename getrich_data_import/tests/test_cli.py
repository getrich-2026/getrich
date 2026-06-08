from __future__ import annotations

from getrich_data_import.catalog import get_dataset_spec
from datetime import date
from types import SimpleNamespace

from getrich_data_import.cli import (
    _format_checkpoint_rows,
    _format_dataset_specs,
    _format_job_rows,
    build_parser,
    main,
)


def test_format_dataset_specs_renders_dataset_table() -> None:
    output = _format_dataset_specs((get_dataset_spec("insight", "parquet_staging"),))

    assert "provider" in output
    assert "parquet_staging" in output
    assert "staging.parquet_file" in output
    assert "parquet_staging" in output


def test_parser_accepts_fetch_dataset_command() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "--provider",
            "insight",
            "fetch-dataset",
            "--dataset",
            "stock_bar_1d",
            "--start-date",
            "2026-06-01",
            "--symbol",
            "000001.SZ",
        ]
    )

    assert args.cmd == "fetch-dataset"
    assert args.provider == "insight"
    assert args.dataset == "stock_bar_1d"
    assert args.symbols == ["000001.SZ"]


def test_parser_accepts_load_dataset_command() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "--provider",
            "insight",
            "load-dataset",
            "--dataset",
            "stock_bar_1d",
            "--end-date",
            "2026-06-01",
            "--reload",
        ]
    )

    assert args.cmd == "load-dataset"
    assert args.provider == "insight"
    assert args.dataset == "stock_bar_1d"
    assert args.end_date == "2026-06-01"
    assert args.reload is True


def test_parser_accepts_import_dataset_command() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "--provider",
            "insight",
            "import-dataset",
            "--dataset",
            "fund_nav",
            "--start-date",
            "2026-06-04",
            "--end-date",
            "2026-06-04",
            "--symbol",
            "161725.SZ",
            "--reload",
        ]
    )

    assert args.cmd == "import-dataset"
    assert args.dataset == "fund_nav"
    assert args.symbols == ["161725.SZ"]
    assert args.reload is True


def test_import_dataset_command_fetches_then_loads(monkeypatch, capsys) -> None:
    calls = []

    class _Pipeline:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_dataset(self, **kwargs):
            calls.append(("fetch", kwargs))
            return SimpleNamespace(
                job_name="fetch_fund_nav_parquet",
                status="success",
                rows_written=1,
            )

        def load_dataset(self, **kwargs):
            calls.append(("load", kwargs))
            return SimpleNamespace(
                job_name="load_fund_nav_parquet",
                status="success",
                rows_written=1,
            )

    monkeypatch.setattr(
        "getrich_data_import.cli.Settings.load",
        lambda _config=None: SimpleNamespace(
            provider="insight", database_url="postgresql://example"
        ),
    )
    monkeypatch.setattr("getrich_data_import.cli.get_history_source", lambda *_args: object())
    monkeypatch.setattr("getrich_data_import.cli.make_engine", lambda *_args: object())
    monkeypatch.setattr("getrich_data_import.cli.ImportPipeline", _Pipeline)

    code = main(
        [
            "--provider",
            "insight",
            "import-dataset",
            "--dataset",
            "fund_nav",
            "--start-date",
            "2026-06-04",
            "--end-date",
            "2026-06-04",
            "--symbol",
            "161725.SZ",
        ]
    )

    assert code == 0
    assert [name for name, _kwargs in calls] == ["fetch", "load"]
    assert calls[0][1]["dataset_name"] == "fund_nav"
    assert calls[1][1]["symbols"] == ["161725.SZ"]
    assert "fetch_fund_nav_parquet status=success rows=1" in capsys.readouterr().out


def test_parser_accepts_export_insight_p1_samples_command() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "--provider",
            "insight",
            "export-insight-p1-samples",
            "--dataset",
            "stock_valuation",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-01",
            "--stock-symbol",
            "000001.SZ",
        ]
    )

    assert args.cmd == "export-insight-p1-samples"
    assert args.provider == "insight"
    assert args.datasets == ["stock_valuation"]
    assert args.stock_symbol == "000001.SZ"
    assert args.fund_symbol == "161725.SZ"


def test_parser_accepts_audit_commands() -> None:
    parser = build_parser()

    show_job = parser.parse_args(
        [
            "--provider",
            "insight",
            "show-job",
            "--dataset",
            "fund_nav",
            "--limit",
            "3",
        ]
    )
    checkpoints = parser.parse_args(
        [
            "--provider",
            "insight",
            "list-checkpoints",
            "--dataset",
            "fund_nav",
            "--partition-key",
            "161725.SZ",
        ]
    )

    assert show_job.cmd == "show-job"
    assert show_job.dataset == "fund_nav"
    assert show_job.limit == 3
    assert checkpoints.cmd == "list-checkpoints"
    assert checkpoints.partition_key == "161725.SZ"


def test_format_audit_rows_renders_compact_json() -> None:
    jobs = _format_job_rows(
        [
            {
                "run_id": 12,
                "job_name": "load_fund_nav_parquet",
                "dataset_name": "fund_nav",
                "status": "success",
                "start_date": date(2026, 6, 4),
                "end_date": date(2026, 6, 4),
                "rows_written": 1,
                "warning_count": 0,
                "request": {"symbols": ["161725.SZ"]},
                "checkpoint": {"rows_written": 1},
            }
        ]
    )
    checkpoints = _format_checkpoint_rows(
        [
            {
                "provider": "insight",
                "dataset_name": "fund_nav",
                "partition_key": "161725.SZ",
                "watermark_date": date(2026, 6, 4),
                "watermark_ts": None,
                "state": {"status": "loaded"},
                "updated_at": None,
            }
        ]
    )

    assert "load_fund_nav_parquet" in jobs
    assert '"symbols": ["161725.SZ"]' in jobs
    assert "161725.SZ" in checkpoints
    assert '"status": "loaded"' in checkpoints
