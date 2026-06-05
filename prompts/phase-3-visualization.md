# Phase 3 — Visualization & the low-code builder

Goal: the product surface — saved dashboards, a chart library, data exploration, and the
drag-and-drop builder.

---

## Task 3.1 — Chart-spec contract
```
Use the backend-engineer + frontend-engineer.
Define a shared chart-spec schema (Pydantic on the backend, TS type on the frontend):
chart type, query/metric refs, encodings, options. This same shape is later emitted by
the AI NL→chart endpoint, so manual and AI charts share one renderer.
Acceptance: schema documented in docs/; a spec round-trips backend↔frontend.
```

## Task 3.2 — Chart renderer
```
Use the frontend-engineer.
Build a single ECharts-based renderer component that takes a chart-spec + data and
renders bar/line/area/pie/table to start. Import only the ECharts modules used.
Acceptance: each chart type renders from a spec; tsc + eslint clean.
```

## Task 3.3 — Save & load dashboards
```
Use the backend-engineer (persistence) + frontend-engineer (UI). Follow tenancy-isolation.
Add Dashboard and Tile models + CRUD endpoints (tenant-scoped) and the UI to create,
save, open, and delete dashboards composed of chart tiles.
Acceptance: dashboards persist per tenant; isolation test passes; reload restores layout.
```

## Task 3.4 — Drag-and-drop builder (dnd-kit)
```
Use the frontend-engineer.
Build the canvas: drag tiles, resize, rearrange (grid). Keep the canvas decoupled from
the renderer. Persist layout via the dashboard API.
Acceptance: a user composes a dashboard by dragging tiles and the layout is saved.
```

## Task 3.5 — Data exploration view
```
Use the frontend-engineer + backend-engineer.
Add an explore screen: pick a dataset/mart, choose dimensions/measures, preview results,
and "save as tile". Queries go through the tenant-scoped, row-capped query service.
Acceptance: a user explores a mart and saves a chart to a dashboard. Run /review-changes.
```
