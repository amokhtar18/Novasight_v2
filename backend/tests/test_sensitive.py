"""Tests for access-controlled disclosure of sensitive columns (app/core/sensitive.py)."""
from __future__ import annotations

import base64

import pytest

from app.core.config import EncryptionSettings
from app.core.crypto import LocalAesGcmProvider, encrypt_value
from app.core.security import Principal
from app.core.sensitive import MASK, apply_to_rows, may_view_sensitive

_KEY = b"\x03" * 32


def _principal(*roles: str) -> Principal:
    return Principal(subject="u", tenant_key="t", email="u@t", roles=frozenset(roles))


class _Settings:
    """Minimal settings stand-in exposing only ``encryption``."""

    def __init__(self, role: str | None) -> None:
        self.encryption = (
            None
            if role is None
            else EncryptionSettings(
                provider="local",
                key=base64.b64encode(_KEY).decode(),  # type: ignore[arg-type]
                sensitive_view_role=role,
            )
        )


def test_may_view_requires_role() -> None:
    settings = _Settings("sensitive_viewer")
    assert may_view_sensitive(_principal("sensitive_viewer"), settings) is True  # type: ignore[arg-type]
    assert may_view_sensitive(_principal("other"), settings) is False  # type: ignore[arg-type]
    assert may_view_sensitive(_principal(), settings) is False  # type: ignore[arg-type]


def test_may_view_false_when_encryption_unconfigured() -> None:
    assert may_view_sensitive(_principal("sensitive_viewer"), _Settings(None)) is False  # type: ignore[arg-type]


def test_apply_masks_sensitive_columns() -> None:
    rows = [["alice", "secret1", 1], ["bob", "secret2", 2]]
    out = apply_to_rows(
        ["name", "ssn", "n"], rows, {"ssn"}, reveal=False, provider=None
    )
    assert out == [["alice", MASK, 1], ["bob", MASK, 2]]


def test_apply_reveals_with_provider() -> None:
    provider = LocalAesGcmProvider(_KEY)
    enc = encrypt_value(provider, "secret")
    out = apply_to_rows(["ssn", "n"], [[enc, 1]], {"ssn"}, reveal=True, provider=provider)
    assert out == [["secret", 1]]


def test_apply_passes_through_when_no_sensitive_columns() -> None:
    rows = [["alice", 1]]
    out = apply_to_rows(["name", "n"], rows, set(), reveal=False, provider=None)
    assert out == [["alice", 1]]
    # A sensitive set that doesn't intersect the columns is also a passthrough.
    out2 = apply_to_rows(["name", "n"], rows, {"ssn"}, reveal=False, provider=None)
    assert out2 == [["alice", 1]]


def test_apply_preserves_null_cells() -> None:
    out = apply_to_rows(["ssn"], [[None]], {"ssn"}, reveal=False, provider=None)
    assert out == [[None]]


def test_reveal_without_provider_raises() -> None:
    with pytest.raises(ValueError, match="requires a KMS provider"):
        apply_to_rows(["ssn"], [["x"]], {"ssn"}, reveal=True, provider=None)
