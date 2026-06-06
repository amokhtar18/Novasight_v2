# Production containers (Phase 6.1)

NovaSight ships as **two** production images, built multi-stage and run **non-root**.
Every host, credential, bucket, model id, and threshold is read from the environment
at runtime (golden rule 1) — there are **no build-time secrets** and nothing
environment- or tenant-specific is baked into an image.

| Image | Dockerfile | Roles (same image, different `command`) |
|-------|-----------|------------------------------------------|
| `novasight-backend` | [`backend/Dockerfile`](../backend/Dockerfile) | **API** (default), **worker**, **scheduler**, **migrations** |
| `novasight-dagster` | [`data-platform/orchestration/Dockerfile`](../data-platform/orchestration/Dockerfile) | **webserver** (default), **daemon** |

One image per deployable serving several roles keeps the dependency closure and the
attack surface identical across processes (golden rule 4).

## Backend image

Build (context is `backend/`):

```bash
docker build -f backend/Dockerfile -t novasight-backend:latest backend
```

Run a role by overriding the command; config comes entirely from the environment:

```bash
# API (default CMD) — binds $API_HOST:$API_PORT (defaults 0.0.0.0:8000)
docker run --rm -p 8000:8000 --env-file .env novasight-backend:latest

# Database migrations (run as a one-shot job / initContainer before the API)
docker run --rm --env-file .env novasight-backend:latest alembic upgrade head

# Dramatiq worker — reporting (5.1) + KPI alerts (5.2)
docker run --rm --env-file .env novasight-backend:latest dramatiq app.reporting.worker

# periodiq scheduler — fires the dispatcher heartbeats
docker run --rm --env-file .env novasight-backend:latest periodiq app.reporting.worker
```

Image-internal conventions (all overridable from the environment, none secret):

| Var | Default | Meaning |
|-----|---------|---------|
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | In-container bind address/port for the API |
| `AI__PROMPT_TEMPLATE_DIR` | `/app/app/ai/prompts` | Bundled, versioned prompt templates |
| `PYTHONPATH` | `/app` | Makes the bundled source authoritative for `import app` |

## Dagster image

The image bundles **both** the orchestration package and the sibling dbt project,
because `dbt_resource.py` resolves the project at `parents[2]/dbt`. The dbt package
deps and the static manifest (`target/manifest.json`, which `dagster-dbt` reads at
import) are built **inside the image** via `dbt deps` + `dbt parse`. Parse uses
throwaway placeholder env values purely to render `profiles.yml`; it never connects to
a database, and the real `CLICKHOUSE__*` / `DBT_SCHEMA` are read at runtime.

> The build context must be `data-platform/` (not `data-platform/orchestration/`) so
> both directories are available.

```bash
docker build -f data-platform/orchestration/Dockerfile -t novasight-dagster:latest data-platform

# Webserver (default CMD) — binds $DAGSTER_HOST:$DAGSTER_PORT (defaults 0.0.0.0:3000)
```

> **Catalog ingestion (5.3) is opt-in.** The `catalog_metadata` asset imports the
> OpenMetadata SDK lazily, so the code location loads without it. The SDK's
> dependency tree only resolves against pre-releases and conflicts with the
> dagster/dbt stack, so it is **not** installed by default. Build with
> `--build-arg INSTALL_CATALOG=true` on a Dagster image dedicated to running that
> asset.

```bash
docker run --rm -p 3000:3000 --env-file .env novasight-dagster:latest

# Daemon — schedules, sensors, run queue
docker run --rm --env-file .env novasight-dagster:latest dagster-daemon run
```

| Var | Default | Meaning |
|-----|---------|---------|
| `DAGSTER_HOME` | `/opt/dagster/home` | Dagster instance home (mount a volume to persist) |
| `DAGSTER_HOST` / `DAGSTER_PORT` | `0.0.0.0` / `3000` | In-container bind address/port for the webserver |

## Running the whole stack

There is one unified compose file: [`docker-compose.yml`](../infra/compose/docker-compose.yml)
brings up **everything** — infrastructure (Postgres, Redis, MinIO, ClickHouse, Cube,
OpenMetadata), the application (`migrate` one-shot → `api`, plus `worker`, `scheduler`,
`dagster`, `dagster-daemon`), and the `frontend` (which also reverse-proxies `/api`, so
the whole app is one origin). There is no separate "local" mode or app overlay —
configuration (the repo-root `.env`) is the only thing that differs between a single
on-prem box and the cloud.

Run from the repo root and pass `--env-file` (Compose anchors `.env` to the compose
file's directory, not the CWD):

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d --build
```

Then open the app at `http://localhost:${FRONTEND__PORT}` (default `8080`) and sign in
with the seeded admin (`SEED_TENANT__ADMIN_EMAIL` / `SEED_TENANT__ADMIN_PASSWORD`).
Observability (Prometheus + Grafana) is an optional overlay:
`-f infra/compose/docker-compose.observability.yml`.

# Kubernetes / Helm (Phase 6.2)

The same two images are packaged by one umbrella chart,
[`infra/helm/novasight`](../infra/helm/novasight). It deploys the API, the worker, the
(singleton) scheduler, the Dagster webserver, and the (singleton) Dagster daemon, runs
DB migrations as a `pre-install`/`pre-upgrade` hook Job, and can optionally bundle the
stateful dependencies (Postgres, Redis, MinIO, ClickHouse).

**No infrastructure value is hardcoded in any template** (golden rule 1). All config
flows through two objects built entirely from values:

- a **ConfigMap** of non-secret env (`config:` in values), and
- a **Secret** of secret env (`secrets:` in values),

both injected into every workload via `envFrom`. Connection endpoints for any *enabled*
bundled dependency are filled in automatically from the in-cluster Service DNS; anything
set in `config:` overrides them. The bundled deps read their own credentials from the
**same** ConfigMap/Secret, so there is a single source of truth.

## The portability seam: one chart, two profiles

On-prem and cloud differ **only** in the values file — configuration + storage backend
(MinIO vs S3), per `ARCHITECTURE.md`. The templates are identical.

| | [`values-onprem.yaml`](../infra/helm/novasight/values-onprem.yaml) | [`values-cloud.yaml`](../infra/helm/novasight/values-cloud.yaml) |
|---|---|---|
| Tenancy | single-tenant | multi-tenant |
| Stateful deps | bundled in-cluster | disabled → managed (RDS, ElastiCache, managed ClickHouse) |
| Object store | bundled **MinIO** | **S3** (same S3-compatible seam) + SSE |
| API | 1 replica, ClusterIP | 3 replicas, HPA, Ingress + TLS |

Render either profile (the acceptance check):

```bash
helm template novasight infra/helm/novasight -f infra/helm/novasight/values-onprem.yaml
helm template novasight infra/helm/novasight -f infra/helm/novasight/values-cloud.yaml
```

Install (supply real secrets at install time — never commit them):

```bash
helm upgrade --install novasight infra/helm/novasight \
  -f infra/helm/novasight/values-onprem.yaml \
  --set-string secrets.POSTGRES__PASSWORD=... \
  --set-string secrets.AI__API_KEY=... \
  --set-string secrets.CUBE__API_SECRET=...   # etc.
```

> Cube and OpenMetadata have their own multi-container charts; deploy them separately
> and point `CUBE__BASE_URL` / `OPENMETADATA__HOST_PORT` at them via `config:`.
> Tenant provisioning (Iceberg namespace + ClickHouse DB + dbt schema + registry) is
> Phase 6.3.
