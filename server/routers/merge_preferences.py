"""
Standalone Preference Merge & Conflict Resolution endpoint.

POST /api/merge-preferences
  Body: { "user_1_input": "...", "user_2_input": "..." }
  Returns a JSON object describing merged preferences and any conflicts.

This endpoint is DB-free: it feeds both users' preference text directly into
the Conflict Resolution Agent (Gemini) and returns structured JSON.
"""
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.ai.client import AIError, extract_json, llm_text

log = logging.getLogger("tripmate.merge_preferences")

router = APIRouter(prefix="/api", tags=["merge-preferences"])

# ------------------------------------------------------------------ schema

class MergeIn(BaseModel):
    user_1_input: str = Field(min_length=1, max_length=4000, description="User 1's raw preference text")
    user_2_input: str = Field(min_length=1, max_length=4000, description="User 2's raw preference text")


class MergedPreferences(BaseModel):
    destinations: list[str] = []
    budget_category: str = ""
    activities: list[str] = []
    food_preferences: list[str] = []


class MergeOut(BaseModel):
    has_critical_conflict: bool
    conflict_details: str
    merged_preferences: MergedPreferences


# ------------------------------------------------------------------ prompt

MERGE_SYSTEM = """You are the conflict resolution and preference-merging engine for a group trip planner.
You will receive preferences from two different users.

Your job is to compare them, detect any direct contradictions, and output a balanced, combined preference profile that respects both users.

Rules:
1. Do not ignore any user's input.
2. If preferences match (e.g., both want beaches), merge them into the final output.
3. If preferences contradict but can be compromised (e.g., User 1 wants luxury, User 2 wants budget), suggest a mid-range solution.
4. If there is a hard contradiction that cannot be merged (e.g., User 1 wants to go to Manali, User 2 wants to go to Goa), flag it as a critical conflict.

You MUST respond ONLY with a valid JSON object in exactly this format:
{
  "has_critical_conflict": true or false,
  "conflict_details": "Explain the exact contradiction if true, otherwise empty string",
  "merged_preferences": {
    "destinations": ["list", "of", "destinations"],
    "budget_category": "budget | mid-range | luxury",
    "activities": ["list", "of", "merged", "activities"],
    "food_preferences": ["list", "of", "merged", "food", "preferences"]
  }
}"""


# ------------------------------------------------------------------ endpoint

@router.post("/merge-preferences", response_model=MergeOut)
async def merge_preferences(body: MergeIn) -> MergeOut:
    """
    Compare two users' travel preferences, detect conflicts, and return
    a merged preference profile (or flag a critical conflict).
    """
    user_prompt = (
        f"User 1 Preferences: {body.user_1_input}\n\n"
        f"User 2 Preferences: {body.user_2_input}"
    )

    try:
        raw = await llm_text(MERGE_SYSTEM, user_prompt, timeout=150)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=exc.user_message) from exc
    except Exception as exc:
        log.exception("Unexpected error in merge_preferences")
        raise HTTPException(status_code=500, detail="Preference merge failed. Please try again.") from exc

    try:
        data = extract_json(raw)
    except AIError as exc:
        log.warning("merge_preferences: could not parse AI JSON: %s | raw: %.300s", exc, raw)
        raise HTTPException(status_code=502, detail="The AI returned an unexpected response. Please try again.") from exc

    # Coerce / validate the AI response gracefully
    merged = data.get("merged_preferences") or {}
    if not isinstance(merged, dict):
        merged = {}

    return MergeOut(
        has_critical_conflict=bool(data.get("has_critical_conflict", False)),
        conflict_details=str(data.get("conflict_details") or ""),
        merged_preferences=MergedPreferences(
            destinations=_to_list(merged.get("destinations")),
            budget_category=str(merged.get("budget_category") or ""),
            activities=_to_list(merged.get("activities")),
            food_preferences=_to_list(merged.get("food_preferences")),
        ),
    )


def _to_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value:
        return [value]
    return []

