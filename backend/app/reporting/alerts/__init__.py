"""KPI alerts (Phase 5.2).

Background-only, on the same Dramatiq worker as reporting. Thin, testable seams:

* ``evaluator`` — pure: extract a KPI's value and decide breach vs threshold.
* ``channels`` — the ``AlertChannel`` protocol + email and webhook implementations.
* ``service``  — tenant-scoped evaluation with exactly-once breach de-duplication.
* ``actors``   — Dramatiq actor glue (imports require a configured broker).
* ``schedule`` — the periodiq dispatcher that enqueues due KPI evaluations.
"""
from __future__ import annotations
