"""Plain-text trip context handed to the AI agents."""
from typing import Optional

from server.models import Preference, Trip, User


def trip_context(trip: Trip, rows: list[tuple[User, Optional[Preference]]]) -> str:
    lines = [
        f"Trip: {trip.name}. Destination: {trip.destination or 'undecided'}. "
        f"Dates: {trip.start_date} to {trip.end_date} ({(trip.end_date - trip.start_date).days + 1} days). "
        f"Travellers: {trip.travelers_count}. Currency: {trip.currency}. "
        f"Group budget: {trip.budget_total or '-'} total / {trip.budget_per_person or '-'} per person ({trip.budget_flexibility})."
    ]
    for user, p in rows:
        if not p:
            lines.append(f"- {user.name}: no preferences saved yet")
            continue
        bits = []
        if p.destination: bits.append(f"destination {p.destination}")
        if p.start_date and p.end_date: bits.append(f"dates {p.start_date} to {p.end_date}")
        elif p.trip_days: bits.append(f"{p.trip_days} days")
        if p.interests: bits.append("interests " + ", ".join(p.interests))
        if p.budget_min is not None or p.budget_max is not None:
            bits.append(f"budget {p.budget_min or 0}-{p.budget_max or '?'} per person")
        for label, v in (("stay", p.accommodation), ("diet", p.dietary), ("restrictions", p.restrictions), ("notes", p.notes)):
            if v: bits.append(f"{label}: {v}")
        lines.append(f"- {user.name}: " + ("; ".join(bits) or "no preferences saved yet"))
    return "\n".join(lines)
