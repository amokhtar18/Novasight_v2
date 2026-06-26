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
// Chart kinds the renderer supports (v2, #8). Mirrors schemas/chart.py.
export type ChartType =
  | "bar"
  | "hbar"
  | "line"
  | "area"
  | "combo"
  | "pie"
  | "donut"
  | "scatter"
  | "funnel"
  | "treemap"
  | "radar"
  | "gauge"
  | "table"
  | "number";

/** Where a chart's data comes from. At least one source must be present. */
export interface ChartQuery {
  /** Dataset the inline query runs against (Phase 1 path). */
  dataset_id?: string | null; // uuid
  /** Inline structured aggregation, compiled to safe read-only SQL server-side. */
  query?: QueryRequest | null;
  /** Governed metric names resolved by the semantic layer (AI path). */
  metric_refs?: string[];
  /**
   * Plain (non-time) governed dimensions to group by. The first is the category axis
   * (`encoding.x`); any others are breakdown dimensions (`encoding.breakdown`) pivoted
   * into series. Empty for legacy single-dimension specs (dimension on `encoding.x`).
   */
  dimensions?: string[];
  /**
   * Time dimensions for a semantic chart — carried on the spec so a saved/AI chart
   * re-runs with the same granularity rollup. The resolved `<dimension>.<granularity>`
   * key is what `encoding.x` reads.
   */
  time_dimensions?: SemanticTimeDimension[];
  /** Governed filters carried on the spec; re-validated server-side. */
  filters?: SemanticFilter[];
  /** Server-side ordering, e.g. { "sales.total": "desc" }. */
  order?: Record<string, "asc" | "desc">;
  /** Per-chart row cap; clamped server-side. */
  limit?: number | null;
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
  /**
   * Breakdown dimensions: dimension columns whose values are pivoted into one series
   * each at render time. When present, `series[0]` is the measure that supplies the
   * pivoted values. Empty for a plain chart where `series` lists measures directly.
   */
  breakdown?: string[];
}

/** How numeric values are formatted in labels, tooltips, and value axes (#8). */
export interface NumberFormat {
  style?: "plain" | "currency" | "percent";
  decimals?: number | null;
  compact?: boolean;
  currency?: string | null;
}

export type ChartSort =
  | "none"
  | "value_desc"
  | "value_asc"
  | "label_asc"
  | "label_desc";

