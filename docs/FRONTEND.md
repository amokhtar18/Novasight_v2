# Frontend

React + TypeScript + Vite single-page application for the NovaSight low-code BI
platform. It is a full **portal**: an app shell (sidebar + topbar) over routed
sections that expose every backend capability — connecting data, asking
questions (NL→SQL), building charts, assembling dashboards, generating insights,
and platform administration — so users never need to open an infrastructure UI
(ClickHouse, Dagster, Grafana, the control plane).

This document covers running the dev server, the runtime-config mechanism, the
Vite proxy, local auth, the information architecture, the design system, the
`ChartSpec` shape, and server-persisted dashboards.

---

## Running the dev server

Prerequisites: Node 20+ and pnpm 8+.

```bash
cd frontend

# Install dependencies
pnpm install

# Start the dev server (default: http://localhost:5173)
pnpm dev
```

Before starting, set the runtime config (`apiBaseUrl`) below. Authentication is
handled by the in-app login — no token in config.

---

## Authentication (login)

Users sign in at `/login`; the app posts to `POST /api/v1/auth/login` and stores
the returned access + refresh tokens and identity in the **auth store**
(`src/store/authStore.ts`, persisted to localStorage). The API client
(`src/api/client.ts`) attaches the access token to every request and, on a 401,
silently refreshes once and retries — clearing the session (→ redirect to
`/login`) if the refresh fails. Routes are gated by `RequireAuth` in `App.tsx`;
sign-out is in the account menu. See `docs/AUTH.md` for the backend contract.

> The token is no longer injected via `config.js`. A leftover `authToken` there is
> ignored once the user logs in.

---

## Runtime configuration (`public/config.js` / `window.__APP_CONFIG__`)

No environment-specific values are baked into the app bundle. Instead, the web
server serves `public/config.js` before the app loads. That script sets
`window.__APP_CONFIG__`:

```js
window.__APP_CONFIG__ = {
  apiBaseUrl: "/api/v1",   // relative path works behind the reverse proxy / Vite proxy
};
```

The app calls `loadConfig()` at startup (`src/lib/config.ts`), which reads this
object and fails loudly if `apiBaseUrl` is absent. This is the frontend
equivalent of the backend's `pydantic-settings` object — one source of truth,
nothing environment-specific in source.

### Setup for local development

```bash
cp frontend/public/config.js.example frontend/public/config.js
# config.js only needs apiBaseUrl; sign in via the /login screen.
```

`public/config.js` is git-ignored (the example is committed). Never commit a
real URL.

### Production / on-prem deployment

The deploy pipeline writes `public/config.js` from secrets/environment variables
before starting the web server. The app bundle itself does not change between
environments.

---

## Vite dev proxy and `VITE_API_PROXY_TARGET`

In local development, the Vite dev server proxies all `/api/*` requests to the
backend, making the SPA and API same-origin. This avoids CORS issues without
modifying the backend.

The proxy target is configured via `VITE_API_PROXY_TARGET` in `.env`:

```
VITE_API_PROXY_TARGET=http://localhost:8000
```

If `VITE_API_PROXY_TARGET` is not set, the proxy defaults to
`http://localhost:8000`.

To change the backend port or host:

```bash
cp frontend/.env.example frontend/.env
# Edit .env:
VITE_API_PROXY_TARGET=http://localhost:8001
```

See `frontend/.env.example` for all available variables with comments.

In `apiBaseUrl` (in `config.js`), keep the relative path `/api/v1` for local
dev — the Vite proxy rewrites it to `http://localhost:8000/api/v1`. For a
deployed environment where the SPA is served separately from the API, set the
full URL in `config.js`.

---

## Auth: setting the dev Bearer token

There is no login UI in the Phase 1 slice. The Bearer token is supplied via
`public/config.js` (`authToken` field) and attached to every request by the API
client.

The backend supports HS256 dev stub tokens when `AUTH__DEV_STUB` is set.

