"""MileMates Telegram Group & DM Bot powered by Google ADK and Gemini."""
import asyncio
from datetime import date, datetime, timedelta
import html
import logging
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message as TGMessage,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from server import runtime
from server.ai.adk_agent import ask_adk_advisor
from server.config import get_settings
from server.db import SessionLocal
from server.models import Conflict, Itinerary, Preference, Trip, TripMember, User, utcnow
from server.routers.trips import new_code, normalise_code
from server.services import itinerary_service as itin_svc
from server.services import messages as msgs
from server.services import preferences as pref_svc
from server.services.budget import compute_budget
from server.services.account_link import link_telegram_account
from server.services.message_bus import (
    IncomingMessage,
    get_trip_lock,
    handle_incoming_message,
    set_telegram_sender,
)
from server.services.realtime import publish
from server.telegram.identity import (
    bind_trip_to_chat,
    ensure_trip_member,
    get_or_create_telegram_user,
    get_trip_by_chat_id,
    get_trip_by_code,
)
from server.telegram.telegraph import publish_itinerary_page

log = logging.getLogger("tripmate.telegram")

_bot_app: Optional[Application] = None


# --- Helpers & Sanitizers -----------------------------------------------------

def escape_html(text: str) -> str:
    """Safely escapes text for Telegram HTML mode."""
    if not text:
        return ""
    return html.escape(str(text))


def is_valid_telegram_button_url(url: Optional[str]) -> bool:
    """Telegram inline keyboard button URLs must be public HTTP/HTTPS or tg:// links.
    Localhost, 127.0.0.1, and private IPs are rejected by Telegram Bot API with 400 Bad Request.
    """
    if not url:
        return False
    u = url.strip().lower()
    if not (u.startswith("https://") or u.startswith("http://") or u.startswith("tg://")):
        return False
    if "localhost" in u or "127.0.0.1" in u or "0.0.0.0" in u:
        return False
    return True


def safe_web_button(text: str, url: Optional[str]) -> Optional[InlineKeyboardButton]:
    """Creates an InlineKeyboardButton only if the URL is valid for Telegram inline buttons."""
    if url and is_valid_telegram_button_url(url):
        return InlineKeyboardButton(text, url=url.strip())
    return None


def normalize_arg(text: Optional[str]) -> str:
    """Strips wrapping < >, [ ], ( ), quotes, and leading/trailing whitespace."""
    if not text:
        return ""
    val = text.strip()
    while val and (val[0] in "<[(\"'" or val[-1] in ">])\"'"):
        val = val.strip("<>[()]\"'").strip()
    return val


def normalize_trip_code(code: Optional[str]) -> str:
    """Normalizes a trip code: strips wrappers, whitespace, and uppercases."""
    raw = normalize_arg(code)
    return "".join(ch for ch in raw.upper() if ch.isalnum() or ch == "-")


