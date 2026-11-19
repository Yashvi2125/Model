"""Unit and integration tests for Telegram bot adapter, identity mapping, and multi-platform sync."""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from server.db import SessionLocal
from server.models import Itinerary, Message, Trip, TripMember, User
from server.services.message_bus import (
    IncomingMessage,
    handle_incoming_message,
    set_telegram_sender,
)
from server.telegram.bot import chunk_message, escape_html
from server.telegram.identity import (
    bind_trip_to_chat,
    ensure_trip_member,
    get_or_create_telegram_user,
    get_trip_by_chat_id,
    get_trip_by_code,
)


def test_chunk_message_under_limit():
    short = "Hello world"
    assert chunk_message(short, max_size=100) == ["Hello world"]

    # Test long string split
    long_msg = "\n".join([f"Line {i}: Some detailed itinerary item information here." for i in range(100)])
    chunks = chunk_message(long_msg, max_size=500)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 500


def test_escape_html():
    raw = "<script>alert('xss');</script> & \"bold\""
    clean = escape_html(raw)
    assert "<script>" not in clean
    assert "&lt;script&gt;" in clean
    assert "&amp;" in clean


def test_telegram_identity_and_binding():
    with SessionLocal() as db_session:
        # 1. Telegram user creation
        u1 = get_or_create_telegram_user(db_session, tg_user_id=1234567, full_name="Alice TG", username="alice_tg")
        assert u1.email == "tg_1234567@telegram.user"
        assert u1.name == "Alice TG"

        # Idempotent retrieval
        u1_again = get_or_create_telegram_user(db_session, tg_user_id=1234567, full_name="Alice TG Updated")
        assert u1_again.id == u1.id
        assert u1_again.name == "Alice TG Updated"

        # 2. Trip creation & code lookup
        trip = Trip(
            name="Tokyo Test",
            code="TESTCODE",
            trip_code="TESTCODE",
            destination="Tokyo",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=5),
            travelers_count=2,
            owner_id=u1.id,
        )
        db_session.add(trip)
        db_session.commit()

        found = get_trip_by_code(db_session, "testcode")
        assert found is not None
        assert found.id == trip.id

        # 3. Group chat binding
        chat_id = -100987654321
        bind_trip_to_chat(db_session, trip, chat_id)
        assert get_trip_by_chat_id(db_session, chat_id).id == trip.id

        # 4. Member registration
        m = ensure_trip_member(db_session, trip.id, u1.id, tg_user_id=1234567, tg_username="alice_tg")
        assert m.channel_origin == "telegram"
        assert m.telegram_user_id == 1234567


@pytest.mark.asyncio
async def test_echo_loop_prevention_and_relay():
    from server import runtime
    runtime.set_loop(asyncio.get_running_loop())
    with SessionLocal() as db_session:
        u = get_or_create_telegram_user(db_session, tg_user_id=999, full_name="Bob")
        trip = Trip(
            name="Paris Test",
            code="PARIS123",
            trip_code="PARIS123",
            destination="Paris",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=4),
            owner_id=u.id,
            telegram_group_chat_id=-10011223344,
        )
        db_session.add(trip)
        db_session.commit()

    relayed_messages = []

    async def mock_tg_sender(chat_id, text):
        relayed_messages.append((chat_id, text))

    set_telegram_sender(mock_tg_sender)

    # 1. Message from Telegram -> should NOT echo back to Telegram sender
    tg_msg = IncomingMessage(
        trip_id=trip.id,
        user_id=u.id,
        channel="telegram",
        text="Bonjour from Telegram!",
        sender_name="Bob",
    )
    await handle_incoming_message(tg_msg)
    assert len(relayed_messages) == 0

    # 2. Message from Web -> should relay to Telegram group
    web_msg = IncomingMessage(
        trip_id=trip.id,
        user_id=u.id,
        channel="web",
        text="Hello from Web app!",
        sender_name="Alice (Web)",
    )
    await handle_incoming_message(web_msg)
    await asyncio.sleep(0.05)
    assert len(relayed_messages) == 1
    assert relayed_messages[0][0] == -10011223344
    assert "Hello from Web app!" in relayed_messages[0][1]


