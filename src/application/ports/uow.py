"""Unit of Work port
Use cases run inside ``with self.uow:``. On success the transaction commits and then any domain events
raised by tracked aggregates (or queued with ``add_event``) are published; on error it rolls back and the
events are discarded. Each instance owns one transaction at a time and is not shared between requests.
"""

from abc import ABC, abstractmethod

from src.application.domain.events import DomainEvent, EventRecorder
from src.application.ports.repo import (
    IAuditRepository,
    ICustomerRepository,
    ILedgerRepository,
    ILoanProductRepository,
    ILoanRepository,
    INotificationRepository,
    IOutboxRepository,
    IPaymentRepository,
)
from src.application.ports.services import IEventPublisher


class IUnitOfWork(ABC):
    customers: ICustomerRepository
    products: ILoanProductRepository
    loans: ILoanRepository
    payments: IPaymentRepository
    ledger: ILedgerRepository
    audit: IAuditRepository
    notifications: INotificationRepository
    outbox: IOutboxRepository

    def __init__(self, event_publisher: IEventPublisher):
        self._event_publisher = event_publisher
        self._tracked: list[EventRecorder] = []
        self._events: list[DomainEvent] = []

    def __enter__(self) -> "IUnitOfWork":
        self._tracked, self._events = [], []
        self._begin()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        except Exception as err:
            self._raise_translated(err)
            raise
        finally:
            self._end()
        if exc_value is not None:
            self._raise_translated(exc_value)
            return  # propagate the original error
        self._publish_events()

    def track(self, aggregate: EventRecorder) -> None:
        """Registers an aggregate whose pending events should publish after commit."""
        if all(aggregate is not seen for seen in self._tracked):
            self._tracked.append(aggregate)

    def add_event(self, event: DomainEvent) -> None:
        """Queues an event that is not raised by an aggregate (e.g. reminders)."""
        self._events.append(event)

    def _publish_events(self) -> None:
        events = list(self._events)
        for aggregate in self._tracked:
            events.extend(aggregate.pull_events())
        self._tracked, self._events = [], []
        for event in events:
            self._event_publisher.publish(event)

    def _raise_translated(self, exc: BaseException) -> None:
        translated = self._translate(exc)
        if translated is not None:
            raise translated from exc

    def _translate(self, exc: BaseException) -> Exception | None:
        """Adapters convert persistence exceptions into application errors here."""
        return None

    @abstractmethod
    def _begin(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def _end(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def rollback(self) -> None:
        raise NotImplementedError
