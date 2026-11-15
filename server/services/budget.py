"""Programmatic budget maths. The language model only *extracts* cost lines; every total is computed here."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

CATEGORIES = ["accommodation", "food", "transport", "activities", "other"]
BASES = ["group_total", "per_person", "per_person_per_day", "per_night_group"]


def d(x: Any) -> Decimal:
    return Decimal(str(x))


def money(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def line_total(item: dict, travelers: int, days: int, nights: int) -> Optional[Decimal]:
    try:
        amount = d(item["amount"])
    except Exception:
        return None
    if amount < 0:
        return None
    basis = item.get("basis", "group_total")
    if basis == "per_person":
        return amount * travelers
    if basis == "per_person_per_day":
        return amount * travelers * days
    if basis == "per_night_group":
        return amount * max(nights, 1)
    if basis == "group_total":
        return amount
    return None


def compute_budget(items: Optional[list], travelers: int, start_date, end_date,
                   budget_total: Optional[float], budget_per_person: Optional[float]) -> dict:
    days = (end_date - start_date).days + 1
    nights = max(days - 1, 0)
    travelers = max(travelers, 1)

    # Group budget as stated by the organiser (total wins; else per-person x travellers)
    group_budget: Optional[Decimal] = None
    if budget_total:
        group_budget = d(budget_total)
    elif budget_per_person:
        group_budget = d(budget_per_person) * travelers

    result: dict[str, Any] = {
        "travelers": travelers, "days": days, "nights": nights,
        "group_budget": money(group_budget) if group_budget is not None else None,
        "per_person_budget": money(group_budget / travelers) if group_budget is not None else None,
        "has_estimate": False, "categories": [], "items": [],
        "total": None, "per_person": None, "difference": None, "within_budget": None,
    }
    if not items:
        return result

    totals = {c: Decimal(0) for c in CATEGORIES}
    rows = []
    for it in items:
        total = line_total(it, travelers, days, nights)
        if total is None:
            continue
        cat = it.get("category") if it.get("category") in CATEGORIES else "other"
        totals[cat] += total
        rows.append({**it, "category": cat, "line_total": money(total)})
    if not rows:
        return result

    grand = sum(totals.values(), Decimal(0))
    result.update(
        has_estimate=True,
        items=rows,
        categories=[{"category": c, "total": money(v), "per_person": money(v / travelers),
                     "share": float(v / grand) if grand else 0.0} for c, v in totals.items() if v > 0],
        total=money(grand), per_person=money(grand / travelers),
    )
    if group_budget is not None:
        diff = group_budget - grand
        result["difference"] = money(diff)  # positive = remaining, negative = over budget
        result["within_budget"] = diff >= 0
    return result
