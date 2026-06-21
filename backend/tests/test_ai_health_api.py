"""Tests for the AI provider health probe (#12) — GET /api/v1/ai/health.

The probe is superuser-gated and *soft-fails*: a bad/expired key (provider 401)
returns HTTP 200 with ``ok=False`` and a safe message — never the key. We override
the LLM gateway with a fake so no real provider is called.
"""
from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway.provider import LLMProviderError, LLMResponse

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"
SU = ["superuser"]

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
    "AUTH__SESSION_SECRET": _SESSION_SECRET,
    "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


class _OkGateway:
    """Fake gateway whose probe completes successfully."""

    async def complete(
        self, request: Any, *, ctx: Any, model_override: str | None = None
    ) -> LLMResponse:
        return LLMResponse(
            text="ok", model="probe-model", usage={"input_tokens": 5, "output_tokens": 1}
        )


class _FailGateway:
    """Fake gateway whose probe raises a provider error (e.g. a bad key)."""

    def __init__(self, status_code: int | None) -> None:
        self._status = status_code

    async def complete(
        self, request: Any, *, ctx: Any, model_override: str | None = None
    ) -> LLMResponse:
        raise LLMProviderError("boom", provider="test", status_code=self._status)


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def client_with_db(session: AsyncSession) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth(tenant: str = "local", roles: list[str] | None = None) -> dict[str, str]:
    payload = {
        "sub": "caller", "email": "c@x", "tenant": tenant,
        "roles": roles or [], "typ": "access", "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


def _override_gateway(gateway: Any) -> None:
    from app.ai.gateway import get_llm_gateway
    from app.main import app

    app.dependency_overrides[get_llm_gateway] = lambda: gateway


@pytest.mark.asyncio
async def test_health_requires_superuser(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    _override_gateway(_OkGateway())
    assert client_with_db.get("/api/v1/ai/health", headers=_auth()).status_code == 403


@pytest.mark.asyncio
async def test_health_ok(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    _override_gateway(_OkGateway())
    resp = client_with_db.get("/api/v1/ai/health", headers=_auth("local", SU))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["model"] == "probe-model"
    assert isinstance(body["latency_ms"], int)


@pytest.mark.asyncio
async def test_health_soft_fails_on_bad_key(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    _override_gateway(_FailGateway(status_code=401))
    resp = client_with_db.get("/api/v1/ai/health", headers=_auth("local", SU))
    # Soft-fail: a bad key is a 200 payload, not a request error.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "API key" in body["detail"]
    # The key/raw error is never echoed.
    assert "boom" not in body["detail"]
