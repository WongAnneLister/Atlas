"""Shared Redis operations with an in-memory implementation for local use."""

from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import Protocol, cast

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from support_agent.infra.settings import RedisSettings


class KeyValueStore(Protocol):
    def ping(self) -> bool: ...
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_s: int) -> None: ...
    def delete(self, key: str) -> bool: ...
    def incr(self, key: str, ttl_s: int) -> int: ...
    def set_if_absent(self, key: str, value: str, ttl_s: int) -> bool: ...


# The first increment sets the expiry. Later increments keep the original window.
_INCREMENT = """
local exists = redis.call('EXISTS', KEYS[1])
local value = redis.call('INCR', KEYS[1])
if exists == 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return value
"""


def _validate_ttl(ttl_s: int) -> None:
    if type(ttl_s) is not int or ttl_s <= 0:
        raise ValueError("TTL must be a positive number of seconds")


class RedisStore:
    def __init__(self, url: str, settings: RedisSettings) -> None:
        self._client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=settings.connect_timeout_s,
            socket_timeout=settings.socket_timeout_s,
            retry=Retry(NoBackoff(), 0),
        )

    def ping(self) -> bool:
        return bool(self._client.ping())

    def get(self, key: str) -> str | None:
        return cast(str | None, self._client.get(key))

    def set(self, key: str, value: str, ttl_s: int) -> None:
        _validate_ttl(ttl_s)
        self._client.set(key, value, ex=ttl_s)

    def delete(self, key: str) -> bool:
        return bool(self._client.delete(key))

    def incr(self, key: str, ttl_s: int) -> int:
        _validate_ttl(ttl_s)
        return cast(int, self._client.eval(_INCREMENT, 1, key, ttl_s))

    def set_if_absent(self, key: str, value: str, ttl_s: int) -> bool:
        _validate_ttl(ttl_s)
        return bool(self._client.set(key, value, ex=ttl_s, nx=True))

    def close(self) -> None:
        self._client.close()


class NullRedis:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._values: dict[str, tuple[str, float]] = {}

    def _entry(self, key: str, now: float) -> tuple[str, float] | None:
        entry = self._values.get(key)
        if entry is not None and entry[1] <= now:
            del self._values[key]
            return None
        return entry

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._entry(key, self._clock())
            return entry[0] if entry is not None else None

    def set(self, key: str, value: str, ttl_s: int) -> None:
        _validate_ttl(ttl_s)
        with self._lock:
            self._values[key] = (value, self._clock() + ttl_s)

    def delete(self, key: str) -> bool:
        with self._lock:
            if self._entry(key, self._clock()) is None:
                return False
            del self._values[key]
            return True

    def incr(self, key: str, ttl_s: int) -> int:
        _validate_ttl(ttl_s)
        with self._lock:
            now = self._clock()
            entry = self._entry(key, now)
            value, deadline = entry if entry is not None else ("0", now + ttl_s)
            result = int(value) + 1
            self._values[key] = (str(result), deadline)
            return result

    def set_if_absent(self, key: str, value: str, ttl_s: int) -> bool:
        _validate_ttl(ttl_s)
        with self._lock:
            now = self._clock()
            if self._entry(key, now) is not None:
                return False
            self._values[key] = (value, now + ttl_s)
            return True
