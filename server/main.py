"""FastAPI application: REST API + WebSocket chat around the existing multi-agent travel planner."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server import runtime
from server.ai.client import ai_status
from server.config import get_settings
from server.routers import auth, chat, checklist, conflicts, health, merge_preferences, planning, preferences, research, telegram, trips, users
from server.security import origin_allowed
from server.services.itinerary_service import mark_stale_runs_failed
from server.telegram.bot import start_telegram_service, stop_telegram_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
log = logging.getLogger("tripmate")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    runtime.set_loop(asyncio.get_running_loop())
    if settings.secret_key.startswith("change-me"):
        log.warning("SECRET_KEY is the insecure default. Set a random value in .env before deploying.")
    # Ensure all tables exist on first startup (auto-migration for fresh clones / SQLite)
    try:
        from server.db import Base, engine
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not auto-create tables: %s", exc)
    try:
        await asyncio.to_thread(mark_stale_runs_failed)
    except Exception:  # noqa: BLE001
        log.error("Database is not reachable or not migrated yet (run `alembic upgrade head`).")
    s = ai_status()
    log.info("AI configured: gemini=%s tavily=%s model=%s", s["gemini_configured"], s["tavily_configured"], s["model"])

    # Launch Telegram Bot service in background
    if settings.telegram_bot_token:
        try:
            await start_telegram_service()
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to start Telegram service: %s", exc)

    yield

    try:
        await stop_telegram_service()
    except Exception as exc:  # noqa: BLE001
        log.warning("Error stopping Telegram service: %s", exc)


settings = get_settings()
app = FastAPI(title="Multi-Agent Group Trip Planner API", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs" if not settings.is_production else None,
              redoc_url=None, openapi_url="/api/openapi.json" if not settings.is_production else None)


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not origin_allowed(
            request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"detail": "Request blocked: it didn't come from this site."}, status_code=403)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    fields, first = {}, None
    for err in exc.errors():
        msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
        loc = [p for p in err.get("loc", []) if p not in ("body", "query", "path")]
        if loc:
            fields.setdefault(str(loc[-1]), msg)
        first = first or msg
    return JSONResponse({"detail": first or "Please check the form and try again.", "fields": fields}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error", exc_info=exc)
    return JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)


for r in (health, auth, users, trips, chat, preferences, conflicts, planning, checklist, research, merge_preferences, telegram):
    app.include_router(r.router)
