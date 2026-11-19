"""TripMate Telegram Group & DM Bot powered by Google ADK and Gemini."""
import asyncio
from datetime import date, datetime, timedelta
import html
import logging
import re
from typing import Optional

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


def escape_html(text: str) -> str:
    """Safely escapes text for Telegram HTML mode while preserving simple tags."""
    if not text:
        return ""
    return html.escape(str(text))


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


# --- Telegram Command Handlers ------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start, including deep-link trip joins: /start <TRIP_CODE>."""
    if not update.effective_user or not update.effective_chat:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    settings = get_settings()

    with SessionLocal() as db:
        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)

        # Check deep link payload (e.g. /start 4VSE4K9Y)
        payload = context.args[0].strip() if context.args else None
        if payload:
            trip = get_trip_by_code(db, payload)
            if trip:
                ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username)
                if update.effective_chat.type in (constants.ChatType.GROUP, constants.ChatType.SUPERGROUP):
                    bind_trip_to_chat(db, trip, chat_id)

                web_url = f"{settings.public_base_url}/app/trips/{trip.id}"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌐 Open Web Dashboard", url=web_url)],
                    [InlineKeyboardButton("📋 View Itinerary", callback_data=f"itin_{trip.id}")],
                ])
                await update.message.reply_html(
                    f"🎉 <b>Welcome to Trip '{escape_html(trip.name)}'!</b>\n\n"
                    f"📍 <b>Destination:</b> {escape_html(trip.destination or 'Undecided')}\n"
                    f"📅 <b>Dates:</b> {trip.start_date} to {trip.end_date}\n"
                    f"🔑 <b>Trip Code:</b> <code>{trip.code}</code>\n\n"
                    f"You have joined the trip. Chat here naturally to share preferences, or use /plan to generate an itinerary!",
                    reply_markup=keyboard,
                )
                return

    help_text = (
        f"👋 <b>Hello {escape_html(tg_user.first_name)}! Welcome to TripMate AI.</b>\n\n"
        "I am your collaborative travel planning companion powered by Google ADK & Gemini.\n\n"
        "<b>Group Commands:</b>\n"
        "• <code>/newtrip &lt;destination&gt;</code> - Create a new group trip\n"
        "• <code>/jointrip &lt;code&gt;</code> - Connect this group to an existing trip\n"
        "• <code>/plan [notes]</code> - Generate a complete multi-agent itinerary\n"
        "• <code>/itinerary</code> - View the latest saved trip plan & Telegraph link\n"
        "• <code>/budget</code> - View the estimated budget breakdown\n"
        "• <code>/status</code> - Check planning progress & member preferences\n"
        "• <code>/members</code> - List everyone in the group\n"
        "• <code>/weblink</code> - Direct link to the web interface\n\n"
        "<i>Add me to your group, disable privacy mode in @BotFather, and start planning together!</i>"
    )
    await update.message.reply_html(help_text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_newtrip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a new trip and binds this chat to it."""
    if not update.effective_user or not update.effective_chat:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    settings = get_settings()

    args_text = " ".join(context.args).strip() if context.args else ""
    destination = args_text or "Undecided"
    s_date = date.today() + timedelta(days=14)
    e_date = s_date + timedelta(days=5)

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
            telegram_group_chat_id=chat_id,
        )
        db.add(trip)
        db.flush()
        ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username, role="owner")
        pref_svc.seed_from_trip(db, trip, user.id)
        db.commit()

        bot_username = settings.telegram_bot_username.lstrip("@")
        deep_link = f"https://t.me/{bot_username}?start={trip.code}"
        web_url = f"{settings.public_base_url}/app/trips/{trip.id}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Open Web Dashboard", url=web_url)],
            [InlineKeyboardButton("🔗 Share Invite Link", url=deep_link)],
        ])

        reply = (
            f"🚀 <b>Trip Created Successfully!</b>\n\n"
            f"🏷 <b>Trip:</b> {escape_html(trip.name)}\n"
            f"📍 <b>Destination:</b> {escape_html(trip.destination)}\n"
            f"📅 <b>Dates:</b> {trip.start_date} to {trip.end_date} (default 6 days)\n"
            f"🔑 <b>Trip Code:</b> <code>{trip.code}</code>\n\n"
            f"This group is now connected to the trip! Friends can join with <code>/jointrip {trip.code}</code> or via the button below."
        )
        await update.message.reply_html(reply, reply_markup=keyboard)


async def cmd_jointrip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Binds group/user to an existing trip code."""
    if not update.effective_user or not update.effective_chat:
        return
    if not context.args:
        await update.message.reply_html("⚠️ Please provide a trip code:\n<code>/jointrip TRIP-XXXX</code>")
        return

    code = context.args[0].strip()
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    settings = get_settings()

    with SessionLocal() as db:
        trip = get_trip_by_code(db, code)
        if not trip:
            await update.message.reply_html(f"❌ No trip found with code <code>{escape_html(code)}</code>.")
            return

        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username)

        # Bind group chat if in a group
        if update.effective_chat.type in (constants.ChatType.GROUP, constants.ChatType.SUPERGROUP):
            bind_trip_to_chat(db, trip, chat_id)

        web_url = f"{settings.public_base_url}/app/trips/{trip.id}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Open Web Dashboard", url=web_url)],
            [InlineKeyboardButton("📋 View Itinerary", callback_data=f"itin_{trip.id}")],
        ])

        await update.message.reply_html(
            f"✅ <b>Connected to '{escape_html(trip.name)}'!</b>\n\n"
            f"📍 <b>Destination:</b> {escape_html(trip.destination or 'Undecided')}\n"
            f"📅 <b>Dates:</b> {trip.start_date} to {trip.end_date}\n"
            f"👥 <b>Total Members:</b> {len(trip.members)}\n\n"
            f"All group messages will now sync with the web planner.",
            reply_markup=keyboard,
        )