### How to obtain a dev token

1. Ensure the backend is running with `AUTH__DEV_STUB=true` (or the equivalent
   setting — see `backend/app/core/config.py`).
2. The dev stub token can be generated with:
   ```bash
   cd backend
   uv run python -c "
   from app.core.auth import create_dev_token
   print(create_dev_token(tenant_id='tenant-dev'))
   "
   ```
   (Adjust the import path if the helper lives elsewhere — check
   `backend/app/core/auth.py`.)
3. Paste the printed JWT into `frontend/public/config.js` as `authToken`.

The token is a standard HS256 JWT. It carries a `tenant` claim that the backend
uses to resolve the tenant context — the client never sends a tenant id
separately.

---

## ChartSpec shape

Charts are driven by a declarative `ChartSpec` object — the same shape the AI
NL→chart endpoint emits, so manual and AI-generated charts share one renderer
(`ChartRenderer`). The full contract (backend Pydantic + this TS mirror, the
canonical example, and the validation invariants) is documented in
[CHART_SPEC.md](CHART_SPEC.md); this section is the frontend quick reference.

```ts
// src/types/api.ts  (mirrors backend/app/schemas/chart.py, snake_case both sides)

type ChartType = "bar" | "line" | "area" | "pie" | "table";

interface ChartSpec {
  version?: string;        // contract version; current "1"
  type: ChartType;
  query: ChartQuery;       // where the data comes from (dataset query or metric refs)
  encoding: ChartEncoding; // x + series → visual channels
  options?: ChartOptions;  // title, stacked, show_legend, axis labels
}
```

### Example

```ts
const spec: ChartSpec = {
  version: "1",
  type: "bar",
  query: {
    dataset_id: datasetId,
    query: { dimensions: ["category"], metrics: [{ function: "count" }] },
  },
  encoding: {
    x: "category",
    series: [{ field: "count", name: "Count" }],
  },
  options: { title: "Count by category" },
};
```

The `ChartRenderer` component maps a `ChartSpec` + `QueryResponse` into an
ECharts option via `buildEChartsOption()` (exported from
`src/components/chart/ChartRenderer.tsx` for unit testing).

```tsx
<ChartRenderer
  spec={spec}
  data={queryResponse}
  title="Bar chart — count by category"
/>
```

Column names in `encoding.x` and `encoding.series[*].field` must exactly match
column names in `QueryResponse.columns`. The renderer throws a descriptive error
if they do not.

---

## Information architecture & routing

Routing uses `react-router-dom`. Every page renders inside `AppShell` (sidebar +
topbar) via `<Outlet>`; pages are lazy-loaded so each route is its own chunk
(ECharts only loads on charting routes — first paint stays lean).

