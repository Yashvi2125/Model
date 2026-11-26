"""Unit and integration tests for Telegram bot adapter, identity mapping, and multi-platform sync."""
import asyncio
from datetime import date, datetime, timedelta, timezone
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


# ==============================================================================
# SPECIFIC SCENARIO TESTS: ACCOUNT LINKING, MERGE, REBIND, RATE LIMIT, MIGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_shared_trip_merge():
    """Scenario 1: Shared trip merge - duplicate member row collapsed into web user."""
    from server.models import Trip, TripMember, User
    from server.services.account_link import generate_link_code, link_telegram_account

    with SessionLocal() as db:
        web_user = User(name="Alice Web", email="alice_shared@test.com", password_hash="h")
        db.add(web_user)
        db.commit()
        db.refresh(web_user)

        tg_id = 90001
        syn_user = User(name="Alice Synth", email=f"tg_{tg_id}@telegram.user", password_hash="h")
        db.add(syn_user)
        db.commit()
        db.refresh(syn_user)

        trip = Trip(
            name="Shared Trip", code="SHR01", start_date=date.today(),
            end_date=date.today() + timedelta(days=4), owner_id=web_user.id
        )
        db.add(trip)
        db.commit()

        m_web = TripMember(trip_id=trip.id, user_id=web_user.id, role="owner", channel_origin="web")
        m_syn = TripMember(trip_id=trip.id, user_id=syn_user.id, role="member", telegram_user_id=tg_id, channel_origin="telegram")
        db.add_all([m_web, m_syn])
        db.commit()

        code = generate_link_code(db, web_user.id)
        ok, msg, linked = link_telegram_account(db, code, tg_id, "alice_tg")
        assert ok, msg
        assert linked.telegram_user_id == tg_id

        # Synthetic user deleted
        assert db.get(User, syn_user.id) is None
        # Trip has exactly 1 member for Alice
        members = db.scalars(select(TripMember).where(TripMember.trip_id == trip.id)).all()
        assert len(members) == 1
        assert members[0].user_id == web_user.id
        assert members[0].telegram_user_id == tg_id


@pytest.mark.asyncio
async def test_unshared_trip_merge():
    """Scenario 2: Unshared trip merge - ownership and membership transferred to web user."""
    from server.models import Trip, TripMember, User
    from server.services.account_link import generate_link_code, link_telegram_account

    with SessionLocal() as db:
        web_user = User(name="Bob Web", email="bob_unshared@test.com", password_hash="h")
        db.add(web_user)
        db.commit()
        db.refresh(web_user)

        tg_id = 90002
        syn_user = User(name="Bob Synth", email=f"tg_{tg_id}@telegram.user", password_hash="h")
        db.add(syn_user)
        db.commit()
        db.refresh(syn_user)

        trip = Trip(
            name="Bob Solo Trip", code="SOLO02", start_date=date.today(),
            end_date=date.today() + timedelta(days=3), owner_id=syn_user.id
        )
        db.add(trip)
        db.commit()

        m_syn = TripMember(trip_id=trip.id, user_id=syn_user.id, role="owner", telegram_user_id=tg_id)
        db.add(m_syn)
        db.commit()

        code = generate_link_code(db, web_user.id)
        ok, msg, linked = link_telegram_account(db, code, tg_id, "bob_tg")
        assert ok, msg

        db.refresh(trip)
        assert trip.owner_id == web_user.id
        members = db.scalars(select(TripMember).where(TripMember.trip_id == trip.id)).all()
        assert len(members) == 1
        assert members[0].user_id == web_user.id


