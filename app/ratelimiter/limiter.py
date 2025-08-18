from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict

from app.logging import logger


@dataclass
class RateBucket:
    max_requests: int
    per_seconds: float
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_time: float = 0.0

    @property
    def min_interval(self) -> float:
        # Pace requests evenly across the window
        return self.per_seconds / float(self.max_requests)

    async def acquire(self, kind: str) -> None:
        async with self._lock:
            now = time.monotonic()
            earliest = self._last_time + self.min_interval
            wait = max(0.0, earliest - now)
            if wait > 0:
                logger.warning("ratelimit.wait", kind=kind, wait=wait)
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._last_time = now


class RateLimiter:
    def __init__(self) -> None:
        # Separate buckets for create/cancel vs other requests
        self.buckets: Dict[str, RateBucket] = {
            "trade": RateBucket(max_requests=500, per_seconds=10.0),
            "other": RateBucket(max_requests=200, per_seconds=10.0),
        }

    async def acquire(self, kind: str) -> None:
        bucket = self.buckets[kind]
        await bucket.acquire(kind)
