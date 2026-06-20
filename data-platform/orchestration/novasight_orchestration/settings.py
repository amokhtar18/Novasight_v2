"""Env-driven configuration for the orchestration code location.

Golden rule 1: nothing environment- or tenant-specific is hardcoded. Every value is
read from the environment, using the SAME variables the backend and dbt read
(``CLICKHOUSE__*``, ``DBT_SCHEMA``, ``DBT_PHASE1_DATASET_TABLE``) so all three layers
share one source of truth.

Tenancy (golden rule 2): on-prem this is a single tenant, but the tenant's serving
database / dbt schema is resolved here at the boundary (``dbt_schema``) and threaded
into every data-touching asset — never hardcoded, never trusted from a request body.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClickHouseSettings(BaseSettings):
    """ClickHouse connection — identical ``CLICKHOUSE__*`` env the backend uses."""

    model_config = SettingsConfigDict(env_prefix="CLICKHOUSE__", extra="ignore")

    host: str
    port: int = 8123  # HTTP interface; safe-everywhere default, same as the backend.
    user: str = "default"
    password: SecretStr


class IcebergSettings(BaseSettings):
    """Iceberg REST catalog — identical ``ICEBERG__*`` env the backend uses.

    Lets the catalog asset register the tenant's lake (landing) tables so lineage can
    start at Iceberg, one hop before ClickHouse.
    """

    model_config = SettingsConfigDict(env_prefix="ICEBERG__", extra="ignore")

    catalog_uri: str                          # REST catalog (Polaris/Nessie)
    warehouse: str                            # warehouse location / prefix
    catalog_token: SecretStr | None = None    # optional bearer token for REST auth


class CatalogSettings(BaseSettings):
    """OpenMetadata connection for catalog + lineage ingestion (Phase 5.3).

    Uses ``OPENMETADATA__*`` env, mirroring the ``CLICKHOUSE__*`` convention. The two
    fields that point at deployment infrastructure (the server URL and the ingestion
    bot's JWT) have no defaults; the OM *service* names under which our surfaces are
    registered are an environment-identical convention, so they carry safe defaults.
    """

    model_config = SettingsConfigDict(env_prefix="OPENMETADATA__", extra="ignore")

    host_port: str            # OM REST API base, e.g. http://openmetadata:8585/api
    jwt_token: SecretStr      # ingestion-bot JWT used to authenticate to the OM server
    service_name: str = "novasight_clickhouse"  # OM service for ClickHouse (serving + raw)
    iceberg_service_name: str = "novasight_iceberg"   # OM service for the Iceberg lake
    source_service_name: str = "novasight_sources"    # OM service for upstream sources
    semantic_service_name: str = "novasight_semantic"  # OM dashboard service for Cube
    # Cron for the per-tenant catalog refresh schedules (golden rule 1 — configurable,
    # safe default: nightly at 02:00, after the daily pipeline/transform runs settle).
    refresh_cron: str = "0 2 * * *"
    # Python of the isolated OM-SDK venv the catalog code shells out to (the SDK can't
    # share the dagster/dbt venv). Image-internal default; overridable (golden rule 1).
    runner_python: str = "/opt/om-venv/bin/python"


class OrchestrationSettings(BaseSettings):
    """Top-level orchestration settings, composed from the environment."""

    model_config = SettingsConfigDict(extra="ignore")

    # The tenant's dbt schema == its ClickHouse database. Resolved at the boundary
    # (single tenant on-prem); the raw ingestion writes here and dbt builds here.
    dbt_schema: str = Field(alias="DBT_SCHEMA")

    # Physical name of the raw table the ingestion writes and the dbt `phase1` source
    # reads. Same env var the dbt source identifier uses, so the two never drift.
    raw_table: str = Field(default="phase1_regional_sales", alias="DBT_PHASE1_DATASET_TABLE")

    # Physical name of the serving table the downstream serving asset publishes the
    # validated mart into, inside the tenant's ClickHouse database. Configurable
    # (golden rule 1) so a deployment can rename the serving surface without a code
    # change; the safe default is stable across dev / on-prem / cloud.
    serving_table: str = Field(default="serving_regional_sales", alias="SERVING_REGIONAL_SALES_TABLE")

    @property
    def clickhouse(self) -> ClickHouseSettings:
        return ClickHouseSettings()  # type: ignore[call-arg]  # values come from env

    @property
    def iceberg(self) -> IcebergSettings:
        return IcebergSettings()  # type: ignore[call-arg]  # values come from env

    @property
    def catalog(self) -> CatalogSettings:
        return CatalogSettings()  # type: ignore[call-arg]  # values come from env


@lru_cache
def get_settings() -> OrchestrationSettings:
    """Return the process-wide settings, built once from the environment."""
    return OrchestrationSettings()  # type: ignore[call-arg]  # values come from env
