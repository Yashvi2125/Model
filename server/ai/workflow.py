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
from server.ai.client import (
    AIError,
    ai_status,
    friendly_error,
    get_client,
    is_model_available,
    is_rate_limit_error,
    mark_model_cooldown,
)
from server.config import get_settings

log = logging.getLogger("tripmate.workflow")


@dataclass
class PlanResult:
    plan: str
    research: str
    search_used: bool
    transcript: list = field(default_factory=list)
    stop_reason: str = ""
    model_used: str = ""


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
        # max_turns=2 ensures Turn 1 is Planner and Turn 2 is Researcher, minimizing quota usage
        return create_travel_team(
            planner=create_planner_agent(client=client),
            researcher=create_researcher_agent(client=client),
            max_turns=2,
        )

    timeout = get_settings().itinerary_timeout_seconds
    model_chain = list(ai_settings.GEMINI_MODEL_CHAIN)
    if not model_chain:
        model_chain = [ai_settings.GEMINI_MODEL or "gemini-3.5-flash-lite"]

    candidate_models = [m for m in model_chain if is_model_available(m)]
    if not candidate_models:
        candidate_models = model_chain

    result = None
    last_exc = None
    model_that_answered = None

    for model_name in candidate_models:
        log.info("Attempting itinerary generation with model '%s'", model_name)
        try:
            team = _build_team(model_name)
            result = await asyncio.wait_for(
                team.run(task=TextMessage(content=full_task, source="User")),
                timeout=timeout,
            )
            model_that_answered = model_name
            log.info("Itinerary planning answered successfully by model '%s'", model_name)
            break
        except asyncio.TimeoutError as exc:
            last_exc = exc
            log.warning("Model '%s' timed out during itinerary planning after %ds", model_name, timeout)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if is_rate_limit_error(exc):
                mark_model_cooldown(model_name, exc)
                log.warning("Model '%s' hit rate limit during planning (%s); falling back to next model", model_name, exc)
            else:
                err_str = str(exc).lower()
                is_recoverable = any(k in err_str for k in ("503", "404", "overloaded", "unavailable", "not_found"))
                if is_recoverable:
                    log.warning("Model '%s' encountered recoverable error (%s); trying next model in chain", model_name, exc)
                else:
                    raise friendly_error(exc) from exc

    if result is None:
        raise friendly_error(last_exc or RuntimeError("All AI models in chain failed"))

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

    # Rule 5: A run that ends without a completed itinerary must be reported as a failure
    # with a Retry button and never saved as a valid version.
    if not plan or not plan.strip():
        log.warning("Itinerary run ended without a plan")
        raise AIError("The planner didn't produce a complete itinerary. Please try again.")

    return PlanResult(
        plan=plan,
        research=research,
        search_used=used,
        transcript=transcript,
        stop_reason=str(getattr(result, "stop_reason", "")),
        model_used=model_that_answered or ai_settings.GEMINI_MODEL,
    )
