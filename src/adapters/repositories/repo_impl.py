"""SQLAlchemy implementations of the repository ports."""

import uuid
from collections.abc import Callable
from datetime import datetime, time, timedelta

from sqlalchemy import Select, Table, func, select
from sqlalchemy.orm import Session

from src.adapters.repositories import orm
from src.application.domain.audit import AuditLog
from src.application.domain.customer import Customer
from src.application.domain.errors import DomainValidationError
from src.application.domain.events import EventRecorder
from src.application.domain.ledger import LedgerAccount, LedgerEntry
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.notification import Notification, NotificationOutbox, OutboxStatus
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


def _paginate(session: Session, stmt: Select, table: Table, query: PageQuery) -> Page:
    """Spring-style paging; ``sort`` accepts camelCase property names (e.g. ``createdAt,desc``)."""
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    for clause in query.sort:
        stmt = stmt.order_by(*_order_by(table, clause))
    items = list(session.scalars(stmt.offset(query.page * query.size).limit(query.size)))
    return Page(items=items, total=total, page=query.page, size=query.size)


def _order_by(table: Table, clause: str) -> list:
    parts = [p.strip() for p in clause.split(",") if p.strip()]
    direction = "asc"
    if parts and parts[-1].lower() in ("asc", "desc"):
        direction = parts.pop().lower()
    order = []
    for prop in parts:
        column_name = "".join("_" + c.lower() if c.isupper() else c for c in prop)
        if column_name not in table.c:
            raise DomainValidationError(f"No property '{prop}' found for '{table.name}'")
        column = table.c[column_name]
        order.append(column.desc() if direction == "desc" else column.asc())
    return order


class CustomerRepository(ICustomerRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, customer_id: uuid.UUID) -> Customer | None:
        return self.session.get(Customer, customer_id)

    def get_for_update(self, customer_id: uuid.UUID) -> Customer | None:
        return self.session.scalars(
            select(Customer).where(orm.customers.c.id == customer_id).with_for_update()
        ).one_or_none()

    def find_by_email(self, email: str) -> Customer | None:
        return self.session.scalars(select(Customer).where(orm.customers.c.email == email)).one_or_none()

    def add(self, customer: Customer) -> None:
        self.session.add(customer)

    def list(self, query: PageQuery) -> Page[Customer]:
        return _paginate(self.session, select(Customer), orm.customers, query)


class LoanProductRepository(ILoanProductRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, product_id: uuid.UUID) -> LoanProduct | None:
        return self.session.get(LoanProduct, product_id)

    def add(self, product: LoanProduct) -> None:
        self.session.add(product)

    def list(self, query: PageQuery) -> Page[LoanProduct]:
        return _paginate(self.session, select(LoanProduct), orm.loan_products, query)


class LoanRepository(ILoanRepository):
    def __init__(self, session: Session, track: Callable[[EventRecorder], None]):
        self.session = session
        self._track = track

    def get(self, loan_id: uuid.UUID) -> Loan | None:
        loan = self.session.get(Loan, loan_id)
        if loan is not None:
            self._track(loan)
        return loan

    def add(self, loan: Loan) -> None:
        self.session.add(loan)
        self._track(loan)

    def list_by_status(self, status: LoanStatus) -> list[Loan]:
        loans = list(self.session.scalars(select(Loan).where(orm.loans.c.status == status)))
        for loan in loans:
            self._track(loan)
        return loans

    def list(
        self, query: PageQuery, customer_id: uuid.UUID | None = None, status: LoanStatus | None = None
    ) -> Page[Loan]:
        stmt = select(Loan)
        if customer_id is not None:
            stmt = stmt.where(orm.loans.c.customer_id == customer_id)
        if status is not None:
            stmt = stmt.where(orm.loans.c.status == status)
        return _paginate(self.session, stmt, orm.loans, query)


