"""Control-plane ORM models.

Importing this package registers every model on ``Base.metadata``. Alembic's
``env.py`` and the test schema bootstrap both rely on that side effect, so import
from here (``from app.models import Base, Tenant, ...``) rather than reaching into
individual modules.
"""
from __future__ import annotations

from app.models.base import Base, TimestampMixin
from app.models.chart import Chart
from app.models.dashboard import Dashboard, DashboardTile
from app.models.dataset import Dataset
from app.models.dbt_model import DbtModel, DbtTest
from app.models.kpi_threshold import KpiThreshold
from app.models.pipeline import Pipeline, PipelineRun
from app.models.report_definition import ReportDefinition
from app.models.schedule import Schedule
from app.models.schedule_pipeline import SchedulePipeline
from app.models.semantic_model import SemanticModel
from app.models.source_connection import SourceConnection
from app.models.tenant import Tenant
from app.models.tenant_resource_map import TenantResourceMap
from app.models.transform_job import TransformJob
from app.models.user import User

__all__ = [
    "Base",
    "Chart",
    "Dashboard",
    "DashboardTile",
    "Dataset",
    "DbtModel",
    "DbtTest",
    "KpiThreshold",
    "Pipeline",
    "PipelineRun",
    "ReportDefinition",
    "Schedule",
    "SchedulePipeline",
    "SemanticModel",
    "SourceConnection",
    "Tenant",
    "TenantResourceMap",
    "TimestampMixin",
    "TransformJob",
    "User",
]
