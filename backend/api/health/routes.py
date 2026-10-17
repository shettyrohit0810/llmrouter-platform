from fastapi import APIRouter, HTTPException

from backend.cache.client import check_connection as redis_check_connection
from backend.db.session import check_connection as db_check_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Unified health check -- shadows the gateway app's own /health once mounted
    (see backend/app.py's mount-order comment for why this one wins).

    Raises 503 (via the standard exception handlers) if a required backing
    service is unreachable -- a behavior change from Phase 3's unconditional
    200, made deliberately so container orchestration health checks reflect
    real dependency state (see docs/migration/phase3_to_phase4.md)."""
    if not db_check_connection():
        raise HTTPException(status_code=503, detail="database unreachable")
    if not redis_check_connection():
        raise HTTPException(status_code=503, detail="redis unreachable")
    return {"status": "ok"}
