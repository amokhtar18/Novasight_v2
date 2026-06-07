/**
 * TypeScript counterparts to backend Pydantic schemas.
 * Source of truth: backend/app/schemas/{dataset,query}.py
 * Keep these in sync when the backend schemas change.
 */

// ---------------------------------------------------------------------------
// Dataset
// ---------------------------------------------------------------------------

export interface DatasetRead {
  id: string; // uuid — serialised as string
  name: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  status: string;
  created_at: string; // ISO-8601 datetime string
}

// ---------------------------------------------------------------------------
// Query
// ---------------------------------------------------------------------------

export type AggFunction = "count" | "sum" | "avg" | "min" | "max";
export type FilterOp = "=" | "!=" | "<" | "<=" | ">" | ">=";

export interface Metric {
  function: AggFunction;
  /** Required for every function except "count". */
  column?: string;
  alias?: string;
}

export interface Filter {
  column: string;
  op: FilterOp;
  value: string | number | boolean;
}

export interface QueryRequest {
  dimensions: string[];
  metrics: Metric[];
  filters?: Filter[];
  limit?: number;
}

export interface QueryResponse {
  columns: string[];
  rows: unknown[][];
  row_count: number;
}

// ---------------------------------------------------------------------------
// Chart spec — the shared contract (Task 3.1)
// ---------------------------------------------------------------------------

/**
 * Declarative description of one chart. The SAME shape is produced by manual
 * configuration (the builder / explore view) and by the AI NL→chart endpoint,
 * so manual and AI charts share one renderer.
 *
 * This mirrors `backend/app/schemas/chart.py` field-for-field (snake_case, so the
 * JSON is identical on both sides). The contract is documented in
 * `docs/CHART_SPEC.md`. The spec carries no SQL: `query` describes a structured
 * aggregation, and encoding `field` values are display references to columns in a
 * `QueryResponse`.
 */
export type ChartType = "bar" | "line" | "area" | "pie" | "table";

/** Where a chart's data comes from. At least one source must be present. */
export interface ChartQuery {
  /** Dataset the inline query runs against (Phase 1 path). */
  dataset_id?: string | null; // uuid
  /** Inline structured aggregation, compiled to safe read-only SQL server-side. */
  query?: QueryRequest | null;
  /** Governed metric names resolved by the semantic layer (AI path). */
  metric_refs?: string[];
}

/** One plotted series: which result column to read, and how to label it. */
export interface SeriesEncoding {
  /** Column name in QueryResponse.columns to read values from. */
  field: string;
  /** Legend label; defaults to `field` when omitted. */
  name?: string | null;
  /** Optional explicit colour (e.g. "#3b82f6"); the renderer picks one if null. */
  color?: string | null;
}

/** How query columns map onto the chart's visual channels. */
export interface ChartEncoding {
  /** Category axis (x for bar/line/area, slice label for pie). Optional for table. */
  x?: string | null;
  /** Value series (for a table, the columns to display). At least one. */
  series: SeriesEncoding[];
}

/** Display-only options. None of these affect the query or the data. */
export interface ChartOptions {
  title?: string | null;
  stacked?: boolean;
  show_legend?: boolean;
  x_axis_label?: string | null;
  y_axis_label?: string | null;
}

export interface ChartSpec {
  /** Contract version. Current: "1". */
  version?: string;
  type: ChartType;
  query: ChartQuery;
  encoding: ChartEncoding;
  options?: ChartOptions;
}

// ---------------------------------------------------------------------------
// NL→chart endpoint — POST /api/v1/ai/chart (Task 4.4)
// ---------------------------------------------------------------------------

/**
 * Request body for the NL→chart endpoint.
 * Mirrors backend `NLChartRequest` schema (snake_case wire shape).
 */
export interface NLChartRequest {
  /** Natural-language description of the desired chart (1–2000 chars, non-empty). */
  request: string;
}

