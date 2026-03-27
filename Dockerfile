FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for document processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock* ./

# Install dependencies (no dev deps)
RUN uv sync --no-dev --no-editable

# Copy application code
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

# Create data directories
RUN mkdir -p data/uploads data/vectorstore

EXPOSE ${PORT:-8000}

# Run with uv to ensure correct virtual env — port from env
CMD ["sh", "-c", "uv run uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
