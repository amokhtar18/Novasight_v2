"""Tests for GET /api/v1/health.

Dependencies (Postgres, Redis) are mocked so no live services are needed.
Two scenarios are verified:
  (a) all components healthy → HTTP 200, status "healthy", each component "up"
  (b) one component down → HTTP 503, status "degraded", the down component reported
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# ── Provide minimal env vars so Settings() can instantiate without a real .env ──
_FAKE_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost",
    "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test",
    "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "test",
    "OBJECT_STORE__SECRET_KEY": "test",
    "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181",
    "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost",
    "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai",
    "AI__MODEL": "gpt-4o",
    "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts",
    "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__OIDC_ISSUER": "http://localhost/",
    "AUTH__OIDC_AUDIENCE": "analytica",
    "AUTH__JWKS_URL": "http://localhost/.well-known/jwks.json",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake environment variables before any import of Settings."""
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def client() -> TestClient:
    """Build a TestClient with settings and DB/Redis overrides applied."""
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.redis import get_redis
    from app.main import app

    # Clear lru_cache so that patched env vars are picked up.
    get_settings.cache_clear()

    # Mock DB session: execute() returns a truthy result, commit/rollback are no-ops.
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def _fake_db() -> Any:
        yield mock_session

    # Mock Redis: ping() succeeds.
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    async def _fake_redis() -> Any:
        return mock_redis

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_redis] = _fake_redis

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# (a) All components healthy → 200
# ─────────────────────────────────────────────────────────────────────────────

def test_health_all_up(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    names = {c["name"]: c["status"] for c in body["components"]}
    assert names["postgres"] == "up"
    assert names["redis"] == "up"


# ─────────────────────────────────────────────────────────────────────────────
# (b) Postgres down → 503, postgres reported "down", redis still "up"
# ─────────────────────────────────────────────────────────────────────────────

def test_health_postgres_down(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.redis import get_redis
    from app.main import app

    get_settings.cache_clear()

    # DB session where execute() raises.
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def _broken_db() -> Any:
        yield mock_session

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    async def _good_redis() -> Any:
        return mock_redis

    app.dependency_overrides[get_db] = _broken_db
    app.dependency_overrides[get_redis] = _good_redis

    with TestClient(app, raise_server_exceptions=True) as c:
        response = c.get("/api/v1/health")

    app.dependency_overrides.clear()
    get_settings.cache_clear()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    names = {comp["name"]: comp["status"] for comp in body["components"]}
    assert names["postgres"] == "down"
    assert names["redis"] == "up"


# ─────────────────────────────────────────────────────────────────────────────
# (c) Redis down → 503, redis reported "down", postgres still "up"
# ─────────────────────────────────────────────────────────────────────────────

def test_health_redis_down(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.redis import get_redis
    from app.main import app

    get_settings.cache_clear()

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def _good_db() -> Any:
        yield mock_session

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(side_effect=Exception("connection refused"))

    async def _broken_redis() -> Any:
        return mock_redis

    app.dependency_overrides[get_db] = _good_db
    app.dependency_overrides[get_redis] = _broken_redis

    with TestClient(app, raise_server_exceptions=True) as c:
        response = c.get("/api/v1/health")

    app.dependency_overrides.clear()
    get_settings.cache_clear()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    names = {comp["name"]: comp["status"] for comp in body["components"]}
    assert names["postgres"] == "up"
    assert names["redis"] == "down"
