from __future__ import annotations

from types import SimpleNamespace

import pytest

from getrich_data_import.orchestration.pipeline import ImportPipeline


class _Tx:
    def __init__(self, engine: "_Engine") -> None:
        self.engine = engine
        self.conn = object()

    def __enter__(self):
        self.engine.events.append(("begin", None))
        return self.conn

    def __exit__(self, exc_type, _exc, _tb):
        self.engine.events.append(("rollback" if exc_type else "commit", None))
        return False


class _Engine:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def begin(self) -> _Tx:
        return _Tx(self)


class _FailingSource:
    name = "test_source"
    provider = "test_source"

    def bar_frames(self, **_kwargs):
        raise RuntimeError("source failed")


def test_import_bars_failure_audit_commits_after_data_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _Engine()
    settings = SimpleNamespace(batch_rows=1000, quality=SimpleNamespace(price_jump_warn_pct=0.2, fail_on_error=True))
    statuses: list[str] = []

    def fake_insert_job_run(_conn, **_kwargs):
        engine.events.append(("insert_job_run", None))
        return 42

    def fake_finish_job_run(_conn, *, status: str, **_kwargs):
        engine.events.append(("finish_job_run", status))
        statuses.append(status)

    monkeypatch.setattr("getrich_data_import.orchestration.pipeline.insert_job_run", fake_insert_job_run)
    monkeypatch.setattr("getrich_data_import.orchestration.pipeline.finish_job_run", fake_finish_job_run)

    pipeline = ImportPipeline(settings=settings, engine=engine, source=_FailingSource())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="source failed"):
        pipeline.import_bars(asset="index", freq="1d", mode="full")

    assert statuses == ["failed"]
    assert engine.events == [
        ("begin", None),
        ("insert_job_run", None),
        ("commit", None),
        ("begin", None),
        ("rollback", None),
        ("begin", None),
        ("finish_job_run", "failed"),
        ("commit", None),
    ]
