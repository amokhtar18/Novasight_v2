"""Control-plane ORM models.

Importing this package registers every model on ``Base.metadata``. Alembic's
``env.py`` and the test schema bootstrap both rely on that side effect, so import
from here (``from app.models import Base, Tenant, ...``) rather than reaching into
individual modules.
"""
from __future__ import annotations

from app.models.base import Base, TimestampMixin
from app.models.dataset import Dataset
from app.models.kpi_threshold import KpiThreshold
from app.models.report_definition import ReportDefinition
from app.models.tenant import Tenant
from app.models.tenant_resource_map import TenantResourceMap
from app.models.user import User

__all__ = [
    "Base",
    "Dataset",
    "KpiThreshold",
    "ReportDefinition",
    "Tenant",
    "TenantResourceMap",
    "TimestampMixin",
    "User",
]