@pytest.mark.asyncio
async def test_both_have_preferences_merge():
    """Scenario 3: Both have preferences merge - keeps web row, fills empties, prefers newer on conflict."""
    from server.models import Preference, Trip, TripMember, User
    from server.services.account_link import generate_link_code, link_telegram_account

    with SessionLocal() as db:
        web_user = User(name="Carol Web", email="carol_pref@test.com", password_hash="h")
        db.add(web_user)
        db.commit()
        db.refresh(web_user)

        tg_id = 90003
        syn_user = User(name="Carol Synth", email=f"tg_{tg_id}@telegram.user", password_hash="h")
        db.add(syn_user)
        db.commit()
        db.refresh(syn_user)

        trip = Trip(
            name="Pref Merge Trip", code="PREF03", start_date=date.today(),
            end_date=date.today() + timedelta(days=5), owner_id=web_user.id
        )
        db.add(trip)
        db.commit()

        # Web preference has older updated_at
        pref_web = Preference(
            trip_id=trip.id, user_id=web_user.id, destination="Old City",
            interests=["hiking"], notes="Need quiet room",
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        # Synth preference has newer updated_at and extra fields
        pref_syn = Preference(
            trip_id=trip.id, user_id=syn_user.id, destination="New City",
            interests=["food"], budget_max=20000,
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db.add_all([pref_web, pref_syn])
        db.commit()

        code = generate_link_code(db, web_user.id)
        ok, msg, _ = link_telegram_account(db, code, tg_id)
        assert ok, msg

        # Only 1 preference row left, assigned to web_user
        prefs = db.scalars(select(Preference).where(Preference.trip_id == trip.id)).all()
        assert len(prefs) == 1
        p = prefs[0]
        assert p.user_id == web_user.id
        # Newer timestamp won the destination conflict
        assert p.destination == "New City"
        # Interests merged
        assert "hiking" in p.interests and "food" in p.interests
        # Backfilled budget_max
        assert p.budget_max == 20000
        # Retained notes
        assert p.notes == "Need quiet room"


@pytest.mark.asyncio
async def test_idempotent_relink():
    """Scenario 4: Idempotent re-link - linking same web user and tg_id again is a harmless no-op."""
    from server.models import User
    from server.services.account_link import generate_link_code, link_telegram_account

    with SessionLocal() as db:
        web_user = User(name="Dan Web", email="dan_relink@test.com", password_hash="h")
        db.add(web_user)
        db.commit()
        db.refresh(web_user)

        tg_id = 90004
        code1 = generate_link_code(db, web_user.id)
        ok1, _, _ = link_telegram_account(db, code1, tg_id)
        assert ok1

        # Second link with fresh code
        code2 = generate_link_code(db, web_user.id)
        ok2, msg2, _ = link_telegram_account(db, code2, tg_id)
        assert ok2
        assert "already linked" in msg2.lower()


@pytest.mark.asyncio
async def test_web_account_already_linked_to_different_telegram_id():
    """Scenario 5: Web account already linked to another Telegram ID rejects new link."""
    from server.models import User
    from server.services.account_link import generate_link_code, link_telegram_account

    with SessionLocal() as db:
        web_user = User(name="Eve Web", email="eve_diff_tg@test.com", password_hash="h", telegram_user_id=11111)
        db.add(web_user)
        db.commit()
        db.refresh(web_user)

        code = generate_link_code(db, web_user.id)
        ok, msg, _ = link_telegram_account(db, code, tg_user_id=22222)
        assert not ok
        assert "already linked to another telegram" in msg.lower()


@pytest.mark.asyncio
async def test_telegram_id_already_linked_to_different_web_account():
    """Scenario 6: Telegram ID already linked to another web account rejects second web account."""
    from server.models import User
    from server.services.account_link import generate_link_code, link_telegram_account

    with SessionLocal() as db:
        user_a = User(name="User A", email="usera@test.com", password_hash="h", telegram_user_id=33333)
        user_b = User(name="User B", email="userb@test.com", password_hash="h")
        db.add_all([user_a, user_b])
        db.commit()
        db.refresh(user_b)

        code = generate_link_code(db, user_b.id)
        ok, msg, _ = link_telegram_account(db, code, tg_user_id=33333)
        assert not ok
        assert "already linked to web user 'user a'" in msg.lower()


@pytest.mark.asyncio
async def test_cmd_link_group_rejection():
    """Scenario 7: /link in group refused for safety and deleted."""
    from telegram import constants
    from server.telegram.bot import cmd_link

    mock_msg = AsyncMock()
    mock_update = AsyncMock()
    mock_update.effective_user = AsyncMock(id=55555)
    mock_update.effective_chat = AsyncMock(id=-1008888, type=constants.ChatType.SUPERGROUP)
    mock_update.effective_message = mock_msg
    mock_update.message = mock_msg
    mock_context = AsyncMock(args=["SOMECODE"])

    await cmd_link(mock_update, mock_context)
    assert mock_msg.delete.called
    assert mock_msg.reply_text.called
    assert "private chat" in mock_msg.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_expired_link_code_rejected():
    """Scenario 8: Expired link code is rejected."""
    from server.models import TelegramLinkCode, User, utcnow
    from server.services.account_link import link_telegram_account

    with SessionLocal() as db:
        user = User(name="Frank", email="frank_exp@test.com", password_hash="h")
        db.add(user)
        db.commit()
        db.refresh(user)

        # Code expired 5 minutes ago
        code_rec = TelegramLinkCode(
            user_id=user.id,
            code="EXPIRE01",
            created_at=utcnow() - timedelta(minutes=15),
            expires_at=utcnow() - timedelta(minutes=5),
        )
        db.add(code_rec)
        db.commit()

        ok, msg, _ = link_telegram_account(db, "EXPIRE01", tg_user_id=44444)
        assert not ok
        assert "invalid or expired" in msg.lower()


@pytest.mark.asyncio
async def test_reused_link_code_rejected():
    """Scenario 9: Reused link code is rejected."""
    from server.models import TelegramLinkCode, User, utcnow
    from server.services.account_link import link_telegram_account

    with SessionLocal() as db:
        user = User(name="Grace", email="grace_reused@test.com", password_hash="h")
        db.add(user)
        db.commit()
        db.refresh(user)

        # Code already used
        code_rec = TelegramLinkCode(
            user_id=user.id,
            code="REUSED01",
            created_at=utcnow() - timedelta(minutes=5),
            expires_at=utcnow() + timedelta(minutes=5),
            used_at=utcnow() - timedelta(minutes=1),
        )
        db.add(code_rec)
        db.commit()

        ok, msg, _ = link_telegram_account(db, "REUSED01", tg_user_id=55555)
        assert not ok
        assert "invalid or expired" in msg.lower()


def test_lockout_after_five_failed_attempts():
    """Scenario 10: Lockout after 5 failed link attempts within 15 minutes."""
    from server.services.account_link import (
        clear_failed_attempts,
        is_rate_limited,
        link_telegram_account,
        record_failed_attempt,
    )

    tg_id = 7777777
    clear_failed_attempts(tg_id)
    assert not is_rate_limited(tg_id)

    # Record 5 failures
    for _ in range(5):
        record_failed_attempt(tg_id)
    assert is_rate_limited(tg_id)

    with SessionLocal() as db:
        ok, msg, _ = link_telegram_account(db, "ANYCODE", tg_user_id=tg_id)
        assert not ok
        assert "too many" in msg.lower()
    clear_failed_attempts(tg_id)


@pytest.mark.asyncio
async def test_group_rebind_notifications():
    """Scenario 11: Group rebind notice when a group connects to a new trip or a trip moves groups."""
    from server.models import Trip, User
    from server.telegram.bot import cmd_jointrip
    from telegram import constants

    with SessionLocal() as db:
        u = User(name="Rebind Owner", email="rebind@test.com", password_hash="h")
        db.add(u)
        db.commit()

        trip_a = Trip(name="Old Trip", code="OLD01", start_date=date.today(), end_date=date.today() + timedelta(days=2), owner_id=u.id, telegram_group_chat_id=-100555)
        trip_b = Trip(name="New Trip", code="NEW02", start_date=date.today(), end_date=date.today() + timedelta(days=2), owner_id=u.id)
        db.add_all([trip_a, trip_b])
        db.commit()
        db.refresh(trip_b)

        # Bot joins group -100555 with trip_b's code (switching from trip_a)
        mock_msg = AsyncMock()
        mock_update = AsyncMock()
        mock_update.effective_user = AsyncMock(id=99999, full_name="User", username="u")
        mock_update.effective_chat = AsyncMock(id=-100555, type=constants.ChatType.SUPERGROUP)
        mock_update.effective_message = mock_msg
        mock_context = AsyncMock(args=["NEW02"], user_data={})

        await cmd_jointrip(mock_update, mock_context)
        assert mock_msg.reply_text.called
        reply = mock_msg.reply_text.call_args[0][0]
        # Notice that group switched from Old Trip to New Trip
        assert "previously connected to 'Old Trip'" in reply


def test_relay_rate_limiter():
    """Scenario 12: Web-to-telegram relay rate limiter (max 5 per 10s) and feature flag."""
    from server.services.message_bus import check_can_relay, _relay_history

    trip_id = 88888
    _relay_history[trip_id] = []

    # First 5 messages within sliding window allowed
    for _ in range(5):
        assert check_can_relay(trip_id) is True

    # 6th message in same window is rate limited
    assert check_can_relay(trip_id) is False


@pytest.mark.asyncio
async def test_supergroup_migration():
    """Scenario 13: Supergroup migration updates telegram_group_chat_id."""
    from server.models import Trip, User
    from server.telegram.bot import handle_chat_migration

    with SessionLocal() as db:
        u = User(name="Mig Owner", email="mig_owner@test.com", password_hash="h")
        db.add(u)
        db.commit()
        trip = Trip(
            name="Mig Trip", code="MIG99", start_date=date.today(),
            end_date=date.today() + timedelta(days=2), owner_id=u.id,
            telegram_group_chat_id=-100111222,
        )
        db.add(trip)
        db.commit()
        db.refresh(trip)

        mock_msg = AsyncMock()
        mock_msg.migrate_from_chat_id = -100111222
        mock_msg.migrate_to_chat_id = -100999888
        mock_update = AsyncMock(message=mock_msg)
        mock_context = AsyncMock()

        await handle_chat_migration(mock_update, mock_context)

        db.refresh(trip)
        assert trip.telegram_group_chat_id == -100999888


# ==============================================================================
# WEB ENDPOINT TO TELEGRAM RELAY INTEGRATION TESTS
# ==============================================================================

def test_web_chat_endpoint_triggers_telegram_relay(user_a):
    """POST /api/trips/{id}/messages triggers the registered Telegram relay function."""
    import time
    from tests.web.conftest import make_trip
    from server.services.message_bus import set_telegram_sender, _relay_history

    t = make_trip(user_a)
    trip_id = t["id"]
    _relay_history[trip_id] = []

    # Bind group chat ID in DB
    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        trip.telegram_group_chat_id = -100998877
        db.commit()

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)

    res = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": "Hello from web planner!"})
    assert res.status_code == 201
    msg_data = res.json()
    assert msg_data["content"] == "Hello from web planner!"

    # Wait briefly for background task
    time.sleep(0.1)
    assert len(relayed) == 1
    chat_id, text = relayed[0]
    assert chat_id == -100998877
    assert "Asha Patel (via web)" in text
    assert "Hello from web planner!" in text


def test_web_chat_relay_skipped_when_flag_false(user_a, monkeypatch):
    """Relay is skipped when RELAY_WEB_TO_TELEGRAM is false."""
    import time
    from tests.web.conftest import make_trip
    from server.config import get_settings
    from server.services.message_bus import set_telegram_sender, _relay_history

    t = make_trip(user_a)
    trip_id = t["id"]
    _relay_history[trip_id] = []

    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        trip.telegram_group_chat_id = -100998877
        db.commit()

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)
    monkeypatch.setattr(get_settings(), "relay_web_to_telegram", False)

    res = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": "Should not relay"})
    assert res.status_code == 201
    time.sleep(0.05)
    assert len(relayed) == 0