/**
 * Success (200) response from the NL→chart endpoint.
 * `spec` is the AI-generated ChartSpec; `data` is the pre-fetched QueryResponse
 * whose columns align to the encoding fields in `spec`.
 * Both are fed directly into `ChartRenderer` — the same renderer used for
 * manually-configured charts.
 */
export interface NLChartResponse {
  spec: ChartSpec;
  data: QueryResponse;
}

// ---------------------------------------------------------------------------
// Semantic layer — /api/v1/semantic  (mirrors schemas/semantic.py)
// ---------------------------------------------------------------------------

/** One governed measure or dimension exposed by a semantic model. */
export interface SemanticField {
  /** Fully-qualified Cube identifier, e.g. "regional_sales.region". */
  name: string;
  /** Human-readable label for display in the builder. */
  title: string;
  /** Cube member type (e.g. "number", "string", "time"). */
  type: string;
}

/** A governed model (Cube cube/view) the tenant may query. */
export interface SemanticModelRead {
  name: string;
  title: string;
  measures: SemanticField[];
  dimensions: SemanticField[];
}

/** A structured, grounded query against the semantic layer. */
export interface SemanticQueryRequest {
  measures: string[];
  dimensions: string[];
  /** Ordering, e.g. { "regional_sales.total_amount": "desc" }. */
  order?: Record<string, "asc" | "desc">;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Semantic-model registry (wizard definitions) — /api/v1/semantic-models
// (mirrors schemas/semantic_model.py). Distinct from SemanticModelRead above,
// which is the *governed Cube meta* the query path reads.
// ---------------------------------------------------------------------------

export type MeasureType = "count" | "sum" | "avg" | "min" | "max" | "count_distinct";
export type DimensionType = "string" | "number" | "time" | "boolean";

export interface MeasureDef {
  name: string;
  type: MeasureType;
  /** Column to aggregate; optional only for "count". */
  sql?: string | null;
  title?: string | null;
  description?: string | null;
}

export interface DimensionDef {
  name: string;
  type: DimensionType;
  sql: string;
  title?: string | null;
  description?: string | null;
  primary_key?: boolean;
}

export interface SemanticModelConfig {
  measures: MeasureDef[];
  dimensions: DimensionDef[];
}

export interface SemanticModelDefRead {
  id: string;
  name: string;
  base_table: string;
  config: SemanticModelConfig;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface SemanticModelDefCreate {
  name: string;
  base_table: string;
  config: SemanticModelConfig;
  enabled?: boolean;
}

// ---------------------------------------------------------------------------
// Saved charts — /api/v1/charts  (mirrors schemas/saved_chart.py)
// ---------------------------------------------------------------------------

export type ChartSourceKind = "semantic" | "dataset";

/** Body for POST /charts — persist a named ChartSpec. */
export interface ChartCreate {
  name: string;
  spec: ChartSpec;
  source_kind?: ChartSourceKind;
  source_ref?: string | null;
}

/** A saved chart as returned by the API. */
export interface SavedChartRead {
  id: string;
  name: string;
  spec: ChartSpec;
  source_kind: string;
  source_ref: string | null;
  owner_id: string | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Dashboards — /api/v1/dashboards  (mirrors schemas/dashboard.py)
// ---------------------------------------------------------------------------

/** A dashboard tile: a placed saved chart (chart embedded for one-round-trip render). */
export interface DashboardTileRead {
  id: string;
  chart_id: string;
  title: string | null;
  position: number;
  x: number;
  y: number;
  w: number;
  h: number;
  chart: SavedChartRead;
}

/** A dashboard in the list view (no tiles, just a count). */
export interface DashboardSummary {
  id: string;
  name: string;
  description: string | null;
  owner_id: string | null;
  tile_count: number;
  created_at: string;
  updated_at: string;
}

/** A dashboard with its ordered tiles (detail view). */
export interface DashboardRead {
  id: string;
  name: string;
  description: string | null;
  owner_id: string | null;
  created_at: string;
  updated_at: string;
  tiles: DashboardTileRead[];
}

export interface DashboardCreate {
  name: string;
  description?: string | null;
}

export interface DashboardUpdate {
  name?: string | null;
  description?: string | null;
}

export interface DashboardTileCreate {
  chart_id: string;
  title?: string | null;
  w?: number | null;
  h?: number | null;
}

/** One tile's placement, for bulk layout persistence (dnd-kit drag/resize). */
export interface TileLayout {
  id: string;
  position: number;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

export interface DashboardLayoutUpdate {
  tiles: TileLayout[];
}

// ---------------------------------------------------------------------------
// Tenant context — GET /api/v1/me  (mirrors schemas/me.py)
// ---------------------------------------------------------------------------

export interface TenantContextRead {
  tenant_id: string;
  iceberg_namespace: string;
  clickhouse_db: string;
  dbt_schema: string;
}

/** GET /api/v1/me — tenant context plus the verified caller identity. */
export interface MeRead extends TenantContextRead {
  subject: string;
  email: string;
  tenant: string;
  roles: string[];
}

// ---------------------------------------------------------------------------
// Auth — /api/v1/auth/*  (mirrors schemas/auth.py)
// ---------------------------------------------------------------------------

export interface LoginRequest {
  email: string;
  password: string;
  /** Tenant slug; omit to use the seed tenant (single-tenant on-prem). */
  tenant?: string;
}

export interface UserIdentity {
  id: string;
  email: string;
  name: string | null;
  tenant: string;
  roles: string[];
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: UserIdentity;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

// ---------------------------------------------------------------------------
// User management — /api/v1/users  (mirrors schemas/user.py)
// ---------------------------------------------------------------------------

export interface UserRead {
  id: string;
  email: string;
  name: string | null;
  roles: string[];
  is_active: boolean;
}

export interface UserCreate {
  email: string;
  password: string;
  name?: string | null;
  roles?: string[];
}

export interface UserUpdate {
  name?: string | null;
  password?: string | null;
  roles?: string[] | null;
  is_active?: boolean | null;
}

// ---------------------------------------------------------------------------
// Health — GET /api/v1/health  (mirrors schemas/health.py)
// ---------------------------------------------------------------------------

export interface ComponentStatus {
  name: string;
  status: string; // "up" | "down"
  detail?: string | null;
}

export interface HealthRead {
  status: string; // "healthy" | "degraded"
  components: ComponentStatus[];
}

// ---------------------------------------------------------------------------
// NL→SQL — POST /api/v1/ai/query
// ---------------------------------------------------------------------------

export interface NLQueryRequest {
  /** Natural-language question (1–2000 chars). */
  question: string;
}

export interface NLQueryResponse {
  /** The validated SQL that was executed (post-validation form). */
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
}

// ---------------------------------------------------------------------------
// Insights — POST /api/v1/ai/insights
// ---------------------------------------------------------------------------

export interface InsightRequest {
  columns: string[];
  rows: unknown[][];
  /** Optional context, e.g. the dashboard title or originating question. */
  context_hint?: string | null;
}

export interface InsightResponse {
  summary: string;
}

// ---------------------------------------------------------------------------
// Dataset suggestions — POST /api/v1/ai/datasets/{id}/suggestions
// ---------------------------------------------------------------------------

export interface SuggestionItem {
  title: string;
  rationale: string;
  spec: ChartSpec;
}

export interface SuggestionsResponse {
  suggestions: SuggestionItem[];
  note?: string | null;
}

// ---------------------------------------------------------------------------
// Tenant provisioning (platform admin) — /api/v1/tenants  (schemas/tenant.py)
// ---------------------------------------------------------------------------

export interface TenantProvisionRequest {
  slug: string;
  name: string;
  admin_email: string;
}

export interface TenantRead {
  id: string;
  slug: string;
  name: string;
  status: string;
  iceberg_namespace: string;
  clickhouse_db: string;
  dbt_schema: string;
}
