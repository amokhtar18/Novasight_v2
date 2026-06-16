"""Generic Arrow→Iceberg writer (#3) — the shared landing-table write step.

Extracted from ``csv_iceberg.py`` so every ETL source (CSV upload, SQL database,
filesystem) lands in the tenant's Iceberg namespace through one code path. Given an
Arrow table it creates-or-overwrites the named table in ``ctx.iceberg_namespace`` via
the REST catalog (idempotent: ``overwrite`` disposition + deterministic identifier).

Tenant isolation: the namespace comes verbatim from ``TenantContext`` (server-resolved,
never a caller value). All infra config comes from ``Settings`` (golden rule 1) — no
literal hosts, URIs, buckets, or credentials here.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.core.crypto import KmsProvider, build_kms_provider
from app.core.iceberg_catalog import build_catalog_properties
from app.ingestion.encryption import encrypt_arrow_columns
from app.tenancy.context import TenantContext

if TYPE_CHECKING:
    import pyarrow as pa

logger = logging.getLogger(__name__)


def write_arrow_table(
    *,
    ctx: TenantContext,
    settings: Settings,
    table_name: str,
    arrow_table: pa.Table,
    sensitive_columns: list[str] | None = None,
    provider: KmsProvider | None = None,
    disposition: str = "overwrite",
    primary_key: list[str] | None = None,
) -> int:
    """Write ``arrow_table`` to ``table_name`` in the tenant's Iceberg namespace.

    ``disposition`` (#7) selects how the data lands into an **existing** table:
    ``overwrite`` (replace), ``append`` / ``incremental`` (add rows), or ``merge``
    (upsert by ``primary_key``). A *new* table is always created from the batch
    (initial load), regardless of disposition. Columns named in ``sensitive_columns``
    are encrypted before the write (fail closed). Returns the number of rows written.
    """
    from pyiceberg.catalog import load_catalog
    from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchTableError

    if sensitive_columns:
        provider = provider or build_kms_provider(settings)
        arrow_table = encrypt_arrow_columns(arrow_table, sensitive_columns, provider)

    # Catalog config entirely from Settings — no literals, no files.
    catalog = load_catalog(
        name=ctx.iceberg_namespace,
        **build_catalog_properties(settings),
    )

    namespace = ctx.iceberg_namespace
    identifier = (namespace, table_name)

    try:
        catalog.create_namespace(namespace)
    except NamespaceAlreadyExistsError:
        logger.debug("Namespace %r already exists — skipping create", namespace)

    try:
        iceberg_table = catalog.load_table(identifier)
    except NoSuchTableError:
        # First load: create from the batch's schema and seed it (all dispositions
        # collapse to a full write into the new table).
        iceberg_table = catalog.create_table(identifier=identifier, schema=arrow_table.schema)
        iceberg_table.overwrite(arrow_table)
    else:
        _apply_disposition(iceberg_table, arrow_table, disposition, primary_key or [])

    rows = int(arrow_table.num_rows)
    logger.info(
        "Iceberg table written: %s.%s (%d rows, %s)", namespace, table_name, rows, disposition
    )
    return rows


def _apply_disposition(
    iceberg_table: object, arrow_table: pa.Table, disposition: str, primary_key: list[str]
) -> None:
    """Route an existing-table write to the matching pyiceberg operation."""
    if disposition in ("append", "incremental"):
        iceberg_table.append(arrow_table)  # type: ignore[attr-defined]
    elif disposition == "merge":
        if not primary_key:
            raise ValueError("merge disposition requires a primary_key")
        # Upsert by the key columns: existing rows with a matching key are updated,
        # new keys inserted (SCD type 1).
        iceberg_table.upsert(arrow_table, join_cols=primary_key)  # type: ignore[attr-defined]
    else:  # overwrite (default)
        iceberg_table.overwrite(arrow_table)  # type: ignore[attr-defined]