def test_web_chat_relay_skipped_when_no_group(user_a):
    """Relay is skipped when the trip has no bound Telegram group."""
    import time
    from tests.web.conftest import make_trip
    from server.services.message_bus import set_telegram_sender

    t = make_trip(user_a)
    trip_id = t["id"]

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)

    res = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": "No group trip message"})
    assert res.status_code == 201
    time.sleep(0.05)
    assert len(relayed) == 0


def test_web_chat_relay_rate_limited_after_5_messages(user_a):
    """Web messages beyond 5 per 10s are dropped for Telegram, but still saved on web."""
    import time
    from tests.web.conftest import make_trip
    from server.services.message_bus import set_telegram_sender, _relay_history

    t = make_trip(user_a)
    trip_id = t["id"]
    _relay_history[trip_id] = []

    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        trip.telegram_group_chat_id = -100998877
        db.commit()

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)

    # First 5 messages
    for i in range(5):
        r = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": f"Msg {i}"})
        assert r.status_code == 201

    time.sleep(0.1)
    assert len(relayed) == 5

    # 6th message should be saved (201) but not relayed to Telegram
    r6 = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": "Msg 6 (rate limited)"})
    assert r6.status_code == 201
    time.sleep(0.1)
    assert len(relayed) == 5  # No extra relay

    # Verify message 6 is persisted in database
    with SessionLocal() as db:
        saved = db.scalars(select(Message).where(Message.trip_id == trip_id, Message.content == "Msg 6 (rate limited)")).first()
        assert saved is not None


