"""Rule-based disagreement detection. Pure facts from members' saved preferences; the AI only proposes compromises."""
import hashlib
import json
import re
from typing import Optional

from server.models import Preference, User


def _first(name: str) -> str:
    return name.split()[0] if name else name


def _fmt(n) -> str:
    return f"{float(n):,.0f}"


def detect(rows: list[tuple[User, Optional[Preference]]], currency: str) -> list[dict]:
    have = [(u, p) for u, p in rows if p is not None]
    found: list[dict] = []

    # 1. budgets
    b = [(u, p) for u, p in have if p.budget_max is not None]
    if len(b) >= 2:
        hi, lo = max(float(p.budget_max) for _, p in b), min(float(p.budget_max) for _, p in b)
        if lo > 0 and hi > lo * 1.25:
            found.append({
                "kind": "budget", "title": "Your group has different budget limits",
                "description": f"Per-person budgets range from {currency} {_fmt(lo)} to {currency} {_fmt(hi)}.",
                "positions": [{"user_id": u.id, "name": _first(u.name),
                               "detail": f"up to {currency} {_fmt(p.budget_max)} per person"} for u, p in b]})

    # 2. destination
    d = [(u, p) for u, p in have if p.destination]
    if len({p.destination.strip().lower() for _, p in d}) >= 2:
        found.append({
            "kind": "destination", "title": "Your group has different destination preferences",
            "description": "Members have named more than one destination.",
            "positions": [{"user_id": u.id, "name": _first(u.name), "detail": p.destination} for u, p in d]})

    # 3. dates
    dt = [(u, p) for u, p in have if p.start_date and p.end_date]
    if len({(p.start_date, p.end_date) for _, p in dt}) >= 2:
        latest_start, earliest_end = max(p.start_date for _, p in dt), min(p.end_date for _, p in dt)
        overlap = (earliest_end - latest_start).days + 1
        desc = ("There is no window where everyone is available." if overlap <= 0
                else f"Everyone is available for {overlap} day(s), from {latest_start:%d %b} to {earliest_end:%d %b}.")
        found.append({
            "kind": "dates", "title": "Your group has different travel dates", "description": desc,
            "positions": [{"user_id": u.id, "name": _first(u.name),
                           "detail": f"{p.start_date:%d %b %Y} – {p.end_date:%d %b %Y}"} for u, p in dt]})

    # 4. activities
    a = [(u, p) for u, p in have if p.interests]
    if len(a) >= 2:
        shared = set.intersection(*[{i.lower() for i in p.interests} for _, p in a])
        if not shared:
            tension = any("adventure" in {i.lower() for i in p.interests} for _, p in a) and \
                any("relaxation" in {i.lower() for i in p.interests} for _, p in a)
            found.append({
                "kind": "activities", "title": "Your group has different activity preferences",
                "description": "No activity type is shared by every member."
                               + (" Adventure and relaxation are both wanted." if tension else ""),
                "positions": [{"user_id": u.id, "name": _first(u.name), "detail": ", ".join(p.interests)} for u, p in a]})

    # 5. accommodation
    ac = [(u, p) for u, p in have if p.accommodation]
    if len({p.accommodation.strip().lower() for _, p in ac}) >= 2:
        found.append({
            "kind": "accommodation", "title": "Your group expects different kinds of stay",
            "description": "Members described different accommodation expectations.",
            "positions": [{"user_id": u.id, "name": _first(u.name), "detail": p.accommodation} for u, p in ac]})

    # 6. notes & day-specific schedule preferences (e.g. "beach on day 2" vs "shibuya on day 2")
    n = [(u, p) for u, p in have if p.notes and p.notes.strip()]
    if len(n) >= 2:
        day_users: dict[str, list[tuple[User, Preference]]] = {}
        for u, p in n:
            days_found = re.findall(r"\bday\s*(\d+)\b", p.notes.lower())
            for d_num in days_found:
                day_key = f"day {d_num}"
                day_users.setdefault(day_key, []).append((u, p))

        for day_key, users_on_day in day_users.items():
            if len(users_on_day) >= 2:
                # Compare notes of different users mentioning the same day
                distinct_notes = {p.notes.strip().lower() for _, p in users_on_day}
                if len(distinct_notes) >= 2:
                    found.append({
                        "kind": "activities",
                        "title": f"Scheduling conflict on {day_key.title()}",
                        "description": f"Members have requested different activities or plans for {day_key.title()}.",
                        "positions": [
                            {"user_id": u.id, "name": _first(u.name), "detail": p.notes.strip()}
                            for u, p in users_on_day
                        ],
                    })

    for c in found:
        c["signature"] = hashlib.sha256(json.dumps(c["positions"], sort_keys=True).encode()).hexdigest()[:32]
    return found
