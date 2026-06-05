# Phase 5 — Reporting, governance & multi-tenant hardening

Goal: scheduled Excel reporting, KPI alerts, cataloging/lineage, encryption for
sensitive data, and exercising isolation under load.

---

## Task 5.1 — Scheduled Excel reports
```
Use the backend-engineer. Follow config-management + tenancy-isolation.
Add a Dramatiq worker (reporting/) that renders a dashboard/query to .xlsx (xlsxwriter)
on a schedule and emails it. SMTP, schedule, and recipients come from settings/tenant
config — none hardcoded. Reports run as background jobs, never inline.
Acceptance: a scheduled job produces a tenant-scoped Excel file and emails it; isolation
test confirms only the tenant's data is included.
```

## Task 5.2 — KPI alerts
```
Use the backend-engineer + data-engineer.
Define KPI thresholds (per tenant, from config/registry). Evaluate on a schedule or on
asset-check events from Phase 2; send alerts (email/webhook) when breached.
Acceptance: a breached threshold fires exactly one alert; thresholds are configurable
without code changes.
```

## Task 5.3 — Catalog & lineage
```
Use the data-engineer.
Integrate OpenMetadata or DataHub: ingest dbt + Dagster lineage and dataset metadata so
users can browse a catalog with lineage. Connection via settings.
Acceptance: datasets and end-to-end lineage are visible in the catalog.
```

## Task 5.4 — Encryption for sensitive data
```
Use the backend-engineer. Follow config-management.
Implement column-level encryption for fields tagged sensitive (KMS/provider via
settings) and confirm at-rest encryption on the object store. Sensitive columns are
masked in logs and unauthorized responses.
Acceptance: tagged columns are encrypted at rest; decryption is access-controlled; no
plaintext sensitive data in logs.
```

## Task 5.5 — Isolation under load + review
```
Use the test-engineer, then reviewer.
Add concurrent multi-tenant tests that hammer query/AI/report paths and assert zero
cross-tenant leakage. Run /review-changes across the phase.
Acceptance: no leakage under concurrency; reviewer APPROVED.
```
