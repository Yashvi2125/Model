import pytest
from starlette.websockets import WebSocketDisconnect

from server.ai.agents import ExtractedPreferences
from tests.web.conftest import make_client, make_trip, wait_for


def test_messages_saved_and_retrieved(user_a, user_b):
    t = make_trip(user_a)
    tid = t["id"]
    user_b.post("/api/trips/join", json={"code": t["code"]})
    sent = user_a.post(f"/api/trips/{tid}/messages", json={"content": "Hello team <b>x</b>"})
    assert sent.status_code == 201 and sent.json()["sender_name"] == "Asha Patel"
    msgs = user_b.get(f"/api/trips/{tid}/messages").json()
    assert any(m["content"] == "Hello team <b>x</b>" for m in msgs)  # stored verbatim; React escapes on render
    assert user_b.get(f"/api/trips/{tid}/messages", params={"after_id": msgs[-1]["id"]}).json() == []
    assert user_a.post(f"/api/trips/{tid}/messages", json={"content": "   "}).status_code == 422


def test_websocket_requires_login_and_membership(user_a, user_b):
    t = make_trip(user_a)
    url = f"/api/ws/trips/{t['id']}"
    with pytest.raises(WebSocketDisconnect) as e:
        with make_client().websocket_connect(url):
            pass
    assert e.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as e:
        with user_b.websocket_connect(url):  # logged in but not a member
            pass
    assert e.value.code == 4403
    with pytest.raises(WebSocketDisconnect) as e:
        with user_a.websocket_connect(url, headers={"origin": "https://evil.example"}):
            pass
    assert e.value.code == 4403


def test_websocket_receives_new_messages(user_a, user_b):
    t = make_trip(user_a)
    user_b.post("/api/trips/join", json={"code": t["code"]})
    with user_b.websocket_connect(f"/api/ws/trips/{t['id']}") as ws:
        ws.receive_json()  # initial presence event
        seen = []
        user_a.post(f"/api/trips/{t['id']}/messages", json={"content": "live message"})
        for _ in range(6):
            ev = ws.receive_json()
            seen.append(ev)
            if ev["type"] == "message" and ev["message"]["content"] == "live message":
                break
        assert any(e["type"] == "message" and e["message"]["content"] == "live message" for e in seen)


def test_ai_mention_reaches_agents_and_creates_pending_suggestion(user_a, monkeypatch):
    t = make_trip(user_a, interests=[])
    calls = {}

    async def fake_extract(text, traveller, ctx):
        calls["extract"] = (text, traveller)
        return ExtractedPreferences(destination="Udaipur", trip_days=3, budget_per_person=8000, interests=["culture"], confidence=0.9)

    async def fake_reply(ctx, recent, sender, text, noted):
        calls["reply"] = noted
        return "Noted! Review it in Preferences."

    monkeypatch.setattr("server.ai.agents.extract_preferences", fake_extract)
    monkeypatch.setattr("server.ai.agents.chat_reply", fake_reply)
    user_a.post(f"/api/trips/{t['id']}/messages",
                json={"content": "@ai I prefer a three-day trip to Udaipur, with historical places and a budget of ₹8,000 per person."})
    ai = wait_for(lambda: next((m for m in user_a.get(f"/api/trips/{t['id']}/messages").json() if m["kind"] == "ai"), None))
    assert ai["content"].startswith("Noted") and ai["sender_name"] == "MileMates AI"
    assert calls["extract"][1] == "Asha Patel" and "@ai" not in calls["extract"][0]

    ov = user_a.get(f"/api/trips/{t['id']}/preferences").json()
    me = ov["members"][0]
    assert me["interests"] == []  # NOT silently applied
    assert len(ov["my_suggestions"]) == 1 and ov["my_suggestions"][0]["data"]["budget_max"] == 8000

    sid = ov["my_suggestions"][0]["id"]
    acc = user_a.post(f"/api/trips/{t['id']}/preferences/suggestions/{sid}/accept").json()
    me = acc["members"][0]
    assert me["interests"] == ["culture"] and me["sources"]["interests"] == "ai" and me["budget_max"] == 8000


