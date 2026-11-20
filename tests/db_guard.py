"""Database safety guard for test execution.

Guarantees tests NEVER run against or drop tables in a live database.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import URL, make_url

log = logging.getLogger("tripmate.tests.guard")

_ORIGINAL_LIVE_DATABASE_URL: Optional[str] = os.environ.get("DATABASE_URL")
_INITIALIZED_TEST_URL: Optional[str] = None


def get_database_name(url: URL) -> str:
    """Extract clean logical database name from a SQLAlchemy URL."""
    db = url.database or ""
    if url.drivername.startswith("sqlite"):
        if not db or db == ":memory:":
            return ":memory:_test"
        return Path(db).stem
    return db


def verify_test_database_safety(
    test_url: str | URL,
    live_url: Optional[str | URL] = None,
) -> None:
    """Hard safety check: aborts if test DB does not end with '_test' or matches live DB."""
    test_u = make_url(test_url) if isinstance(test_url, str) else test_url
    test_name = get_database_name(test_u)

    if not test_name.endswith("_test"):
        raise RuntimeError(
            f"SAFETY GUARD VIOLATION: Test database '{test_name}' must end with '_test'. "
            "Refusing to run tests or drop tables on a non-test database."
        )

    if live_url:
        live_u = make_url(live_url) if isinstance(live_url, str) else live_url
        live_name = get_database_name(live_u)
        if live_name and test_name == live_name:
            raise RuntimeError(
                f"SAFETY GUARD VIOLATION: Test database '{test_name}' matches live database '{live_name}'. "
                "Refusing to run tests or drop tables on the live database."
            )


def ensure_postgres_database_exists(test_url: URL) -> None:
    """Connect to PostgreSQL maintenance DB and create the test database if it does not exist."""
    from sqlalchemy import create_engine, text

    db_name = test_url.database
    if not db_name:
        return

    # Connect to "postgres" maintenance database on the same host/credentials
    maint_url = test_url.set(database="postgres")
    try:
        maint_engine = create_engine(maint_url, isolation_level="AUTOCOMMIT")
        with maint_engine.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                log.info("Created PostgreSQL test database '%s'", db_name)
        maint_engine.dispose()
    except Exception as exc:
        # Fallback to "template1" if "postgres" database is inaccessible
        try:
            maint_url_fallback = test_url.set(database="template1")
            maint_engine_fallback = create_engine(maint_url_fallback, isolation_level="AUTOCOMMIT")
            with maint_engine_fallback.connect() as conn:
                exists = conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": db_name},
                )
                if not exists:
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    log.info("Created PostgreSQL test database '%s' via template1", db_name)
            maint_engine_fallback.dispose()
        except Exception as exc2:
            raise RuntimeError(
                f"Failed to ensure test database '{db_name}' exists: {exc2}"
            ) from exc2


def setup_test_database(force_reconfigure: bool = False) -> str:
    """Determine, guard, create and set the test database URL.

    Returns:
        The verified safe test database URL string.
    """
    global _ORIGINAL_LIVE_DATABASE_URL, _INITIALIZED_TEST_URL

    if _INITIALIZED_TEST_URL is not None and not force_reconfigure:
        return _INITIALIZED_TEST_URL

    raw_live_url = _ORIGINAL_LIVE_DATABASE_URL
    explicit_test_url = os.environ.get("TEST_DATABASE_URL")

    if explicit_test_url:
        target_url_str = explicit_test_url
    elif raw_live_url and ("postgresql" in raw_live_url or "postgres" in raw_live_url):
        # Auto-derive from live PostgreSQL URL
        live_u = make_url(raw_live_url)
        live_db = live_u.database or "tripmate"
        test_db = f"{live_db}_test" if not live_db.endswith("_test") else live_db
        target_u = live_u.set(database=test_db)
        target_url_str = target_u.render_as_string(hide_password=False)
    else:
        # SQLite fallback for local test runs without Postgres
        sqlite_path = os.path.join(tempfile.gettempdir(), "tripmate_test.db")
        target_url_str = f"sqlite:///{sqlite_path}"

    target_u = make_url(target_url_str)

    # 1. Hard safety guard
    verify_test_database_safety(target_u, live_url=raw_live_url)

    # 2. If Postgres, ensure the database exists
    if "postgresql" in target_u.drivername:
        ensure_postgres_database_exists(target_u)

    # 3. Export to environment
    os.environ["DATABASE_URL"] = target_url_str
    os.environ["TEST_DATABASE_URL"] = target_url_str
    _INITIALIZED_TEST_URL = target_url_str

    # 4. Invalidate lru_cache on get_settings if server.config was loaded
    try:
        from server.config import get_settings
        get_settings.cache_clear()
    except ImportError:
        pass

    return target_url_str
