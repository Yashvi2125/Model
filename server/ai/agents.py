"""Specialised agents from the proposal, built on the shared Gemini client.

* Preference Extraction Agent  - chat message -> structured preferences
* Conflict Resolution Agent    - detected disagreements -> feasible compromises
* Budget Agent (extraction)    - plan text -> cost lines (all arithmetic is in services/budget.py)
* Assistant reply              - conversational answer inside the group chat
The Itinerary Planning + Travel Research agents are the project's existing Planner/Researcher team
(see server/ai/workflow.py).
"""
import json
import logging
import re
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from server.ai.client import AIError, llm_json, llm_text
from server.ai.gateway import (
    PRIORITY_BACKGROUND,
    PRIORITY_INTERACTIVE,
    PRIORITY_URGENT,
)
from server.schemas import INTEREST_IDS
from server.services.budget import BASES, CATEGORIES

log = logging.getLogger("tripmate.ai")


# ---------------------------------------------------------------- preference extraction
class ExtractedPreferences(BaseModel):
    destination: Optional[str] = None
    trip_days: Optional[int] = Field(default=None, ge=1, le=60)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget_per_person: Optional[float] = Field(default=None, ge=0)
    budget_total: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    interests: list[str] = []
    accommodation: Optional[str] = None
    dietary: Optional[str] = None
    restrictions: Optional[str] = None
    notes: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    provider: Optional[str] = "gemini"
    model: Optional[str] = None

    @field_validator("start_date", "end_date", "trip_days", "budget_per_person", "budget_total", "confidence", mode="before")
    @classmethod
    def _lenient(cls, v):
        return None if v in ("", "null", "None") else v

    @field_validator("interests", mode="before")
    @classmethod
    def _list(cls, v):
        return [str(x) for x in v] if isinstance(v, list) else []


PREF_SYSTEM = f"""You are the Preference Extraction Agent in a group trip-planning app.
Read ONE chat message written by ONE traveller and extract ONLY what the message explicitly says about that traveller's OWN trip preferences.
Never guess or infer beyond the text. If the message is small talk, a question, or has no preferences, return nulls/empty lists and confidence 0.
Return ONLY a JSON object with exactly these keys:
destination (string|null), trip_days (integer|null), start_date (YYYY-MM-DD|null), end_date (YYYY-MM-DD|null),
budget_per_person (number|null), budget_total (number|null), currency (ISO code like INR|null; Rs/₹ means INR),
interests (array of strings; use these ids when they fit: {", ".join(INTEREST_IDS)}; historical/heritage sites -> "culture"),
accommodation (string|null), dietary (string|null), restrictions (string|null), notes (string|null), confidence (0..1).
Amounts are plain numbers without separators (8,000 -> 8000)."""


async def extract_preferences_gemini(text: str, traveller: str, trip_ctx: str) -> ExtractedPreferences:
    import time
    from server.ai.client import ai_status
    t0 = time.time()
    data = await llm_json(
        PREF_SYSTEM,
        f"Today: {date.today().isoformat()}\n{trip_ctx}\nTraveller: {traveller}\nMessage: \"\"\"{text}\"\"\"",
        feature="preference_extraction",
        priority=PRIORITY_BACKGROUND,
    )
    latency_ms = int((time.time() - t0) * 1000)
    try:
        ex = ExtractedPreferences.model_validate(data)
        ex.provider = "gemini"
        ex.model = ai_status()["model"]
        log.info("provider=gemini model=%s latency_ms=%d", ex.model, latency_ms)
        return ex
    except Exception as exc:  # noqa: BLE001
        log.warning("Preference extraction validation failed: %s", exc)
        raise AIError("The AI response couldn't be understood. Please try again.") from exc


async def extract_preferences(text: str, traveller: str, trip_ctx: str) -> ExtractedPreferences:
    from server.ai.local_llm import extract_preferences_with_fallback
    return await extract_preferences_with_fallback(text, traveller, trip_ctx)


# ---------------------------------------------------------------- assistant reply
CHAT_SYSTEM = """You are MileMates AI, the assistant inside a group trip-planning chat.
Be warm, concise (under 130 words) and practical. Use the trip context provided; never invent prices, opening hours, availability or bookings.
- If the traveller shared preferences, acknowledge them briefly and say they're saved as suggestions to review in the Preferences tab (they are not applied automatically).
- If members clearly disagree, point to the Conflicts tab.
- If asked for a full plan, point to the Itinerary tab and its Generate button; do not write a full itinerary in chat.
- If you lack information, say so and ask one clear question."""


