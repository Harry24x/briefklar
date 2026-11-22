"""Very small per-IP daily rate limit, kept in memory (resets on restart; fine for the MVP)."""

from collections import defaultdict
from datetime import date
from threading import Lock

from fastapi import HTTPException, Request


class DailyLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._day = date.today()
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def hit(self, key: str) -> bool:
        """Count one request; return False if the key is over today's limit."""
        with self._lock:
            today = date.today()
            if today != self._day:
                self._day, self._counts = today, defaultdict(int)
            if self._counts[key] >= self.limit:
                return False
            self._counts[key] += 1
            return True


def client_ip(request: Request) -> str:
    # Behind Caddy the real client IP is in X-Forwarded-For (first entry).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: DailyLimiter, request: Request) -> None:
    if not limiter.hit(client_ip(request)):
        raise HTTPException(status_code=429, detail="Daily limit reached. Please try tomorrow.")
