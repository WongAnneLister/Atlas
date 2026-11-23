"""Signed demo identities and per-principal fixed-window rate limits."""

import hashlib
import hmac
import logging
import os
import secrets
from base64 import b64decode, urlsafe_b64encode
from functools import lru_cache
from threading import Lock
from time import time

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from support_agent.config import RateLimitSettings, SessionSettings
from support_agent.infra.redis import KeyValueStore

logger = logging.getLogger(__name__)
_FALLBACK_LOCK = Lock()
_TURN_PATHS = frozenset({"/api/chat", "/api/resume"})
SESSION_REQUIRED = "A valid demo session token is required"


class InvalidSession(ValueError):
    """A request did not provide a valid signed session token."""


@lru_cache(maxsize=1)
def _fallback_secret(process_id: int) -> bytes:
    # The cache key gives a forked worker its own secret.
    logger.warning("SESSION_SECRET is unset. Demo sessions use a per-process signing key.")
    return secrets.token_bytes(32)


def _signing_key() -> bytes:
    secret = os.getenv("SESSION_SECRET")
    if secret:
        return secret.encode("utf-8")
    with _FALLBACK_LOCK:
        return _fallback_secret(os.getpid())


class SessionTokens:
    def __init__(self, secret: bytes, ttl_s: int) -> None:
        self._secret = secret
        self._ttl_s = ttl_s

    @classmethod
    def from_environment(cls, settings: SessionSettings) -> "SessionTokens":
        return cls(_signing_key(), settings.ttl_s)

    def _signature(self, payload: bytes) -> bytes:
        return urlsafe_b64encode(hmac.digest(self._secret, payload, "sha256")).rstrip(b"=")

    def issue(self, customer_id: str) -> str:
        claims = f"{customer_id}:{int(time()) + self._ttl_s}".encode()
        encoded = urlsafe_b64encode(claims)
        return (encoded + b"." + self._signature(encoded)).decode("ascii")

    def verify(self, token: str) -> str:
        try:
            payload, signature = token.encode("ascii").split(b".")
            if not hmac.compare_digest(signature, self._signature(payload)):
                raise InvalidSession()
            claims = b64decode(payload, altchars=b"-_", validate=True).decode("utf-8")
            customer_id, expiry = claims.split(":")
            if not customer_id or int(expiry) <= time():
                raise InvalidSession()
        except ValueError:
            raise InvalidSession() from None
        return customer_id


class SessionAuthMiddleware:
    def __init__(self, app: ASGIApp, tokens: SessionTokens) -> None:
        self.app = app
        self.tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path) :]
        requires_auth = (
            (scope["method"] == "POST" and path in _TURN_PATHS)
            or (
                scope["method"] in {"GET", "DELETE"}
                and (path == "/api/me/memories" or path.startswith("/api/me/memories/"))
            )
            or (
                scope["method"] == "GET"
                and path.startswith("/api/conversations/")
                and path.endswith("/events")
            )
        )
        if requires_auth:
            headers = Headers(scope=scope).getlist("authorization")
            parts = headers[0].split() if len(headers) == 1 else []
            try:
                if len(parts) != 2 or parts[0].casefold() != "bearer":
                    raise InvalidSession()
                scope.setdefault("state", {})["atlas_customer_id"] = self.tokens.verify(parts[1])
            except InvalidSession:
                response = JSONResponse(
                    {"detail": SESSION_REQUIRED},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class RateLimitUnavailable(RuntimeError):
    """The configured shared rate limit cannot be checked."""


class RateLimits:
    def __init__(
        self, config: RateLimitSettings, store: KeyValueStore | None, shared: bool
    ) -> None:
        self.config = config
        self.store = store
        self.shared = shared
        self._lock = Lock()
        self._local_window: int | None = None
        self._local_counts: dict[str, int] = {}

    def _increment(self, key: str, window: int, remaining: int) -> int:
        if self.shared:
            if self.store is None:
                raise RateLimitUnavailable()
            try:
                return self.store.incr(f"atlas:rate:{window}:{key}", remaining)
            except Exception as error:
                logger.warning("Rate limit check failed: %s", type(error).__name__)
                raise RateLimitUnavailable() from None
        with self._lock:
            if self._local_window != window:
                self._local_window = window
                self._local_counts.clear()
            count = self._local_counts.get(key, 0) + 1
            self._local_counts[key] = count
            return count

    def retry_after(self, ip: str, customer_id: str | None = None) -> int | None:
        window_s = self.config.window_s
        window, elapsed = divmod(int(time()), window_s)
        remaining = window_s - elapsed
        ip_key = "ip:" + hashlib.sha256(ip.encode("utf-8")).hexdigest()
        if self._increment(ip_key, window, remaining) > self.config.per_ip:
            return remaining
        if customer_id is not None:
            customer_key = "customer:" + hashlib.sha256(customer_id.encode("utf-8")).hexdigest()
            if self._increment(customer_key, window, remaining) > self.config.per_customer:
                return remaining
        return None