@pytest.mark.asyncio
async def test_multi_platform_same_trip():
    """Integration scenario: Two Telegram users + One web user join same trip and share itinerary."""
    with SessionLocal() as db_session:
        # Web owner creates trip
        web_owner = User(name="Web Organizer", email="owner@web.test", password_hash="hash")
        db_session.add(web_owner)
        db_session.commit()

        trip = Trip(
            name="Kyoto Multi-Platform",
            code="KYOTO888",
            trip_code="KYOTO888",
            destination="Kyoto",
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=15),
            travelers_count=3,
            owner_id=web_owner.id,
            telegram_group_chat_id=-100998877,
        )
        db_session.add(trip)
        db_session.flush()
        ensure_trip_member(db_session, trip.id, web_owner.id, role="owner")

        # Telegram user 1 joins via code
        tg_user1 = get_or_create_telegram_user(db_session, 1001, "Tanish TG", "tanishtg")
        ensure_trip_member(db_session, trip.id, tg_user1.id, tg_user_id=1001, tg_username="tanishtg")

        # Telegram user 2 joins via code
        tg_user2 = get_or_create_telegram_user(db_session, 1002, "Bhakti TG", "bhaktitg")
        ensure_trip_member(db_session, trip.id, tg_user2.id, tg_user_id=1002, tg_username="bhaktitg")

        # Verify all 3 members are in the trip
        members = db_session.scalars(select(TripMember).where(TripMember.trip_id == trip.id)).all()
        assert len(members) == 3

        # Add shared itinerary
        itin = Itinerary(
            trip_id=trip.id,
            version=1,
            status="succeeded",
            plan_markdown="## Day 1: Arrive in Kyoto\n- Visit Fushimi Inari\n- Dinner in Gion",
            days={"1": {"title": "Arrive in Kyoto"}},
        )
        db_session.add(itin)
        db_session.commit()

        # Verify latest itinerary is accessible by the trip
        latest = db_session.scalar(
            select(Itinerary).where(Itinerary.trip_id == trip.id, Itinerary.status == "succeeded")
        )
        assert latest.version == 1
        assert "Fushimi Inari" in latest.plan_markdown


def test_safe_web_button_filters_localhost():
    from server.telegram.bot import is_valid_telegram_button_url, safe_web_button

    assert not is_valid_telegram_button_url("http://localhost:3000/app/trips/1")
    assert not is_valid_telegram_button_url("http://127.0.0.1:8000/api")
    assert not is_valid_telegram_button_url("http://0.0.0.0:3000")
    assert not is_valid_telegram_button_url(None)
    assert not is_valid_telegram_button_url("")

    assert is_valid_telegram_button_url("https://tripmate.onrender.com/app/trips/1")
    assert is_valid_telegram_button_url("https://t.me/Tripmate_planner_bot?start=4VSE4K9Y")

    assert safe_web_button("Web", "http://localhost:3000/app/trips/1") is None
    btn = safe_web_button("Web", "https://tripmate.onrender.com/app/trips/1")
    assert btn is not None
    assert btn.text == "Web"
    assert btn.url == "https://tripmate.onrender.com/app/trips/1"


def test_argument_and_code_normalization():
    from server.telegram.bot import normalize_arg, normalize_trip_code

    # Angle brackets, quotes, whitespace
    assert normalize_arg("<Goa>") == "Goa"
    assert normalize_arg('"Goa"') == "Goa"
    assert normalize_arg("  <Goa>  ") == "Goa"
    assert normalize_arg("[Tokyo]") == "Tokyo"

    # Trip codes
    assert normalize_trip_code("<4VSE4K9Y>") == "4VSE4K9Y"
    assert normalize_trip_code("[4VSE4K9Y]") == "4VSE4K9Y"
    assert normalize_trip_code('"4vse4k9y"') == "4VSE4K9Y"
    assert normalize_trip_code("  4vse4k9y  ") == "4VSE4K9Y"
    assert normalize_trip_code("TRIP-4VSE4K9Y") == "TRIP-4VSE4K9Y"


