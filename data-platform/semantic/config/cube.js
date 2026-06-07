/**
 * Cube server configuration — multi-tenancy + security wiring.
 *
 * Golden rule 1: no connection strings, database names, passwords, or tenant
 * identifiers are hardcoded here. Every value comes from environment variables
 * (CUBEJS_DB_*, CUBEJS_API_SECRET, CUBEJS_SERVING_REGIONAL_SALES_TABLE) or from
 * the per-request JWT security context.
 *
 * Golden rule 2: tenant isolation is enforced at two levels:
 *   1. contextToAppId — Cube caches compiled schemas per appId. The appId is
 *      derived from securityContext.clickhouse_db, so tenant A's compiled model
 *      never leaks into tenant B's query.
 *   2. contextToOrchestratorId — each tenant gets a dedicated query orchestrator
 *      (connection pool slice), preventing cross-tenant connection sharing.
 *   3. The sql_table in regional_sales.js references
 *      COMPILE_CONTEXT.securityContext.clickhouse_db, so an absent or mismatched
 *      clickhouse_db causes a compile error rather than falling back to a shared DB.
 *
 * Security context flow:
 *   1. Backend resolves TenantContext from the authenticated principal (OIDC claim →
 *      tenant registry lookup — never from client body).
 *   2. Backend mints a short-lived HS256 JWT signed with CUBEJS_API_SECRET:
 *        { "clickhouse_db": "<tenant_clickhouse_db>", "exp": <now + 3600> }
 *   3. That JWT is passed as Bearer in the Authorization header to Cube's load
 *      endpoint (/cubejs-api/v1/load).
 *   4. Cube verifies the signature, then calls the checkAuth callback below, which
 *      extracts the claim and populates securityContext.
 *   5. contextToAppId is called with that securityContext — the compiled schema is
 *      keyed to this tenant's DB.
 *   6. The sql_table in the data model resolves to the correct tenant DB at compile
 *      time.
 *
 * Fail-closed: if clickhouse_db is absent from the JWT, checkAuth throws 403 and no
 * query is executed. There is no fallback database.
 */

const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// Model roots (mounted in compose):
//   model-shared — hand-written static cubes, shared by all tenants (regional_sales)
//   model-tenant/<clickhouse_db>/ — codegen output, one subdir per tenant
// Both are siblings of this config file (/cube/conf).
// ---------------------------------------------------------------------------
const SHARED_DIR = path.join(__dirname, "model-shared");
const TENANT_ROOT = path.join(__dirname, "model-tenant");

// Read all *.js / *.yml model files in a directory (non-recursive) as
// { fileName, content } records. Missing directory → []. Never throws.
function readModelFiles(dir) {
  let names = [];
  try {
    names = fs.readdirSync(dir);
  } catch (e) {
    return [];
  }
  const files = [];
  for (const name of names) {
    if (!/\.(js|yml|yaml)$/.test(name)) continue;
    const full = path.join(dir, name);
    try {
      if (!fs.statSync(full).isFile()) continue;
      files.push({ fileName: name, content: fs.readFileSync(full, "utf-8") });
    } catch (e) {
      /* skip unreadable entries */
    }
  }
  return files;
}

