"""Repayment schedule rows and payments (Java ``RepaymentScheduleTest`` and ``PaymentTest``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from src.application.domain.repayment import Payment, RepaymentSchedule, ScheduleStatus


def _row(amount_due: str) -> RepaymentSchedule:
    return RepaymentSchedule(
        due_date=date(2026, 5, 1),
        amount_due=Decimal(amount_due),
        created_at=datetime(2026, 4, 1, 12, 0),
    )


def test_apply_payment_caps_at_remaining_and_returns_unallocated():
    s = _row("100.00")
    left = s.apply_payment(Decimal("40.00"))
    assert left == 0
    assert s.amount_paid == Decimal("40.00")
    assert s.status == ScheduleStatus.PENDING

    left = s.apply_payment(Decimal("80.00"))
    assert left == Decimal("20.00")
    assert s.amount_paid == Decimal("100.00")
    assert s.status == ScheduleStatus.PAID


def test_apply_payment_zero_or_negative_returns_unchanged():
    s = _row("50.00")
    assert s.apply_payment(Decimal("0")) == 0
    assert s.apply_payment(Decimal("-1.00")) == Decimal("-1.00")
    # Java leaves amountPaid null; the Python model initialises it to zero. Either way nothing was paid.
    assert not s.amount_paid


def test_mark_overdue_transitions_once_and_skips_paid_rows():
    s = _row("10.00")
    assert not s.mark_overdue(date(2026, 5, 1))  # due today: not yet overdue
    assert s.mark_overdue(date(2026, 5, 2))
    assert not s.mark_overdue(date(2026, 5, 3))
    paid = _row("10.00")
    paid.apply_payment(Decimal("10.00"))
    assert not paid.mark_overdue(date(2026, 6, 1))
    assert paid.status == ScheduleStatus.PAID


def test_payment_create_sets_fields():
    loan_id = uuid.uuid4()
    when = datetime(2026, 4, 1, 14, 30)
    p = Payment.create(loan_id, Decimal("500.00"), when, "txn_abc")

    # Java leaves the id null until persisted; the Python factory assigns it eagerly.
    assert p.loan_id == loan_id
    assert p.amount == Decimal("500.00")
    assert p.payment_date == when
    assert p.external_reference == "txn_abc"
    assert p.created_at is not None


def test_payment_create_rejects_null_external_reference():
    with pytest.raises(TypeError):
        Payment.create(uuid.uuid4(), Decimal("1"), datetime.now(), None)
