"""Daily LLM spend cap for public demos (thread-safe, UTC daily rollover)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from threading import Lock


def _utc_today() -> date:
    return datetime.now(UTC).date()


class DailySpendCap:
    """Tracks daily UTC LLM spend and rejects new turns once cap_usd is reached."""

    def __init__(
        self,
        cap_usd: float,
        *,
        today_fn: Callable[[], date] = _utc_today,
    ) -> None:
        self.cap_usd = max(0.0, float(cap_usd))
        self._today_fn = today_fn
        self._lock = Lock()
        self._day: date = self._today_fn()
        self._spent_usd: float = 0.0

    def _roll_if_needed(self) -> None:
        today = self._today_fn()
        if today != self._day:
            self._day = today
            self._spent_usd = 0.0

    @property
    def enabled(self) -> bool:
        return self.cap_usd > 0.0

    def spent_today(self) -> float:
        with self._lock:
            self._roll_if_needed()
            return self._spent_usd

    def remaining(self) -> float | None:
        if not self.enabled:
            return None
        with self._lock:
            self._roll_if_needed()
            return max(0.0, self.cap_usd - self._spent_usd)

    def exceeded(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            self._roll_if_needed()
            return self._spent_usd >= self.cap_usd

    def record(self, amount_usd: float) -> float:
        if amount_usd <= 0.0:
            return self.spent_today()
        with self._lock:
            self._roll_if_needed()
            self._spent_usd += float(amount_usd)
            return self._spent_usd