def test_web_chat_relay_escapes_html_special_characters(user_a):
    """Relay HTML escapes user name and message text (e.g. <b> and &)."""
    import time
    from tests.web.conftest import make_trip
    from server.services.message_bus import set_telegram_sender, _relay_history

    t = make_trip(user_a)
    trip_id = t["id"]
    _relay_history[trip_id] = []

    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        trip.telegram_group_chat_id = -100998877
        db.commit()

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)

    raw_msg = "<script>alert('xss')</script> & <b>bold text</b>"
    res = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": raw_msg})
    assert res.status_code == 201
    time.sleep(0.1)

    assert len(relayed) == 1
    chat_id, text = relayed[0]
    # Check that angle brackets and ampersands are escaped in the body
    assert "&lt;script&gt;" in text
    assert "&lt;b&gt;bold text&lt;/b&gt;" in text
    assert "&amp;" in text
    # The only raw HTML allowed is the bot's own formatting tags: <b>...</b>
    assert not text.endswith("<b>bold text</b>")


def test_web_chat_relay_task_failure_does_not_affect_web_response(user_a):
    """If Telegram sender fails/raises, the web response is still 201 and message is saved."""
    import time
    from tests.web.conftest import make_trip
    from server.services.message_bus import set_telegram_sender, _relay_history

    t = make_trip(user_a)
    trip_id = t["id"]
    _relay_history[trip_id] = []

    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        trip.telegram_group_chat_id = -100998877
        db.commit()

    async def failing_sender(chat_id, text):
        raise RuntimeError("Simulated Telegram API network connection failure")

    set_telegram_sender(failing_sender)

    res = user_a.post(f"/api/trips/{trip_id}/messages", json={"content": "Important saved message"})
    assert res.status_code == 201
    time.sleep(0.1)

    # Message exists in DB
    with SessionLocal() as db:
        saved = db.scalars(select(Message).where(Message.trip_id == trip_id, Message.content == "Important saved message")).first()
        assert saved is not None


