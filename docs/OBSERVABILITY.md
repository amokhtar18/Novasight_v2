# Observability — metrics + tracing (Phase 6.4)

Analytica emits **Prometheus metrics** and **OpenTelemetry traces** across the API,
the background workers, and the ingestion pipeline. Every endpoint/exporter is
config-driven (golden rule 1): the app only *produces* telemetry; where it is scraped
or shipped is deployment configuration.

## What's exposed

| Signal | Where | Source |
|--------|-------|--------|
| **Request** metrics | API `:8000/metrics` | [`PrometheusHTTPMiddleware`](../backend/app/core/metrics.py) — `analytica_http_requests_total`, `analytica_http_request_duration_seconds` (labeled by method, route template, status) |
| **Pipeline** metrics | wherever ingestion runs, on `/metrics` | [`csv_iceberg`](../backend/app/ingestion/csv_iceberg.py) — `analytica_ingest_rows_total`, `analytica_ingest_duration_seconds` |
| **Resource** metrics | every `/metrics` | prometheus-client default collectors — `process_*` (CPU, RSS, fds) and `python_*` |
| **Job** metrics | worker `:9100` | Dramatiq's fork-safe built-in Prometheus middleware — `dramatiq_messages_total`, durations, in-progress |
| **Traces** | OTLP → collector/Jaeger | FastAPI (server spans) + httpx (outbound) + SQLAlchemy (DB), so one request is a connected span tree |

Labels deliberately **exclude the tenant id** — bounded cardinality, and no tenant
identity on a shared scrape endpoint (tenancy-isolation: no cross-tenant leakage).

## Configuration (`OBSERVABILITY__*`)

| Var | Default | Meaning |
|-----|---------|---------|
| `OBSERVABILITY__METRICS_ENABLED` | `true` | wire the metrics middleware + `/metrics` |
| `OBSERVABILITY__METRICS_PATH` | `/metrics` | API metrics path |
| `OBSERVABILITY__WORKER_METRICS_PORT` | `9100` | worker metrics exposition port |
| `OBSERVABILITY__TRACING_ENABLED` | `false` | enable OTLP tracing (also needs an endpoint) |
| `OBSERVABILITY__OTLP_ENDPOINT` | _(none)_ | OTLP/HTTP base URL, e.g. `http://jaeger:4318` |
| `OBSERVABILITY__SERVICE_NAME` | `analytica` | base `service.name` |
| `OBSERVABILITY__TRACE_SAMPLE_RATIO` | `1.0` | head sampling ratio |

Tracing is a no-op until `TRACING_ENABLED=true` **and** an OTLP endpoint are set.

## Run the local stack

The [`docker-compose.observability.yml`](../infra/compose/docker-compose.observability.yml)
overlay adds Prometheus, Grafana, and Jaeger, scrapes the API + worker, and flips
tracing on for the app by pointing it at Jaeger:

```bash
docker compose --env-file .env \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.app.yml \
  -f infra/compose/docker-compose.observability.yml up -d --build
```

- **Grafana** http://localhost:3001 — auto-provisioned Prometheus + Jaeger datasources
  and the *Analytica — Overview* dashboard (request rate, p95 latency, ingest rows,
  worker jobs, API memory).
- **Prometheus** http://localhost:9090 — targets `analytica-api` and `analytica-worker`.
- **Jaeger** http://localhost:16686 — pick service `analytica-api` to see a request's
  end-to-end trace (server → DB → outbound spans).

## Kubernetes

Metrics/tracing are turned on the same way — set `OBSERVABILITY__*` keys under
`config:` in the Helm values. The chart stamps `prometheus.io/scrape` annotations on
the API (`:8000/metrics`) and worker (`:9100`) pods (toggle with
`observability.prometheusScrape`); point `OBSERVABILITY__OTLP_ENDPOINT` at your
in-cluster collector.
