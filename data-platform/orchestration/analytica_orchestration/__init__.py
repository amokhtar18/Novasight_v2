"""Analytica orchestration: Dagster software-defined assets.

The data platform is modelled as assets (dbt-dagster-workflow skill): a raw dlt
ingestion asset feeds the dbt staging -> intermediate -> mart models, which are loaded
as assets via ``dagster-dbt``. Lineage is then automatic in the Dagster UI.
"""