async def cmd_weblink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns direct web link for the current trip."""
    if not update.effective_chat:
        return
    with SessionLocal() as db:
        trip = get_trip_by_chat_id(db, update.effective_chat.id)
        if not trip:
            await update.message.reply_html("⚠️ This chat is not connected to a trip yet. Use /newtrip or /jointrip.")
            return
        web_url = f"{get_settings().public_base_url}/app/trips/{trip.id}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web App", url=web_url)]])
        await update.message.reply_html(
            f"🌐 <b>Web Dashboard for '{escape_html(trip.name)}':</b>\n{web_url}",
            reply_markup=keyboard,
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows collected preferences and planning readiness."""
    if not update.effective_chat:
        return
    with SessionLocal() as db:
        trip = get_trip_by_chat_id(db, update.effective_chat.id)
        if not trip:
            await update.message.reply_html("⚠️ No active trip in this chat. Connect one using /newtrip or /jointrip.")
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 View on Web", url=web_url)]])
        await update.message.reply_html("\n".join(lines), reply_markup=keyboard)


async def cmd_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists trip members and platform origins."""
    if not update.effective_chat:
        return
    with SessionLocal() as db:
        trip = get_trip_by_chat_id(db, update.effective_chat.id)
        if not trip:
            await update.message.reply_html("⚠️ Connect a trip first using /newtrip or /jointrip.")
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

        await update.message.reply_html("\n".join(lines))


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calculates and displays budget overview."""
    if not update.effective_chat:
        return
    with SessionLocal() as db:
        trip = get_trip_by_chat_id(db, update.effective_chat.id)
        if not trip:
            await update.message.reply_html("⚠️ Connect a trip first using /newtrip or /jointrip.")
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
        await update.message.reply_html(text)


