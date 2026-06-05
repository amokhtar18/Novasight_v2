"""Tests for roles extraction on the authenticated Principal (app/core/security.py)."""
from __future__ import annotations

from app.core.security import _build_principal, _extract_roles


def test_extract_roles_from_list() -> None:
    assert _extract_roles({"roles": ["a", "b"]}, "roles") == frozenset({"a", "b"})


def test_extract_roles_from_scalar() -> None:
    assert _extract_roles({"roles": "admin"}, "roles") == frozenset({"admin"})


def test_extract_roles_missing_is_empty() -> None:
    assert _extract_roles({}, "roles") == frozenset()


def test_extract_roles_filters_non_strings() -> None:
    assert _extract_roles({"roles": ["a", 1, None, "b"]}, "roles") == frozenset({"a", "b"})


def test_extract_roles_honors_configured_claim() -> None:
    assert _extract_roles({"groups": ["x"]}, "groups") == frozenset({"x"})


def test_build_principal_populates_roles() -> None:
    principal = _build_principal(
        {"sub": "u", "tenant": "t", "roles": ["sensitive_viewer"]}, "tenant", "roles"
    )
    assert principal.roles == frozenset({"sensitive_viewer"})


def test_build_principal_defaults_to_no_roles() -> None:
    principal = _build_principal({"sub": "u", "tenant": "t"}, "tenant", "roles")
    assert principal.roles == frozenset()
