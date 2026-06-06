# Scheduled reporting (Phase 5.1)

NovaSight renders saved queries to Excel workbooks and emails them on a schedule.
All of it runs **in the background** through a Dramatiq worker — never on the API
request path — and every step is tenant-scoped.

## Pieces

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Broker | [`app/core/broker.py`](../backend/app/core/broker.py) | Builds the Dramatiq Redis broker from `RedisSettings`. |
| Job session | [`app/core/db.py`](../backend/app/core/db.py) `session_scope` | An `AsyncSession` for code outside a request. |
| Job tenant scope | [`app/tenancy/job_context.py`](../backend/app/tenancy/job_context.py) | Re-resolves a `TenantContext` from a slug via the registry, fail-closed. |
| Registry row | [`app/models/report_definition.py`](../backend/app/models/report_definition.py) | Per-tenant report: dataset, stored query, cron schedule, recipients. |
| Cron | [`app/reporting/cron.py`](../backend/app/reporting/cron.py) | Minimal 5-field cron matcher for per-report schedules. |
| Render | [`app/reporting/excel.py`](../backend/app/reporting/excel.py) | Query result → `.xlsx` bytes. |
| Email | [`app/reporting/email.py`](../backend/app/reporting/email.py) | `EmailSender` protocol + SMTP implementation. |
| Orchestration | [`app/reporting/service.py`](../backend/app/reporting/service.py) | Load → resolve scope → query → render → store → email. |
| Actors | [`app/reporting/actors.py`](../backend/app/reporting/actors.py) | `render_and_send_report` Dramatiq actor (thin glue). |
| Dispatcher | [`app/reporting/schedule.py`](../backend/app/reporting/schedule.py) | periodiq heartbeat → enqueue due reports. |
| Entrypoint | [`app/reporting/worker.py`](../backend/app/reporting/worker.py) | Wires the broker, registers actors. |

## How a report runs

1. **periodiq** fires `dispatch_due_reports` on the heartbeat cron
   (`REPORTING__DISPATCH_CRON`, every minute by default).
2. The dispatcher loads all enabled `report_definitions` and, for each whose own
   cron `schedule` is due this minute, enqueues `render_and_send_report.send(id)`.
3. The worker runs `render_and_send_report`, which:
   - re-resolves the tenant scope from the registry — **never** from the message,
   - validates the stored `query_spec` back into a `QueryRequest`,
   - runs the aggregation bound to the tenant's ClickHouse database (read-only;
     the service also asserts the dataset belongs to the resolved tenant),
   - renders the result to `.xlsx`,
   - writes it under the tenant's object-store prefix (`<namespace>/reports/...`),
   - emails it to the report's recipients with the workbook attached.

## Running it locally

```bash
# worker (processes report jobs)
cd backend && uv run dramatiq app.reporting.worker
# scheduler (fires the heartbeat)
cd backend && uv run periodiq app.reporting.worker
```

Both need Redis (already in the dev compose stack) and the same `.env` the API uses.

## Configuration

Nothing here is hardcoded (golden rule 1). Two groups in
[`app/core/config.py`](../backend/app/core/config.py):

- **`SMTP__*`** (`SmtpSettings`) — the relay used to send mail. **Optional**: omit
  it if you don't run reports. If any `SMTP__*` var is set, `SMTP__HOST` and
  `SMTP__FROM_ADDRESS` are required, and the worker fails closed (clear error) if
  reporting is invoked without it.
- **`REPORTING__*`** (`ReportingSettings`) — environment-identical conventions
  (storage prefix, heartbeat cron, row cap, subject prefix), all with safe
  defaults.

The genuinely per-tenant settings — **which report, on what cron, to whom** — are
*not* configuration. They live as `report_definitions` rows so they change without
a deploy. See [`.env.example`](../backend/.env.example) for the SMTP/reporting block.

## Tenant isolation

The report's data scope is resolved server-side from the control-plane registry,
identical to the HTTP boundary (see the `tenancy-isolation` skill). The aggregation
runs bound to the tenant's own ClickHouse database, and the service asserts the
referenced dataset belongs to the resolved tenant — so a mis-pointed report row
fails closed instead of reading another tenant's data. The rendered file's object
key is prefixed with the tenant namespace, keeping isolation structural rather than
conventional. `test_reporting_service.py` exercises both the happy path and the
cross-tenant rejection.
