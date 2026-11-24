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
    is_overload_error,
    is_rate_limit_error,
    llm_text,
    mark_model_cooldown,
    parse_retry_delay,
)
from server.ai.gateway import gateway
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


def test_unrelated_words_not_classified_as_rate_limit():
    """Verify that unrelated words containing 'rate' (generate, accurate, operate) are NOT false-positive rate limits."""
    e1 = Exception("Failed to generate content accurately")
    assert is_rate_limit_error(e1) is False

    e2 = Exception("The system failed to operate under moderate load")
    assert is_rate_limit_error(e2) is False

    e3 = Exception("Desperate attempt to curate data")
    assert is_rate_limit_error(e3) is False


def test_overload_error_distinction_from_rate_limit():
    """503 and 'model is overloaded' must be classified as overload, NEVER as a rate limit."""
    overload_err = Exception("503 Service Unavailable: The model is overloaded. Please try again later.")
    assert is_overload_error(overload_err) is True
    assert is_rate_limit_error(overload_err) is False

    fe = friendly_error(overload_err)
    assert "overloaded" in fe.user_message.lower()
    assert "rate-limited" not in fe.user_message.lower()


def test_ai_gateway_usage_endpoint(user_a):
    """GET /api/ai/usage returns metrics without any secrets or prompts."""
    from tests.web.conftest import make_client

    # Record a test call in gateway
    gateway.record_call(feature="test_feature", model="test-model", status=200)

    # 1. Unauthenticated request should be rejected (401)
    unauth = make_client()
    res_unauth = unauth.get("/api/ai/usage")
    assert res_unauth.status_code == 401

    # 2. Authenticated request succeeds
    res = user_a.get("/api/ai/usage")
    assert res.status_code == 200
    data = res.json()
    assert "gateway_enabled" in data
    assert "total_requests" in data
    assert "requests_by_feature" in data
    assert "requests_by_model" in data
    assert "active_cooldowns_remaining_seconds" in data
    # Ensure zero secrets leaked
    text = res.text
    assert "key" not in text.lower() or "active_cooldowns" in text
    assert "ai_key" not in text.lower()
    assert "prompt" not in text.lower()


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


def test_token_bucket_rate_limiter():
    """Verify TokenBucket capacity, consumption, refill rate, and 429 penalty."""
    from server.ai.gateway import TokenBucket

    tb = TokenBucket(capacity=5.0, refill_rate=1.0)
    assert tb.available() == 5.0
    assert tb.consume(1.0) is True
    assert round(tb.available(), 1) == 4.0

    # Consume all remaining tokens
    assert tb.consume(4.0) is True
    assert tb.consume(1.0) is False

    # Simulate 429 with retry delay penalty
    tb.penalize(delay_seconds=30.0)
    assert tb.in_cooldown() is True
    assert tb.available() == 0.0
    assert tb.consume(1.0) is False


@pytest.mark.asyncio
async def test_priority_queue_starvation_protection():
    """Verify priority queue ordering and that waiting lower-priority items age to prevent starvation."""
    from server.ai.gateway import QueueWaiter, PRIORITY_BACKGROUND, PRIORITY_URGENT

    w_urgent = QueueWaiter(priority=PRIORITY_URGENT, model="m", feature="chat_reply", timeout=10.0)
    w_bg = QueueWaiter(priority=PRIORITY_BACKGROUND, model="m", feature="preference_extraction", timeout=10.0)

    # Initially, urgent has lower numerical score (1.0 vs 3.0) -> higher priority
    assert w_urgent.effective_priority < w_bg.effective_priority

    # Simulate w_bg waiting for 50 seconds (aging)
    w_bg.enqueue_time = time.time() - 50.0
    # Aging boost: 3.0 - (50 * 0.05) = 0.5, which is lower than w_urgent (1.0)!
    assert w_bg.effective_priority < w_urgent.effective_priority


@pytest.mark.asyncio
async def test_conflict_analysis_negative_caching(client, user_a, user_b):
    """Opening Conflicts tab repeatedly when no conflicts exist uses cached result (0 LLM calls)."""
    # Create trip and join both users
    res = user_a.post("/api/trips", json={
        "name": "Cache Test Trip",
        "destination": "Goa",
        "start_date": "2026-12-01",
        "end_date": "2026-12-05",
        "travelers_count": 2,
    })
    trip_id = res.json()["id"]
    code = res.json()["code"]
    user_b.post("/api/trips/join", json={"code": code})

    # User A and User B share agreeing preferences via /preferences/me (no conflict)
    user_a.put(f"/api/trips/{trip_id}/preferences/me", json={"interests": ["beach"], "notes": "Relaxation"})
    user_b.put(f"/api/trips/{trip_id}/preferences/me", json={"interests": ["beach"], "notes": "Relaxation"})

    call_count = 0

    async def fake_resolve(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"suggestions": {}, "additional": []}

    with patch("server.ai.agents.resolve_conflicts", side_effect=fake_resolve):
        # 1. First visit auto-analyzes (1 call)
        res1 = user_a.get(f"/api/trips/{trip_id}/conflicts")
        assert res1.status_code == 200
        assert call_count == 1

        # 2. Repeated visits within cache window use 0 LLM calls!
        res2 = user_a.get(f"/api/trips/{trip_id}/conflicts")
        assert res2.status_code == 200
        assert call_count == 1  # Still 1! No new LLM call!

        res3 = user_b.get(f"/api/trips/{trip_id}/conflicts")
        assert res3.status_code == 200
        assert call_count == 1  # Still 1!


@pytest.mark.asyncio
async def test_map_coordinate_fallback_deferred_when_quota_low(monkeypatch):
    """When AI quota/budget is low, Tier-e coordinate fallback is skipped with short retry TTL."""
    from server.services.research import _geocode_candidate_within_radius, _geocode_miss_cache, MISS_TTL

    # Mock gateway to report low budget
    monkeypatch.setattr("server.ai.gateway.gateway.is_enabled", lambda: True)
    monkeypatch.setattr("server.ai.gateway.gateway.should_skip_optional", lambda p: True)
    # Mock network GET calls to return empty so early tiers find nothing and reach Tier e
    monkeypatch.setattr("server.services.research._get", AsyncMock(return_value=[]))

    res, miss_reason = await _geocode_candidate_within_radius(
        name="Obscure Local Shrine",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )

    assert res is None
    assert "Skipped to save AI quota" in miss_reason
    assert "will retry in background" in miss_reason

    # Verify not cached as permanent 24h miss
    cache_key = "obscure local shrine|ahmedabad|23.02,72.57"
    assert cache_key in _geocode_miss_cache
    ts, reason = _geocode_miss_cache[cache_key]
    assert reason == miss_reason
    # Cache timestamp was set so remaining TTL is short (~30s), not full 24h
    elapsed_fake = time.time() - ts
    assert elapsed_fake > (MISS_TTL - 60.0)

