"""Validate stage -- parse and guardrail AI-generated SQL before any execution.

This module is the security-critical chokepoint between LLM output and the
database.  It is called BEFORE any query reaches ClickHouse.

## Guardrails enforced (in order)

1. **UNSATISFIABLE sentinel** -- if the LLM returned ``UNSATISFIABLE`` the
   question cannot be answered from the semantic layer; raise immediately.
2. **Parse** -- parse with sqlglot (ClickHouse dialect).  Unparseable SQL is
   rejected.
3. **Single statement** -- exactly one statement; multi-statement / stacked
   queries are rejected (protects against SQL injection via stacking).
4. **Read-only** -- the statement must be a ``SELECT``.  Any
   INSERT/UPDATE/DELETE/MERGE/ALTER/CREATE/DROP/TRUNCATE/CALL/ATTACH/SET or
   other write/DDL/DML is rejected.
5. **Allow-list + TVF rejection** -- every table reference must be in the
   configured set of governed physical tables.  References to unlisted tables
   (``secrets``, ``users``, raw physical tables, CTEs from outer subqueries,
   etc.) are rejected.  Any ``exp.Table`` node whose ``this`` child is an
   ``exp.Anonymous`` expression (i.e. a table-valued function such as
   ``url()``, ``remote()``, ``s3()``, ``mysql()``, ``cluster()``, etc.) is
   unconditionally rejected as a potential SSRF / external-data-read /
   exfiltration vector, before the empty-name guard.  The allow-list also
   rejects any table whose name is empty or whitespace (defense in depth
   against TVFs or other constructs that produce a nameless ``exp.Table``
   node).
6. **Tenant DB isolation** -- any table reference with an explicit database
   qualifier that does NOT match ``ctx.clickhouse_db`` is rejected.  This
   guards against an LLM-emitted ``other_tenant_db.table`` that would resolve
   cross-tenant even though the connection default-db is correct.
7. **Row cap + SETTINGS strip** -- if no LIMIT clause is present, inject
   ``LIMIT <max_query_rows>``.  Clamp any existing LIMIT to
   ``max_query_rows``.  Strip any ``SETTINGS`` clause, ``INTO OUTFILE``
   clause, and ``FORMAT`` clause from the AST before regenerating SQL.
   ``SETTINGS`` can disable server-side timeouts and memory caps (DoS vector);
   ``INTO OUTFILE`` and ``FORMAT`` are output-redirection/exfiltration
   vectors.

## Design notes

- We use two independent rejection layers: the AST walk (items 3-6) AND the
  read-only ClickHouse connection at execution time (defense in depth).
- The allow-list comparison is case-insensitive and strip-whitespace.
- ``sqlglot.parse()`` with ``dialect="clickhouse"`` is used so ClickHouse
  syntax extensions are parsed correctly.
- We deliberately do NOT allow CTEs (``WITH`` expressions) that reference
  tables outside the allow-list.  Any table node in the AST tree -- including
  those nested inside CTEs -- is checked.
- The TVF check uses ``exp.Anonymous`` detection rather than a hard-coded
  name list so that novel ClickHouse TVFs not yet in our list are also
  rejected.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)

# Sentinel the LLM emits when it cannot answer from the semantic layer.
_UNSATISFIABLE = "UNSATISFIABLE"

# Statement node types that are NOT read-only (reject on sight).
_WRITE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,          # ALTER TABLE / ALTER VIEW / ALTER INDEX (base class)
    exp.TruncateTable,
    exp.Command,        # CALL, ATTACH, SET, and other ClickHouse commands
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


class SQLValidationError(Exception):
    """Raised when the generated SQL fails any guardrail.

    The ``reason`` attribute is safe to return to the caller (no raw SQL, no
    DB internals).  Do not include the raw generated SQL in the message — it
    may contain injected content.

    Attributes:
        reason: A short human-readable description of the guardrail that fired.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_and_cap(
    raw_sql: str,
    *,
    allowed_tables: set[str],
    tenant_db: str,
    max_rows: int,
) -> str:
    """Parse, validate, and row-cap AI-generated SQL.

    This function is the security chokepoint — it must be called on EVERY
    LLM-generated SQL string before execution.  It is intentionally strict:
    on any doubt the query is rejected.

    Args:
        raw_sql: The raw SQL string returned by the LLM.
        allowed_tables: Lowercase unqualified table names from the governed
            semantic layer plus the deployment config allow-list.
        tenant_db: The tenant's ClickHouse database name (from
            ``TenantContext.clickhouse_db``).  Any explicit cross-db qualifier
            that is NOT this value is rejected.
        max_rows: Hard cap on rows.  Injected/clamped into the LIMIT clause.

    Returns:
        The validated SQL string, with a LIMIT clause injected or clamped.

    Raises:
        SQLValidationError: If any guardrail fires.
    """
    stripped = raw_sql.strip()

    # ------------------------------------------------------------------
    # 1. UNSATISFIABLE sentinel
    # ------------------------------------------------------------------
    if stripped.upper() == _UNSATISFIABLE:
        raise SQLValidationError(
            "The question cannot be answered from the available semantic objects. "
            "Please rephrase your question or use the manual query builder."
        )

    # ------------------------------------------------------------------
    # 2. Parse
    # ------------------------------------------------------------------
    try:
        statements = sqlglot.parse(
            stripped,
            dialect="clickhouse",
            error_level=sqlglot.ErrorLevel.RAISE,
        )
    except sqlglot.errors.ParseError as exc:
        logger.warning("SQL parse error: %s", exc)
        raise SQLValidationError(
            "The generated SQL could not be parsed. Please rephrase your question."
        ) from exc

    # ------------------------------------------------------------------
    # 3. Single statement
    # ------------------------------------------------------------------
    if not statements:
        raise SQLValidationError(
            "The generated SQL contains no statements. Please rephrase your question."
        )
    if len(statements) > 1:
        raise SQLValidationError(
            "The generated SQL contains multiple statements. "
            "Only a single SELECT is allowed."
        )

    stmt = statements[0]
    if stmt is None:
        raise SQLValidationError(
            "The generated SQL contains no valid statement. "
            "Please rephrase your question."
        )

    # ------------------------------------------------------------------
    # 4. Read-only: must be SELECT (not any write/DDL/DML type)
    # ------------------------------------------------------------------
    if isinstance(stmt, _WRITE_TYPES):
        stmt_type = type(stmt).__name__.upper()
        logger.warning(
            "SQL validation rejected write/DDL statement type=%s",
            stmt_type,
        )
        raise SQLValidationError(
            f"Generated SQL is not read-only ({stmt_type} is not permitted). "
            "Only SELECT statements are allowed."
        )

    if not isinstance(stmt, exp.Select):
        stmt_type = type(stmt).__name__.upper()
        logger.warning(
            "SQL validation rejected non-SELECT statement type=%s",
            stmt_type,
        )
        raise SQLValidationError(
            f"Generated SQL is not a SELECT statement ({stmt_type}). "
            "Only SELECT statements are allowed."
        )

    # ------------------------------------------------------------------
    # 5 + 6. Allow-list + tenant DB isolation (single AST walk)
    # ------------------------------------------------------------------
    _check_table_references(stmt, allowed_tables=allowed_tables, tenant_db=tenant_db)

    # ------------------------------------------------------------------
    # 7. Row cap: inject or clamp LIMIT
    # ------------------------------------------------------------------
    validated_sql = _enforce_row_cap(stmt, max_rows=max_rows)

    logger.info(
        "SQL validation passed: allowed_tables=%r tenant_db=%r max_rows=%d",
        sorted(allowed_tables),
        tenant_db,
        max_rows,
    )
    return validated_sql


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _check_table_references(
    stmt: exp.Expression,
    *,
    allowed_tables: set[str],
    tenant_db: str,
) -> None:
    """Walk every Table node in the AST and apply allow-list + tenant-db rules.

    Covers ALL table nodes in the full AST including those nested inside CTEs,
    subqueries, UNION arms, and JOIN clauses (``exp.Expression.find_all``
    descends recursively).

    Raises ``SQLValidationError`` on the first violation found.
    """
    # Normalise allow-list to lowercase for case-insensitive comparison.
    allowed_lower = {t.lower() for t in allowed_tables}

    for table_node in stmt.find_all(exp.Table):
        # ------------------------------------------------------------------
        # FIX 1b: Unconditionally reject table-valued functions.
        #
        # ClickHouse TVFs (url(), remote(), remoteSecure(), mysql(),
        # postgresql(), s3(), cluster(), clusterAllReplicas(), merge(),
        # file(), numbers(), generateRandom(), …) parse as an exp.Table
        # whose ``this`` child is an exp.Anonymous expression.  They are
        # SSRF / cross-tenant / external-data-read / exfiltration vectors
        # and are never permitted regardless of what the allow-list says.
        # ------------------------------------------------------------------
        if isinstance(table_node.this, exp.Anonymous):
            func_name: str = getattr(table_node.this, "name", "") or "unknown"
            logger.warning(
                "SQL validation: table-valued function rejected: func=%r",
                func_name,
            )
            raise SQLValidationError(
                "Table-valued functions are not permitted in generated SQL. "
                "Only governed semantic-layer tables may be queried."
            )

        table_name: str = (table_node.name or "").strip()
        raw_db = table_node.args.get("db") or ""
        # sqlglot may wrap the db identifier in an exp.Identifier node.
        # str() normalises both cases (plain str and Identifier) to a string.
        db_qualifier: str = str(raw_db.name if hasattr(raw_db, "name") else raw_db).strip()

        # 6. Tenant DB isolation: explicit cross-database qualifier check.
        if db_qualifier and db_qualifier.lower() != tenant_db.lower():
            logger.warning(
                "SQL validation: cross-tenant DB qualifier detected: "
                "qualifier=%r tenant_db=%r",
                db_qualifier,
                tenant_db,
            )
            raise SQLValidationError(
                "Generated SQL references a database outside the tenant scope. "
                "Cross-tenant queries are not permitted."
            )

        # ------------------------------------------------------------------
        # FIX 1a: Reject any Table node with an empty/whitespace name.
        #
        # An empty name means sqlglot could not resolve a plain identifier
        # for this table node (e.g. a TVF variant not caught by the
        # Anonymous check above, or another construct that bypasses normal
        # name resolution).  Fail closed: if we cannot confirm the name is
        # on the allow-list, reject it.
        # ------------------------------------------------------------------
        # 5. Allow-list: the unqualified table name must be non-empty AND on
        # the allow-list.  Note the intentional change from the PREVIOUS
        # guard ``if table_name and table_name.lower() not in allowed_lower``
        # which short-circuited on empty names and let them through.
        if not table_name or table_name.lower() not in allowed_lower:
            logger.warning(
                "SQL validation: table not in allow-list: table=%r allowed=%r",
                table_name,
                sorted(allowed_lower),
            )
            raise SQLValidationError(
                f"Generated SQL references an object ({table_name!r}) that is "
                "not in the governed semantic layer. "
                "Please rephrase using only the available metrics and dimensions."
            )


