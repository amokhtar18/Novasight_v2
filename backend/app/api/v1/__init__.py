# v1 router assembly
from fastapi import APIRouter

from app.api.v1.ai import router as ai_router
from app.api.v1.auth import router as auth_router
from app.api.v1.charts import router as charts_router
from app.api.v1.dashboards import router as dashboards_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.health import router as health_router
from app.api.v1.me import router as me_router
from app.api.v1.semantic import router as semantic_router
from app.api.v1.semantic_models import router as semantic_models_router
from app.api.v1.sources import router as sources_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.users import router as users_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(me_router)
v1_router.include_router(datasets_router)
v1_router.include_router(ai_router)
v1_router.include_router(tenants_router)
v1_router.include_router(users_router)
v1_router.include_router(sources_router)
v1_router.include_router(semantic_router)
v1_router.include_router(semantic_models_router)
v1_router.include_router(charts_router)
v1_router.include_router(dashboards_router)
