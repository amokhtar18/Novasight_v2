"""Phase 5.5 — concurrent multi-tenant isolation under load.

Hammers the three data-touching paths — **query**, **AI (NL→SQL)**, and
**report** — with many interleaved requests across two tenants at once, and
asserts **zero cross-tenant leakage**: every response/artifact for a tenant is
derived only from that tenant's own scope, never another's.

The leakage probe is a ClickHouse fake that echoes back the *database it was bound
to* as the data. Because every path binds the connection to
``TenantContext.clickhouse_db`` (resolved server-side), a leak would surface as a
tenant receiving another tenant's database marker. Concurrency is real: tasks are
gathered and each await yields the event loop, so contexts interleave — proving the
scope is per-call state, never shared.

No live infra: ClickHouse, the object store, SMTP, the LLM gateway, and the
semantic layer are all fakes; the control plane runs on a file-backed SQLite DB so
each concurrent task/request gets its own session/connection.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.clickhouse import QueryResult
from app.core.config import Settings
from app.models import Base, Dataset, ReportDefinition, Tenant, TenantResourceMap
from app.schemas.query import Metric, QueryRequest
from app.tenancy import resources_for_slug
from app.tenancy.context import TenantContext

_DEV_STUB_SECRET = "test-dev-stub-secret-do-not-use-in-production"

_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost",
    "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test",
    "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "k",
    "OBJECT_STORE__SECRET_KEY": "s",
    "OBJECT_STORE__BUCKET": "b",
    "ICEBERG__CATALOG_URI": "http://localhost:8181",
    "ICEBERG__WAREHOUSE": "s3://b/warehouse",
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
    "SEED_TENANT__NAME": "Local",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}

_TENANT_A = "alpha"
_TENANT_B = "betacorp"
_FANOUT = 12  # concurrent operations per tenant per path


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return Settings()


def _token(slug: str) -> str:
    payload = {
        "sub": "u",
        "tenant": slug,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, _DEV_STUB_SECRET, algorithm="HS256")


def _ctx(slug: str) -> TenantContext:
    res = resources_for_slug(slug)
    return TenantContext(
        tenant_id=str(uuid.uuid4()),
        iceberg_namespace=res.iceberg_namespace,
        clickhouse_db=res.clickhouse_db,
        dbt_schema=res.dbt_schema,
    )


class _DbMarkerClickHouse:
    """ClickHouse fake whose result echoes the database the query was bound to.

    This is the leakage probe: a query bound to tenant A's database can only ever
    return ``tenant_alpha``. Cross-tenant bleed would surface as the wrong marker.
    Recording is append-only and safe under cooperative asyncio concurrency.
    """

    def __init__(self) -> None:
        self.databases: list[str] = []

    def command(self, sql: str, *, database: str | None = None) -> None:  # pragma: no cover
        raise AssertionError("no path under test issues DDL/writes")

    def query(
        self, sql: str, *, database: str, parameters: Any = None, read_only: bool = True
    ) -> QueryResult:
        self.databases.append(database)
        return QueryResult(column_names=["who"], rows=[(database,)])


class _FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = body

    async def get_object(self, *, key: str) -> bytes:  # pragma: no cover
        return self.objects[key]

    async def list_keys(self, *, prefix: str) -> list[str]:  # pragma: no cover
        return [k for k in self.objects if k.startswith(prefix)]


class _FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[list[str]] = []

    def send(self, *, subject: str, recipients: Any, body: str, attachment: Any = None) -> None:
        self.sent.append(list(recipients))


# ---------------------------------------------------------------------------
# File-backed control-plane DB so each concurrent task gets its own connection
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cp.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed_tenant(session: AsyncSession, slug: str) -> tuple[Tenant, Dataset]:
    res = resources_for_slug(slug)
    tenant = Tenant(
        slug=slug,
        name=slug.title(),
        resource_map=TenantResourceMap(
            iceberg_namespace=res.iceberg_namespace,
            clickhouse_db=res.clickhouse_db,
            dbt_schema=res.dbt_schema,
        ),
    )
    dataset = Dataset(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="orders",
        original_filename="orders.csv",
        object_key=f"{slug}/orders-{uuid.uuid4().hex}.csv",
        content_type="text/csv",
        size_bytes=10,
        # These fixtures stand in for already-materialized datasets, so they are
        # queryable (the query path now rejects non-ingested datasets with 409).
        status="ingested",
    )
    session.add(tenant)
    await session.flush()
    dataset.tenant_id = tenant.id
    session.add(dataset)
    await session.flush()
    return tenant, dataset


# ===========================================================================
# Query path — concurrent HTTP requests across two tenants
# ===========================================================================


@pytest.fixture
def fake_clickhouse() -> _DbMarkerClickHouse:
    return _DbMarkerClickHouse()


@pytest_asyncio.fixture
async def http_app(
    db_factory: async_sessionmaker[AsyncSession], fake_clickhouse: _DbMarkerClickHouse
) -> AsyncIterator[tuple[Any, dict[str, uuid.UUID]]]:
    from app.core.clickhouse import get_clickhouse_client
    from app.core.config import get_settings
    from app.core.db import get_db
    from app.core.object_store import get_object_store
    from app.main import app

    get_settings.cache_clear()

    # Seed both tenants + a dataset each.
    dataset_ids: dict[str, uuid.UUID] = {}
    async with db_factory() as s:
        for slug in (_TENANT_A, _TENANT_B):
            _tenant, dataset = await _seed_tenant(s, slug)
            dataset_ids[slug] = dataset.id
        await s.commit()

    async def _db() -> Any:
        async with db_factory() as session:
            yield session

    def _store() -> Any:
        return _FakeObjectStore()

    def _ch() -> Any:
        return fake_clickhouse

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_object_store] = _store
    app.dependency_overrides[get_clickhouse_client] = _ch
    try:
        yield app, dataset_ids
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_concurrent_query_path_no_leakage(
    http_app: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, dataset_ids = http_app
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def one(slug: str) -> tuple[str, Any]:
            resp = await client.post(
                f"/api/v1/datasets/{dataset_ids[slug]}/query",
                headers={"Authorization": f"Bearer {_token(slug)}"},
                json={"metrics": [{"function": "count"}]},
            )
            return slug, resp

        tasks = [one(slug) for slug in (_TENANT_A, _TENANT_B) for _ in range(_FANOUT)]
        results = await asyncio.gather(*[asyncio.create_task(t) for t in tasks])

    expected = {_TENANT_A: "tenant_alpha", _TENANT_B: "tenant_betacorp"}
    for slug, resp in results:
        assert resp.status_code == 200, resp.text
        rows = resp.json()["rows"]
        # Each tenant only ever sees its OWN database marker — never the other's.
        assert rows == [[expected[slug]]]
        assert expected[_TENANT_B if slug == _TENANT_A else _TENANT_A] not in resp.text


# ===========================================================================
# AI (NL→SQL) path — concurrent service calls across two tenants
# ===========================================================================


def _ai_service(settings: Settings, fake_ch: _DbMarkerClickHouse) -> Any:
    from app.ai.nl_sql.service import NLToSQLService
    from app.services.clickhouse_datasets import ClickHouseDatasetService

    # Gateway returns an unqualified SELECT over the governed serving table; it
    # passes validation for every tenant and executes bound to that tenant's DB.
    gateway = MagicMock()
    gateway.complete = AsyncMock(
        return_value=MagicMock(
            text=f"SELECT region FROM {settings.serving_regional_sales_table}",
            usage={"output_tokens": 1},
        )
    )
    loader = MagicMock()
    loader.render = MagicMock(return_value="")
    semantic = MagicMock()
    semantic.meta = AsyncMock(return_value={"cubes": []})

    return NLToSQLService(
        gateway=gateway,
        prompt_loader=loader,
        semantic_client=semantic,
        ch_dataset_svc=ClickHouseDatasetService(ch=fake_ch, settings=settings),
        settings=settings,
    )


@pytest.mark.asyncio
async def test_concurrent_ai_path_no_leakage(
    settings: Settings, fake_clickhouse: _DbMarkerClickHouse
) -> None:
    svc = _ai_service(settings, fake_clickhouse)
    contexts = {_TENANT_A: _ctx(_TENANT_A), _TENANT_B: _ctx(_TENANT_B)}
    expected = {_TENANT_A: "tenant_alpha", _TENANT_B: "tenant_betacorp"}

    async def one(slug: str) -> tuple[str, Any]:
        _sql, result = await svc.query(contexts[slug], question="how many sales?")
        return slug, result

    tasks = [one(slug) for slug in (_TENANT_A, _TENANT_B) for _ in range(_FANOUT)]
    results = await asyncio.gather(*[asyncio.create_task(t) for t in tasks])

    for slug, result in results:
        # AI execution is bound to the caller's DB — the result carries only that marker.
        assert result.rows == [(expected[slug],)]

    # Every database the AI runner touched was a known tenant DB — nothing else.
    assert set(fake_clickhouse.databases) <= {"tenant_alpha", "tenant_betacorp"}


# ===========================================================================
# Report path — concurrent background renders across two tenants
# ===========================================================================


@pytest.mark.asyncio
async def test_concurrent_report_path_no_leakage(
    db_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    fake_clickhouse: _DbMarkerClickHouse,
) -> None:
    from app.reporting.service import ReportService
    from app.services.clickhouse_datasets import ClickHouseDatasetService

    spec = QueryRequest(metrics=[Metric(function="count", alias="n")]).model_dump()
    owner: dict[uuid.UUID, str] = {}

    async with db_factory() as s:
        for slug in (_TENANT_A, _TENANT_B):
            tenant, dataset = await _seed_tenant(s, slug)
            for _ in range(_FANOUT):
                report = ReportDefinition(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    dataset_id=dataset.id,
                    name=f"{slug}-report",
                    query_spec=spec,
                    schedule="0 6 * * *",
                    recipients=[f"ops@{slug}.test"],
                )
                s.add(report)
                owner[report.id] = slug
        await s.commit()

    store = _FakeObjectStore()
    service = ReportService(
        ch_service=ClickHouseDatasetService(ch=fake_clickhouse, settings=settings),
        object_store=store,
        email_sender=_FakeEmailSender(),
        settings=settings,
    )

    async def run_one(report_id: uuid.UUID) -> tuple[uuid.UUID, Any]:
        async with db_factory() as db:
            return report_id, await service.run_report(db, report_id)

    results = await asyncio.gather(
        *[asyncio.create_task(run_one(rid)) for rid in owner]
    )

    namespace = {_TENANT_A: "alpha", _TENANT_B: "betacorp"}
    for report_id, result in results:
        slug = owner[report_id]
        # Each report's artifact is stored under ITS tenant's namespace only.
        assert result.object_key.startswith(f"{namespace[slug]}/")
        other_ns = namespace[_TENANT_B if slug == _TENANT_A else _TENANT_A]
        assert not result.object_key.startswith(f"{other_ns}/")

    # Every produced object lives under exactly one tenant prefix — none crossed over.
    assert len(store.objects) == 2 * _FANOUT
    for key in store.objects:
        assert key.startswith("alpha/") or key.startswith("betacorp/")
    # Each tenant produced exactly its own count.
    assert sum(k.startswith("alpha/") for k in store.objects) == _FANOUT
    assert sum(k.startswith("betacorp/") for k in store.objects) == _FANOUT
