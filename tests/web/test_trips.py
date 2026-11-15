from tests.web.conftest import make_client, make_trip, register


def test_create_list_and_details(user_a):
    t = make_trip(user_a)
    assert len(t["code"]) == 8 and t["my_role"] == "owner" and t["member_count"] == 1
    lst = user_a.get("/api/trips").json()
    assert [x["name"] for x in lst] == ["Udaipur getaway"]
    assert user_a.get(f"/api/trips/{t['id']}").json()["members"][0]["role"] == "owner"
    prefs = user_a.get(f"/api/trips/{t['id']}/preferences").json()
    assert prefs["members"][0]["interests"] == ["culture", "food"]  # organiser's answers seed their preferences
    assert prefs["members"][0]["sources"]["interests"] == "direct"
    assert len(user_a.get(f"/api/trips/{t['id']}/checklist").json()) >= 5


def test_trip_validation(user_a):
    base = {"name": "X trip", "destination": "Goa", "start_date": "2027-03-10", "end_date": "2027-03-05", "travelers_count": 2}
    assert user_a.post("/api/trips", json=base).status_code == 422
    assert user_a.post("/api/trips", json={**base, "end_date": "2027-03-12", "destination": None}).status_code == 422
    ok = user_a.post("/api/trips", json={**base, "end_date": "2027-03-12", "destination": None, "destination_undecided": True})
    assert ok.status_code == 201


def test_join_with_code_and_duplicates(user_a, user_b):
    t = make_trip(user_a)
    pv = user_b.get(f"/api/trips/preview/{t['code'].lower()}")
    assert pv.status_code == 200 and pv.json()["already_member"] is False and "trip_id" not in {k for k, v in pv.json().items() if v}
    assert user_b.post("/api/trips/join", json={"code": t["code"][:4] + "-" + t["code"][4:]}).status_code == 200
    again = user_b.post("/api/trips/join", json={"code": t["code"]})
    assert again.status_code == 200
    d = user_a.get(f"/api/trips/{t['id']}").json()
    assert d["member_count"] == 2  # no duplicate membership
    assert user_b.get("/api/trips").json()[0]["my_role"] == "member"


def test_invalid_code_and_closed_joining(user_a, user_b):
    assert user_b.post("/api/trips/join", json={"code": "ZZZZZZZZ"}).status_code == 404
    t = make_trip(user_a)
    assert user_b.patch(f"/api/trips/{t['id']}/joining", json={"is_joinable": False}).status_code == 404  # non-member
    user_a.patch(f"/api/trips/{t['id']}/joining", json={"is_joinable": False})
    assert user_b.post("/api/trips/join", json={"code": t["code"]}).status_code == 403
    new = user_a.post(f"/api/trips/{t['id']}/invite/regenerate").json()["code"]
    assert new != t["code"]


def test_non_members_cannot_see_anything(user_a, user_b):
    t = make_trip(user_a)
    tid = t["id"]
    for path in ["", "/messages", "/preferences", "/conflicts", "/itinerary", "/budget", "/checklist", "/research"]:
        assert user_b.get(f"/api/trips/{tid}{path}").status_code == 404, path
    assert user_b.post(f"/api/trips/{tid}/messages", json={"content": "hi"}).status_code == 404
    assert user_b.delete(f"/api/trips/{tid}").status_code == 404
    assert user_b.get("/api/trips").json() == []
    assert make_client().get(f"/api/trips/{tid}").status_code == 401


def test_only_owner_can_delete_and_remove(user_a, user_b):
    t = make_trip(user_a)
    user_b.post("/api/trips/join", json={"code": t["code"]})
    assert user_b.delete(f"/api/trips/{t['id']}").status_code == 403
    uid = user_a.get(f"/api/trips/{t['id']}").json()["members"][1]["user_id"]
    assert user_b.delete(f"/api/trips/{t['id']}/members/{uid}").status_code == 403
    assert user_a.delete(f"/api/trips/{t['id']}/members/{uid}").status_code == 204
    assert user_b.get(f"/api/trips/{t['id']}").status_code == 404


def test_data_persists_across_app_restart(user_a):
    t = make_trip(user_a)
    from fastapi.testclient import TestClient
    from server.main import app
    with TestClient(app) as restarted:  # new app lifespan + new cookie jar, same database
        assert restarted.post("/api/auth/login", json={"email": "asha@example.com", "password": "Sup3rSecret!"}).status_code == 200
        assert restarted.get("/api/trips").json()[0]["id"] == t["id"]
