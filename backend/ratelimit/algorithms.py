"""Redis-backed rate-limiting algorithms: sliding window and token bucket.

Both are implemented as Lua scripts (`redis.Redis.register_script`) so the
read-check-write sequence is atomic on the Redis server -- a plain
GET/compute/SET from Python would race under concurrent requests hitting
the same key (two requests could both read "9 of 10 used" and both be
allowed, exceeding the limit).
"""

from dataclasses import dataclass

import redis


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_seconds: float


_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)

if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window)
    return {1, limit - count - 1, 0}
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = window
    if oldest[2] then
        retry_after = (tonumber(oldest[2]) + window) - now
    end
    return {0, 0, retry_after}
end
"""

_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_rate = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
local retry_after = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    retry_after = (requested - tokens) / refill_rate
end

redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) + 60)

return {allowed, tokens, retry_after}
"""


class SlidingWindowLimiter:
    """Counts requests in a rolling window (a Redis sorted set keyed by
    timestamp) -- precise (no boundary burst the way fixed windows allow),
    at the cost of one sorted-set entry per request until it ages out."""

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
        self._script = redis_client.register_script(_SLIDING_WINDOW_SCRIPT)

    def check(self, key: str, limit: int, window_seconds: float, now: float) -> RateLimitResult:
        member = f"{now}:{id(object())}"
        allowed, remaining, retry_after = self._script(
            keys=[key], args=[now, window_seconds, limit, member]
        )
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=float(remaining),
            retry_after_seconds=float(retry_after),
        )


class TokenBucketLimiter:
    """Classic token bucket: `capacity` tokens, refilling continuously at
    `refill_rate` tokens/second -- allows bursts up to capacity, then
    throttles to the steady-state refill rate. Used for plan-tier limits
    (Milestone 6) since "N requests per minute, with some burst headroom"
    is what a plan limit means in practice."""

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
        self._script = redis_client.register_script(_TOKEN_BUCKET_SCRIPT)

    def check(
        self,
        key: str,
        capacity: float,
        refill_rate_per_second: float,
        now: float,
        requested: float = 1,
    ) -> RateLimitResult:
        allowed, remaining, retry_after = self._script(
            keys=[key], args=[now, capacity, refill_rate_per_second, requested]
        )
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=float(remaining),
            retry_after_seconds=float(retry_after),
        )