def test_ordinary_chat_does_not_call_ai(user_a, monkeypatch):
    t = make_trip(user_a)

    async def boom(*a, **k):
        raise AssertionError("AI must not be called for small talk")

    monkeypatch.setattr("server.ai.agents.extract_preferences", boom)
    monkeypatch.setattr("server.ai.agents.chat_reply", boom)
    user_a.post(f"/api/trips/{t['id']}/messages", json={"content": "lol see you all tomorrow, who is bringing snacks?"})
    import time
    time.sleep(0.4)
    assert not [m for m in user_a.get(f"/api/trips/{t['id']}/messages").json() if m["kind"] == "ai"]


def test_ai_failure_is_reported_in_chat_not_faked(user_a, monkeypatch):
    t = make_trip(user_a)
    from server.ai.client import AIError

    async def fail(*a, **k):
        raise AIError("The AI service is rate-limited right now. Wait a minute and try again.")

    monkeypatch.setattr("server.ai.agents.extract_preferences", fail)
    monkeypatch.setattr("server.ai.agents.chat_reply", fail)
    user_a.post(f"/api/trips/{t['id']}/messages", json={"content": "@ai plan something"})
    ai = wait_for(lambda: next((m for m in user_a.get(f"/api/trips/{t['id']}/messages").json() if m["kind"] == "ai"), None))
    assert ai["meta"]["error"] is True and "rate-limited" in ai["content"]


def test_suggestions_belong_to_their_owner(user_a, user_b, monkeypatch):
    t = make_trip(user_a)
    user_b.post("/api/trips/join", json={"code": t["code"]})

    async def ex(*a, **k):
        return ExtractedPreferences(interests=["beaches"], confidence=0.9)

    async def rp(*a, **k):
        return "ok"

    monkeypatch.setattr("server.ai.agents.extract_preferences", ex)
    monkeypatch.setattr("server.ai.agents.chat_reply", rp)
    user_b.post(f"/api/trips/{t['id']}/messages", json={"content": "@ai I love beaches"})
    sid = wait_for(lambda: (user_b.get(f"/api/trips/{t['id']}/preferences").json()["my_suggestions"] or [{}])[0].get("id"))
    assert user_a.post(f"/api/trips/{t['id']}/preferences/suggestions/{sid}/accept").status_code == 404  # not Asha's
    assert user_b.post(f"/api/trips/{t['id']}/preferences/suggestions/{sid}/dismiss").status_code == 200


def test_direct_preferences_override_and_clear(user_a):
    t = make_trip(user_a)
    r = user_a.put(f"/api/trips/{t['id']}/preferences/me", json={"accommodation": "Boutique hotel", "budget_max": 9000})
    me = r.json()["members"][0]
    assert me["sources"]["accommodation"] == "direct" and "accommodation" not in me["missing"]
    r = user_a.put(f"/api/trips/{t['id']}/preferences/me", json={"accommodation": None})
    assert "accommodation" in r.json()["members"][0]["missing"]
    assert user_a.put(f"/api/trips/{t['id']}/preferences/me", json={"budget_min": 5, "budget_max": 1}).status_code == 422


def test_checklist_persists(user_a, user_b):
    t = make_trip(user_a)
    tid = t["id"]
    items = user_a.get(f"/api/trips/{tid}/checklist").json()
    assert user_a.patch(f"/api/trips/{tid}/checklist/{items[0]['id']}", json={"done": True}).json()["done"] is True
    assert user_a.get(f"/api/trips/{tid}/checklist").json()[0]["done"] is True
    new = user_a.post(f"/api/trips/{tid}/checklist", json={"text": "Book cab"}).json()
    assert user_a.delete(f"/api/trips/{tid}/checklist/{new['id']}").status_code == 204
    assert user_b.patch(f"/api/trips/{tid}/checklist/{items[0]['id']}", json={"done": False}).status_code == 404
