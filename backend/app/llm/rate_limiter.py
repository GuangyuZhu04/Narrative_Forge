import asyncio
import time


class TokenBucketRateLimiter:
    def __init__(self):
        self._rpm = 60
        self._tokens = 60.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def configure(self, config: dict):
        self._rpm = config.get("requests_per_minute", 60)
        self._tokens = float(self._rpm)
        self._last_refill = time.monotonic()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._rpm,
                self._tokens + (now - self._last_refill) * (self._rpm / 60.0),
            )
            self._last_refill = now
            if self._tokens < 1:
                await asyncio.sleep(
                    (1 - self._tokens) / (self._rpm / 60.0)
                )
                self._tokens = 0
            else:
                self._tokens -= 1
