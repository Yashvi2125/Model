"""Thin async helpers around the Google GenAI SDK.

Replaces the AutoGen OpenAI-compat path (which returns 503 for Interactions-API
keys that start with 'AQ.'). Uses google-genai directly for all LLM calls while
keeping the same llm_text / llm_json / AIError interface the rest of the app expects.

The AutoGen team is kept for the multi-agent travel planner workflow (workflow.py /
travel_team.py), but all single-turn chat calls (preference extraction, conflict
resolution, chat reply, budget extraction) go through this module.
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

import config.settings as ai_settings
from models.gemini_model import get_gemini_semaphore
from server.config import get_settings

log = logging.getLogger("tripmate.ai")

# Model cooldown dictionary: model_name -> expiration timestamp (epoch seconds)
_model_cooldown: dict[str, float] = {}


class AIError(Exception):
    """Carries a message that is safe to show to end users."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AINotConfigured(AIError):
    pass


def _configured(value) -> bool:
    return bool(value) and "your_" not in str(value).lower()


def ai_status() -> dict:
    return {
        "gemini_configured": _configured(ai_settings.GEMINI_API_KEY),
        "tavily_configured": _configured(ai_settings.TAVILY_API_KEY),
        "model": ai_settings.GEMINI_MODEL,
        "model_chain": getattr(ai_settings, "GEMINI_MODEL_CHAIN", [ai_settings.GEMINI_MODEL]),
    }


# ── retryDelay and rate limit helpers ─────────────────────────────────────────

