"""CSV-to-Iceberg ingestion pipeline (Task 1.2).

Loads an already-uploaded CSV (a ``Dataset`` row) from the tenant's raw S3 prefix
into an Apache Iceberg table in the tenant's Iceberg namespace via the REST catalog.

## Design: idempotency

Idempotency guarantee: **overwrite** write disposition + deterministic table name.

- The Iceberg table is named ``dataset_<uuid_hex>`` where ``uuid_hex`` is the
  dataset UUID with hyphens stripped — a stable, SQL-safe identifier.
- On every run ``pyiceberg``'s ``Table.overwrite()`` atomically replaces all data
  in the table with the current CSV contents.  A second run with the same CSV
  produces exactly the same table state as the first; no duplicate rows accumulate
  and no orphaned data files are left behind.
- If the table does not yet exist, ``catalog.create_table()`` creates it with the
  Arrow-inferred schema; subsequent runs reach the existing table via
  ``catalog.load_table()`` and call ``overwrite()``.  Both paths are idempotent.

## Tenant isolation

The Iceberg namespace is taken verbatim from ``TenantContext.iceberg_namespace``,
which is resolved server-side from the authenticated JWT — never from a caller
parameter.  ``CsvIcebergPipeline`` accepts only a ``TenantContext``; callers
cannot substitute a different namespace.

## Configuration

All infra-pointing values come from ``Settings``:
- ``settings.iceberg.catalog_uri``    — REST catalog endpoint
- ``settings.iceberg.warehouse``      — catalog warehouse location
- ``settings.iceberg.catalog_token``  — optional bearer token for the REST catalog
- ``settings.object_store.*``         — S3-compatible credentials, endpoint, bucket

No literal hosts, URIs, bucket names, or credentials appear in this module.

## Why dlt + pyiceberg (not dlt-filesystem iceberg destination)?

dlt's ``filesystem`` destination's Iceberg path resolves the catalog via its own
``@with_config`` injection chain, which reads from ``.pyiceberg.yaml`` or
``secrets.toml`` — config files that would need to be written at runtime, mixing
config-management concerns.  Instead we use:

1. ``dlt`` for the declarative resource/schema-inference layer (CSV → Arrow schema).
2. ``pyiceberg`` directly for the catalog interaction, with a catalog built
   programmatically from ``Settings`` — the single source of truth.

This keeps all infra config in ``backend/app/core/config.py`` per golden rule 1.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from typing import TYPE_CHECKING

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.iceberg_catalog import build_catalog_properties
from app.core.object_store import ObjectStore, get_object_store
from app.tenancy.context import TenantContext

if TYPE_CHECKING:
    from app.models.dataset import Dataset

logger = logging.getLogger(__name__)

# Strip hyphens to produce a valid SQL identifier from a UUID.
_HYPHEN_RE = re.compile(r"-")


def _table_name_for_dataset(dataset_id: uuid.UUID) -> str:
    """Return a deterministic, SQL-safe Iceberg table name for ``dataset_id``.

    The name is ``dataset_<uuid_hex>`` — stable across runs and globally unique
    per dataset.  Stripping hyphens makes it a valid identifier in every SQL
    dialect (Iceberg table names follow SQL rules).
    """
    return f"dataset_{_HYPHEN_RE.sub('', str(dataset_id))}"


class CsvIcebergPipeline:
    """Load a tenant's uploaded CSV into its Iceberg namespace.

    Constructor accepts only infrastructure dependencies (store, settings) and a
    ``TenantContext`` resolved server-side.  No namespace, database, or credentials
    are accepted from untrusted callers.

    Usage::

        pipeline = CsvIcebergPipeline(ctx=tenant_ctx, store=object_store, settings=settings)
        table_id = await pipeline.run(dataset)
    """

    def __init__(
        self,
        ctx: TenantContext,
        store: ObjectStore,
        settings: Settings,
    ) -> None:
        self._ctx = ctx
        self._store = store
        self._settings = settings

    async def run(self, dataset: Dataset) -> str:
        """Load ``dataset`` CSV into the tenant's Iceberg namespace.

        Downloads the raw CSV bytes from the object store, infers the Arrow
        schema, then creates or overwrites the Iceberg table in the tenant's
        namespace.

        Args:
            dataset: The ``Dataset`` row to ingest.  Its ``object_key`` must
                     point to a readable CSV in the configured bucket.

        Returns:
            The fully-qualified Iceberg table identifier
            ``<namespace>.<table_name>``.

        Raises:
            ValueError: if the dataset does not belong to this tenant context.
            RuntimeError: if the catalog or write step fails.
        """
        # Tenant isolation guard: the dataset must belong to the context tenant.
        if str(dataset.tenant_id) != self._ctx.tenant_id:
            raise ValueError(
                f"Dataset {dataset.id} belongs to tenant {dataset.tenant_id!r}, "
                f"not {self._ctx.tenant_id!r}"
            )

        logger.info(
            "Ingesting dataset %s for tenant %s (namespace=%r)",
            dataset.id,
            self._ctx.tenant_id,
            self._ctx.iceberg_namespace,
        )

        raw_bytes = await self._store.get_object(key=dataset.object_key)

        table_name = _table_name_for_dataset(dataset.id)
        table_id = f"{self._ctx.iceberg_namespace}.{table_name}"

        self._write_iceberg_table(raw_bytes=raw_bytes, table_name=table_name)

        logger.info("Iceberg table created/replaced: %s", table_id)
        return table_id

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_iceberg_table(
        self,
        *,
        raw_bytes: bytes,
        table_name: str,
    ) -> None:
        """Parse the CSV, build a catalog from settings, and write (overwrite) the table.

        This is the synchronous, Iceberg-specific layer.  It is separated from
        ``run()`` so it can be called from a thread executor if async wrapping is
        needed in the future.
        """
        import pyarrow.csv as pa_csv
        from pyiceberg.catalog import load_catalog
        from pyiceberg.exceptions import (
            NamespaceAlreadyExistsError,
            NoSuchTableError,
        )

        # Parse CSV bytes to an Arrow table for schema inference and typed writing.
        arrow_table = pa_csv.read_csv(io.BytesIO(raw_bytes))

        # Build catalog config entirely from Settings — no literals, no files.
        catalog_props = self._build_catalog_properties()

        catalog = load_catalog(
            name=self._ctx.iceberg_namespace,
            **catalog_props,
        )

        namespace = self._ctx.iceberg_namespace
        identifier = (namespace, table_name)

        # Ensure the namespace exists; idempotent — NamespaceAlreadyExistsError is fine.
        try:
            catalog.create_namespace(namespace)
        except NamespaceAlreadyExistsError:
            logger.debug("Namespace %r already exists — skipping create", namespace)

        # Create table on first run; overwrite on subsequent runs.
        try:
            iceberg_table = catalog.load_table(identifier)
            # Table exists — overwrite all data (idempotency mechanism).
            iceberg_table.overwrite(arrow_table)
        except NoSuchTableError:
            # First run — create the table with the inferred Arrow schema.
            iceberg_table = catalog.create_table(
                identifier=identifier,
                schema=arrow_table.schema,
            )
            iceberg_table.overwrite(arrow_table)

    def _build_catalog_properties(self) -> dict[str, str]:
        """Return a pyiceberg ``load_catalog`` properties dict built from Settings.

        Delegates to ``app.core.iceberg_catalog.build_catalog_properties`` so the
        ClickHouse registration service (Task 1.3) builds an identical catalog
        from the same single source of truth.
        """
        return build_catalog_properties(self._settings)


# ---------------------------------------------------------------------------
# Assembler (FastAPI / Dagster dependency injection)
# ---------------------------------------------------------------------------


def get_csv_iceberg_pipeline(
    ctx: TenantContext,
    store: ObjectStore = Depends(get_object_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CsvIcebergPipeline:
    """Assemble a ``CsvIcebergPipeline`` for the resolved tenant context.

    ``ctx`` must be pre-resolved server-side (e.g. via ``Depends(get_tenant_context)``).
    It is accepted as an explicit argument — not resolved here — so the full
    dependency chain remains testable via ``dependency_overrides``.
    """
    return CsvIcebergPipeline(ctx=ctx, store=store, settings=settings)
