# syntax=docker/dockerfile:1.7
#
# Production image for the NovaSight Dagster code location (dlt ingestion + dbt).
#
# Build context MUST be the data-platform/ directory, because the image bundles BOTH
# the orchestration package AND the sibling dbt project — dbt_resource.py resolves the
# project at ``<orchestration>/../../dbt`` (parents[2]/dbt), so the on-disk layout
#   data-platform/orchestration/...   and   data-platform/dbt/...
# must be preserved. Build with:
#   docker build -f data-platform/orchestration/Dockerfile -t novasight-dagster data-platform
#
# Roles (same image, different process):
#   * webserver (default CMD): dagster-webserver -m novasight_orchestration.definitions
#   * daemon:                  dagster-daemon run   (schedules/sensors/run queue)
#
# Golden rule 1 — no build-time secrets, no environment-specific config baked in. The
# CLICKHOUSE__*, DBT_SCHEMA, and OPENMETADATA__* values are read from the environment
# at RUNTIME (the dbt CLI and the OpenMetadata SDK re-read them on every invocation).
# The placeholders below exist ONLY so ``dbt parse`` can render profiles.yml to build
# the static manifest at image-build time; dbt parse does not connect to any database,
# and these throwaway values never reach a running container.

# ---------------------------------------------------------------------------
# Stage 1 — builder: install the code location + build the dbt manifest.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# git is needed by `dbt deps` to fetch package dependencies (dbt_expectations).
RUN apt-get update \
 && apt-get install --no-install-recommends -y git \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /opt/novasight/data-platform

# Copy the orchestration package and the dbt project, preserving the sibling layout.
COPY orchestration ./orchestration
COPY dbt ./dbt

# Editable install keeps the package files at this path so dbt_resource.py's
# parents[2]/dbt resolution points at /opt/novasight/data-platform/dbt at runtime.
#
# The [catalog] extra (OpenMetadata ingestion SDK, used only by the catalog_metadata
# asset) is OPT-IN: the asset imports the SDK lazily, so the code location loads
# without it, and the SDK's dependency tree only resolves against pre-releases, which
# would otherwise fail every build. Enable it with `--build-arg INSTALL_CATALOG=true`.
ARG INSTALL_CATALOG=false
RUN uv venv "$VIRTUAL_ENV" \
 && uv pip install --no-cache -e ./orchestration \
 && if [ "$INSTALL_CATALOG" = "true" ]; then \
      uv pip install --no-cache --prerelease=allow -e "./orchestration[catalog]"; \
    fi

# Build the dbt package deps and the static manifest dagster-dbt loads at import.
# Placeholders satisfy the required env_var() lookups in profiles.yml during parse
# only; runtime supplies the real values.
RUN cd dbt \
 && CLICKHOUSE__HOST=build-time-placeholder \
    CLICKHOUSE__PASSWORD=build-time-placeholder \
    DBT_SCHEMA=build_time_placeholder \
    dbt deps --project-dir . \
 && CLICKHOUSE__HOST=build-time-placeholder \
    CLICKHOUSE__PASSWORD=build-time-placeholder \
    DBT_SCHEMA=build_time_placeholder \
    dbt parse --project-dir . --profiles-dir .

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim, non-root, carries the venv + the data-platform tree.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Image-internal conventions (not environment-specific) — all overridable:
    DAGSTER_HOME=/opt/dagster/home \
    DAGSTER_HOST=0.0.0.0 \
    DAGSTER_PORT=3000

# git remains useful at runtime for ad-hoc `dbt deps`; kept minimal otherwise.
RUN apt-get update \
 && apt-get install --no-install-recommends -y git \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system dagster \
 && useradd --system --gid dagster --home-dir /opt/dagster --shell /usr/sbin/nologin dagster \
 && mkdir -p /opt/dagster/home \
 # Empty instance config = Dagster defaults (the runnable baseline). Production
 # overrides storage/run-launcher by mounting its own dagster.yaml here.
 && : > /opt/dagster/home/dagster.yaml

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/novasight /opt/novasight

# The editable install referenced the builder path; the runtime path is identical
# (/opt/novasight/data-platform/...), so imports and parents[2]/dbt still resolve.
RUN chown -R dagster:dagster /opt/dagster /opt/novasight

USER dagster
WORKDIR /opt/novasight/data-platform

EXPOSE 3000

# Default role: the Dagster webserver, serving the code location. Bind address/port
# come from the environment. Run the daemon with `command: dagster-daemon run`.
CMD ["sh", "-c", "exec dagster-webserver -h \"$DAGSTER_HOST\" -p \"$DAGSTER_PORT\" -m novasight_orchestration.definitions"]
