# syntax=docker/dockerfile:1.6

# ── Stage 1: builder — install deps with uv ──────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# Build-time deps for some Python wheels (e.g. lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, deterministic installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Cache layer — only copies dep files. uv.lock must exist (no glob); a
# missing lockfile would make --frozen silently no-op a fresh resolve.
COPY pyproject.toml uv.lock ./

# Install only runtime deps into a venv at /app/.venv
# Include the docling extra so PARSE_MODE=docling (the default) works on
# first PDF upload — without it the background ingest task throws
# ModuleNotFoundError silently.
RUN uv sync --no-dev --frozen --no-editable --extra docling

# ── Stage 2: runtime — slim, no uv, no build tooling ─────────
FROM python:3.13-slim

WORKDIR /app

# Make the venv binaries primary
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# App code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Pre-create the dirs we mount volumes onto so the app finds them
RUN mkdir -p /app/data/uploads /app/data/vectorstore /app/data/mindmaps /root/.cache/docling

EXPOSE 8000

# Run alembic migrations then uvicorn. exec replaces sh so signals reach uvicorn.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
