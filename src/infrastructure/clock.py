"""Clock adapters for the ``IClock`` port.

Timestamps are naive UTC (stored in ``TIMESTAMP`` columns); business dates use the local system date,
matching the Java ``Clock.systemDefaultZone()``.
"""

from datetime import UTC, date, datetime

from src.application.ports.services import IClock


class SystemClock(IClock):
    def now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def today(self) -> date:
        return date.today()


class FixedClock(IClock):
    """Deterministic clock for tests and simulations; mutable via ``set``."""

    def __init__(self, now: datetime, today: date | None = None):
        self.set(now, today)

    def set(self, now: datetime, today: date | None = None) -> None:
        self._now = now
        self._today = today or now.date()

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._today
