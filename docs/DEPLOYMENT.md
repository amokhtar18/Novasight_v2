# Production containers (Phase 6.1)

Analytica ships as **two** production images, built multi-stage and run **non-root**.
Every host, credential, bucket, model id, and threshold is read from the environment
at runtime (golden rule 1) — there are **no build-time secrets** and nothing
environment- or tenant-specific is baked into an image.

| Image | Dockerfile | Roles (same image, different `command`) |
|-------|-----------|------------------------------------------|
| `analytica-backend` | [`backend/Dockerfile`](../backend/Dockerfile) | **API** (default), **worker**, **scheduler**, **migrations** |
| `analytica-dagster` | [`data-platform/orchestration/Dockerfile`](../data-platform/orchestration/Dockerfile) | **webserver** (default), **daemon** |

One image per deployable serving several roles keeps the dependency closure and the
attack surface identical across processes (golden rule 4).

## Backend image

Build (context is `backend/`):

```bash
docker build -f backend/Dockerfile -t analytica-backend:latest backend
```

Run a role by overriding the command; config comes entirely from the environment:

```bash
# API (default CMD) — binds $API_HOST:$API_PORT (defaults 0.0.0.0:8000)
docker run --rm -p 8000:8000 --env-file .env analytica-backend:latest

# Database migrations (run as a one-shot job / initContainer before the API)
docker run --rm --env-file .env analytica-backend:latest alembic upgrade head

# Dramatiq worker — reporting (5.1) + KPI alerts (5.2)
docker run --rm --env-file .env analytica-backend:latest dramatiq app.reporting.worker

# periodiq scheduler — fires the dispatcher heartbeats
docker run --rm --env-file .env analytica-backend:latest periodiq app.reporting.worker
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
docker build -f data-platform/orchestration/Dockerfile -t analytica-dagster:latest data-platform

# Webserver (default CMD) — binds $DAGSTER_HOST:$DAGSTER_PORT (defaults 0.0.0.0:3000)
```

> **Catalog ingestion (5.3) is opt-in.** The `catalog_metadata` asset imports the
> OpenMetadata SDK lazily, so the code location loads without it. The SDK's
> dependency tree only resolves against pre-releases and conflicts with the
> dagster/dbt stack, so it is **not** installed by default. Build with
> `--build-arg INSTALL_CATALOG=true` on a Dagster image dedicated to running that
> asset.

```bash
docker run --rm -p 3000:3000 --env-file .env analytica-dagster:latest

# Daemon — schedules, sensors, run queue
docker run --rm --env-file .env analytica-dagster:latest dagster-daemon run
```

| Var | Default | Meaning |
|-----|---------|---------|
| `DAGSTER_HOME` | `/opt/dagster/home` | Dagster instance home (mount a volume to persist) |
| `DAGSTER_HOST` / `DAGSTER_PORT` | `0.0.0.0` / `3000` | In-container bind address/port for the webserver |

## Running the whole stack locally

The base compose runs infrastructure only; the
[`docker-compose.app.yml`](../infra/compose/docker-compose.app.yml) overlay builds and
runs the application images against it, reaching infrastructure by compose service
name. Run from the repo root and pass `--env-file` (Compose anchors `.env` to the
compose file's directory, not the CWD):

```bash
docker compose --env-file .env \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.app.yml up -d --build
```

This brings up `migrate` (one-shot) → `api`, plus `worker`, `scheduler`, `dagster`,
and `dagster-daemon`. The Kubernetes/Helm packaging of these same images is Phase 6.2.
