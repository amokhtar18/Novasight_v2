"""Tests for app/core/config.py.

Verifies two acceptance criteria:
(a) get_settings() builds a fully-populated Settings object from env vars only
    (using monkeypatch to inject all required values via __ delimiter).
(b) A missing required infra value (e.g. POSTGRES__HOST) causes a ValidationError,
    i.e. the system fails closed — it cannot start with incomplete configuration.

get_settings() is @lru_cache'd; each test clears the cache before exercising it.
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Minimal complete env — every field that has no default must be present.
# ---------------------------------------------------------------------------
COMPLETE_ENV: dict[str, str] = {
    # app-level
    "ENVIRONMENT": "local",
    "LOG_LEVEL": "DEBUG",
    "DEFAULT_PAGE_SIZE": "25",
    "MAX_QUERY_ROWS": "50000",
    "MAX_UPLOAD_MB": "50",
    # postgres
    "POSTGRES__HOST": "db.example.internal",
    "POSTGRES__PORT": "5432",
    "POSTGRES__USER": "novasight",
    "POSTGRES__PASSWORD": "s3cr3t-pg",
    "POSTGRES__DB": "control_plane",
    # redis
    "REDIS__HOST": "redis.example.internal",
    "REDIS__PORT": "6379",
    "REDIS__DB": "0",
    # object store
    "OBJECT_STORE__ENDPOINT_URL": "http://minio.example.internal:9000",
    "OBJECT_STORE__REGION": "us-east-1",
    "OBJECT_STORE__ACCESS_KEY": "minio-access",
    "OBJECT_STORE__SECRET_KEY": "minio-s3cr3t",
    "OBJECT_STORE__BUCKET": "novasight-data",
    # iceberg
    "ICEBERG__CATALOG_URI": "http://nessie.example.internal:19120/api/v1",
    "ICEBERG__WAREHOUSE": "s3://novasight-data/warehouse",
    # clickhouse
    "CLICKHOUSE__HOST": "ch.example.internal",
    "CLICKHOUSE__PORT": "8123",
    "CLICKHOUSE__USER": "default",
    "CLICKHOUSE__PASSWORD": "s3cr3t-ch",
    # ai
    "AI__PROVIDER": "anthropic",
    "AI__MODEL": "claude-test-model",
    "AI__API_KEY": "sk-test-key",
    "AI__TEMPERATURE": "0.0",
    "AI__MAX_TOKENS": "1024",
    "AI__PROMPT_TEMPLATE_DIR": "/app/ai/prompts",
    # cube semantic layer
    "CUBE__BASE_URL": "http://cube.example.internal:4000",
    "CUBE__API_SECRET": "test-cube-secret-at-least-32-chars!",
    # auth
    "AUTH__OIDC_ISSUER": "https://auth.example.com/realms/novasight",
    "AUTH__OIDC_AUDIENCE": "novasight-api",
    "AUTH__JWKS_URL": "https://auth.example.com/realms/novasight/protocol/openid-connect/certs",
    # seed tenant (bootstrap)
    "SEED_TENANT__SLUG": "local",
    "SEED_TENANT__NAME": "Local Tenant",
    "SEED_TENANT__ADMIN_EMAIL": "admin@local.test",
}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Clear the lru_cache before every test so env changes take effect."""
    get_settings.cache_clear()


