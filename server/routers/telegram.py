"""FastAPI endpoint for Telegram Webhook mode."""
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from server import runtime
from server.config import get_settings
from server.telegram.bot import process_telegram_webhook

log = logging.getLogger("tripmate.telegram.webhook")
router = APIRouter(prefix="/api/telegram", tags=["telegram"])


async def _safe_process_update(data: dict) -> None:
    try:
        await process_telegram_webhook(data)
    except Exception as exc:  # noqa: BLE001
        log.exception("Error processing webhook update in background: %s", exc)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None),
):
    settings = get_settings()
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            log.warning("Rejected telegram webhook: Invalid secret token")
            raise HTTPException(403, "Invalid secret token")

    try:
        data = await request.json()
    except Exception as exc:
        log.warning("Invalid JSON received at telegram webhook: %s", exc)
        return {"ok": True}

    try:
        runtime.spawn(_safe_process_update(data))
    except Exception as exc:
        log.exception("Failed to spawn background task for telegram webhook: %s", exc)

    return {"ok": True}
