# The NovaSight stack (Docker Compose)

One unified compose file runs the **whole** product: infrastructure — **Postgres**
(control-plane DB), **Redis** (cache + task queue), **MinIO** (S3-compatible object lake
— the portability seam), **Iceberg REST catalog** (`iceberg-rest` — the lake's table
registry), **ClickHouse** (serving engine), **Cube** (semantic layer), and
**OpenMetadata** (catalog) — plus the application (`migrate` → `api`, `worker`,
`scheduler`, `dagster`, `dagster-daemon`) and the **frontend** (which also reverse-proxies
`/api`, so the whole app is one origin). There is no separate "local" mode or app overlay.
The same images run under Helm in the cloud; only configuration and the storage backend
change. After it is up, open `http://localhost:${FRONTEND__PORT}` (default `8080`).

Nothing is hardcoded: every credential, port, database name, and bucket is read from the
repo-root **`.env`** — the *same* file `backend/app/core/config.py` reads — so the stack
and the app never drift. See the `config-management` skill and `docs/CONFIGURATION.md`.

## Prerequisites

- Docker Engine + Compose v2 (`docker compose version`).
- A `.env` at the repo root: `cp .env.example .env` (or `make env`), then edit secrets.

## Bring it up

From the **repo root**:

```bash
make up        # = docker compose --env-file .env -f infra/compose/docker-compose.yml up -d
```

Equivalent raw command (also from the repo root):

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d
```

> **Why `--env-file .env`?** Compose v2 looks for an auto-loaded `.env` next to the
> *compose file* (`infra/compose/`), **not** in your shell's working directory. Our
> single source of truth lives at the repo root, so we point Compose at it explicitly.
> Without the flag, the host **port** mappings (which are interpolated from `.env`) would
> resolve to blanks. `make up` adds the flag for you.

This also runs a one-shot `minio-setup` job that creates the lake bucket
(`OBJECT_STORE__BUCKET`); re-running is a no-op.

## Verify health

```bash
make health
```

This probes all four services from the host using the ports in `.env`, including the two
required endpoints:

- **ClickHouse** — `GET http://localhost:${CLICKHOUSE__PORT}/ping` → `Ok.`
- **MinIO** — `GET http://localhost:${MINIO__API_PORT}/minio/health/live` → `200`

You can also read Compose's own healthchecks: `make ps` (look for `(healthy)`).

### Manual probes

Bash:

```bash
curl -fsS http://localhost:8123/ping                      # -> Ok.
curl -fsS http://localhost:9000/minio/health/live ; echo  # -> 200 (empty body)
```

PowerShell (no `make`/`bash`):

```powershell
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d
(Invoke-WebRequest http://localhost:8123/ping).Content              # -> Ok.
(Invoke-WebRequest http://localhost:9000/minio/health/live).StatusCode  # -> 200
```

## Ports (all from `.env`)

| Service        | Host port                  | Container | Notes                               |
|----------------|----------------------------|-----------|-------------------------------------|
| Postgres       | `POSTGRES__PORT` (5432)     | 5432      | control-plane DB                    |
| Redis          | `REDIS__PORT` (6379)        | 6379      | cache + queue                       |
| MinIO API      | `MINIO__API_PORT` (9000)    | 9000      | S3 endpoint (`OBJECT_STORE__*`)     |
| MinIO Console  | `MINIO__CONSOLE_PORT` (9001)| 9001      | web UI                              |
| Iceberg REST   | `ICEBERG__REST_PORT` (8181) | 8181      | lake catalog (`/v1/config`)         |
| ClickHouse     | `CLICKHOUSE__PORT` (8123)   | 8123      | HTTP interface (`/ping` lives here) |

## Common commands

```bash
make ps        # status (and health) of each container
make logs      # tail all logs
make down      # stop + remove containers (DATA IS KEPT in named volumes)
make clean     # down -v — also DELETES the data volumes (destructive)
```

Data persists in named volumes (`postgres-data`, `redis-data`, `minio-data`,
`clickhouse-data`) across `make down`/`up`.
