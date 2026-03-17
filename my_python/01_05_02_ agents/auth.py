"""
Authentication middleware and rate limiting.
Port of 4th-devs/01_05_agent middleware/auth.ts + rate-limit.ts.

Auth is toggled by AUTH_ENABLED app state flag.
When disabled, protected endpoints work without a token.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from errors import err
from repositories import Repositories


def hash_api_key(api_key: str) -> str:
    """SHA-256 hash of an API key for secure storage / lookup."""
    return hashlib.sha256(api_key.encode()).hexdigest()


_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """FastAPI dependency: validates bearer token, returns User or None.
    Returns None when AUTH_ENABLED is falsy (dev mode).
    """
    if not getattr(request.app.state, "auth_enabled", False):
        return None

    if credentials is None:
        raise err.unauthorized("Missing Authorization header")
    api_key = credentials.credentials
    if not api_key:
        raise err.unauthorized("Missing token")

    repos: Repositories = request.app.state.repos
    key_hash = hash_api_key(api_key)
    user = repos.users.get_by_api_key_hash(key_hash)
    if not user:
        raise err.unauthorized("Invalid API key")

    _rate_limiter.check(user.id)
    return user


# ── Fixed-window rate limiter ─────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, limit: int = 60, window_s: int = 60):
        self._limit = limit
        self._window_s = window_s
        self._windows: dict[str, dict[str, Any]] = {}

    def check(self, user_id: str) -> None:
        now = time.time()
        w = self._windows.get(user_id)
        if not w or now >= w["reset"]:
            w = {"count": 0, "reset": now + self._window_s}
            self._windows[user_id] = w
        w["count"] += 1
        if w["count"] > self._limit:
            retry = max(1, int(w["reset"] - now))
            raise err.rate_limited(f"Rate limit exceeded. Try again in {retry}s", retry_after=retry)

    def cleanup(self) -> None:
        now = time.time()
        for k in [k for k, v in self._windows.items() if now >= v["reset"]]:
            del self._windows[k]


_rate_limiter = _RateLimiter(limit=60, window_s=60)


# ── Seed helper ───────────────────────────────────────────────────────────────

DEFAULT_DEV_API_KEY = "test-api-key-01-05-02"


def seed_default_user(repos: Repositories, api_key: str = DEFAULT_DEV_API_KEY) -> None:
    """Create a default user for development / testing (idempotent)."""
    key_hash = hash_api_key(api_key)
    if repos.users.get_by_api_key_hash(key_hash):
        return
    repos.users.create({"email": "dev@agent.local", "api_key_hash": key_hash})
