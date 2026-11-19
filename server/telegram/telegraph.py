"""Telegraph API client for publishing rich itinerary pages."""
import html
import logging
import re
from typing import Optional

import httpx

from server.config import get_settings

log = logging.getLogger("tripmate.telegraph")
API_BASE = "https://api.telegra.ph"
_cached_token: Optional[str] = None


async def get_or_create_access_token() -> Optional[str]:
    global _cached_token
    token = get_settings().telegraph_access_token or _cached_token
    if token:
        return token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{API_BASE}/createAccount",
                json={
                    "short_name": "TripMate",
                    "author_name": "TripMate AI",
                    "author_url": get_settings().public_base_url,
                },
            )
            data = resp.json()
            if data.get("ok") and "access_token" in data.get("result", {}):
                _cached_token = data["result"]["access_token"]
                return _cached_token
            log.warning("Telegraph createAccount returned not ok: %s", data)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not create Telegraph account: %s", exc)
    return None


def markdown_to_nodes(markdown_text: str) -> list[dict]:
    """Convert Markdown itinerary into Telegraph Node array."""
    nodes = []
    lines = markdown_text.splitlines()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            nodes.append({"tag": "h4", "children": [line[4:]]})
        elif line.startswith("## "):
            nodes.append({"tag": "h3", "children": [line[3:]]})
        elif line.startswith("# "):
            nodes.append({"tag": "h3", "children": [line[2:]]})
        elif line.startswith(("- ", "* ")):
            clean_item = re.sub(r"^\s*[-*]\s*", "", line)
            # handle simple bold formatting
            parts = re.split(r"(\*\*.*?\*\*)", clean_item)
            children = []
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    children.append({"tag": "strong", "children": [part[2:-2]]})
                elif part:
                    children.append(part)
            nodes.append({"tag": "p", "children": ["• "] + children})
        else:
            parts = re.split(r"(\*\*.*?\*\*)", line)
            children = []
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    children.append({"tag": "strong", "children": [part[2:-2]]})
                elif part:
                    children.append(part)
            nodes.append({"tag": "p", "children": children})
    return nodes or [{"tag": "p", "children": ["No itinerary content."]}]


async def publish_itinerary_page(
    title: str, plan_markdown: str, author_name: str = "TripMate AI"
) -> Optional[str]:
    """Publishes a formatted itinerary to telegra.ph and returns the public link."""
    token = await get_or_create_access_token()
    if not token:
        return None
    try:
        nodes = markdown_to_nodes(plan_markdown)
        clean_title = re.sub(r"[^\w\s-]", "", title).strip() or "Trip Itinerary"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{API_BASE}/createPage",
                json={
                    "access_token": token,
                    "title": clean_title[:64],
                    "author_name": author_name,
                    "author_url": get_settings().public_base_url,
                    "content": nodes,
                    "return_content": False,
                },
            )
            data = resp.json()
            if data.get("ok") and "url" in data.get("result", {}):
                return data["result"]["url"]
            log.warning("Telegraph createPage failed: %s", data)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to publish to Telegraph: %s", exc)
    return None
