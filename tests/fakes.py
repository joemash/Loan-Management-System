"""In-memory adapters for testing use cases without a database, broker or container.

``FakeUnitOfWork`` keeps state across ``with`` blocks (like a committed database) but does not undo
in-memory mutations on rollback; tests assert on commits/rollbacks and published events instead.
"""

import uuid
from datetime import date, datetime

from src.application.domain.audit import AuditLog
from src.application.domain.customer import Customer
from src.application.domain.events import DomainEvent
from src.application.domain.ledger import LedgerAccount, LedgerEntry
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.notification import (
    Notification,
    NotificationEventMessage,
    NotificationOutbox,
    OutboxStatus,
)
from src.application.domain.repayment import Payment
from src.application.ports.pagination import Page, PageQuery
from src.application.ports.repo import (
    IAuditRepository,
    ICustomerRepository,
    ILedgerRepository,
    ILoanProductRepository,
    ILoanRepository,
    INotificationRepository,
    IOutboxRepository,
    IPaymentRepository,
    NotificationFilter,
)
from src.application.ports.services import (
    IClock,
    IEventPublisher,
    INotificationChannel,
    INotificationMetrics,
    INotificationProducer,
)
from src.application.ports.uow import IUnitOfWork


def _page(items: list, query: PageQuery) -> Page:
    start = query.page * query.size
    return Page(items=items[start : start + query.size], total=len(items), page=query.page, size=query.size)


class FakeClock(IClock):
    def __init__(self, now: datetime, today: date | None = None):
        self.set(now, today)

    def set(self, now: datetime, today: date | None = None) -> None:
        self._now, self._today = now, today or now.date()

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._today


class FakeEventPublisher(IEventPublisher):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: type) -> list:
        return [e for e in self.events if isinstance(e, event_type)]


class InMemoryCustomerRepository(ICustomerRepository):
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Customer] = {}

    def get(self, customer_id):
        return self.items.get(customer_id)

    def get_for_update(self, customer_id):
        return self.items.get(customer_id)

    def find_by_email(self, email):
        return next((c for c in self.items.values() if c.email == email), None)

    def add(self, customer):
        self.items[customer.id] = customer

    def list(self, query):
        return _page(list(self.items.values()), query)


class InMemoryLoanProductRepository(ILoanProductRepository):
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, LoanProduct] = {}

    def get(self, product_id):
        return self.items.get(product_id)

    def add(self, product):
        self.items[product.id] = product

    def list(self, query):
        return _page(list(self.items.values()), query)


class InMemoryLoanRepository(ILoanRepository):
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Loan] = {}
        self.track = lambda loan: None

    def get(self, loan_id):
        loan = self.items.get(loan_id)
        if loan is not None:
            self.track(loan)
        return loan

    def add(self, loan):
        self.items[loan.id] = loan
        self.track(loan)

    def list_by_status(self, status: LoanStatus):
        loans = [loan for loan in self.items.values() if loan.status == status]
        for loan in loans:
            self.track(loan)
        return loans

    def list(self, query, customer_id=None, status=None):
        loans = [
            loan
            for loan in self.items.values()
            if (customer_id is None or loan.customer_id == customer_id)
            and (status is None or loan.status == status)
        ]
        return _page(loans, query)


class InMemoryPaymentRepository(IPaymentRepository):
    def __init__(self) -> None:
        self.items: list[Payment] = []

    def exists_by_external_reference(self, external_reference):
        return any(p.external_reference == external_reference for p in self.items)

    def add(self, payment):
        self.items.append(payment)

    def list_for_loan(self, loan_id):
        return sorted(
            (p for p in self.items if p.loan_id == loan_id), key=lambda p: p.payment_date, reverse=True
        )


