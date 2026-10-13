"""Use-case ports (driving side). Web routes, scheduled jobs and the Kafka consumer depend only on these."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.application.domain.customer import Customer
from src.application.domain.events import (
    LoanDisbursedEvent,
    LoanOverdueEvent,
    PaymentDueEvent,
    PaymentReceivedEvent,
)
from src.application.domain.loan import Loan, LoanSummary
from src.application.domain.loan_product import LoanProduct
from src.application.domain.notification import Notification, NotificationEventMessage
from src.application.domain.repayment import Payment, RepaymentSchedule
from src.application.ports.pagination import Page, PageQuery
from src.application.ports.repo import NotificationFilter


class ICustomerUseCases(ABC):
    @abstractmethod
    def register(self, name: str, email: str, credit_limit: Decimal, status: str | None = None) -> Customer:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        customer_id: uuid.UUID,
        name: str | None = None,
        status: str | None = None,
        credit_limit: Decimal | None = None,
    ) -> Customer:
        raise NotImplementedError

    @abstractmethod
    def get(self, customer_id: uuid.UUID) -> Customer:
        raise NotImplementedError

    @abstractmethod
    def list(self, query: PageQuery) -> Page[Customer]:
        raise NotImplementedError


class ILoanProductUseCases(ABC):
    @abstractmethod
    def create(
        self,
        *,
        name: str,
        interest_strategy: str,
        repayment_strategy: str,
        fee_strategy: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        min_tenure_days: int | None = None,
        max_tenure_days: int | None = None,
        config: dict[str, Any] | None = None,
    ) -> LoanProduct:
        raise NotImplementedError

    @abstractmethod
    def update(self, product_id: uuid.UUID, **changes: Any) -> LoanProduct:
        """Partial update; ``None`` values are ignored and ``config`` replaces the whole object."""
        raise NotImplementedError

    @abstractmethod
    def get(self, product_id: uuid.UUID) -> LoanProduct:
        raise NotImplementedError

    @abstractmethod
    def list(self, query: PageQuery) -> Page[LoanProduct]:
        raise NotImplementedError


@dataclass(frozen=True)
class LoanDetail:
    loan: Loan
    schedules: list[RepaymentSchedule]
    summary: LoanSummary
    payments: list[Payment]


class ILoanUseCases(ABC):
    @abstractmethod
    def apply(self, customer_id: uuid.UUID, product_id: uuid.UUID, amount: Decimal) -> Loan:
        raise NotImplementedError

    @abstractmethod
    def approve(self, loan_id: uuid.UUID) -> Loan:
        raise NotImplementedError

    @abstractmethod
    def disburse(self, loan_id: uuid.UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    def repay(self, loan_id: uuid.UUID, amount: Decimal, external_reference: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def summary(self, loan_id: uuid.UUID) -> LoanSummary:
        raise NotImplementedError

    @abstractmethod
    def detail(self, loan_id: uuid.UUID) -> LoanDetail:
        raise NotImplementedError

    @abstractmethod
    def list(
        self, query: PageQuery, customer_id: uuid.UUID | None = None, status: str | None = None
    ) -> Page[Loan]:
        raise NotImplementedError


class ILoanMaintenanceUseCases(ABC):
    @abstractmethod
    def process_overdues_and_penalties(self) -> int:
        """Returns the number of active loans processed."""
        raise NotImplementedError

    @abstractmethod
    def publish_due_reminders(self) -> int:
        """Returns the number of reminders queued."""
        raise NotImplementedError


class INotificationUseCases(ABC):
    @abstractmethod
    def record_loan_disbursed(self, event: LoanDisbursedEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_payment_received(self, event: PaymentReceivedEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_loan_overdue(self, event: LoanOverdueEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_payment_due(self, event: PaymentDueEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, notification_id: uuid.UUID) -> Notification:
        raise NotImplementedError

    @abstractmethod
    def search(self, criteria: NotificationFilter, query: PageQuery) -> Page[Notification]:
        raise NotImplementedError

    @abstractmethod
    def mark_read(self, notification_id: uuid.UUID) -> None:
        raise NotImplementedError

    @abstractmethod
    def publish_pending(self) -> int:
        """Relays due outbox rows to the broker; returns the number published."""
        raise NotImplementedError

    @abstractmethod
    def handle_delivery(self, message: NotificationEventMessage) -> None:
        """Dispatches a consumed message through the channel and records the outcome."""
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> dict[str, int]:
        """Counts for monitoring: ``failed``, ``unread``, ``outbox_due``."""
        raise NotImplementedError