def _enforce_row_cap(stmt: exp.Select, *, max_rows: int) -> str:
    """Inject or clamp the LIMIT clause on ``stmt`` and return the SQL string.

    - No LIMIT → inject ``LIMIT <max_rows>``.
    - LIMIT > max_rows → clamp to max_rows.
    - LIMIT <= max_rows → leave as-is.

    Additionally strips dangerous ClickHouse-specific clauses before
    regenerating SQL (FIX 2 -- SETTINGS-clause DoS defence):

    - ``SETTINGS`` clause: can set ``max_execution_time=0`` or
      ``max_memory_usage=0``, disabling server-side resource limits (DoS).
      Even under ``readonly=1`` the server respects SETTINGS on the SELECT,
      so stripping here is necessary.
    - ``INTO OUTFILE`` clause: output-redirection / exfiltration vector.
    - ``FORMAT`` clause: can be used together with INTO OUTFILE for
      exfiltration or to alter result encoding in unexpected ways.

    All three are stripped silently (not rejected) so that a query that
    would otherwise be valid still executes safely without the dangerous
    clause.

    Returns the regenerated SQL string (from the (potentially mutated) AST).
    """
    limit_node: Any = stmt.args.get("limit")

    if limit_node is None:
        # No LIMIT clause — inject one.
        stmt = stmt.limit(max_rows)
    else:
        # Extract the current limit value.
        try:
            # sqlglot LIMIT node: stmt.args["limit"] is exp.Limit,
            # its child expression (the row count) is stmt.args["limit"].expression
            raw_expr = limit_node.expression if hasattr(limit_node, "expression") else limit_node
            current_limit = int(raw_expr.name)
            if current_limit > max_rows:
                stmt = stmt.limit(max_rows)
        except (AttributeError, TypeError, ValueError):
            # Cannot parse the limit expression — inject a safe cap.
            stmt = stmt.limit(max_rows)

    # ------------------------------------------------------------------
    # FIX 2: Strip SETTINGS, INTO OUTFILE, and FORMAT clauses.
    #
    # These AST keys map to ClickHouse-specific extensions on the Select
    # node.  Setting them to None removes them before SQL is regenerated.
    # ``settings`` → SETTINGS max_execution_time=0  (DoS vector)
    # ``into``     → INTO OUTFILE '...'             (exfiltration vector)
    # ``format``   → FORMAT CSV                     (exfiltration / encoding)
    # ------------------------------------------------------------------
    for dangerous_key in ("settings", "into", "format"):
        if stmt.args.get(dangerous_key) is not None:
            logger.warning(
                "SQL validation: stripping dangerous clause %r from generated SELECT",
                dangerous_key,
            )
            stmt.set(dangerous_key, None)

    # Strip SQL comments before returning to avoid injected content hiding in them.
    sql = stmt.sql(dialect="clickhouse")
    return _strip_sql_comments(sql)


_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* */`` block comments from SQL."""
    sql = _LINE_COMMENT_RE.sub("", sql)
    sql = _BLOCK_COMMENT_RE.sub("", sql)
    # Collapse runs of whitespace left by comment removal.
    return " ".join(sql.split())
