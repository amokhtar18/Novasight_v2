# syntax=docker/dockerfile:1.7
#
# Production image for the Analytica backend.
#
# ONE image, THREE runtime roles — they share the same code and dependencies and
# differ only by the process they launch (golden rule 4: thin slices, no duplication):
#   * API        (default CMD): uvicorn app.main:app
#   * worker:     dramatiq app.reporting.worker      (reporting 5.1 + KPI alerts 5.2)
#   * scheduler:  periodiq app.reporting.worker      (periodiq heartbeat)
#   * migrations: alembic upgrade head               (run as a job/initContainer)
#
# Golden rule 1 — NO build-time secrets and NO environment-specific config is baked
# in. Every host, credential, bucket, model id, and threshold is read from the
# environment at runtime via app.core.config.Settings. The only ENV defaults set
# here are image-internal conventions (paths inside the image, the in-container
# bind address/port), all overridable from the environment.

# ---------------------------------------------------------------------------
# Stage 1 — builder: resolve and install dependencies into an isolated venv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# uv resolves and installs far faster than pip and is the project's package manager.
RUN pip install --no-cache-dir uv

WORKDIR /src

# Install dependencies (and the project) into the venv. Copy the metadata and the
# package source needed to build the wheel; the resulting venv is the only thing
# carried forward to the runtime stage.
COPY pyproject.toml ./
COPY app ./app
RUN uv venv "$VIRTUAL_ENV" \
 && uv pip install --no-cache .

# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim, non-root, carries only the venv + source it runs.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    # Image-internal conventions (not environment-specific) — all overridable:
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    # Bundled, versioned prompt templates live alongside the code in this image.
    AI__PROMPT_TEMPLATE_DIR=/app/app/ai/prompts

# Non-root runtime user (golden rule: least privilege; never run as root).
RUN groupadd --system app \
 && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies from the builder.
COPY --from=builder /opt/venv /opt/venv

# Application source. PYTHONPATH=/app makes this tree authoritative for `import app`
# (so the bundled prompt templates and any other package data are used directly),
# and alembic.ini + alembic/ are present so the same image can run migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

USER app

EXPOSE 8000

# Default role: the API. The bind address/port come from the environment so the
# same image serves any deployment. Workers/scheduler/migrations override `command`.
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"$API_HOST\" --port \"$API_PORT\""]
