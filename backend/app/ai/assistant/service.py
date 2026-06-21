"""Unified assistant service: one grounded agent for chat, charts & insights (#7/#11).

Merges what were three separate AI surfaces (chat, NL→SQL, insights) into a single
agent (built on ``app.ai.agent``) whose skills delegate to the existing validated
services. The assistant proposes artifacts — generated charts and insight summaries —
that ride back on the reply for the user to **save/pin/confirm** (propose-then-confirm,
golden rule #3: nothing is queried outside the governed semantic layer).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Depends
from pydantic import BaseModel

from app.ai.agent import Agent, Skill, SkillRegistry
from app.ai.gateway import LLMGateway, get_llm_gateway
from app.ai.gateway.loader import PromptLoader
from app.ai.insights import InsightService, get_insight_service
from app.ai.nl_chart import NLToChartService, get_nl_to_chart_service
from app.ai.nl_sql import NLToSQLService, get_nl_to_sql_service
from app.core.config import Settings, get_settings
from app.schemas.chart import ChartSpec
from app.schemas.semantic import SemanticQueryRequest
from app.services.semantic import SemanticService, get_semantic_service
from app.tenancy.context import TenantContext

logger = logging.getLogger(__name__)

# Cap rows returned to the model so a large result can't blow the context window.
_MAX_TOOL_ROWS = 50

LIST_MODELS = "list_semantic_models"
QUERY_MODEL = "query_semantic_model"
NL_TO_SQL = "nl_to_sql"
NL_TO_CHART = "nl_to_chart"
SUMMARIZE_INSIGHT = "summarize_insight"

# Fallback if the versioned prompt file isn't present (e.g. tests, misconfig).
_DEFAULT_SYSTEM = (
    "You are NovaSight's analytics assistant. Answer ONLY by calling the provided "
    "skills, which query a governed semantic layer. Never invent numbers. First call "
    "list_semantic_models, then query_semantic_model or nl_to_sql; call nl_to_chart to "
    "visualize and summarize_insight for takeaways. Base every figure on a skill result."
)


def build_skills(
    semantic: SemanticService,
    nl_sql: NLToSQLService,
    nl_chart: NLToChartService,
    insight: InsightService,
    chart_sink: list[ChartSpec],
    insight_sink: list[str],
) -> list[Skill]:
    """Wire the assistant's grounded skills from the existing services.

    ``chart_sink``/``insight_sink`` are per-request lists the chart/insight skills
    append to, so ``AssistantService`` can surface the proposed artifacts on its reply.
    """

    async def list_models(ctx: TenantContext, _inp: dict[str, Any]) -> str:
        models = await semantic.list_models(ctx)
        return json.dumps(
            [
                {
                    "name": m.name,
                    "measures": [x.name for x in m.measures],
                    "dimensions": [x.name for x in m.dimensions],
                }
                for m in models
            ]
        )

    async def query_model(ctx: TenantContext, inp: dict[str, Any]) -> str:
        req = SemanticQueryRequest(
            measures=list(inp.get("measures", [])),
            dimensions=list(inp.get("dimensions", [])),
            limit=inp.get("limit"),
        )
        resp = await semantic.query(ctx, req)
        return json.dumps(
            {
                "columns": resp.columns,
                "rows": resp.rows[:_MAX_TOOL_ROWS],
                "row_count": resp.row_count,
            }
        )

    async def nl_to_sql_skill(ctx: TenantContext, inp: dict[str, Any]) -> str:
        sql, result = await nl_sql.query(ctx, question=str(inp.get("question", "")))
        return json.dumps(
            {
                "sql": sql,
                "columns": result.column_names,
                "rows": [list(r) for r in result.rows[:_MAX_TOOL_ROWS]],
            }
        )

    async def nl_to_chart_skill(ctx: TenantContext, inp: dict[str, Any]) -> str:
        spec, data = await nl_chart.generate(ctx, request=str(inp.get("request", "")))
        chart_sink.append(spec)
        return json.dumps(
            {
                "chart_generated": True,
                "chart_type": spec.type,
                "title": spec.options.title,
                "columns": data.columns,
                "row_count": data.row_count,
            }
        )

    async def summarize_insight(ctx: TenantContext, inp: dict[str, Any]) -> str:
        req = SemanticQueryRequest(
            measures=list(inp.get("measures", [])),
            dimensions=list(inp.get("dimensions", [])),
            limit=inp.get("limit"),
        )
        resp = await semantic.query(ctx, req)
        summary = await insight.summarise(
            ctx,
            columns=resp.columns,
            rows=resp.rows,
            context_hint=inp.get("context_hint"),
        )
        insight_sink.append(summary)
        return json.dumps({"summary": summary, "rows_analysed": resp.row_count})

    return [
        Skill(
            name=LIST_MODELS,
            description=(
                "List the governed semantic models the tenant may query, with each "
                "model's measures and dimensions. Call this first."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=list_models,
        ),
        Skill(
            name=QUERY_MODEL,
            description=(
                "Run a structured query against the governed semantic layer with "
                "fully-qualified measure/dimension names. Returns columns + rows."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "measures": {"type": "array", "items": {"type": "string"}},
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            handler=query_model,
        ),
        Skill(
            name=NL_TO_SQL,
            description=(
                "Answer an ad-hoc analytical question by generating validated, "
                "read-only SQL over the governed layer and returning the rows."
            ),
            input_schema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
                "additionalProperties": False,
            },
            handler=nl_to_sql_skill,
        ),
        Skill(
            name=NL_TO_CHART,
            description=(
                "Generate a chart from a natural-language description over the governed "
                "semantic layer. Returns a short summary; the chart rides back on the "
                "reply for the user to save or pin."
            ),
            input_schema={
                "type": "object",
                "properties": {"request": {"type": "string"}},
                "required": ["request"],
                "additionalProperties": False,
            },
            handler=nl_to_chart_skill,
        ),
        Skill(
            name=SUMMARIZE_INSIGHT,
            description=(
                "Summarise a metric in plain language. Give the measures + dimensions "
                "to analyse; returns a grounded, no-invented-numbers narrative that "
                "rides back on the reply."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "measures": {"type": "array", "items": {"type": "string"}},
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "context_hint": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            handler=summarize_insight,
        ),
    ]


class AssistantResult(BaseModel):
    """The assistant's reply: the answer, the skills it used, and proposed artifacts.

    ``charts`` are validated ChartSpecs the user can save/pin; ``insights`` are
    guardrailed summaries. Both are *proposals* — nothing is persisted by the agent.
    """

    answer: str
    tools_used: list[str]
    charts: list[ChartSpec] = []
    insights: list[str] = []


class AssistantService:
    """Runs the unified assistant agent and collects its proposed artifacts."""

    def __init__(
        self,
        agent: Agent,
        *,
        chart_sink: list[ChartSpec],
        insight_sink: list[str],
    ) -> None:
        self._agent = agent
        self._chart_sink = chart_sink
        self._insight_sink = insight_sink

    async def ask(self, ctx: TenantContext, message: str) -> AssistantResult:
        result = await self._agent.run(ctx, message)
        return AssistantResult(
            answer=result.answer,
            tools_used=result.tools_used,
            charts=list(self._chart_sink),
            insights=list(self._insight_sink),
        )


def _load_system(settings: Settings) -> str:
    """Load the assistant's system instruction from the versioned prompt dir (#13)."""
    try:
        return PromptLoader(settings.ai.prompt_template_dir).load("assistant", "v1")
    except Exception:
        logger.warning("assistant/v1 system prompt not found — using the inline default")
        return _DEFAULT_SYSTEM


def get_assistant_service(
    gateway: LLMGateway = Depends(get_llm_gateway),  # noqa: B008
    semantic: SemanticService = Depends(get_semantic_service),  # noqa: B008
    nl_sql: NLToSQLService = Depends(get_nl_to_sql_service),  # noqa: B008
    nl_chart: NLToChartService = Depends(get_nl_to_chart_service),  # noqa: B008
    insight: InsightService = Depends(get_insight_service),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AssistantService:
    """FastAPI dependency: assemble the unified assistant from the agent framework."""
    chart_sink: list[ChartSpec] = []
    insight_sink: list[str] = []
    skills = build_skills(semantic, nl_sql, nl_chart, insight, chart_sink, insight_sink)
    agent = Agent(gateway, SkillRegistry(skills), system=_load_system(settings))
    return AssistantService(agent, chart_sink=chart_sink, insight_sink=insight_sink)