| Route | Page | Purpose |
|-------|------|---------|
| `/` | Overview | Greeting, live system health, counts, quick actions, recents |
| `/data` | Data sources | Upload CSVs; browse datasets with status |
| `/data/:datasetId` | Dataset detail | AI chart suggestions for a dataset |
| `/pipelines` | Pipelines | ETL: manage source connections (create/test) + build pipelines, run now, **schedule (cron)**, view run history (superuser) |
| `/transforms` | Transforms | dbt model+test wizard: layer/materialization/SQL + column tests (regenerates dbt codegen; superuser) |
| `/models` | Semantic models | Wizard to define governed measures/dimensions over a mart (regenerates Cube codegen; superuser) |
| `/explore` | Ask AI | NL→SQL: question → validated SQL + table + visualize + summarize |
| `/chat` | Chat | Conversational Q&A over the governed semantic layer via grounded tool-calling (shows which tools the assistant used); when the assistant generates a chart it renders inline with **Save chart** + **Add to dashboard** actions (#12) |
| `/build` | Chart builder | Drag-and-drop builder over **semantic models** (Superset-style shelves: **X-axis** / **Breakdown** / **Metrics**) — drag governed dimensions/measures onto shelves, allow **multiple measures** and **breakdown dimensions** (pivoted into series via `chartPivot`), + NL→chart; a `time`-typed X dimension exposes a **granularity** selector (day…year); a **Saved charts** list (not tiles) loads any chart back into the shelves; **Save chart** (server-side, `POST /charts`) or add to dashboard |
| `/dashboards` | Dashboards | List / create dashboards |
| `/dashboards/:dashboardId` | Dashboard detail | dnd-kit grid: reorder/resize/remove tiles |
| `/insights` | Insights | Guardrailed AI narrative for a metric |
| `/admin` | Admin | System health detail + tenant provisioning (platform admin) |
| `/settings` | Settings | Theme + resolved tenant context |

The sidebar's **Admin** entry is shown only when the (display-only) decoded JWT
carries an admin-ish role (`src/lib/identity.ts`). Authorization is always
enforced by the backend — the client decode only affects what the UI *shows*.

## Design system & theming

- Tokens live in `src/index.css` as raw HSL channels: light theme in `:root`,
  dark theme in `.dark`. A categorical chart palette (`--chart-1..8`) is read at
  runtime by the renderer (`src/lib/chartTheme.ts`) so charts follow the theme.
- `ThemeProvider` (`src/lib/theme.tsx`) is **dark-first**: it defaults to dark,
  persists the choice in `localStorage`, and follows the OS in "system" mode.
- UI primitives in `src/components/ui/` are hand-rolled shadcn-style components
  (button, card, alert, badge, input, textarea, select, switch, tabs, dialog,
  dropdown-menu, skeleton, spinner, separator, empty-state).
- The brand is the infinity/Möbius mark (`src/components/BrandMark.tsx`, themed
  via a gradient) and the matching favicon.

### Control contract (core primitives)

The core controls share one contract, backed by tokens in `src/index.css`:

- **Sizes:** `Button`, `Input`, `Select` take `size="sm" | "md" | "lg"` (default
  `md` = `--control-h-md`, 2.25rem / h-9). Heights come from the `--control-h-*`
  tokens via `src/components/ui/_shared.ts` (`controlHeight`), so buttons and
  inputs always align.
- **Focus:** every control uses the shared `focusRing` class (`_shared.ts`) — one
  focus-visible ring everywhere.
- **Invalid:** `Input`, `Select`, `Textarea` accept `invalid` (sets `aria-invalid`
  + a destructive ring).
- **Loading:** `Button` accepts `loading` (spinner overlay + `aria-busy` +
  disabled, with zero layout shift — the label stays laid out).
- **Elevation:** `Card` accepts `elevation="none" | "sm" | "md" | "lg"` (default
  `sm` = `--elevation-1`); shadows are theme-aware.
- **Field molecule:** `src/components/molecules/Field.tsx` composes
  label + control + hint/error and auto-wires `htmlFor`/`id`/`aria-describedby`/
  `aria-invalid`. Pass exactly one control as the child.
- **Rolled out:** the shared `focusRing` and the `--z-*` / `--elevation-*`
  tokens are also applied to `Switch`, `Tabs`, `DropdownMenu`, `Badge`, and
  `Checkbox` (slice 2). `Dialog` adopts them in a later pass.
- **Pages consume the primitives:** the chat box (`Assistant`), the NL-chart
  prompt (`NLChartPanel`), the dbt SQL field (`DbtModels`), and the dashboard
  add-object text (`DashboardDetail`) use the hardened `Input`/`Textarea` — no
  more hand-rolled `focus-visible:ring-1` text controls in those screens (slice 3).
- **Checkboxes:** the chart-format panels and the pipeline/schedule wizards use
  the hardened `Checkbox` (themed `accent-primary` + shared ring) — no more bare
  browser-native checkboxes (slice 4).

New composite layers live in `src/components/molecules/` and
`src/components/organisms/` (atoms stay in `src/components/ui/`).

### Component gallery (dev only)

`/dev/components` renders every core primitive across its variants and states in
the live theme. It is registered only when `import.meta.env.DEV` and lazy-loaded,
so it never ships in production. Use it as the visual-regression surface when
changing a primitive.

## Dashboards (server-persisted)

Dashboards are persisted server-side via the `/api/v1/dashboards` API (TanStack
Query hooks in `src/api/hooks.ts`); tenant scoping is enforced by the backend from
the JWT, so there is no client-side per-tenant partitioning. A dashboard is an
ordered grid of tiles, each pinning a **saved chart** (`/api/v1/charts`). Tiles store
no data: each embeds the chart's `ChartSpec` and re-runs its grounded query on
display via `src/lib/useChartData.ts` (semantic specs → `/semantic/query`, dataset
specs → `/datasets/{id}/query`), so a dashboard always reflects current data.
Reordering/resizing persists through `PUT /dashboards/{id}/layout` with an optimistic
cache update. See `docs/SEMANTIC_LAYER.md` for the API surface.

**View-time filter bar** (`DashboardFilterBar`): in view mode the dashboard shows a
filter — pick a governed dimension + a value — handed to each tile via `DashboardGrid`.
The dimension list is scoped to the **cubes the dashboard's tiles actually use**
(`DashboardDetail` derives the cube set from the tiles' specs), so the bar never offers
a filter that would affect nothing. A tile applies the filter only when it is a
**semantic** chart on the **same cube** as the filter member (a non-matching tile
renders unfiltered and shows no "Filtered" badge), so a filter never breaks an
unrelated tile. The filter
flows into `useChartData(spec, filters)` → `/semantic/query`, where the server
re-validates each member against the governed allow-list (`SemanticFilter`). It is a
single filter — a governed dimension, an **operator** (`equals`/`notEquals`/`contains`/
`notContains`/`gt`/`gte`/`lt`/`lte`, plus the value-less presence checks `set`/`notSet`),
and a value — **persisted on the dashboard** (`dashboards.filters` JSON, migration
`0008`): changing it `PATCH`es `/dashboards/{id}` with `filters`, and the bar
initialises from `DashboardRead.filters` on load, so it survives reload and is shared
with anyone who opens the dashboard. Persisting a filter never widens data access — the
query path re-validates the member every time a tile runs. Set-membership operators
(`equals`/`notEquals`/`contains`/`notContains`) accept a **comma-separated list** of
values (match any/none); comparison operators take a single value. Applying filters to
dataset-path tiles is a later slice.

**Cross-filtering**: clicking a data point on a category-axis chart (bar/line/area/pie)
sets the dashboard filter to that chart's dimension `equals` the clicked category — so a
chart doubles as a filter control. `ChartRenderer` reports the clicked category via
`onSelectCategory`; the tile maps it to its `encoding.x` dimension and calls
`onCrossFilter`, which `DashboardDetail` routes through the same persist path as the bar.
Wired for semantic tiles only, and disabled in edit mode.

## Project structure

```
frontend/
  public/
    config.js.example   # template — copy to config.js and fill in for local dev
  src/
    api/
      client.ts         # typed API client (all fetch logic here, not in components)
      hooks.ts          # TanStack Query hooks (me, health, datasets, AI, tenants)
    components/
      BrandMark.tsx     # infinity/Möbius brand mark (SVG)
      chart/            # ChartRenderer (ECharts), TableRenderer, SpecChart, NLChartPanel
      dashboard/        # AddToDashboard, DashboardGrid + DashboardCardTile (dnd-kit), DashboardFilterBar
      data/             # UploadCard (drag-drop CSV + validation)
      layout/           # AppShell, Sidebar, TopBar, PageHeader, nav
      ui/               # hand-rolled shadcn-style primitives
    lib/
      config.ts         # loadConfig() — runtime config accessor
      theme.tsx         # ThemeProvider / useTheme (dark-first)
      identity.ts, jwt.ts  # display-only JWT decode (tenant + roles)
      chartTheme.ts, format.ts, useTenantId.ts, cn.ts
    pages/              # one component per route (see table above)
    store/
      uiStore.ts        # sidebar / mobile-nav UI state
      # dashboards are server-persisted via /api/v1/dashboards (no local store)
    types/
      api.ts            # TypeScript mirrors of backend Pydantic schemas + ChartSpec
    main.tsx            # Entry: config, TanStack Query, ThemeProvider, BrowserRouter
    App.tsx             # Routes inside AppShell (lazy-loaded pages)
  .env.example          # Vite env vars (copy to .env for local dev)
  eslint.config.js
  vitest.config.ts
  vite.config.ts
```

---

## NL→chart flow (Task 4.4)

### Overview

The `NLChartPanel` component lets users describe a chart in plain English. It
calls `POST /api/v1/ai/chart` and renders the response with the **same**
`ChartRenderer` that powers the manual builder — the shared `ChartSpec` +
`QueryResponse` contract is the load-bearing seam.

```
User types prompt
      │
      ▼
useNLChart() mutation  ──▶  POST /api/v1/ai/chart
      │                         { "request": "total sales by region as bar" }
      │
  200 OK ──────────────────▶  { spec: ChartSpec, data: QueryResponse }
      │                              │
      │                              ▼
      │                        ChartRenderer (same as manual path)
      │
  422 ────────────────────▶  fallback message + onFallback() callback
      │                       → parent scrolls to manual builder
      │
  503 ────────────────────▶  "service unavailable, try again" message
```

### Shared renderer reuse

The AI endpoint returns `{ spec: ChartSpec, data: QueryResponse }` — exactly
the two props `ChartRenderer` expects. No translation layer is needed:

```tsx
<ChartRenderer
  spec={aiResult.spec}
  data={aiResult.data}
  title={aiResult.spec.options?.title ?? "AI-generated chart"}
/>
```

The manual builder builds the same `{ spec, data }` pair from user controls and
a `useDatasetQuery` result. Both paths share one renderer.

### Graceful fallback

| Status | Meaning | UI behaviour |
|--------|---------|--------------|
| 200 | Success | Chart rendered via `ChartRenderer` |
| 422 | Ungroundable / invalid spec | Friendly message; `onFallback()` called; manual builder scrolled into view |
| 503 | LLM / Cube unavailable | Transient error alert with retry prompt |
| other | Unexpected | Generic error alert |

A 422 never crashes the app and never renders a partial chart. The manual
builder (`ResultsScreen`'s Query & Chart card) remains fully usable at all
times — it is not hidden behind the AI panel.

### New types (`src/types/api.ts`)

```ts
interface NLChartRequest {
  request: string;   // 1–2000 chars, non-empty
}

interface NLChartResponse {
  spec: ChartSpec;
  data: QueryResponse;
}
```

### New client function (`src/api/client.ts`)

```ts
async function postNLChart(request: NLChartRequest): Promise<NLChartResponse>
```

Throws `NLChartError` (a subclass of `Error`) with `.kind`:
- `"ungroundable"` — 422
- `"service_unavailable"` — 503
- `"unknown"` — other non-2xx

### New hook (`src/api/hooks.ts`)

```ts
function useNLChart(): UseMutationResult<NLChartResponse, Error, NLChartRequest>
```

A TanStack Query mutation (not a query) because it is user-triggered and not
idempotent. Callers read `error` and cast to `NLChartError` to branch on kind.

### Where the input lives

`NLChartPanel` is embedded in the **Chart builder** page (`/build`) alongside the
manual builder; both are always available. On success it calls `onResult` so the
page can offer "Add to dashboard" on the AI chart. The same NL→SQL flow (with SQL
transparency and one-click summarize/visualize) lives on the **Ask AI** page
(`/explore`).

---

## Running checks

```bash
cd frontend

# Type check
pnpm exec tsc --noEmit

# Lint
pnpm lint

# Tests
pnpm test
```