async def cmd_itinerary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches the latest itinerary and links."""
    if not update.effective_chat:
        return
    with SessionLocal() as db:
        trip = get_trip_by_chat_id(db, update.effective_chat.id)
        if not trip:
            await update.message.reply_html("⚠️ Connect a trip first using /newtrip or /jointrip.")
            return

        itin = db.scalar(
            select(Itinerary)
            .where(Itinerary.trip_id == trip.id, Itinerary.status == "succeeded")
            .order_by(Itinerary.version.desc())
        )
        if not itin or not itin.plan_markdown:
            await update.message.reply_html(
                f"🗺 No itinerary has been generated for <b>{escape_html(trip.name)}</b> yet.\n"
                "Run <code>/plan</code> to create one with our multi-agent AI team!"
            )
            return

        # Publish or get Telegraph link
        telegraph_url = await publish_itinerary_page(
            f"{trip.name} - Itinerary v{itin.version}", itin.plan_markdown
        )
        web_url = f"{get_settings().public_base_url}/app/trips/{trip.id}/itinerary"

        buttons = [[InlineKeyboardButton("🌐 Open Dashboard", url=web_url)]]
        if telegraph_url:
            buttons.insert(0, [InlineKeyboardButton("📖 Open Full Itinerary (Telegraph)", url=telegraph_url)])
        buttons.append([InlineKeyboardButton("💰 Budget Split", callback_data=f"budget_{trip.id}")])

        summary_preview = itin.plan_markdown[:1400]
        if len(itin.plan_markdown) > 1400:
            summary_preview += "\n\n<i>...Open the Telegraph or Dashboard link to view the complete plan.</i>"

        await update.message.reply_html(
            f"🗺 <b>Itinerary v{itin.version} for '{escape_html(trip.name)}'</b>\n\n"
            f"{escape_html(summary_preview)}",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs the full multi-agent workflow to generate a new itinerary."""
    if not update.effective_chat or not update.effective_user:
        return
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    instructions = " ".join(context.args).strip() if context.args else None

    with SessionLocal() as db:
        trip = get_trip_by_chat_id(db, chat_id)
        if not trip:
            await update.message.reply_html(
                "⚠️ This chat is not connected to any trip. Use <code>/newtrip</code> or <code>/jointrip</code> first."
            )
            return

        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        trip_id = trip.id
        trip_name = trip.name

        try:
            it = itin_svc.start_run(db, trip, user.id, instructions)
        except Exception as exc:  # noqa: BLE001
            await update.message.reply_html(f"❌ Could not start planning: {escape_html(str(exc))}")
            return

    progress_msg = await update.message.reply_html(
        f"⏳ <b>Generating Itinerary v{it.version} for '{escape_html(trip_name)}'...</b>\n"
        "Our collaborative agents (Planner + Researcher) are researching real-time travel data and crafting your schedule. This usually takes 30-60 seconds."
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
        await progress_msg.edit_text(f"❌ Planning failed: {escape_html(str(exc))}")
        return
    finally:
        typing_task.cancel()

    with SessionLocal() as db:
        it_done = db.get(Itinerary, it.id)
        if not it_done or it_done.status != "succeeded":
            err = it_done.error if it_done else "Unknown error"
            await progress_msg.edit_text(f"❌ Planning failed: {escape_html(err)}")
            return

        plan_text = it_done.plan_markdown or "Itinerary generated."
        telegraph_url = await publish_itinerary_page(
            f"{trip_name} - Itinerary v{it_done.version}", plan_text
        )
        web_url = f"{get_settings().public_base_url}/app/trips/{trip_id}/itinerary"

        buttons = [[InlineKeyboardButton("🌐 Open Web Dashboard", url=web_url)]]
        if telegraph_url:
            buttons.insert(0, [InlineKeyboardButton("📖 Open Full Itinerary (Telegraph)", url=telegraph_url)])
        buttons.append([
            InlineKeyboardButton("👍 Approve Plan", callback_data=f"approve_{trip_id}_{it_done.version}"),
            InlineKeyboardButton("💰 Budget Split", callback_data=f"budget_{trip_id}"),
        ])

        summary = plan_text[:1400]
        if len(plan_text) > 1400:
            summary += "\n\n<i>...Read the complete day-by-day plan via the Telegraph or Dashboard link below.</i>"

        await progress_msg.edit_text(
            f"🎉 <b>Itinerary v{it_done.version} is Ready!</b>\n\n{escape_html(summary)}",
            parse_mode=constants.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )


# --- Callback Query Handler (Inline Buttons) ----------------------------------

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
            btns = [[InlineKeyboardButton("🌐 View on Web", url=web_url)]]
            if telegraph_url:
                btns.insert(0, [InlineKeyboardButton("📖 Read on Telegraph", url=telegraph_url)])
            await query.message.reply_html(
                f"🗺 <b>Itinerary v{itin.version} for {escape_html(trip.name)}</b>\n\n{escape_html(itin.plan_markdown[:1000])}...",
                reply_markup=InlineKeyboardMarkup(btns),
            )

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
                await query.message.reply_html(
                    f"💰 <b>Budget Breakdown:</b>\n"
                    f"• Target / Person: {cur} {b_data.get('target_per_person') or 'Flexible'}\n"
                    f"• Estimated / Person: {cur} {b_data.get('estimated_per_person') or 'Calculating...'}\n"
                    f"• Total Estimated: {cur} {b_data.get('estimated_total') or 'N/A'}"
                )

    elif data.startswith("approve_"):
        parts = data.split("_")
        trip_id = int(parts[1])
        ver = parts[2]
        user_name = update.effective_user.first_name if update.effective_user else "Member"
        with SessionLocal() as db:
            msgs.post(db, trip_id, "system", f"👍 {user_name} approved Itinerary v{ver} via Telegram.")
        await query.message.reply_html(f"👍 <b>Thanks {escape_html(user_name)}!</b> Your approval has been recorded.")


# --- Natural Messages & Passive Mode ------------------------------------------

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes normal group and private chat messages.

    In passive mode (groups), records messages for preference extraction without spamming.
    Replies when directly mentioned or in DM using Google ADK Travel Advisor Agent.
    """
    if not update.message or not update.message.text or not update.effective_user:
        return
    text = update.message.text.strip()
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    is_private = update.effective_chat.type == constants.ChatType.PRIVATE

    with SessionLocal() as db:
        user = get_or_create_telegram_user(db, tg_user.id, tg_user.full_name, tg_user.username)
        trip = get_trip_by_chat_id(db, chat_id)
        if trip:
            ensure_trip_member(db, trip.id, user.id, tg_user.id, tg_user.username)

    # 1. Forward to Unified Ingestion Bus if connected to a trip
    if trip:
        in_msg = IncomingMessage(
            trip_id=trip.id,
            user_id=user.id,
            channel="telegram",
            text=text,
            external_message_id=str(update.message.message_id),
            sender_name=user.name,
        )
        runtime.spawn(handle_incoming_message(in_msg))

    # 2. Check if we should reply actively:
    # In DM: Always reply. In group: Only if bot is mentioned (@ai, @Tripmate_planner_bot, or bot name)
    bot_username = (context.bot.username or "").lower()
    is_mention = (
        is_private
        or f"@{bot_username}" in text.lower()
        or "@ai" in text.lower()
        or "@tripmate" in text.lower()
        or "@bot" in text.lower()
    )

    if not is_mention:
        return  # Passive mode: do not spam the group

    # Active reply via Google ADK Travel Advisor Agent
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
        await update.message.reply_html(escape_html(chunk))

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
            await _bot_app.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=constants.ParseMode.HTML,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to send message to Telegram chat %s: %s", chat_id, exc)


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
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("itinerary", cmd_itinerary))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("members", cmd_members))
    app.add_handler(CommandHandler("weblink", cmd_weblink))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Group and DM text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_group_message))

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
    else:
        log.info("Telegram Bot initialized in webhook mode.")


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
