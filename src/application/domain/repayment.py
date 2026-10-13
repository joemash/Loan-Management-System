"""Repayment schedules (expected installments) and payments (actual cash received)."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

ZERO = Decimal("0")


class ScheduleStatus(enum.StrEnum):
    PENDING = "PENDING"  # not yet fully settled (may be partially paid); not past due
    OVERDUE = "OVERDUE"  # past due date and not fully paid
    PAID = "PAID"  # amount_paid has reached amount_due


class RepaymentSchedule:
    """One expected installment, owned by the ``Loan`` aggregate."""

    def __init__(
        self,
        *,
        due_date: date,
        amount_due: Decimal,
        created_at: datetime,
        id: uuid.UUID | None = None,
        loan_id: uuid.UUID | None = None,
        amount_paid: Decimal | None = ZERO,
        status: ScheduleStatus = ScheduleStatus.PENDING,
        penalty_accrued: Decimal = ZERO,
        penalty_last_accrual_date: date | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.loan_id = loan_id
        self.due_date = due_date
        self.amount_due = amount_due
        self.amount_paid = amount_paid
        self.status = status
        self.penalty_accrued = penalty_accrued
        self.penalty_last_accrual_date = penalty_last_accrual_date
        self.created_at = created_at

    def remaining_due(self) -> Decimal:
        """Outstanding installment amount (excludes penalties)."""
        return max(self.amount_due - (self.amount_paid or ZERO), ZERO)

    def is_overdue(self) -> bool:
        return self.status == ScheduleStatus.OVERDUE

    def is_fully_paid(self) -> bool:
        return self.status == ScheduleStatus.PAID or (self.amount_paid or ZERO) >= self.amount_due

    def mark_overdue(self, today: date) -> bool:
        """Marks the row overdue when unpaid and past due; ``True`` only if this call transitioned it."""
        if self.is_fully_paid():
            return False
        if today > self.due_date and self.status != ScheduleStatus.OVERDUE:
            self.status = ScheduleStatus.OVERDUE
            return True
        return False

    def record_penalty_accrual(self, increment: Decimal, accrual_date: date) -> None:
        if increment <= 0:
            return
        self.penalty_accrued = (self.penalty_accrued or ZERO) + increment
        self.penalty_last_accrual_date = accrual_date

    def apply_payment(self, payment: Decimal) -> Decimal:
        """Applies cash up to the remaining due; returns the unallocated remainder."""
        if payment <= 0 or self.is_fully_paid():
            return payment
        paid = self.amount_paid or ZERO
        applied = min(payment, self.amount_due - paid)
        self.amount_paid = paid + applied
        if self.amount_paid == self.amount_due:
            self.status = ScheduleStatus.PAID
        return payment - applied


class Payment:
    """Actual funds received. Not part of the ``Loan`` aggregate; references the loan by id only.

    ``external_reference`` is the idempotency key for ingest (e.g. a PSP transaction id).
    """

    def __init__(
        self,
        *,
        id: uuid.UUID,
        loan_id: uuid.UUID,
        amount: Decimal,
        payment_date: datetime,
        external_reference: str | None,
        created_at: datetime,
    ):
        self.id = id
        self.loan_id = loan_id
        self.amount = amount
        self.payment_date = payment_date
        self.external_reference = external_reference
        self.created_at = created_at

    @classmethod
    def create(
        cls, loan_id: uuid.UUID, amount: Decimal, payment_date: datetime, external_reference: str
    ) -> "Payment":
        for name, value in (
            ("loan_id", loan_id),
            ("amount", amount),
            ("payment_date", payment_date),
            ("external_reference", external_reference),
        ):
            if value is None:
                raise TypeError(f"{name} must not be None")
        return cls(
            id=uuid.uuid4(),
            loan_id=loan_id,
            amount=amount,
            payment_date=payment_date,
            external_reference=external_reference,
            created_at=payment_date,
        )
