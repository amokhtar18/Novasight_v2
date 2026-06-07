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
    # Filesystem path where the semantic-model codegen writes generated per-tenant
    # Cube model files (a volume shared read-only with the Cube container). Optional:
    # when unset, codegen renders but does not write (e.g. in tests, or before the
    # shared volume is wired). Env: CUBE__MODEL_DIR.
    model_dir: str | None = None


class DbtSettings(BaseSettings):
    """dbt codegen output (the dbt model + test wizard, #5/#6).

    ``models_dir`` is the filesystem path where the codegen writes generated per-tenant
    dbt model files (``tenant_<schema>/<name>.sql`` + ``schema.yml``) — a directory
    inside the dbt project that the Dagster/dbt run reads. Optional: when unset, the
    codegen renders but does not write (e.g. in tests, or before the project volume is
    wired). Env: ``DBT__MODELS_DIR``. Golden rule 1: no path is hardcoded.
    """

    model_config = SettingsConfigDict(extra="ignore")

    models_dir: str | None = None


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
    subject_prefix: str = "[NovaSight] "


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
    subject_prefix: str = "[NovaSight][ALERT] "


class ObservabilitySettings(BaseSettings):
    """Metrics + tracing knobs (Phase 6.4).

    Conventions carry safe, environment-identical defaults; the one value that points
    at infrastructure — the OTLP collector endpoint — has no default and tracing stays
    OFF until it is supplied (golden rule 1: endpoints/exporters come from the
    environment, never a literal). Env vars use the ``OBSERVABILITY__`` group, e.g.
    ``OBSERVABILITY__OTLP_ENDPOINT``.
    """

    # Prometheus metrics.
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    # Port the worker exposes its metrics on via an embedded HTTP server (the API
    # serves metrics on its own port at ``metrics_path``; workers have no HTTP server
    # of their own, so they start a tiny one just for scraping).
    worker_metrics_port: int = 9100

    # OpenTelemetry tracing. Disabled unless explicitly enabled AND an endpoint is set.
    tracing_enabled: bool = False
    otlp_endpoint: str = ""  # e.g. http://otel-collector:4318 — OTLP/HTTP base URL
    # Base service name; each process refines it (…-api, …-worker) at startup.
    service_name: str = "novasight"
    # Head sampling ratio in [0, 1]; 1.0 = sample every trace.
    trace_sample_ratio: float = 1.0


class DagsterSettings(BaseSettings):
    """Backend↔Dagster control-plane connection (Phase 1).

    The backend launches runs and reloads the code location over Dagster's GraphQL
    API so users schedule/run pipelines and dbt jobs without opening Dagster. The
    one infrastructure-pointing value — ``graphql_url`` — has no real default (empty
    sentinel disables the integration; the client returns a clear error if invoked),
    keeping golden rule 1. The location/repository names are environment-identical
    conventions matching the ``novasight_orchestration`` code location.
    """

    graphql_url: str = ""  # e.g. http://dagster:3000/graphql — empty disables control
    # Code location (the -m module name) and Definitions' repository name.
    repository_location: str = "novasight_orchestration"
    repository_name: str = "__repository__"
    request_timeout_seconds: float = 30.0


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

    # Password-auth mode: the backend itself issues HS256 access/refresh tokens
    # (see ``app/services/auth.py``) signed with this secret, and verifies them with
    # the same secret. Set this (with ``dev_stub`` left False) for the self-contained
    # password login that works out of the box in a single deployment. No default —
    # it is an environment-specific secret (golden rule 1). When neither ``dev_stub``
    # nor ``session_secret`` is set, real OIDC (RS256/JWKS) is in force.
    session_secret: SecretStr | None = None
    # Access / refresh token lifetimes in seconds. Environment-identical conventions
    # with safe defaults; overridable via AUTH__ACCESS_TTL_SECONDS / AUTH__REFRESH_TTL_SECONDS.
    access_ttl_seconds: int = 3600            # 1 hour
    refresh_ttl_seconds: int = 1_209_600      # 14 days

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

    # Tenant-scoped role a user must hold to operate orchestration (create/run/schedule
    # pipelines and dbt jobs) within their own tenant. A "super user" inside the tenant,
    # distinct from the platform admin who manages tenants. Convention with a safe
    # default, overridable via AUTH__TENANT_SUPERUSER_ROLE.
    tenant_superuser_role: str = "superuser"

    @property
    def hs256_secret(self) -> str | None:
        """The active HS256 secret for issuing/verifying password-mode tokens.

        ``dev_stub`` uses ``dev_stub_secret``; password mode uses ``session_secret``.
        Returns ``None`` when neither is configured (real OIDC is in force), which
        also disables the password-login endpoints.
        """
        if self.dev_stub and self.dev_stub_secret is not None:
            return self.dev_stub_secret.get_secret_value()
        if self.session_secret is not None:
            return self.session_secret.get_secret_value()
        return None

    @model_validator(mode="after")
    def _require_mode_config(self) -> AuthSettings:
        """Fail closed at startup if the selected auth mode is misconfigured.

        Three mutually exclusive modes, resolved in order:
          * dev-stub (``dev_stub`` True) — requires ``dev_stub_secret``.
          * password (``session_secret`` set) — the backend signs+verifies HS256.
          * real OIDC (neither of the above) — requires issuer, audience, JWKS URL.
        This keeps infrastructure-pointing values effectively required (golden rule:
        no environment-specific value is silently defaulted) while letting each mode
        omit the config it does not use.
        """
        if self.dev_stub:
            if self.dev_stub_secret is None:
                raise ValueError(
                    "AUTH__DEV_STUB_SECRET is required when AUTH__DEV_STUB is true"
                )
            return self
        if self.session_secret is not None:
            # Password mode: backend-issued HS256 tokens; no OIDC infra required.
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
                f"{', '.join(missing)} required for OIDC mode "
                "(set AUTH__DEV_STUB or AUTH__SESSION_SECRET to use HS256 instead)"
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
    # Password for the seeded admin user (HS256/password mode). No default — it is
    # a secret (golden rule 1). When set, the seed grants the admin the platform-admin
    # and tenant-superuser roles so the install is operable out of the box. Omit in
    # OIDC mode (the IdP owns credentials), where the admin user has no local password.
    admin_password: SecretStr | None = None


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
    # periodiq heartbeat cron for the pipeline-schedule dispatcher (#4). A 5-field
    # cron; every minute by default — the dispatcher then checks each schedule's own
    # cron. Env: PIPELINE_DISPATCH_CRON.
    pipeline_dispatch_cron: str = "* * * * *"

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
    # Observability (metrics + tracing). All-default conventions; tracing stays off
    # until an OTLP endpoint is configured.
    observability: ObservabilitySettings = ObservabilitySettings()
    # Backend↔Dagster control plane. All-default conventions; the integration stays
    # off until DAGSTER__GRAPHQL_URL is set.
    dagster: DagsterSettings = DagsterSettings()
    # dbt codegen output dir (the dbt model/test wizard). All-default; writing is
    # skipped until DBT__MODELS_DIR points at the dbt project's models volume.
    dbt: DbtSettings = DbtSettings()
    smtp: SmtpSettings | None = None
    # Column-level encryption. Optional — only required once a dataset tags a column
    # sensitive; the ingestion/serving paths validate its presence at point of use.
    encryption: EncryptionSettings | None = None


@lru_cache
def get_settings() -> Settings:
    """Cached accessor. Inject via `Depends(get_settings)`; override in tests."""
    return Settings()
