"""Central application settings — the ONLY place that reads the environment.

Golden rule: nothing environment- or tenant-specific is hardcoded anywhere else in the
backend. Everything is loaded here, typed, and injected via `Depends(get_settings)`.

Env vars use a nested delimiter, e.g. CLICKHOUSE__HOST, POSTGRES__PASSWORD.
A default is allowed ONLY when the value is correct in every environment. Anything that
points at infrastructure (hosts, buckets, model ids, keys) has NO default.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    host: str                       # no default — must be supplied
    port: int = 5432
    user: str
    password: SecretStr
    db: str

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    host: str
    port: int = 6379
    db: int = 0


class ObjectStoreSettings(BaseSettings):
    """S3-compatible (MinIO on-prem, S3/GCS in cloud) — the portability seam."""
    endpoint_url: str               # e.g. http://minio:9000 locally, omit for AWS S3
    region: str = "us-east-1"
    access_key: SecretStr
    secret_key: SecretStr
    bucket: str
    # Server-side encryption algorithm for objects at rest (e.g. "AES256" for SSE-S3,
    # "aws:kms" for SSE-KMS). ``None`` (default) sends no SSE header — appropriate when
    # the bucket enforces default encryption itself. When set, it is passed on every
    # write so confirmation of at-rest encryption does not depend on bucket policy.
    server_side_encryption: str | None = None


class IcebergSettings(BaseSettings):
    catalog_uri: str                # REST catalog (Polaris/Nessie)
    warehouse: str                  # warehouse location / prefix
    catalog_token: SecretStr | None = None  # optional bearer token for REST catalog auth


class ClickHouseSettings(BaseSettings):
    host: str
    port: int = 8123
    user: str = "default"
    password: SecretStr


class AISettings(BaseSettings):
    """Provider-agnostic; the gateway reads these. Never hardcode a model id."""
    provider: str                   # e.g. "anthropic" | "openai" | "azure"
    model: str                      # default model id when a tenant has no override
    api_key: SecretStr
    temperature: float = 0.0
    max_tokens: int = 1024
    prompt_template_dir: str        # versioned prompt templates on disk




class CubeSettings(BaseSettings):
    """Cube semantic-layer connection.  The backend mints per-tenant JWTs and POSTs
    to the load endpoint; Cube verifies the signature with the same secret.

    Both fields point at deployment infrastructure — no defaults.

    ``extra="ignore"`` so sibling ``CUBE__*`` env vars that the backend does not
    consume (notably ``CUBE__PORT`` — a Compose host-port knob documented in
    ``.env.example``) don't fail backend startup when routed into this nested group
    by the ``__`` delimiter. The backend reaches Cube via ``base_url`` only.
    """

    model_config = SettingsConfigDict(extra="ignore")

    base_url: str                   # e.g. http://cube:4000  (env: CUBE__BASE_URL)
    api_secret: SecretStr           # HS256 signing secret    (env: CUBE__API_SECRET)


class EncryptionSettings(BaseSettings):
    """Column-level encryption for fields tagged sensitive (Phase 5.4).

    The provider is an abstraction over the key authority: ``local`` keeps a
    symmetric master key in settings (dev / on-prem); cloud deployments select a
    KMS-backed provider. The whole group is *optional* on ``Settings`` — only
    required once a dataset actually tags a column sensitive, at which point the
    ingestion/serving paths fail closed with a clear error if it is absent.

    ``key`` has no default (it is a secret, environment-specific). For the local
    provider it is a base64-encoded 32-byte AES key.
    """

    provider: str = "local"         # "local" | (future) "aws-kms" | "gcp-kms" | ...
    key: SecretStr                  # base64 32-byte key for the local provider
    # Role (from the JWT roles claim) a principal must hold to see decrypted
    # sensitive values; everyone else gets masked output.
    sensitive_view_role: str = "sensitive_viewer"


class SmtpSettings(BaseSettings):
    """SMTP relay the reporting worker uses to email rendered reports.

    Infrastructure-pointing values (host, sender address, credentials) have NO
    defaults. The whole group is *optional* on ``Settings`` (default ``None``) so
    installs that don't use scheduled reporting need not configure a relay; when
    any ``SMTP__*`` var is set, the required fields must all be present (fail
    closed). Port and TLS carry safe, environment-identical defaults.
    """

    host: str                       # e.g. smtp.example.com  (env: SMTP__HOST)
    port: int = 587
    username: str | None = None     # omit for relays that don't require auth
    password: SecretStr | None = None
    use_tls: bool = True            # STARTTLS on connect
    from_address: str               # From: header / envelope sender (SMTP__FROM_ADDRESS)
    # TLS trust configuration for STARTTLS. ``tls_verify`` (default True) keeps
    # certificate + hostname verification on; ``ca_bundle`` points at a CA file for
    # an internal/self-signed relay (common on-prem). Both are deployment-specific,
    # so they come from settings — never a code literal (golden rule 1).
    tls_verify: bool = True
    ca_bundle: str | None = None    # path to a CA bundle (PEM) for the relay's cert


class ReportingSettings(BaseSettings):
    """Knobs for the scheduled-report worker.

    Every value here is an environment-identical *convention*, not infrastructure,
    so each carries a safe default. The things that are genuinely per-deployment or
    per-tenant — the SMTP relay (``SmtpSettings``) and each report's schedule and
    recipients — live elsewhere (settings / the ``report_definitions`` registry),
    never as literals in code (golden rule 1).
    """

    # Object-store key prefix under which a tenant's rendered reports are written.
    # Always combined with the tenant's own namespace prefix, so it never breaks
    # isolation on its own.
    storage_prefix: str = "reports"
    # Cron expression for the dispatcher heartbeat (periodiq fires it); the
    # dispatcher then matches each report's own cron against the tick.
    dispatch_cron: str = "* * * * *"
    # Hard cap on rows pulled into a single report workbook.
    max_rows: int = 100_000
    # Subject-line prefix for report emails.
    subject_prefix: str = "[Analytica] "


class AlertSettings(BaseSettings):
    """KPI-alert worker conventions (Phase 5.2).

    Every value is an environment-identical convention with a safe default; the
    genuinely per-tenant parts — each KPI's threshold, schedule, channel, and
    recipients/webhook — live in the ``kpi_thresholds`` registry, never here
    (golden rule 1). The delivery relay (SMTP) is shared with reporting.
    """

    # Cron for the dispatcher heartbeat (periodiq); each KPI's own cron is matched
    # against the tick, mirroring the reporting dispatcher.
    dispatch_cron: str = "* * * * *"
    # Timeout for webhook POSTs.
    webhook_timeout_seconds: float = 10.0
    # Subject-line prefix for alert emails.
    subject_prefix: str = "[Analytica][ALERT] "


class AuthSettings(BaseSettings):
    # OIDC / RS256 settings. These point at deployment infrastructure, so they have
    # NO standalone default; the mode validator below makes them required whenever
    # real OIDC is in force (``dev_stub`` is False). The empty-string sentinel only
    # exists so dev-stub installs need not supply OIDC infra they don't use.
    oidc_issuer: str = ""
    oidc_audience: str = ""
    jwks_url: str = ""

    # Developer stub: HS256 signing with a shared secret — NEVER enabled in production.
    # Secure default is False; must be explicitly set to True in local/dev environments.
    dev_stub: bool = False
    dev_stub_secret: SecretStr | None = None

    # The JWT claim name that carries the tenant identifier (e.g. "tenant").
    # Matches whatever our OIDC provider / token issuance convention sets.
    tenant_claim: str = "tenant"

    # The JWT claim name carrying the principal's roles (a list of strings). Used to
    # gate access to decrypted sensitive columns (see EncryptionSettings).
    roles_claim: str = "roles"

    # Role (from the roles claim) a principal must hold to operate the control plane
    # (provision / de-provision tenants). An environment-identical convention with a
    # safe default, overridable via AUTH__PLATFORM_ADMIN_ROLE — never a code literal at
    # the call site (golden rule 1). This is a *platform* role, not a tenant role:
    # control-plane endpoints are not tenant-scoped.
    platform_admin_role: str = "platform_admin"

    @model_validator(mode="after")
    def _require_mode_config(self) -> AuthSettings:
        """Fail closed at startup if the selected auth mode is misconfigured.

        Real OIDC (``dev_stub`` False) must have the issuer, audience, and JWKS
        URL; dev-stub mode must have its signing secret. This keeps the
        infrastructure-pointing OIDC values effectively required (golden rule:
        no environment-specific value is silently defaulted) while still letting
        dev-stub installs omit OIDC config they don't use.
        """
        if self.dev_stub:
            if self.dev_stub_secret is None:
                raise ValueError(
                    "AUTH__DEV_STUB_SECRET is required when AUTH__DEV_STUB is true"
                )
            return self
        missing = [
            name
            for name, value in (
                ("AUTH__OIDC_ISSUER", self.oidc_issuer),
                ("AUTH__OIDC_AUDIENCE", self.oidc_audience),
                ("AUTH__JWKS_URL", self.jwks_url),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"{', '.join(missing)} required when AUTH__DEV_STUB is false (real OIDC)"
            )
        return self


class SeedTenantSettings(BaseSettings):
    """Identity of the bootstrap tenant created by the seed script.

    On-prem single-tenant installs serve exactly this tenant; cloud deployments
    may seed a default/demo tenant and create the rest via the API. The values
    are deployment-chosen (no defaults) so the bootstrap tenant identity is never
    a literal in code — the seed script reads them from here.
    """

    slug: str                       # used to derive physical resource names
    name: str                       # human-facing display name
    admin_email: str                # first user provisioned for the tenant


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str                # "local" | "onprem" | "cloud"
    log_level: str = "INFO"

    # Safe-everywhere defaults (not infrastructure-specific)
    default_page_size: int = 50
    max_query_rows: int = 100_000
    max_upload_mb: int = 100

    # Governed serving-table allow-list for NL→SQL validation.  Uses the same env
    # var that Dagster and Cube consume so the physical table name has one source of
    # truth across all layers.  A safe default is allowed because the name is
    # identical in every environment unless an operator explicitly renames the table.
    serving_regional_sales_table: str = "serving_regional_sales"
    # env: SERVING_REGIONAL_SALES_TABLE

    postgres: PostgresSettings
    redis: RedisSettings
    object_store: ObjectStoreSettings
    iceberg: IcebergSettings
    clickhouse: ClickHouseSettings
    ai: AISettings
    cube: CubeSettings
    auth: AuthSettings
    seed_tenant: SeedTenantSettings
    # Background reporting. ``reporting`` is always present (all-default conventions);
    # ``smtp`` is optional — only required when scheduled reporting is actually used,
    # and validated at the point of use so the app/worker fails closed with a clear
    # error rather than emailing nothing.
    reporting: ReportingSettings = ReportingSettings()
    alerts: AlertSettings = AlertSettings()
    smtp: SmtpSettings | None = None
    # Column-level encryption. Optional — only required once a dataset tags a column
    # sensitive; the ingestion/serving paths validate its presence at point of use.
    encryption: EncryptionSettings | None = None


@lru_cache
def get_settings() -> Settings:
    """Cached accessor. Inject via `Depends(get_settings)`; override in tests."""
    return Settings()
