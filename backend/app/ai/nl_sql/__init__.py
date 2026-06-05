"""NL→SQL sub-package (Phase 4, Task 4.3).

Public surface
--------------
- ``NLToSQLService``       — orchestrates the 4-stage Ground→Generate→Validate→Execute pipeline.
- ``get_nl_to_sql_service`` — FastAPI dependency.
- ``SQLValidationError``   — raised by the validator on any guardrail violation.
"""
from app.ai.nl_sql.service import NLToSQLService, get_nl_to_sql_service
from app.ai.nl_sql.validator import SQLValidationError

__all__ = [
    "NLToSQLService",
    "SQLValidationError",
    "get_nl_to_sql_service",
]
