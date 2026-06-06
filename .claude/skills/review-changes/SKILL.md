---
name: review-changes
description: >
  Run the standard pre-done audit on the current diff against the five golden rules,
  security, and the definition of done. Invoke as /review-changes (optionally pass a
  path or range to focus on).
allowed-tools: Read, Grep, Glob, Bash
---

Audit the current changes for NovaSight. Focus area (optional): $ARGUMENTS

First gather the diff:
!`git diff --stat`
!`git diff`

Then delegate to the `reviewer` agent with this diff and produce its standard verdict
(`APPROVED` / `CHANGES REQUESTED`) plus a Critical → Important → Minor issue list with
file:line references.

Pay special attention to:
- Hardcoded configuration (literal hosts, ports, URLs, buckets, credentials, model ids,
  thresholds, paths) — every one is a defect.
- Tenant scoping derived from the authenticated context, never the request body.
- AI features: read-only, validated, semantic-layer-only, no cross-tenant leakage.
- Secrets in code/logs/fixtures.
- Tests present (incl. tenant-isolation), and `docs/` updated for new config/behavior.
