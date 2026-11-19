"""FastAPI endpoint for Telegram Webhook mode."""
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from server.config import get_settings
from server.telegram.bot import process_telegram_webhook

log = logging.getLogger("tripmate.telegram.webhook")
router = APIRouter(prefix="/api/telegram", tags=["telegram"])


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

    data = await request.json()
    try:
        await process_telegram_webhook(data)
    except Exception as exc:  # noqa: BLE001
        log.exception("Error processing webhook update: %s", exc)
    return {"ok": True}
