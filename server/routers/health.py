from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from server.ai.client import ai_status
from server.db import engine

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    body = {"status": "ok" if db_ok else "degraded", "database": db_ok, "ai": ai_status()}
    return JSONResponse(body, status_code=200 if db_ok else 503)
