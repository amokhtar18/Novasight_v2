"""Tenant provisioning saga tests (Task 6.3).

These exercise the real provisioning/de-provisioning logic against the in-memory
SQLite control-plane DB, with fakes for the two non-transactional external systems
(ClickHouse + the Iceberg catalog). They prove:

  * provisioning yields a fully isolated environment (namespace + DB + registry);
  * it is ATOMIC — a failure at any step rolls back everything it created, and only
    what it created (pre-existing resources are never destroyed);
  * de-provisioning purges tables, drops the namespace + database, and removes the row;
  * ISOLATION — a failed provision of tenant B leaves tenant A fully intact.
"""
from __future__ import annotations

from typing import Any

import pytest
from pyiceberg.exceptions import NamespaceAlreadyExistsError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clickhouse import QueryResult
from app.models import Tenant
from app.tenancy.provisioning import (
    ResourceConflictError,
    TenantAlreadyExistsError,
    TenantNotFoundError,
    TenantProvisioner,
)
from app.tenancy.resources import resources_for_slug

pytestmark = pytest.mark.asyncio


class _FakeClickHouse:
    """In-memory ClickHouse: tracks existing databases via DDL + system.databases."""

    def __init__(self) -> None:
        self.databases: set[str] = set()
        self.commands: list[str] = []
        self.fail_on_create: bool = False

    @staticmethod
    def _name(sql: str) -> str:
        return sql.split("`")[1]

    def command(self, sql: str, *, database: str | None = None) -> None:
        self.commands.append(sql)
        upper = sql.upper()
        if upper.startswith("CREATE DATABASE"):
            if self.fail_on_create:
                raise RuntimeError("simulated ClickHouse failure")
            self.databases.add(self._name(sql))
        elif "DROP DATABASE" in upper:
            self.databases.discard(self._name(sql))

    def query(
        self,
        sql: str,
        *,
        database: str,
        parameters: Any = None,
        read_only: bool = True,
    ) -> QueryResult:
        name = (parameters or {}).get("db")
        rows = [(1,)] if name in self.databases else []
        return QueryResult(column_names=["1"], rows=rows)


class _FakeIceberg:
    """In-memory Iceberg catalog admin."""

    def __init__(self) -> None:
        self.namespaces: set[str] = set()
        self.tables: dict[str, list[tuple[str, ...]]] = {}

    def create_namespace(self, namespace: str) -> None:
        if namespace in self.namespaces:
            raise NamespaceAlreadyExistsError(namespace)
        self.namespaces.add(namespace)
        self.tables.setdefault(namespace, [])

    def drop_namespace(self, namespace: str) -> None:
        self.namespaces.discard(namespace)
        self.tables.pop(namespace, None)

    def list_tables(self, namespace: str) -> list[tuple[str, ...]]:
        return list(self.tables.get(namespace, []))

    def purge_table(self, identifier: tuple[str, ...]) -> None:
        ns = identifier[0]
        self.tables.get(ns, []).remove(identifier)


def _provisioner(
    session: AsyncSession, ch: _FakeClickHouse, ice: _FakeIceberg
) -> TenantProvisioner:
    return TenantProvisioner(db=session, ch=ch, iceberg=ice)


async def test_provision_creates_isolated_environment(session: AsyncSession) -> None:
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    res = resources_for_slug("acme")

    tenant = await _provisioner(session, ch, ice).provision(
        slug="acme", name="Acme Corp", admin_email="admin@acme.test"
    )

    # Physical resources exist.
    assert res.iceberg_namespace in ice.namespaces
    assert res.clickhouse_db in ch.databases
    # Registry row persisted with derived (not client-supplied) resource names.
    row = await session.scalar(select(Tenant).where(Tenant.slug == "acme"))
    assert row is not None
    assert row.resource_map.iceberg_namespace == res.iceberg_namespace
    assert row.resource_map.clickhouse_db == res.clickhouse_db
    assert row.resource_map.dbt_schema == res.dbt_schema
    assert [u.email for u in row.users] == ["admin@acme.test"]
    assert tenant.status == "active"


async def test_provision_single_database_when_schema_equals_db(session: AsyncSession) -> None:
    # resources_for_slug gives dbt_schema == clickhouse_db, so exactly ONE create.
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    res = resources_for_slug("acme")
    assert res.dbt_schema == res.clickhouse_db

    await _provisioner(session, ch, ice).provision(
        slug="acme", name="Acme", admin_email="a@acme.test"
    )

    creates = [c for c in ch.commands if c.upper().startswith("CREATE DATABASE")]
    assert len(creates) == 1


