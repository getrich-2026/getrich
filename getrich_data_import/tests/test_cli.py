from __future__ import annotations

from getrich_data_import.catalog import get_dataset_spec
from getrich_data_import.cli import _format_dataset_specs, build_parser


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
