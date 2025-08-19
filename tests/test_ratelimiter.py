import asyncio
import time

import pytest

from app.ratelimiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_spreads_requests():
    limiter = RateLimiter()
    start = time.monotonic()

    async def do(kind: str):
        await limiter.acquire(kind)

    # 600 trade requests in 10s window should not error, they should be spread
    tasks = [asyncio.create_task(do("trade")) for _ in range(600)]
    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start
    # With 500/10s, 600 will take at least 12s
    assert elapsed >= 12.0
