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


async def _call_local_or_remote_chat(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: Any,
    model_name: str,
    messages: list[dict],
    schema: dict,
    num_predict: int = 256,
) -> str:
    """Dispatches chat completion to Ollama (/api/chat) or OpenAI-compatible endpoint (/v1/chat/completions).

    - When api_key is empty: calls standard Ollama /api/chat with 'format' JSON schema and 'options.num_predict'.
    - When api_key is present: calls /v1/chat/completions with Bearer authorization and response_format={"type": "json_object"}.
    Returns the string message content.
    """
    key_str = str(api_key).strip() if isinstance(api_key, str) else ""
    b = base_url.rstrip("/")
    if key_str:
        if b.endswith("/v1"):
            url = f"{b}/chat/completions"
        elif "/v1/" in b:
            url = b
        else:
            url = f"{b}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {key_str}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": num_predict,
            "response_format": {"type": "json_object"},
        }
        resp = await client.post(url, json=payload, headers=headers)
        if hasattr(resp, "raise_for_status"):
            res = resp.raise_for_status()
            if asyncio.iscoroutine(res):
                await res
        data = resp.json()
        if asyncio.iscoroutine(data):
            data = await data
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "{}")
        return "{}"
    else:
        url = f"{b}/api/chat"
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": num_predict,
            },
            "format": schema,
        }
        resp = await client.post(url, json=payload)
        if hasattr(resp, "raise_for_status"):
            res = resp.raise_for_status()
            if asyncio.iscoroutine(res):
                await res
        data = resp.json()
        if asyncio.iscoroutine(data):
            data = await data
        return data.get("message", {}).get("content", "{}")


async def classify_message_intent(
    text: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 15.0,
) -> tuple[str, int]:
    """Lightweight intent classification using local Ollama or remote OpenAI-compatible Qwen.

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
    key = api_key if api_key is not None else getattr(settings, "local_llm_api_key", "")

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
        messages = [
            {"role": "system", "content": LOCAL_INTENT_SYSTEM},
            {"role": "user", "content": f"Message: \"\"\"{text}\"\"\""},
        ]

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            raw_content = await _call_local_or_remote_chat(
                client=client,
                base_url=ollama_url,
                api_key=key,
                model_name=model_name,
                messages=messages,
                schema=LOCAL_INTENT_SCHEMA,
                num_predict=48,
            )

        latency_ms = int((time.time() - t0) * 1000)
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
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Any:
    """Extract trip preferences using local Ollama or OpenAI-compatible Qwen.

    Raises LocalLLMBusyError immediately if another local inference is in progress.
    """
    settings = get_settings()
    model_name = model or settings.local_llm_model
    ollama_url = base_url or settings.local_llm_base_url
    key = api_key if api_key is not None else getattr(settings, "local_llm_api_key", "")
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
        messages = [
            {"role": "system", "content": LOCAL_PREF_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        t0 = time.time()
        async with httpx.AsyncClient(timeout=float(timeout_sec)) as client:
            raw_content = await _call_local_or_remote_chat(
                client=client,
                base_url=ollama_url,
                api_key=key,
                model_name=model_name,
                messages=messages,
                schema=LOCAL_PREF_SCHEMA,
                num_predict=256,
            )

        latency_ms = int((time.time() - t0) * 1000)
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
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Any:
    """Unified entry point for preference extraction.

    Checks config / parameter for provider ("gemini" vs "qwen").
    If "qwen", tries local Ollama or OpenAI-compatible Qwen with non-blocking concurrency semaphore (limit 1)
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
            api_key=api_key,
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


# ── Localized Single-Day Itinerary Swaps ──────────────────────────────────────

DAY_SWAP_SYSTEM = (
    "You are an expert itinerary editor. Your task is to update a single day of a travel itinerary to strictly fulfill the user's customization request.\n"
    "CRITICAL RULES:\n"
    "1. You MUST incorporate the user's requested addition, replacement, or modification directly into the day's activities.\n"
    "2. If the user asks to add or visit a landmark/activity/restaurant (e.g. 'Add Eiffel tower visit on this day'), you MUST place it into the most suitable time period (Morning, Afternoon, Evening, or Night) with a descriptive sentence and estimated cost.\n"
    "3. Keep other periods intact or adjust them logically to accommodate the requested change. Do not change the day number.\n"
    "4. Return ONLY valid JSON matching this exact structure:\n"
    '{"day": int, "title": "Day Title", "intro": "optional brief intro", "sections": [{"period": "morning|afternoon|evening|night", "content": "activity text"}]}\n'
)

