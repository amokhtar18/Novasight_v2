"""Async Dagster GraphQL client — the backend's control-plane handle on Dagster.

Exposes only the operations the API needs and that are stable across Dagster
versions: launch a run of a generic job, query a run's status, and reload the code
location (used after a schedule definition changes). All configuration comes from
``settings.dagster`` (golden rule 1); the GraphQL URL has no real default, so an
unconfigured install fails closed with a clear ``DagsterError`` rather than calling
an unknown endpoint.

Errors never leak raw upstream payloads to callers — the router maps ``DagsterError``
to a safe 503.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import Depends

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class DagsterError(Exception):
    """Raised when a Dagster GraphQL call fails or returns an error payload."""


# GraphQL documents kept as module constants so the request shape is reviewable in
# one place and unit-tested against mocked responses.
_LAUNCH_RUN = """
mutation Launch($params: ExecutionParams!) {
  launchRun(executionParams: $params) {
    __typename
    ... on LaunchRunSuccess { run { runId status } }
    ... on PythonError { message }
    ... on RunConfigValidationInvalid { errors { message } }
    ... on PipelineNotFoundError { message }
  }
}
"""

_RUN_STATUS = """
query RunStatus($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run { status }
    ... on PythonError { message }
  }
}
"""

_RELOAD = """
mutation Reload($name: String!) {
  reloadRepositoryLocation(repositoryLocationName: $name) {
    __typename
    ... on PythonError { message }
  }
}
"""


class DagsterClient:
    """Thin async wrapper over the Dagster GraphQL endpoint."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._cfg = settings.dagster
        # An injected client (tests) is used as-is; otherwise one is created per call.
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def launch_run(self, *, job_name: str, run_config: dict[str, Any]) -> str:
        """Launch a run of ``job_name`` with ``run_config``; return the Dagster run id."""
        params = {
            "selector": {
                "repositoryLocationName": self._cfg.repository_location,
                "repositoryName": self._cfg.repository_name,
                "jobName": job_name,
            },
            "runConfigData": run_config,
            "mode": "default",
        }
        data = await self._execute(_LAUNCH_RUN, {"params": params})
        result = data.get("launchRun", {})
        typename = result.get("__typename")
        if typename != "LaunchRunSuccess":
            raise DagsterError(f"launch failed: {typename}: {self._first_message(result)}")
        run_id = result.get("run", {}).get("runId")
        if not run_id:
            raise DagsterError("launch succeeded but no run id was returned")
        return str(run_id)

    async def get_run_status(self, run_id: str) -> str:
        """Return the Dagster run status string (e.g. ``STARTED``, ``SUCCESS``)."""
        data = await self._execute(_RUN_STATUS, {"runId": run_id})
        result = data.get("runOrError", {})
        if result.get("__typename") != "Run":
            raise DagsterError(f"run status error: {self._first_message(result)}")
        return str(result.get("status", "UNKNOWN"))

    async def reload_location(self) -> None:
        """Reload the code location so registry changes (e.g. new schedules) take effect."""
        data = await self._execute(_RELOAD, {"name": self._cfg.repository_location})
        result = data.get("reloadRepositoryLocation", {})
        if result.get("__typename") == "PythonError":
            raise DagsterError(f"reload failed: {result.get('message')}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _url(self) -> str:
        if not self._cfg.graphql_url:
            raise DagsterError(
                "Dagster control plane is not configured (set DAGSTER__GRAPHQL_URL)"
            )
        return self._cfg.graphql_url

    async def _execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        url = self._url()
        payload = {"query": query, "variables": variables}
        try:
            if self._client is not None:
                resp = await self._client.post(url, json=payload)
            else:
                async with httpx.AsyncClient(
                    timeout=self._cfg.request_timeout_seconds
                ) as client:
                    resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Dagster GraphQL transport error: %s", type(exc).__name__)
            raise DagsterError("Dagster is unavailable") from exc

        if body.get("errors"):
            # GraphQL-level errors (bad query, server error). Log, don't leak.
            logger.error("Dagster GraphQL returned errors: %s", body["errors"])
            raise DagsterError("Dagster returned an error")
        data = body.get("data")
        if not isinstance(data, dict):
            raise DagsterError("Dagster returned no data")
        return data

    @staticmethod
    def _first_message(result: dict[str, Any]) -> str:
        if "message" in result:
            return str(result["message"])
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            return str(errors[0].get("message", ""))
        return "unknown error"


def get_dagster_client(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> DagsterClient:
    """FastAPI dependency: a ``DagsterClient`` built from settings."""
    return DagsterClient(settings)
