"""A minimal async rate limiter (single-process, monotonic-clock based)."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Spaces out calls so that at most `rate_per_sec` `acquire()`s happen per second."""

    def __init__(self, rate_per_sec: float):
        self.min_interval = 1.0 / rate_per_sec if rate_per_sec and rate_per_sec > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()
