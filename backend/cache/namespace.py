"""Generic namespaced cache -- get/set/delete/get_or_set with JSON
serialization and a TTL, prefixed so different callers' keys never collide.
Every named cache in backend/cache/caches.py is one instance of this with
its own prefix and default TTL, not a hand-rolled key scheme per caller.
"""

import json
from typing import Any, Callable, Optional

from backend.cache.client import get_redis


class CacheNamespace:
    def __init__(self, prefix: str, default_ttl_seconds: int):
        self.prefix = prefix
        self.default_ttl_seconds = default_ttl_seconds

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def get(self, key: str) -> Optional[Any]:
        raw = get_redis().get(self._key(key))
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        get_redis().set(self._key(key), json.dumps(value), ex=ttl)

    def delete(self, key: str) -> None:
        get_redis().delete(self._key(key))

    def exists(self, key: str) -> bool:
        return bool(get_redis().exists(self._key(key)))

    def get_or_set(
        self, key: str, compute: Callable[[], Any], ttl_seconds: Optional[int] = None
    ) -> Any:
        """Return the cached value if present, otherwise call `compute()`,
        cache its result, and return it. `compute` is only invoked on a
        cache miss."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.set(key, value, ttl_seconds)
        return value
