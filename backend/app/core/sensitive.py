"""Access-controlled disclosure of sensitive columns on read paths (Phase 5.4).

Sensitive columns are stored encrypted in the lake (see ``app.core.crypto``). When
they are read back, this module decides per request whether to **reveal** (decrypt)
or **mask** them:

* interactive requests reveal only if the principal holds the configured
  ``sensitive_view_role``;
* everything else — unauthorized requests, and background jobs with no interactive
  principal (e.g. scheduled reports) — gets masked output.

Masking never needs the key; revealing routes through the configured KMS provider.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.config import Settings
from app.core.crypto import KmsProvider, decrypt_value
from app.core.security import Principal

# What a masked sensitive cell shows instead of plaintext or ciphertext.
MASK = "***"


def may_view_sensitive(principal: Principal, settings: Settings) -> bool:
    """Return ``True`` if ``principal`` is authorized to see decrypted sensitive data.

    Fail closed: if encryption is not configured there is nothing to reveal, and a
    principal must explicitly hold the configured role.
    """
    cfg = settings.encryption
    if cfg is None:
        return False
    return cfg.sensitive_view_role in principal.roles


def apply_to_rows(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    sensitive_columns: set[str],
    *,
    reveal: bool,
    provider: KmsProvider | None,
) -> list[list[Any]]:
    """Return ``rows`` with sensitive columns decrypted (``reveal``) or masked.

    ``sensitive_columns`` is the set of *logical* column names tagged sensitive on
    the dataset; only result columns whose name is in that set are touched. When
    ``reveal`` is true a ``provider`` is required to decrypt; otherwise every
    sensitive cell becomes :data:`MASK` and no key is needed.
    """
    if not sensitive_columns:
        return [list(row) for row in rows]

    sensitive_indices = [i for i, name in enumerate(columns) if name in sensitive_columns]
    if not sensitive_indices:
        return [list(row) for row in rows]

    if reveal and provider is None:
        raise ValueError("reveal=True requires a KMS provider")

    result: list[list[Any]] = []
    for row in rows:
        new_row = list(row)
        for i in sensitive_indices:
            cell = new_row[i]
            if cell is None:
                continue
            if reveal:
                # provider is non-None here (guarded above).
                new_row[i] = decrypt_value(provider, str(cell))  # type: ignore[arg-type]
            else:
                new_row[i] = MASK
        result.append(new_row)
    return result
