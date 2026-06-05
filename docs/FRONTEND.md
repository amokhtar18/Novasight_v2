# Frontend

React + TypeScript + Vite single-page application for the Analytica low-code BI
platform. This document covers how to run the dev server, the runtime-config
mechanism, the Vite proxy setup, authentication for local development, and the
`ChartSpec` shape.

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

Before starting, complete the two config steps below (runtime config and auth token).

---

## Runtime configuration (`public/config.js` / `window.__APP_CONFIG__`)

No environment-specific values are baked into the app bundle. Instead, the web
server serves `public/config.js` before the app loads. That script sets
`window.__APP_CONFIG__`:

```js
window.__APP_CONFIG__ = {
  apiBaseUrl: "/api/v1",   // relative path works behind the Vite proxy
  authToken: "...",        // Bearer token (see Auth section below)
};
```

The app calls `loadConfig()` at startup (`src/lib/config.ts`), which reads this
object and fails loudly if required values are absent or still set to their
placeholder values. This is the frontend equivalent of the backend's
`pydantic-settings` object — one source of truth, nothing environment-specific
in source.

### Setup for local development

```bash
cp frontend/public/config.js.example frontend/public/config.js
# Edit config.js and replace REPLACE_WITH_DEV_TOKEN with your dev stub token.
```

`public/config.js` is git-ignored (the example is committed). Never commit a
real token or URL.

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

## Project structure

```
frontend/
  public/
    config.js.example   # template — copy to config.js and fill in for local dev
  src/
    api/
      client.ts         # typed API client (all fetch logic here, not in components)
      hooks.ts          # TanStack Query hooks
    components/
      chart/
        ChartRenderer.tsx  # ECharts renderer driven by ChartSpec
      ui/
        button.tsx, card.tsx, label.tsx, alert.tsx, empty-state.tsx  # shadcn-style primitives
    lib/
      config.ts         # loadConfig() — runtime config accessor
      cn.ts             # Tailwind class merge helper
    screens/
      UploadScreen.tsx  # Upload CSV → get dataset id
      ResultsScreen.tsx # Query dataset → render chart
    store/
      appStore.ts       # Zustand store (UI / navigation state only)
    types/
      api.ts            # TypeScript mirrors of backend Pydantic schemas + ChartSpec
    main.tsx            # Entry point: bootstrap config, TanStack Query, mount app
    App.tsx             # Root component: upload ↔ results routing
  .env.example          # Vite env vars (copy to .env for local dev)
  eslint.config.js
  vitest.config.ts
  vite.config.ts
```

---

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

`NLChartPanel` is rendered at the top of `ResultsScreen`, above the existing
manual Query & Chart card. Both are always visible; the AI panel's `onFallback`
prop scrolls the manual card into focus when a 422 is returned.

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
