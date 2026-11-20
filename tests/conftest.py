"""Runs before any test module is imported, so settings never depend on a developer's local .env."""
import os

from tests.db_guard import setup_test_database

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")  # every AI call in tests is mocked or replayed
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-not-real")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"

# Configure safe test database before any server module is imported
setup_test_database()
