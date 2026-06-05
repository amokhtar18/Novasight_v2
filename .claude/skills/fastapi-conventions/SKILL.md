---
name: fastapi-conventions
description: >
  Structure and conventions for the FastAPI backend. Apply when creating routers,
  services, dependencies, schemas, error handling, or background workers in
  backend/app/. Covers module layout, dependency injection, Pydantic schemas, async,
  and migrations.
---

# FastAPI conventions

## Module layout
```
backend/app/
  core/        # config.py (settings), db.py (session), security.py, logging.py
  api/         # routers only — thin; one module per resource; v1/ versioned
  tenancy/     # tenant context + registry (see tenancy-isolation skill)
  ingestion/   # dlt pipeline definitions + triggers
  ai/          # NL→SQL, NL→chart, insights, llm gateway
  reporting/   # Dramatiq workers: scheduled Excel exports, KPI alerts
  models/      # SQLAlchemy ORM models (control plane)
  schemas/     # Pydantic request/response models
  services/    # business logic; routers call services, not the DB directly
```

## Conventions
- **Routers are thin.** Validation via Pydantic, work delegated to `services/`.
  No business logic or raw SQL in routers.
- **Dependencies for cross-cutting concerns**: `get_settings`, `get_db`,
  `get_tenant_context`, `get_principal`. Compose them with `Depends`.
- **Async all the way**: async endpoints, async DB driver, `httpx.AsyncClient` for
  outbound calls. Don't block the event loop.
- **Schemas are explicit**: separate `Create`, `Update`, `Read` models; never return
  ORM objects directly; never accept un-modeled dicts.
- **Errors**: raise typed `HTTPException`s (or domain exceptions mapped by a handler).
  Messages are user-safe; details go to structured logs, never to the client.
- **Migrations**: every schema change has an Alembic migration; never mutate schema
  outside migrations. Migrations are reviewed and reversible.
- **Logging**: structured (JSON), tenant-scoped, PII-redacted. No secrets.
- **Background work**: long/scheduled jobs (Excel reports, alerts) go to Dramatiq
  workers in `reporting/`, never run inline in a request.

## Endpoint skeleton
```python
# app/api/v1/datasets.py
from fastapi import APIRouter, Depends
from app.schemas.dataset import DatasetCreate, DatasetRead
from app.services.datasets import DatasetService
from app.tenancy.context import get_tenant_context, TenantContext

router = APIRouter(prefix="/datasets", tags=["datasets"])

@router.post("", response_model=DatasetRead, status_code=201)
async def create_dataset(
    payload: DatasetCreate,
    ctx: TenantContext = Depends(get_tenant_context),
    svc: DatasetService = Depends(),
) -> DatasetRead:
    return await svc.create(ctx, payload)   # scope is the context, not the payload
```

Definition of done: `uv run ruff check .` and `uv run mypy app` are clean, tests pass.