module.exports = {
  // ---------------------------------------------------------------------------
  // Per-tenant model loading (directory-level isolation).
  //
  // Each request is scoped to securityContext.clickhouse_db. We serve that tenant
  // the shared static cubes PLUS only its own generated subdir — so one tenant's
  // catalog is never even parsed for another (stronger than an in-file guard).
  // The backend codegen writes model-tenant/<db>/models.js (see
  // backend/app/codegen/cube_model.py); a missing/absent db yields shared-only.
  // ---------------------------------------------------------------------------
  repositoryFactory: ({ securityContext }) => ({
    dataSchemaFiles: async () => {
      const shared = readModelFiles(SHARED_DIR);
      const db = securityContext && securityContext.clickhouse_db;
      const tenant = db ? readModelFiles(path.join(TENANT_ROOT, db)) : [];
      // Prefix tenant filenames so they can never collide with a shared file.
      return shared.concat(
        tenant.map((f) => ({ fileName: `t_${db}__${f.fileName}`, content: f.content }))
      );
    },
  }),

  // ---------------------------------------------------------------------------
  // Per-tenant recompile trigger for dynamic (wizard-generated) models.
  //
  // Cube caches a compiled schema per appId (contextToAppId, keyed on
  // clickhouse_db), so without a version signal a tenant would keep an old schema
  // after editing a model. We key schemaVersion on the tenant's generated file's
  // mtime: every codegen write bumps it, forcing a recompile. Tenants with no
  // generated file (shared cubes only) get a stable constant — no needless work.
  // ---------------------------------------------------------------------------
  schemaVersion: ({ securityContext }) => {
    const db = securityContext && securityContext.clickhouse_db;
    if (!db) return "0";
    const file = path.join(TENANT_ROOT, db, "models.js");
    try {
      return String(fs.statSync(file).mtimeMs);
    } catch (e) {
      return "0"; // no generated models for this tenant yet
    }
  },

  // ---------------------------------------------------------------------------
  // Authentication — Cube's BUILT-IN JWT verification.
  //
  // We deliberately do NOT define a custom `checkAuth`. Defining one disables
  // Cube's built-in JWT decode/verify, leaving the decoded payload unavailable
  // (the `auth` arg is undefined) and surfacing auth failures as HTTP 500.
  //
  // Instead, with CUBEJS_API_SECRET set (see compose env), Cube verifies the
  // HS256 Bearer token on every request and populates `securityContext` with the
  // decoded claims — so `securityContext.clickhouse_db` is the tenant DB the
  // backend signed in. An absent/expired/invalid token is rejected with a proper
  // 403 by Cube itself; a validly-signed token that omits `clickhouse_db` is
  // failed closed by `contextToAppId` below (no fallback database).
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Multi-tenant compiled-schema isolation
  //
  // Cube caches one compiled schema per appId. By keying on clickhouse_db, each
  // tenant's schema compilation is independent and cannot bleed across tenants.
  // ---------------------------------------------------------------------------
  contextToAppId: ({ securityContext }) => {
    if (!securityContext || !securityContext.clickhouse_db) {
      throw new Error(
        "contextToAppId: securityContext.clickhouse_db is missing. " +
        "Refusing to compile without a tenant scope."
      );
    }
    return `CUBE_APP__${securityContext.clickhouse_db}`;
  },

  // ---------------------------------------------------------------------------
  // Dedicated orchestrator per tenant — prevents connection-pool cross-tenant
  // sharing. Uses the same key as contextToAppId.
  // ---------------------------------------------------------------------------
  contextToOrchestratorId: ({ securityContext }) => {
    if (!securityContext || !securityContext.clickhouse_db) {
      throw new Error(
        "contextToOrchestratorId: securityContext.clickhouse_db is missing."
      );
    }
    return `CUBE_ORCH__${securityContext.clickhouse_db}`;
  },

  // ---------------------------------------------------------------------------
  // Environment variable pass-through into COMPILE_CONTEXT.env
  //
  // Cube only exposes env vars to the data model that are explicitly listed here.
  // We expose exactly one: the serving table name, so the model can read it via
  // COMPILE_CONTEXT.env.CUBEJS_SERVING_REGIONAL_SALES_TABLE without having access
  // to secrets.
  // ---------------------------------------------------------------------------
  compilerCacheSize: 200,       // cache up to 200 tenant compiled schemas in memory

  // Extend COMPILE_CONTEXT with env vars the model files may reference.
  // This runs at schema compile time, not per request.
  //
  // Fail closed (golden rule 1): if the serving-table name is unset, refuse to
  // compile rather than letting the model's `sql_table` template interpolate an
  // `undefined` table name (which is a valid SQL identifier and would only fail
  // later as an opaque ClickHouse "table doesn't exist" runtime error).
  extendContext: (req) => {
    const servingTable = process.env.CUBEJS_SERVING_REGIONAL_SALES_TABLE;
    if (!servingTable) {
      throw new Error(
        "CUBEJS_SERVING_REGIONAL_SALES_TABLE must be set — refusing to compile " +
        "the model with an undefined serving-table name."
      );
    }
    return { env: { CUBEJS_SERVING_REGIONAL_SALES_TABLE: servingTable } };
  },
};
