#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}src"

echo "[start_prod] Running Alembic migrations..."
uv run --frozen --offline --no-dev alembic upgrade head

echo "[start_prod] Running idempotent MVP challenge seed..."
uv run --frozen --offline --no-dev python -m infrastructure.seed

echo "[start_prod] Starting Uvicorn on 0.0.0.0:${PORT:-8000}..."
exec uv run --frozen --offline --no-dev uvicorn api.app:app --host 0.0.0.0 --port "${PORT:-8000}"
