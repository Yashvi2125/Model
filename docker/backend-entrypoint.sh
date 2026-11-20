#!/bin/sh
# 1) wait for PostgreSQL  2) apply migrations (safe to repeat)  3) start the API.
# One worker on purpose: WebSocket rooms live in this process's memory.
set -e
python -m server.wait_for_db
alembic upgrade head
exec uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
