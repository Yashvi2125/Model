"""Local LLM client (Ollama / Qwen 2.5) for fast, on-device preference extraction.

Key features:
- Short, focused extraction prompt for minimal CPU prompt-evaluation latency.
- Non-blocking concurrency semaphore (asyncio.Semaphore(1)): only 1 local inference runs at a time.
- Immediate zero-wait fallback to Gemini (AIGateway) if the semaphore is busy (locked).
- Structured JSON format enforced via Ollama schema parameter and mapped to ExtractedPreferences.
- Automatic fallback to Gemini on timeout (LOCAL_LLM_TIMEOUT), connection error, or invalid JSON.
- Structured logging: provider=qwen model=... latency_ms=... or provider=gemini fallback_reason=...
- Gateway call metering for /api/ai/usage.
"""
import asyncio
from datetime import date
import json
import logging
import re
import time
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from server.ai.gateway import gateway
from server.config import get_settings
from server.schemas import INTEREST_IDS

log = logging.getLogger("tripmate.ai.local_llm")

# Global non-blocking semaphore: only 1 local LLM call at a time to prevent CPU overload
_local_semaphore = asyncio.Semaphore(1)


class LocalLLMBusyError(Exception):
    """Raised when the local LLM semaphore is already held by another request."""
    pass


LOCAL_INTENT_SYSTEM = (
    "Classify the traveller's chat message into exactly one intent:\n"
    "- casual_chat: greetings, banter, jokes, social small talk, unrelated chat\n"
    "- preference_update: destinations, dates, budgets, activities, hotels, food, travel constraints\n"
    "- ai_question: asking questions to the AI or asking for recommendations\n"
    "- itinerary_approval: agreeing or approving a plan, dates, or schedule\n"
    "Return JSON only with key 'intent'."
)

ALLOWED_INTENTS = {"casual_chat", "preference_update", "ai_question", "itinerary_approval"}

LOCAL_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "casual_chat",
                "preference_update",
                "ai_question",
                "itinerary_approval",
            ],
        }
    },
    "required": ["intent"],
}


async def classify_message_intent(
    text: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 15.0,
) -> tuple[str, int]:
    """Lightweight intent classification using local Ollama (qwen2.5:1.5b-instruct).

    Returns (intent_string, latency_ms).
    Fails open cleanly returning ("uncertain", latency_ms) on:
    - Semaphore locked / busy
    - Connection refused or network error
    - Timeout
    - Invalid JSON or unexpected format
    """
    settings = get_settings()
    model_name = model or "qwen2.5:1.5b-instruct"
    ollama_url = base_url or settings.local_llm_base_url

    # Check semaphore non-blocking: if locked, fail open immediately
    if _local_semaphore.locked():
        log.info("Local LLM semaphore is busy; failing open with intent='uncertain'")
        return "uncertain", 0

    try:
        await asyncio.wait_for(_local_semaphore.acquire(), timeout=0.001)
    except (asyncio.TimeoutError, Exception):
        log.info("Failed to acquire local LLM slot immediately; failing open with intent='uncertain'")
        return "uncertain", 0

    t0 = time.time()
    try:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": LOCAL_INTENT_SYSTEM},
                {"role": "user", "content": f"Message: \"\"\"{text}\"\"\""},
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 48,
            },
            "format": LOCAL_INTENT_SCHEMA,
        }

        api_endpoint = f"{ollama_url.rstrip('/')}/api/chat"
        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.post(api_endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency_ms = int((time.time() - t0) * 1000)
        raw_content = data.get("message", {}).get("content", "{}")
        parsed = json.loads(raw_content)
        intent = parsed.get("intent", "").strip().lower()

        if intent in ALLOWED_INTENTS:
            return intent, latency_ms
        log.warning("Unrecognized intent '%s' from local LLM; failing open with 'uncertain'", intent)
        return "uncertain", latency_ms

    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log.info("Ollama offline/connection error for intent classification (%s); failing open with 'uncertain'", exc)
        return "uncertain", latency_ms
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        latency_ms = int((time.time() - t0) * 1000)
        log.info("Ollama intent classification timed out (%s); failing open with 'uncertain'", exc)
        return "uncertain", latency_ms
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.time() - t0) * 1000)
        log.info("Ollama intent classification encountered error (%s); failing open with 'uncertain'", exc)
        return "uncertain", latency_ms
    finally:
        _local_semaphore.release()


