"""Tests for the serving-load asset (``serving.py``).

Exercise the contract without a live warehouse, in the same style as the gate tests:
feed the load logic a *fake* ClickHouse client that records the SQL it is sent and
answers ``count()`` queries from canned table sizes. We assert three things the task
calls for:

* **good data**  -> the integrity check passes (serving mirrors the validated mart);
* **bad data**   -> the check fails (empty or row-count mismatch from a partial load);
* **tenant scoping** -> every statement is qualified with the tenant's ClickHouse
  database resolved at the boundary, and nothing else.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from analytica_orchestration.serving import (
    MART_TABLE,
    SERVING_CHECK_NAME,
    build_serving_check,
    promote_mart,
    run_serving_load,
)


class _FakeClient:
    """Records executed SQL and answers ``count()`` from per-table canned sizes."""

    def __init__(self, *, mart_table: str, serving_table: str, mart_rows: int, serving_rows: int) -> None:
        self.commands: list[str] = []
        self.closed = False
        self._mart_table = mart_table
        self._serving_table = serving_table
        self._mart_rows = mart_rows
        self._serving_rows = serving_rows

    def command(self, cmd: str, *args: Any, **kwargs: Any) -> Any:
        self.commands.append(cmd)
        if cmd.lstrip().upper().startswith("SELECT COUNT"):
            # The two count queries are distinguishable by their (distinct) table names.
            if self._serving_table in cmd:
                return self._serving_rows
            if self._mart_table in cmd:
                return self._mart_rows
        return None

    def close(self) -> None:
        self.closed = True


def _settings(*, dbt_schema: str = "tenant_local", serving_table: str = "serving_regional_sales") -> Any:
    """A minimal stand-in for OrchestrationSettings (only the fields the load reads)."""
    return SimpleNamespace(dbt_schema=dbt_schema, serving_table=serving_table)


# --- promote_mart: the physical load ---------------------------------------------


def test_promote_creates_serving_from_validated_mart() -> None:
    client = _FakeClient(
        mart_table=MART_TABLE, serving_table="serving_regional_sales",
        mart_rows=4, serving_rows=4,
    )

    serving_rows, mart_rows = promote_mart(
        client, database="tenant_local", mart_table=MART_TABLE,
        serving_table="serving_regional_sales",
    )

    assert (serving_rows, mart_rows) == (4, 4)
    # The serving table is built from the mart with an atomic, re-runnable replace.
    replace = next(c for c in client.commands if "CREATE OR REPLACE TABLE" in c)
    assert "serving_regional_sales" in replace
    assert f"SELECT * FROM `tenant_local`.`{MART_TABLE}`" in replace
    # And the tenant database is ensured first.
    assert client.commands[0] == "CREATE DATABASE IF NOT EXISTS `tenant_local`"


def test_promote_is_tenant_scoped() -> None:
    # Every statement must reference the resolved tenant database and no other.
    client_a = _FakeClient(
        mart_table=MART_TABLE, serving_table="srv", mart_rows=1, serving_rows=1,
    )
    promote_mart(client_a, database="tenant_a", mart_table=MART_TABLE, serving_table="srv")
    assert all("`tenant_a`" in c for c in client_a.commands)
    assert not any("tenant_b" in c for c in client_a.commands)

    # The same code routes a different tenant to its own database — no leakage.
    client_b = _FakeClient(
        mart_table=MART_TABLE, serving_table="srv", mart_rows=1, serving_rows=1,
    )
    promote_mart(client_b, database="tenant_b", mart_table=MART_TABLE, serving_table="srv")
    assert all("`tenant_b`" in c for c in client_b.commands)
    assert not any("tenant_a" in c for c in client_b.commands)


# --- build_serving_check: good vs bad data ---------------------------------------


def test_check_passes_on_good_data() -> None:
    result = build_serving_check(serving_rows=4, mart_rows=4)

    assert result.passed
    assert result.check_name == SERVING_CHECK_NAME
    assert result.metadata["serving_rows"].value == 4
    assert result.metadata["mart_rows"].value == 4


def test_check_fails_on_row_count_mismatch() -> None:
    # A partial load: fewer rows reached the serving table than the validated mart.
    result = build_serving_check(serving_rows=3, mart_rows=4)

    assert not result.passed
    assert "mismatch" in (result.description or "").lower()


def test_check_fails_on_empty_serving_table() -> None:
    # The mart was validated and non-empty, but nothing landed in serving.
    result = build_serving_check(serving_rows=0, mart_rows=4)

    assert not result.passed


# --- run_serving_load: the asset body, end to end --------------------------------


def test_run_serving_load_good_data_materializes_passing_check() -> None:
    captured: dict[str, _FakeClient] = {}

    def fake_connect(settings: Any) -> _FakeClient:
        client = _FakeClient(
            mart_table=MART_TABLE, serving_table=settings.serving_table,
            mart_rows=3, serving_rows=3,
        )
        captured["client"] = client
        return client

    result = run_serving_load(_settings(), connect=fake_connect)

    # One passing integrity check is attached to the materialization.
    assert len(result.check_results) == 1
    assert result.check_results[0].passed
    # Metadata names the tenant-scoped serving table and source mart.
    assert result.metadata["serving_table"].value == "tenant_local.serving_regional_sales"
    assert result.metadata["source_mart"].value == f"tenant_local.{MART_TABLE}"
    assert result.metadata["rows_served"].value == 3
    # The client was closed even on the happy path.
    assert captured["client"].closed


def test_run_serving_load_bad_data_materializes_failing_check() -> None:
    def fake_connect(settings: Any) -> _FakeClient:
        # Partial load: serving ended up empty despite a non-empty validated mart.
        return _FakeClient(
            mart_table=MART_TABLE, serving_table=settings.serving_table,
            mart_rows=5, serving_rows=0,
        )

    result = run_serving_load(_settings(), connect=fake_connect)

    assert len(result.check_results) == 1
    assert not result.check_results[0].passed


def test_run_serving_load_is_tenant_scoped() -> None:
    seen: dict[str, _FakeClient] = {}

    def fake_connect(settings: Any) -> _FakeClient:
        client = _FakeClient(
            mart_table=MART_TABLE, serving_table=settings.serving_table,
            mart_rows=2, serving_rows=2,
        )
        seen["client"] = client
        return client

    result = run_serving_load(_settings(dbt_schema="acme"), connect=fake_connect)

    assert result.metadata["serving_table"].value.startswith("acme.")
    assert all("`acme`" in c for c in seen["client"].commands if c.startswith(("CREATE", "SELECT")))