class PaymentRepository(IPaymentRepository):
    def __init__(self, session: Session):
        self.session = session

    def exists_by_external_reference(self, external_reference: str) -> bool:
        stmt = select(orm.payments.c.id).where(orm.payments.c.external_reference == external_reference)
        return self.session.scalar(stmt) is not None

    def add(self, payment: Payment) -> None:
        self.session.add(payment)

    def list_for_loan(self, loan_id: uuid.UUID) -> list[Payment]:
        return list(
            self.session.scalars(
                select(Payment)
                .where(orm.payments.c.loan_id == loan_id)
                .order_by(orm.payments.c.payment_date.desc())
            )
        )


class LedgerRepository(ILedgerRepository):
    def __init__(self, session: Session):
        self.session = session

    def find_account(self, account_type: str, reference_id: uuid.UUID) -> LedgerAccount | None:
        c = orm.ledger_accounts.c
        return self.session.scalars(
            select(LedgerAccount).where(c.account_type == account_type, c.reference_id == reference_id)
        ).first()

    def add_account(self, account: LedgerAccount) -> None:
        self.session.add(account)
        # Entries reference accounts by id without an ORM relationship, so insert accounts first.
        self.session.flush()

    def add_entry(self, entry: LedgerEntry) -> None:
        self.session.add(entry)


class AuditRepository(IAuditRepository):
    def __init__(self, session: Session):
        self.session = session

    def add(self, entry: AuditLog) -> None:
        self.session.add(entry)


class NotificationRepository(INotificationRepository):
    def __init__(self, session: Session):
        self.session = session

    def get(self, notification_id: uuid.UUID) -> Notification | None:
        return self.session.get(Notification, notification_id)

    def get_by_event_id(self, event_id: uuid.UUID) -> Notification | None:
        return self.session.scalars(
            select(Notification).where(orm.notifications.c.event_id == event_id)
        ).one_or_none()

    def add(self, notification: Notification) -> None:
        self.session.add(notification)

    def search(self, criteria: NotificationFilter, query: PageQuery) -> Page[Notification]:
        c = orm.notifications.c
        stmt = select(Notification)
        if criteria.customer_id is not None:
            stmt = stmt.where(c.customer_id == criteria.customer_id)
        if criteria.type and criteria.type.strip():
            stmt = stmt.where(c.type == criteria.type.strip().upper())
        if criteria.delivery_status and criteria.delivery_status.strip():
            stmt = stmt.where(c.delivery_status == criteria.delivery_status.strip().upper())
        if criteria.ui_status and criteria.ui_status.strip():
            stmt = stmt.where(c.ui_status == criteria.ui_status.strip().upper())
        if criteria.from_date is not None:
            stmt = stmt.where(c.created_at >= datetime.combine(criteria.from_date, time.min))
        if criteria.to_date is not None:
            stmt = stmt.where(c.created_at < datetime.combine(criteria.to_date + timedelta(days=1), time.min))
        return _paginate(self.session, stmt, orm.notifications, query)

    def count_by_delivery_status(self, status: str) -> int:
        c = orm.notifications.c
        return self.session.scalar(select(func.count()).where(c.delivery_status == status)) or 0

    def count_by_ui_status(self, status: str) -> int:
        c = orm.notifications.c
        return self.session.scalar(select(func.count()).where(c.ui_status == status)) or 0


class OutboxRepository(IOutboxRepository):
    def __init__(self, session: Session):
        self.session = session

    def add(self, outbox: NotificationOutbox) -> None:
        self.session.add(outbox)

    def _due(self, now: datetime):
        c = orm.notification_outbox.c
        return (c.status == OutboxStatus.PENDING.value, c.next_retry_at < now)

    def due_for_publish(self, now: datetime, limit: int = 100) -> list[NotificationOutbox]:
        return list(
            self.session.scalars(
                select(NotificationOutbox)
                .where(*self._due(now))
                .order_by(orm.notification_outbox.c.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    def count_due(self, now: datetime, limit: int = 100) -> int:
        ids = select(orm.notification_outbox.c.id).where(*self._due(now)).limit(limit).subquery()
        return self.session.scalar(select(func.count()).select_from(ids)) or 0