def parse_retry_delay(exc: Exception) -> Optional[float]:
    """Extract retry delay in seconds from exception string or details if present."""
    text = str(exc)
    # Match patterns like: retryDelay': '12.3s' or retryDelay: "15s" or retry_delay { seconds: 12 }
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)\s*s?", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            pass
    m = re.search(r"retry_after['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            pass
    m = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*s", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            pass
    return None


def is_daily_quota_error(exc: Exception) -> bool:
    """Check if the error is due to daily quota exhaustion (e.g. free tier daily requests limit)."""
    text = str(exc).lower()
    if any(k in text for k in ("per day", "requests per day", "daily", "day limit", "free_tier_requests_per_day", "per_day")):
        return True
    delay = parse_retry_delay(exc)
    if delay is not None and delay > 300:
        return True
    return False


def is_rate_limit_error(exc: Exception) -> bool:
    """Check if the error is 429, RESOURCE_EXHAUSTED, or rate/quota limit."""
    text = str(exc).lower()
    return any(k in text for k in ("429", "rate", "resource_exhausted", "quota", "overloaded"))


def format_delay(seconds: Optional[float]) -> str:
    """Format seconds into human-readable text (e.g. '15s', '2 minutes', '3.5 hours')."""
    if not seconds or seconds <= 0:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        mins = max(1, int(round(seconds / 60)))
        return f"{mins} minute{'s' if mins != 1 else ''}"
    hours = round(seconds / 3600, 1)
    hours_val = int(hours) if hours == int(hours) else hours
    return f"{hours_val} hour{'s' if hours_val != 1 else ''}"


def mark_model_cooldown(model_name: str, exc: Exception) -> None:
    """Put a model in cooldown so subsequent calls try other models in the chain."""
    delay = parse_retry_delay(exc)
    if is_daily_quota_error(exc):
        # Daily quota exhausted: cooldown for the provided delay or 24 hours
        cooldown_secs = delay if (delay and delay > 300) else 86400.0
    else:
        # Per-minute rate limit: cooldown for delay or 60s
        cooldown_secs = delay if delay else 60.0

    expiry = time.time() + cooldown_secs
    _model_cooldown[model_name] = expiry
    log.warning(
        "Model '%s' placed in cooldown until %f (duration: %s) due to %s",
        model_name,
        expiry,
        format_delay(cooldown_secs),
        type(exc).__name__,
    )


def is_model_available(model_name: str) -> bool:
    """Check whether a model has passed its cooldown period."""
    exp = _model_cooldown.get(model_name)
    if not exp:
        return True
    if time.time() >= exp:
        _model_cooldown.pop(model_name, None)
        return True
    return False


# ── native google-genai client ────────────────────────────────────────────────

def _get_genai_client():
    """Return a google.genai.Client, raising AINotConfigured if the key is missing."""
    if not _configured(ai_settings.GEMINI_API_KEY):
        raise AINotConfigured(
            "The AI assistant isn't set up yet. Add GEMINI_API_KEY to the .env file and restart the backend."
        )
    import google.genai as genai  # installed: google-genai>=1.0.0
    return genai.Client(api_key=ai_settings.GEMINI_API_KEY)


def get_client():
    """
    Compatibility shim: workflow.py / gemini_model.py still use the AutoGen
    OpenAI-compat client for the multi-agent travel-team. Return that client
    when asked; raise AINotConfigured when the key is missing.
    """
    if not _configured(ai_settings.GEMINI_API_KEY):
        raise AINotConfigured(
            "The AI assistant isn't set up yet. Add GEMINI_API_KEY to the .env file and restart the backend."
        )
    from models import gemini_model
    return gemini_model.model_client or gemini_model.create_gemini_model_client()


# ── error helpers ─────────────────────────────────────────────────────────────

def friendly_error(exc: Exception) -> AIError:
    if isinstance(exc, AIError):
        return exc
    text = str(exc).lower()
    log.warning("AI call failed: %s: %s", type(exc).__name__, str(exc)[:300])

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timed out" in text or "timeout" in text:
        return AIError("The AI took too long to respond. Please try again.")

    if is_rate_limit_error(exc):
        delay = parse_retry_delay(exc)
        delay_str = format_delay(delay)
        if is_daily_quota_error(exc):
            if delay_str:
                return AIError(f"The daily free AI quota is used up. It will reset later (try again in {delay_str}).")
            return AIError("The daily free AI quota is used up. It will reset later. Please try again tomorrow.")
        else:
            if delay_str:
                return AIError(f"The AI service is rate-limited right now. Please wait {delay_str} and try again.")
            return AIError("The AI service is rate-limited right now. Wait a minute and try again.")

    if "401" in text or "403" in text or "api key" in text or "permission" in text:
        return AIError("The AI provider rejected the API key. Check GEMINI_API_KEY in the .env file.")
    if ("404" in text and "model" in text) or "not_found" in text or "no longer available" in text:
        return AIError("The configured Gemini model wasn't found. Check GEMINI_MODEL in the .env file.")
    if "503" in text or "service unavailable" in text or "unavailable" in text:
        return AIError("The AI service is temporarily unavailable. Please try again in a moment.")
    return AIError("The AI service returned an error. Please try again in a moment.")


# ── core LLM helpers (google-genai native) ────────────────────────────────────

async def llm_text(system: str, user: str, timeout: int | None = None) -> str:
    """
    Single-turn text generation using the google-genai SDK.
    Iterates through the model chain (GEMINI_MODEL_CHAIN) skipping cooled-down models.
    Honours the global concurrency limit (2) and logs which model answered.
    """
    effective_timeout = timeout or get_settings().ai_timeout_seconds
    model_chain = list(ai_settings.GEMINI_MODEL_CHAIN)
    if not model_chain:
        model_chain = [ai_settings.GEMINI_MODEL or "gemini-3.5-flash-lite"]

    # Filter out models currently in cooldown; if all are in cooldown, try all as fallback
    candidate_models = [m for m in model_chain if is_model_available(m)]
    if not candidate_models:
        candidate_models = model_chain

    client = _get_genai_client()
    prompt = f"{system}\n\n{user}"
    import google.genai.types as genai_types

    async def _call_model(model_name: str):
        sem = get_gemini_semaphore()
        async with sem:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.4,
                    ),
                ),
                timeout=effective_timeout,
            )

    last_exc = None
    response = None
    model_that_answered = None

    for model_name in candidate_models:
        try:
            response = await _call_model(model_name)
            model_that_answered = model_name
            log.info("AI call answered successfully by '%s'", model_name)
            break
        except asyncio.TimeoutError as exc:
            last_exc = exc
            log.warning("AI model '%s' timed out after %ds", model_name, effective_timeout)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if is_rate_limit_error(exc):
                mark_model_cooldown(model_name, exc)
                log.warning("AI model '%s' rate limited (%s); falling back to next model", model_name, exc)
            else:
                err_str = str(exc).lower()
                is_recoverable = any(k in err_str for k in ("503", "404", "overloaded", "unavailable", "not_found"))
                if is_recoverable:
                    log.warning("AI model '%s' encountered recoverable error (%s); trying next model", model_name, exc)
                else:
                    # Non-recoverable error (e.g. auth 401/403)
                    raise friendly_error(exc) from exc

    if response is None:
        raise friendly_error(last_exc or RuntimeError("All AI models in chain failed"))

    # Extract text
    try:
        content = response.text
    except Exception:
        try:
            content = response.candidates[0].content.parts[0].text
        except Exception:
            content = ""

    if not content or not content.strip():
        raise AIError("The AI returned an empty response. Please try again.")
    return content.strip()


def extract_json(text: str) -> dict[str, Any]:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise AIError("The AI response couldn't be understood. Please try again.")
    try:
        data = json.loads(t[start: end + 1])
    except json.JSONDecodeError as exc:
        raise AIError("The AI response couldn't be understood. Please try again.") from exc
    if not isinstance(data, dict):
        raise AIError("The AI response couldn't be understood. Please try again.")
    return data


async def llm_json(system: str, user: str, timeout: int | None = None) -> dict[str, Any]:
    return extract_json(await llm_text(system, user, timeout))
