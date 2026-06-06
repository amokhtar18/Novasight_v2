# KPI alerts (Phase 5.2)

NovaSight evaluates per-tenant KPI thresholds on a schedule and fires an alert
(email or webhook) when a metric breaches. It runs on the same Dramatiq worker as
reporting, is tenant-scoped, and de-duplicates so a breach alerts **exactly once**.

## Pieces

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Registry row | [`app/models/kpi_threshold.py`](../backend/app/models/kpi_threshold.py) | Per-tenant KPI: dataset, query, comparator+threshold, schedule, channel, breach state. |
| Evaluator | [`app/reporting/alerts/evaluator.py`](../backend/app/reporting/alerts/evaluator.py) | Pure: extract the KPI value and decide breach vs threshold. |
| Channels | [`app/reporting/alerts/channels.py`](../backend/app/reporting/alerts/channels.py) | `AlertChannel` protocol + email (shared SMTP) and webhook (HTTP POST). |
| Service | [`app/reporting/alerts/service.py`](../backend/app/reporting/alerts/service.py) | Tenant-scoped evaluate + exactly-once breach state. |
| Actor | [`app/reporting/alerts/actors.py`](../backend/app/reporting/alerts/actors.py) | `evaluate_kpi` Dramatiq actor. |
| Dispatcher | [`app/reporting/alerts/schedule.py`](../backend/app/reporting/alerts/schedule.py) | periodiq heartbeat → enqueue due KPIs. |

## How a KPI runs

1. **periodiq** fires `dispatch_due_kpis` on the heartbeat cron (`ALERTS__DISPATCH_CRON`).
2. The dispatcher enqueues `evaluate_kpi.send(id)` for each enabled KPI whose own
   `schedule` cron is due. (Dagster asset-check events from Phase 2 can enqueue the
   same actor on-demand — evaluate the moment the underlying asset refreshes.)
3. `evaluate_kpi` re-resolves the tenant scope from the registry, runs the stored
   single-value aggregate bound to the tenant's ClickHouse database (read-only; the
   service asserts the dataset belongs to the resolved tenant), and compares the
   value to the threshold with the configured comparator.

## Exactly-once

Breach state lives on the KPI row (`is_breaching` + `last_fired_at`). The de-dupe
key is the **transition**, not the condition:

| Previous | Now breached? | Action |
|----------|---------------|--------|
| not breaching | yes | **fire one alert**, set `is_breaching=True` |
| breaching | yes | nothing (already alerted) |
| breaching | no | set `is_breaching=False` (re-arm) |
| not breaching | no | nothing |

The job session commits the state transition, so the guarantee holds across ticks
and worker restarts. A sustained breach never re-fires; a recovery re-arms it.

## Configuration

Per-KPI threshold, comparator, schedule, channel, and recipients/webhook are
**registry data** (the `kpi_thresholds` table) — change them with no deploy and no
code change (golden rule 1). Only conventions live in settings:

| Var | Meaning |
|-----|---------|
| `ALERTS__DISPATCH_CRON` | periodiq heartbeat that scans for due KPIs. |
| `ALERTS__WEBHOOK_TIMEOUT_SECONDS` | Timeout for webhook POSTs. |
| `ALERTS__SUBJECT_PREFIX` | Subject-line prefix for email alerts. |

Email delivery reuses the reporting `SMTP__*` relay. See [`.env.example`](../backend/.env.example).

## Tenant isolation

Identical to reporting: the scope is resolved server-side from the registry, the
query runs bound to the tenant's own ClickHouse database, and the service asserts
the dataset belongs to the resolved tenant — a mis-pointed KPI fails closed instead
of reading another tenant's data. `test_alerts_service.py` exercises the exactly-once
lifecycle and the cross-tenant rejection.
