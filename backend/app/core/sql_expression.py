"""Validated SQL-expression grammar for semantic-model members (#6).

Semantic-model measures/dimensions historically allowed only a bare column name
(injection-proof by construction). To support real transforms (window functions,
string manipulation, ``CASE``, arithmetic) the wizard now accepts an *expression*,
but it must pass this allow-list validator before it can reach the generated Cube
file or ClickHouse.

The expression is author-written (a tenant superuser, like dbt SQL) and the codegen
JSON-encodes it, so it can't break out of the Cube JS file. What this validator
guards is the **SQL** ClickHouse ultimately runs:

* only allow-listed functions may be *called* — this blocks table-valued / IO
  functions (``url``, ``s3``, ``remote``, ``file``, ``mysql`` …) that would bypass
  tenant isolation (see the ``nl-sql-validator-tvf`` lesson);
* statement/DDL keywords (``SELECT``, ``FROM``, ``INSERT``, ``DROP`` …) and comment
  markers / ``;`` are rejected, so an expression can't smuggle a subquery or a second
  statement;
* qualified names (``db.table``) and identifier-quoting are rejected, so a member
  can't reference another database/tenant.

A bare column name is a valid expression, so every previously-accepted member still
validates. This module is pure (regex only) and unit-tested directly.
"""
from __future__ import annotations

import re

#: Hard cap on a member expression (defense against pathological inputs).
MAX_EXPRESSION_LENGTH = 1000


class SqlExpressionError(ValueError):
    """Raised when a member expression fails validation. ``reason`` is safe to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Curated allow-list of functions a member expression may call (lower-cased).
# Scalar + aggregate + window functions that are safe and useful for modelling;
# deliberately excludes IO/table functions and anything with side effects.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # aggregates
        "count", "countdistinct", "sum", "avg", "min", "max", "any", "anylast",
        "median", "quantile", "stddevpop", "stddevsamp", "varpop", "varsamp",
        "argmin", "argmax", "sumif", "countif", "avgif", "uniq", "uniqexact",
        # math
        "abs", "round", "roundbankers", "floor", "ceil", "ceiling", "trunc",
        "exp", "ln", "log", "log2", "log10", "sqrt", "cbrt", "pow", "power",
        "sign", "mod", "modulo", "intdiv", "gcd", "lcm", "greatest", "least",
        # string
        "concat", "concatws", "lower", "lowerutf8", "upper", "upperutf8",
        "length", "lengthutf8", "char_length", "character_length",
        "substring", "substr", "substringutf8", "trim", "trimboth", "trimleft",
        "trimright", "ltrim", "rtrim", "replaceall", "replaceone",
        "replaceregexpall", "replaceregexpone", "position", "positionutf8",
        "splitbychar", "splitbystring", "lpad", "rpad", "leftpad", "rightpad",
        "left", "right", "reverse", "format", "tostring", "startswith",
        "endswith", "match", "extract", "extractall", "like", "ilike",
        "initcap", "repeat", "ascii", "encodeurlcomponent",
        # date / time
        "todate", "todatetime", "todatetime64", "todateordefault",
        "tostartofday", "tostartofweek", "tostartofmonth", "tostartofquarter",
        "tostartofyear", "tostartofhour", "tostartofminute", "tostartoffiveminutes",
        "toyear", "toquarter", "tomonth", "todayofmonth", "todayofweek",
        "todayofyear", "tohour", "tominute", "tosecond", "toweek", "toisoweek",
        "datediff", "date_diff", "dateadd", "date_add", "datesub", "date_sub",
        "datetrunc", "date_trunc", "now", "today", "yesterday",
        "formatdatetime", "tounixtimestamp", "fromunixtimestamp", "age",
        "toyyyymm", "toyyyymmdd", "tomonday", "tolastdayofmonth",
        # conditional / null
        "if", "multiif", "coalesce", "ifnull", "nullif", "isnull", "isnotnull",
        "isnan", "assumenotnull", "greatestordefault",
        # cast / convert
        "tobool", "toint8", "toint16", "toint32", "toint64", "touint8",
        "touint16", "touint32", "touint64", "tofloat32", "tofloat64",
        "todecimal32", "todecimal64", "todecimal128", "tonullable", "cast",
        "accuratecast", "accuratecastornull", "toint64ordefault",
        "tofloat64ordefault", "todatetimeordefault",
        # window functions
        "row_number", "rank", "dense_rank", "laginframe", "leadinframe",
        "first_value", "last_value", "nth_value", "ntile", "percent_rank",
        "cume_dist", "rownumberinallblocks",
    }
)

# Bare keywords allowed as words (control flow, operators, window syntax, literals).
ALLOWED_KEYWORDS: frozenset[str] = frozenset(
    {
        "case", "when", "then", "else", "end",
        "and", "or", "not", "in", "between", "is", "null", "like", "ilike",
        "over", "partition", "by", "order", "asc", "desc", "rows", "range",
        "preceding", "following", "current", "row", "unbounded", "distinct",
        "interval", "second", "minute", "hour", "day", "week", "month",
        "quarter", "year", "true", "false",
    }
)

# Statement / DDL / cross-object keywords that must never appear.
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        "select", "from", "where", "join", "union", "insert", "update",
        "delete", "drop", "alter", "create", "grant", "revoke", "attach",
        "detach", "system", "into", "table", "database", "values", "with",
        "settings", "format", "optimize", "truncate", "rename", "describe",
        "show", "use", "set", "kill", "having", "group", "limit", "offset",
    }
)

# Substrings that are never allowed (comments, statement separators, quoting that
# could escape the expression context or reference a qualified object).
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (";", "--", "/*", "*/", "#", "`", '"', "$", "\\")

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<number>\d+\.\d+|\d+|\.\d+)
    | (?P<string>'(?:[^'\\]|\\.)*')
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op><=|>=|<>|!=|\|\||[-+*/%,()<>=])
    | (?P<other>.)
    """,
    re.VERBOSE,
)


