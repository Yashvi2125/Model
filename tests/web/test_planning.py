from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.ai.workflow import PlanResult
from server.services.budget import compute_budget
from server.services.itinerary_parser import parse_itinerary
from tests.web.conftest import make_trip, wait_for

PLAN = """Summary line.

## Day 1: Old city
**Morning**
- City Palace (entry approx ₹300 per person)
**Evening**
- Lake Pichola boat ride

## Day 2: Lakes
**Afternoon**
- Sajjangarh

## Stay & transport tips
Book early. https://example.com/tips
"""


def test_conflict_detection_votes_and_ai_failure(user_a, user_b, monkeypatch):
    t = make_trip(user_a, interests=["adventure"], budget_total=None, budget_per_person=20000)
    tid = t["id"]
    user_b.post("/api/trips/join", json={"code": t["code"]})
    user_b.put(f"/api/trips/{tid}/preferences/me", json={"interests": ["relaxation"], "budget_max": 6000})

    async def no_ai(*a, **k):
        from server.ai.client import AIError
        raise AIError("The AI assistant isn't set up yet.")

    monkeypatch.setattr("server.ai.agents.resolve_conflicts", no_ai)
    r = user_a.post(f"/api/trips/{tid}/conflicts/analyze").json()
    kinds = {c["kind"] for c in r["conflicts"]}
    assert {"budget", "activities"} <= kinds and r["ai_error"]  # facts still shown, no fake compromise
    assert all(c["suggestion"] is None for c in r["conflicts"])
    cid = r["conflicts"][0]["id"]
    assert user_a.post(f"/api/trips/{tid}/conflicts/{cid}/vote", json={"vote": "agree"}).status_code == 400

    async def ai(trip_ctx, detected, *args, **kwargs):
        return {"suggestions": {c["kind"]: f"Compromise for {c['kind']}" for c in detected}, "additional": []}

    monkeypatch.setattr("server.ai.agents.resolve_conflicts", ai)
    r = user_a.post(f"/api/trips/{tid}/conflicts/analyze").json()
    c = next(c for c in r["conflicts"] if c["kind"] == "budget")
    assert c["suggestion"] == "Compromise for budget" and c["status"] == "open"
    r = user_a.post(f"/api/trips/{tid}/conflicts/{c['id']}/vote", json={"vote": "agree"}).json()
    assert next(x for x in r["conflicts"] if x["id"] == c["id"])["status"] == "open"  # one yes is not a decision
    r = user_b.post(f"/api/trips/{tid}/conflicts/{c['id']}/vote", json={"vote": "agree"}).json()
    assert next(x for x in r["conflicts"] if x["id"] == c["id"])["status"] == "accepted"
    assert user_b.post(f"/api/trips/{tid}/conflicts/{c['id']}/dismiss").status_code == 403


def test_itinerary_generation_runs_agent_workflow_and_budget(user_a, monkeypatch):
    t = make_trip(user_a)
    seen = {}

    async def fake_generate(prompt, query):
        seen["prompt"], seen["query"] = prompt, query
        return PlanResult(plan=PLAN, research="Tip: carry cash.", search_used=True, transcript=[{"source": "Travel_Planner", "content": PLAN}])

    async def fake_items(plan, currency, travelers, days):
        return [{"category": "activities", "label": "City Palace", "amount": 300, "basis": "per_person", "source_text": "approx ₹300 per person"},
                {"category": "accommodation", "label": "Hotel", "amount": 5000, "basis": "per_night_group", "source_text": "x"}]

    monkeypatch.setattr("server.services.itinerary_service.generate_plan", fake_generate)
    monkeypatch.setattr("server.ai.agents.extract_budget_items", fake_items)
    r = user_a.post(f"/api/trips/{t['id']}/itinerary/generate", json={"instructions": "More food"})
    assert r.status_code == 202 and r.json()["status"] == "running"
    it = wait_for(lambda: (lambda i: i if i and i["status"] != "running" else None)(user_a.get(f"/api/trips/{t['id']}/itinerary").json()))
    assert it["status"] == "succeeded" and it["plan_markdown"] == PLAN  # original text preserved
    assert it["days"]["structured"] and [d["day"] for d in it["days"]["days"]] == [1, 2]
    assert "Udaipur" in seen["prompt"] and "More food" in seen["prompt"] and "3 people" in seen["prompt"]
    b = wait_for(lambda: (lambda x: x if x["has_estimate"] else None)(user_a.get(f"/api/trips/{t['id']}/budget").json()))
    # 300*3 travellers + 5000*3 nights = 900 + 15000
    assert b["total"] == 15900 and b["per_person"] == 5300 and b["within_budget"] is True and b["difference"] == 29100
    assert user_a.get(f"/api/trips/{t['id']}").json()["status"] == "itinerary_ready"


