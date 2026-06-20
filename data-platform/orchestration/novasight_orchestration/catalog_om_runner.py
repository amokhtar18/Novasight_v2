"""Standalone OpenMetadata-SDK runner — executed in the isolated ``/opt/om-venv``.

The OM ingestion SDK cannot share a venv with the dagster/dbt stack (its dependency
tree collides with ``dbt-clickhouse`` on ``dbt-adapters``). So the SDK lives in a
dedicated venv and the catalog code (``catalog.py`` / ``catalog_lineage.py``) shells out
to *this* file with that venv's Python, handing it a JSON payload over a temp file:

    /opt/om-venv/bin/python catalog_om_runner.py <mode> <payload.json>

``mode`` is ``workflow`` (run one OM ingestion workflow from its config dict) or
``lineage`` (post a batch of lineage edges). This module imports ONLY the standard
library and the OM SDK — never ``novasight_orchestration`` — so it runs in a venv that
has the SDK but not the rest of the code location.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def _run_workflow(config: dict[str, Any]) -> None:
    """Execute one OpenMetadata ingestion workflow given its config dict."""
    from metadata.workflow.metadata import MetadataWorkflow  # type: ignore[import-not-found]

    workflow = MetadataWorkflow.create(config)
    workflow.execute()
    workflow.raise_from_status()
    workflow.print_status()
    workflow.stop()


def _fqn(ref: dict[str, str]) -> str:
    """``service.database.schema.table`` — the OpenMetadata fully-qualified name."""
    return f"{ref['service']}.{ref['database']}.{ref['schema']}.{ref['table']}"


def _ensure_table_entity(metadata: Any, ref: dict[str, str]) -> Any:
    """Resolve a table entity by FQN, creating a minimal logical one if it is absent.

    Source objects and Cube cubes are not ingested by a scan, so their endpoints may
    not exist yet. We upsert the whole hierarchy (CustomDatabase service → database →
    schema → table) idempotently so the lineage edge has an endpoint. ClickHouse tables
    already exist from their scan and resolve directly — we never clobber them, because
    we only create when ``get_by_name`` finds nothing.
    """
    from metadata.generated.schema.api.data.createDatabase import (  # type: ignore[import-not-found]
        CreateDatabaseRequest,
    )
    from metadata.generated.schema.api.data.createDatabaseSchema import (  # type: ignore[import-not-found]
        CreateDatabaseSchemaRequest,
    )
    from metadata.generated.schema.api.data.createTable import (  # type: ignore[import-not-found]
        CreateTableRequest,
    )
    from metadata.generated.schema.api.services.createDatabaseService import (  # type: ignore[import-not-found]
        CreateDatabaseServiceRequest,
    )
    from metadata.generated.schema.entity.data.table import (  # type: ignore[import-not-found]
        Column,
        DataType,
        Table,
    )
    from metadata.generated.schema.entity.services.databaseService import (  # type: ignore[import-not-found]
        DatabaseServiceType,
    )

    existing = metadata.get_by_name(entity=Table, fqn=_fqn(ref))
    if existing is not None:
        return existing
    service, database, schema, table = ref["service"], ref["database"], ref["schema"], ref["table"]
    # Idempotent create_or_update of each level (logical CustomDatabase service).
    metadata.create_or_update(
        CreateDatabaseServiceRequest(name=service, serviceType=DatabaseServiceType.CustomDatabase)
    )
    metadata.create_or_update(CreateDatabaseRequest(name=database, service=service))
    metadata.create_or_update(
        CreateDatabaseSchemaRequest(name=schema, database=f"{service}.{database}")
    )
    return metadata.create_or_update(
        CreateTableRequest(
            name=table,
            columns=[Column(name="_", dataType=DataType.UNKNOWN)],
            databaseSchema=f"{service}.{database}.{schema}",
        )
    )


def _emit_lineage(payload: dict[str, Any]) -> None:
    """POST each ``{from, to}`` edge to OpenMetadata using the server creds in payload."""
    from metadata.generated.schema.api.lineage.addLineage import (  # type: ignore[import-not-found]
        AddLineageRequest,
    )
    from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (  # type: ignore[import-not-found]
        OpenMetadataConnection,
    )
    from metadata.generated.schema.security.client.openMetadataJWTClientConfig import (  # type: ignore[import-not-found]
        OpenMetadataJWTClientConfig,
    )
    from metadata.generated.schema.type.entityLineage import (  # type: ignore[import-not-found]
        EntitiesEdge,
    )
    from metadata.generated.schema.type.entityReference import (  # type: ignore[import-not-found]
        EntityReference,
    )
    from metadata.ingestion.ometa.ometa_api import OpenMetadata  # type: ignore[import-not-found]

    server = payload["server"]
    metadata = OpenMetadata(
        OpenMetadataConnection(
            hostPort=server["host_port"],
            authProvider="openmetadata",
            securityConfig=OpenMetadataJWTClientConfig(jwtToken=server["jwt_token"]),
        )
    )
    for edge in payload["edges"]:
        upstream = _ensure_table_entity(metadata, edge["from"])
        downstream = _ensure_table_entity(metadata, edge["to"])
        metadata.add_lineage(
            AddLineageRequest(
                edge=EntitiesEdge(
                    fromEntity=EntityReference(id=upstream.id, type="table"),
                    toEntity=EntityReference(id=downstream.id, type="table"),
                )
            )
        )


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: catalog_om_runner.py <workflow|lineage> <payload.json>", file=sys.stderr)
        return 2
    mode, path = argv[1], argv[2]
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if mode == "workflow":
        _run_workflow(payload)
    elif mode == "lineage":
        _emit_lineage(payload)
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
