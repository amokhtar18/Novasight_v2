"""Observability tests (Phase 6.4): settings, /metrics exposition, tracing toggle,
and worker metrics wiring.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

_BASE_ENV: dict[str, str] = {
    "ENVIRONMENT": "test",
    "POSTGRES__HOST": "localhost",
    "POSTGRES__USER": "test",
    "POSTGRES__PASSWORD": "test",
    "POSTGRES__DB": "test",
    "REDIS__HOST": "localhost",
    "OBJECT_STORE__ENDPOINT_URL": "http://localhost:9000",
    "OBJECT_STORE__ACCESS_KEY": "test",
    "OBJECT_STORE__SECRET_KEY": "test",
    "OBJECT_STORE__BUCKET": "test",
    "ICEBERG__CATALOG_URI": "http://localhost:8181",
    "ICEBERG__WAREHOUSE": "s3://test/",
    "CLICKHOUSE__HOST": "localhost",
    "CLICKHOUSE__PASSWORD": "test",
    "AI__PROVIDER": "openai",
    "AI__MODEL": "gpt-4o",
    "AI__API_KEY": "test",
    "AI__PROMPT_TEMPLATE_DIR": "prompts",
    "CUBE__BASE_URL": "http://cube:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    "AUTH__DEV_STUB": "true",
    "AUTH__DEV_STUB_SECRET": "test-dev-stub-secret-do-not-use-in-production",
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _BASE_ENV.items():
        monkeypatch.setenv(key, value)


# --- settings ---------------------------------------------------------------


def test_observability_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    obs = get_settings().observability
    assert obs.metrics_enabled is True
    assert obs.tracing_enabled is False  # off until an endpoint is configured
    assert obs.metrics_path == "/metrics"
    get_settings.cache_clear()


def test_observability_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("OBSERVABILITY__TRACING_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__OTLP_ENDPOINT", "http://otel-collector:4318")
    monkeypatch.setenv("OBSERVABILITY__WORKER_METRICS_PORT", "9999")
    get_settings.cache_clear()
    obs = get_settings().observability
    assert obs.tracing_enabled is True
    assert obs.otlp_endpoint == "http://otel-collector:4318"
    assert obs.worker_metrics_port == 9999
    get_settings.cache_clear()


# --- /metrics exposition ----------------------------------------------------


@pytest.fixture()
def client() -> Iterator[TestClient]:
    from app.core.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_metrics_endpoint_exposes_request_and_resource_metrics(client: TestClient) -> None:
    # Make a request so the HTTP middleware records at least one observation.
    client.get("/metrics")
    body = client.get("/metrics").text

    # Request metric (visible after the prior call).
    assert "novasight_http_requests_total" in body
    # Pipeline metric series is registered (exported even at zero).
    assert "novasight_ingest_rows_total" in body or "novasight_ingest_duration_seconds" in body
    # Resource/runtime metrics from the default collectors. ``python_gc_*`` is
    # cross-platform; ``process_*`` (RSS, CPU, fds) is added on Linux (the container).
    assert "python_gc_objects_collected_total" in body or "process_resident_memory_bytes" in body


# --- tracing toggle ---------------------------------------------------------


def test_configure_tracing_noop_when_disabled() -> None:
    from app.core.config import get_settings
    from app.core.tracing import configure_tracing

    get_settings.cache_clear()
    settings = get_settings()
    assert configure_tracing(settings, service_name="novasight-test") is False
    get_settings.cache_clear()


# --- worker metrics wiring --------------------------------------------------


@pytest.fixture()
def _restore_prom_env() -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in (
        "PROMETHEUS_MULTIPROC_DIR", "prometheus_multiproc_dir",
        "dramatiq_prom_host", "dramatiq_prom_port",
    )}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_worker_observability_adds_metrics_middleware(_restore_prom_env: None) -> None:
    import dramatiq
    from dramatiq.brokers.stub import StubBroker

    from app.core.config import get_settings
    from app.reporting.observability import setup_worker_observability

    broker = StubBroker()
    dramatiq.set_broker(broker)
    get_settings.cache_clear()

    setup_worker_observability(get_settings(), service_name="novasight-worker-test")

    assert any(type(m).__name__ == "Prometheus" for m in broker.middleware)
    assert os.environ["dramatiq_prom_port"] == "9100"  # noqa: SIM112 — Dramatiq's name
    get_settings.cache_clear()


def test_worker_observability_skips_when_metrics_disabled(
    monkeypatch: pytest.MonkeyPatch, _restore_prom_env: None
) -> None:
    import dramatiq
    from dramatiq.brokers.stub import StubBroker

    from app.core.config import get_settings
    from app.reporting.observability import setup_worker_observability

    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "false")
    broker = StubBroker()
    dramatiq.set_broker(broker)
    get_settings.cache_clear()

    setup_worker_observability(get_settings(), service_name="novasight-worker-test")

    assert not any(type(m).__name__ == "Prometheus" for m in broker.middleware)
    get_settings.cache_clear()
