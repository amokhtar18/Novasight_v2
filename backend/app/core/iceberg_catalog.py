"""Shared construction of a pyiceberg REST catalog from ``Settings``.

Both the ingestion pipeline (``app.ingestion.csv_iceberg``) and the ClickHouse
registration service (``app.services.clickhouse_datasets``) need to talk to the
same Iceberg REST catalog, built the same way. That construction lives here once
so the catalog properties — all sourced from ``Settings`` per golden rule 1 — are
never duplicated or drift apart.

No literal hosts, URIs, bucket names, or credentials appear in this module: every
value comes from ``settings.iceberg.*`` and ``settings.object_store.*``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    from pyiceberg.catalog import Catalog


def build_catalog_properties(settings: Settings) -> dict[str, str]:
    """Return a pyiceberg ``load_catalog`` properties dict built from settings.

    All values come from ``settings.iceberg.*`` and ``settings.object_store.*``;
    no literal URIs, credentials, or bucket names appear here.
    """
    os_cfg = settings.object_store
    iceberg_cfg = settings.iceberg

    props: dict[str, str] = {
        "type": "rest",
        "uri": iceberg_cfg.catalog_uri,
        "warehouse": iceberg_cfg.warehouse,
        # Route pyiceberg file I/O through fsspec (s3fs) so it uses the same
        # S3-compatible endpoint as the rest of the platform.
        "py-io-impl": "pyiceberg.io.fsspec.FsspecFileIO",
        "s3.endpoint": os_cfg.endpoint_url,
        "s3.access-key-id": os_cfg.access_key.get_secret_value(),
        "s3.secret-access-key": os_cfg.secret_key.get_secret_value(),
        "s3.region": os_cfg.region,
    }
    if iceberg_cfg.catalog_token:
        props["credential"] = iceberg_cfg.catalog_token.get_secret_value()
    return props


def load_iceberg_catalog(settings: Settings, *, name: str) -> Catalog:
    """Load a pyiceberg REST ``Catalog`` configured entirely from ``Settings``.

    ``name`` is the catalog label (we pass the tenant's Iceberg namespace); it
    has no effect on which physical catalog is reached — that is fixed by
    ``settings.iceberg.catalog_uri``.
    """
    from pyiceberg.catalog import load_catalog

    # pyiceberg is untyped (ignore_missing_imports), so the returned Catalog is Any.
    return load_catalog(name=name, **build_catalog_properties(settings))
