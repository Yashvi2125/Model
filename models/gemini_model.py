"""
Google Gemini model client integration for AutoGen agents.
Connects to Google AI Studio using the official Gemini endpoint.
"""
from typing import Optional
from config.settings import GEMINI_API_KEY, GEMINI_MODEL
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ModelFamily

try:
    from autogen_ext.models.openai import _message_transform
    from autogen_ext.models.openai._transformation import register_transformer

    # Ensure Gemini assistant tool call messages have non-null content (' ') to avoid Google 400 Bad Request
    _message_transform.assistant_transformer_funcs_gemini["tools"] = (
        _message_transform.thought_assistant_transformer_funcs_gemini
    )
    register_transformer("openai", "gemini", _message_transform.__GEMINI_TRANSFORMER_MAP)
    for m in ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash-lite"]:
        register_transformer("openai", m, _message_transform.__GEMINI_TRANSFORMER_MAP)
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
        model: Gemini model identifier (e.g. 'gemini-2.5-flash'). Defaults to GEMINI_MODEL setting.
        api_key: Gemini API key. Defaults to GEMINI_API_KEY setting.
        base_url: Google AI Studio OpenAI-compatible endpoint.

    Returns:
        OpenAIChatCompletionClient configured for Gemini.
    """
    effective_model = model or GEMINI_MODEL or "gemini-3.8-flash"
    effective_key = api_key or GEMINI_API_KEY

    if not effective_key:
        raise ValueError(
            "GEMINI_API_KEY is missing. Please set GEMINI_API_KEY in your .env file or environment."
        )

    return OpenAIChatCompletionClient(
        model=effective_model,
        api_key=effective_key,
        base_url=base_url,
        max_retries=5,
        timeout=180.0,
        model_info={
            "vision": True,
            "function_calling": True,
            "json_output": True,
            "family": ModelFamily.GEMINI_2_5_FLASH,
            "structured_output": False,
        },
    )


# Default model client instance for AutoGen agents
# If GEMINI_API_KEY is not yet set in environment, defer instantiation until called
try:
    if GEMINI_API_KEY:
        model_client = create_gemini_model_client()
    else:
        model_client = None
except Exception:
    model_client = None