class InMemoryLedgerRepository(ILedgerRepository):
    def __init__(self) -> None:
        self.accounts: list[LedgerAccount] = []
        self.entries: list[LedgerEntry] = []

    def find_account(self, account_type, reference_id):
        return next(
            (a for a in self.accounts if a.account_type == account_type and a.reference_id == reference_id),
            None,
        )

    def add_account(self, account):
        self.accounts.append(account)

    def add_entry(self, entry):
        self.entries.append(entry)

    def account(self, account_id: uuid.UUID) -> LedgerAccount:
        return next(a for a in self.accounts if a.id == account_id)


class InMemoryAuditRepository(IAuditRepository):
    def __init__(self) -> None:
        self.items: list[AuditLog] = []

    def add(self, entry):
        self.items.append(entry)


class InMemoryNotificationRepository(INotificationRepository):
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Notification] = {}

    def get(self, notification_id):
        return self.items.get(notification_id)

    def get_by_event_id(self, event_id):
        return next((n for n in self.items.values() if n.event_id == event_id), None)

    def add(self, notification):
        self.items[notification.id] = notification

    def search(self, criteria: NotificationFilter, query):
        items = [
            n
            for n in self.items.values()
            if (criteria.customer_id is None or n.customer_id == criteria.customer_id)
            and (not criteria.type or n.type == criteria.type.strip().upper())
            and (
                not criteria.delivery_status or n.delivery_status == criteria.delivery_status.strip().upper()
            )
            and (not criteria.ui_status or n.ui_status == criteria.ui_status.strip().upper())
        ]
        return _page(items, query)

    def count_by_delivery_status(self, status):
        return sum(1 for n in self.items.values() if n.delivery_status == status)

    def count_by_ui_status(self, status):
        return sum(1 for n in self.items.values() if n.ui_status == status)


class InMemoryOutboxRepository(IOutboxRepository):
    def __init__(self) -> None:
        self.items: list[NotificationOutbox] = []

    def add(self, outbox):
        self.items.append(outbox)

    def due_for_publish(self, now, limit=100):
        due = [o for o in self.items if o.status == OutboxStatus.PENDING and o.next_retry_at < now]
        return sorted(due, key=lambda o: o.created_at)[:limit]

    def count_due(self, now, limit=100):
        return len(self.due_for_publish(now, limit))


class FakeUnitOfWork(IUnitOfWork):
    def __init__(self, event_publisher: IEventPublisher | None = None):
        self.publisher = event_publisher or FakeEventPublisher()
        super().__init__(self.publisher)
        self.customers = InMemoryCustomerRepository()
        self.products = InMemoryLoanProductRepository()
        self.loans = InMemoryLoanRepository()
        self.loans.track = self.track
        self.payments = InMemoryPaymentRepository()
        self.ledger = InMemoryLedgerRepository()
        self.audit = InMemoryAuditRepository()
        self.notifications = InMemoryNotificationRepository()
        self.outbox = InMemoryOutboxRepository()
        self.active = False
        self.commits = 0
        self.rollbacks = 0

    def _begin(self) -> None:
        if self.active:
            raise RuntimeError("Unit of work is already active")
        self.active = True

    def _end(self) -> None:
        self.active = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeProducer(INotificationProducer):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, NotificationEventMessage]] = []

    def send(self, topic, key, message):
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.sent.append((topic, key, message))


class FakeChannel(INotificationChannel):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.dispatched: list[NotificationEventMessage] = []

    def dispatch(self, message):
        if self.fail:
            raise RuntimeError("smtp down")
        self.dispatched.append(message)


class FakeMetrics(INotificationMetrics):
    def __init__(self) -> None:
        self.counts = {"outbox_published": 0, "outbox_failed": 0, "consumed": 0, "consume_failed": 0}

    def outbox_published(self):
        self.counts["outbox_published"] += 1

    def outbox_failed(self):
        self.counts["outbox_failed"] += 1

    def consumed(self):
        self.counts["consumed"] += 1

    def consume_failed(self):
        self.counts["consume_failed"] += 1
