"""Tests for cloud deployment readiness: CORS, cookie security, and Telegram webhook mode."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from server.config import get_settings
from server.main import app
from server.security import clear_session_cookie, set_session_cookie
from server.telegram import bot as bot_module


def test_cors_preflight_allowed_and_disallowed_origins(client: TestClient):
    allowed_origin = get_settings().origins[0]

    # Preflight from allowed origin
    res = client.options(
        "/api/trips",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == allowed_origin
    assert res.headers.get("access-control-allow-credentials") == "true"

    # Preflight from disallowed origin
    res_bad = client.options(
        "/api/trips",
        headers={
            "Origin": "https://malicious-site.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_bad.headers.get("access-control-allow-origin") is None


def test_cookie_samesite_per_cookie_secure():
    # 1. Dev / Non-secure mode: SameSite=Lax, Secure not set
    resp_dev = Response()
    with patch.object(get_settings(), "cookie_secure", False):
        set_session_cookie(resp_dev, token="token_dev", max_age=3600, remember=True)
        cookie_header = resp_dev.headers.get("set-cookie", "").lower()
        assert "samesite=lax" in cookie_header
        assert "secure" not in cookie_header

        clear_resp_dev = Response()
        clear_session_cookie(clear_resp_dev)
        clear_cookie = clear_resp_dev.headers.get("set-cookie", "").lower()
        assert "samesite=lax" in clear_cookie
        assert "secure" not in clear_cookie

    # 2. Production / Secure mode: SameSite=None, Secure is True
    resp_prod = Response()
    with patch.object(get_settings(), "cookie_secure", True):
        set_session_cookie(resp_prod, token="token_prod", max_age=3600, remember=True)
        cookie_header_prod = resp_prod.headers.get("set-cookie", "").lower()
        assert "samesite=none" in cookie_header_prod
        assert "secure" in cookie_header_prod

        clear_resp_prod = Response()
        clear_session_cookie(clear_resp_prod)
        clear_cookie_prod = clear_resp_prod.headers.get("set-cookie", "").lower()
        assert "samesite=none" in clear_cookie_prod
        assert "secure" in clear_cookie_prod


def test_telegram_webhook_secret_verification(client: TestClient):
    with patch.object(get_settings(), "telegram_webhook_secret", "expected-secret-token"):
        # Missing secret header -> 403
        r_missing = client.post("/api/telegram/webhook", json={"update_id": 100})
        assert r_missing.status_code == 403

        # Wrong secret header -> 403
        r_wrong = client.post(
            "/api/telegram/webhook",
            json={"update_id": 100},
            headers={"X-Telegram-Bot-Api-Secret-Token": "invalid-secret"},
        )
        assert r_wrong.status_code == 403

        # Correct secret header -> 200
        with patch("server.routers.telegram.runtime.spawn", side_effect=lambda coro: coro.close()) as mock_spawn:
            r_ok = client.post(
                "/api/telegram/webhook",
                json={"update_id": 100, "message": {"text": "hello"}},
                headers={"X-Telegram-Bot-Api-Secret-Token": "expected-secret-token"},
            )
            assert r_ok.status_code == 200
            assert r_ok.json() == {"ok": True}
            assert mock_spawn.called


def test_telegram_webhook_returns_200_quickly_on_invalid_json_or_errors(client: TestClient):
    with patch.object(get_settings(), "telegram_webhook_secret", "expected-secret-token"):
        # Malformed / empty payload should return 200 without throwing 500
        r = client.post(
            "/api/telegram/webhook",
            content=b"not valid json",
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": "expected-secret-token",
            },
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_set_webhook_called_only_in_webhook_mode():
    mock_app = MagicMock()
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.updater = MagicMock()
    mock_app.updater.start_polling = AsyncMock()
    mock_app.bot = MagicMock()
    mock_app.bot.set_webhook = AsyncMock()

    # Case A: Polling mode -> start_polling called, set_webhook NOT called
    with patch.object(bot_module, "build_telegram_app", return_value=mock_app):
        with patch.object(get_settings(), "telegram_mode", "polling"):
            await bot_module.start_telegram_service()
            assert mock_app.updater.start_polling.called
            assert not mock_app.bot.set_webhook.called

    mock_app.reset_mock()
    mock_app.updater.start_polling.reset_mock()
    mock_app.bot.set_webhook.reset_mock()

    # Case B: Webhook mode with valid settings -> set_webhook called
    with patch.object(bot_module, "build_telegram_app", return_value=mock_app):
        with patch.object(get_settings(), "telegram_mode", "webhook"), \
             patch.object(get_settings(), "telegram_webhook_url", "https://tripmate-backend.onrender.com"), \
             patch.object(get_settings(), "telegram_webhook_secret", "secret-key-xyz"):
            await bot_module.start_telegram_service()
            assert not mock_app.updater.start_polling.called
            assert mock_app.bot.set_webhook.called
            mock_app.bot.set_webhook.assert_awaited_once_with(
                url="https://tripmate-backend.onrender.com/api/telegram/webhook",
                secret_token="secret-key-xyz",
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"],
            )

    # Case C: Webhook mode with missing settings -> fails clearly at startup
    mock_app.reset_mock()
    with patch.object(bot_module, "build_telegram_app", return_value=mock_app):
        with patch.object(get_settings(), "telegram_mode", "webhook"), \
             patch.object(get_settings(), "telegram_webhook_url", ""):
            with pytest.raises(RuntimeError) as exc_info:
                await bot_module.start_telegram_service()
            assert "requires both TELEGRAM_WEBHOOK_URL and TELEGRAM_WEBHOOK_SECRET" in str(exc_info.value)
