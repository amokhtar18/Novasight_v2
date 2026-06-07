# Semantic Layer

This page documents the Cube semantic layer: its data model, the per-tenant security
mechanism, and the exact contract the backend client must implement to query it.

Read `docs/ARCHITECTURE.md` for context on where the semantic layer sits in the stack.

---

## Why Cube (not MetricFlow)

The serving engine is ClickHouse. As of 2025, dbt MetricFlow does not support
ClickHouse as a query target. Cube supports ClickHouse natively via its HTTP driver
and is the locked engine decision for NovaSight (see architecture decision record in
project memory).

---

## Data model

### Location

```
data-platform/semantic/model/regional_sales.js
data-platform/semantic/config/cube.js
```

### Cube: `regional_sales`

The cube maps to the serving table produced by the Dagster serving asset
(`data-platform/orchestration/novasight_orchestration/serving.py`). The physical table
name is read from the environment variable `CUBEJS_SERVING_REGIONAL_SALES_TABLE` (which
is set from `SERVING_REGIONAL_SALES_TABLE` in the repo-root `.env`). The database is
resolved from the per-request JWT security context — never from env or a literal.

Full `sql_table` expression (as it appears in the model file):

```js
sql_table: `\`${COMPILE_CONTEXT.securityContext.clickhouse_db}\`.\`${COMPILE_CONTEXT.env.CUBEJS_SERVING_REGIONAL_SALES_TABLE}\``
```

At query time this resolves to e.g. `` `tenant_acme`.`serving_regional_sales` ``.

#### Measures

| Identifier | Type | SQL expression | Description |
|---|---|---|---|
| `regional_sales.total_amount` | `sum` | `amount` | Sum of sales amount across all rows in the result set |
| `regional_sales.avg_share` | `avg` | `amount_share_pct` | Average share-of-total percentage across selected regions |

#### Dimensions

| Identifier | Type | SQL expression | Notes |
|---|---|---|---|
| `regional_sales.region` | `string` | `region` | Sales region name; primary key (grain) |
| `regional_sales.sales_rank` | `number` | `sales_rank` | Region rank by sales amount (lower = higher) |

---

## Per-tenant security mechanism

### Principle

Cube compiles one schema per tenant and enforces tenant isolation at two levels:

1. **Compiled-schema cache** (`contextToAppId`): each unique `clickhouse_db` value
   produces an independent compiled schema. Tenant A's schema can never be served to
   Tenant B.
2. **Query orchestrator** (`contextToOrchestratorId`): each tenant gets a dedicated
   connection-pool slice. Cross-tenant connection sharing is prevented.
3. **sql_table scoping**: the database qualifier in the cube's `sql_table` is injected
   from the security context at compile time. An absent or mismatched `clickhouse_db`
   causes a compile error — Cube fails closed rather than defaulting to a shared DB.

### JWT security context

Cube reads the security context from the JWT supplied by the caller. The backend is
responsible for minting this JWT. The flow is:

```
1. Authenticated request arrives at the FastAPI backend.
2. Backend resolves TenantContext via get_tenant_context() dependency:
     - extracts the tenant identifier from the OIDC access token (claim name set
       by AUTH__TENANT_CLAIM, default "tenant")
     - looks up the tenant in the registry
     - derives clickhouse_db = f"tenant_{tenant.slug}"
   TenantContext is NEVER derived from the request body/path/query — only from the
   verified OIDC claim (tenancy-isolation skill, rule 2).
3. Backend mints a short-lived HS256 JWT:
     header:  { "alg": "HS256", "typ": "JWT" }
     payload: {
       "clickhouse_db": "<TenantContext.clickhouse_db>",
       "exp": <unix_timestamp, now + 3600>
     }
   Signed with the secret from CubeSettings.api_secret (env: CUBE__API_SECRET).
4. JWT is sent as Authorization: Bearer <token> to Cube's load endpoint.
5. Cube's BUILT-IN JWT verification (enabled by CUBEJS_API_SECRET) verifies the
   HS256 signature and populates `securityContext` with the decoded claims —
   so `securityContext.clickhouse_db` is the tenant DB the backend signed in.
   `cube.js` deliberately does NOT define a custom `checkAuth`: doing so disables
   the built-in decode (the `auth` argument is undefined) and surfaces auth
   failures as HTTP 500 instead of 403.
