/**
 * Cube data model: regional_sales
 *
 * Golden rule 1 — config-driven: the serving table name comes from the
 * CUBEJS_SERVING_REGIONAL_SALES_TABLE environment variable (no default; must be
 * supplied). The ClickHouse database comes from the per-request security context
 * (securityContext.clickhouse_db) — never from env or a literal.
 *
 * Golden rule 2 — tenant isolation: sql_table is scoped to the database carried in
 * the JWT security context. Cube compiles a separate query plan per
 * securityContext.clickhouse_db value (contextToAppId), so one tenant's compiled
 * model can never bleed into another tenant's query.
 *
 * The security context is populated by the backend: it mints a short-lived HS256 JWT
 * signed with CUBEJS_API_SECRET whose payload contains:
 *   { "clickhouse_db": "<tenant_clickhouse_db>" }
 * Cube extracts that claim and injects it into COMPILE_CONTEXT.securityContext.
 *
 * Columns on the serving table (data-platform/orchestration/…/serving.py):
 *   region              String
 *   amount              Float64 / Decimal
 *   amount_share_pct    Float64 / Decimal
 *   sales_rank          Int32 / UInt32
 */

cube(`regional_sales`, {
  sql_table: `\`${COMPILE_CONTEXT.securityContext.clickhouse_db}\`.\`${COMPILE_CONTEXT.env.CUBEJS_SERVING_REGIONAL_SALES_TABLE}\``,

  // ---------------------------------------------------------------------------
  // Measures
  // ---------------------------------------------------------------------------
  measures: {
    total_amount: {
      sql: `amount`,
      type: `sum`,
      title: `Total Amount`,
      description: `Sum of sales amount across all rows in the result set.`,
    },

    avg_share: {
      sql: `amount_share_pct`,
      type: `avg`,
      title: `Average Share %`,
      description: `Average share-of-total percentage across selected regions.`,
    },
  },

  // ---------------------------------------------------------------------------
  // Dimensions
  // ---------------------------------------------------------------------------
  dimensions: {
    region: {
      sql: `region`,
      type: `string`,
      title: `Region`,
      description: `Sales region name.`,
      primaryKey: true,   // region is the grain of the serving table (one row per region)
      public: true,       // primaryKey members are hidden by default; region is a
                          // first-class queryable dimension, so expose it explicitly.
    },

    sales_rank: {
      sql: `sales_rank`,
      type: `number`,
      title: `Sales Rank`,
      description: `Rank of the region by sales amount (lower = higher sales).`,
    },
  },

  // ---------------------------------------------------------------------------
  // Pre-aggregations — none defined at this stage.
  // Add a rollup here once query volume warrants it; the cube name and measure
  // identifiers above will remain stable.
  // ---------------------------------------------------------------------------
  preAggregations: {},
});
