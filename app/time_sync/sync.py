from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

from app.logging import logger


ClockFetcher = Callable[[], Awaitable[int]]


@dataclass
class TimeSynchronizer:
    fetch_server_ms: ClockFetcher
    drift_ms_threshold: int = 1000

    _offset_ms: int = 0

    async def refresh(self) -> int:
        server_ms = await self.fetch_server_ms()
        local_ms = int(time.time() * 1000)
        self._offset_ms = server_ms - local_ms
        drift = abs(self._offset_ms)
        if drift > self.drift_ms_threshold:
            logger.warn("time.drift", drift_ms=drift)
        else:
            logger.info("time.sync", drift_ms=drift)
        return self._offset_ms

    def now_ms(self) -> int:
        return int(time.time() * 1000) + self._offset_ms
