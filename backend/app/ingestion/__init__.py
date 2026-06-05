"""Ingestion package — raw source to Iceberg table.

Currently supports CSV-to-Iceberg via the ``CsvIcebergPipeline``.
"""
from __future__ import annotations

from app.ingestion.csv_iceberg import CsvIcebergPipeline, get_csv_iceberg_pipeline

__all__ = ["CsvIcebergPipeline", "get_csv_iceberg_pipeline"]