@pytest.mark.asyncio
async def test_send_safe_reply_fallbacks():
    from server.telegram.bot import send_safe_reply
    from telegram import constants, InlineKeyboardMarkup, InlineKeyboardButton

    mock_msg = AsyncMock()
    mock_update = AsyncMock()
    mock_update.effective_message = mock_msg

    # 1. Successful HTML reply
    await send_safe_reply(mock_update, "<b>Hello</b>", None)
    mock_msg.reply_text.assert_called_with("<b>Hello</b>", parse_mode=constants.ParseMode.HTML, reply_markup=None)

    # 2. Markup failure -> retries without markup
    mock_msg.reply_text.reset_mock()
    mock_msg.reply_text.side_effect = [Exception("Bad markup"), AsyncMock()]
    fake_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Bad", callback_data="bad")]])
    await send_safe_reply(mock_update, "<b>Hello</b>", fake_kb)
    assert mock_msg.reply_text.call_count == 2
    mock_msg.reply_text.assert_called_with("<b>Hello</b>", parse_mode=constants.ParseMode.HTML, reply_markup=None)

    # 3. HTML parsing failure -> retries plain text without tags
    mock_msg.reply_text.reset_mock()
    mock_msg.reply_text.side_effect = [Exception("Bad entities"), Exception("Bad entities"), AsyncMock()]
    await send_safe_reply(mock_update, "<b>Unclosed tag", fake_kb)
    assert mock_msg.reply_text.call_count == 3
    mock_msg.reply_text.assert_called_with("Unclosed tag", parse_mode=None, reply_markup=None)


@pytest.mark.asyncio
async def test_global_error_handler():
    from server.telegram.bot import global_telegram_error_handler

    mock_msg = AsyncMock()
    mock_update = AsyncMock()
    mock_update.effective_message = mock_msg
    mock_context = AsyncMock()
    mock_context.error = ValueError("Unexpected boom!")

    await global_telegram_error_handler(mock_update, mock_context)
    mock_msg.reply_text.assert_called_once_with("Something went wrong, please try again.")


@pytest.mark.asyncio
async def test_private_chat_newtrip_and_jointrip():
    from server.telegram.bot import cmd_newtrip, cmd_jointrip
    from telegram import constants

    with SessionLocal() as db_session:
        # User in a private chat
        mock_user = AsyncMock()
        mock_user.id = 778899
        mock_user.full_name = "Private User"
        mock_user.username = "puser"
        mock_user.first_name = "Private"

        mock_chat = AsyncMock()
        mock_chat.id = 778899
        mock_chat.type = constants.ChatType.PRIVATE

        mock_msg = AsyncMock()
        mock_update = AsyncMock()
        mock_update.effective_user = mock_user
        mock_update.effective_chat = mock_chat
        mock_update.effective_message = mock_msg

        mock_context = AsyncMock()
        mock_context.args = ["<Goa>"]
        mock_context.user_data = {}

        # 1. /newtrip <Goa> in private chat
        await cmd_newtrip(mock_update, mock_context)

        # Confirm trip was created and active_trip_id set in user_data
        active_id = mock_context.user_data.get("active_trip_id")
        assert active_id is not None

        trip = db_session.get(Trip, active_id)
        assert trip is not None
        assert trip.destination == "Goa"
        # Confirm telegram_group_chat_id is NOT set in private chat
        assert trip.telegram_group_chat_id is None

        # Confirm reply sent
        assert mock_msg.reply_text.called
        reply_text = mock_msg.reply_text.call_args[0][0]
        assert "Trip Created Successfully!" in reply_text
        assert trip.code in reply_text

        # 2. /jointrip with same code -> already joined
        mock_msg.reply_text.reset_mock()
        mock_context.args = [f"<{trip.code}>"]
        await cmd_jointrip(mock_update, mock_context)
        assert mock_msg.reply_text.called
        reply_join = mock_msg.reply_text.call_args[0][0]
        assert "already a member" in reply_join.lower()

        # 3. /jointrip missing code
        mock_msg.reply_text.reset_mock()
        mock_context.args = []
        await cmd_jointrip(mock_update, mock_context)
        reply_missing = mock_msg.reply_text.call_args[0][0]
        assert "Please provide a trip code" in reply_missing

        # 4. /jointrip invalid/unknown code
        mock_msg.reply_text.reset_mock()
        mock_context.args = ["NONEXIST123"]
        await cmd_jointrip(mock_update, mock_context)
        reply_unknown = mock_msg.reply_text.call_args[0][0]
        assert "No trip found" in reply_unknown

