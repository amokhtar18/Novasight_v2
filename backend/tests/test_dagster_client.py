"""Tests for the backend Dagster GraphQL client + run-config contract.

The client is exercised against an ``httpx.MockTransport`` so request construction
and response/error parsing are verified without a live Dagster — the live GraphQL
schema is validated when the stack runs.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import DagsterSettings
from app.orchestration import (
    PIPELINE_OP,
    DagsterClient,
    DagsterError,
    pipeline_run_config,
    transform_run_config,
)


def _settings(url: str = "http://dagster:3000/graphql") -> Any:
    return SimpleNamespace(dagster=DagsterSettings(graphql_url=url))


def _client(handler: Any, url: str = "http://dagster:3000/graphql") -> DagsterClient:
    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport)
    return DagsterClient(_settings(url), client=ac)


# ---------------------------------------------------------------------------
# run-config contract
# ---------------------------------------------------------------------------


def test_pipeline_run_config_shape() -> None:
    cfg = pipeline_run_config("pid-1", "acme")
    assert cfg == {"ops": {PIPELINE_OP: {"config": {"pipeline_id": "pid-1", "tenant": "acme"}}}}


def test_transform_run_config_shape() -> None:
    cfg = transform_run_config("tid-1", "acme")
    assert cfg["ops"]["run_transform"]["config"] == {
        "transform_job_id": "tid-1",
        "tenant": "acme",
    }


# ---------------------------------------------------------------------------
# launch_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_run_success_returns_run_id() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"data": {"launchRun": {"__typename": "LaunchRunSuccess",
                                          "run": {"runId": "run-123", "status": "STARTED"}}}},
        )

    client = _client(handler)
    run_id = await client.launch_run(job_name="pipeline_job", run_config={"ops": {}})
    assert run_id == "run-123"
    # Request carried the right selector + job name.
    params = captured["variables"]["params"]
    assert params["selector"]["jobName"] == "pipeline_job"
    assert params["selector"]["repositoryLocationName"] == "novasight_orchestration"
    assert "launchRun" in captured["query"]


@pytest.mark.asyncio
async def test_launch_run_validation_error_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"launchRun": {"__typename": "RunConfigValidationInvalid",
                                          "errors": [{"message": "bad config"}]}}},
        )

    with pytest.raises(DagsterError, match="bad config"):
        await _client(handler).launch_run(job_name="pipeline_job", run_config={})


# ---------------------------------------------------------------------------
# get_run_status / reload / errors / unconfigured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_run_status() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"runOrError": {"__typename": "Run", "status": "SUCCESS"}}}
        )

    assert await _client(handler).get_run_status("run-123") == "SUCCESS"


@pytest.mark.asyncio
async def test_reload_location_ok_and_error() -> None:
    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"reloadRepositoryLocation": {"__typename": "WorkspaceLocationEntry"}}},
        )

    await _client(ok).reload_location()  # no raise

    def err(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"reloadRepositoryLocation": {"__typename": "PythonError",
                                                         "message": "boom"}}},
        )

    with pytest.raises(DagsterError, match="boom"):
        await _client(err).reload_location()


@pytest.mark.asyncio
async def test_graphql_errors_raise() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "nope"}]})

    with pytest.raises(DagsterError):
        await _client(handler).get_run_status("run-1")


@pytest.mark.asyncio
async def test_transport_error_raises_dagster_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(DagsterError, match="unavailable"):
        await _client(handler).launch_run(job_name="pipeline_job", run_config={})


@pytest.mark.asyncio
async def test_unconfigured_url_raises() -> None:
    client = DagsterClient(_settings(url=""))
    with pytest.raises(DagsterError, match="not configured"):
        await client.get_run_status("run-1")
