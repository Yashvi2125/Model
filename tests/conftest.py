"""Runs before any test module is imported, so settings never depend on a developer's local .env."""
import os

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")  # every AI call in tests is mocked or replayed
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-not-real")
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