def test_itinerary_failure_is_visible(user_a, monkeypatch):
    t = make_trip(user_a)
    from server.ai.client import AIError

    async def fail(prompt, query):
        raise AIError("The AI took too long to respond. Please try again.")

    monkeypatch.setattr("server.services.itinerary_service.generate_plan", fail)
    user_a.post(f"/api/trips/{t['id']}/itinerary/generate", json={})
    it = wait_for(lambda: (lambda i: i if i and i["status"] != "running" else None)(user_a.get(f"/api/trips/{t['id']}/itinerary").json()))
    assert it["status"] == "failed" and "too long" in it["error"] and it["plan_markdown"] is None


def test_generate_needs_destination_and_api_key(user_a, monkeypatch):
    t = make_trip(user_a, destination=None, destination_undecided=True)
    assert user_a.post(f"/api/trips/{t['id']}/itinerary/generate", json={}).status_code == 400
    monkeypatch.setattr("config.settings.GEMINI_API_KEY", None)
    r = user_a.post(f"/api/trips/{t['id']}/itinerary/generate", json={})
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]


@pytest.mark.asyncio
async def test_workflow_uses_existing_planner_researcher_team(monkeypatch):
    """generate_plan() must drive teams.travel_team.create_travel_team with FRESH planner/researcher agents."""
    import server.ai.workflow as wf

    created = {}

    class FakeTeam:
        async def run(self, task):
            created["task"] = task.content
            msg = lambda s, c: SimpleNamespace(source=s, content=c)
            return SimpleNamespace(messages=[msg("User", "x"), msg("Travel_Planner", "## Day 1\nPlan body"),
                                             msg("Researcher", "Good plan. Carry cash. stop")], stop_reason="Text 'stop' mentioned")

    def fake_team(planner=None, researcher=None, max_turns=7):
        created["planner"], created["researcher"] = planner, researcher
        return FakeTeam()

    async def no_search(q):
        return "\n[Live Verified Research Data from Tavily Search]: ...\n", True

    monkeypatch.setattr("teams.travel_team.create_travel_team", fake_team)
    monkeypatch.setattr("agents.planner.create_planner_agent", lambda *a, **k: "FRESH_PLANNER")
    monkeypatch.setattr("agents.researcher.create_researcher_agent", lambda *a, **k: "FRESH_RESEARCHER")
    monkeypatch.setattr(wf, "_live_research", no_search)
    res = await wf.generate_plan("Plan a trip", "query")
    assert created["planner"] == "FRESH_PLANNER" and created["researcher"] == "FRESH_RESEARCHER"
    assert "Live Verified Research Data" in created["task"]
    assert res.plan.startswith("## Day 1") and res.research == "Good plan. Carry cash." and res.search_used


def test_budget_maths_is_programmatic():
    items = [{"category": "food", "amount": 500, "basis": "per_person_per_day"},
             {"category": "transport", "amount": 3000, "basis": "group_total"},
             {"category": "bogus", "amount": 100, "basis": "per_person"},
             {"category": "food", "amount": "abc", "basis": "per_person"}]
    b = compute_budget(items, 4, date(2027, 1, 1), date(2027, 1, 3), None, 3000)  # 3 days, 4 people
    assert b["total"] == 500 * 4 * 3 + 3000 + 400 == 9400
    assert b["per_person"] == 2350.0 and b["group_budget"] == 12000 and b["within_budget"] and b["difference"] == 2600
    cats = {c["category"]: c["total"] for c in b["categories"]}
    assert cats == {"food": 6000, "transport": 3000, "other": 400}
    over = compute_budget(items, 4, date(2027, 1, 1), date(2027, 1, 3), 5000, None)
    assert over["within_budget"] is False and over["difference"] == -4400
    assert compute_budget(None, 2, date(2027, 1, 1), date(2027, 1, 2), None, None)["has_estimate"] is False
    thirds = compute_budget([{"category": "food", "amount": 100, "basis": "group_total"}], 3, date(2027, 1, 1), date(2027, 1, 1), None, None)
    assert thirds["per_person"] == 33.33


def test_parser_keeps_unstructured_text():
    p = parse_itinerary("Just a paragraph without days. https://x.org/a")
    assert p["structured"] is False and p["overview"].startswith("Just") and p["sources"] == ["https://x.org/a"]
    p = parse_itinerary(PLAN)
    assert p["days"][0]["sections"][0]["period"] == "morning" and "Book early" in p["tail"]


def test_research_endpoint_degrades_without_network(user_a, monkeypatch):
    t = make_trip(user_a)

    async def down(url, params):
        raise RuntimeError("no network")

    monkeypatch.setattr("server.services.research._get", down)
    r = user_a.get(f"/api/trips/{t['id']}/research").json()
    assert r["location"] is None and r["weather"] is None and r["errors"]  # clear unavailable state, no fake data


async def test_workflow_runs_real_autogen_team_with_replayed_model(monkeypatch):
    """No mocks of the team itself: the project's real RoundRobinGroupChat + agents run against a scripted model client.
    This proves the web workflow drives the existing agents; it does NOT prove live Gemini works."""
    import config.settings as ai_settings
    from autogen_ext.models.replay import ReplayChatCompletionClient

    import server.ai.workflow as wf

    def scripted():
        return ReplayChatCompletionClient(
            ["## Day 1: Old city\n**Morning**\n- City Palace\n\n## Day 2: Lakes\n**Evening**\n- Boat ride",
             f"Looks good. Carry cash and book the boat early. {ai_settings.TERMINATION_WORD}"],
            model_info={"vision": False, "function_calling": True, "json_output": False, "family": "unknown", "structured_output": False})

    shared = scripted()  # planner and researcher take turns on one scripted client
    monkeypatch.setattr("agents.planner.model_client", shared)
    monkeypatch.setattr("agents.researcher.model_client", shared)

    async def no_search(q):
        return "", False

    monkeypatch.setattr(wf, "_live_research", no_search)
    res = await wf.generate_plan("Plan a 2-day trip to Udaipur for 3 people", "Udaipur")
    assert res.plan.startswith("## Day 1") and "Day 2" in res.plan
    assert res.research == "Looks good. Carry cash and book the boat early."  # termination word stripped
    assert [t["source"] for t in res.transcript] == ["Travel_Planner", "Researcher"]
    assert parse_itinerary(res.plan)["structured"] is True


async def test_tavily_research_containing_word_stop_does_not_terminate_early(monkeypatch):
    """Prove that research text or prompts containing words like 'stop', 'bus stop', 'non-stop'
    do NOT trigger early termination. The chat continues to the final agent.
    """
    import config.settings as ai_settings
    from autogen_agentchat.messages import TextMessage
    from utils.utils import get_termination_condition

    # 1. Termination condition does not fire on 'stop' in text
    cond = get_termination_condition()
    msg_with_stops = TextMessage(
        content="Research data: Bus stop located 100m away. Non-stop metro service. Make a quick stop at Lake Pichola.",
        source="User"
    )
    # TextMentionTermination check takes a sequence of messages
    result = await cond([msg_with_stops])
    assert result is None  # Must NOT terminate on normal words like 'stop'

    # 2. Only fires on the sentinel termination token
    msg_with_sentinel = TextMessage(
        content=f"Final itinerary verified. {ai_settings.TERMINATION_WORD}",
        source="Researcher"
    )
    result_sentinel = await cond([msg_with_sentinel])
    assert result_sentinel is not None  # Terminates properly on the exact sentinel token


def test_conflicts_report_how_many_members_have_shared(user_a, user_b, monkeypatch):
    t = make_trip(user_a)
    tid = t["id"]
    monkeypatch.setattr("server.ai.agents.resolve_conflicts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI needed")))
    solo = user_a.get(f"/api/trips/{tid}/conflicts").json()
    assert solo["member_count"] == 1 and solo["members_sharing"] == 1 and solo["conflicts"] == []
    user_b.post("/api/trips/join", json={"code": t["code"]})
    joined = user_a.get(f"/api/trips/{tid}/conflicts").json()
    assert joined["member_count"] == 2 and joined["members_sharing"] == 1  # Ravi hasn't shared anything yet
    user_b.put(f"/api/trips/{tid}/preferences/me", json={"interests": ["nightlife"]})
    assert user_a.get(f"/api/trips/{tid}/conflicts").json()["members_sharing"] == 2


@pytest.mark.asyncio
async def test_hosted_qwen_primary_with_gemini_fallback(monkeypatch):
    """Verifies that when LLM_PROVIDER='qwen' and LOCAL_LLM_API_KEY is non-empty,
    Qwen runs first as primary for full itinerary generation, with Gemini as automatic fallback.
    When LOCAL_LLM_API_KEY is empty (local CPU Ollama), Gemini remains primary.
    """
    import server.ai.workflow as wf
    import config.settings as ai_settings
    import server.config as srv_config
    from autogen_agentchat.messages import TextMessage

    # 1. Test hosted Qwen primary: LLM_PROVIDER="qwen" and LOCAL_LLM_API_KEY set
    monkeypatch.setattr(ai_settings, "LLM_PROVIDER", "qwen")
    monkeypatch.setattr(ai_settings, "LOCAL_LLM_API_KEY", "gsk_test_groq_key")
    monkeypatch.setattr(ai_settings, "LOCAL_LLM_MODEL", "qwen-2.5-32b")
    monkeypatch.setattr(ai_settings, "GEMINI_MODEL_CHAIN", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"])
    monkeypatch.setattr(srv_config.get_settings(), "llm_provider", "qwen")
    monkeypatch.setattr(srv_config.get_settings(), "local_llm_api_key", "gsk_test_groq_key")
    monkeypatch.setattr(srv_config.get_settings(), "local_llm_model", "qwen-2.5-32b")

    # Track which models are attempted in order
    attempted_models = []

    class MockTravelTeam:
        def __init__(self, model_name):
            self.model_name = model_name

        async def run(self, task):
            attempted_models.append(self.model_name)
            if "qwen" in self.model_name.lower():
                # Simulate Qwen failing with temporary error to trigger fallback
                raise RuntimeError("503 Service Unavailable: Hosted Qwen busy")
            # Gemini fallback succeeds
            word = ai_settings.TERMINATION_WORD
            return type("Result", (), {
                "messages": [
                    TextMessage(content=f"## Day 1: Paris\nVisit Eiffel Tower\n{word}", source="Travel_Planner"),
                    TextMessage(content=f"Research complete.\n{word}", source="Researcher"),
                ]
            })()

    def mock_build_team(model_name=None):
        return MockTravelTeam(model_name)

    monkeypatch.setattr(wf, "_build_team", mock_build_team)
    monkeypatch.setattr(wf, "_live_research", AsyncMock(return_value=("", False)))

    res = await wf.generate_plan("Plan a 1-day trip to Paris", "Paris")
    # Qwen must be attempted FIRST, followed by Gemini fallback
    assert attempted_models[0] == "qwen-2.5-32b"
    assert attempted_models[1] == "gemini-3.5-flash-lite"
    assert "Eiffel Tower" in res.plan

    # 2. Test local CPU Ollama: LOCAL_LLM_API_KEY is empty -> Gemini primary
    attempted_models.clear()
    monkeypatch.setattr(ai_settings, "LOCAL_LLM_API_KEY", "")
    monkeypatch.setattr(srv_config.get_settings(), "local_llm_api_key", "")

    class MockGeminiPrimaryTeam:
        def __init__(self, model_name):
            self.model_name = model_name

        async def run(self, task):
            attempted_models.append(self.model_name)
            word = ai_settings.TERMINATION_WORD
            return type("Result", (), {
                "messages": [
                    TextMessage(content=f"## Day 1: Paris\nVisit Louvre\n{word}", source="Travel_Planner"),
                    TextMessage(content=f"Research complete.\n{word}", source="Researcher"),
                ]
            })()

    monkeypatch.setattr(wf, "_build_team", lambda m=None: MockGeminiPrimaryTeam(m))
    res2 = await wf.generate_plan("Plan a 1-day trip to Paris", "Paris")
    assert attempted_models[0] == "gemini-3.5-flash-lite"
    assert "Louvre" in res2.plan


def test_single_day_swap_modifies_and_persists_itinerary_day(user_a, monkeypatch):
    """Test that single-day customize ('Update Day') modifies the target day's activities
    according to user instructions, persists to PostgreSQL/Supabase via flag_modified,
    and returns the updated day so the UI renders it immediately.
    """
    from server.db import SessionLocal
    from server.models import Itinerary

    t = make_trip(user_a)
    trip_id = t["id"]

    # Seed an itinerary with 2 days
    initial_days = {
        "overview": "Paris trip",
        "days": [
            {
                "day": 1,
                "title": "Day 1: Arrival",
                "intro": "Welcome",
                "sections": [{"period": "morning", "content": "Check into hotel"}],
                "places": []
            },
            {
                "day": 2,
                "title": "Day 2: Art & Gardens",
                "intro": "",
                "sections": [
                    {"period": "morning", "content": "Visit the Louvre Museum early."},
                    {"period": "afternoon", "content": "Picnic in Tuileries Garden."},
                    {"period": "evening", "content": "Walk along the Seine."}
                ],
                "places": []
            }
        ]
    }

    with SessionLocal() as session:
        it = Itinerary(
            trip_id=trip_id,
            version=1,
            status="succeeded",
            days=initial_days,
            plan_markdown="## Day 1\nCheck into hotel\n## Day 2\nVisit the Louvre Museum early."
        )
        session.add(it)
        session.commit()

    # Mock swap_itinerary_day to return updated Day 2 with user instruction applied
    async def mock_swap_itinerary_day(day_data, instruction, trip_ctx=""):
        assert "Eiffel tower" in instruction
        assert day_data["day"] == 2
        return {
            "day": 2,
            "title": "Day 2: Art & Eiffel Tower",
            "intro": "Updated day with iconic tower",
            "sections": [
                {"period": "morning", "content": "Visit the Eiffel Tower and take photos."},
                {"period": "afternoon", "content": "Picnic in Tuileries Garden."},
                {"period": "evening", "content": "Walk along the Seine."}
            ]
        }, "qwen"

    monkeypatch.setattr("server.ai.local_llm.swap_itinerary_day", mock_swap_itinerary_day)

    # 1. Call POST day swap endpoint
    resp = user_a.post(
        f"/api/trips/{trip_id}/itinerary/days/2/swap",
        json={"instruction": "Add Eiffel tower visit on this day"}
    )
    assert resp.status_code == 200
    data = resp.json()

    # Verify Day 2 in returned response has Eiffel Tower
    day2 = next(d for d in data["days"]["days"] if d["day"] == 2)
    assert "Eiffel Tower" in day2["title"] or "Eiffel Tower" in day2["sections"][0]["content"]

    # 2. Refetch via GET endpoint to ensure changes are 100% persisted in DB
    refetch = user_a.get(f"/api/trips/{trip_id}/itinerary").json()
    refetched_day2 = next(d for d in refetch["days"]["days"] if d["day"] == 2)
    assert refetched_day2["sections"][0]["content"] == "Visit the Eiffel Tower and take photos."
    assert refetched_day2["title"] == "Day 2: Art & Eiffel Tower"
    assert "Eiffel Tower" in refetch["plan_markdown"]

