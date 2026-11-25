"""Fixtures for the web backend tests."""
import os
import time

from tests.db_guard import setup_test_database, verify_test_database_safety

# Ensures test DB is configured even if tests/web is invoked directly without parent conftest
setup_test_database()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import models  # noqa: E402, F401
from server.db import Base, engine  # noqa: E402
from server.main import app  # noqa: E402
from server.security import reset_rate_limits  # noqa: E402

PASSWORD = "Sup3rSecret!"


@pytest.fixture(autouse=True)
def fresh_db():
    verify_test_database_safety(engine.url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_rate_limits()
    try:
        from server.ai.gateway import gateway
        gateway.reset()
    except Exception:
        pass
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_client() -> TestClient:
    return TestClient(app)


def register(c: TestClient, name="Asha Patel", email="asha@example.com", password=PASSWORD):
    return c.post("/api/auth/register", json={"name": name, "email": email, "password": password,
                                              "confirm_password": password, "accept_terms": True})


@pytest.fixture
def user_a(client):
    r = register(client)
    assert r.status_code == 201, r.text
    return client


@pytest.fixture
def user_b():
    with TestClient(app) as c:  # separate cookie jar = separate browser
        assert register(c, "Ravi Shah", "ravi@example.com").status_code == 201
        yield c


TRIP = {"name": "Udaipur getaway", "destination": "Udaipur", "start_date": "2027-02-10", "end_date": "2027-02-13",
        "travelers_count": 3, "budget_total": 45000, "currency": "INR", "interests": ["culture", "food"]}


def make_trip(c: TestClient, **over):
    r = c.post("/api/trips", json={**TRIP, **over})
    assert r.status_code == 201, r.text
    return r.json()


def wait_for(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met in time")