async def send_typing_action(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    except Exception:
        pass


def chunk_message(text: str, max_size: int = 4000) -> list[str]:
    """Splits long text to strictly avoid Telegram's 4096 character limit."""
    if len(text) <= max_size:
        return [text]
    chunks = []
    lines = text.split("\n")
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > max_size:
            if current:
                chunks.append(current.strip())
                current = ""
            if len(line) > max_size:
                for i in range(0, len(line), max_size):
                    chunks.append(line[i : i + max_size])
            else:
                current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


async def send_safe_reply(
    update: Update,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = constants.ParseMode.HTML,
) -> Optional[TGMessage]:
    """Safely replies to a message.
    If HTML parsing or reply_markup fails, retries without markup, then plain text.
    Guarantees the command never silently ends without attempting to inform the user.
    """
    if not update.effective_message:
        return None
    msg = update.effective_message
    try:
        return await msg.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as exc1:
        log.warning("send_safe_reply failed with markup/HTML (%s). Retrying without markup...", exc1)
        try:
            return await msg.reply_text(text, parse_mode=parse_mode, reply_markup=None)
        except Exception as exc2:
            log.warning("send_safe_reply failed with HTML (%s). Retrying as plain text...", exc2)
            try:
                clean = re.sub(r"<[^>]+>", "", text)
                return await msg.reply_text(clean, parse_mode=None, reply_markup=None)
            except Exception as exc3:
                log.error("send_safe_reply completely failed to deliver reply: %s", exc3)
                return None


def get_effective_trip(
    db: Session, update: Update, context: Optional[ContextTypes.DEFAULT_TYPE] = None
) -> Optional[Trip]:
    """Resolves the active Trip for the current context.
    - In group/supergroup: looks up strictly by telegram_group_chat_id.
    - In private chat:
        1. Checks context.user_data['active_trip_id'] if present and valid.
        2. Falls back to the latest trip where the user is a registered member.
    """
    chat = update.effective_chat
    if not chat:
        return None
    if chat.type in (constants.ChatType.GROUP, constants.ChatType.SUPERGROUP):
        return get_trip_by_chat_id(db, chat.id)

    tg_user = update.effective_user
    if not tg_user:
        return None

    # Check context.user_data in private chat
    if context and context.user_data:
        active_id = context.user_data.get("active_trip_id")
        if active_id:
            t = db.get(Trip, active_id)
            if t:
                return t

    # Fallback to user's latest trip membership
    user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
    latest_membership = db.scalar(
        select(TripMember)
        .where((TripMember.user_id == user.id) | (TripMember.telegram_user_id == tg_user.id))
        .order_by(TripMember.id.desc())
    )
    if latest_membership:
        t = db.get(Trip, latest_membership.trip_id)
        if t and context and context.user_data is not None:
            context.user_data["active_trip_id"] = t.id
        return t

    return None


# --- Global Error Handler ----------------------------------------------------

async def global_telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler for all unhandled bot exceptions.
    Logs the full traceback server-side and guarantees a user-facing reply.
    """
    exc = context.error
    log.error("Unhandled exception in Telegram bot: %s", exc, exc_info=exc)
    if hasattr(update, "effective_message") and update.effective_message:
        try:
            await update.effective_message.reply_text("Something went wrong, please try again.")
        except Exception as send_err:
            log.error("Failed to deliver error message to user: %s", send_err)


# --- Telegram Command Handlers ------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start, including deep-link trip joins: /start <TRIP_CODE>."""
    if not update.effective_user or not update.effective_chat:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    settings = get_settings()

    log.info("CMD /start user_id=%s chat_id=%s (type=%s)", tg_user.id, chat_id, chat_type)

    with SessionLocal() as db:
        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)

        # Check deep link payload (e.g. /start 4VSE4K9Y)
        raw_payload = context.args[0].strip() if context.args else None
        payload = normalize_trip_code(raw_payload) if raw_payload else None
        if payload:
            trip = get_trip_by_code(db, payload)
            if trip:
                ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username)
                if chat_type in (constants.ChatType.GROUP, constants.ChatType.SUPERGROUP):
                    bind_trip_to_chat(db, trip, chat_id)
                elif context.user_data is not None:
                    context.user_data["active_trip_id"] = trip.id

                web_url = f"{settings.public_base_url}/app/trips/{trip.id}"
                rows = []
                btn = safe_web_button("🌐 Open Web Dashboard", web_url)
                if btn:
                    rows.append([btn])
                rows.append([InlineKeyboardButton("📋 View Itinerary", callback_data=f"itin_{trip.id}")])
                keyboard = InlineKeyboardMarkup(rows) if rows else None

                reply = (
                    f"🎉 <b>Welcome to Trip '{escape_html(trip.name)}'!</b>\n\n"
                    f"📍 <b>Destination:</b> {escape_html(trip.destination or 'Undecided')}\n"
                    f"📅 <b>Dates:</b> {trip.start_date} to {trip.end_date}\n"
                    f"🔑 <b>Trip Code:</b> <code>{trip.code}</code>\n"
                    f"🌐 <b>Web Dashboard:</b> {web_url}\n\n"
                    f"You have joined the trip. Chat here naturally to share preferences, or use /plan to generate an itinerary!"
                )
                await send_safe_reply(update, reply, reply_markup=keyboard)
                return

    help_text = (
        f"👋 <b>Hello {escape_html(tg_user.first_name)}! Welcome to MileMates AI.</b>\n\n"
        "I am your collaborative travel planning companion powered by Google ADK & Gemini.\n\n"
        "<b>Available Commands:</b>\n"
        "• <code>/newtrip Goa</code> - Create a new trip\n"
        "• <code>/jointrip 4VSE4K9Y</code> - Connect to an existing trip\n"
        "• <code>/status</code> - Check planning progress & member preferences\n"
        "• <code>/members</code> - List everyone in the trip\n"
        "• <code>/plan</code> - Generate a complete multi-agent itinerary\n"
        "• <code>/itinerary</code> - View the latest saved trip plan\n"
        "• <code>/budget</code> - View the estimated budget breakdown\n"
        "• <code>/link CODE</code> - Link to your web account\n"
        "• <code>/weblink</code> - Direct link to the web interface\n\n"
        "<i>Plan directly here in DM, or add me to your group and plan together!</i>"
    )
    await send_safe_reply(update, help_text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_newtrip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a new trip and sets it active."""
    if not update.effective_user or not update.effective_chat:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    settings = get_settings()

    raw_args = " ".join(context.args).strip() if context.args else ""
    destination = normalize_arg(raw_args) or "Undecided"
    s_date = date.today() + timedelta(days=14)
    e_date = s_date + timedelta(days=5)

    is_group = chat_type in (constants.ChatType.GROUP, constants.ChatType.SUPERGROUP)

    with SessionLocal() as db:
        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        code = new_code(db)
        trip = Trip(
            name=f"{destination} Adventure"[:120],
            destination=destination[:120],
            code=code,
            trip_code=code,
            start_date=s_date,
            end_date=e_date,
            travelers_count=2,
            owner_id=user.id,
            telegram_group_chat_id=chat_id if is_group else None,
        )
        db.add(trip)
        db.flush()
        ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username, role="owner")
        pref_svc.seed_from_trip(db, trip, user.id)
        db.commit()

        if context.user_data is not None:
            context.user_data["active_trip_id"] = trip.id

        bot_username = (settings.telegram_bot_username or "").lstrip("@")
        deep_link = f"https://t.me/{bot_username}?start={trip.code}" if bot_username else None
        web_url = f"{settings.public_base_url}/app/trips/{trip.id}"

        rows = []
        btn = safe_web_button("🌐 Open Web Dashboard", web_url)
        if btn:
            rows.append([btn])
        if deep_link:
            s_btn = safe_web_button("🔗 Share Invite Link", deep_link)
            if s_btn:
                rows.append([s_btn])
        keyboard = InlineKeyboardMarkup(rows) if rows else None

        scope_msg = (
            f"This group is now connected to the trip! Friends can join with <code>/jointrip {trip.code}</code>."
            if is_group
            else f"This is now your active trip. Invite friends to join using code <code>{trip.code}</code>."
        )

        reply = (
            f"🚀 <b>Trip Created Successfully!</b>\n\n"
            f"🏷 <b>Trip:</b> {escape_html(trip.name)}\n"
            f"📍 <b>Destination:</b> {escape_html(trip.destination)}\n"
            f"📅 <b>Dates:</b> {trip.start_date} to {trip.end_date} (default 6 days)\n"
            f"🔑 <b>Trip Code:</b> <code>{trip.code}</code>\n"
            f"🌐 <b>Web Dashboard:</b> {web_url}\n\n"
            f"{scope_msg}"
        )
        log.info(
            "CMD /newtrip trip_id=%s code=%s user_id=%s is_group=%s outcome=created",
            trip.id,
            trip.code,
            tg_user.id,
            is_group,
        )
        await send_safe_reply(update, reply, reply_markup=keyboard)


async def cmd_jointrip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Binds group/user to an existing trip code."""
    if not update.effective_user or not update.effective_chat:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    settings = get_settings()

    if not context.args:
        log.info("CMD /jointrip missing code from user_id=%s", tg_user.id)
        await send_safe_reply(
            update,
            "⚠️ Please provide a trip code:\n<code>/jointrip 4VSE4K9Y</code>",
        )
        return

    raw_code = " ".join(context.args).strip()
    code = normalize_trip_code(raw_code)
    if not code:
        log.info("CMD /jointrip invalid code from user_id=%s (raw=%s)", tg_user.id, raw_code)
        await send_safe_reply(
            update,
            "⚠️ Please provide a valid trip code:\n<code>/jointrip 4VSE4K9Y</code>",
        )
        return

    is_group = chat_type in (constants.ChatType.GROUP, constants.ChatType.SUPERGROUP)

    with SessionLocal() as db:
        trip = get_trip_by_code(db, code)
        if not trip:
            log.info("CMD /jointrip code=%s NOT_FOUND for user_id=%s", code, tg_user.id)
            await send_safe_reply(
                update,
                f"❌ No trip found with code <code>{escape_html(code)}</code>.\nPlease check the code and try again.",
            )
            return

        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        existing_member = db.scalar(
            select(TripMember).where(
                TripMember.trip_id == trip.id,
                (TripMember.user_id == user.id) | (TripMember.telegram_user_id == tg_user.id),
            )
        )
        was_already_member = existing_member is not None
        ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username)

        # Bind group chat if in a group with rebind detection
        rebind_notices = []
        if is_group:
            prev_bound_trip = db.scalar(
                select(Trip).where(Trip.telegram_group_chat_id == chat_id, Trip.id != trip.id)
            )
            if prev_bound_trip:
                rebind_notices.append(
                    f"ℹ️ <i>Notice: This group was previously connected to '{escape_html(prev_bound_trip.name)}'. "
                    f"It has now been switched to '{escape_html(trip.name)}'.</i>"
                )
            if trip.telegram_group_chat_id and trip.telegram_group_chat_id != chat_id:
                rebind_notices.append(
                    "ℹ️ <i>Notice: This trip was previously linked to another Telegram chat. "
                    "It is now bound to this group.</i>"
                )
            bind_trip_to_chat(db, trip, chat_id)

        # Always record as active trip in user_data
        if context.user_data is not None:
            context.user_data["active_trip_id"] = trip.id

        web_url = f"{settings.public_base_url}/app/trips/{trip.id}"
        rows = []
        btn = safe_web_button("🌐 Open Web Dashboard", web_url)
        if btn:
            rows.append([btn])
        rows.append([InlineKeyboardButton("📋 View Itinerary", callback_data=f"itin_{trip.id}")])
        keyboard = InlineKeyboardMarkup(rows) if rows else None

        if was_already_member:
            status_heading = f"ℹ️ <b>You are already a member of '{escape_html(trip.name)}'!</b>"
            scope_notice = (
                "This trip is now connected to this group."
                if is_group
                else "This trip is set as your active trip."
            )
        else:
            status_heading = f"✅ <b>Connected to '{escape_html(trip.name)}'!</b>"
            scope_notice = (
                "All group messages will now sync with the web planner."
                if is_group
                else "This trip is now your active trip. Use /status or /itinerary to check details."
            )

        reply_parts = [
            f"{status_heading}\n",
            f"📍 <b>Destination:</b> {escape_html(trip.destination or 'Undecided')}",
            f"📅 <b>Dates:</b> {trip.start_date} to {trip.end_date}",
            f"🔑 <b>Trip Code:</b> <code>{trip.code}</code>",
            f"👥 <b>Total Members:</b> {len(trip.members)}",
            f"🌐 <b>Web Dashboard:</b> {web_url}\n",
            scope_notice,
        ]
        if rebind_notices:
            reply_parts.extend(["", *rebind_notices])
        reply = "\n".join(reply_parts)
        log.info(
            "CMD /jointrip trip_id=%s code=%s user_id=%s was_member=%s is_group=%s outcome=success",
            trip.id,
            trip.code,
            tg_user.id,
            was_already_member,
            is_group,
        )
        await send_safe_reply(update, reply, reply_markup=keyboard)


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Links a Telegram account to a MileMates web account using a one-time code.
    Private chat only for security. Deletes the /link message immediately.
    """
    if not update.effective_user or not update.effective_chat:
        return
    chat_type = update.effective_chat.type
    is_private = chat_type == constants.ChatType.PRIVATE

    # Delete message immediately so the link code doesn't stay in chat history
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

    # Reject if called in a group
    if not is_private:
        await send_safe_reply(
            update,
            "🔒 <b>For your safety, send <code>/link</code> in a private chat with me.</b>",
        )
        return

    if not context.args:
        await send_safe_reply(
            update,
            "⚠️ Please provide your link code from the web app:\n<code>/link YOUR_CODE</code>\n\n"
            "<i>Visit your Profile on the web dashboard to generate a one-time link code.</i>",
        )
        return

    raw_code = " ".join(context.args).strip()
    tg_user = update.effective_user

    with SessionLocal() as db:
        success, reply_text, _ = link_telegram_account(
            db=db,
            code_str=raw_code,
            tg_user_id=tg_user.id,
            tg_username=tg_user.username,
            tg_full_name=tg_user.full_name,
        )

    await send_safe_reply(update, reply_text)


async def cmd_weblink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns direct web link for the current trip."""
    if not update.effective_chat or not update.effective_user:
        return
    log.info("CMD /weblink user_id=%s", update.effective_user.id)
    with SessionLocal() as db:
        trip = get_effective_trip(db, update, context)
        if not trip:
            await send_safe_reply(
                update,
                "⚠️ No active trip found. Join one with <code>/jointrip 4VSE4K9Y</code> or create one with <code>/newtrip Goa</code>.",
            )
            return
        web_url = f"{get_settings().public_base_url}/app/trips/{trip.id}"
        btn = safe_web_button("🌐 Open Web App", web_url)
        keyboard = InlineKeyboardMarkup([[btn]]) if btn else None
        await send_safe_reply(
            update,
            f"🌐 <b>Web Dashboard for '{escape_html(trip.name)}':</b>\n{web_url}",
            reply_markup=keyboard,
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows collected preferences and planning readiness."""
    if not update.effective_chat or not update.effective_user:
        return
    log.info("CMD /status user_id=%s", update.effective_user.id)
    with SessionLocal() as db:
        trip = get_effective_trip(db, update, context)
        if not trip:
            await send_safe_reply(
                update,
                "⚠️ No active trip found. Join one with <code>/jointrip 4VSE4K9Y</code> or create one with <code>/newtrip Goa</code>.",
            )
            return

        rows = pref_svc.member_prefs(db, trip.id)
        conflicts = db.scalars(
            select(Conflict).where(Conflict.trip_id == trip.id, Conflict.status == "open")
        ).all()
        itin = db.scalar(
            select(Itinerary)
            .where(Itinerary.trip_id == trip.id, Itinerary.status == "succeeded")
            .order_by(Itinerary.version.desc())
        )

        lines = [
            f"📊 <b>Status for '{escape_html(trip.name)}'</b> (Code: <code>{trip.code}</code>)",
            f"📍 <b>Destination:</b> {escape_html(trip.destination or 'Undecided')}",
            f"👥 <b>Members ({len(trip.members)}):</b>",
        ]
        for u, p in rows:
            interests = ", ".join(p.interests[:3]) if p and p.interests else "None yet"
            budget = f"Up to {p.budget_max}" if p and p.budget_max else "Flexible"
            lines.append(f"• <b>{escape_html(u.name)}</b>: {interests} | Budget: {budget}")

        lines.append(f"\n⚡ <b>Open Disagreements:</b> {len(conflicts)}")
        lines.append(f"🗺 <b>Itinerary:</b> {'v' + str(itin.version) + ' Ready' if itin else 'Not generated yet (use /plan)'}")
        web_url = f"{get_settings().public_base_url}/app/trips/{trip.id}"
        lines.append(f"🌐 <b>Dashboard:</b> {web_url}")

        btn = safe_web_button("🌐 View on Web", web_url)
        keyboard = InlineKeyboardMarkup([[btn]]) if btn else None
        await send_safe_reply(update, "\n".join(lines), reply_markup=keyboard)


async def cmd_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists trip members and platform origins."""
    if not update.effective_chat or not update.effective_user:
        return
    log.info("CMD /members user_id=%s", update.effective_user.id)
    with SessionLocal() as db:
        trip = get_effective_trip(db, update, context)
        if not trip:
            await send_safe_reply(
                update,
                "⚠️ No active trip found. Join one with <code>/jointrip 4VSE4K9Y</code> or create one with <code>/newtrip Goa</code>.",
            )
            return

        members = db.scalars(
            select(TripMember).where(TripMember.trip_id == trip.id).order_by(TripMember.joined_at)
        ).all()
        lines = [f"👥 <b>Members of '{escape_html(trip.name)}' ({len(members)}):</b>"]
        for m in members:
            origin = "📱 Telegram" if m.channel_origin == "telegram" or m.telegram_user_id else "💻 Web"
            role = " (Organiser)" if m.role == "owner" else ""
            uname = f" (@{escape_html(m.telegram_username)})" if m.telegram_username else ""
            lines.append(f"• <b>{escape_html(m.user.name)}</b>{role}{uname} — {origin}")

        web_url = f"{get_settings().public_base_url}/app/trips/{trip.id}"
        lines.append(f"\n🌐 <b>Dashboard:</b> {web_url}")
        btn = safe_web_button("🌐 View on Web", web_url)
        keyboard = InlineKeyboardMarkup([[btn]]) if btn else None
        await send_safe_reply(update, "\n".join(lines), reply_markup=keyboard)


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calculates and displays budget overview."""
    if not update.effective_chat or not update.effective_user:
        return
    log.info("CMD /budget user_id=%s", update.effective_user.id)
    with SessionLocal() as db:
        trip = get_effective_trip(db, update, context)
        if not trip:
            await send_safe_reply(
                update,
                "⚠️ No active trip found. Join one with <code>/jointrip 4VSE4K9Y</code> or create one with <code>/newtrip Goa</code>.",
            )
            return

        itin = db.scalar(
            select(Itinerary)
            .where(Itinerary.trip_id == trip.id, Itinerary.status == "succeeded")
            .order_by(Itinerary.version.desc())
        )
        b_data = compute_budget(
            itin.budget_items if itin else None,
            trip.travelers_count,
            trip.start_date,
            trip.end_date,
            float(trip.budget_total) if trip.budget_total else None,
            float(trip.budget_per_person) if trip.budget_per_person else None,
        )

        cur = trip.currency or "INR"
        text = (
            f"💰 <b>Budget Overview for '{escape_html(trip.name)}':</b>\n\n"
            f"• <b>Target Total:</b> {cur} {b_data.get('target_total') or 'Flexible'}\n"
            f"• <b>Per Person Target:</b> {cur} {b_data.get('target_per_person') or 'Flexible'}\n"
            f"• <b>Estimated Total:</b> {cur} {b_data.get('estimated_total') or 'Pending itinerary items'}\n"
            f"• <b>Estimated Per Person:</b> {cur} {b_data.get('estimated_per_person') or 'Pending itinerary items'}\n"
            f"• <b>Status:</b> {b_data.get('status', 'Planning').title()}"
        )
        await send_safe_reply(update, text)


async def cmd_itinerary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches the latest itinerary and links."""
    if not update.effective_chat or not update.effective_user:
        return
    log.info("CMD /itinerary user_id=%s", update.effective_user.id)
    with SessionLocal() as db:
        trip = get_effective_trip(db, update, context)
        if not trip:
            await send_safe_reply(
                update,
                "⚠️ No active trip found. Join one with <code>/jointrip 4VSE4K9Y</code> or create one with <code>/newtrip Goa</code>.",
            )
            return

        itin = db.scalar(
            select(Itinerary)
            .where(Itinerary.trip_id == trip.id, Itinerary.status == "succeeded")
            .order_by(Itinerary.version.desc())
        )
        if not itin or not itin.plan_markdown:
            await send_safe_reply(
                update,
                f"🗺 No itinerary has been generated for <b>{escape_html(trip.name)}</b> yet.\n"
                "Run <code>/plan</code> to create one with our multi-agent AI team!",
            )
            return

        # Publish or get Telegraph link
        telegraph_url = await publish_itinerary_page(
            f"{trip.name} - Itinerary v{itin.version}", itin.plan_markdown
        )
        web_url = f"{get_settings().public_base_url}/app/trips/{trip.id}/itinerary"

        rows = []
        if telegraph_url:
            t_btn = safe_web_button("📖 Open Full Itinerary (Telegraph)", telegraph_url)
            if t_btn:
                rows.append([t_btn])
        btn = safe_web_button("🌐 Open Dashboard", web_url)
        if btn:
            rows.append([btn])
        rows.append([InlineKeyboardButton("💰 Budget Split", callback_data=f"budget_{trip.id}")])
        keyboard = InlineKeyboardMarkup(rows) if rows else None

        summary_preview = itin.plan_markdown[:1400]
        if len(itin.plan_markdown) > 1400:
            summary_preview += "\n\n<i>...Open the Telegraph or Dashboard link to view the complete plan.</i>"

        msg_body = (
            f"🗺 <b>Itinerary v{itin.version} for '{escape_html(trip.name)}'</b>\n\n"
            f"{escape_html(summary_preview)}\n\n"
            f"🌐 <b>Dashboard:</b> {web_url}"
        )
        if telegraph_url:
            msg_body += f"\n📖 <b>Telegraph:</b> {telegraph_url}"

        await send_safe_reply(update, msg_body, reply_markup=keyboard)


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs the full multi-agent workflow to generate a new itinerary."""
    if not update.effective_chat or not update.effective_user:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    instructions = " ".join(context.args).strip() if context.args else None

    log.info("CMD /plan user_id=%s instructions=%s", tg_user.id, bool(instructions))

    with SessionLocal() as db:
        trip = get_effective_trip(db, update, context)
        if not trip:
            await send_safe_reply(
                update,
                "⚠️ This chat is not connected to any trip. Use <code>/newtrip Goa</code> or <code>/jointrip 4VSE4K9Y</code> first.",
            )
            return

        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        trip_id = trip.id
        trip_name = trip.name

        try:
            it = itin_svc.start_run(db, trip, user.id, instructions)
        except Exception as exc:  # noqa: BLE001
            await send_safe_reply(update, f"❌ Could not start planning: {escape_html(str(exc))}")
            return

    progress_msg = await send_safe_reply(
        update,
        f"⏳ <b>Generating Itinerary v{it.version} for '{escape_html(trip_name)}'...</b>\n"
        "Our collaborative agents (Planner + Researcher) are researching real-time travel data and crafting your schedule. This usually takes 30-60 seconds.",
    )

    async def _keep_typing():
        while True:
            await send_typing_action(chat_id, context)
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(_keep_typing())
    lock = get_trip_lock(trip_id)

    try:
        async with lock:
            await itin_svc.run_generation(it.id)
    except Exception as exc:  # noqa: BLE001
        typing_task.cancel()
        err_text = f"❌ Planning failed: {escape_html(str(exc))}"
        if progress_msg:
            try:
                await progress_msg.edit_text(err_text, parse_mode=constants.ParseMode.HTML)
            except Exception:
                await send_safe_reply(update, err_text)
        return
    finally:
        typing_task.cancel()

    with SessionLocal() as db:
        it_done = db.get(Itinerary, it.id)
        if not it_done or it_done.status != "succeeded":
            err = it_done.error if it_done else "Unknown error"
            fail_text = f"❌ Planning failed: {escape_html(err)}"
            if progress_msg:
                try:
                    await progress_msg.edit_text(fail_text, parse_mode=constants.ParseMode.HTML)
                except Exception:
                    await send_safe_reply(update, fail_text)
            return

        plan_text = it_done.plan_markdown or "Itinerary generated."
        telegraph_url = await publish_itinerary_page(
            f"{trip_name} - Itinerary v{it_done.version}", plan_text
        )
        web_url = f"{get_settings().public_base_url}/app/trips/{trip_id}/itinerary"

        rows = []
        if telegraph_url:
            t_btn = safe_web_button("📖 Open Full Itinerary (Telegraph)", telegraph_url)
            if t_btn:
                rows.append([t_btn])
        btn = safe_web_button("🌐 Open Web Dashboard", web_url)
        if btn:
            rows.append([btn])
        rows.append([
            InlineKeyboardButton("👍 Approve Plan", callback_data=f"approve_{trip_id}_{it_done.version}"),
            InlineKeyboardButton("💰 Budget Split", callback_data=f"budget_{trip_id}"),
        ])
        keyboard = InlineKeyboardMarkup(rows) if rows else None

        summary = plan_text[:1400]
        if len(plan_text) > 1400:
            summary += "\n\n<i>...Read the complete day-by-day plan via the Telegraph or Dashboard link below.</i>"

        final_text = (
            f"🎉 <b>Itinerary v{it_done.version} is Ready!</b>\n\n"
            f"{escape_html(summary)}\n\n"
            f"🌐 <b>Dashboard:</b> {web_url}"
        )
        if telegraph_url:
            final_text += f"\n📖 <b>Telegraph:</b> {telegraph_url}"

        if progress_msg:
            try:
                await progress_msg.edit_text(
                    final_text,
                    parse_mode=constants.ParseMode.HTML,
                    reply_markup=keyboard,
                )
            except Exception:
                await send_safe_reply(update, final_text, reply_markup=keyboard)


# --- Callback Query Handler (Inline Buttons) ----------------------------------

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data.startswith("itin_"):
        trip_id = int(data.split("_")[1])
        with SessionLocal() as db:
            itin = db.scalar(
                select(Itinerary)
                .where(Itinerary.trip_id == trip_id, Itinerary.status == "succeeded")
                .order_by(Itinerary.version.desc())
            )
            trip = db.get(Trip, trip_id)
            if not itin or not trip:
                await query.edit_message_text("No itinerary found yet.")
                return
            telegraph_url = await publish_itinerary_page(f"{trip.name} Itinerary", itin.plan_markdown)
            web_url = f"{get_settings().public_base_url}/app/trips/{trip_id}/itinerary"

            rows = []
            if telegraph_url:
                t_btn = safe_web_button("📖 Read on Telegraph", telegraph_url)
                if t_btn:
                    rows.append([t_btn])
            btn = safe_web_button("🌐 View on Web", web_url)
            if btn:
                rows.append([btn])
            keyboard = InlineKeyboardMarkup(rows) if rows else None

            body = (
                f"🗺 <b>Itinerary v{itin.version} for {escape_html(trip.name)}</b>\n\n"
                f"{escape_html(itin.plan_markdown[:1000])}...\n\n"
                f"🌐 <b>Dashboard:</b> {web_url}"
            )
            if telegraph_url:
                body += f"\n📖 <b>Telegraph:</b> {telegraph_url}"
            await send_safe_reply(update, body, reply_markup=keyboard)

    elif data.startswith("budget_"):
        trip_id = int(data.split("_")[1])
        with SessionLocal() as db:
            trip = db.get(Trip, trip_id)
            if trip:
                itin = db.scalar(
                    select(Itinerary)
                    .where(Itinerary.trip_id == trip_id, Itinerary.status == "succeeded")
                    .order_by(Itinerary.version.desc())
                )
                b_data = compute_budget(
                    itin.budget_items if itin else None,
                    trip.travelers_count,
                    trip.start_date,
                    trip.end_date,
                    float(trip.budget_total) if trip.budget_total else None,
                    float(trip.budget_per_person) if trip.budget_per_person else None,
                )
                cur = trip.currency or "INR"
                await send_safe_reply(
                    update,
                    f"💰 <b>Budget Breakdown:</b>\n"
                    f"• Target / Person: {cur} {b_data.get('target_per_person') or 'Flexible'}\n"
                    f"• Estimated / Person: {cur} {b_data.get('estimated_per_person') or 'Calculating...'}\n"
                    f"• Total Estimated: {cur} {b_data.get('estimated_total') or 'N/A'}",
                )

    elif data.startswith("approve_"):
        parts = data.split("_")
        trip_id = int(parts[1])
        ver = parts[2]
        user_name = update.effective_user.first_name if update.effective_user else "Member"
        with SessionLocal() as db:
            msgs.post(db, trip_id, "system", f"👍 {user_name} approved Itinerary v{ver} via Telegram.")
        await send_safe_reply(update, f"👍 <b>Thanks {escape_html(user_name)}!</b> Your approval has been recorded.")


# --- Natural Messages & Passive Mode ------------------------------------------

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes normal group and private chat messages.

    In passive mode (groups), records messages for preference extraction without spamming.
    Replies when directly mentioned or in DM using Google ADK Travel Advisor Agent.
    """
    if not update.message or not update.message.text or not update.effective_user or not update.effective_chat:
        return
    text = update.message.text.strip()
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    is_private = update.effective_chat.type == constants.ChatType.PRIVATE

    with SessionLocal() as db:
        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        trip = get_effective_trip(db, update, context)
        if trip:
            ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username)

    bot_username = (context.bot.username or "").lower()
    is_reply_to_bot = (
        update.message.reply_to_message is not None
        and update.message.reply_to_message.from_user is not None
        and context.bot is not None
        and update.message.reply_to_message.from_user.id == context.bot.id
    )
    is_mention = (
        is_private
        or is_reply_to_bot
        or (bool(bot_username) and f"@{bot_username}" in text.lower())
        or "@ai" in text.lower()
        or "@tripmate" in text.lower()
        or "@bot" in text.lower()
    )

    # 1. Forward to Unified Ingestion Bus if connected to a trip
    if trip:
        in_msg = IncomingMessage(
            trip_id=trip.id,
            user_id=user.id,
            channel="telegram",
            text=text,
            external_message_id=str(update.message.message_id),
            sender_name=user.name,
            meta={"ai_mention": is_mention},
        )
        runtime.spawn(handle_incoming_message(in_msg))
        # Active replies for trip chats are handled authoritatively by the unified
        # message bus (chat_ai.run_ai_mention), which relays the AI response to the group.
        # This prevents duplicate responses from both the bus and the ADK advisor.
        return

    if not is_mention:
        return  # Passive mode: do not spam the group

    # Active reply via Google ADK Travel Advisor Agent (for 1-on-1 private DMs outside a trip)
    clean_text = re.sub(rf"@({re.escape(bot_username)}|ai|tripmate|bot)\b", "", text, flags=re.IGNORECASE).strip() or text
    await send_typing_action(chat_id, context)

    user_key = f"tg_{tg_user.id}"
    session_key = f"tg_chat_{chat_id}_user_{tg_user.id}"
    context_prefix = f"Trip context: {trip.name} (Code: {trip.code}, Destination: {trip.destination}). " if trip else ""
    prompt = f"{context_prefix}User {user.name} says: {clean_text}"

    reply = await ask_adk_advisor(user_id=user_key, session_id=session_key, prompt=prompt)

    # Post reply to Telegram group/DM
    chunks = chunk_message(reply)
    for chunk in chunks:
        await send_safe_reply(update, escape_html(chunk))

    # Also log the AI's reply into the trip's message history if in a trip
    if trip:
        with SessionLocal() as db:
            msgs.post(
                db=db,
                trip_id=trip.id,
                kind="ai",
                content=reply,
                channel="telegram",
            )


