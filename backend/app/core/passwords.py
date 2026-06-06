"""Password hashing and verification.

A thin, dependency-light wrapper over ``bcrypt``. Used by the password-auth login
flow (``app/services/auth.py``) and user management (``app/services/users.py``).

bcrypt only considers the first 72 bytes of the input, so we truncate at the byte
level explicitly to keep hashing/verification deterministic for very long inputs
rather than relying on driver-specific behaviour. Callers should still bound the
password length at the schema layer.
"""
from __future__ import annotations

import bcrypt

# bcrypt's documented maximum significant input length.
_MAX_BYTES = 72


def _encode(plaintext: str) -> bytes:
    return plaintext.encode("utf-8")[:_MAX_BYTES]


def hash_password(plaintext: str) -> str:
    """Return a salted bcrypt hash (utf-8 string) for ``plaintext``."""
    return bcrypt.hashpw(_encode(plaintext), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True iff ``plaintext`` matches the stored bcrypt ``hashed`` value.

    Never raises: a malformed or empty hash returns ``False`` (fail closed).
    """
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_encode(plaintext), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
