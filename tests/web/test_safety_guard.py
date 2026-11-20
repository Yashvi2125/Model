"""Tests for the database safety guard."""
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine import make_url

from tests.db_guard import (
    get_database_name,
    setup_test_database,
    verify_test_database_safety,
)


def test_get_database_name():
    assert get_database_name(make_url("postgresql+psycopg://u:p@localhost:5432/tripmate_test")) == "tripmate_test"
    assert get_database_name(make_url("sqlite:///C:/tmp/tripmate_test.db")) == "tripmate_test"
    assert get_database_name(make_url("sqlite:///:memory:")) == ":memory:_test"
    assert get_database_name(make_url("sqlite:///")) == ":memory:_test"


def test_guard_rejects_database_not_ending_with_test():
    # PostgreSQL live names
    with pytest.raises(RuntimeError, match="must end with '_test'"):
        verify_test_database_safety("postgresql+psycopg://tripmate:secret@localhost:5432/tripmate")

    with pytest.raises(RuntimeError, match="must end with '_test'"):
        verify_test_database_safety("postgresql://postgres:secret@db.supabase.com:5432/postgres")

    # SQLite live names
    with pytest.raises(RuntimeError, match="must end with '_test'"):
        verify_test_database_safety("sqlite:///./tripmate_dev.db")


def test_guard_rejects_matching_live_database():
    live_url = "postgresql+psycopg://tripmate:secret@localhost:5432/tripmate_test"
    test_url = "postgresql+psycopg://tripmate:secret@localhost:5432/tripmate_test"

    with pytest.raises(RuntimeError, match="matches live database"):
        verify_test_database_safety(test_url, live_url=live_url)


def test_guard_allows_safe_test_database():
    live_url = "postgresql+psycopg://tripmate:secret@localhost:5432/tripmate"
    test_url = "postgresql+psycopg://tripmate:secret@localhost:5432/tripmate_test"

    # Should succeed without error
    verify_test_database_safety(test_url, live_url=live_url)
    verify_test_database_safety("sqlite:///tmp/tripmate_test.db")
    verify_test_database_safety("sqlite:///:memory:")


def test_setup_test_database_auto_derives_and_guards():
    live_url = "postgresql+psycopg://tripmate:secret@db:5432/tripmate"

    with patch.dict("os.environ", {"DATABASE_URL": live_url}, clear=True), \
         patch("tests.db_guard._ORIGINAL_LIVE_DATABASE_URL", live_url), \
         patch("tests.db_guard.ensure_postgres_database_exists") as mock_ensure:
        test_url = setup_test_database(force_reconfigure=True)
        assert test_url.endswith("/tripmate_test")
        assert mock_ensure.called


def test_setup_test_database_aborts_if_explicit_test_url_is_unsafe():
    live_url = "postgresql+psycopg://tripmate:secret@db:5432/tripmate"

    # Attempting to set TEST_DATABASE_URL to live DB
    with patch.dict("os.environ", {"DATABASE_URL": live_url, "TEST_DATABASE_URL": live_url}, clear=True), \
         patch("tests.db_guard._ORIGINAL_LIVE_DATABASE_URL", live_url):
        with pytest.raises(RuntimeError, match="must end with '_test'"):
            setup_test_database(force_reconfigure=True)
