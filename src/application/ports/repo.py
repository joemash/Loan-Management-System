"""Repository ports (driven side). Implemented by ``src.adapters.repositories.repo_impl``."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from src.application.domain.audit import AuditLog
from src.application.domain.customer import Customer
from src.application.domain.ledger import LedgerAccount, LedgerEntry
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.notification import Notification, NotificationOutbox
from src.application.domain.repayment import Payment
from src.application.ports.pagination import Page, PageQuery


class ICustomerRepository(ABC):
    @abstractmethod
    def get(self, customer_id: uuid.UUID) -> Customer | None:
        raise NotImplementedError

    @abstractmethod
    def get_for_update(self, customer_id: uuid.UUID) -> Customer | None:
        """Loads the customer with a pessimistic write lock (credit-line changes)."""
        raise NotImplementedError

    @abstractmethod
    def find_by_email(self, email: str) -> Customer | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, customer: Customer) -> None:
        raise NotImplementedError

    @abstractmethod
    def list(self, query: PageQuery) -> Page[Customer]:
        raise NotImplementedError


class ILoanProductRepository(ABC):
    @abstractmethod
    def get(self, product_id: uuid.UUID) -> LoanProduct | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, product: LoanProduct) -> None:
        raise NotImplementedError

    @abstractmethod
    def list(self, query: PageQuery) -> Page[LoanProduct]:
        raise NotImplementedError


class ILoanRepository(ABC):
    """Loans returned by this repository are tracked so their domain events publish after commit."""

    @abstractmethod
    def get(self, loan_id: uuid.UUID) -> Loan | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, loan: Loan) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_by_status(self, status: LoanStatus) -> list[Loan]:
        raise NotImplementedError

    @abstractmethod
    def list(
        self, query: PageQuery, customer_id: uuid.UUID | None = None, status: LoanStatus | None = None
    ) -> Page[Loan]:
        raise NotImplementedError


class IPaymentRepository(ABC):
    @abstractmethod
    def exists_by_external_reference(self, external_reference: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def add(self, payment: Payment) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_for_loan(self, loan_id: uuid.UUID) -> list[Payment]:
        """Newest payment first."""
        raise NotImplementedError


class ILedgerRepository(ABC):
    @abstractmethod
    def find_account(self, account_type: str, reference_id: uuid.UUID) -> LedgerAccount | None:
        raise NotImplementedError

    @abstractmethod
    def add_account(self, account: LedgerAccount) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_entry(self, entry: LedgerEntry) -> None:
        raise NotImplementedError


class IAuditRepository(ABC):
    @abstractmethod
    def add(self, entry: AuditLog) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class NotificationFilter:
    """All provided criteria are combined with AND; date bounds are inclusive UTC days."""

    customer_id: uuid.UUID | None = None
    type: str | None = None
    delivery_status: str | None = None
    ui_status: str | None = None
    from_date: date | None = None
    to_date: date | None = None


class INotificationRepository(ABC):
    @abstractmethod
    def get(self, notification_id: uuid.UUID) -> Notification | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_event_id(self, event_id: uuid.UUID) -> Notification | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, notification: Notification) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, criteria: NotificationFilter, query: PageQuery) -> Page[Notification]:
        raise NotImplementedError

    @abstractmethod
    def count_by_delivery_status(self, status: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def count_by_ui_status(self, status: str) -> int:
        raise NotImplementedError


class IOutboxRepository(ABC):
    @abstractmethod
    def add(self, outbox: NotificationOutbox) -> None:
        raise NotImplementedError

    @abstractmethod
    def due_for_publish(self, now: datetime, limit: int = 100) -> list[NotificationOutbox]:
        """Pending rows whose retry time has passed, oldest first, locked for this transaction."""
        raise NotImplementedError

    @abstractmethod
    def count_due(self, now: datetime, limit: int = 100) -> int:
        raise NotImplementedError
