"""Atomic tenant provisioning and de-provisioning — the control plane (Task 6.3).

Provisioning a tenant creates, as one all-or-nothing unit, the four homes a tenant's
data lives in (see the ``tenancy-isolation`` skill):

1. the **Iceberg namespace** (lake storage, via the REST catalog),
2. the **ClickHouse database** (serving tier),
3. the **dbt target schema** (transform tier) — in this ClickHouse-backed deployment
   the dbt schema *is* a ClickHouse database; ``resources_for_slug`` gives it the same
   name as the serving database, so step 3 is a no-op when they coincide and a second
   ``CREATE DATABASE`` only when an operator has configured them to differ, and
4. the **registry entry** (control-plane Postgres: ``Tenant`` + ``TenantResourceMap``
   + admin ``User``).

## Atomicity without 2PC

These resources span three systems (a REST catalog, ClickHouse, Postgres) with no
distributed transaction. We get all-or-nothing semantics with a **saga**: each
physical resource is created in order and its compensating drop is pushed onto a
stack; the Postgres registry row is written and committed **last**. If any step
fails, the registry transaction is rolled back and every compensation runs in
reverse — and crucially we only ever drop resources THIS call created, so a
pre-existing resource (an inconsistency we fail closed on) is never destroyed.

## Tenancy invariant

Physical names are *derived* from the validated slug via :mod:`app.tenancy.resources`
— never accepted from a caller. Resolution and the registry are the sole authority
for where a tenant's data lives.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import Depends
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchNamespaceError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.clickhouse import ClickHouseClient, get_clickhouse_client
from app.core.clickhouse import quote_ident as _ident
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.iceberg_catalog import load_iceberg_catalog
from app.models import Tenant, TenantResourceMap, User
from app.tenancy.resources import TenantResources, resources_for_slug

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain errors (mapped to HTTP status codes by the router).
# ---------------------------------------------------------------------------


class ProvisioningError(Exception):
    """Base class for provisioning failures."""


class TenantAlreadyExistsError(ProvisioningError):
    """A tenant with the requested slug is already registered."""


class TenantNotFoundError(ProvisioningError):
    """No tenant with the requested slug exists (de-provisioning)."""


class ResourceConflictError(ProvisioningError):
    """A physical resource already exists for a tenant not in the registry.

    Signals an inconsistent state; we fail closed rather than adopt or clobber it.
    """


# ---------------------------------------------------------------------------
# Iceberg namespace administration — a tiny seam over pyiceberg so tests inject a
# fake (mirrors the ``ClickHouseClient`` protocol approach).
# ---------------------------------------------------------------------------


class IcebergAdmin(Protocol):
    """The minimal Iceberg catalog admin surface provisioning needs."""

    def create_namespace(self, namespace: str) -> None:
        """Create a namespace. Raises ``NamespaceAlreadyExistsError`` if it exists."""
        ...

    def drop_namespace(self, namespace: str) -> None:
        """Drop a namespace (must be empty). Tolerates a missing namespace."""
        ...

    def list_tables(self, namespace: str) -> list[tuple[str, ...]]:
        """Return the table identifiers in a namespace (empty if it is gone)."""
        ...

    def purge_table(self, identifier: tuple[str, ...]) -> None:
        """Drop a table and delete its data + metadata files."""
        ...


class PyIcebergAdmin:
    """``IcebergAdmin`` backed by the shared pyiceberg REST catalog from settings."""

    def __init__(self, settings: Settings) -> None:
        # The catalog ``name`` is only a label; the physical catalog is fixed by
        # settings.iceberg.catalog_uri (golden rule 1 — no literals here).
        self._catalog: Any = load_iceberg_catalog(settings, name="provisioning")

    def create_namespace(self, namespace: str) -> None:
        self._catalog.create_namespace(namespace)

    def drop_namespace(self, namespace: str) -> None:
        try:
            self._catalog.drop_namespace(namespace)
        except NoSuchNamespaceError:
            logger.debug("Namespace %r already absent — skipping drop", namespace)

    def list_tables(self, namespace: str) -> list[tuple[str, ...]]:
        try:
            return [tuple(ident) for ident in self._catalog.list_tables(namespace)]
        except NoSuchNamespaceError:
            return []

    def purge_table(self, identifier: tuple[str, ...]) -> None:
        self._catalog.purge_table(identifier)


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------


class TenantProvisioner:
    """Create / tear down a tenant's full isolated environment, atomically."""

    def __init__(
        self,
        db: AsyncSession,
        ch: ClickHouseClient,
        iceberg: IcebergAdmin,
    ) -> None:
        self._db = db
        self._ch = ch
        self._iceberg = iceberg

    # -- ClickHouse helpers (sync; run off the event loop via asyncio.to_thread) --

    def _ch_database_exists(self, name: str) -> bool:
        result = self._ch.query(
            "SELECT 1 FROM system.databases WHERE name = {db:String}",
            database="system",
            parameters={"db": name},
            read_only=True,
        )
        return bool(result.rows)

    def _create_ch_database(self, name: str) -> None:
        """Create a ClickHouse database, failing closed if it already exists."""
        if self._ch_database_exists(name):
            raise ResourceConflictError(
                f"ClickHouse database {name!r} already exists for an unregistered tenant"
            )
        self._ch.command(f"CREATE DATABASE {_ident(name)}")

    def _drop_ch_database(self, name: str) -> None:
        """Drop a ClickHouse database if present (idempotent: compensation + teardown)."""
        self._ch.command(f"DROP DATABASE IF EXISTS {_ident(name)}")

    def _purge_namespace(self, namespace: str) -> None:
        """Purge every table in the namespace, then drop the namespace itself."""
        for identifier in self._iceberg.list_tables(namespace):
            self._iceberg.purge_table(identifier)
        self._iceberg.drop_namespace(namespace)

    # -- public API --

    async def provision(self, *, slug: str, name: str, admin_email: str) -> Tenant:
        """Provision a new tenant atomically. Returns the committed ``Tenant``.

        Raises:
            ValueError: the slug is not a safe identifier fragment.
            TenantAlreadyExistsError: the slug is already registered.
            ResourceConflictError: a physical resource already exists out-of-band.
        """
        resources: TenantResources = resources_for_slug(slug)  # validates the slug

        existing = await self._db.scalar(select(Tenant).where(Tenant.slug == slug))
        if existing is not None:
            raise TenantAlreadyExistsError(f"tenant {slug!r} already exists")

        # Compensations for resources THIS call created, run in reverse on failure.
        compensations: list[Callable[[], None]] = []
        try:
            # 1. Iceberg namespace.
            try:
                await asyncio.to_thread(self._iceberg.create_namespace, resources.iceberg_namespace)
            except NamespaceAlreadyExistsError as exc:
                raise ResourceConflictError(
                    f"Iceberg namespace {resources.iceberg_namespace!r} already exists"
                ) from exc
            compensations.append(
                lambda: self._iceberg.drop_namespace(resources.iceberg_namespace)
            )

            # 2. ClickHouse serving database.
            await asyncio.to_thread(self._create_ch_database, resources.clickhouse_db)
            compensations.append(lambda: self._drop_ch_database(resources.clickhouse_db))

            # 3. dbt target schema — only when distinct from the serving database.
            if resources.dbt_schema != resources.clickhouse_db:
                await asyncio.to_thread(self._create_ch_database, resources.dbt_schema)
                compensations.append(lambda: self._drop_ch_database(resources.dbt_schema))

            # 4. Registry entry — committed last, so it is durable only if every
            #    physical resource above succeeded.
            tenant = Tenant(
                slug=slug,
                name=name,
                status="active",
                resource_map=TenantResourceMap(
                    iceberg_namespace=resources.iceberg_namespace,
                    clickhouse_db=resources.clickhouse_db,
                    dbt_schema=resources.dbt_schema,
                ),
                users=[User(email=admin_email, is_active=True)],
            )
            self._db.add(tenant)
            await self._db.flush()
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            await self._run_compensations(compensations)
            raise

        logger.info(
            "provisioned tenant %r (id=%s): namespace=%s clickhouse_db=%s dbt_schema=%s",
            slug,
            tenant.id,
            resources.iceberg_namespace,
            resources.clickhouse_db,
            resources.dbt_schema,
        )
        return tenant

    async def deprovision(self, *, slug: str) -> None:
        """Tear down a tenant: drop physical resources, then delete the registry row.

        Physical teardown runs first (idempotent drops), so a partial prior failure
        can be retried; the registry row is removed only after. Raises
        ``TenantNotFoundError`` if the slug is not registered.
        """
        # Eager-load resource_map: in a fresh request session a lazy access would
        # fail under async SQLAlchemy (no implicit I/O outside the greenlet).
        tenant = await self._db.scalar(
            select(Tenant)
            .where(Tenant.slug == slug)
            .options(selectinload(Tenant.resource_map))
        )
        if tenant is None:
            raise TenantNotFoundError(f"tenant {slug!r} not found")
        rmap = tenant.resource_map

        # Drop physical resources (idempotent). Lake first, then serving/transform.
        await asyncio.to_thread(self._purge_namespace, rmap.iceberg_namespace)
        await asyncio.to_thread(self._drop_ch_database, rmap.clickhouse_db)
        if rmap.dbt_schema != rmap.clickhouse_db:
            await asyncio.to_thread(self._drop_ch_database, rmap.dbt_schema)

        # Registry last — cascades to resource_map, users, and datasets.
        await self._db.delete(tenant)
        await self._db.commit()

        logger.info("de-provisioned tenant %r (namespace=%s)", slug, rmap.iceberg_namespace)

    @staticmethod
    async def _run_compensations(compensations: list[Callable[[], None]]) -> None:
        """Best-effort reverse-order rollback of created physical resources."""
        for compensate in reversed(compensations):
            try:
                await asyncio.to_thread(compensate)
            except Exception:
                # Never mask the original error — log and continue rolling back.
                logger.exception("compensation step failed during provisioning rollback")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_tenant_provisioner(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    ch: ClickHouseClient = Depends(get_clickhouse_client),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> TenantProvisioner:
    """FastAPI dependency: a ``TenantProvisioner`` wired from request-scoped deps.

    The Iceberg admin is built from settings here; tests override this provider
    (or pass a fake admin to the constructor) to avoid live infrastructure.
    """
    return TenantProvisioner(db=db, ch=ch, iceberg=PyIcebergAdmin(settings))