class TestSettingsBuildsFromEnv:
    """(a) Settings are fully populated when all required env vars are present."""

    def test_builds_with_complete_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        settings = get_settings()

        # app-level
        assert settings.environment == "local"
        assert settings.log_level == "DEBUG"
        assert settings.default_page_size == 25
        assert settings.max_query_rows == 50_000
        assert settings.max_upload_mb == 50

    def test_postgres_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.postgres.host == "db.example.internal"
        assert s.postgres.port == 5432
        assert s.postgres.user == "novasight"
        assert s.postgres.db == "control_plane"
        # password must be SecretStr — .get_secret_value() needed to read it
        assert s.postgres.password.get_secret_value() == "s3cr3t-pg"

    def test_object_store_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.object_store.endpoint_url == "http://minio.example.internal:9000"
        assert s.object_store.bucket == "novasight-data"
        assert s.object_store.access_key.get_secret_value() == "minio-access"
        assert s.object_store.secret_key.get_secret_value() == "minio-s3cr3t"

    def test_clickhouse_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.clickhouse.host == "ch.example.internal"
        assert s.clickhouse.port == 8123
        assert s.clickhouse.password.get_secret_value() == "s3cr3t-ch"

    def test_ai_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.ai.provider == "anthropic"
        assert s.ai.model == "claude-test-model"
        assert s.ai.api_key.get_secret_value() == "sk-test-key"
        assert s.ai.temperature == 0.0
        assert s.ai.max_tokens == 1024
        assert s.ai.prompt_template_dir == "/app/ai/prompts"

    def test_auth_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.auth.oidc_issuer == "https://auth.example.com/realms/novasight"
        assert s.auth.oidc_audience == "novasight-api"
        assert s.auth.jwks_url == (
            "https://auth.example.com/realms/novasight"
            "/protocol/openid-connect/certs"
        )

    def test_postgres_url_property_contains_no_literal_infra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The .url property on PostgresSettings must embed the configured host, not a literal."""
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()
        url = s.postgres.url

        assert "db.example.internal" in url
        assert "control_plane" in url
        # ensure it's an asyncpg URL for SQLAlchemy async
        assert url.startswith("postgresql+asyncpg://")

    def test_seed_tenant_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.seed_tenant.slug == "local"
        assert s.seed_tenant.name == "Local Tenant"
        assert s.seed_tenant.admin_email == "admin@local.test"

    def test_cube_nested_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s = get_settings()

        assert s.cube.base_url == "http://cube.example.internal:4000"
        assert s.cube.api_secret.get_secret_value() == "test-cube-secret-at-least-32-chars!"

    def test_sibling_cube_port_does_not_break_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CUBE__* var the backend doesn't consume must not fail startup.

        Regression: CUBE__PORT is a Compose host-port knob (documented in
        .env.example) that the nested ``__`` delimiter routes into the CubeSettings
        group. Without ``extra="ignore"`` on that group, its mere presence in the
        environment raised a ValidationError and the backend could not start.
        """
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("CUBE__PORT", "4000")

        s = get_settings()

        # Cube settings still load; the unconsumed sibling var is ignored.
        assert s.cube.base_url == "http://cube.example.internal:4000"

    def test_mcp_path_not_clobbered_by_os_path_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``McpSettings.path`` must keep its default and not bind the OS ``PATH``.

        Regression: McpSettings is a BaseSettings that reads the environment, so
        without the ``env_prefix="MCP__"`` scope its unprefixed ``path`` field bound
        the ubiquitous, case-insensitive ``PATH`` OS variable — the MCP server then
        served at a garbage route (``/usr/local/bin:...``) instead of ``/mcp``.
        """
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
        monkeypatch.setenv("HOST", "some-os-host")

        s = get_settings()

        # The OS PATH/HOST must not leak into the MCP group; defaults are preserved.
        assert s.mcp.path == "/mcp"
        assert s.mcp.host == "0.0.0.0"  # noqa: S104 — asserting the container-bind default

    def test_mcp_prefixed_overrides_apply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``MCP__*`` env vars still populate the MCP group through the prefix."""
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("MCP__BACKEND_BASE_URL", "http://api:8000/api/v1")
        monkeypatch.setenv("MCP__PATH", "/custom-mcp")
        monkeypatch.setenv("MCP__PORT", "8901")

        s = get_settings()

        assert s.mcp.backend_base_url == "http://api:8000/api/v1"
        assert s.mcp.path == "/custom-mcp"
        assert s.mcp.port == 8901

    def test_get_settings_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """lru_cache means repeated calls return the same object."""
        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestSettingsFailsClosedOnMissingRequired:
    """(b) Missing required infra values must raise a ValidationError — fail closed."""

    def _env_without(self, *keys: str) -> dict[str, str]:
        return {k: v for k, v in COMPLETE_ENV.items() if k not in keys}

    def test_missing_postgres_host_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("POSTGRES__HOST").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("POSTGRES__HOST", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_postgres_password_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("POSTGRES__PASSWORD").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("POSTGRES__PASSWORD", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_clickhouse_host_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("CLICKHOUSE__HOST").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("CLICKHOUSE__HOST", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_object_store_bucket_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("OBJECT_STORE__BUCKET").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("OBJECT_STORE__BUCKET", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_ai_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("AI__API_KEY").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("AI__API_KEY", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_environment_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("ENVIRONMENT").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_missing_seed_tenant_slug_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic import ValidationError

        for key, value in self._env_without("SEED_TENANT__SLUG").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("SEED_TENANT__SLUG", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_oidc_mode_missing_jwks_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Real-OIDC mode (dev_stub False) must reject a missing JWKS URL at startup.

        The OIDC fields point at deployment infrastructure, so omitting one is a
        misconfiguration the app must fail closed on rather than start silently.
        """
        from pydantic import ValidationError

        for key, value in self._env_without("AUTH__JWKS_URL").items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("AUTH__JWKS_URL", raising=False)

        with pytest.raises(ValidationError):
            get_settings()

    def test_dev_stub_mode_missing_secret_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dev-stub mode (dev_stub True) must reject a missing signing secret."""
        from pydantic import ValidationError

        for key, value in COMPLETE_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("AUTH__DEV_STUB", "true")
        monkeypatch.delenv("AUTH__DEV_STUB_SECRET", raising=False)

        with pytest.raises(ValidationError):
            get_settings()


class TestAuthModeConfig:
    """The auth mode validator allows dev installs to omit OIDC infrastructure."""

    def test_dev_stub_mode_does_not_require_oidc_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With dev_stub True + a secret, the OIDC infra fields may be absent."""
        env = {k: v for k, v in COMPLETE_ENV.items()
               if k not in {"AUTH__OIDC_ISSUER", "AUTH__OIDC_AUDIENCE", "AUTH__JWKS_URL"}}
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        for key in ("AUTH__OIDC_ISSUER", "AUTH__OIDC_AUDIENCE", "AUTH__JWKS_URL"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("AUTH__DEV_STUB", "true")
        monkeypatch.setenv("AUTH__DEV_STUB_SECRET", "local-dev-secret")

        s = get_settings()

        assert s.auth.dev_stub is True
        assert s.auth.dev_stub_secret is not None
        assert s.auth.dev_stub_secret.get_secret_value() == "local-dev-secret"
