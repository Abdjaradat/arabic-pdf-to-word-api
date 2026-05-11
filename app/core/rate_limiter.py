from __future__ import annotations

import hashlib
from typing import Protocol

import redis.asynced as aioredis

from app.config import settings

_redis_pool: aioredis.Redis | None = None


async def init_rate_limiter() -> None:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.db.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )


async def close_rate_limiter() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None


def get_redis() -> aioredis.Redis | None:
    return _redis_pool


class RateLimitResult:
    def __init__(self, allowed: bool, remaining: int, reset_after_seconds: int):
        self.allowed = allowed
        self.remaining = remaining
        self.reset_after_seconds = reset_after_seconds


def _build_key(identifier: str, route: str) -> str:
    raw = f"{identifier}:{route}"
    return f"ratelimit:{hashlib.sha256(raw.encode()).hexdigest()}"


async def check_rate_limit(
    identifier: str,
    route: str = "default",
    max_requests: int | None = None,
    window_seconds: int = 60,
) -> RateLimitResult:
    if max_requests is None:
        max_requests = settings.rate_limit_per_minute

    redis = get_redis()
    if redis is None:
        return RateLimitResult(allowed=True, remaining=max_requests, reset_after_seconds=0)

    key = _build_key(identifier, route)
    now = await redis.time()
    now_ms = int(now[0]) * 1000 + int(now[1]) // 1000
    window_start = now_ms - (window_seconds * 1000)

    await redis.zremrangebyscore(key, 0, window_start)

    current_count = await redis.zcard(key)

    if current_count >= max_requests:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            reset_time = int(oldest[0][1]) // 1000 + window_seconds
            reset_after = max(0, reset_time - int(now[0]))
        else:
            reset_after = window_seconds
        return RateLimitResult(allowed=False, remaining=0, reset_after_seconds=reset_after)

    await redis.zadd(key, {str(now_ms): now_ms})
    await redis.expire(key, window_seconds * 2)

    remaining = max_requests - current_count - 1
    return RateLimitResult(allowed=True, remaining=remaining, reset_after_seconds=window_seconds)


async def get_rate_limit_identifier(user_id: str | None, ip_address: str) -> str:
    return user_id or f"ip:{ip_address}"
