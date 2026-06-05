"""NL→Chart sub-package (Phase 4, Task 4.4).

Public surface
--------------
- ``NLToChartService``       — orchestrates the 4-stage Ground→Generate→Validate→Resolve pipeline.
- ``get_nl_to_chart_service`` — FastAPI dependency.
- ``ChartValidationError``   — raised by the validator on any guardrail violation.
"""
from app.ai.nl_chart.service import NLToChartService, get_nl_to_chart_service
from app.ai.nl_chart.validator import ChartValidationError

__all__ = [
    "ChartValidationError",
    "NLToChartService",
    "get_nl_to_chart_service",
]
