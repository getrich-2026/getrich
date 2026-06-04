from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from getrich_data_import.orchestration.pipeline import ImportPipeline


class _Rows:
    def mappings(self):
        return self

    def all(self):
        return [
            {
                "instrument_id": 10,
                "asset": "future",
                "exchange": "CFFEX",
                "symbol": "IF2406.CFFEX",
            }
        ]


class _Conn:
    def execute(self, _sql, _params):
        return _Rows()


class _Source:
    name = "test"

    def future_contract_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "asset": "future",
                    "exchange": "CFFEX",
                    "symbol": "IF2406.CFFEX",
                    "underlying": "IF",
                    "multiplier": "300",
                    "price_tick": "0.2",
                }
            ]
        )


def test_future_contracts_attach_instrument_id_before_upsert(monkeypatch) -> None:
    captured = {}

    def fake_upsert_dataframe(_conn, frame, **kwargs):
        captured["frame"] = frame
        captured["kwargs"] = kwargs
        return len(frame)

    monkeypatch.setattr("getrich_data_import.orchestration.pipeline.upsert_dataframe", fake_upsert_dataframe)
    pipeline = ImportPipeline(
        settings=SimpleNamespace(batch_rows=1000),
        engine=object(),  # type: ignore[arg-type]
        source=_Source(),  # type: ignore[arg-type]
    )

    rows = pipeline._upsert_future_contracts(_Conn())  # type: ignore[arg-type]

    assert rows == 1
    assert captured["kwargs"]["schema"] == "meta"
    assert captured["kwargs"]["table"] == "future_contracts"
    assert captured["frame"].loc[0, "instrument_id"] == 10
    assert captured["frame"].loc[0, "multiplier"] == 300