DAY_SWAP_SCHEMA = {
    "type": "object",
    "properties": {
        "day": {"type": "integer"},
        "title": {"type": "string"},
        "intro": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["morning", "afternoon", "evening", "night"]},
                    "content": {"type": "string"},
                },
                "required": ["period", "content"],
            },
        },
    },
    "required": ["day", "title", "sections"],
}


async def _swap_itinerary_day_gemini(day_data: dict, instruction: str, trip_ctx: str) -> tuple[dict, str]:
    from server.ai.client import ai_status, llm_json
    prompt = (
        f"Trip Context: {trip_ctx}\n\n"
        f"Current Day Plan (Day {day_data.get('day')}):\n{json.dumps(day_data, ensure_ascii=False, indent=2)}\n\n"
        f"User Customization Request: {instruction}\n\n"
        f"Please update Day {day_data.get('day')} so that '{instruction}' is fully and explicitly incorporated into the day's schedule."
    )
    t0 = time.time()
    data = await llm_json(DAY_SWAP_SYSTEM, prompt, feature="itinerary_day_swap")
    latency_ms = int((time.time() - t0) * 1000)
    model = ai_status().get("model", "gemini-3.5-flash-lite")
    log.info("provider=gemini model=%s latency_ms=%d feature=itinerary_day_swap", model, latency_ms)

    if not isinstance(data, dict) or "sections" not in data or not data["sections"]:
        raise ValueError("Invalid day structure returned from Gemini")

    data["day"] = day_data.get("day", data.get("day", 1))
    data.setdefault("title", day_data.get("title", f"Day {data['day']}"))
    data.setdefault("intro", day_data.get("intro", ""))
    return data, "gemini"


async def swap_itinerary_day(
    day_data: dict,
    instruction: str,
    trip_ctx: str = "",
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> tuple[dict, str]:
    """Swap or customize a single-day itinerary slice.

    Tries local Ollama or OpenAI-compatible Qwen with non-blocking semaphore (1) and falls back immediately to Gemini.
    """
    settings = get_settings()
    if getattr(settings, "llm_provider", "gemini").lower() != "qwen":
        return await _swap_itinerary_day_gemini(day_data, instruction, trip_ctx)

    model_name = model or ("qwen2.5:1.5b-instruct" if "1.5b" in getattr(settings, "local_llm_model", "") else getattr(settings, "local_llm_model", "qwen2.5:1.5b-instruct"))
    ollama_url = base_url or settings.local_llm_base_url
    key = api_key if api_key is not None else getattr(settings, "local_llm_api_key", "")
    timeout_sec = timeout or settings.local_llm_timeout

    if _local_semaphore.locked():
        log.warning("provider=gemini fallback_reason=semaphore_busy feature=itinerary_day_swap")
        return await _swap_itinerary_day_gemini(day_data, instruction, trip_ctx)

    try:
        await asyncio.wait_for(_local_semaphore.acquire(), timeout=0.001)
    except (asyncio.TimeoutError, Exception):
        log.warning("provider=gemini fallback_reason=semaphore_busy feature=itinerary_day_swap")
        return await _swap_itinerary_day_gemini(day_data, instruction, trip_ctx)

    t0 = time.time()
    try:
        prompt = (
            f"Trip Context: {trip_ctx}\n\n"
            f"Current Day Plan (Day {day_data.get('day')}):\n{json.dumps(day_data, ensure_ascii=False, indent=2)}\n\n"
            f"User Customization Request: {instruction}\n\n"
            f"Please update Day {day_data.get('day')} so that '{instruction}' is fully and explicitly incorporated into the day's schedule."
        )
        messages = [
            {"role": "system", "content": DAY_SWAP_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        async with httpx.AsyncClient(timeout=float(timeout_sec)) as client:
            raw_content = await _call_local_or_remote_chat(
                client=client,
                base_url=ollama_url,
                api_key=key,
                model_name=model_name,
                messages=messages,
                schema=DAY_SWAP_SCHEMA,
                num_predict=384,
            )

        latency_ms = int((time.time() - t0) * 1000)
        parsed = json.loads(raw_content)

        if not isinstance(parsed, dict) or "sections" not in parsed:
            raise ValueError("Invalid day structure returned")

        # Ensure day number is preserved
        parsed["day"] = day_data.get("day", parsed.get("day", 1))
        parsed.setdefault("title", day_data.get("title", f"Day {parsed['day']}"))
        parsed.setdefault("intro", "")

        log.info("provider=qwen model=%s latency_ms=%d feature=itinerary_day_swap", model_name, latency_ms)
        if gateway.is_enabled():
            gateway.record_call(feature="itinerary_day_swap", model=model_name, status=200)

        return parsed, "qwen"

    except Exception as exc:  # noqa: BLE001
        reason = "timeout" if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "connection_refused" if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) else "validation_error"
        log.warning("provider=gemini fallback_reason=%s detail=%s feature=itinerary_day_swap", reason, exc)
        return await _swap_itinerary_day_gemini(day_data, instruction, trip_ctx)
    finally:
        _local_semaphore.release()


# ── AI Packing Checklist Generator ───────────────────────────────────────────

PACKING_SYSTEM = (
    "You are a travel preparation assistant. Suggest 8-12 essential, practical packing items for this trip based on the destination, duration, weather, and activities.\n"
    "Categorize each item: clothing, electronics, documents, toiletries, gear, or health.\n"
    "Return JSON only matching the schema: {\"items\": [{\"text\": \"Item description\", \"category\": \"clothing|electronics|documents|toiletries|gear|health\"}]}.\n"
)

PACKING_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["text", "category"],
            },
        }
    },
    "required": ["items"],
}


