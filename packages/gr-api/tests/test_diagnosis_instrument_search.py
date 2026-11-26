"""持仓诊断标的模糊搜索接口测试（GET /v1/diagnosis/instruments/search）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from gr_api.auth import create_token
from gr_api.config import load_api_settings
from gr_api.deps import get_db
from gr_api.main import create_app
from gr_api.services import diagnosis as svc
from gr_tools.config import Environment


HEADERS = (
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
)
UID = "11111111-1111-4111-8111-111111111111"


def _fake_db(rows: list[dict[str, Any]]) -> tuple[MagicMock, AsyncMock]:
    cursor = AsyncMock()
    cursor.fetchall.return_value = rows
    db = MagicMock()
    db.cursor.return_value.__aenter__.return_value = cursor
    return db, cursor


@pytest.mark.anyio
async def test_search_instruments_blank_query_skips_database() -> None:
    db, cursor = _fake_db([])
    assert await svc.search_instruments(db, "") == []
    assert await svc.search_instruments(db, "   \t  ") == []
    cursor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_search_instruments_prefix_fuzzy_exchange_hint_and_like_escape() -> None:
    sample_rows = [
        {
            "instrument_id": 30698,
            "symbol": "600000.SH",
            "code": "600000",
            "name": "浦发银行",
            "exchange": "XSHG",
        },
        {
            "instrument_id": 30697,
            "symbol": "600004.SH",
            "code": "600004",
            "name": "白云机场",
            "exchange": "XSHG",
        },
    ]
    db, cursor = _fake_db(sample_rows)
    res = await svc.search_instruments(db, " 6 ", limit=10, as_of=date(2026, 11, 26))
    assert len(res) == 2
    assert res[0]["symbol"] == "600000.SH"
    assert res[0]["code"] == "600000"
    sql, params = cursor.execute.call_args.args
    assert "FROM meta.instruments" in sql
    assert "status = 'active'" in sql
    assert "ESCAPE '\\'" in sql
    assert params == (
        ["XSHE", "XSHG"],
        date(2026, 11, 26),
        "%6%",
        "%6%",
        "6",
        "6",
        "6%",
        "6%",
        10,
    )

    # 支持 SH/SZ 交易所前缀输入（如 sh600519）
    db_sh, cur_sh = _fake_db([])
    await svc.search_instruments(db_sh, "sh60051", limit=15, as_of=date(2026, 11, 26))
    _, sh_params = cur_sh.execute.call_args.args
    assert sh_params[0] == ["XSHG"]
    assert sh_params[2] == "%60051%"
    assert sh_params[6] == "60051%"
    assert sh_params[8] == 15

    # LIKE 通配符 % / _ / \ 必须转义，避免通配注入
    db_esc, cur_esc = _fake_db([])
    await svc.search_instruments(db_esc, "60%_\\1", limit=100, as_of=date(2026, 11, 26))
    _, esc_params = cur_esc.execute.call_args.args
    assert esc_params[2] == "%60\\%\\_\\\\1%"
    assert esc_params[6] == "60\\%\\_\\\\1%"
    assert esc_params[8] == 50  # 上限保护


def _make_client(tmp_path: Path, *, v1_only: bool = True) -> TestClient:
    settings = load_api_settings(
        Environment(
            tmp_path,
            {
                "JWT_SECRET": "fixture-key",
                "GETRICH_V1_DIAGNOSIS_ONLY": "true" if v1_only else "false",
            },
        )
    )
    app = create_app(settings)

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def test_http_search_instruments_auth_validation_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, v1_only=True)
    token = create_token({"sub": UID}, "fixture-key", expires_in=60)
    auth = {"Authorization": f"Bearer {token}"}

    # 1) 未登录 401 + 4 项安全头
    unauth = client.get("/v1/diagnosis/instruments/search?q=6")
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "unauthorized"
    assert all(h in unauth.headers for h in HEADERS)

    # 2) 已登录正常搜索返回标准信封 + Cache-Control + 4 项安全头
    mock_search = AsyncMock(
        return_value=[
            {
                "instrument_id": 30322,
                "symbol": "600519.SH",
                "code": "600519",
                "name": "贵州茅台",
                "exchange": "XSHG",
            }
        ]
    )
    monkeypatch.setattr(svc, "search_instruments", mock_search)
    ok_resp = client.get("/v1/diagnosis/instruments/search?q=60051&limit=10", headers=auth)
    assert ok_resp.status_code == 200
    assert ok_resp.headers["Cache-Control"] == "private, no-store"
    assert all(h in ok_resp.headers for h in HEADERS)
    body = ok_resp.json()
    assert body["code"] == 0
    assert body["data"]["items"] == [
        {
            "instrument_id": 30322,
            "symbol": "600519.SH",
            "code": "600519",
            "name": "贵州茅台",
            "exchange": "XSHG",
        }
    ]
    mock_search.assert_awaited_once()
    assert mock_search.call_args.args[1] == "60051"
    assert mock_search.call_args.kwargs == {"limit": 10}

    # 3) limit 越界与超长 q 返回诊断 422 契约
    bad_limit = client.get("/v1/diagnosis/instruments/search?q=6&limit=51", headers=auth)
    assert bad_limit.status_code == 422
    assert bad_limit.json()["error"]["code"] == "validation_error"
    assert all(h in bad_limit.headers for h in HEADERS)

    bad_q = client.get(f"/v1/diagnosis/instruments/search?q={'6' * 65}", headers=auth)
    assert bad_q.status_code == 422
    assert bad_q.json()["error"]["code"] == "validation_error"
