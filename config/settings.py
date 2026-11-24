"""
Configuration settings for AutoGen Travel Planner.
Loads API keys and runtime parameters from .env.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Google Gemini settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_CHAIN_STR = os.getenv("GEMINI_MODEL_CHAIN", "gemini-3.5-flash-lite,gemini-3.1-flash-lite")
GEMINI_MODEL_CHAIN = [m.strip() for m in GEMINI_MODEL_CHAIN_STR.split(",") if m.strip()]
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or (GEMINI_MODEL_CHAIN[0] if GEMINI_MODEL_CHAIN else "gemini-3.5-flash-lite")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL") or (GEMINI_MODEL_CHAIN[1] if len(GEMINI_MODEL_CHAIN) > 1 else GEMINI_MODEL)

# Weather service API keys
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

# Backwards compatibility alias
MODEL = GEMINI_MODEL

# Tavily search settings
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Telegram Bot settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Team execution settings
MAX_TURN = int(os.getenv("MAX_TURN", "7"))
MAX_TURN_10 = int(os.getenv("MAX_TURN_10", "10"))
TERMINATION_WORD = os.getenv("TERMINATION_WORD", "stop")


def validate_config(require_keys: bool = True) -> list[str]:
    """
    Validate that required environment variables are set and not placeholders.

    Args:
        require_keys: If True, raises ValueError when required keys are missing.

    Returns:
        list[str]: List of error messages for missing or invalid variables.
    """
    errors: list[str] = []

    if not GEMINI_API_KEY or "your_gemini_api_key" in GEMINI_API_KEY.lower():
        errors.append(
            "GEMINI_API_KEY is missing or not configured. "
            "Please obtain a Gemini API key from Google AI Studio (https://aistudio.google.com/) "
            "and set it in your .env file."
        )

    if not TAVILY_API_KEY or "your_tavily_api_key" in TAVILY_API_KEY.lower():
        errors.append(
            "TAVILY_API_KEY is missing or not configured. "
            "Please obtain a Tavily API key from https://tavily.com/ "
            "and set it in your .env file."
        )

    if errors and require_keys:
        raise ValueError("\n".join(errors))

    return errors