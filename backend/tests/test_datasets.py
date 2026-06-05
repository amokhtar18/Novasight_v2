"""Tests for the dataset upload + listing endpoints (Task 1.1).

Runs in dev-stub (HS256) auth mode and against the in-memory SQLite session.
The object store is replaced with an in-memory fake so no MinIO/S3 is needed,
while still asserting the raw object lands under the tenant's prefix.

Coverage:
  (a) upload returns a dataset id and the object lands under the tenant prefix.
  (b) non-CSV files are rejected (415).
  (c) oversized files are rejected (413) using the settings-driven limit.
  (d) unauthenticated upload/list are rejected (401).
  (e) ISOLATION: tenant A cannot list tenant B's datasets, and keys never cross
      tenant prefixes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clickhouse import QueryResult
from app.tenancy import resources_for_slug

_DEV_STUB_SECRET = "test-dev-stub-secret-do-not-use-in-production"

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
    "AUTH__OIDC_ISSUER": "",
    "AUTH__OIDC_AUDIENCE": "",
    "AUTH__JWKS_URL": "",
    "AUTH__DEV_STUB": "true",
    "AUTH__DEV_STUB_SECRET": _DEV_STUB_SECRET,
    "AUTH__TENANT_CLAIM": "tenant",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


def _make_token(tenant_slug: str, *, exp_offset: int = 3600) -> str:
    """Sign an HS256 dev-stub JWT carrying the tenant claim."""
    payload = {
        "sub": "user-sub-123",
        "email": "user@example.com",
        "tenant": tenant_slug,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, _DEV_STUB_SECRET, algorithm="HS256")


class _FakeObjectStore:
    """In-memory stand-in for the S3 object store."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    async def get_object(self, *, key: str) -> bytes:
        body, _ = self.objects[key]
        return body

    async def list_keys(self, *, prefix: str) -> list[str]:
        return [k for k in self.objects if k.startswith(prefix)]


@dataclass
class _FakeClickHouse:
    """In-memory ClickHouseClient recording each query for endpoint assertions."""

    rows: list[tuple[Any, ...]] = field(default_factory=list)
    column_names: list[str] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)

    def command(self, sql: str, *, database: str | None = None) -> None:  # pragma: no cover
        raise AssertionError("the query endpoint must never issue DDL/writes")

    def query(
        self,
        sql: str,
        *,
        database: str,
        parameters: Any = None,
        read_only: bool = True,
    ) -> QueryResult:
        self.queries.append(
            {
                "sql": sql,
                "database": database,
                "read_only": read_only,
                "parameters": dict(parameters) if parameters else {},
            }
        )
        return QueryResult(column_names=list(self.column_names), rows=list(self.rows))


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def fake_store() -> _FakeObjectStore:
    return _FakeObjectStore()


@pytest.fixture()
def fake_clickhouse() -> _FakeClickHouse:
    return _FakeClickHouse()


@pytest.fixture()
def client_with_db(
    session: AsyncSession,
    fake_store: _FakeObjectStore,
    fake_clickhouse: _FakeClickHouse,
) -> TestClient:  # type: ignore[return]
    """TestClient with the in-memory DB session and fake object store wired in."""
    from app.core.clickhouse import get_clickhouse_client
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

    def _fake_object_store() -> Any:
        return fake_store

    def _fake_clickhouse_client() -> Any:
        return fake_clickhouse

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_tenant_registry] = _fake_registry
    app.dependency_overrides[get_object_store] = _fake_object_store
    app.dependency_overrides[get_clickhouse_client] = _fake_clickhouse_client

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c  # type: ignore[misc]

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _upload(
    client: TestClient,
    token: str,
    *,
    name: str = "data.csv",
    body: bytes = b"a,b\n1,2\n",
) -> Any:
    return client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, body, "text/csv")},
    )


