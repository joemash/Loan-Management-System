"""Loan aggregate root: lifecycle state machine, schedules and repayment allocation.

    CREATED → APPROVED → DISBURSED → CLOSED
                        ↘ DEFAULTED (policy)

The aggregate owns its repayment schedules but not payments (see ``repayment.Payment``).
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.application.domain.errors import DomainStateError, DomainValidationError
from src.application.domain.events import (
    EventRecorder,
    LoanDisbursedEvent,
    LoanOverdueEvent,
    PaymentReceivedEvent,
)
from src.application.domain.repayment import RepaymentSchedule

ZERO = Decimal("0")


class LoanStatus(enum.StrEnum):
    CREATED = "CREATED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


@dataclass(frozen=True)
class LoanSummary:
    principal: Decimal
    paid: Decimal
    remaining: Decimal
    overdue: Decimal
    penalties: Decimal


class Loan(EventRecorder):
    def __init__(
        self,
        *,
        id: uuid.UUID,
        customer_id: uuid.UUID,
        product_id: uuid.UUID,
        principal: Decimal,
        status: LoanStatus,
        created_at: datetime,
        updated_at: datetime,
        total_amount: Decimal | None = None,
        disbursement_date: date | None = None,
        schedules: list[RepaymentSchedule] | None = None,
    ):
        self.id = id
        self.customer_id = customer_id
        self.product_id = product_id
        self.principal = principal
        self.total_amount = total_amount
        self.status = status
        self.disbursement_date = disbursement_date
        self.created_at = created_at
        self.updated_at = updated_at
        self.schedules = schedules if schedules is not None else []

    @classmethod
    def apply(
        cls, customer_id: uuid.UUID, product_id: uuid.UUID, principal: Decimal, now: datetime
    ) -> "Loan":
        """New loan application in ``CREATED`` status."""
        for name, value in (
            ("customer_id", customer_id),
            ("product_id", product_id),
            ("principal", principal),
        ):
            if value is None:
                raise TypeError(f"{name} must not be None")
        return cls(
            id=uuid.uuid4(),
            customer_id=customer_id,
            product_id=product_id,
            principal=principal,
            status=LoanStatus.CREATED,
            created_at=now,
            updated_at=now,
        )

    create = apply

    # --- lifecycle -----------------------------------------------------------------------------------

    def approve(self) -> None:
        if self.status != LoanStatus.CREATED:
            raise DomainStateError(
                f"Loan can only be approved when CREATED, current status: {self.status.value}"
            )
        self.status = LoanStatus.APPROVED

    def disburse(
        self,
        disbursement_date: date,
        total_amount: Decimal | None,
        repayment_schedules: list[RepaymentSchedule],
        now: datetime,
    ) -> None:
        """``APPROVED`` → ``DISBURSED``; idempotent (no-op, no events) when already disbursed.

        When ``total_amount`` is given, schedule ``amount_due`` values must sum to it exactly.
        Replaces any existing schedules and raises ``LoanDisbursedEvent``.
        """
        if disbursement_date is None or repayment_schedules is None:
            raise TypeError("disbursement_date and repayment_schedules must not be None")
        if self.status == LoanStatus.DISBURSED:
            return
        if self.status != LoanStatus.APPROVED:
            raise DomainStateError(
                f"Loan must be APPROVED before disbursement, current status: {self.status.value}"
            )
        _validate_schedules(total_amount, repayment_schedules)
        self.status = LoanStatus.DISBURSED
        self.disbursement_date = disbursement_date
        self.total_amount = total_amount
        self.schedules.clear()
        for schedule in repayment_schedules:
            self.add_repayment_schedule(schedule)
        self._record_event(
            LoanDisbursedEvent(
                loan_id=self.id,
                customer_id=self.customer_id,
                total_amount=total_amount,
                disbursement_date=disbursement_date,
                occurred_at=now,
            )
        )

    def add_repayment_schedule(self, schedule: RepaymentSchedule) -> None:
        schedule.loan_id = self.id
        self.schedules.append(schedule)

    def remove_repayment_schedule(self, schedule: RepaymentSchedule) -> None:
        self.schedules.remove(schedule)

    def check_overdue(self, today: date, now: datetime) -> None:
        """Marks past-due installments overdue; raises ``LoanOverdueEvent`` if any row newly transitioned.

        Does not default the loan (see ``apply_default_policy``).
        """
        if self.status != LoanStatus.DISBURSED:
            return
        newly_overdue = [s.mark_overdue(today) for s in self.schedules]
        if any(newly_overdue):
            self._record_event(
                LoanOverdueEvent(loan_id=self.id, customer_id=self.customer_id, occurred_at=now)
            )

    def apply_default_policy(self, today: date, min_days_past_due: int) -> None:
        """Moves to ``DEFAULTED`` when any unpaid overdue installment is ``min_days_past_due`` days late."""
        if self.status != LoanStatus.DISBURSED:
            return
        for schedule in self.schedules:
            if schedule.is_fully_paid() or not schedule.is_overdue():
                continue
            if (today - schedule.due_date).days >= min_days_past_due:
                self.status = LoanStatus.DEFAULTED
                return

    def register_payment_received(self, amount: Decimal, external_reference: str, now: datetime) -> None:
        self._record_event(
            PaymentReceivedEvent(
                loan_id=self.id,
                customer_id=self.customer_id,
                amount=amount,
                external_reference=external_reference,
                occurred_at=now,
            )
        )

    def apply_repayment(self, amount: Decimal) -> None:
        """Allocates cash FIFO by due date; closes the loan when every installment is paid.

        Requires ``DISBURSED`` or ``DEFAULTED``. Overpayment (cash left after all rows settle) is rejected.
        """
        if amount <= 0:
            raise DomainValidationError("Repayment amount must be positive")
        if self.status not in (LoanStatus.DISBURSED, LoanStatus.DEFAULTED):
            raise DomainStateError("Loan is not active for repayment")
        if not self.schedules:
            raise DomainStateError("Loan has no repayment schedules")
        remaining = amount
        for schedule in sorted(self.schedules, key=lambda s: s.due_date):
            if not schedule.is_fully_paid():
                remaining = schedule.apply_payment(remaining)
                if remaining == 0:
                    break
        if remaining > 0:
            raise DomainValidationError(
                f"Repayment exceeds remaining obligation; unallocated amount: {remaining}"
            )
        if self.is_fully_paid():
            self.status = LoanStatus.CLOSED

    def is_fully_paid(self) -> bool:
        """All schedules paid (``False`` when there are no schedules)."""
        return bool(self.schedules) and all(s.is_fully_paid() for s in self.schedules)

    @property
    def credit_to_release(self) -> Decimal:
        """Amount reserved on the credit line at disbursement (contractual total, else principal)."""
        return self.total_amount if self.total_amount is not None else self.principal

    def summary(self) -> LoanSummary:
        paid = remaining = overdue = penalties = ZERO
        for s in self.schedules:
            paid += s.amount_paid or ZERO
            remaining += s.remaining_due()
            if s.is_overdue():
                overdue += s.remaining_due()
            penalties += s.penalty_accrued or ZERO
        return LoanSummary(self.principal, paid, remaining, overdue, penalties)


def _validate_schedules(total_amount: Decimal | None, schedules: list[RepaymentSchedule]) -> None:
    if any(s.amount_due is None for s in schedules):
        raise DomainValidationError("Each repayment schedule must have amountDue set")
    total = sum((s.amount_due for s in schedules), ZERO)
    if total_amount is not None and total != total_amount:
        raise DomainValidationError(
            f"Sum of schedule amounts ({total}) does not match totalAmount ({total_amount})"
        )