async def chat_reply(trip_ctx: str, recent: str, sender: str, text: str, noted: Optional[str]) -> str:
    user = (f"{trip_ctx}\n\nRecent chat:\n{recent or '(none)'}\n\n"
            f"{sender} says to you: {text}\n"
            f"{'Preferences detected in this message (saved as suggestions): ' + noted if noted else ''}")
    return await llm_text(CHAT_SYSTEM, user, feature="chat_reply", priority=PRIORITY_URGENT)


# ---------------------------------------------------------------- conflict resolution
CONFLICT_SYSTEM = """You are the conflict resolution and preference-merging engine for a group trip planner.
You receive all travellers' saved preferences (destination, dates, budget, accommodation, dietary requirements, and specific notes/requests) plus any rule-detected disagreements.

Your job is to thoroughly compare them, detect any direct contradictions, and output a balanced, combined assessment that respects all users.
Rules:
1. Do not ignore any user's input or specific notes (e.g. day-specific preferences like "wants to explore Shibuya on Day 2" vs "prefers visiting beach on Day 2").
2. For each rule-detected disagreement, provide ONE feasible, fair compromise (2-3 sentences).
3. If there are other contradictions or compromises needed (such as scheduling clashes, food/dietary splits, pace of travel), include them under "additional".
4. For each conflict, identify the positions of the members involved.

Return ONLY JSON in this format:
{
  "suggestions": {
    "<kind>": "<compromise for the rule-detected disagreement kind, e.g. activities, budget, etc.>"
  },
  "additional": [
    {
      "kind": "activities | schedule | budget | accommodation | dietary | other",
      "title": "Short descriptive title (e.g. 'Day 2 Itinerary Clash: Beach vs. Shibuya')",
      "description": "Explain the exact contradiction between members",
      "positions": [
        {"name": "FirstName", "detail": "Their specific preference or note"}
      ],
      "suggestion": "A fair, concrete compromise (2-3 sentences)"
    }
  ]
}"""


async def resolve_conflicts(trip_ctx: str, detected: list[dict], chat_context: str = "") -> dict[str, Any]:
    payload = [{"kind": c["kind"], "title": c["title"], "positions": c["positions"]} for c in detected]
    prompt = f"{trip_ctx}\n\nDetected structural disagreements:\n{json.dumps(payload, ensure_ascii=False, default=str)}"
    if chat_context:
        prompt += f"\n\nRecent group chat messages:\n{chat_context}"
    return await llm_json(CONFLICT_SYSTEM, prompt, timeout=120, feature="conflict_resolution", priority=PRIORITY_INTERACTIVE)


# ---------------------------------------------------------------- chat-based conflict scan
CHAT_SCAN_SYSTEM = """You are the Conflict Detection Agent for a group trip-planning app.
Read the recent group chat history and each member's saved preferences.
Find disagreements that are NOT already in the provided list of known conflicts.
Look for: different preferred activities on specific days, one person wanting X while another wants Y,
scheduling clashes, food preference conflicts, pace-of-travel differences, etc.

Return ONLY valid JSON:
{
  "conflicts": [
    {
      "title": "Short title (max 10 words)",
      "description": "What exactly disagrees and why it matters (1-2 sentences)",
      "suggestion": "A fair, concrete compromise (2-3 sentences)",
      "positions": [{"name": "FirstName", "detail": "Their specific preference or statement"}]
    }
  ]
}
If you find no NEW disagreements beyond what is already known, return {"conflicts": []}.
Do NOT repeat conflicts already in the known list. Be specific — quote what members actually said."""