def test_markdown_to_telegram_html_conversion():
    from server.services.message_bus import markdown_to_telegram_html

    # Bold and Italic
    res = markdown_to_telegram_html("Here is **bold** and *italic* and `code`.")
    assert "<b>bold</b>" in res
    assert "<i>italic</i>" in res
    assert "<code>code</code>" in res

    # Escaped raw HTML
    res2 = markdown_to_telegram_html("Fish & chips < 500 yen > 100 yen.")
    assert "&amp;" in res2
    assert "&lt; 500" in res2
    assert "&gt; 100" in res2

    # Headings and bullets
    res3 = markdown_to_telegram_html("## Day 1: Tokyo\n- Visit Senso-ji\n* Eat Ramen")
    assert "<b>Day 1: Tokyo</b>" in res3
    assert "• Visit Senso-ji" in res3
    assert "• Eat Ramen" in res3

    # Links
    res4 = markdown_to_telegram_html("[Google](https://google.com)")
    assert '<a href="https://google.com">Google</a>' in res4

    # Code blocks
    res5 = markdown_to_telegram_html("```python\nprint('hello')\n```")
    assert "<pre><code>" in res5


@pytest.mark.asyncio
async def test_ai_reply_relayed_with_ai_label_and_no_via_web():
    from server import runtime
    runtime.set_loop(asyncio.get_running_loop())
    from server.services.chat_ai import _post
    from server.services.message_bus import set_telegram_sender, _relay_history

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)

    with SessionLocal() as db:
        u = get_or_create_telegram_user(db, tg_user_id=987654, full_name="Test AI User")
        t = Trip(
            name="AI Sync Test",
            code="AISYNC01",
            trip_code="AISYNC01",
            destination="Kyoto",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=3),
            owner_id=u.id,
            telegram_group_chat_id=-10022334455,
        )
        db.add(t)
        db.commit()
        trip_id = t.id

    _relay_history[trip_id] = []

    # Post an AI reply via chat_ai._post
    ai_text = "Here is your plan for **Day 1**: Visit Kinkaku-ji with budget < ¥2000 & cash only!"
    _post(trip_id, "ai", ai_text, {})
    await asyncio.sleep(0.05)

    assert len(relayed) == 1
    chat_id, body = relayed[0]
    assert chat_id == -10022334455
    # Must use MileMates AI label, NOT '(via web)'
    assert "🤖 <b>MileMates AI:</b>" in body
    assert "(via web)" not in body
    # Markdown converted and raw HTML escaped
    assert "<b>Day 1</b>" in body
    assert "&lt; ¥2000" in body
    assert "&amp;" in body


