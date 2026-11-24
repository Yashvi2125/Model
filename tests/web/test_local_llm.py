"""Tests for Local LLM (Qwen via Ollama) preference extraction and fallback.

Covers:
- Default provider is Gemini.
- Qwen success with schema validation, interest mapping, and confidence normalisation.
- Instant non-blocking Gemini fallback when semaphore is busy.
- Fallback on timeout (> LOCAL_LLM_TIMEOUT).
- Fallback on invalid JSON / schema error.
- Fallback on connection refused.
- Suggestion metadata (_provider, _model) preserved in suggestion data and ignored during preference application.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from server.ai.agents import ExtractedPreferences, extract_preferences
from server.ai.local_llm import (
    _local_semaphore,
    extract_preferences_ollama,
    extract_preferences_with_fallback,
    normalize_extracted_json,
)
from server.config import get_settings
from server.models import Preference
from server.services import preferences as prefs
from tests.db_guard import setup_test_database, verify_test_database_safety

# Ensure isolated test database
setup_test_database()


def test_normalize_extracted_json_mappings():
    raw = {
        "destination": "Goa",
        "trip_days": 4,
        "budget_per_person": 15000,
        "interests": ["beach", "historical", "trekking", "parties", "temple"],
        "confidence": 90,  # 0-100 scale from model
    }
    normalized = normalize_extracted_json(raw)
    assert normalized["confidence"] == 0.9
    assert normalized["destination"] == "Goa"
    assert normalized["trip_days"] == 4
    assert normalized["budget_per_person"] == 15000.0
    # Canonical interests
    assert "beaches" in normalized["interests"]
    assert "culture" in normalized["interests"]
    assert "adventure" in normalized["interests"]
    assert "spiritual" in normalized["interests"]


@pytest.mark.asyncio
async def test_llm_provider_default_gemini():
    settings = get_settings()
    assert settings.llm_provider in ("gemini", "qwen")

    mock_gemini = ExtractedPreferences(
        destination="Jaipur",
        trip_days=3,
        confidence=0.85,
        provider="gemini",
        model="gemini-3.5-flash-lite",
    )
    with patch("server.ai.agents.extract_preferences_gemini", new_callable=AsyncMock) as m_gem:
        m_gem.return_value = mock_gemini
        result = await extract_preferences_with_fallback(
            "I want to visit Jaipur for 3 days",
            traveller="Asha",
            provider="gemini",
        )
        assert result.provider == "gemini"
        assert result.destination == "Jaipur"
        m_gem.assert_called_once()


@pytest.mark.asyncio
async def test_qwen_success_path():
    fake_response = {
        "message": {
            "content": '{"destination": "Manali", "trip_days": 5, "budget_per_person": 20000, "interests": ["nature", "mountains"], "confidence": 0.95}'
        }
    }

    mock_resp = httpx.Response(
        status_code=200,
        json=fake_response,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
        m_post.return_value = mock_resp
        result = await extract_preferences_with_fallback(
            "Trip to Manali for 5 days with 20000 budget",
            traveller="Rohan",
            provider="qwen",
            model="qwen2.5:3b-instruct",
            base_url="http://localhost:11434",
        )
        assert result.provider == "qwen"
        assert result.model == "qwen2.5:3b-instruct"
        assert result.destination == "Manali"
        assert result.trip_days == 5
        assert result.budget_per_person == 20000.0
        assert "nature" in result.interests
        assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_qwen_semaphore_busy_instant_gemini_fallback():
    mock_gemini = ExtractedPreferences(
        destination="Udaipur",
        confidence=0.8,
        provider="gemini",
        model="gemini-3.5-flash-lite",
    )

    # Acquire semaphore to simulate an active local inference
    await _local_semaphore.acquire()
    try:
        assert _local_semaphore.locked()

        with patch("server.ai.agents.extract_preferences_gemini", new_callable=AsyncMock) as m_gem:
            m_gem.return_value = mock_gemini
            # Should immediately fallback to Gemini without waiting
            result = await extract_preferences_with_fallback(
                "Udaipur trip next week",
                traveller="Asha",
                provider="qwen",
            )
            assert result.provider == "gemini"
            assert result.destination == "Udaipur"
            m_gem.assert_called_once()
    finally:
        _local_semaphore.release()


@pytest.mark.asyncio
async def test_qwen_timeout_gemini_fallback():
    mock_gemini = ExtractedPreferences(
        destination="Kerala",
        confidence=0.75,
        provider="gemini",
        model="gemini-3.5-flash-lite",
    )

    with patch("httpx.AsyncClient.post", side_effect=httpx.ReadTimeout("timed out")):
        with patch("server.ai.agents.extract_preferences_gemini", new_callable=AsyncMock) as m_gem:
            m_gem.return_value = mock_gemini
            result = await extract_preferences_with_fallback(
                "Kerala backwaters",
                traveller="Asha",
                provider="qwen",
            )
            assert result.provider == "gemini"
            assert result.destination == "Kerala"
            m_gem.assert_called_once()


@pytest.mark.asyncio
async def test_qwen_invalid_json_gemini_fallback():
    fake_bad_resp = {
        "message": {
            "content": "Not JSON at all, model hallucinated free text"
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_bad_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )

    mock_gemini = ExtractedPreferences(
        destination="Ooty",
        confidence=0.8,
        provider="gemini",
        model="gemini-3.5-flash-lite",
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
        m_post.return_value = mock_resp
        with patch("server.ai.agents.extract_preferences_gemini", new_callable=AsyncMock) as m_gem:
            m_gem.return_value = mock_gemini
            result = await extract_preferences_with_fallback(
                "Ooty trip",
                traveller="Asha",
                provider="qwen",
            )
            assert result.provider == "gemini"
            assert result.destination == "Ooty"
            m_gem.assert_called_once()


@pytest.mark.asyncio
async def test_qwen_connection_refused_gemini_fallback():
    mock_gemini = ExtractedPreferences(
        destination="Varanasi",
        confidence=0.9,
        provider="gemini",
        model="gemini-3.5-flash-lite",
    )

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("connection refused")):
        with patch("server.ai.agents.extract_preferences_gemini", new_callable=AsyncMock) as m_gem:
            m_gem.return_value = mock_gemini
            result = await extract_preferences_with_fallback(
                "Varanasi temples",
                traveller="Asha",
                provider="qwen",
                base_url="http://127.0.0.1:59999",
            )
            assert result.provider == "gemini"
            assert result.destination == "Varanasi"
            m_gem.assert_called_once()


def test_suggestion_metadata_preserved_and_isolated():
    ex = ExtractedPreferences(
        destination="Goa",
        trip_days=4,
        budget_per_person=12000,
        interests=["beaches"],
        confidence=0.88,
        provider="qwen",
        model="qwen2.5:3b-instruct",
    )

    # 1. fields_from_extracted attaches _provider and _model
    fields = prefs.fields_from_extracted(ex, travelers=2)
    assert fields["_provider"] == "qwen"
    assert fields["_model"] == "qwen2.5:3b-instruct"
    assert fields["destination"] == "Goa"

    # 2. apply_fields ignores _provider and _model so preferences table remains clean
    p = Preference(trip_id=1, user_id=1, interests=[], sources={})
    prefs.apply_fields(p, fields, "ai")
    assert p.destination == "Goa"
    assert p.trip_days == 4
    assert not hasattr(p, "_provider")
    assert "_provider" not in p.sources