6. contextToAppId derives "CUBE_APP__<clickhouse_db>" — schema cache key.
7. The model's sql_table resolves to the correct tenant database.
```

### Fail-closed guarantee

If the JWT is missing, expired, or has an invalid signature, Cube's built-in auth
rejects it with a 403 before any query runs. A validly-signed token that omits the
`clickhouse_db` claim is failed closed by `contextToAppId`/`contextToOrchestratorId`
in `cube.js`, which refuse to compile without a tenant scope. No query is executed
and no default database is used — the fail-closed behavior required by
tenancy-isolation golden rule 5.

### Required infrastructure: Cube Store

Outside dev mode, Cube requires **Cube Store** (its cache/queue/pre-aggregation
layer) — without it every query is rejected with *"Cube Store was specified as
queue/cache driver."* The compose stack runs a single-node `cubestore` service and
points Cube at it via `CUBEJS_CUBESTORE_HOST`/`CUBEJS_CUBESTORE_PORT`. Cube Store
holds only cache keyed by the per-tenant compiled query, so tenant isolation is
still enforced by the upstream security context.

### Model path gotcha

`CUBEJS_SCHEMA_PATH` is resolved **relative to the Cube project root** (`/cube/conf`),
so it must be `model`, not an absolute `/cube/conf/model` — an absolute value is
joined onto the root, finds no files, and silently compiles zero cubes.

---

## Backend client contract

This section is the precise specification the ai-engineer implements. Do not deviate
from the identifiers below — they are stable across all tenants and environments.

### Load endpoint

```
POST /cubejs-api/v1/load
Host: <CUBE__BASE_URL>
Authorization: Bearer <tenant_jwt>
Content-Type: application/json
```

`CUBE__BASE_URL` is read from `CubeSettings.base_url` in `app/core/config.py`. It
must not be hardcoded.

### JWT specification

| Field | Value |
|---|---|
| Algorithm | HS256 |
| Signing secret | `CubeSettings.api_secret` (env: `CUBE__API_SECRET`) |
| Required payload claim | `clickhouse_db` (string) — the value of `TenantContext.clickhouse_db` |
| Recommended `exp` | now + 3600 seconds (one hour) |

Example payload (not a real token):

```json
{
  "clickhouse_db": "tenant_acme",
  "exp": 1780000000
}
```

The JWT is signed server-side from `TenantContext.clickhouse_db`, which is derived
from the tenant registry after verifying the OIDC access token. The `clickhouse_db`
value is never accepted from the client request.

### Request body

Standard Cube JSON query format:

```json
{
  "query": {
    "measures": ["regional_sales.total_amount"],
    "dimensions": ["regional_sales.region"],
    "order": { "regional_sales.total_amount": "desc" }
  }
}
```

#### Available query identifiers

| Type | Identifier | Notes |
|---|---|---|
| Measure | `regional_sales.total_amount` | Sum of `amount` |
| Measure | `regional_sales.avg_share` | Average of `amount_share_pct` |
| Dimension | `regional_sales.region` | Region name string |
| Dimension | `regional_sales.sales_rank` | Integer rank |

### Response shape

Cube returns a standard `ResultSet` object:

```json
{
  "data": [
    { "regional_sales.region": "EMEA", "regional_sales.total_amount": "142500.00" },
    { "regional_sales.region": "APAC", "regional_sales.total_amount": "98300.00" }
  ],
  "annotation": { ... }
}
```

Data values for numeric measures are returned as strings by Cube's JSON serialiser.
The backend client must cast them as needed before returning to the frontend.

### Error handling

| HTTP status | Meaning |
|---|---|
| 403 | JWT missing, expired, invalid signature, or `clickhouse_db` claim absent |
| 400 | Malformed query (unknown measure/dimension name) |
| 200 | Success — check `data` array; may be empty if no rows match |

---

## Environment variables

The backend `CubeSettings` group (to be added to `app/core/config.py` by the
ai-engineer) must read:

| Env var | Purpose | Notes |
|---|---|---|
| `CUBE__BASE_URL` | Base URL for the Cube HTTP API | No default; must be supplied |
| `CUBE__API_SECRET` | HS256 signing secret | `SecretStr`; no default |
| `CUBE__PORT` | Host-published port (Compose only) | Not read by backend; Compose only |

`SERVING_REGIONAL_SALES_TABLE` is read by both the Dagster orchestration layer
(`OrchestrationSettings.serving_table`) and the Cube data model
(`CUBEJS_SERVING_REGIONAL_SALES_TABLE`). The backend does not need to read it — it
only queries Cube by stable cube/measure/dimension names that do not include the
physical table name.

---

## Infrastructure (Docker Compose)

The Cube service is defined in `infra/compose/docker-compose.yml`. Key points:

- `CUBEJS_DB_TYPE: clickhouse` — uses Cube's ClickHouse driver.
- `CUBEJS_DB_PORT` maps to `${CLICKHOUSE__PORT}` — HTTP port 8123. The native TCP
  port 9000 is not exposed in this stack and must not be used.
- `depends_on: clickhouse: condition: service_healthy` — Cube does not start until
  ClickHouse passes its `/ping` health check.
- The shared static model dir (`data-platform/semantic/model/` → `/cube/conf/model-shared`)
  and the server config (`cube.js`) are bind-mounted read-only; generated per-tenant
  models arrive via the `cube-model` named volume at `/cube/conf/model-tenant` (see the
  codegen section below). Model loading is via `repositoryFactory`, not `CUBEJS_SCHEMA_PATH`.

---

---

## Backend client implementation

The client lives at `backend/app/ai/semantic/client.py`.  It is the *only*
backend component that talks to Cube — all other code accesses the semantic
layer through it.

### Class: `SemanticLayerClient`

```python
SemanticLayerClient(cube_settings: CubeSettings, http_client: httpx.AsyncClient)
```

Constructor takes only infrastructure dependencies so tests can substitute a
fake `httpx` transport without live infra.

**Method:**

```python
async def query(
    ctx: TenantContext,
    *,
    measures: list[str],
    dimensions: list[str],
    order: dict[str, str] | None = None,
) -> list[CubeRow]
```

- `ctx` must be a server-resolved `TenantContext` (from `get_tenant_context()`).
  Never pass a client-supplied tenant identifier.
- `CubeRow` is `dict[str, str | Decimal]`.  Numeric measure values are cast to
  `Decimal`; dimension values are strings.
- Raises `CubeAuthError` (status 403) or `CubeQueryError` (other non-200) — no
  fallback, no retry.

### FastAPI dependency

```python
from app.ai.semantic import get_semantic_layer_client, SemanticLayerClient

