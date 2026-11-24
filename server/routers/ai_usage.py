"""Read-only AI usage and metering endpoint.

Requires authentication. Returns only in-memory counts, statuses, and cooldowns.
Never returns keys, prompts, or user content.
"""
from fastapi import APIRouter, Depends

from server.ai.gateway import gateway
from server.models import User
from server.security import current_user

router = APIRouter(tags=["ai"])


@router.get("/api/ai/usage")
def get_ai_usage(user: User = Depends(current_user)):
    """Return in-memory advisory AI gateway usage metrics.

    Only authenticated users may access this. Contains zero secrets, user data, or prompts.
    """
    return gateway.get_usage()
