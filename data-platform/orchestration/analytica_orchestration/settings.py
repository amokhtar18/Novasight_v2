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


@lru_cache
def get_settings() -> OrchestrationSettings:
    """Return the process-wide settings, built once from the environment."""
    return OrchestrationSettings()  # type: ignore[call-arg]  # values come from env
