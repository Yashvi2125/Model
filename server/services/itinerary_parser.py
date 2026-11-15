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
        out_days.append({
            "day": d["day"],
            "title": d["title"],
            "intro": "\n".join(d["intro"]).strip(),
            "sections": [{"period": s["period"], "content": "\n".join(s["lines"]).strip()}
                         for s in d["sections"] if "\n".join(s["lines"]).strip()],
        })
    return {"overview": "\n".join(overview).strip(), "days": out_days, "tail": "\n".join(tail).strip(),
            "structured": bool(out_days),
            "sources": list(dict.fromkeys(u.rstrip(".,;") for u in URL_RE.findall(markdown or "")))[:25]}
