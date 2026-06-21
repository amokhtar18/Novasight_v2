"""Security + correctness tests for the member SQL-expression validator (#6).

The validator is the trust boundary that lets the semantic wizard accept real
expressions instead of bare columns. These tests pin both that legitimate modelling
expressions pass and that injection / IO / statement constructs are rejected.
"""
from __future__ import annotations

import pytest

from app.core.sql_expression import SqlExpressionError, validate_expression


@pytest.mark.parametrize(
    "expr",
    [
        "amount",  # a bare column (backwards compatible)
        "amount * 1.2",
        "if(status = 'paid', amount, 0)",
        "multiIf(score > 90, 'A', score > 80, 'B', 'C')",
        "coalesce(discount, 0)",
        "concat(first_name, ' ', last_name)",
        "upper(trim(region))",
        "toStartOfMonth(order_date)",
        "dateDiff('day', created_at, shipped_at)",
        "CASE WHEN amount > 100 THEN 'big' ELSE 'small' END",
        "sum(amount) OVER (PARTITION BY region ORDER BY order_date)",
        "round(avg(amount), 2)",
        "substring(sku, 1, 3)",
    ],
)
def test_accepts_valid_expressions(expr: str) -> None:
    assert validate_expression(expr) == expr.strip()


@pytest.mark.parametrize(
    "expr",
    [
        # table-valued / IO functions that would bypass tenant isolation
        "url('http://evil/data', 'CSV')",
        "s3('http://evil/x', 'CSV')",
        "remote('other:9000', 'db.t')",
        "file('/etc/passwd')",
        "mysql('host:3306', 'db', 't', 'u', 'p')",
        "postgresql('host', 'db', 't', 'u', 'p')",
        "jdbc('ds', 'select 1')",
        # statement / subquery smuggling
        "amount; DROP TABLE users",
        "(SELECT secret FROM other.creds)",
        "amount FROM other_table",
        "1 UNION SELECT password FROM users",
        # comments
        "amount -- ignore the rest",
        "amount /* block */ + 1",
        # qualified / quoted identifiers (cross-db, escape)
        "otherdb.customers.ssn",
        '"weird"',
        "`backtick`",
        "amount + ${CUBE}",
        # structural
        "sum(amount",  # unbalanced
        "amount)",  # unbalanced
        "",  # empty
        "   ",  # blank
        # a non-allow-listed function
        "evilFunc(amount)",
        "sleep(10)",
    ],
)
def test_rejects_dangerous_expressions(expr: str) -> None:
    with pytest.raises(SqlExpressionError):
        validate_expression(expr)


def test_length_cap() -> None:
    with pytest.raises(SqlExpressionError):
        validate_expression("a" + " + 1" * 400)


def test_error_reason_is_safe_string() -> None:
    try:
        validate_expression("s3('x')")
    except SqlExpressionError as exc:
        assert "s3" in exc.reason
        assert "not allowed" in exc.reason
