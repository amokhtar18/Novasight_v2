"""S3-compatible object store — the portability seam for raw bytes.

This is the one adapter the rest of the backend uses to read/write objects in
the configured bucket (MinIO on-prem, AWS S3 / GCS in cloud). Everything that
varies between environments — endpoint, region, credentials, bucket — comes from
``ObjectStoreSettings``; callers pass only a *key* and never see the bucket or
the underlying client (golden rule: no hardcoded infrastructure).

The ``ObjectStore`` Protocol is what services depend on, so tests can substitute
an in-memory fake without touching live infrastructure. Tenant isolation is the
*caller's* responsibility: every key handed to this store is already prefixed
with the tenant's namespace (see ``app.services.datasets``).
"""
from __future__ import annotations

from typing import Any, Protocol

import aioboto3
from fastapi import Depends

from app.core.config import ObjectStoreSettings, Settings, get_settings


class ObjectStore(Protocol):
    """The minimal object-store surface the backend depends on.

    The bucket is bound at construction time (it is configuration, resolved
    once), so callers only ever supply a key — they cannot reach another bucket.
    """

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        """Write ``body`` to ``key`` in the configured bucket."""
        ...

    async def get_object(self, *, key: str) -> bytes:
        """Read and return the raw bytes stored at ``key`` in the configured bucket."""
        ...

    async def list_keys(self, *, prefix: str) -> list[str]:
        """Return all object keys under ``prefix`` in the configured bucket."""
        ...


class S3ObjectStore:
    """``ObjectStore`` backed by an S3-compatible service via aioboto3.

    A single ``aioboto3.Session`` is reused; a fresh async client is opened per
    operation (aioboto3 clients are async context managers and not meant to be
    held open across the process). All connection parameters come from settings.
    """

    def __init__(self, cfg: ObjectStoreSettings) -> None:
        self._cfg = cfg
        self._session = aioboto3.Session()

    def _client(self) -> Any:  # noqa: ANN401 — aioboto3 client type is opaque
        # endpoint_url is empty for native AWS S3 (region-routed); pass None then.
        return self._session.client(
            "s3",
            endpoint_url=self._cfg.endpoint_url or None,
            region_name=self._cfg.region,
            aws_access_key_id=self._cfg.access_key.get_secret_value(),
            aws_secret_access_key=self._cfg.secret_key.get_secret_value(),
        )

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        extra: dict[str, str] = {}
        # Request server-side (at-rest) encryption when configured, so confirmation
        # of at-rest encryption does not depend on a bucket default policy.
        if self._cfg.server_side_encryption:
            extra["ServerSideEncryption"] = self._cfg.server_side_encryption
        async with self._client() as client:
            await client.put_object(
                Bucket=self._cfg.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                **extra,
            )

    async def get_object(self, *, key: str) -> bytes:
        async with self._client() as client:
            response = await client.get_object(Bucket=self._cfg.bucket, Key=key)
            async with response["Body"] as stream:
                return await stream.read()  # type: ignore[no-any-return]

    async def list_keys(self, *, prefix: str) -> list[str]:
        keys: list[str] = []
        async with self._client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._cfg.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
        return keys


# Process-wide singleton; the session/config is identical for every request.
_store: S3ObjectStore | None = None


def get_object_store(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ObjectStore:
    """FastAPI dependency: return the shared object store built from settings.

    Overridden in tests with an in-memory fake via ``dependency_overrides``.
    """
    global _store
    if _store is None:
        _store = S3ObjectStore(settings.object_store)
    return _store
