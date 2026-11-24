"""B-16: Token-bucket rate limiter middleware.

Limits:
  - /gateway/call      → 30 req / 60 s
  - /prototype/simulate → 30 req / 60 s
  - /auth/login        → 10 req / 60 s

Key: first hop of X-Forwarded-For when TRUST_PROXY=1, else client host.

Returns 429 with Retry-After header when the bucket is exhausted.
"""
import os
import time
import threading
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


_RULES: list[tuple[str, int, int]] = [
    # (path_prefix, max_tokens, window_seconds)
    ("/gateway/call",       30, 60),
    ("/prototype/simulate", 30, 60),
    ("/auth/login",         10, 60),
]

_TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"


def _client_key(request: Request) -> str:
    if _TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class _Bucket:
    """Simple fixed-window token bucket (thread-safe)."""

    __slots__ = ("tokens", "window_start", "_max", "_window", "lock")

    def __init__(self, max_tokens: int, window_seconds: int):
        self.tokens = max_tokens
        self.window_start = time.monotonic()
        self._max = max_tokens
        self._window = window_seconds
        self.lock = threading.Lock()

    def consume(self) -> tuple[bool, int]:
        """Try to consume one token.  Returns (allowed, retry_after_seconds)."""
        with self.lock:
            now = time.monotonic()
            if now - self.window_start >= self._window:
                self.tokens = self._max
                self.window_start = now
            if self.tokens > 0:
                self.tokens -= 1
                return True, 0
            retry = int(self._window - (now - self.window_start)) + 1
            return False, retry


# {path_prefix: {client_key: _Bucket}}
_buckets: dict[str, dict[str, _Bucket]] = {}
_buckets_lock = threading.Lock()


def _get_bucket(path_prefix: str, client_key: str, max_tokens: int, window: int) -> _Bucket:
    with _buckets_lock:
        if path_prefix not in _buckets:
            _buckets[path_prefix] = {}
        if client_key not in _buckets[path_prefix]:
            _buckets[path_prefix][client_key] = _Bucket(max_tokens, window)
        return _buckets[path_prefix][client_key]


_TEST_MODE = os.getenv("APP_ENV", "") == "test"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # B-16: Rate limiting is a production concern. Skip entirely in test mode
        # so fixture login calls and functional tests never hit 429 mid-suite.
        if _TEST_MODE:
            return await call_next(request)

        path = request.url.path
        for prefix, max_tokens, window in _RULES:
            if path == prefix or path.startswith(prefix + "/"):
                key = _client_key(request)
                bucket = _get_bucket(prefix, key, max_tokens, window)
                allowed, retry_after = bucket.consume()
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded. Please slow down."},
                        headers={"Retry-After": str(retry_after)},
                    )
                break
        return await call_next(request)
