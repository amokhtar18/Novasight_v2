"""Insights sub-package — automated summaries and source-based suggestions.

Sub-feature (a): POST /api/v1/ai/insights
  Produces a 2-4 sentence natural-language summary of an already-computed
  QueryResponse result set.  A no-invented-numbers guardrail verifies that
  every numeric token in the generated summary is traceable to the result set
  (defence against hallucination).

Sub-feature (b): POST /api/v1/ai/datasets/{dataset_id}/suggestions
  Profiles a tenant-owned dataset (column names/types, cardinality, stats,
  sample values) then generates 3-5 ChartSpec suggestions grounded on the
  profile columns.  Every suggested spec is validated: schema-strict AND
  column allow-list (only columns the dataset actually has).

Both features follow the four-stage nl-to-sql-grounding skill pattern:
Ground → Generate → Validate → Execute/Return.
"""
from app.ai.insights.guardrail import InsightGuardrailError, verify_no_invented_numbers
from app.ai.insights.suggestions import SuggestionsService, get_suggestions_service
from app.ai.insights.summary import InsightService, get_insight_service

__all__ = [
    "InsightGuardrailError",
    "InsightService",
    "SuggestionsService",
    "get_insight_service",
    "get_suggestions_service",
    "verify_no_invented_numbers",
]
