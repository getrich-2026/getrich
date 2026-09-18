"""应用配置角色与原 worker 配置行为回归。"""

from __future__ import annotations

import os
import subprocess
import sys

from gr_api.config import WorkerConfig


def test_from_env_defaults(monkeypatch: object) -> None:
    """Defaults: backend=inproc, broker=localhost, flower=localhost:5555."""
    # 模型不读 dotenv；隔离进程变量后验证默认值。
    monkeypatch.setattr(os, "environ", {})  # type: ignore[attr-defined]
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "inproc"
    assert cfg.broker_url == "redis://localhost:6379/0"
    assert cfg.result_backend == "redis://localhost:6379/0"
    assert cfg.flower_url == "http://localhost:5555"


def test_from_env_celery_backend(monkeypatch: object) -> None:
    """Switching to celery with a non-default broker URL is reflected."""
    monkeypatch.setattr(  # type: ignore[attr-defined]
        os,
        "environ",
        {
            "GETRICH_WORKER_BACKEND": "celery",
            "GETRICH_BROKER_URL": "redis://broker.internal:6379/3",
            "GETRICH_RESULT_BACKEND": "redis://broker.internal:6379/4",
        },
    )
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "celery"
    assert cfg.broker_url == "redis://broker.internal:6379/3"
    assert cfg.result_backend == "redis://broker.internal:6379/4"


def test_from_env_invalid_backend_falls_back(monkeypatch: object) -> None:
    """Unknown backend values fall back to ``inproc`` with a warning."""
    monkeypatch.setattr(os, "environ", {"GETRICH_WORKER_BACKEND": "rabbitmq"})  # type: ignore[attr-defined]
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "inproc"


def test_from_env_backend_case_insensitive(monkeypatch: object) -> None:
    """``CELERY`` (uppercase) normalises to ``celery``."""
    monkeypatch.setattr(os, "environ", {"GETRICH_WORKER_BACKEND": "CELERY"})  # type: ignore[attr-defined]
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "celery"


def test_model_imports_do_not_load_dotenv_or_create_files(tmp_path):
    (tmp_path / ".env").write_text("CONFIG_IMPORT_SENTINEL=secret\nLOG_LEVEL=invalid\n")
    home = tmp_path / "empty-home"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import gr_tools.config
import gr_data.config
import gr_data.config.pipeline
import gr_api.config
assert 'CONFIG_IMPORT_SENTINEL' not in os.environ
assert not hasattr(gr_data.config, 'Settings')
assert not hasattr(gr_data.config, 'load_settings')
""",
        ],
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "GETRICH_ROOT": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    assert not home.exists()
    assert list(tmp_path.iterdir()) == [tmp_path / ".env"]


def test_asgi_entry_loads_configuration_only_when_requested(tmp_path):
    (tmp_path / ".env").write_text("LOG_LEVEL=invalid\n")
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import gr_api.main
import gr_tools.config
assert 'app' not in vars(gr_api.main)

from pathlib import Path
from uvicorn.importer import import_from_string
environment = gr_tools.config.Environment(Path.cwd(), {})
settings = gr_api.config.load_api_settings(environment)
gr_api.main.load_api_settings = lambda: settings
app = import_from_string('gr_api.main:app')
assert app.state.settings is settings
assert import_from_string('gr_api.main:app') is app
""",
        ],
        env={**os.environ, "GETRICH_ROOT": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr


def test_pg_only_and_worker_ignore_unused_configuration(tmp_path):
    from gr_api.config import load_worker_settings
    from gr_data.config import load_postgres
    from gr_tools.config import Environment

    environment = Environment(
        tmp_path,
        {
            "STRICT_MODE": "true",
            "PG_PASSWORD": "fixture-secret",
            "CLICKHOUSE_PORT": "invalid",
            "WEB_PORT": "invalid",
            "ENABLE_INSIGHT": "true",
            "GETRICH_WORKER_BACKEND": "inproc",
            "BACKTEST_ARTIFACT_DIR": str(tmp_path),
        },
    )
    assert load_postgres(environment).database == "getrich"
    assert load_worker_settings(environment).worker.backend == "inproc"


def test_api_instances_keep_jwt_cors_and_admin_configuration_separate(tmp_path):
    from dataclasses import replace

    from fastapi import Depends
    from fastapi.testclient import TestClient
    from gr_api.auth import create_token
    from gr_api.config import load_api_settings
    from gr_api.deps import require_user
    from gr_api.main import create_app
    from gr_tools.config import Environment

    config = load_api_settings(Environment(tmp_path, {"PG_PASSWORD": "fixture-password"}))
    clients = []
    for key, origin in (
        ("first-key", "https://first.example"),
        ("second-key", "https://second.example"),
    ):
        app = create_app(
            replace(config, web=replace(config.web, jwt_secret=key, cors_origins=(origin,)))
        )

        @app.get("/config-user")
        async def user(user_id: str = Depends(require_user)):
            return {"user": user_id}

        clients.append(TestClient(app))  # 不启用 lifespan，不连接数据库。
    token = create_token({"sub": "user-1"}, "first-key", expires_in=60)
    headers = {"Authorization": f"Bearer {token}", "Origin": "https://first.example"}
    first = clients[0].get("/config-user", headers=headers)
    second = clients[1].get("/config-user", headers=headers)
    assert first.status_code == 200
    assert first.headers["access-control-allow-origin"] == "https://first.example"
    assert second.status_code == 401
    assert "access-control-allow-origin" not in second.headers
    for response in (first, second):
        for header in (
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "Referrer-Policy",
        ):
            assert header in response.headers


def test_config_representations_hide_credentials(tmp_path):
    from gr_api.config import load_api_settings
    from gr_data.config import InsightConfig, RiceQuantConfig
    from gr_tools.config import Environment

    secret = "never-print-this-secret"
    env = Environment(
        tmp_path,
        {
            "PG_PASSWORD": secret,
            "JWT_SECRET": secret,
            "GETRICH_BROKER_URL": f"redis://:{secret}@localhost/0",
        },
    )
    assert secret not in repr(load_api_settings(env))
    assert secret not in repr(InsightConfig(True, "user", secret))
    assert secret not in repr(RiceQuantConfig(True, secret))


def test_payment_secret_from_dotenv_reaches_request_without_global_install(tmp_path, monkeypatch):
    import hashlib
    import hmac
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient
    from gr_api.config import load_api_settings
    from gr_api.deps import get_db
    from gr_api.main import create_app
    from gr_api.services import payment
    from gr_tools.config import load_environment

    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET", raising=False)
    (tmp_path / ".env").write_text("PAYMENT_WEBHOOK_SECRET=isolated-secret\n")
    config = load_api_settings(load_environment(root=tmp_path, environ={}))
    assert "PAYMENT_WEBHOOK_SECRET" not in os.environ
    app = create_app(config)
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(payment, "handle_webhook", AsyncMock(return_value={"processed": True}))
    client = TestClient(app)
    body = (
        b'{"order_id":"ORD_1","payment_ref":"PAY_1","status":"success",'
        b'"amount":99,"payment_source":"wechat"}'
    )
    assert client.post("/v1/webhooks/payment", content=body).status_code == 401
    signature = hmac.new(b"isolated-secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/v1/webhooks/payment", content=body, headers={"X-Webhook-Signature": signature}
    )
    assert response.status_code == 200
    for header in (
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
    ):
        assert header in response.headers
