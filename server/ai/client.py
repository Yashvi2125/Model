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
from typing import Any

import config.settings as ai_settings
from server.config import get_settings

log = logging.getLogger("tripmate.ai")


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
    }


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
    if "429" in text or ("rate" in text and "limit" in text) or "quota" in text or "resource_exhausted" in text:
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
    system + user are combined into a single prompt since the native SDK
    treats the first turn as user content; we prepend the system instruction.
    Supports automatic fallback to GEMINI_FALLBACK_MODEL on 429, 503, 404, or overload errors.
    """
    effective_timeout = timeout or get_settings().ai_timeout_seconds
    primary_model = ai_settings.GEMINI_MODEL or "gemini-3.8-flash"
    fallback_model = getattr(ai_settings, "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

    client = _get_genai_client()
    prompt = f"{system}\n\n{user}"

    import google.genai.types as genai_types

    async def _call_model(model_name: str):
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

    response = None
    try:
        response = await _call_model(primary_model)
    except asyncio.TimeoutError as exc:
        raise AIError("The AI took too long to respond. Please try again.") from exc
    except Exception as exc:  # noqa: BLE001
        err_str = str(exc).lower()
        is_recoverable = any(k in err_str for k in ("429", "503", "404", "overloaded", "unavailable", "rate", "resource_exhausted", "not_found"))
        if is_recoverable and fallback_model and fallback_model != primary_model:
            log.warning("Primary model %s failed (%s); falling back to %s", primary_model, exc, fallback_model)
            try:
                response = await _call_model(fallback_model)
            except asyncio.TimeoutError as f_exc:
                raise AIError("The AI took too long to respond. Please try again.") from f_exc
            except Exception as f_exc:  # noqa: BLE001
                raise friendly_error(f_exc) from f_exc
        else:
            raise friendly_error(exc) from exc

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
