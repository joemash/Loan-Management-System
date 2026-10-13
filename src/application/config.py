"""Application-level policies, built from infrastructure settings by the composition root."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LoanPolicy:
    daily_penalty_rate: Decimal = Decimal("0.001")
    default_after_days_past_due: int = 90
    reminder_days_before_due: int = 3


@dataclass(frozen=True)
class NotificationPolicy:
    topic: str = "notifications.events"
    max_attempts: int = 5
