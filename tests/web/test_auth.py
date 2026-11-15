from sqlalchemy import select

from server.db import SessionLocal
from server.models import AuthSession, User
from tests.web.conftest import PASSWORD, register


def test_register_login_logout_flow(client):
    r = register(client)
    assert r.status_code == 201
    assert "password" not in r.text and "hash" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/auth/me").json()["email"] == "asha@example.com"  # session survives "refresh"

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401  # session invalidated server-side
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession)) is None

    bad = client.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong-pass1"})
    assert bad.status_code == 401 and "Incorrect email or password" in bad.json()["detail"]
    ok = client.post("/api/auth/login", json={"email": "ASHA@example.com", "password": PASSWORD})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_password_is_hashed_and_email_unique(client):
    register(client)
    with SessionLocal() as db:
        u = db.scalar(select(User))
        assert u.password_hash.startswith("$argon2") and PASSWORD not in u.password_hash
    dup = register(client, name="Someone Else", email="Asha@Example.com")
    assert dup.status_code == 409


def test_validation_errors(client):
    weak = client.post("/api/auth/register", json={"name": "Asha P", "email": "a@b.co", "password": "short",
                                                   "accept_terms": True})
    assert weak.status_code == 422 and "Password" in weak.json()["detail"]
    mismatch = client.post("/api/auth/register", json={"name": "Asha P", "email": "a@b.co", "password": PASSWORD,
                                                       "confirm_password": "Different1!", "accept_terms": True})
    assert mismatch.status_code == 422
    no_terms = client.post("/api/auth/register", json={"name": "Asha P", "email": "a@b.co", "password": PASSWORD})
    assert no_terms.status_code == 422
    assert client.post("/api/auth/register", json={"name": "Asha P", "email": "not-an-email", "password": PASSWORD,
                                                   "accept_terms": True}).status_code == 422


def test_protected_routes_need_login(client):
    for path in ["/api/trips", "/api/auth/me", "/api/users/me", "/api/ai/status"]:
        assert client.get(path).status_code == 401, path


def test_cross_site_post_is_blocked(client):
    r = client.post("/api/auth/login", json={"email": "a@b.co", "password": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_profile_and_password_change(user_a):
    assert user_a.patch("/api/users/me", json={"name": "Asha P. Patel"}).json()["name"] == "Asha P. Patel"
    assert user_a.post("/api/users/me/password", json={"current_password": "nope", "new_password": "N3wPassword!"}).status_code == 400
    assert user_a.post("/api/users/me/password", json={"current_password": PASSWORD, "new_password": "N3wPassword!"}).status_code == 204
    user_a.post("/api/auth/logout")
    assert user_a.post("/api/auth/login", json={"email": "asha@example.com", "password": PASSWORD}).status_code == 401
    assert user_a.post("/api/auth/login", json={"email": "asha@example.com", "password": "N3wPassword!"}).status_code == 200


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] is True