@router.get("/metrics")
async def get_metrics(
    ctx: TenantContext = Depends(get_tenant_context),
    sl: SemanticLayerClient = Depends(get_semantic_layer_client),
) -> list[CubeRow]:
    return await sl.query(
        ctx,
        measures=[MEASURE_TOTAL_AMOUNT],
        dimensions=[DIM_REGION],
        order={MEASURE_TOTAL_AMOUNT: "desc"},
    )
```

`get_semantic_layer_client` reads `settings.cube` (injected via
`Depends(get_settings)`) and wires the process-wide `httpx.AsyncClient`
singleton.  Override in tests with `app.dependency_overrides`.

### Stable identifier constants

Exported from `app.ai.semantic.client` for use throughout the codebase:

| Constant | Value |
|---|---|
| `CUBE_REGIONAL_SALES` | `"regional_sales"` |
| `MEASURE_TOTAL_AMOUNT` | `"regional_sales.total_amount"` |
| `MEASURE_AVG_SHARE` | `"regional_sales.avg_share"` |
| `DIM_REGION` | `"regional_sales.region"` |
| `DIM_SALES_RANK` | `"regional_sales.sales_rank"` |

### JWT minting

The `_mint_jwt()` helper builds an HS256 JWT with:
- `clickhouse_db` = `ctx.clickhouse_db` (from the server-resolved context only)
- `exp` = now + 3600 seconds

The secret (`CubeSettings.api_secret`) is never logged or stored in a named
local variable; it is retrieved inline via `get_secret_value()`.

### Error types

| Exception | When raised |
|---|---|
| `CubeAuthError` | Cube returns 403 (bad/missing JWT) |
| `CubeQueryError` | Cube returns 400, 500, or any other non-200 status |

Both exceptions expose `.status` (int) and `.body` (str) for structured
logging.  They must not be forwarded verbatim to the frontend.

---

## Adding new cubes / measures

1. Add a new `.js` file under `data-platform/semantic/model/`.
2. Use the same `COMPILE_CONTEXT.securityContext.clickhouse_db` pattern for
   `sql_table` — tenant isolation is non-negotiable.
3. Update this page with the new cube name and measure/dimension identifiers.
4. Add new identifier constants to `backend/app/ai/semantic/client.py` and
   re-export them from `backend/app/ai/semantic/__init__.py`.
5. Update `docs/CONFIGURATION.md` if a new env var is introduced.

---

## HTTP API: governed structured queries (manual charts)

Feature #9 adds a point-and-click analogue of the AI `NL→chart` path. Both are
read-only and grounded on the governed Cube layer; neither touches a raw physical
table (golden rule #3). The endpoints are tenant-scoped via `get_tenant_context` —
the tenant is resolved from the JWT, never a body/path value.

- **`GET /api/v1/semantic/models`** → the governed models the tenant may query,
  derived from Cube `/meta`. Each model lists its `measures` and `dimensions`
  (`name`, `title`, `type`). The builder offers only what Cube exposes.
- **`POST /api/v1/semantic/query`** → run a structured request:

  ```json
  { "measures": ["regional_sales.total_amount"],
    "dimensions": ["regional_sales.region"],
    "order": { "regional_sales.total_amount": "desc" },
    "limit": 50 }
  ```

  Every reference is validated against the tenant's governed meta **before** any
  query runs; an unknown measure/dimension (or an order key that isn't selected)
  returns **422**. The `limit` is clamped to `settings.max_query_rows`. The result
  is a `QueryResponse` whose `columns` are `dimensions + measures` — the exact shape
  the shared `ChartRenderer` consumes for AI charts, so manual and AI charts render
  identically.

Implementation: `backend/app/api/v1/semantic.py` → `services/semantic.py`
(`SemanticService`, fail-closed `SemanticValidationError`) → `ai/semantic/client.py`
(`SemanticLayerClient.query`, now with an optional `limit`).

## HTTP API: saved charts

A built chart (manual or AI) can be persisted server-side so it survives across
devices and can later be composed onto a dashboard.

- **`GET /api/v1/charts`**, **`GET /api/v1/charts/{id}`**, **`POST /api/v1/charts`**,
  **`PATCH /api/v1/charts/{id}`**, **`DELETE /api/v1/charts/{id}`** — tenant-scoped
  CRUD over the `charts` table. A chart is a named `ChartSpec` plus
  `source_kind` (`semantic` | `dataset`) and `source_ref`. The spec (not a data
  snapshot) is stored, so a chart re-runs its grounded query when displayed.

A chart owned by another tenant is indistinguishable from not-found (404) — no
cross-tenant existence leak. Implementation: `backend/app/api/v1/charts.py` →
`services/charts.py` → `models/chart.py`.

Frontend: the chart builder (`frontend/src/pages/Builder.tsx`) defaults to the
semantic-model path (pick model → dimension → measure → type → live preview) and
both paths expose **Save chart** (`components/chart/SaveChartButton.tsx`) which posts
to the charts API.

## HTTP API: dashboards (#10)

Dashboards are persisted server-side (replacing the old localStorage store), so they
survive across devices and are shared within a tenant. A dashboard is an ordered grid
of tiles; each tile pins a saved ``Chart``. Tiles store **no data** — they embed the
chart's spec and the frontend re-runs its grounded query on display, so a dashboard
always reflects current data.

- **`GET /api/v1/dashboards`** → summaries (name, tile count).
- **`POST /api/v1/dashboards`**, **`GET/PATCH/DELETE /api/v1/dashboards/{id}`** — CRUD.
  The detail response embeds each tile's chart in one round-trip.
- **`POST /api/v1/dashboards/{id}/tiles`** → pin a saved chart. The chart's ownership
  is re-checked server-side, so a tile can never point at another tenant's chart (404).
- **`PATCH/DELETE /api/v1/dashboards/{id}/tiles/{tile_id}`** — update placement / remove.
- **`PUT /api/v1/dashboards/{id}/layout`** → persist the whole grid (order + sizes)
  after a drag/resize.

A dashboard, tile, or chart from another tenant is indistinguishable from not-found
(404). Implementation: `backend/app/api/v1/dashboards.py` → `services/dashboards.py`
→ `models/dashboard.py`. Frontend: the dashboard pages/grid/tiles use TanStack Query
against this API (the localStorage store is removed); tiles re-run via
`frontend/src/lib/useChartData.ts`.

## HTTP API: semantic-model registry + codegen (#8)

The chart/AI paths above query whatever cubes Cube exposes. The **registry** lets users
*define* those cubes from the UI (the wizard), and **codegen** turns a definition into a
Cube model file.

- **`GET/POST /api/v1/semantic-models`**, **`GET/PATCH/DELETE /api/v1/semantic-models/{id}`**
  — tenant-scoped CRUD over model definitions (name, `base_table`, and `config` =
  measures + dimensions). Reads need a tenant context; **mutations require the tenant
  superuser role** (defining the governed layer writes to the shared Cube model volume
  and affects every query). Names are unique per tenant (a name becomes a cube name).
  Members and column refs are strict identifiers — no arbitrary SQL reaches the model.

### Codegen — directory-level isolation via repositoryFactory

Cube loads model files through a `repositoryFactory` (`cube.js`): a request scoped to
`securityContext.clickhouse_db` is served the **shared static cubes** plus **only that
tenant's generated subdir**. Isolation is therefore at the *directory* level — one
tenant's catalog is never even parsed for another, so the generated cubes need no in-file
guard.

Two model roots are mounted (`infra/compose/docker-compose.yml`):

| Mount | Source | Holds |
|---|---|---|
| `/cube/conf/model-shared` (ro) | bind: `data-platform/semantic/model/` | hand-written static cubes (`regional_sales.js`) |
| `/cube/conf/model-tenant` (ro) | named volume `cube-model` | codegen output, `<clickhouse_db>/models.js` per tenant |

The codegen (`backend/app/codegen/cube_model.py`) is the single writer: on every
create/update/delete the service re-renders the tenant's enabled models and writes
`<CUBE__MODEL_DIR>/<clickhouse_db>/models.js` atomically. The **api** service mounts the
`cube-model` volume read-write (`CUBE__MODEL_DIR=/cube-model`); Cube mounts the same volume
read-only. `cube.js` adds a `schemaVersion` keyed on that file's mtime, so each write
forces a per-tenant recompile (Cube caches a compiled schema per appId).

```js
// cube.js (sketch)
repositoryFactory: ({ securityContext }) => ({
  dataSchemaFiles: async () => shared.concat(tenantFilesFor(securityContext.clickhouse_db)),
}),
```

**Verification note:** the pure render + writer are unit-tested
(`tests/test_cube_codegen.py`, `tests/test_semantic_models_api.py`); the live Cube
recompile (repositoryFactory + the shared volume) is verified on the running stack —
`docker compose up`, define a model, confirm it appears in `/cubejs-api/v1/meta` for that
tenant only.

Frontend: the **Semantic models** page (`frontend/src/pages/SemanticModels.tsx`, route
`/models`) is the wizard — name + base table + measure/dimension rows → `POST`.

## HTTP API: chat over the semantic layer (#11/#12)

`POST /api/v1/ai/chat` answers a natural-language question by running an **LLM
tool-dispatch loop** grounded on the governed semantic layer. The model may call only
a fixed set of **grounded, tenant-scoped tools** that delegate to the existing,
already-validated services — there is no raw-table or arbitrary-SQL path (golden rule
#3):

- `list_semantic_models` → `SemanticService.list_models` (Cube `/meta`),
- `query_semantic_model` → `SemanticService.query` (validated structured query),
- `nl_to_sql` → `NLToSQLService.query` (validated, read-only SQL).

Every tool runs under the server-resolved `TenantContext` — the model cannot widen the
tenant scope. Tool failures are fed back to the model as `is_error` results (fail
closed, but let it explain) rather than crashing the request; the loop is bounded.
Provider/semantic outages return 503 with a safe message.

### Gateway tool-use (provider-neutral)

The chat service drives the LLM via a provider-neutral tool-use surface added to the
gateway: `LLMGateway.complete_with_tools(ToolChatRequest) -> ToolChatResponse` with
neutral `ToolSpec` / `ToolCall` / `ToolResultMsg` / `ChatTurn` types
(`backend/app/ai/gateway/provider.py`). Providers map these onto their own wire format
(`AnthropicProvider.complete_with_tools` — see the `claude-api` skill). The chat
**dispatch loop** (`backend/app/ai/chat/service.py`) is unit-tested with a fake gateway
(`tests/test_ai_chat.py`); the live LLM tool-calling and the provider adapters are
verified on the running stack.

Frontend: the **Chat** page (`frontend/src/pages/Chat.tsx`, route `/chat`) shows the
answer plus the grounded tools the assistant called.

**Remaining (later):** a standalone MCP-protocol server (FastMCP) exposing these same
grounded tools to external MCP clients — it needs the `mcp` dependency and its own
compose service, and is best wired/verified on the running stack. The tool functions
+ grounding it would expose already exist here (the chat handlers); #12's
"AI charts/dashboards saved" reuses the existing `/charts` + `/dashboards` APIs.
