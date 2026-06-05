"""Dataset profiler — builds a compact, PII-aware profile for suggestions.

The profile is fed into the LLM prompt for sub-feature (b).  It captures
enough schema and statistical information for the LLM to propose useful
chart specs, while staying compact and non-sensitive.

## PII-aware design

- Sample categorical values are capped at ``_MAX_SAMPLE_VALUES`` per column
  (default 5).  This limits exposure of potentially identifying values.
- Free-text columns (high cardinality or very long values) are excluded from
  the sample entirely — we note "high-cardinality" instead.
- Column names are included as-is (they are schema metadata, not data values).
- No row-level free-text content reaches the prompt.

## Queries

All profiling queries run through ``ClickHouseDatasetService.run_read_only_query``
which binds the connection to ``ctx.clickhouse_db`` and enforces read-only at
the ClickHouse level.  The dataset is pre-validated by ``DatasetService.
get_for_tenant`` before this module is called, so the table reference is
already tenant-scoped.

All SQL identifiers (database name, table name) are backtick-quoted and are
derived from server-resolved context / validated UUIDs — never from caller input.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.clickhouse_datasets import ClickHouseDatasetService, _ident
from app.tenancy.context import TenantContext

if TYPE_CHECKING:
    from app.models.dataset import Dataset

logger = logging.getLogger(__name__)

# Profiling caps
_MAX_SAMPLE_VALUES = 5        # per-column categorical samples
_MAX_SAMPLE_VALUE_LEN = 64    # truncate very long string values
_HIGH_CARDINALITY_THRESHOLD = 100  # distinct values above this → no samples
_MAX_PROFILE_COLUMNS = 50     # cap columns profiled (2 queries each) on wide tables
_NUMERIC_TYPE_PREFIXES = (
    "Int", "UInt", "Float", "Decimal", "int", "uint", "float", "double",
)


@dataclass
class ColumnProfile:
    """Profile of a single dataset column."""

    name: str
    type: str
    row_count: int = 0
    null_count: int = 0
    distinct_count: int | None = None
    # Numeric stats (None for non-numeric columns)
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    # Categorical sample values (capped at _MAX_SAMPLE_VALUES)
    sample_values: list[str] = field(default_factory=list)
    is_high_cardinality: bool = False


@dataclass
class DatasetProfile:
    """Full profile of a dataset, ready for prompt injection."""

    dataset_id: str
    table_name: str
    total_rows: int
    columns: list[ColumnProfile]

    def to_prompt_text(self) -> str:
        """Serialise the profile to a compact text for the suggestions prompt.

        Format is readable by both humans and LLMs; keeps tokens low.
        """
        lines: list[str] = [
            f"Dataset ID: {self.dataset_id}",
            f"Table: {self.table_name}",
            f"Total rows: {self.total_rows}",
            "",
            "Columns:",
        ]
        for col in self.columns:
            lines.append(f"  - {col.name} ({col.type})")
            if col.distinct_count is not None:
                lines.append(f"      distinct_values: {col.distinct_count}")
            if col.is_high_cardinality:
                lines.append("      sample_values: [high-cardinality, no samples]")
            elif col.sample_values:
                samples = ", ".join(repr(v) for v in col.sample_values)
                lines.append(f"      sample_values: [{samples}]")
            if col.min_value is not None:
                lines.append(
                    f"      stats: min={col.min_value}, max={col.max_value}, "
                    f"avg={col.avg_value}"
                )
        return "\n".join(lines)


class DatasetProfiler:
    """Build a compact, PII-aware profile of a tenant dataset.

    All queries run through the tenant-scoped ``ClickHouseDatasetService``
    (read-only, bound to ``ctx.clickhouse_db``).

    Args:
        ch_svc: The tenant-scoped ClickHouse dataset service.
    """

    def __init__(self, ch_svc: ClickHouseDatasetService) -> None:
        self._ch = ch_svc

    def profile(self, ctx: TenantContext, dataset: Dataset) -> DatasetProfile:
        """Build and return a ``DatasetProfile`` for ``dataset``.

        Runs three sets of queries (all read-only, tenant-scoped):
        1. DESCRIBE — column names and types.
        2. COUNT(*) — total rows.
        3. Per-column cardinality + stats (numeric min/max/avg, categorical samples).

        The ``dataset`` must already have been validated by
        ``DatasetService.get_for_tenant`` before this method is called.

        Args:
            ctx: Server-resolved tenant context.
            dataset: The tenant-owned dataset to profile.

        Returns:
            A ``DatasetProfile`` ready for prompt injection.
        """
        from app.ingestion.csv_iceberg import _table_name_for_dataset  # local import avoids cycle

        table_name = _table_name_for_dataset(dataset.id)
        db_ident = _ident(ctx.clickhouse_db)
        tbl_ident = _ident(table_name)

        logger.info(
            "DatasetProfiler.profile: tenant_id=%r dataset_id=%r table=%r",
            ctx.tenant_id,
            str(dataset.id),
            table_name,
        )

        # ------------------------------------------------------------------
        # 1. DESCRIBE — column names + types
        # ------------------------------------------------------------------
        describe_result = self._ch.run_read_only_query(
            ctx,
            f"DESCRIBE {db_ident}.{tbl_ident}",
        )
        # DESCRIBE returns rows: [name, type, default_type, default_expression, comment, ...]
        all_columns: list[tuple[str, str]] = [
            (str(row[0]), str(row[1])) for row in describe_result.rows
        ]
        # Cap the number of columns profiled: each column costs 2 ClickHouse
        # round-trips (distinct-count + stats/sample), so a very wide table would
        # otherwise fan out into hundreds of synchronous queries. Suggestions only
        # need a representative subset.
        raw_columns = all_columns[:_MAX_PROFILE_COLUMNS]
        if len(all_columns) > _MAX_PROFILE_COLUMNS:
            logger.info(
                "DatasetProfiler.profile: tenant_id=%r dataset_id=%r — profiling "
                "first %d of %d columns",
                ctx.tenant_id,
                str(dataset.id),
                _MAX_PROFILE_COLUMNS,
                len(all_columns),
            )

        # ------------------------------------------------------------------
        # 2. COUNT(*) — total rows
        # ------------------------------------------------------------------
        count_result = self._ch.run_read_only_query(
            ctx,
            f"SELECT count(*) FROM {db_ident}.{tbl_ident}",  # noqa: S608
        )
        total_rows = int(count_result.rows[0][0]) if count_result.rows else 0

        # ------------------------------------------------------------------
        # 3. Per-column stats
        # ------------------------------------------------------------------
        column_profiles: list[ColumnProfile] = []
        for col_name, col_type in raw_columns:
            col_profile = self._profile_column(
                ctx,
                db_ident=db_ident,
                tbl_ident=tbl_ident,
                col_name=col_name,
                col_type=col_type,
                total_rows=total_rows,
            )
            column_profiles.append(col_profile)

        return DatasetProfile(
            dataset_id=str(dataset.id),
            table_name=table_name,
            total_rows=total_rows,
            columns=column_profiles,
        )

    def _profile_column(
        self,
        ctx: TenantContext,
        *,
        db_ident: str,
        tbl_ident: str,
        col_name: str,
        col_type: str,
        total_rows: int,
    ) -> ColumnProfile:
        """Build a ColumnProfile for one column.

        Uses safe, backtick-quoted column identifiers.
        """
        col_ident = _ident(col_name)
        profile = ColumnProfile(name=col_name, type=col_type, row_count=total_rows)

        is_numeric = any(col_type.startswith(p) for p in _NUMERIC_TYPE_PREFIXES)

        # Distinct count (needed for cardinality decision)
        try:
            distinct_result = self._ch.run_read_only_query(
                ctx,
                f"SELECT uniq({col_ident}) FROM {db_ident}.{tbl_ident}",  # noqa: S608
            )
            profile.distinct_count = (
                int(distinct_result.rows[0][0]) if distinct_result.rows else None
            )
        except Exception:
            logger.debug(
                "DatasetProfiler: could not get distinct count for column %r",
                col_name,
                exc_info=True,
            )

        if is_numeric:
            # Numeric stats: min, max, avg
            try:
                stats_result = self._ch.run_read_only_query(
                    ctx,
                    f"SELECT min({col_ident}), max({col_ident}), avg({col_ident}) "  # noqa: S608
                    f"FROM {db_ident}.{tbl_ident}",
                )
                if stats_result.rows:
                    row = stats_result.rows[0]
                    profile.min_value = _safe_float(row[0])
                    profile.max_value = _safe_float(row[1])
                    profile.avg_value = _safe_float(row[2])
            except Exception:
                logger.debug(
                    "DatasetProfiler: could not get numeric stats for column %r",
                    col_name,
                    exc_info=True,
                )
        else:
            # Categorical column: sample values (if not high-cardinality)
            distinct = profile.distinct_count or 0
            if distinct > _HIGH_CARDINALITY_THRESHOLD:
                profile.is_high_cardinality = True
            else:
                try:
                    sample_result = self._ch.run_read_only_query(
                        ctx,
                        f"SELECT DISTINCT {col_ident} FROM {db_ident}.{tbl_ident} "  # noqa: S608
                        f"LIMIT {_MAX_SAMPLE_VALUES}",
                    )
                    samples: list[str] = []
                    for sample_row in sample_result.rows:
                        val = str(sample_row[0])
                        if len(val) > _MAX_SAMPLE_VALUE_LEN:
                            val = val[:_MAX_SAMPLE_VALUE_LEN] + "..."
                        samples.append(val)
                    profile.sample_values = samples
                except Exception:
                    logger.debug(
                        "DatasetProfiler: could not get sample values for column %r",
                        col_name,
                        exc_info=True,
                    )

        return profile


def _safe_float(value: object) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