# --- Outbound Relay Function (Web -> Telegram) -------------------------------

async def send_to_telegram_chat(chat_id: int, html_text: str):
    """Delivers an outbound message to a Telegram group (e.g. from web chat)."""
    global _bot_app
    if not _bot_app or not _bot_app.bot:
        return
    try:
        chunks = chunk_message(html_text)
        for chunk in chunks:
            try:
                await _bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=constants.ParseMode.HTML,
                )
            except Exception as e1:
                log.warning("HTML send to chat %s failed (%s). Retrying as plain text...", chat_id, e1)
                clean = re.sub(r"<[^>]+>", "", chunk)
                await _bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=clean,
                    parse_mode=None,
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to send message to Telegram chat %s: %s", chat_id, exc)


async def handle_chat_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Updates telegram_group_chat_id when a group is upgraded to a supergroup."""
    msg = update.message
    if not msg:
        return
    old_id = msg.migrate_from_chat_id or msg.chat_id
    new_id = msg.migrate_to_chat_id
    if new_id and old_id:
        with SessionLocal() as db:
            trips = db.scalars(select(Trip).where(Trip.telegram_group_chat_id == old_id)).all()
            for t in trips:
                t.telegram_group_chat_id = new_id
            db.commit()
            log.info("Migrated Telegram chat %s -> %s for %s trip(s)", old_id, new_id, len(trips))


# --- Application Setup & Lifecycle --------------------------------------------

def build_telegram_app() -> Optional[Application]:
    global _bot_app
    token = get_settings().telegram_bot_token.strip()
    if not token or token.startswith("your_"):
        log.warning("TELEGRAM_BOT_TOKEN is not configured. Telegram bot disabled.")
        return None

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("newtrip", cmd_newtrip))
    app.add_handler(CommandHandler("jointrip", cmd_jointrip))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("itinerary", cmd_itinerary))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("members", cmd_members))
    app.add_handler(CommandHandler("weblink", cmd_weblink))

    # Migration handler
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, handle_chat_migration))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Group and DM text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

    # Global error handler
    app.add_error_handler(global_telegram_error_handler)

    _bot_app = app
    set_telegram_sender(send_to_telegram_chat)
    return app


async def start_telegram_service():
    """Starts the bot in polling mode (for dev) or webhook mode."""
    app = build_telegram_app()
    if not app:
        return
    settings = get_settings()
    log.info("Starting Telegram Bot (mode: %s)...", settings.telegram_mode)
    await app.initialize()
    await app.start()

    if settings.telegram_mode.lower() == "polling":
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram Bot is listening via long-polling!")
    elif settings.telegram_mode.lower() == "webhook":
        if not settings.telegram_webhook_url or not settings.telegram_webhook_secret:
            msg = "Telegram webhook mode requires both TELEGRAM_WEBHOOK_URL and TELEGRAM_WEBHOOK_SECRET."
            log.error(msg)
            raise RuntimeError(msg)

        webhook_url = f"{settings.telegram_webhook_url.rstrip('/')}/api/telegram/webhook"
        try:
            await app.bot.set_webhook(
                url=webhook_url,
                secret_token=settings.telegram_webhook_secret,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"],
            )
            log.info("Telegram Bot registered webhook at %s", webhook_url)
        except Exception as exc:  # noqa: BLE001
            safe_err = str(exc)
            if settings.telegram_bot_token and settings.telegram_bot_token in safe_err:
                safe_err = safe_err.replace(settings.telegram_bot_token, "[MASKED]")
            if settings.telegram_webhook_secret and settings.telegram_webhook_secret in safe_err:
                safe_err = safe_err.replace(settings.telegram_webhook_secret, "[MASKED]")
            log.warning("Failed to register Telegram webhook: %s", safe_err)
    else:
        log.warning("Unknown telegram_mode '%s'. Expected 'polling' or 'webhook'.", settings.telegram_mode)


async def stop_telegram_service():
    global _bot_app
    if _bot_app:
        try:
            if _bot_app.updater and _bot_app.updater.running:
                await _bot_app.updater.stop()
            if _bot_app.running:
                await _bot_app.stop()
            await _bot_app.shutdown()
            log.info("Telegram Bot stopped cleanly.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Error stopping Telegram Bot: %s", exc)


async def process_telegram_webhook(update_data: dict):
    """Processes an incoming webhook update from FastAPI."""
    global _bot_app
    if not _bot_app:
        return
    update = Update.de_json(update_data, _bot_app.bot)
    await _bot_app.process_update(update)