@pytest.mark.asyncio
async def test_ai_reply_chunked_under_4096_chars():
    from server.telegram.bot import chunk_message

    # Generate a long message exceeding 4096 chars
    long_plan = "\n\n".join([f"**Section {i}**: Plan details with comprehensive sightseeing and hotel recommendations." for i in range(70)])
    assert len(long_plan) > 5000

    chunks = chunk_message(long_plan, max_size=4000)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 4000


@pytest.mark.asyncio
async def test_telegram_user_own_message_never_echoed():
    from server import runtime
    runtime.set_loop(asyncio.get_running_loop())
    from server.services.message_bus import set_telegram_sender, _relay_history

    relayed = []

    async def mock_sender(chat_id, text):
        relayed.append((chat_id, text))

    set_telegram_sender(mock_sender)

    with SessionLocal() as db:
        u = get_or_create_telegram_user(db, tg_user_id=876543, full_name="Telegram Sender")
        t = Trip(
            name="No Echo Test",
            code="NOECHO01",
            trip_code="NOECHO01",
            destination="Osaka",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=2),
            owner_id=u.id,
            telegram_group_chat_id=-10033445566,
        )
        db.add(t)
        db.commit()
        trip_id = t.id

    _relay_history[trip_id] = []

    # Telegram user sends a regular message
    msg = IncomingMessage(
        trip_id=trip_id,
        user_id=u.id,
        channel="telegram",
        text="Hello group, I love ramen!",
        sender_name="TelegramUser",
    )
    await handle_incoming_message(msg)
    await asyncio.sleep(0.05)

    # Telegram sender must NOT have received an echo
    assert len(relayed) == 0