LOCAL_PREF_SYSTEM = (
    "Extract explicit trip preferences for the traveller from their chat message.\n"
    "Return JSON only matching the schema. If small talk or no preferences mentioned, return confidence 0.\n"
    f"Allowed interests: {', '.join(INTEREST_IDS)}.\n"
    "Amounts must be numbers without commas. Confidence is a float between 0.0 and 1.0."
)

LOCAL_PREF_SCHEMA = {
    "type": "object",
    "properties": {
        "destination": {"type": "string"},
        "trip_days": {"type": "integer"},
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
        "budget_per_person": {"type": "number"},
        "budget_total": {"type": "number"},
        "currency": {"type": "string"},
        "interests": {
            "type": "array",
            "items": {"type": "string"},
        },
        "accommodation": {"type": "string"},
        "dietary": {"type": "string"},
        "restrictions": {"type": "string"},
        "notes": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["confidence"],
}

# Synonym mapping to canonical INTEREST_IDS
INTEREST_SYNONYMS = {
    "beach": "beaches",
    "beaches": "beaches",
    "coastal": "beaches",
    "sea": "beaches",
    "culture": "culture",
    "cultural": "culture",
    "heritage": "culture",
    "history": "culture",
    "historical": "culture",
    "museum": "culture",
    "museums": "culture",
    "temple": "spiritual",
    "temples": "spiritual",
    "spiritual": "spiritual",
    "religious": "spiritual",
    "adventure": "adventure",
    "trek": "adventure",
    "trekking": "adventure",
    "hiking": "adventure",
    "sports": "adventure",
    "nature": "nature",
    "mountains": "nature",
    "wildlife": "nature",
    "safari": "nature",
    "food": "food",
    "foodie": "food",
    "dining": "food",
    "cuisine": "food",
    "shopping": "shopping",
    "markets": "shopping",
    "relaxation": "relaxation",
    "relax": "relaxation",
    "relaxing": "relaxation",
    "spa": "relaxation",
    "nightlife": "nightlife",
    "party": "nightlife",
    "clubs": "nightlife",
    "pub": "nightlife",
}


def normalize_extracted_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Clean and coerce raw Ollama JSON to match ExtractedPreferences fields safely."""
    out = dict(raw)

    # 1. Normalize confidence to 0.0 - 1.0
    conf = out.get("confidence")
    if conf is not None:
        try:
            val = float(conf)
            if val > 1.0:
                val = val / 100.0 if val <= 100.0 else 1.0
            out["confidence"] = max(0.0, min(1.0, val))
        except (ValueError, TypeError):
            out["confidence"] = 0.5
    else:
        out["confidence"] = 0.5

    # 2. Normalize interests
    interests_raw = out.get("interests")
    cleaned_interests: list[str] = []
    if isinstance(interests_raw, list):
        for item in interests_raw:
            k = str(item).strip().lower()
            canonical = INTEREST_SYNONYMS.get(k)
            if canonical and canonical in INTEREST_IDS:
                if canonical not in cleaned_interests:
                    cleaned_interests.append(canonical)
            elif k in INTEREST_IDS:
                if k not in cleaned_interests:
                    cleaned_interests.append(k)
    out["interests"] = cleaned_interests

    # 3. Numeric cleanup (budget_per_person, budget_total, trip_days)
    for num_key in ("budget_per_person", "budget_total"):
        val = out.get(num_key)
        if val is not None:
            try:
                out[num_key] = max(0.0, float(val))
            except (ValueError, TypeError):
                out[num_key] = None

    days = out.get("trip_days")
    if days is not None:
        try:
            d_val = int(days)
            out["trip_days"] = max(1, min(60, d_val))
        except (ValueError, TypeError):
            out["trip_days"] = None

    # 4. Dates: validate ISO YYYY-MM-DD; if invalid string like "December", move to notes
    for date_key in ("start_date", "end_date"):
        dt_val = out.get(date_key)
        if dt_val:
            dt_str = str(dt_val).strip()
            try:
                date.fromisoformat(dt_str)
                out[date_key] = dt_str
            except ValueError:
                # Invalid date format, preserve in notes if not already there
                out[date_key] = None
                existing_notes = out.get("notes") or ""
                if dt_str not in existing_notes:
                    out["notes"] = f"{existing_notes} ({date_key}: {dt_str})".strip()

    # 5. Strings strip
    for str_key in ("destination", "currency", "accommodation", "dietary", "restrictions", "notes"):
        s_val = out.get(str_key)
        if s_val:
            cleaned_s = str(s_val).strip()
            out[str_key] = cleaned_s if cleaned_s and cleaned_s.lower() != "null" else None

    return out


async def extract_preferences_ollama(
    text: str,
    traveller: str,
    trip_ctx: str = "",
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Any:
    """Extract trip preferences using local Ollama (Qwen 2.5).

    Raises LocalLLMBusyError immediately if another local inference is in progress.
    """
    settings = get_settings()
    model_name = model or settings.local_llm_model
    ollama_url = base_url or settings.local_llm_base_url
    timeout_sec = timeout or settings.local_llm_timeout

    # Non-blocking semaphore check: do not queue or block if already locked
    if _local_semaphore.locked():
        raise LocalLLMBusyError("Local LLM semaphore is busy; skipping Ollama")

    try:
        await asyncio.wait_for(_local_semaphore.acquire(), timeout=0.001)
    except (asyncio.TimeoutError, Exception) as exc:
        raise LocalLLMBusyError("Failed to acquire local LLM slot immediately") from exc

    try:
        user_prompt = f"Traveller: {traveller}\nMessage: \"\"\"{text}\"\"\""
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": LOCAL_PREF_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 256,
            },
            "format": LOCAL_PREF_SCHEMA,
        }

        api_endpoint = f"{ollama_url.rstrip('/')}/api/chat"
        t0 = time.time()
        async with httpx.AsyncClient(timeout=float(timeout_sec)) as client:
            resp = await client.post(api_endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency_ms = int((time.time() - t0) * 1000)
        raw_content = data.get("message", {}).get("content", "{}")
        parsed_json = json.loads(raw_content)
        normalized = normalize_extracted_json(parsed_json)

        from server.ai.agents import ExtractedPreferences
        ex = ExtractedPreferences.model_validate(normalized)
        ex.provider = "qwen"
        ex.model = model_name

        log.info("provider=qwen model=%s latency_ms=%d", model_name, latency_ms)

        if gateway.is_enabled():
            gateway.record_call(feature="preference_extraction", model=model_name, status=200)

        return ex

    finally:
        _local_semaphore.release()


async def extract_preferences_with_fallback(
    text: str,
    traveller: str,
    trip_ctx: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Any:
    """Unified entry point for preference extraction.

    Checks config / parameter for provider ("gemini" vs "qwen").
    If "qwen", tries local Ollama with non-blocking concurrency semaphore (limit 1)
    and falls back instantly to Gemini on:
    - Semaphore busy
    - Connection refused / network error
    - Timeout (> LOCAL_LLM_TIMEOUT)
    - JSON / schema validation error
    """
    settings = get_settings()
    selected_provider = (provider or settings.llm_provider).lower()

    if selected_provider != "qwen":
        from server.ai.agents import extract_preferences_gemini
        return await extract_preferences_gemini(text, traveller, trip_ctx)

    model_name = model or settings.local_llm_model
    try:
        return await extract_preferences_ollama(
            text=text,
            traveller=traveller,
            trip_ctx=trip_ctx,
            model=model_name,
            base_url=base_url,
            timeout=timeout,
        )
    except LocalLLMBusyError as exc:
        log.warning("provider=gemini fallback_reason=semaphore_busy model=%s detail=%s", model_name, exc)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        log.warning("provider=gemini fallback_reason=connection_refused model=%s detail=%s", model_name, exc)
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        log.warning("provider=gemini fallback_reason=timeout model=%s detail=%s", model_name, exc)
    except (ValidationError, json.JSONDecodeError) as exc:
        log.warning("provider=gemini fallback_reason=validation_error model=%s detail=%s", model_name, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("provider=gemini fallback_reason=unexpected_error model=%s detail=%s", model_name, exc)

    # Automatic fallback to Gemini gateway
    from server.ai.agents import extract_preferences_gemini
    return await extract_preferences_gemini(text, traveller, trip_ctx)
