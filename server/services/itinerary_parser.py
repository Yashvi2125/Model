"""Turns the planner's Markdown into Day / Morning / Afternoon / Evening cards.

Deterministic: nothing is added or invented. Anything that can't be placed stays in the raw Markdown,
which the UI always keeps available.
"""
import re
from typing import Any

DAY_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s*)?(?:\*\*|__)?\s*Day\s+(\d{1,2})\b[^\n]*$", re.IGNORECASE)
PERIOD_RE = re.compile(r"^\s{0,6}(?:[-*+]\s*)?(?:#{1,6}\s*)?(?:\*\*|__)?\s*(Morning|Afternoon|Evening|Night)\b[^\n]*$", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)>\]]+")


def _clean_title(line: str) -> str:
    return re.sub(r"^[#\s*_]+|[*_\s:]+$", "", line).strip()


def extract_structured_places_from_content(content: str) -> list[dict[str, str]]:
    """Extract structured place objects from activity content.
    Returns list of dicts: {"name": str, "area": Optional[str], "kind": str}
    """
    places = []
    # Pattern 1: Activity bullet beginning with bold place name: * **Place Name:** or **Place Name** -
    bold_lead = re.compile(
        r"(?:^|\n)\s*[-*+]\s*\*\*([A-Za-z0-9\s'’\-–—.,/&:]+?)\*\*\s*[:\-–—]?\s*(.*?)(?=(?:\n\s*[-*+]\s*\*\*|\Z))",
        re.DOTALL
    )
    for m in bold_lead.finditer(content):
        raw_name = m.group(1).strip().strip(" :.-–—*")
        desc = m.group(2).strip()
        # Clean meal prefixes like "Lunch at Agashiye" -> "Agashiye"
        clean_name = re.sub(r"^(?:Lunch|Dinner|Breakfast|Brunch|Snacks|Drinks|Meal)\s+at\s+", "", raw_name, flags=re.I).strip()
        clean_name = re.sub(r"^(?:Visit|Explore|Tour)\s+(?:the\s+)?", "", clean_name, flags=re.I).strip()
        
        # Determine kind
        low_raw = raw_name.lower()
        low_desc = desc[:120].lower()
        if any(w in low_raw or w in low_desc for w in ("lunch", "dinner", "breakfast", "cafe", "restaurant", "dining", "thali", "diner", "bistro", "bakery")):
            kind = "restaurant"
        elif any(w in low_raw or w in low_desc for w in ("market", "shopping", "bazaar", "bazar", "boutique", "emporium", "mall")):
            kind = "market"
        elif any(w in low_raw or w in low_desc for w in ("hotel", "resort", "hostel", "stay", "accommodation")):
            kind = "hotel"
        else:
            kind = "attraction"

        # Check for area hint (e.g. "in Vastrapur", "in Old City", "in Shibuya")
        area_match = re.search(r"\bin\s+(?:the\s+)?([A-Z][a-zA-Z0-9\s]+?)(?:,|\.|\barea\b|\bdistrict\b|\bneighborhood\b)", desc)
        area = area_match.group(1).strip() if area_match else None

        if len(clean_name) > 2 and len(clean_name.split()) <= 6:
            places.append({
                "name": clean_name,
                "area": area,
                "kind": kind
            })

    return places


def parse_itinerary(markdown: str) -> dict[str, Any]:
    lines = (markdown or "").splitlines()
    overview: list[str] = []
    days: list[dict[str, Any]] = []
    tail: list[str] = []
    cur_day = None
    cur_period = None
    day_level = 0
    in_tail = False

    for line in lines:
        m = DAY_RE.match(line)
        if m and len(line.strip()) < 160:
            cur_day = {"day": int(m.group(1)), "title": _clean_title(line), "sections": [], "intro": []}
            days.append(cur_day)
            cur_period = None
            in_tail = False
            day_level = len(re.match(r"^\s*(#*)", line).group(1))
            continue
        if cur_day is None:
            overview.append(line)
            continue
        h = re.match(r"^\s{0,3}(#{1,6})\s", line)
        if h and not PERIOD_RE.match(line) and (day_level == 0 or len(h.group(1)) <= day_level):
            in_tail = True  # a new top-level section after the days (tips, stays, budget...)
        if in_tail:
            tail.append(line)
            continue
        p = PERIOD_RE.match(line)
        if p:
            name = p.group(1).lower()
            cur_period = {"period": "evening" if name == "night" else name, "lines": []}
            cur_day["sections"].append(cur_period)
            rest = re.sub(r"^[\s\-*+#_]*(?:\*\*|__)?\s*(Morning|Afternoon|Evening|Night)[^:\n]*?(?:\*\*|__)?\s*[:\-–—]?\s*(?:\*\*|__)?", "", line, flags=re.IGNORECASE).strip()
            if rest and rest not in ("**", "__"):
                cur_period["lines"].append(rest)
            continue
        (cur_period["lines"] if cur_period else cur_day["intro"]).append(line)

    out_days = []
    for d in days:
        sections_data = [{"period": s["period"], "content": "\n".join(s["lines"]).strip()}
                         for s in d["sections"] if "\n".join(s["lines"]).strip()]
        day_places = []
        for s in sections_data:
            day_places.extend(extract_structured_places_from_content(s["content"]))
        out_days.append({
            "day": d["day"],
            "title": d["title"],
            "intro": "\n".join(d["intro"]).strip(),
            "sections": sections_data,
            "places": day_places,
        })
    return {"overview": "\n".join(overview).strip(), "days": out_days, "tail": "\n".join(tail).strip(),
            "structured": bool(out_days),
            "sources": list(dict.fromkeys(u.rstrip(".,;") for u in URL_RE.findall(markdown or "")))[:25]}
