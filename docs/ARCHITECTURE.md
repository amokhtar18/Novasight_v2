# Architecture

> Read this before designing anything. It is the source of truth for how the layers fit.

## Two decisions that govern everything

**One artifact, two deployment shapes.** A modular monolith, containerized. The same
images run as `docker compose up` on one on-prem box (single tenant) and as Helm charts
on Kubernetes in the cloud (multi-tenant). What flips is configuration and the storage
backend: MinIO + local Postgres on-prem; S3/GCS + managed Postgres in cloud. The
**S3-compatible object API is the portability seam** — nothing above storage knows which
backend it's talking to. Resist premature microservices.

**Tenancy = pooled compute, isolated data.** Shared application/orchestration tier, but:
- each tenant has its own Iceberg **namespace / object-store prefix**,
- its own **ClickHouse database**,
- its own **dbt target schema**.
A control-plane Postgres holds the tenant registry, users, connector configs, and the
resource mapping. Tenant context is resolved at the auth boundary and selects scope on
every request. On-prem, there is exactly one tenant and this collapses to a no-op — but
the code path is identical, so isolation is never retrofitted.

## The layers

```
Sources ─▶ Ingestion & lake ─▶ Transform & orchestrate ─▶ Serving ─▶ Visualization/UI
            (dlt + Airbyte,      (dbt Core run by           (ClickHouse  (React + ECharts
             Iceberg + REST       Dagster; quality           per tenant)  low-code builder)
             catalog, MinIO/S3)   gates as asset checks)
   ▲                                                                          ▲
   └────── Control plane (tenancy & auth) wraps the left ────────────────────┘
                    AI layer (NL→SQL, NL→chart, insights) reads serving + semantic layer
                    Governance, security, lineage & monitoring span everything
```

**Ingestion & data lake.** `dlt` for declarative, incremental, Iceberg-native loads
(streaming + event-triggered supported); Airbyte for the SaaS connector long tail; NiFi
for heavy CDC. Data lands as Iceberg tables in object storage via a REST catalog
(Polaris/Nessie — Nessie adds git-style data branching, handy for validation).

**Transform & orchestrate.** dbt Core (staging → intermediate → marts) driven by Dagster
via `dagster-dbt`. Iceberg tables and dbt models are software-defined assets, so lineage
is automatic. dbt tests + quality checks run as Dagster **asset checks** that gate
downstream materialization.

**Semantic layer (the hinge).** Cube or dbt MetricFlow defines metrics, dimensions, and
join paths once. The AI layer queries *this*, never raw tables — this is what makes
NL→SQL accurate and safe.

**Serving.** ClickHouse, one database per tenant, hydrated from validated marts, for
sub-second OLAP.

**Visualization & UI.** React + TypeScript, shadcn/ui + Tailwind, ECharts, a dnd-kit
drag-and-drop builder, Zustand + TanStack Query. Charts are driven by a declarative
**chart-spec** — the same shape the AI NL→chart endpoint emits — so manual and AI charts
share one renderer.

**AI layer.** Four features (NL→SQL, NL→chart, insights/summaries, source-based
suggestions), one pattern: **ground** on the tenant's semantic layer → **generate** via a
provider-agnostic gateway with versioned prompts → **validate** (read-only, allow-listed,
schema-checked) → **execute** read-only & sandboxed / return the spec.

**Reporting.** Dramatiq workers render scheduled Excel exports (xlsxwriter) and evaluate
KPI alerts; never inline in a request.

**Governance & security.** OpenMetadata/DataHub for catalog + lineage; column-level
encryption for sensitive fields (KMS) plus at-rest object-store encryption; PII-aware
logging.

**Infrastructure.** Prometheus + Grafana + OpenTelemetry across API, workers, pipelines.

## Backend stack

Python 3.12, FastAPI (async), Pydantic v2 + pydantic-settings, SQLAlchemy 2.0, Alembic,
Dramatiq + Redis, dlt, clickhouse-connect, Authentik/Keycloak (OIDC).

> Pin to the current stable release of each component when you reach its phase; the data
> ecosystem moves fast.