async def scan_chat_for_conflicts(
    trip_ctx: str,
    recent_messages: str,
    known_conflict_titles: list[str],
) -> list[dict]:
    """Scan recent chat messages for latent conflicts not caught by the rule engine."""
    known = json.dumps(known_conflict_titles, ensure_ascii=False)
    user_prompt = (
        f"{trip_ctx}\n\n"
        f"Already-known conflicts (do NOT repeat these): {known}\n\n"
        f"Recent group chat (oldest first):\n{recent_messages}"
    )
    try:
        data = await llm_json(CHAT_SCAN_SYSTEM, user_prompt, timeout=120, feature="chat_conflict_scan", priority=PRIORITY_BACKGROUND)
    except Exception as exc:  # noqa: BLE001
        log.warning("Chat conflict scan failed: %s", exc)
        return []

    raw = data.get("conflicts") if isinstance(data.get("conflicts"), list) else []
    result = []
    for item in raw[:5]:  # cap at 5 new conflicts per scan
        title = str(item.get("title", ""))[:200]
        if not title:
            continue
        result.append({
            "title": title,
            "description": str(item.get("description", ""))[:1200],
            "suggestion": str(item.get("suggestion", ""))[:1200] or None,
            "positions": item.get("positions") if isinstance(item.get("positions"), list) else [],
        })
    return result


# ---------------------------------------------------------------- budget extraction
BUDGET_SYSTEM = f"""You are the Budget Agent's extraction step. Read the travel plan and list ONLY cost figures that are explicitly written in it.
Do NOT invent, estimate or fill gaps. Never multiply anything yourself - the program does all the maths.
Return ONLY JSON: {{"items": [{{"category": one of {CATEGORIES}, "label": short text, "amount": number, "basis": one of {BASES}, "source_text": the exact fragment of the plan the number came from}}]}}
basis meanings: group_total = one amount for the whole group; per_person = per traveller, charged once; per_person_per_day = per traveller per day (e.g. daily food); per_night_group = whole-group accommodation price per night.
STRICT RULES (these prevent wrong totals):
1. List every cost ONCE. If the same cost appears in a day-by-day section and again in a summary or table, keep only one entry.
2. NEVER list totals, subtotals, "estimated total", "budget summary", per-person totals or grand totals - only the individual items they are made of.
3. Pick the basis from the words in the plan: "per person"/"pp"/"each" -> per_person; "per person per day"/"daily" -> per_person_per_day; "per night" for a hotel/room -> per_night_group; "for the group"/"total for X" or no per-person wording -> group_total.
4. The amount is the number as written, in the trip currency, with no conversion. If a range is given use the midpoint.
5. Skip any item whose amount or basis is unclear instead of guessing.
6. If a hotel is given as a total for the whole stay, use group_total, not per_night_group."""


_TOTALISH = re.compile(
    r"^\s*(grand\s*total|sub-?\s*total|total(\s+(estimated|estimate|cost|costs|budget|trip|expenses?|spend|per\s+person))?|"
    r"overall(\s+(cost|total|budget))?|estimated\s+(total|budget|cost)|trip\s+total|budget\s+(summary|total)|per\s+person\s+total)\b",
    re.IGNORECASE,
)


def sanitize_budget_items(items: list[dict]) -> list[dict]:
    """Drop lines that would double count: totals/subtotals and repeats of the same cost."""
    seen: set[tuple] = set()
    clean: list[dict] = []
    for it in items:
        label = (it.get("label") or "").strip()
        if _TOTALISH.match(label):
            continue
        key = (it["category"], round(float(it["amount"]), 2), it["basis"], re.sub(r"\W+", "", label.lower())[:30])
        src_key = (round(float(it["amount"]), 2), re.sub(r"\W+", "", (it.get("source_text") or "").lower())[:60])
        if key in seen or (src_key[1] and src_key in seen):
            continue
        seen.add(key)
        if src_key[1]:
            seen.add(src_key)
        clean.append(it)
    return clean


async def extract_budget_items(plan: str, currency: str, travelers: int, days: int) -> list[dict]:
    data = await llm_json(
        BUDGET_SYSTEM,
        f"Currency: {currency}. Travellers: {travelers}. Days: {days}.\n\nPLAN:\n{plan[:14000]}",
        timeout=120,
        feature="budget_extraction",
        priority=PRIORITY_INTERACTIVE,
    )
    items = []
    for it in data.get("items", []) if isinstance(data.get("items"), list) else []:
        try:
            amount = float(it.get("amount"))
        except (TypeError, ValueError):
            continue
        if amount < 0 or it.get("basis") not in BASES:
            continue
        items.append({"category": it.get("category") if it.get("category") in CATEGORIES else "other",
                      "label": str(it.get("label", ""))[:120], "amount": amount, "basis": it["basis"],
                      "source_text": str(it.get("source_text", ""))[:300]})
    return sanitize_budget_items(items)[:60]
