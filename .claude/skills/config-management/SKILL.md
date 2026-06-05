---
name: config-management
description: >
  Rules and patterns for configuration in Analytica. Apply whenever writing or
  reviewing backend, data, or AI code that references a host, port, URL, credential,
  bucket, file path, model name, timeout, threshold, or feature flag. Enforces: nothing
  environment- or tenant-specific is ever hardcoded — all config is loaded from the
  environment through one typed settings object.
---

# Configuration management

**Principle: code is identical across environments; only configuration differs.**
The single source of truth is `backend/app/core/config.py` (a pydantic-settings
`BaseSettings` tree). Nothing else reads `os.environ`.

## The rules

1. **One settings object.** Define typed, nested settings in `app/core/config.py`.
   Expose a cached accessor `get_settings()`. Everything else imports from there.
2. **Inject, don't import-at-module-level.** In FastAPI, depend on settings via
   `Depends(get_settings)` so they are overridable in tests.
3. **Every value is documented.** Adding a setting means updating three places in the
   same change: the settings model, `.env.example` (with a comment), and
   `docs/CONFIGURATION.md`.
4. **Secrets are secrets.** Use `SecretStr`. Never log, never put in `.env.example`
   (only placeholders), never commit a real `.env`.
5. **Sensible, safe defaults only.** A default is allowed only when it is correct in
   every environment (e.g. a page size of 50). Anything that points at infrastructure
   (hosts, buckets, model names) has **no default** and must be supplied.
6. **Tenant-specific values are runtime data, not config.** They come from the tenant
   registry (database), resolved per request — never from env or literals.

## Smell test (reject in review)
A string or number is a config smell if its correct value could differ between
laptop / on-prem / cloud / per tenant. Examples that must NOT be literals:
`"localhost"`, `8123`, `"http://minio:9000"`, `"analytica-bucket"`, a model id,
`temperature=0.2`, a retry count, an absolute path, an API key.

## Reference pattern
```python
# app/core/config.py
from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class ClickHouseSettings(BaseSettings):
    host: str                      # no default — must be provided
    port: int = 8123               # safe default, same everywhere
    user: str = "default"
    password: SecretStr

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_nested_delimiter="__", extra="ignore"
    )
    environment: str               # e.g. "local" | "onprem" | "cloud"
    clickhouse: ClickHouseSettings

@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```
Env vars use the nested delimiter: `CLICKHOUSE__HOST`, `CLICKHOUSE__PASSWORD`, etc.

## Frontend
No env values baked into components. Read from `import.meta.env` at build, or fetch a
small `/config` payload at runtime for things that vary per deployment.