async def test_provision_invalid_slug_touches_nothing(session: AsyncSession) -> None:
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    with pytest.raises(ValueError):
        await _provisioner(session, ch, ice).provision(
            slug="Bad-Slug", name="x", admin_email="a@b.test"
        )
    assert ice.namespaces == set()
    assert ch.databases == set()
    assert await session.scalar(select(Tenant)) is None


async def test_provision_duplicate_slug_rejected(session: AsyncSession) -> None:
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    p = _provisioner(session, ch, ice)
    await p.provision(slug="acme", name="Acme", admin_email="a@acme.test")

    with pytest.raises(TenantAlreadyExistsError):
        await p.provision(slug="acme", name="Acme2", admin_email="a2@acme.test")


async def test_rollback_when_clickhouse_fails(session: AsyncSession) -> None:
    """A ClickHouse failure rolls back the already-created Iceberg namespace + registry."""
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    ch.fail_on_create = True
    res = resources_for_slug("acme")

    with pytest.raises(RuntimeError):
        await _provisioner(session, ch, ice).provision(
            slug="acme", name="Acme", admin_email="a@acme.test"
        )

    # Compensation dropped the namespace; nothing persisted.
    assert res.iceberg_namespace not in ice.namespaces
    assert res.clickhouse_db not in ch.databases
    assert await session.scalar(select(Tenant).where(Tenant.slug == "acme")) is None


async def test_preexisting_namespace_fails_closed(session: AsyncSession) -> None:
    """If the namespace already exists out-of-band, fail closed and don't drop it."""
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    res = resources_for_slug("acme")
    ice.namespaces.add(res.iceberg_namespace)  # pre-existing

    with pytest.raises(ResourceConflictError):
        await _provisioner(session, ch, ice).provision(
            slug="acme", name="Acme", admin_email="a@acme.test"
        )

    assert res.iceberg_namespace in ice.namespaces  # not destroyed
    assert ch.databases == set()
    assert await session.scalar(select(Tenant).where(Tenant.slug == "acme")) is None


async def test_preexisting_database_fails_closed_and_rolls_back_namespace(
    session: AsyncSession,
) -> None:
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    res = resources_for_slug("acme")
    ch.databases.add(res.clickhouse_db)  # pre-existing, not registered

    with pytest.raises(ResourceConflictError):
        await _provisioner(session, ch, ice).provision(
            slug="acme", name="Acme", admin_email="a@acme.test"
        )

    # Namespace we created was rolled back; the pre-existing DB was NOT dropped.
    assert res.iceberg_namespace not in ice.namespaces
    assert res.clickhouse_db in ch.databases
    assert await session.scalar(select(Tenant).where(Tenant.slug == "acme")) is None


async def test_failed_provision_leaves_other_tenant_intact(session: AsyncSession) -> None:
    """ISOLATION: a failed provision of B does not touch A's resources or registry."""
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    a_res = resources_for_slug("aaa")
    await _provisioner(session, ch, ice).provision(
        slug="aaa", name="A", admin_email="a@a.test"
    )

    # Now provisioning B fails mid-saga.
    ch.fail_on_create = True
    with pytest.raises(RuntimeError):
        await _provisioner(session, ch, ice).provision(
            slug="bbb", name="B", admin_email="b@b.test"
        )

    # A intact everywhere; B absent everywhere.
    assert a_res.iceberg_namespace in ice.namespaces
    assert a_res.clickhouse_db in ch.databases
    assert await session.scalar(select(Tenant).where(Tenant.slug == "aaa")) is not None
    assert resources_for_slug("bbb").iceberg_namespace not in ice.namespaces
    assert await session.scalar(select(Tenant).where(Tenant.slug == "bbb")) is None


async def test_deprovision_cleans_up_everything(session: AsyncSession) -> None:
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    res = resources_for_slug("acme")
    p = _provisioner(session, ch, ice)
    await p.provision(slug="acme", name="Acme", admin_email="a@acme.test")
    # Simulate a table living in the namespace so purge is exercised.
    ice.tables[res.iceberg_namespace].append((res.iceberg_namespace, "orders"))
    # Detach all instances so deprovision must re-load the tenant + resource_map from
    # the DB — the production path (a fresh request session), where a lazy access
    # would fail without eager loading.
    session.expunge_all()

    await p.deprovision(slug="acme")

    assert res.iceberg_namespace not in ice.namespaces
    assert res.clickhouse_db not in ch.databases
    assert await session.scalar(select(Tenant).where(Tenant.slug == "acme")) is None


async def test_deprovision_unknown_tenant_raises(session: AsyncSession) -> None:
    ch, ice = _FakeClickHouse(), _FakeIceberg()
    with pytest.raises(TenantNotFoundError):
        await _provisioner(session, ch, ice).deprovision(slug="ghost")
