#!/bin/sh
set -e
# Apply schema migrations (Flyway equivalent), then serve.
alembic upgrade head
exec uvicorn --factory src.main:app_factory --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers
