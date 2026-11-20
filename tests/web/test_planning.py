from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    from autogen_ext.models.replay import ReplayChatCompletionClient

    import server.ai.workflow as wf

    def scripted():
        return ReplayChatCompletionClient(
            ["## Day 1: Old city\n**Morning**\n- City Palace\n\n## Day 2: Lakes\n**Evening**\n- Boat ride",
             "Looks good. Carry cash and book the boat early. stop"],
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
