"""Blocks until PostgreSQL accepts connections (used by the Docker entrypoint)."""
import sys
import time

from sqlalchemy import text

from server.db import engine

deadline = time.time() + 90
while True:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        print("Database is ready.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        if time.time() > deadline:
            print(f"Database never became ready: {type(exc).__name__}", file=sys.stderr)
            sys.exit(1)
        print("Waiting for database…")
        time.sleep(2)
