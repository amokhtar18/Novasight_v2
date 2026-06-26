"""Unit tests for ``quote_ident`` — the ClickHouse identifier-quoting helper.

The helper backtick-quotes an identifier and **doubles any embedded backtick**
(ClickHouse's escape). Most identifiers reaching it are already constrained
(validated slug / UUID hex / regex-checked column name), but column names taken
verbatim from a CSV header on upload are not, so the escape is the defence that
stops a crafted name breaking out of the quotes into executable SQL.
"""
from __future__ import annotations

from app.core.clickhouse import quote_ident


def test_quote_ident_wraps_in_backticks() -> None:
    assert quote_ident("orders") == "`orders`"


def test_quote_ident_doubles_embedded_backtick() -> None:
    # A single backtick in the name must be doubled, not left to terminate the
    # identifier early.
    assert quote_ident("a`b") == "`a``b`"


def test_quote_ident_neutralises_injection_attempt() -> None:
    # A name engineered to break out of the quotes and inject a statement stays
    # fully enclosed in one quoted identifier after escaping.
    malicious = "x`; DROP TABLE users; --"
    quoted = quote_ident(malicious)
    assert quoted == "`x``; DROP TABLE users; --`"
    # Exactly one opening and one closing backtick pair frames the whole thing:
    assert quoted.startswith("`") and quoted.endswith("`")
    # Every interior backtick is part of a doubled pair (no lone backtick splits it).
    assert quoted[1:-1].count("`") % 2 == 0
