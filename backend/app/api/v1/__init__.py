# v1 router assembly
from fastapi import APIRouter

from app.api.v1.datasets import router as datasets_router
from app.api.v1.health import router as health_router
from app.api.v1.me import router as me_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(health_router)
v1_router.include_router(me_router)
v1_router.include_router(datasets_router)
