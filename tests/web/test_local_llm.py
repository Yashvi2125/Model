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
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from server.ai.agents import ExtractedPreferences, extract_preferences
from server.ai.local_llm import (
    _local_semaphore,
    classify_message_intent,
    extract_preferences_ollama,
    extract_preferences_with_fallback,
    generate_packing_list,
    normalize_extracted_json,
    summarize_chat_messages,
    swap_itinerary_day,
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


@pytest.mark.asyncio
async def test_classify_message_intent_success():
    fake_resp = {
        "message": {
            "content": '{"intent": "casual_chat"}'
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
        m_post.return_value = mock_resp
        intent, latency_ms = await classify_message_intent("Haha nice joke bro")
        assert intent == "casual_chat"
        assert latency_ms >= 0


@pytest.mark.asyncio
async def test_classify_message_intent_preference_update():
    fake_resp = {
        "message": {
            "content": '{"intent": "preference_update"}'
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
        m_post.return_value = mock_resp
        intent, latency_ms = await classify_message_intent("Goa for 4 days budget 20k")
        assert intent == "preference_update"
        assert latency_ms >= 0


@pytest.mark.asyncio
async def test_classify_message_intent_semaphore_busy_fail_open():
    await _local_semaphore.acquire()
    try:
        assert _local_semaphore.locked()
        intent, latency_ms = await classify_message_intent("Any message")
        # Must fail open cleanly to "uncertain"
        assert intent == "uncertain"
        assert latency_ms == 0
    finally:
        _local_semaphore.release()


@pytest.mark.asyncio
async def test_classify_message_intent_offline_fail_open():
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("connection refused")):
        intent, latency_ms = await classify_message_intent("Any message")
        assert intent == "uncertain"
        assert latency_ms >= 0


@pytest.mark.asyncio
async def test_classify_message_intent_timeout_fail_open():
    with patch("httpx.AsyncClient.post", side_effect=httpx.ReadTimeout("timed out")):
        intent, latency_ms = await classify_message_intent("Any message")
        assert intent == "uncertain"
        assert latency_ms >= 0


@pytest.mark.asyncio
async def test_classify_message_intent_invalid_json_fail_open():
    fake_resp = {
        "message": {
            "content": "Not JSON at all"
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
        m_post.return_value = mock_resp
        intent, latency_ms = await classify_message_intent("Any message")
        assert intent == "uncertain"
        assert latency_ms >= 0


@pytest.mark.asyncio
async def test_run_auto_extract_casual_chat_skips_extraction():
    from server.services.chat_ai import run_auto_extract

    mock_ctx = {
        "ctx": "Trip context",
        "sender": "Asha",
        "sender_id": 1,
        "text": "Haha see you tomorrow!",
        "travelers": 2,
    }

    with patch("server.services.chat_ai._load", return_value=mock_ctx):
        with patch("server.services.chat_ai.get_settings") as m_settings:
            m_settings.return_value.llm_provider = "qwen"
            with patch("server.ai.local_llm.classify_message_intent", new_callable=AsyncMock) as m_cls:
                m_cls.return_value = ("casual_chat", 25)
                with patch("server.ai.agents.extract_preferences", new_callable=AsyncMock) as m_extract:
                    await run_auto_extract(trip_id=1, message_id=10)
                    m_cls.assert_called_once_with("Haha see you tomorrow!")
                    # extract_preferences must NOT be called for casual_chat
                    m_extract.assert_not_called()


@pytest.mark.asyncio
async def test_run_auto_extract_preference_update_proceeds():
    from server.services.chat_ai import run_auto_extract

    mock_ctx = {
        "ctx": "Trip context",
        "sender": "Asha",
        "sender_id": 1,
        "text": "I want to visit Goa for 4 days with 20000 budget",
        "travelers": 2,
    }
    fake_pref = ExtractedPreferences(
        destination="Goa",
        trip_days=4,
        budget_per_person=20000,
        confidence=0.9,
    )

    with patch("server.services.chat_ai._load", return_value=mock_ctx):
        with patch("server.services.chat_ai.get_settings") as m_settings:
            m_settings.return_value.llm_provider = "qwen"
            with patch("server.ai.local_llm.classify_message_intent", new_callable=AsyncMock) as m_cls:
                m_cls.return_value = ("preference_update", 35)
                with patch("server.ai.agents.extract_preferences", new_callable=AsyncMock) as m_extract:
                    m_extract.return_value = fake_pref
                    with patch("server.services.chat_ai._save_suggestion", return_value=(1, {})):
                        with patch("server.services.chat_ai.publish"):
                            await run_auto_extract(trip_id=1, message_id=10)
                            m_cls.assert_called_once()
                            m_extract.assert_called_once_with("I want to visit Goa for 4 days with 20000 budget", "Asha", "Trip context")


@pytest.mark.asyncio
async def test_run_auto_extract_uncertain_fail_open_proceeds():
    from server.services.chat_ai import run_auto_extract

    mock_ctx = {
        "ctx": "Trip context",
        "sender": "Asha",
        "sender_id": 1,
        "text": "Maybe mountains?",
        "travelers": 2,
    }
    fake_pref = ExtractedPreferences(confidence=0.5)

    with patch("server.services.chat_ai._load", return_value=mock_ctx):
        with patch("server.services.chat_ai.get_settings") as m_settings:
            m_settings.return_value.llm_provider = "qwen"
            with patch("server.ai.local_llm.classify_message_intent", new_callable=AsyncMock) as m_cls:
                m_cls.return_value = ("uncertain", 0)
                with patch("server.ai.agents.extract_preferences", new_callable=AsyncMock) as m_extract:
                    m_extract.return_value = fake_pref
                    with patch("server.services.chat_ai._save_suggestion", return_value=(None, {})):
                        await run_auto_extract(trip_id=1, message_id=10)
                        m_cls.assert_called_once()
                        # Failed-open uncertain intent must proceed to extraction
                        m_extract.assert_called_once()


# ── Tests for Localized Single-Day Itinerary Swaps ────────────────────────────

@pytest.mark.asyncio
async def test_swap_itinerary_day_qwen_success():
    day_in = {
        "day": 2,
        "title": "Day 2: Beach & Heritage",
        "intro": "Relaxing day",
        "sections": [
            {"period": "morning", "content": "Visit Fort Aguada"},
            {"period": "afternoon", "content": "Lunch at beach shack"},
            {"period": "evening", "content": "Dinner at seafood restaurant"},
        ],
    }
    fake_qwen_resp = {
        "message": {
            "content": json.dumps({
                "day": 2,
                "title": "Day 2: Beach & Vegetarian Delights",
                "intro": "Relaxing vegetarian-friendly day",
                "sections": [
                    {"period": "morning", "content": "Visit Fort Aguada"},
                    {"period": "afternoon", "content": "Lunch at beach shack"},
                    {"period": "evening", "content": "Dinner at a budget vegetarian café"},
                ],
            })
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_qwen_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    with patch("server.ai.local_llm.get_settings") as m_settings:
        m_settings.return_value.llm_provider = "qwen"
        m_settings.return_value.local_llm_model = "qwen2.5:1.5b-instruct"
        m_settings.return_value.local_llm_base_url = "http://localhost:11434"
        m_settings.return_value.local_llm_timeout = 60
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
            m_post.return_value = mock_resp
            res, provider = await swap_itinerary_day(day_in, "replace dinner with vegetarian spot", "Goa 4 days")
            assert provider == "qwen"
            assert res["day"] == 2
            assert "vegetarian" in res["sections"][2]["content"].lower()


@pytest.mark.asyncio
async def test_swap_itinerary_day_semaphore_busy_gemini_fallback():
    day_in = {
        "day": 1,
        "title": "Day 1: Arrival",
        "sections": [{"period": "morning", "content": "Arrive and check in"}],
    }
    fake_gemini_resp = {
        "day": 1,
        "title": "Day 1: Arrival & Rest",
        "sections": [{"period": "morning", "content": "Arrive and check in"}],
    }
    await _local_semaphore.acquire()
    try:
        assert _local_semaphore.locked()
        with patch("server.ai.local_llm.get_settings") as m_settings:
            m_settings.return_value.llm_provider = "qwen"
            with patch("server.ai.local_llm._swap_itinerary_day_gemini", new_callable=AsyncMock) as m_gem:
                m_gem.return_value = (fake_gemini_resp, "gemini")
                res, provider = await swap_itinerary_day(day_in, "rest after flight", "Manali")
                assert provider == "gemini"
                assert res["day"] == 1
                m_gem.assert_called_once()
    finally:
        _local_semaphore.release()


@pytest.mark.asyncio
async def test_swap_itinerary_day_offline_gemini_fallback():
    day_in = {"day": 3, "title": "Day 3", "sections": []}
    fake_gemini_resp = {"day": 3, "title": "Day 3 Patched", "sections": []}
    with patch("server.ai.local_llm.get_settings") as m_settings:
        m_settings.return_value.llm_provider = "qwen"
        m_settings.return_value.local_llm_base_url = "http://127.0.0.1:59999"
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("connection refused")):
            with patch("server.ai.local_llm._swap_itinerary_day_gemini", new_callable=AsyncMock) as m_gem:
                m_gem.return_value = (fake_gemini_resp, "gemini")
                res, provider = await swap_itinerary_day(day_in, "add museum", "Jaipur")
                assert provider == "gemini"
                m_gem.assert_called_once()


# ── Tests for AI Packing Checklist Generator ──────────────────────────────────

@pytest.mark.asyncio
async def test_generate_packing_list_qwen_success():
    fake_qwen_resp = {
        "message": {
            "content": json.dumps({
                "items": [
                    {"text": "Sunscreen SPF 50+", "category": "toiletries"},
                    {"text": "Swimwear and beach towel", "category": "clothing"},
                    {"text": "Universal power adapter", "category": "electronics"},
                ]
            })
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_qwen_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    with patch("server.ai.local_llm.get_settings") as m_settings:
        m_settings.return_value.llm_provider = "qwen"
        m_settings.return_value.local_llm_model = "qwen2.5:1.5b-instruct"
        m_settings.return_value.local_llm_base_url = "http://localhost:11434"
        m_settings.return_value.local_llm_timeout = 60
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
            m_post.return_value = mock_resp
            items, provider = await generate_packing_list("Goa beaches 4 days")
            assert provider == "qwen"
            assert len(items) == 3
            assert items[0]["category"] == "toiletries"


@pytest.mark.asyncio
async def test_generate_packing_list_semaphore_busy_gemini_fallback():
    await _local_semaphore.acquire()
    try:
        assert _local_semaphore.locked()
        with patch("server.ai.local_llm.get_settings") as m_settings:
            m_settings.return_value.llm_provider = "qwen"
            with patch("server.ai.local_llm._generate_packing_list_gemini", new_callable=AsyncMock) as m_gem:
                m_gem.return_value = ([{"text": "Passport", "category": "documents"}], "gemini")
                items, provider = await generate_packing_list("Dubai trip")
                assert provider == "gemini"
                assert len(items) == 1
                m_gem.assert_called_once()
    finally:
        _local_semaphore.release()


@pytest.mark.asyncio
async def test_generate_packing_list_offline_gemini_fallback():
    with patch("server.ai.local_llm.get_settings") as m_settings:
        m_settings.return_value.llm_provider = "qwen"
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("connection refused")):
            with patch("server.ai.local_llm._generate_packing_list_gemini", new_callable=AsyncMock) as m_gem:
                m_gem.return_value = ([{"text": "Warm jacket", "category": "clothing"}], "gemini")
                items, provider = await generate_packing_list("Manali winter")
                assert provider == "gemini"
                m_gem.assert_called_once()


# ── Tests for Trip Chat Summarization ("Catch me up") ─────────────────────────

@pytest.mark.asyncio
async def test_summarize_chat_messages_qwen_success():
    fake_qwen_resp = {
        "message": {
            "content": json.dumps({
                "bullets": [
                    "Agreed on travelling to Goa for 4 days",
                    "Budget capped at 20,000 per person",
                    "Rohan preferred North Goa; Asha suggested South Goa for quiet beaches",
                    "Pending decision on renting scooters vs taxi",
                ]
            })
        }
    }
    mock_resp = httpx.Response(
        status_code=200,
        json=fake_qwen_resp,
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )
    with patch("server.ai.local_llm.get_settings") as m_settings:
        m_settings.return_value.llm_provider = "qwen"
        m_settings.return_value.local_llm_model = "qwen2.5:1.5b-instruct"
        m_settings.return_value.local_llm_base_url = "http://localhost:11434"
        m_settings.return_value.local_llm_timeout = 60
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as m_post:
            m_post.return_value = mock_resp
            bullets, provider = await summarize_chat_messages("Chat log...")
            assert provider == "qwen"
            assert len(bullets) == 4
            assert "Goa" in bullets[0]


@pytest.mark.asyncio
async def test_summarize_chat_messages_semaphore_busy_gemini_fallback():
    await _local_semaphore.acquire()
    try:
        assert _local_semaphore.locked()
        with patch("server.ai.local_llm.get_settings") as m_settings:
            m_settings.return_value.llm_provider = "qwen"
            with patch("server.ai.local_llm._summarize_chat_gemini", new_callable=AsyncMock) as m_gem:
                m_gem.return_value = (["Decision: Udaipur chosen"], "gemini")
                bullets, provider = await summarize_chat_messages("Chat log...")
                assert provider == "gemini"
                assert len(bullets) == 1
                m_gem.assert_called_once()
    finally:
        _local_semaphore.release()


@pytest.mark.asyncio
async def test_summarize_chat_messages_offline_gemini_fallback():
    with patch("server.ai.local_llm.get_settings") as m_settings:
        m_settings.return_value.llm_provider = "qwen"
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("connection refused")):
            with patch("server.ai.local_llm._summarize_chat_gemini", new_callable=AsyncMock) as m_gem:
                m_gem.return_value = (["Fallback summary"], "gemini")
                bullets, provider = await summarize_chat_messages("Chat log...")
                assert provider == "gemini"
                m_gem.assert_called_once()


