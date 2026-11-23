"""Runs the project's EXISTING Planner + Researcher team (teams/travel_team.py) for the web backend.

Mirrors main.py's run_planner(): live Tavily research first (when configured), then the round-robin team.
Differences required for a server: a FRESH team/agents per request (module-level ones keep chat history and
cannot run concurrently), results are collected instead of printed, and a missing Tavily key degrades gracefully.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from autogen_agentchat.messages import TextMessage

import config.settings as ai_settings
from server.ai.client import AIError, ai_status, friendly_error, get_client
from server.config import get_settings

log = logging.getLogger("tripmate.workflow")


@dataclass
class PlanResult:
    plan: str
    research: str
    search_used: bool
    transcript: list = field(default_factory=list)
    stop_reason: str = ""


async def _live_research(query: str) -> tuple[str, bool]:
    if not ai_status()["tavily_configured"]:
        return "", False
    try:
        from main import parse_structured_data  # existing CLI helper (safe literal parsing)
        from utils.tools import create_travel_specific_search_tool

        tool = create_travel_specific_search_tool()
        raw = await asyncio.to_thread(tool._func, query[:380])
        if raw.startswith("Search error"):
            log.warning("Tavily search failed: %s", raw[:200])
            return "", False
        parsed = parse_structured_data(raw)
        if parsed is None and "results" not in raw:
            return "", False
        return f"\n\n[Live Verified Research Data from Tavily Search]:\n{raw}\n", True
    except Exception as exc:  # noqa: BLE001
        log.warning("Live research unavailable: %s", exc)
        return "", False


def _text(msg) -> str:
    c = getattr(msg, "content", None)
    return c.strip() if isinstance(c, str) else ""


async def generate_plan(prompt: str, search_query: str) -> PlanResult:
    get_client()  # raises AINotConfigured with a clear message if the key is missing
    from agents.planner import create_planner_agent
    from agents.researcher import create_researcher_agent
    from models.gemini_model import create_gemini_model_client
    from teams.travel_team import create_travel_team

    search_context, used = await _live_research(search_query)
    full_task = (f"{prompt}{search_context}\n"
                 "Instructions: Use the real-time research above (if present) to create a detailed, day-by-day itinerary "
                 "with estimated costs and recommendations. Label costs as estimates unless a source gives a fixed price.")

    def _build_team(model_name: str | None = None):
        import agents.planner as _pl
        import models.gemini_model as _gm
        custom_client = getattr(_pl, "model_client", None)
        if custom_client is not None and custom_client is not getattr(_gm, "model_client", None):
            client = custom_client
        elif model_name:
            client = create_gemini_model_client(model=model_name)
        else:
            client = None
        return create_travel_team(
            planner=create_planner_agent(client=client),
            researcher=create_researcher_agent(client=client),
        )

    primary_model = ai_settings.GEMINI_MODEL or "gemini-3.8-flash"
    fallback_model = getattr(ai_settings, "GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    timeout = get_settings().itinerary_timeout_seconds

    team = _build_team(primary_model)
    try:
        result = await asyncio.wait_for(
            team.run(task=TextMessage(content=full_task, source="User")), timeout)
    except asyncio.TimeoutError as exc:
        raise AIError("The AI took too long to respond. Please try again.") from exc
    except Exception as exc:  # noqa: BLE001
        err_str = str(exc).lower()
        is_recoverable = any(k in err_str for k in ("429", "503", "404", "overloaded", "unavailable", "rate", "resource_exhausted", "not_found"))
        if is_recoverable and fallback_model and fallback_model != primary_model:
            log.warning("Primary model %s failed during itinerary team planning (%s); falling back to %s", primary_model, exc, fallback_model)
            try:
                fallback_team = _build_team(fallback_model)
                result = await asyncio.wait_for(
                    fallback_team.run(task=TextMessage(content=full_task, source="User")), timeout)
            except asyncio.TimeoutError as f_exc:
                raise AIError("The AI took too long to respond. Please try again.") from f_exc
            except Exception as f_exc:  # noqa: BLE001
                raise friendly_error(f_exc) from f_exc
        else:
            raise friendly_error(exc) from exc

    word = ai_settings.TERMINATION_WORD
    transcript, plan, research = [], "", ""
    for m in result.messages:
        src, txt = getattr(m, "source", "agent"), _text(m)
        if src == "User" or not txt:
            continue
        transcript.append({"source": src, "content": txt})
        if src == "Travel_Planner":
            plan = txt
        elif src == "Researcher":
            research = re.sub(rf"\s*{re.escape(word)}\W*$", "", txt, flags=re.IGNORECASE).strip()
    if not plan:
        raise AIError("The planner didn't produce an itinerary. Please try again.")
    return PlanResult(plan=plan, research=research, search_used=used, transcript=transcript,
                      stop_reason=str(getattr(result, "stop_reason", "")))
