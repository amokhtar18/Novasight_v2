"""Tests for server-side (at-rest) encryption on object writes (app/core/object_store.py)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.config import ObjectStoreSettings
from app.core.object_store import S3ObjectStore


class _AsyncClientCM:
    """Async context manager yielding a mock S3 client (mirrors aioboto3)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _cfg(sse: str | None) -> ObjectStoreSettings:
    return ObjectStoreSettings(
        endpoint_url="http://localhost:9000",
        access_key=SecretStr("k"),
        secret_key=SecretStr("s"),
        bucket="bk",
        server_side_encryption=sse,
    )


async def _put_and_capture(sse: str | None) -> dict[str, Any]:
    store = S3ObjectStore(_cfg(sse))
    client = MagicMock()
    client.put_object = AsyncMock()
    with patch.object(store, "_client", return_value=_AsyncClientCM(client)):
        await store.put_object(key="k", body=b"x", content_type="text/csv")
    return client.put_object.call_args.kwargs


@pytest.mark.asyncio
async def test_put_object_requests_sse_when_configured() -> None:
    kwargs = await _put_and_capture("AES256")
    assert kwargs["ServerSideEncryption"] == "AES256"
    assert kwargs["Bucket"] == "bk"
    assert kwargs["Key"] == "k"


@pytest.mark.asyncio
async def test_put_object_omits_sse_when_not_configured() -> None:
    kwargs = await _put_and_capture(None)
    assert "ServerSideEncryption" not in kwargs
