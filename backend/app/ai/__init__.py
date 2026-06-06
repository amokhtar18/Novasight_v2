"""AI layer for NovaSight.

Provides:
- semantic/  — tenant-scoped Cube semantic-layer client (Phase 4, Task 4.1)
- gateway/   — provider-agnostic LLM gateway (Phase 4, Task 4.2)

Upcoming sub-packages (later phases):
- nl/        — NL → SQL / NL → chart pipeline
- insights/  — insight generation from result sets

All AI features follow the four-stage pattern in ``.claude/skills/nl-to-sql-grounding``:
Ground → Generate → Validate → Execute/Return.
"""
