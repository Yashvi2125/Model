"""Web-server settings (database, sessions, CORS). AI settings stay in config/settings.py."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "change-me-to-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./tripmate_dev.db"
    secret_key: str = INSECURE_DEFAULT_SECRET

    # Sessions (server-side, stored in PostgreSQL, delivered as an HttpOnly cookie)
    session_hours: int = 12
    remember_me_days: int = 30
    cookie_secure: bool = False  # set true when serving over HTTPS

    # Comma-separated list of browser origins allowed to call state-changing endpoints.
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # Telegram Bot & Multi-Platform Integration
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_mode: str = "polling"  # polling | webhook
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = ""
    public_base_url: str = "http://localhost:3000"
    telegraph_access_token: str = ""
    relay_web_to_telegram: bool = True

    # AI behaviour
    ai_auto_extract: bool = True  # suggest preferences from ordinary chat messages (never auto-applied)
    ai_timeout_seconds: int = 180
    itinerary_timeout_seconds: int = 420

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and (s.secret_key == INSECURE_DEFAULT_SECRET or len(s.secret_key) < 32):
        raise RuntimeError("SECRET_KEY must be set to a random value of at least 32 characters in production.")
    return s