def validate_expression(expression: str) -> str:
    """Validate a member SQL expression, returning it trimmed, or raise.

    Raises:
        SqlExpressionError: with a safe ``reason`` on any violation.
    """
    expr = expression.strip()
    if not expr:
        raise SqlExpressionError("expression must not be empty")
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise SqlExpressionError(
            f"expression exceeds the {MAX_EXPRESSION_LENGTH}-character limit"
        )
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in expr:
            raise SqlExpressionError(f"expression may not contain {bad!r}")

    tokens: list[tuple[str, str]] = []  # (kind, text), excluding whitespace
    depth = 0
    pos = 0
    while pos < len(expr):
        match = _TOKEN_RE.match(expr, pos)
        if match is None:  # pragma: no cover - the 'other' group always matches
            raise SqlExpressionError("expression contains an invalid character")
        pos = match.end()
        kind = match.lastgroup or ""
        text = match.group()
        if kind == "ws":
            continue
        if kind == "other":
            raise SqlExpressionError(f"expression contains an invalid character: {text!r}")
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
            if depth < 0:
                raise SqlExpressionError("unbalanced parentheses")
        tokens.append((kind, text))

    if depth != 0:
        raise SqlExpressionError("unbalanced parentheses")
    if not tokens:
        raise SqlExpressionError("expression must not be empty")

    for i, (kind, text) in enumerate(tokens):
        if kind != "ident":
            continue
        word = text.lower()
        if word in FORBIDDEN_KEYWORDS:
            raise SqlExpressionError(f"'{text}' is not allowed in a member expression")
        # An allowed keyword (e.g. OVER, CASE, IN) is fine even when followed by '('
        # (``OVER (...)`` is a window clause, not a function call).
        if word in ALLOWED_KEYWORDS:
            continue
        # A following '(' makes a non-keyword ident a function call — allow-list it.
        next_is_paren = i + 1 < len(tokens) and tokens[i + 1][1] == "("
        if next_is_paren and word not in ALLOWED_FUNCTIONS:
            raise SqlExpressionError(f"function '{text}' is not allowed")
        # Otherwise it's a column reference — fine.

    return expr