# ---------------------------------------------------------------------------
# (a) Upload returns an id and stores the object under the tenant prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_returns_id_and_stores_under_tenant_prefix(
    client_with_db: TestClient,
    fake_store: _FakeObjectStore,
    make_tenant: Any,
) -> None:
    await make_tenant("acmecorp")
    token = _make_token("acmecorp")

    resp = _upload(client_with_db, token, name="sales.csv")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    assert body["original_filename"] == "sales.csv"
    assert body["status"] == "uploaded"
    assert body["size_bytes"] > 0

    # The raw object landed under the tenant's namespace prefix.
    namespace = resources_for_slug("acmecorp").iceberg_namespace
    keys = list(fake_store.objects)
    assert len(keys) == 1
    assert keys[0].startswith(f"{namespace}/")
    assert body["id"] in keys[0]


# ---------------------------------------------------------------------------
# (b) Non-CSV is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_non_csv(
    client_with_db: TestClient,
    fake_store: _FakeObjectStore,
    make_tenant: Any,
) -> None:
    await make_tenant("acmecorp")
    token = _make_token("acmecorp")

    resp = _upload(client_with_db, token, name="notes.txt")

    assert resp.status_code == 415, resp.text
    assert fake_store.objects == {}  # nothing stored on rejection


# ---------------------------------------------------------------------------
# (c) Oversized upload is rejected using the settings-driven limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(
    monkeypatch: pytest.MonkeyPatch,
    client_with_db: TestClient,
    fake_store: _FakeObjectStore,
    make_tenant: Any,
) -> None:
    # Tighten the limit to 1 MB and send ~2 MB.
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    from app.core.config import get_settings

    get_settings.cache_clear()

    await make_tenant("acmecorp")
    token = _make_token("acmecorp")

    oversized = b"a,b\n" + b"1,2\n" * (600_000)  # > 1 MB
    resp = _upload(client_with_db, token, body=oversized)

    assert resp.status_code == 413, resp.text
    assert fake_store.objects == {}


# ---------------------------------------------------------------------------
# (d) Unauthenticated access is rejected
# ---------------------------------------------------------------------------


