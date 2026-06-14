# Chart-spec contract

> The declarative shape that describes one chart. **One spec, two producers, one
> renderer.** Manual configuration (the explore view / low-code builder) and the AI
> `NL→chart` endpoint both emit this exact shape, so they share a single renderer.

The spec is the seam between *deciding what a chart is* and *drawing it*. Nothing in
the spec mentions ECharts; the frontend renderer translates it into an ECharts
option. Nothing in the spec is SQL; the `query` describes a structured aggregation
that the query service compiles to a safe, read-only `SELECT`.

## Where it lives

| Side | File | Notes |
| --- | --- | --- |
| Backend | [`backend/app/schemas/chart.py`](../backend/app/schemas/chart.py) | Pydantic v2; the source of truth |
| Frontend | [`frontend/src/types/api.ts`](../frontend/src/types/api.ts) | TypeScript mirror |
| Example | [`docs/examples/chart-spec.example.json`](examples/chart-spec.example.json) | Canonical fixture used by both round-trip tests |

Field names are **snake_case on both sides**, so the JSON that crosses the wire is
identical — a backend-produced spec deserialises on the frontend and vice versa,
with no key translation. The round-trip is enforced by tests on both sides
([`backend/tests/test_chart_spec.py`](../backend/tests/test_chart_spec.py) and
[`frontend/src/test/chartSpec.test.ts`](../frontend/src/test/chartSpec.test.ts)),
both reading the one canonical fixture so the two languages cannot drift.

## Shape

```jsonc
{
  "version": "1",                // contract version; bump on breaking changes
  "type": "bar",                 // bar | line | area | pie | table | number
  "query": {                     // WHERE the data comes from (≥1 source required)
    "dataset_id": "…uuid…",      //   dataset the inline query runs against
    "query": { /* QueryRequest */ }, //   structured aggregation (Phase 1 path)
    "metric_refs": []            //   OR governed metric names (semantic / AI path)
  },
  "encoding": {                  // HOW columns map to visual channels
    "x": "month",                //   category axis (x / pie label); omit for table
    "series": [                  //   value series (≥1); for a table, the columns
      { "field": "sales", "name": "Sales", "color": "#3b82f6" }
    ]
  },
  "options": {                   // display-only; never affects the query/data
    "title": "Monthly sales",
    "stacked": false,
    "show_legend": true,
    "x_axis_label": "Month",
    "y_axis_label": "Amount"
  }
}
```

### `type`

`bar`, `line`, `area`, `pie`, `table`, `number`. `area` renders as a line series with
an area fill. `table` presents the query result as columns. `number` is a single
"big number" KPI tile that shows the **total of its first series** across the result
(a single-aggregate query shows that value; a grouped query shows the grand total).
`table` and `number` are the two types that may omit `encoding.x`.

### `query` — query/metric refs

A chart must be **grounded**: it references a data source, never raw SQL. At least
one of two sources is required:

- an inline structured `query` (a [`QueryRequest`](../backend/app/schemas/query.py))
  against `dataset_id` — the structured-aggregation path used today; and/or
- `metric_refs` — names of governed metrics resolved by the semantic layer, the
  path the AI layer will use (see the `nl-to-sql-grounding` skill).

There is intentionally nowhere to put a raw SQL string.

### `encoding` — encodings

`x` names the column used for the category axis (or pie slice labels). `series` is a
non-empty list; each entry's `field` is a column name in the resulting
`QueryResponse`. `name` is the legend label (defaults to `field`); `color` is an
optional explicit colour. Encoding `field`/`x` values are *display references* only
— they are pattern-bounded (`^[A-Za-z_][A-Za-z0-9_.]*$`) and never reach the SQL
builder.

### `options`

Display-only. `title`, `stacked`, `show_legend`, `x_axis_label`, `y_axis_label`.
Changing any option never changes the query or the data.

## Validation invariants

The Pydantic schema enforces (and the frontend type mirrors):

- a `ChartQuery` must have an inline `query` **or** at least one `metric_refs` entry;
- `encoding.series` has at least one entry;
- `encoding.x` is required for every type except `table` and `number`;
- `field`/`x`/`metric_refs` match the bounded field-name pattern above.

## Round-trip guarantee

The acceptance test for this contract is that a spec round-trips backend↔frontend.
Concretely:

1. the backend parses the canonical fixture into a `ChartSpec` and re-serialises it
   to value-identical JSON, and
2. the frontend reads the *same* file, finds it assignable to the TS `ChartSpec`,
   round-trips it through JSON unchanged, and feeds it to the shared renderer.

Run both: `cd backend && uv run pytest tests/test_chart_spec.py` and
`cd frontend && pnpm test chartSpec`.