async def _generate_packing_list_gemini(trip_ctx: str, focus: Optional[str] = None) -> tuple[list[dict], str]:
    from server.ai.client import ai_status, llm_json
    prompt = f"Trip Context:\n{trip_ctx}"
    if focus:
        prompt += f"\n\nSpecial Packing Focus: {focus}"
    t0 = time.time()
    data = await llm_json(PACKING_SYSTEM, prompt, feature="checklist_generation")
    latency_ms = int((time.time() - t0) * 1000)
    model = ai_status().get("model", "gemini-3.5-flash-lite")
    log.info("provider=gemini model=%s latency_ms=%d feature=checklist_generation", model, latency_ms)
    items = data.get("items", []) if isinstance(data, dict) else []
    return items, "gemini"


async def generate_packing_list(
    trip_ctx: str,
    focus: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> tuple[list[dict], str]:
    """Generate categorized packing items via local Ollama or OpenAI-compatible Qwen with instant Gemini fallback."""
    settings = get_settings()
    if getattr(settings, "llm_provider", "gemini").lower() != "qwen":
        return await _generate_packing_list_gemini(trip_ctx, focus)

    model_name = model or ("qwen2.5:1.5b-instruct" if "1.5b" in getattr(settings, "local_llm_model", "") else getattr(settings, "local_llm_model", "qwen2.5:1.5b-instruct"))
    ollama_url = base_url or settings.local_llm_base_url
    key = api_key if api_key is not None else getattr(settings, "local_llm_api_key", "")
    timeout_sec = timeout or settings.local_llm_timeout

    if _local_semaphore.locked():
        log.warning("provider=gemini fallback_reason=semaphore_busy feature=checklist_generation")
        return await _generate_packing_list_gemini(trip_ctx, focus)

    try:
        await asyncio.wait_for(_local_semaphore.acquire(), timeout=0.001)
    except (asyncio.TimeoutError, Exception):
        log.warning("provider=gemini fallback_reason=semaphore_busy feature=checklist_generation")
        return await _generate_packing_list_gemini(trip_ctx, focus)

    t0 = time.time()
    try:
        prompt = f"Trip Context:\n{trip_ctx}"
        if focus:
            prompt += f"\n\nSpecial Packing Focus: {focus}"

        messages = [
            {"role": "system", "content": PACKING_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        async with httpx.AsyncClient(timeout=float(timeout_sec)) as client:
            raw_content = await _call_local_or_remote_chat(
                client=client,
                base_url=ollama_url,
                api_key=key,
                model_name=model_name,
                messages=messages,
                schema=PACKING_SCHEMA,
                num_predict=384,
            )

        latency_ms = int((time.time() - t0) * 1000)
        parsed = json.loads(raw_content)
        items = parsed.get("items", []) if isinstance(parsed, dict) else []

        if not items:
            raise ValueError("No packing items generated")

        log.info("provider=qwen model=%s latency_ms=%d feature=checklist_generation", model_name, latency_ms)
        if gateway.is_enabled():
            gateway.record_call(feature="checklist_generation", model=model_name, status=200)

        return items, "qwen"

    except Exception as exc:  # noqa: BLE001
        reason = "timeout" if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "connection_refused" if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) else "validation_error"
        log.warning("provider=gemini fallback_reason=%s detail=%s feature=checklist_generation", reason, exc)
        return await _generate_packing_list_gemini(trip_ctx, focus)
    finally:
        _local_semaphore.release()


# ── Trip Chat Summarization ("Catch me up") ───────────────────────────────────

CHAT_SUMMARY_SYSTEM = (
    "Summarize the key decisions, agreed plans, traveller preferences, and pending questions from the recent group trip chat messages.\n"
    "Output 4-5 concise, actionable bullet points.\n"
    "Return JSON only matching the schema: {\"bullets\": [\"bullet 1\", \"bullet 2\", ...]}.\n"
)

CHAT_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["bullets"],
}


async def _summarize_chat_gemini(messages_text: str, trip_ctx: str) -> tuple[list[str], str]:
    from server.ai.client import ai_status, llm_json
    prompt = f"Trip Context: {trip_ctx}\n\nRecent Chat Messages:\n{messages_text}"
    t0 = time.time()
    data = await llm_json(CHAT_SUMMARY_SYSTEM, prompt, feature="chat_summarization")
    latency_ms = int((time.time() - t0) * 1000)
    model = ai_status().get("model", "gemini-3.5-flash-lite")
    log.info("provider=gemini model=%s latency_ms=%d feature=chat_summarization", model, latency_ms)
    bullets = data.get("bullets", []) if isinstance(data, dict) else []
    return bullets, "gemini"


async def summarize_chat_messages(
    messages_text: str,
    trip_ctx: str = "",
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[int] = None,
) -> tuple[list[str], str]:
    """Summarize recent chat into 4-5 bullet points with instant Gemini fallback."""
    settings = get_settings()
    if getattr(settings, "llm_provider", "gemini").lower() != "qwen":
        return await _summarize_chat_gemini(messages_text, trip_ctx)

    model_name = model or ("qwen2.5:1.5b-instruct" if "1.5b" in getattr(settings, "local_llm_model", "") else getattr(settings, "local_llm_model", "qwen2.5:1.5b-instruct"))
    ollama_url = base_url or settings.local_llm_base_url
    key = api_key if api_key is not None else getattr(settings, "local_llm_api_key", "")
    timeout_sec = timeout or settings.local_llm_timeout

    if _local_semaphore.locked():
        log.warning("provider=gemini fallback_reason=semaphore_busy feature=chat_summarization")
        return await _summarize_chat_gemini(messages_text, trip_ctx)

    try:
        await asyncio.wait_for(_local_semaphore.acquire(), timeout=0.001)
    except (asyncio.TimeoutError, Exception):
        log.warning("provider=gemini fallback_reason=semaphore_busy feature=chat_summarization")
        return await _summarize_chat_gemini(messages_text, trip_ctx)

    t0 = time.time()
    try:
        prompt = f"Trip Context: {trip_ctx}\n\nRecent Chat Messages:\n{messages_text}"
        messages = [
            {"role": "system", "content": CHAT_SUMMARY_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        async with httpx.AsyncClient(timeout=float(timeout_sec)) as client:
            raw_content = await _call_local_or_remote_chat(
                client=client,
                base_url=ollama_url,
                api_key=key,
                model_name=model_name,
                messages=messages,
                schema=CHAT_SUMMARY_SCHEMA,
                num_predict=256,
            )

        latency_ms = int((time.time() - t0) * 1000)
        parsed = json.loads(raw_content)
        bullets = parsed.get("bullets", []) if isinstance(parsed, dict) else []

        if not bullets:
            raise ValueError("No bullets returned from summarizer")

        log.info("provider=qwen model=%s latency_ms=%d feature=chat_summarization", model_name, latency_ms)
        if gateway.is_enabled():
            gateway.record_call(feature="chat_summarization", model=model_name, status=200)

        return bullets, "qwen"

    except Exception as exc:  # noqa: BLE001
        reason = "timeout" if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)) else "connection_refused" if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)) else "validation_error"
        log.warning("provider=gemini fallback_reason=%s detail=%s feature=chat_summarization", reason, exc)
        return await _summarize_chat_gemini(messages_text, trip_ctx)
    finally:
        _local_semaphore.release()