def test_upload_requires_auth(client_with_db: TestClient) -> None:
    resp = client_with_db.post(
        "/api/v1/datasets/upload",
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 401


def test_list_requires_auth(client_with_db: TestClient) -> None:
    resp = client_with_db.get("/api/v1/datasets")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# (e) ISOLATION: tenant A cannot list tenant B's datasets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_cannot_list_other_tenants_datasets(
    client_with_db: TestClient,
    fake_store: _FakeObjectStore,
    make_tenant: Any,
) -> None:
    await make_tenant("tenant_alpha")
    await make_tenant("tenant_beta")
    token_a = _make_token("tenant_alpha")
    token_b = _make_token("tenant_beta")

    # A uploads one dataset; B uploads two.
    assert _upload(client_with_db, token_a, name="a1.csv").status_code == 201
    assert _upload(client_with_db, token_b, name="b1.csv").status_code == 201
    assert _upload(client_with_db, token_b, name="b2.csv").status_code == 201

    list_a = client_with_db.get(
        "/api/v1/datasets", headers={"Authorization": f"Bearer {token_a}"}
    )
    list_b = client_with_db.get(
        "/api/v1/datasets", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert list_a.status_code == 200
    assert list_b.status_code == 200

    names_a = {d["original_filename"] for d in list_a.json()}
    names_b = {d["original_filename"] for d in list_b.json()}

    # Each tenant sees only its own datasets — no cross-tenant leakage.
    assert names_a == {"a1.csv"}
    assert names_b == {"b1.csv", "b2.csv"}
    assert names_a.isdisjoint(names_b)

    # And the object keys are partitioned by tenant namespace.
    ns_a = resources_for_slug("tenant_alpha").iceberg_namespace
    ns_b = resources_for_slug("tenant_beta").iceberg_namespace
    for key in fake_store.objects:
        assert key.startswith(f"{ns_a}/") or key.startswith(f"{ns_b}/")
    assert any(k.startswith(f"{ns_a}/") for k in fake_store.objects)
    assert any(k.startswith(f"{ns_b}/") for k in fake_store.objects)


# ---------------------------------------------------------------------------
# Task 1.4 — POST /datasets/{id}/query
# ---------------------------------------------------------------------------


def _query(client: TestClient, token: str, dataset_id: str, body: dict[str, Any]) -> Any:
    return client.post(
        f"/api/v1/datasets/{dataset_id}/query",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


@pytest.mark.asyncio
async def test_query_returns_aggregated_data(
    client_with_db: TestClient,
    make_tenant: Any,
    fake_clickhouse: _FakeClickHouse,
) -> None:
    fake_clickhouse.column_names = ["region", "total"]
    fake_clickhouse.rows = [("eu", 30), ("us", 12)]

    await make_tenant("acmecorp")
    token = _make_token("acmecorp")
    dataset_id = _upload(client_with_db, token, name="sales.csv").json()["id"]

    resp = _query(
        client_with_db,
        token,
        dataset_id,
        {
            "dimensions": ["region"],
            "metrics": [{"function": "sum", "column": "amount", "alias": "total"}],
            "filters": [{"column": "active", "op": "=", "value": True}],
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["region", "total"]
    assert body["rows"] == [["eu", 30], ["us", 12]]
    assert body["row_count"] == 2

    # The query ran read-only, bound to the tenant's own ClickHouse database.
    assert len(fake_clickhouse.queries) == 1
    query = fake_clickhouse.queries[0]
    assert query["database"] == resources_for_slug("acmecorp").clickhouse_db
    assert query["read_only"] is True
    assert query["parameters"] == {"p0": True}


def test_query_requires_auth(client_with_db: TestClient) -> None:
    resp = client_with_db.post(
        "/api/v1/datasets/00000000-0000-0000-0000-000000000000/query",
        json={"metrics": [{"function": "count"}]},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_query_unknown_dataset_returns_404(
    client_with_db: TestClient,
    make_tenant: Any,
    fake_clickhouse: _FakeClickHouse,
) -> None:
    await make_tenant("acmecorp")
    token = _make_token("acmecorp")

    resp = _query(
        client_with_db,
        token,
        "00000000-0000-0000-0000-000000000000",
        {"metrics": [{"function": "count"}]},
    )

    assert resp.status_code == 404, resp.text
    # Fail closed before touching ClickHouse.
    assert fake_clickhouse.queries == []


@pytest.mark.asyncio
async def test_query_rejects_invalid_identifier(
    client_with_db: TestClient,
    make_tenant: Any,
    fake_clickhouse: _FakeClickHouse,
) -> None:
    await make_tenant("acmecorp")
    token = _make_token("acmecorp")
    dataset_id = _upload(client_with_db, token).json()["id"]

    # A column with SQL metacharacters never reaches the builder — 422 at the schema.
    resp = _query(
        client_with_db,
        token,
        dataset_id,
        {"dimensions": ["amount; DROP TABLE x"], "metrics": [{"function": "count"}]},
    )

    assert resp.status_code == 422, resp.text
    assert fake_clickhouse.queries == []


# ---------------------------------------------------------------------------
# ISOLATION: tenant A cannot query tenant B's dataset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_cannot_query_other_tenants_dataset(
    client_with_db: TestClient,
    make_tenant: Any,
    fake_clickhouse: _FakeClickHouse,
) -> None:
    await make_tenant("tenant_alpha")
    await make_tenant("tenant_beta")
    token_a = _make_token("tenant_alpha")
    token_b = _make_token("tenant_beta")

    # A owns the dataset; B knows (or guesses) its id and tries to query it.
    dataset_id = _upload(client_with_db, token_a, name="a.csv").json()["id"]

    resp = _query(
        client_with_db,
        token_b,
        dataset_id,
        {"metrics": [{"function": "count"}]},
    )

    # Indistinguishable from "not found" — no existence leak, and nothing ran.
    assert resp.status_code == 404, resp.text
    assert fake_clickhouse.queries == []

    # Sanity: the owner can query it, and the query targets A's database only.
    ok = _query(
        client_with_db,
        token_a,
        dataset_id,
        {"metrics": [{"function": "count"}]},
    )
    assert ok.status_code == 200, ok.text
    assert fake_clickhouse.queries[0]["database"] == (
        resources_for_slug("tenant_alpha").clickhouse_db
    )
