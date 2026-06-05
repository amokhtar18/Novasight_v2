"""Reporting subsystem — scheduled Excel reports (Phase 5.1).

Background only: reports are rendered and emailed by a Dramatiq worker, never on
the request path. The package is laid out as thin, testable seams:

* ``cron``    — a minimal 5-field cron matcher (per-report schedules).
* ``excel``   — render a query result to ``.xlsx`` bytes.
* ``email``   — the ``EmailSender`` protocol + an SMTP implementation.
* ``service`` — tenant-scoped orchestration: load → render → store → email.
* ``actors``  — Dramatiq actor glue (imports require a configured broker).
* ``schedule``— the periodiq dispatcher that enqueues due reports.
* ``worker``  — the process entrypoint that wires the broker and registers actors.
"""
from __future__ import annotations
