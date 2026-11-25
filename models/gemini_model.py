"""
Google Gemini model client integration for AutoGen agents.
Connects to Google AI Studio using the official Gemini endpoint.
"""
import asyncio
from typing import Optional
from config.settings import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MODEL_CHAIN
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ModelFamily

# Global concurrency semaphore for all Gemini calls (limit 2 concurrent calls)
_gemini_semaphore: Optional[asyncio.Semaphore] = None


def get_gemini_semaphore() -> asyncio.Semaphore:
    global _gemini_semaphore
    if _gemini_semaphore is None:
        _gemini_semaphore = asyncio.Semaphore(2)
    return _gemini_semaphore


def register_gemini_model_transformer(model_name: str) -> None:
    """Register a model with AutoGen's OpenAI message transformer to support Gemini format."""
    try:
        from autogen_ext.models.openai import _message_transform
        from autogen_ext.models.openai._transformation import register_transformer

        _message_transform.assistant_transformer_funcs_gemini["tools"] = (
            _message_transform.thought_assistant_transformer_funcs_gemini
        )
        register_transformer("openai", model_name, _message_transform.__GEMINI_TRANSFORMER_MAP)
    except Exception:
        pass


# Register all models in GEMINI_MODEL_CHAIN dynamically at startup
try:
    from autogen_ext.models.openai import _message_transform
    from autogen_ext.models.openai._transformation import register_transformer

    _message_transform.assistant_transformer_funcs_gemini["tools"] = (
        _message_transform.thought_assistant_transformer_funcs_gemini
    )
    register_transformer("openai", "gemini", _message_transform.__GEMINI_TRANSFORMER_MAP)

    all_models = set(GEMINI_MODEL_CHAIN) | {
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    }
    for m in all_models:
        register_gemini_model_transformer(m)
except Exception:
    pass

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def create_gemini_model_client(
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: str = DEFAULT_GEMINI_BASE_URL,
) -> OpenAIChatCompletionClient:
    """
    Create an AutoGen ChatCompletionClient configured for Google Gemini via Google AI Studio.

    Args:
        model: Gemini model identifier (e.g. 'gemini-3.5-flash-lite'). Defaults to GEMINI_MODEL setting.
        api_key: Gemini API key. Defaults to GEMINI_API_KEY setting.
        base_url: Google AI Studio OpenAI-compatible endpoint.

    Returns:
        OpenAIChatCompletionClient configured for Gemini with concurrency throttling.
    """
    effective_model = model or GEMINI_MODEL or (GEMINI_MODEL_CHAIN[0] if GEMINI_MODEL_CHAIN else "gemini-3.5-flash-lite")
    effective_key = api_key or GEMINI_API_KEY

    if not effective_key:
        raise ValueError(
            "GEMINI_API_KEY is missing. Please set GEMINI_API_KEY in your .env file or environment."
        )

    # Ensure this specific model is registered dynamically in message transformer
    register_gemini_model_transformer(effective_model)

    client = OpenAIChatCompletionClient(
        model=effective_model,
        api_key=effective_key,
        base_url=base_url,
        max_retries=1,
        timeout=180.0,
        model_info={
            "vision": True,
            "function_calling": True,
            "json_output": True,
            "family": ModelFamily.GEMINI_2_5_FLASH,
            "structured_output": False,
        },
    )

    # Enforce concurrency limit (2) and central gateway rate limiting/priority queue per Gemini request
    orig_create = client.create

    async def throttled_create(*args, **kwargs):
        from server.ai.gateway import (
            PRIORITY_URGENT,
            gateway,
            is_overload_error,
            is_rate_limit_error,
            parse_retry_delay,
        )

        sem = get_gemini_semaphore()
        async with sem:
            if gateway.is_enabled():
                await gateway.acquire_slot(
                    model=effective_model,
                    priority=PRIORITY_URGENT,
                    feature="itinerary_planning",
                )
            try:
                res = await orig_create(*args, **kwargs)
                if gateway.is_enabled():
                    gateway.record_call(feature="itinerary_planning", model=effective_model, status=200)
                return res
            except Exception as exc:
                if gateway.is_enabled():
                    code = getattr(exc, "status_code", None) or ("429" if is_rate_limit_error(exc) else "503" if is_overload_error(exc) else "error")
                    gateway.record_call(feature="itinerary_planning", model=effective_model, status=code)
                    if is_rate_limit_error(exc):
                        delay = parse_retry_delay(exc)
                        gateway.learn_429(effective_model, delay)
                raise

    client.create = throttled_create
    return client


def create_qwen_model_client(
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OpenAIChatCompletionClient:
    """
    Create an AutoGen OpenAIChatCompletionClient configured for Qwen (hosted Groq or local Ollama).
    """
    from autogen_core.models import ModelFamily
    import config.settings as ai_settings

    effective_model = model or getattr(ai_settings, "LOCAL_LLM_MODEL", "qwen2.5:3b-instruct")
    raw_url = base_url or getattr(ai_settings, "LOCAL_LLM_BASE_URL", "http://host.docker.internal:11434")
    norm_url = raw_url.rstrip("/")
    if not norm_url.endswith("/v1"):
        norm_url = f"{norm_url}/v1"
    effective_key = api_key if api_key is not None else getattr(ai_settings, "LOCAL_LLM_API_KEY", "")
    if not effective_key:
        effective_key = "ollama"

    client = OpenAIChatCompletionClient(
        model=effective_model,
        api_key=effective_key,
        base_url=norm_url,
        max_retries=1,
        timeout=180.0,
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "family": ModelFamily.UNKNOWN,
            "structured_output": False,
        },
    )

    orig_create = client.create

    async def throttled_qwen_create(*args, **kwargs):
        from server.ai.gateway import (
            PRIORITY_URGENT,
            gateway,
            is_overload_error,
            is_rate_limit_error,
        )

        if gateway.is_enabled():
            await gateway.acquire_slot(
                model=effective_model,
                priority=PRIORITY_URGENT,
                feature="itinerary_planning",
            )
        try:
            res = await orig_create(*args, **kwargs)
            if gateway.is_enabled():
                gateway.record_call(feature="itinerary_planning", model=effective_model, status=200)
            return res
        except Exception as exc:
            if gateway.is_enabled():
                code = getattr(exc, "status_code", None) or ("429" if is_rate_limit_error(exc) else "503" if is_overload_error(exc) else "error")
                gateway.record_call(feature="itinerary_planning", model=effective_model, status=code)
            raise

    client.create = throttled_qwen_create
    return client


# Default model client instance for AutoGen agents
try:
    if GEMINI_API_KEY:
        model_client = create_gemini_model_client()
    else:
        model_client = None
except Exception:
    model_client = None
