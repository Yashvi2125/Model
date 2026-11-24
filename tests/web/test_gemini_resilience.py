"""
Tests for Gemini rate limit resilience, model chain fallback, retryDelay parsing,
concurrency limit, and friendly error formatting with mocks (no real Gemini quota spent).
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config.settings as ai_settings
from models.gemini_model import create_gemini_model_client, get_gemini_semaphore
from server.ai.client import (
    AIError,
    format_delay,
    friendly_error,
    is_daily_quota_error,
    is_model_available,
    is_rate_limit_error,
    llm_text,
    mark_model_cooldown,
    parse_retry_delay,
)
from server.ai.workflow import PlanResult, generate_plan


def test_autogen_client_builds_for_every_model_in_chain():
    """Requirement 2: Ensure AutoGen client can be built for each model in GEMINI_MODEL_CHAIN."""
    chain = ai_settings.GEMINI_MODEL_CHAIN
    assert len(chain) >= 2
    assert "gemini-3.5-flash-lite" in chain
    assert "gemini-3.1-flash-lite" in chain
    assert "gemini-3.8-flash" not in chain

    for model_name in chain:
        client = create_gemini_model_client(model=model_name, api_key="dummy_key_for_testing")
        assert client is not None
        # AutoGen client stores model in _create_args or _resolved_model
        resolved = getattr(client, "_resolved_model", None) or client._create_args.get("model")
        assert resolved == model_name


def test_gemini_semaphore_concurrency_limit():
    """Requirement 3: Concurrency limit (2) applies per individual Gemini request."""
    sem = get_gemini_semaphore()
    assert isinstance(sem, asyncio.Semaphore)
    # Default value is 2
    assert sem._value <= 2


def test_parse_retry_delay():
    """Test extracting retryDelay across different error message shapes."""
    e1 = Exception("429 ResourceExhausted: Please wait. {'retryDelay': '15.5s'}")
    assert parse_retry_delay(e1) == 15.5

    e2 = Exception("Rate limit exceeded. retryDelay: \"45s\"")
    assert parse_retry_delay(e2) == 45.0

    e3 = Exception("429 Too Many Requests: retry_after: 30")
    assert parse_retry_delay(e3) == 30.0

    e4 = Exception("Standard error with no delay")
    assert parse_retry_delay(e4) is None


def test_daily_vs_per_minute_quota_detection():
    """Requirement 4: Distinguish daily quota from per-minute limit."""
    per_minute_err = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for Generate Content API requests per minute. retryDelay: '12s'")
    assert is_rate_limit_error(per_minute_err) is True
    assert is_daily_quota_error(per_minute_err) is False

    daily_err = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'Generate Content API requests per day'. retryDelay: '43200s'")
    assert is_rate_limit_error(daily_err) is True
    assert is_daily_quota_error(daily_err) is True


def test_friendly_error_daily_quota_message():
    """Requirement 4: Never say 'update your Gemini key in settings', mention reset."""
    daily_err = Exception("429 RESOURCE_EXHAUSTED: Generate Content API requests per day exhausted. retryDelay: '3600s'")
    fe = friendly_error(daily_err)
    msg = fe.user_message
    assert "update your gemini key" not in msg.lower()
    assert "daily free ai quota is used up" in msg.lower()
    assert "reset later" in msg.lower()
    assert "1 hour" in msg or "60 minute" in msg


def test_friendly_error_per_minute_message():
    """Requirement 1(f): Format per-minute rate-limited message with wait time."""
    pm_err = Exception("429 RESOURCE_EXHAUSTED: Requests per minute exceeded. retryDelay: '20s'")
    fe = friendly_error(pm_err)
    msg = fe.user_message
    assert "rate-limited" in msg.lower()
    assert "20s" in msg


def test_model_cooldown_tracking():
    """Requirement 1(b): Model cooldown marks model unavailable until expired."""
    test_model = "test-model-cooldown-check"
    assert is_model_available(test_model) is True

    exc = Exception("429 ResourceExhausted: retryDelay: '30s'")
    mark_model_cooldown(test_model, exc)
    assert is_model_available(test_model) is False


@pytest.mark.asyncio
async def test_llm_text_fallback_chain_on_429(monkeypatch):
    """Requirement 1(b): llm_text tries primary model, hits 429, falls back to second model in chain."""
    chain = ["model-a", "model-b"]
    monkeypatch.setattr(ai_settings, "GEMINI_MODEL_CHAIN", chain)
    monkeypatch.setattr(ai_settings, "GEMINI_API_KEY", "dummy_key")

    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "model-a":
                raise Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for model-a. retryDelay: '15s'")
            resp = MagicMock()
            resp.text = "Answer from model-b"
            return resp

    fake_client = MagicMock()
    fake_client.models = FakeModels()

    monkeypatch.setattr("server.ai.client._get_genai_client", lambda: fake_client)

    result = await llm_text(system="sys", user="user")
    assert result == "Answer from model-b"
    assert calls == ["model-a", "model-b"]
    # model-a should now be in cooldown
    assert is_model_available("model-a") is False
    assert is_model_available("model-b") is True


@pytest.mark.asyncio
async def test_workflow_incomplete_plan_raises_failure(monkeypatch):
    """Requirement 5: An itinerary run that ends without a completed plan raises AIError and is not saved."""
    from autogen_agentchat.messages import TextMessage

    fake_team = MagicMock()

    class FakeResult:
        messages = [
            TextMessage(content="User prompt", source="User"),
            TextMessage(content="", source="Travel_Planner"),
        ]
        stop_reason = "max_turns"

    fake_team.run = AsyncMock(return_value=FakeResult())

    monkeypatch.setattr(ai_settings, "GEMINI_API_KEY", "dummy_key")
    monkeypatch.setattr("server.ai.client._configured", lambda x: True)
    monkeypatch.setattr("server.ai.workflow._live_research", AsyncMock(return_value=("", False)))

    with patch("teams.travel_team.create_travel_team", return_value=fake_team):
        with pytest.raises(AIError) as exc_info:
            await generate_plan("Plan a trip", "research query")
        assert "complete itinerary" in str(exc_info.value).lower()
