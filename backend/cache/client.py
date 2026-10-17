"""Redis connection management -- one client per process, mirroring
backend/db/session.py's init_engine()/get_engine() pattern (module-level
singleton, idempotent init, a cheap real check_connection() for /health).
"""

import redis

_client: redis.Redis | None = None


def init_redis(redis_url: str) -> redis.Redis:
    """Create (or return the existing) module-level Redis client. Idempotent
    so tests and `create_app()` can both call it safely."""
    global _client
    if _client is None:
        _client = redis.Redis.from_url(redis_url, decode_responses=True)
    return _client


def get_redis() -> redis.Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialized -- call init_redis() first")
    return _client


def check_connection() -> bool:
    """Used by the /health endpoint -- a real PING, not just 'was the client
    object constructed'."""
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
