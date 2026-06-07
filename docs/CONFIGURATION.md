# Configuration

This page is the contract behind the golden rule **"no hardcoded configuration in the
backend."** Read the `config-management` skill for the enforcement rules; this is the
human reference.

## Philosophy
- The code is identical across local / on-prem / cloud. Only configuration and the
  storage backend differ.
- One source of truth: `backend/app/core/config.py`. Nothing else reads the environment.
- Inject settings via `Depends(get_settings)`; never import module-level config or read
  `os.environ` elsewhere.
- Adding a setting is a three-file change in the same commit: the settings model,
  `.env.example` (placeholder + comment), and this page.
- Secrets use `SecretStr`, are never logged, and never appear in `.env.example` as real
  values. Real `.env` files are git-ignored.
- **Defaults**: allowed only when correct everywhere (e.g. page size). Infrastructure
  pointers (hosts, buckets, model ids, keys) have no default and must be supplied.
- **Tenant-specific values are runtime data, not config** — they live in the tenant
  registry (Postgres) and are resolved per request, never via env or literals.

## Variable reference

| Variable | Type | Default | Varies by | Purpose |
|---|---|---|---|---|
| `ENVIRONMENT` | str | — | deployment | local / onprem / cloud |
| `LOG_LEVEL` | str | INFO | — | logging verbosity |
| `DEFAULT_PAGE_SIZE` | int | 50 | — | API pagination default |
| `MAX_QUERY_ROWS` | int | 100000 | — | hard cap on rows returned |
| `MAX_UPLOAD_MB` | int | 100 | — | upload size limit |
| `POSTGRES__*` | — | port 5432 | deployment | control-plane DB connection |
| `REDIS__*` | — | port 6379 | deployment | cache + queue |
| `OBJECT_STORE__*` | — | region us-east-1 | deployment | S3-compatible lake storage (the portability seam) |
| `ICEBERG__CATALOG_URI` / `__WAREHOUSE` | str | — | deployment | REST catalog + warehouse location |
| `ICEBERG__CATALOG_TOKEN` | SecretStr | `None` | deployment | Optional bearer token for REST catalog auth (Polaris/Nessie credential). Omit when the catalog is unauthenticated. |
| `CLICKHOUSE__*` | — | port 8123 | deployment | serving engine connection |
| `AI__PROVIDER` / `__MODEL` / `__API_KEY` | str / secret | — | deployment + tenant | LLM gateway provider, default model, key |
| `AI__TEMPERATURE` / `__MAX_TOKENS` | float / int | 0.0 / 1024 | — | generation params |
| `AI__PROMPT_TEMPLATE_DIR` | str | — | deployment | versioned prompt templates |
| `AUTH__OIDC_ISSUER` / `__OIDC_AUDIENCE` / `__JWKS_URL` | str | `""` | deployment | OIDC (RS256) provider — issuer URL, audience, JWKS endpoint. Required only in OIDC mode (neither `AUTH__DEV_STUB` nor `AUTH__SESSION_SECRET` set). |
| `AUTH__DEV_STUB` | bool | `false` | deployment | Enable HS256 dev-stub mode. **NEVER set to `true` in production.** Secure default is `false`. |
| `AUTH__DEV_STUB_SECRET` | SecretStr | `None` | local/dev only | HS256 signing secret used in dev-stub mode (use a long random string, 32+ chars recommended). Required when `DEV_STUB=true`; ignored otherwise. |
| `AUTH__SESSION_SECRET` | SecretStr | `None` | deployment | HS256 secret for **password mode**: the backend signs+verifies its own access/refresh tokens and serves `/auth/login`. The default out-of-box mode. Mutually exclusive with OIDC; leave blank to use an external IdP. |
| `AUTH__ACCESS_TTL_SECONDS` / `__REFRESH_TTL_SECONDS` | int | 3600 / 1209600 | — | access (1h) and refresh (14d) token lifetimes for password mode. |
| `AUTH__TENANT_CLAIM` | str | `"tenant"` | deployment | Name of the JWT claim that carries the tenant identifier (slug). |
| `AUTH__ROLES_CLAIM` | str | `"roles"` | deployment | Name of the JWT claim carrying the principal's roles list. |
| `AUTH__PLATFORM_ADMIN_ROLE` | str | `"platform_admin"` | deployment | Role required to operate the control plane (provision/de-provision tenants). Platform role, not tenant-scoped. |
| `AUTH__TENANT_SUPERUSER_ROLE` | str | `"superuser"` | deployment | Tenant-scoped role required to create/run/schedule pipelines and dbt jobs. A platform admin is implicitly allowed. |
| `DAGSTER__GRAPHQL_URL` | str | `""` | deployment | Dagster GraphQL endpoint the backend uses to launch runs + reload the code location (e.g. `http://dagster:3000/graphql`). Empty disables the control plane; orchestration endpoints then fail closed with 503. |
| `DAGSTER__REPOSITORY_LOCATION` / `__REPOSITORY_NAME` | str | `novasight_orchestration` / `__repository__` | convention | Code location (the `-m` module) and Definitions repository name the dynamic jobs/schedules live in. |
| `SEED_TENANT__SLUG` / `__NAME` / `__ADMIN_EMAIL` | str | — | deployment | bootstrap tenant identity used by the seed script; slug derives the tenant's Iceberg namespace / ClickHouse db / dbt schema |
| `SEED_TENANT__ADMIN_PASSWORD` | SecretStr | `None` | deployment | Password for the seeded admin (password mode). When set, the admin can log in and is granted the platform-admin + tenant-superuser roles. Omit in OIDC mode. |
| `MINIO__API_PORT` | int | 9000 | local stack | host publish port for the MinIO S3 API (Compose only); must match the port in `OBJECT_STORE__ENDPOINT_URL` |
| `MINIO__CONSOLE_PORT` | int | 9001 | local stack | host publish port for the MinIO web console (Compose only) |
| `DBT_SCHEMA` | str | — | per tenant | dbt target schema == the tenant's ClickHouse database; resolved from the tenant context at invocation. dbt/Dagster only. |
| `DBT_PHASE1_DATASET_TABLE` | str | — | per dataset | registered Phase 1 dataset table (`dataset_<uuid_hex>`) the staging model reads. Runtime data; required for `dbt build`. dbt only. |
| `DBT_THREADS` | int | 4 | — | dbt parallelism. dbt only. |
| `CUBE__BASE_URL` | str | — | deployment | URL the backend uses to reach Cube's HTTP API (e.g. `http://cube:4000`). Read by `CubeSettings.base_url` in `app/core/config.py`. |
| `CUBE__API_SECRET` | SecretStr | — | deployment | HS256 shared secret. Backend signs per-tenant JWTs; Cube verifies them. Minimum 32 random characters. |
| `CUBE__PORT` | int | — | local stack | Host-published port for the Cube container (internal port 4000). Compose only; must match the port in `CUBE__BASE_URL`. |
| `CUBE__MODEL_DIR` | str \| None | `None` | deployment | Filesystem path where the semantic-model codegen writes generated per-tenant Cube model files (`tenant__<db>.js`); must be a directory the Cube container also reads (shared volume). Unset → codegen renders but does not write. Read by `CubeSettings.model_dir`. |
| `SERVING_REGIONAL_SALES_TABLE` | str | `serving_regional_sales` | deployment | Physical name of the serving table the Dagster serving asset writes and the Cube model reads. Shared by both layers via the same env var so they never drift. |

> `MINIO__*` are consumed only by `infra/compose/docker-compose.yml` for the local dev
> stack, not by the backend. Postgres, Redis, and the ClickHouse HTTP port reuse
> `POSTGRES__PORT`, `REDIS__PORT`, and `CLICKHOUSE__PORT` as their host publish ports.

> `DBT_*` are consumed by the `data-platform/dbt` project (and the Dagster runner that
> invokes it), not by the backend `Settings` object. The dbt profile reuses the
> backend's `CLICKHOUSE__*` variables for the connection. `DBT_SCHEMA` and
> `DBT_PHASE1_DATASET_TABLE` are tenant/runtime data — Dagster sets them per run from
> the resolved tenant context, never from a literal.

> When you add a setting, add its row here. A reviewer will reject a new config value
> that isn't documented and present in `.env.example`.

## On-prem vs cloud
The only deltas are values like `OBJECT_STORE__ENDPOINT_URL` (MinIO URL vs blank for AWS
S3), the Postgres host (local container vs managed), and ClickHouse host. The
application code does not branch on environment for these — it just reads settings.
