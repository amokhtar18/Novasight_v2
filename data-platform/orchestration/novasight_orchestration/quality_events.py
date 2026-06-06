"""Structured quality-gate failure events for the alerting layer.

When a dbt test (surfaced as a Dagster **asset check** by ``dbt build``) fails, the
quality gate blocks downstream materialization — dbt skips the dependent models, so a
failing upstream check means the mart is never built (dbt-dagster-workflow skill,
step 3: "Quality gate must pass before serving"). This module turns each failing
``AssetCheckResult`` into a stable, serializable :class:`QualityGateFailure` and emits
it on a *decoupled seam* — a structured ``ERROR`` log line tagged with a fixed
``event_type`` — that the reporting/alerting layer consumes later. The alerting layer
does not exist yet; producing a well-defined event now is the contract between the two.

Golden rule 2 (tenancy): every event carries the tenant whose pipeline produced it,
resolved at the boundary from the orchestration settings — never inferred from input.
Golden rule 1: no channels, thresholds, or destinations are hardcoded here. This module
only *produces* the event; *where* and *how* to alert is the alerting layer's config.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from dagster import AssetCheckResult, AssetCheckSeverity

# Stable marker so a downstream consumer can filter quality-gate failures out of the
# event/log stream without parsing free-form text. Part of the event contract — treat
# it as an API and do not change it casually.
QUALITY_GATE_FAILURE_EVENT = "quality_gate_failure"

# Metadata key dagster-dbt attaches to a check result with the number of failing rows.
_FAILED_ROW_COUNT_KEY = "dagster_dbt/failed_row_count"

# JSON-native scalar types; anything else in metadata is stringified so the event
# always round-trips through ``json.dumps`` for whatever transport the alerting layer
# eventually uses.
_JSON_SCALARS = (str, int, float, bool, type(None))


class SupportsError(Protocol):
    """The slice of a logger this module needs (e.g. Dagster's ``context.log``)."""

    def error(self, msg: str) -> Any: ...


@dataclass(frozen=True)
class QualityGateFailure:
    """A single failed data-quality check, in a shape the alerting layer can consume.

    Frozen and built only from values resolved at the orchestration boundary, so an
    emitted event is an immutable, self-contained record of one gate failure.
    """

    tenant: str
    asset_key: str
    check_name: str
    severity: str
    failed_row_count: int | None
    message: str
    detected_at: str
    event_type: str = QUALITY_GATE_FAILURE_EVENT
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        # Sorted keys => stable, diffable output for tests and log scraping.
        return json.dumps(self.to_dict(), sort_keys=True)


def _plain(value: Any) -> Any:
    """Coerce a Dagster ``MetadataValue`` (or plain value) to a JSON-native value."""
    unwrapped = getattr(value, "value", value)
    return unwrapped if isinstance(unwrapped, _JSON_SCALARS) else str(unwrapped)


def build_failure_event(
    result: AssetCheckResult,
    *,
    tenant: str,
    now: datetime | None = None,
) -> QualityGateFailure:
    """Build a structured failure event from a failed asset-check result.

    Pure (no I/O, no Dagster context): ``now`` is injectable so the event is
    deterministic under test. Caller is responsible for only passing failed results.
    """
    metadata = {key: _plain(value) for key, value in (result.metadata or {}).items()}

    raw_failed = metadata.get(_FAILED_ROW_COUNT_KEY)
    failed_row_count = int(raw_failed) if isinstance(raw_failed, (int, float)) else None

    asset_key = result.asset_key.to_user_string() if result.asset_key else ""
    check_name = result.check_name or ""
    severity = (
        result.severity.value
        if isinstance(result.severity, AssetCheckSeverity)
        else str(result.severity)
    )

    rows = "" if failed_row_count is None else f" ({failed_row_count} failing row(s))"
    message = (
        f"Quality gate failed for tenant '{tenant}': check '{check_name}' on asset "
        f"'{asset_key}'{rows}. Downstream materialization is blocked."
    )

    moment = now or datetime.now(timezone.utc)
    return QualityGateFailure(
        tenant=tenant,
        asset_key=asset_key,
        check_name=check_name,
        severity=severity,
        failed_row_count=failed_row_count,
        message=message,
        detected_at=moment.isoformat(),
        metadata=metadata,
    )


def emit_quality_gate_failure(log: SupportsError, failure: QualityGateFailure) -> None:
    """Emit the failure on the alerting seam: one structured, filterable ERROR line.

    Logging (rather than a hard dependency on a not-yet-built alerting service) keeps
    the producer decoupled: the event lands in Dagster's event log, and a future
    sensor/sink filters on ``event_type == quality_gate_failure`` to raise the alert.
    """
    log.error(failure.to_json())
