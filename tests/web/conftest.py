"""Fixtures for the web backend tests.

Runs against SQLite by default so it works anywhere; set TEST_DATABASE_URL to a PostgreSQL URL
(e.g. postgresql+psycopg://tripmate:...@localhost:5432/tripmate_test) to run the same tests on PostgreSQL.
"""
import os
import tempfile
import time

_default = "sqlite:///" + os.path.join(tempfile.gettempdir(), "tripmate_pytest.db")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", _default)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import models  # noqa: E402, F401
from server.db import Base, engine  # noqa: E402
from server.main import app  # noqa: E402
from server.security import reset_rate_limits  # noqa: E402

PASSWORD = "Sup3rSecret!"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_rate_limits()
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
