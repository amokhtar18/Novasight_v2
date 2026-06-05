"""Tests for column encryption primitives (app/core/crypto.py)."""
from __future__ import annotations

import base64

import pytest

from app.core.crypto import (
    EncryptionError,
    LocalAesGcmProvider,
    build_kms_provider,
    decrypt_value,
    encrypt_value,
    is_encrypted,
)

_KEY = b"\x01" * 32


def _provider() -> LocalAesGcmProvider:
    return LocalAesGcmProvider(_KEY)


def test_round_trip() -> None:
    provider = _provider()
    token = encrypt_value(provider, "123-45-6789")
    assert is_encrypted(token)
    assert token != "123-45-6789"
    assert decrypt_value(provider, token) == "123-45-6789"


def test_ciphertext_is_nondeterministic() -> None:
    # A fresh nonce per call means the same plaintext encrypts differently each time.
    provider = _provider()
    assert encrypt_value(provider, "x") != encrypt_value(provider, "x")


def test_encrypt_is_idempotent_on_tokens() -> None:
    provider = _provider()
    token = encrypt_value(provider, "secret")
    # Re-encrypting an already-encrypted token leaves it unchanged.
    assert encrypt_value(provider, token) == token


def test_decrypt_passthrough_for_plaintext() -> None:
    # A value without the marker is returned unchanged (defensive).
    assert decrypt_value(_provider(), "not-encrypted") == "not-encrypted"


def test_wrong_key_fails_closed() -> None:
    token = encrypt_value(_provider(), "secret")
    other = LocalAesGcmProvider(b"\x02" * 32)
    with pytest.raises(EncryptionError):
        decrypt_value(other, token)


def test_bad_key_length_rejected() -> None:
    with pytest.raises(EncryptionError):
        LocalAesGcmProvider(b"tooshort")


def test_build_kms_provider_requires_config() -> None:
    from app.core.config import Settings

    # A settings object with no encryption group → fail closed.
    class _NoEnc:
        encryption = None

    with pytest.raises(EncryptionError):
        build_kms_provider(_NoEnc())  # type: ignore[arg-type]
    assert Settings  # import smoke


def test_build_kms_provider_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import EncryptionSettings, Settings

    class _Enc:
        encryption = EncryptionSettings(
            provider="local",
            key=base64.b64encode(_KEY).decode(),  # type: ignore[arg-type]
        )

    provider = build_kms_provider(_Enc())  # type: ignore[arg-type]
    assert decrypt_value(provider, encrypt_value(provider, "v")) == "v"
    assert Settings  # import smoke


def test_unknown_provider_rejected() -> None:
    from app.core.config import EncryptionSettings

    class _Enc:
        encryption = EncryptionSettings(provider="martian", key="AAAA")  # type: ignore[arg-type]

    with pytest.raises(EncryptionError, match="unknown encryption provider"):
        build_kms_provider(_Enc())  # type: ignore[arg-type]
