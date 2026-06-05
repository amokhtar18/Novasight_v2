# Phase 2 — Transform & orchestrate

Goal: introduce dbt + Dagster and the first data-quality gate, turning raw datasets into
modeled, tested marts.

---

## Task 2.1 — dbt project scaffold
```
Use the data-engineer. Follow dbt-dagster-workflow + config-management.
Initialize data-platform/dbt with staging/intermediate/marts folders and an env-driven
profiles.yml (no credentials in files; target schema derived from tenant context).
Add a staging model for the Phase 1 dataset with not_null/unique tests.
Acceptance: `dbt parse` and `dbt build --select staging` succeed against the dev target.
```

## Task 2.2 — First mart
```
Use the data-engineer.
Add an intermediate model and a consumption-ready mart, each with tests (use
dbt-expectations for a range/expectation check). The mart is what ClickHouse will serve.
Acceptance: `dbt build --select +marts` passes with all tests green.
```

## Task 2.3 — Dagster assets via dagster-dbt
```
Use the data-engineer. Follow dbt-dagster-workflow.
Set up data-platform/orchestration as a Dagster project. Load the dbt project as assets
so models appear in the asset graph. Add the dlt ingestion as an upstream asset.
Acceptance: the Dagster UI shows lineage from raw → staging → mart; materializing the
graph runs the pipeline.
```

## Task 2.4 — Quality gate as asset checks
```
Use the data-engineer.
Wrap the dbt tests as Dagster asset checks so a failure blocks downstream
materialization. Emit a structured failure event for the alerting layer to consume later.
Acceptance: a deliberately bad row causes the check to fail and stops the mart from
materializing; a good run passes.
```

## Task 2.5 — Load mart to ClickHouse + review
```
Use the data-engineer, then test-engineer, then reviewer.
Add a downstream asset that loads the validated mart into the tenant's ClickHouse db.
Add tests for the asset checks (good/bad data) and tenant scoping. Run /review-changes.
Acceptance: validated mart appears in ClickHouse per tenant; checks tested; reviewer
APPROVED.
```
