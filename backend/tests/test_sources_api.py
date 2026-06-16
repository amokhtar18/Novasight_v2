"""Tests for the source-connection API (ETL wizard — source step).

Password (HS256) mode + local encryption configured. A fake object store backs the
filesystem connector; a temporary SQLite file backs the SQL connector. Covers CRUD,
secret encryption (never returned), test/preview, superuser gating, and tenant
isolation.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_SECRET = "test-session-secret-do-not-use-in-production-0123456789"
_ENC_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()

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
    "ENCRYPTION__PROVIDER": "local",
    "ENCRYPTION__KEY": _ENC_KEY,
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


class _FakeStore:
    def __init__(self, data: dict[str, bytes]) -> None:
        self._data = data

    async def get_object(self, *, key: str) -> bytes:
        if key not in self._data:
            raise FileNotFoundError(key)
        return self._data[key]


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def fake_store() -> _FakeStore:
    return _FakeStore({"raw/data.csv": b"region,amount\nwest,10\neast,20\n"})


@pytest.fixture()
def client_with_db(session: AsyncSession, fake_store: _FakeStore) -> TestClient:  # type: ignore[return]
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.object_store import get_object_store
    from app.main import app
    from app.tenancy.registry import TenantRegistry, get_tenant_registry

    get_settings.cache_clear()

    async def _fake_db() -> Any:
        yield session

    async def _fake_registry() -> Any:
        return TenantRegistry(session)

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    app.dependency_overrides[get_object_store] = lambda: fake_store

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _auth(roles: list[str] | None = None) -> dict[str, str]:
    payload = {
        "sub": "caller",
        "email": "c@x",
        "tenant": "local",
        "roles": roles or [],
        "typ": "access",
        "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _SESSION_SECRET, algorithm='HS256')}"}


def _sqlite_db(tmp_path: Path) -> str:
    db = tmp_path / "src.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE orders (id INTEGER, region TEXT)"))
        conn.execute(text("INSERT INTO orders VALUES (1, 'west')"))
    engine.dispose()
    return str(db)


SU = ["superuser"]


@pytest.mark.asyncio
async def test_kinds_and_create_requires_superuser(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    assert set(client_with_db.get("/api/v1/sources/kinds", headers=_auth()).json()) == {
        "sql_database",
        "filesystem",
    }
    # create needs superuser
    resp = client_with_db.post(
        "/api/v1/sources",
        headers=_auth([]),
        json={
            "name": "db",
            "kind": "sql_database",
            "config": {"driver": "sqlite", "database": "x"},
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_engines_lists_per_engine_defaults(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    engines = client_with_db.get("/api/v1/sources/engines", headers=_auth()).json()
    by_key = {e["key"]: e for e in engines}
    assert {"postgres", "mysql", "sqlserver", "oracle"} <= set(by_key)
    assert by_key["postgres"]["default_port"] == 5432
    assert by_key["oracle"]["database_label"] == "Service name"
    assert by_key["mysql"]["supports_schemas"] is False


@pytest.mark.asyncio
async def test_create_encrypts_secret_and_hides_it(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    resp = client_with_db.post(
        "/api/v1/sources",
        headers=_auth(SU),
        json={
            "name": "warehouse",
            "kind": "sql_database",
            "config": {"driver": "postgresql", "host": "db", "database": "sales"},
            "secret": {"password": "s3cret"},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["has_secret"] is True
    assert "secret" not in body  # never returned
    assert body["config"]["host"] == "db"


@pytest.mark.asyncio
async def test_sql_test_and_preview(
    client_with_db: TestClient, make_tenant: Any, tmp_path: Path
) -> None:
    await make_tenant("local")
    created = client_with_db.post(
        "/api/v1/sources",
        headers=_auth(SU),
        json={"name": "db", "kind": "sql_database",
              "config": {"driver": "sqlite", "database": _sqlite_db(tmp_path)}},
    ).json()
    sid = created["id"]

    assert client_with_db.post(f"/api/v1/sources/{sid}/test", headers=_auth(SU)).json()["ok"]

    preview = client_with_db.post(
        f"/api/v1/sources/{sid}/preview", headers=_auth(SU), json={"target": "orders"}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["columns"] == ["id", "region"]

    # Introspection: schema → tables → columns (with a suggested target type).
    tables = client_with_db.post(
        f"/api/v1/sources/{sid}/introspect?schema=main", headers=_auth(SU)
    )
    assert tables.status_code == 200, tables.text
    assert "orders" in tables.json()["tables"]

    cols = client_with_db.post(
        f"/api/v1/sources/{sid}/introspect?schema=main&table=orders", headers=_auth(SU)
    ).json()["columns"]
    by_name = {c["name"]: c for c in cols}
    assert set(by_name) == {"id", "region"}
    assert by_name["id"]["suggested_target_type"] == "Int64"
    assert by_name["region"]["suggested_target_type"] == "String"


@pytest.mark.asyncio
async def test_filesystem_preview(client_with_db: TestClient, make_tenant: Any) -> None:
    await make_tenant("local")
    created = client_with_db.post(
        "/api/v1/sources",
        headers=_auth(SU),
        json={"name": "file", "kind": "filesystem",
              "config": {"format": "csv", "key": "raw/data.csv"}},
    ).json()
    preview = client_with_db.post(
        f"/api/v1/sources/{created['id']}/preview", headers=_auth(SU), json={}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["columns"] == ["region", "amount"]


@pytest.mark.asyncio
async def test_list_update_delete_and_isolation(
    client_with_db: TestClient, make_tenant: Any
) -> None:
    await make_tenant("local")
    await make_tenant("other")
    created = client_with_db.post(
        "/api/v1/sources",
        headers=_auth(SU),
        json={"name": "db", "kind": "sql_database",
              "config": {"driver": "sqlite", "database": "x"}},
    ).json()
    sid = created["id"]

    assert len(client_with_db.get("/api/v1/sources", headers=_auth()).json()) == 1

    upd = client_with_db.patch(
        f"/api/v1/sources/{sid}", headers=_auth(SU), json={"name": "renamed"}
    )
    assert upd.json()["name"] == "renamed"

    # A superuser of "other" cannot see/touch local's source.
    other_payload = {
        "sub": "o", "email": "o@x", "tenant": "other", "roles": SU,
        "typ": "access", "exp": int(time.time()) + 3600,
    }
    other_token = jwt.encode(other_payload, _SESSION_SECRET, algorithm="HS256")
    other = {"Authorization": f"Bearer {other_token}"}
    assert client_with_db.get(f"/api/v1/sources/{sid}", headers=other).status_code == 404

    assert client_with_db.delete(f"/api/v1/sources/{sid}", headers=_auth(SU)).status_code == 204
    assert client_with_db.post(f"/api/v1/sources/{sid}/test", headers=_auth(SU)).status_code == 404
