"""Domain events raised by aggregates and the reminder job."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class DomainEvent:
    occurred_at: datetime


@dataclass(frozen=True, kw_only=True)
class LoanDisbursedEvent(DomainEvent):
    loan_id: uuid.UUID | None
    customer_id: uuid.UUID
    total_amount: Decimal | None
    disbursement_date: date


@dataclass(frozen=True, kw_only=True)
class PaymentReceivedEvent(DomainEvent):
    loan_id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    external_reference: str


@dataclass(frozen=True, kw_only=True)
class LoanOverdueEvent(DomainEvent):
    loan_id: uuid.UUID
    customer_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class PaymentDueEvent(DomainEvent):
    """Emitted when an installment is due soon (scheduled reminder job)."""

    loan_id: uuid.UUID
    customer_id: uuid.UUID
    due_date: date


class EventRecorder:
    """Mixin for aggregates that raise domain events.

    Instances loaded by the ORM bypass ``__init__``, so the pending list is created lazily.
    """

    @property
    def _pending_events(self) -> list[DomainEvent]:
        return self.__dict__.setdefault("_domain_events", [])

    def _record_event(self, event: DomainEvent) -> None:
        self._pending_events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        """Removes and returns pending domain events (published after commit)."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events