/** Display-only options (#8). None of these affect the query or the data. */
export interface ChartOptions {
  title?: string | null;
  stacked?: boolean;
  percent?: boolean;
  show_legend?: boolean;
  legend_position?: "top" | "bottom" | "left" | "right";
  x_axis_label?: string | null;
  y_axis_label?: string | null;
  y_min?: number | null;
  y_max?: number | null;
  log_scale?: boolean;
  data_labels?: boolean;
  sort?: ChartSort;
  number_format?: NumberFormat;
  palette?: string[];
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

/** Cube filter operators exposed by the semantic query API (mirrors schemas/semantic.py). */
export type SemanticFilterOperator =
  | "equals"
  | "notEquals"
  | "contains"
  | "notContains"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "set"
  | "notSet";

/** A filter on a governed member: `member <operator> values`. */
export interface SemanticFilter {
  member: string;
  operator: SemanticFilterOperator;
  /** Empty for `set`/`notSet`; at least one value otherwise. */
  values: string[];
}

/** Cube time-dimension granularities (mirrors schemas/semantic.py). */
export type SemanticGranularity =
  | "second"
  | "minute"
  | "hour"
  | "day"
  | "week"
  | "month"
  | "quarter"
  | "year";

/** Relative time-range tokens (mirrors schemas/semantic.py RelativeDateRange). */
export type RelativeDateRange =
  | "last_7_days"
  | "last_30_days"
  | "last_90_days"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "last_quarter"
  | "this_year"
  | "last_year";

/**
 * A time dimension to group by, optionally rolled up to a `granularity`.
 * With a granularity Cube returns the bucket under the `<dimension>.<granularity>`
 * key — the column a time chart reads for its axis.
 */
export interface SemanticTimeDimension {
  dimension: string;
  granularity?: SemanticGranularity | null;
  /** Time-range filter: a relative token or an absolute [from, to] ISO-date pair. */
  date_range?: RelativeDateRange | string[] | null;
}

/** A structured, grounded query against the semantic layer. */
export interface SemanticQueryRequest {
  measures: string[];
  dimensions: string[];
  /** Time dimensions to group by (each optionally rolled up to a granularity). */
  time_dimensions?: SemanticTimeDimension[];
  /** Ordering, e.g. { "regional_sales.total_amount": "desc" }. */
  order?: Record<string, "asc" | "desc">;
  /** Filters on governed members; each is re-validated server-side. */
  filters?: SemanticFilter[];
  limit?: number;
}

// ---------------------------------------------------------------------------
// ETL: source connections — /api/v1/sources  (mirrors schemas/source.py)
// ---------------------------------------------------------------------------

export interface SourceConnectionRead {
  id: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  status: string;
  has_secret: boolean;
}

export interface SourceConnectionCreate {
  name: string;
  kind: string;
  config: Record<string, unknown>;
  /** Credentials (e.g. { password }); encrypted at rest. Omit when none. */
  secret?: Record<string, unknown> | null;
}

/** PATCH /sources/{id} — partial; omit `secret` to keep the stored one. */
export interface SourceConnectionUpdate {
  name?: string;
  config?: Record<string, unknown>;
  secret?: Record<string, unknown> | null;
  status?: string;
}

export interface SourceTestResponse {
  ok: boolean;
  detail?: string | null;
}

/** A SQL engine the connection wizard offers (GET /sources/engines). */
export interface EngineSpec {
  key: string;
  label: string;
  default_port: number;
  supports_schemas: boolean;
  database_label: string;
}

// ---------------------------------------------------------------------------
// ETL: pipelines — /api/v1/pipelines  (mirrors schemas/pipeline.py)
// ---------------------------------------------------------------------------

export type WriteDisposition = "overwrite" | "append" | "merge" | "incremental";

export type TargetType =
  | "String"
  | "Int64"
  | "Float64"
  | "Decimal"
  | "Boolean"
  | "Date"
  | "DateTime"
  | "JSON"
  | "UUID";

export type ScdType = "none" | "scd1" | "scd2";

export type FilterOperator =
  | "eq"
  | "ne"
  | "gt"
  | "ge"
  | "lt"
  | "le"
  | "like"
  | "in"
  | "is_null"
  | "is_not_null";

/** One source column mapped to a destination column (mirrors schemas/pipeline.ColumnMap). */
export interface ColumnMap {
  source_name: string;
  source_type?: string;
  target_name: string;
  target_type?: TargetType;
  included?: boolean;
}

/** A structured source-side predicate (mirrors schemas/pipeline.FilterClause). */
export interface FilterClause {
  column: string;
  operator: FilterOperator;
  value?: string | number | boolean | Array<string | number> | null;
}

export interface PipelineConfig {
  /** Source object to extract: a DB table name, or a file key for filesystem. */
  object: string;
  write_disposition?: WriteDisposition;
  source_schema?: string | null;
  columns?: ColumnMap[];
  primary_key?: string[];
  partition_by?: string[];
  source_filters?: FilterClause[];
  scd_type?: ScdType;
  cdc_column?: string | null;
}

/** One column from POST /sources/{id}/introspect (schema+table given). */
export interface IntrospectColumn {
  name: string;
  source_type: string;
  suggested_target_type: TargetType;
}

/** Response from POST /sources/{id}/introspect (one level populated per call). */
export interface SourceIntrospectResponse {
  schemas: string[];
  tables: string[];
  columns: IntrospectColumn[];
}

export interface PipelineRead {
  id: string;
  name: string;
  source_connection_id: string;
  config: PipelineConfig;
  target_table: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface PipelineCreate {
  name: string;
  source_connection_id: string;
  config: PipelineConfig;
  target_table: string;
  enabled?: boolean;
}

/** PATCH /pipelines/{id} — partial update. */
export interface PipelineUpdate {
  name?: string;
  config?: PipelineConfig;
  target_table?: string;
  enabled?: boolean;
}

export interface PipelineRunRead {
  id: string;
  pipeline_id: string;
  status: string;
  dagster_run_id: string | null;
  rows: number | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
}

/** A run joined with its pipeline's name — the tenant-wide monitoring feed. */
export interface PipelineRunSummary extends PipelineRunRead {
  pipeline_name: string;
}

// Schedules — /api/v1/schedules (mirrors schemas/schedule.py)
// A reusable schedule drives one or more pipelines (#3, M:N).
export interface ScheduleRead {
  id: string;
  name: string;
  target_kind: string;
  /** Pipelines this schedule drives. */
  pipeline_ids: string[];
  cron: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScheduleCreate {
  name: string;
  target_kind?: "pipeline";
  /** One or more pipelines to attach (must be non-empty). */
  pipeline_ids: string[];
  cron: string;
  enabled?: boolean;
}

export interface ScheduleUpdate {
  name?: string;
  cron?: string;
  enabled?: boolean;
  /** When provided, replaces the schedule's attached pipelines (non-empty). */
  pipeline_ids?: string[];
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

export type SemanticJoinRelationship = "one_to_one" | "one_to_many" | "many_to_one";

/**
 * A join from this model to another cube by column equality. Single-key
 * (local_key/foreign_key) or composite (local_keys/foreign_keys, equal length) — #6.
 */
export interface SemanticJoinDef {
  name: string;
  relationship: SemanticJoinRelationship;
  local_key?: string | null;
  foreign_key?: string | null;
  local_keys?: string[];
  foreign_keys?: string[];
}

/** A serving-table column — GET /api/v1/serving/tables/{table}/columns. */
export interface ServingColumn {
  name: string;
  type: string;
}

export interface SemanticModelConfig {
  measures: MeasureDef[];
  dimensions: DimensionDef[];
  joins?: SemanticJoinDef[];
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

/** PATCH /semantic-models/{id} — partial update. */
export interface SemanticModelDefUpdate {
  name?: string;
  base_table?: string;
  config?: SemanticModelConfig;
  enabled?: boolean;
}

// ---------------------------------------------------------------------------
// dbt model + test registry (wizard) — /api/v1/dbt-models
// (mirrors schemas/dbt_model.py)
// ---------------------------------------------------------------------------

export type DbtLayer = "staging" | "intermediate" | "marts";
export type DbtMaterialization = "view" | "table" | "incremental";
export type DbtTestType = "not_null" | "unique" | "accepted_values" | "relationships";
export type DbtIncrementalStrategy =
  | "append"
  | "merge"
  | "delete+insert"
  | "insert_overwrite";
export type DbtOnSchemaChange =
  | "ignore"
  | "fail"
  | "append_new_columns"
  | "sync_all_columns";

/** dbt incremental settings — only applied when materialization is "incremental". */
export interface DbtIncrementalConfig {
  unique_key?: string[];
  incremental_strategy?: DbtIncrementalStrategy | null;
  on_schema_change?: DbtOnSchemaChange | null;
}

export interface DbtTestDef {
  column_name?: string | null;
  test_type: DbtTestType;
  config?: Record<string, unknown>;
}

export interface DbtTestReadModel {
  id: string;
  column_name: string | null;
  test_type: string;
  config: Record<string, unknown>;
}

export interface DbtModelDefRead {
  id: string;
  name: string;
  layer: string;
  materialization: string;
  sql: string | null;
  config: Record<string, unknown>;
  incremental?: DbtIncrementalConfig | null;
  enabled: boolean;
  tests: DbtTestReadModel[];
  created_at: string;
  updated_at: string;
}

// dbt lineage DAG — GET /api/v1/dbt-models/lineage (mirrors services/dbt_lineage.py)
export interface LineageNode {
  /** Namespaced id, e.g. "model:mart_orders". */
  id: string;
  label: string;
  /** "model" | "source" | "external". */
  kind: string;
  layer?: string | null;
}

export interface LineageEdge {
  source: string;
  target: string;
}

export interface LineageGraph {
  nodes: LineageNode[];
  edges: LineageEdge[];
}

export interface DbtModelDefCreate {
  name: string;
  layer?: DbtLayer;
  materialization?: DbtMaterialization;
  sql: string;
  config?: Record<string, unknown>;
  incremental?: DbtIncrementalConfig | null;
  tests?: DbtTestDef[];
  enabled?: boolean;
}

/** PATCH /dbt-models/{id} — partial update (`tests`, if given, replaces all). */
export interface DbtModelDefUpdate {
  name?: string;
  layer?: DbtLayer;
  materialization?: DbtMaterialization;
  sql?: string;
  config?: Record<string, unknown>;
  incremental?: DbtIncrementalConfig | null;
  tests?: DbtTestDef[];
  enabled?: boolean;
}

/** Result of launching a dbt model build via Dagster (POST /dbt-models/{id}/run). */
export interface DbtRunRead {
  transform_job_id: string;
  selection: string;
  dagster_run_id: string;
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
// What a dashboard tile holds (#10): a pinned chart, or a decoration object.
export type TileKind = "chart" | "text" | "markdown" | "image" | "divider" | "filter";

export interface DashboardTileRead {
  id: string;
  kind: TileKind;
  /** Set for chart tiles; null for decoration tiles. */
  chart_id: string | null;
  /** Payload for non-chart tiles (text/markdown body, image url, filter member, …). */
  content: Record<string, unknown> | null;
  title: string | null;
  position: number;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Embedded chart for chart tiles; null for decoration tiles. */
  chart: SavedChartRead | null;
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
  /** View-time filters applied across the dashboard's matching semantic tiles. */
  filters?: SemanticFilter[];
  tiles: DashboardTileRead[];
}

export interface DashboardCreate {
  name: string;
  description?: string | null;
}

export interface DashboardUpdate {
  name?: string | null;
  description?: string | null;
  /** Replaces the dashboard's view-time filters when provided. */
  filters?: SemanticFilter[];
}

export interface DashboardTileCreate {
  /** Defaults to "chart". A chart tile needs chart_id; decorations carry content. */
  kind?: TileKind;
  chart_id?: string | null;
  content?: Record<string, unknown> | null;
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
// Chat — POST /api/v1/ai/chat  (grounded tool-calling over the semantic layer)
// ---------------------------------------------------------------------------

export interface ChatRequest {
  /** A natural-language question about the tenant's data (1–2000 chars). */
  message: string;
}

export interface ChatResponse {
  /** Grounded answer — figures trace to tool results. */
  answer: string;
  /** Names of the grounded tools the assistant called (for transparency). */
  tools_used: string[];
  /** A validated chart when the assistant generated one (nl_to_chart), for pinning. */
  chart?: ChartSpec | null;
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
// Unified assistant — POST /api/v1/ai/assistant  (#7/#11)
// ---------------------------------------------------------------------------

export interface AssistantRequest {
  message: string;
}

export interface AssistantResponse {
  /** Grounded answer — figures trace to skill results. */
  answer: string;
  /** Grounded skills the assistant called (for transparency). */
  tools_used: string[];
  /** Validated charts the assistant proposed, for the user to save/pin. */
  charts: ChartSpec[];
  /** Guardrailed insight summaries the assistant produced. */
  insights: string[];
}

// ---------------------------------------------------------------------------
// AI provider health probe — GET /api/v1/ai/health
// ---------------------------------------------------------------------------

export interface AIHealthResponse {
  /** True when a minimal completion round-tripped through the configured provider. */
  ok: boolean;
  /** Model that answered the probe (on success). */
  model?: string | null;
  /** Round-trip latency in milliseconds (on success). */
  latency_ms?: number | null;
  /** Safe status detail on failure (never includes the API key). */
  detail?: string | null;
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
