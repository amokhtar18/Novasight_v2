"""Column-level encryption for sensitive data (Phase 5.4).

The ``KmsProvider`` abstraction is the seam between the application and whatever
holds the key material: a local symmetric key (dev / on-prem) or a managed KMS in
the cloud. Application code depends only on the protocol, so swapping providers is
a configuration change, not a code change (golden rule 1).

Values are encrypted at the cell level on ingest and stored as opaque base64
tokens (prefixed with a version marker) in the lake, so a tagged column is
ciphertext at rest. Decryption happens only in the application, on access-checked
read paths (see ``app.core.sensitive``).

Local provider: AES-256-GCM with a random 96-bit nonce per call, prepended to the
ciphertext. The key comes from ``EncryptionSettings.key`` (base64-encoded 32 bytes)
— never a literal.
"""
from __future__ import annotations

import base64
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import EncryptionSettings, Settings, get_settings

# Marker prefixing every encrypted token so encrypted values are self-describing
# (lets decrypt be idempotent and lets masking detect already-encrypted cells).
_TOKEN_PREFIX = "enc:v1:"  # noqa: S105 — token marker, not a credential
_NONCE_BYTES = 12
_AES_KEY_BYTES = 32


class EncryptionError(RuntimeError):
    """Encryption/decryption failed or was misconfigured."""


class KmsProvider(Protocol):
    """Minimal key-authority surface the app depends on (encrypt/decrypt bytes)."""

    def encrypt(self, plaintext: bytes) -> bytes:
        """Return ciphertext for ``plaintext``."""
        ...

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Return the plaintext for ``ciphertext``."""
        ...


class LocalAesGcmProvider:
    """``KmsProvider`` using a local AES-256-GCM symmetric key from settings."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _AES_KEY_BYTES:
            raise EncryptionError(
                f"local encryption key must be {_AES_KEY_BYTES} bytes, got {len(key)}"
            )
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        import os

        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aesgcm.encrypt(nonce, plaintext, None)

    def decrypt(self, ciphertext: bytes) -> bytes:
        nonce, body = ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:]
        return self._aesgcm.decrypt(nonce, body, None)


def is_encrypted(value: str) -> bool:
    """Return ``True`` if ``value`` is one of our encrypted tokens."""
    return value.startswith(_TOKEN_PREFIX)


def encrypt_value(provider: KmsProvider, plaintext: str) -> str:
    """Encrypt a string cell into a versioned, base64 token.

    Idempotent: a value that is already an encrypted token is returned unchanged,
    so re-ingesting the same data does not double-encrypt.
    """
    if is_encrypted(plaintext):
        return plaintext
    ciphertext = provider.encrypt(plaintext.encode("utf-8"))
    return _TOKEN_PREFIX + base64.b64encode(ciphertext).decode("ascii")


def decrypt_value(provider: KmsProvider, token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_value`.

    A value without the marker is returned unchanged (defensive: tolerates
    historical plaintext or non-sensitive data that reached this path).
    """
    if not is_encrypted(token):
        return token
    raw = base64.b64decode(token[len(_TOKEN_PREFIX) :])
    try:
        return provider.decrypt(raw).decode("utf-8")
    except Exception as exc:  # cryptography raises InvalidTag etc.
        raise EncryptionError("failed to decrypt sensitive value") from exc


def build_kms_provider(settings: Settings | None = None) -> KmsProvider:
    """Assemble the configured ``KmsProvider`` from settings.

    Raises ``EncryptionError`` if encryption is not configured (so callers that
    actually need it fail closed) or the provider name is unknown.
    """
    settings = settings or get_settings()
    cfg = settings.encryption
    if cfg is None:
        raise EncryptionError(
            "ENCRYPTION__* is not configured but a sensitive column requires encryption"
        )
    return _provider_for(cfg)


def _provider_for(cfg: EncryptionSettings) -> KmsProvider:
    if cfg.provider == "local":
        key = base64.b64decode(cfg.key.get_secret_value())
        return LocalAesGcmProvider(key)
    raise EncryptionError(f"unknown encryption provider {cfg.provider!r}")
