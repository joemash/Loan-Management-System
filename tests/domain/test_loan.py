"""Loan aggregate state machine (Java ``LoanTest`` and ``LoanOverdueTest``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from src.application.domain.errors import DomainStateError, DomainValidationError
from src.application.domain.events import LoanDisbursedEvent, LoanOverdueEvent, PaymentReceivedEvent
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.repayment import RepaymentSchedule, ScheduleStatus

NOW = datetime(2026, 4, 1, 12, 0)


def _loan(principal: str = "1000.00") -> Loan:
    return Loan.create(uuid.uuid4(), uuid.uuid4(), Decimal(principal), NOW)


def _row(amount_due: str | None, due_date: date = date(2026, 5, 1), created: str = "2026-04-01T12:00:00"):
    return RepaymentSchedule(
        due_date=due_date,
        amount_due=Decimal(amount_due) if amount_due is not None else None,
        created_at=datetime.fromisoformat(created),
    )


def test_apply_creates_loan_in_created_status():
    customer_id, product_id = uuid.uuid4(), uuid.uuid4()
    loan = Loan.apply(customer_id, product_id, Decimal("10.00"), NOW)
    assert loan.status == LoanStatus.CREATED
    assert (loan.customer_id, loan.product_id, loan.principal) == (customer_id, product_id, Decimal("10.00"))
    assert loan.created_at == loan.updated_at == NOW
    assert loan.schedules == []


def test_apply_rejects_missing_principal():
    with pytest.raises(TypeError):
        Loan.apply(uuid.uuid4(), uuid.uuid4(), None, NOW)


def test_approve_only_from_created():
    loan = _loan()
    loan.approve()
    assert loan.status == LoanStatus.APPROVED
    with pytest.raises(DomainStateError):
        loan.approve()


def test_disburse_only_after_approved():
    loan = _loan()
    when = date(2026, 4, 1)
    with pytest.raises(DomainStateError):
        loan.disburse(when, Decimal("1100.00"), [_row("1100.00")], NOW)

    loan.approve()
    loan.disburse(when, Decimal("1100.00"), [_row("1100.00")], NOW)

    assert loan.status == LoanStatus.DISBURSED
    assert loan.disbursement_date == when
    assert loan.total_amount == Decimal("1100.00")
    assert len(loan.schedules) == 1
    assert loan.schedules[0].loan_id == loan.id


def test_disburse_wires_multiple_schedules_when_total_matches_sum():
    loan = _loan()
    loan.approve()
    a = _row("500.00")
    b = _row("500.00", date(2026, 6, 1))
    loan.disburse(date(2026, 4, 1), Decimal("1000.00"), [a, b], NOW)
    assert len(loan.schedules) == 2
    assert all(s.loan_id == loan.id for s in loan.schedules)


def test_disburse_rejects_schedule_total_mismatch():
    loan = _loan()
    loan.approve()
    with pytest.raises(DomainValidationError, match="does not match totalAmount"):
        loan.disburse(date(2026, 4, 1), Decimal("200.00"), [_row("100.00")], NOW)


def test_disburse_rejects_null_amount_due():
    loan = _loan()
    loan.approve()
    bad = _row("100.00")
    bad.amount_due = None
    with pytest.raises(DomainValidationError, match="amountDue"):
        loan.disburse(date(2026, 4, 1), Decimal("100.00"), [bad], NOW)


def test_disburse_second_call_is_idempotent_no_new_events():
    loan = _loan()
    loan.approve()
    when = date(2026, 4, 1)
    loan.disburse(when, Decimal("100.00"), [_row("100.00")], NOW)
    assert len(loan.pull_events()) == 1

    loan.disburse(when, Decimal("999.00"), [_row("999.00")], NOW)
    assert loan.total_amount == Decimal("100.00")
    assert len(loan.schedules) == 1
    assert loan.pull_events() == []


def test_disburse_emits_loan_disbursed_event():
    loan = _loan()
    loan.approve()
    when = date(2026, 4, 1)
    loan.disburse(when, Decimal("1100.00"), [_row("1100.00")], NOW)

    events = loan.pull_events()
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, LoanDisbursedEvent)
    assert event.disbursement_date == when
    assert event.total_amount == Decimal("1100.00")
    assert event.occurred_at == NOW
    assert loan.pull_events() == []


def test_register_payment_received_records_event():
    loan = _loan()
    loan.register_payment_received(Decimal("5.00"), "ref-1", NOW)
    (event,) = loan.pull_events()
    assert isinstance(event, PaymentReceivedEvent)
    assert (event.amount, event.external_reference, event.occurred_at) == (Decimal("5.00"), "ref-1", NOW)


def test_apply_repayment_allocates_by_due_date_and_closes_when_settled():
    loan = _loan()
    loan.approve()
    later = _row("500.00", date(2026, 7, 1))
    earlier = _row("500.00", date(2026, 5, 1))
    loan.disburse(date(2026, 4, 1), Decimal("1000.00"), [later, earlier], NOW)

    loan.apply_repayment(Decimal("700.00"))

    assert loan.status == LoanStatus.DISBURSED
    assert earlier.amount_paid == Decimal("500.00")
    assert earlier.status == ScheduleStatus.PAID
    assert later.amount_paid == Decimal("200.00")
    assert later.status == ScheduleStatus.PENDING

    loan.apply_repayment(Decimal("300.00"))
    assert loan.status == LoanStatus.CLOSED
    assert later.amount_paid == Decimal("500.00")
    assert later.status == ScheduleStatus.PAID


def test_apply_repayment_rejects_overpayment():
    loan = _loan()
    loan.approve()
    loan.disburse(date(2026, 4, 1), Decimal("100.00"), [_row("100.00")], NOW)
    with pytest.raises(DomainValidationError, match="exceeds remaining obligation"):
        loan.apply_repayment(Decimal("150.00"))


def test_apply_repayment_rejects_non_positive_amount():
    loan = _loan()
    with pytest.raises(DomainValidationError, match="must be positive"):
        loan.apply_repayment(Decimal("0"))


def test_apply_repayment_requires_disbursed():
    loan = _loan()
    loan.approve()
    with pytest.raises(DomainStateError, match="^Loan is not active for repayment$"):
        loan.apply_repayment(Decimal("10.00"))


def _overdue_loan(disbursed: date = date(2026, 1, 1)) -> tuple[Loan, RepaymentSchedule]:
    loan = _loan("100.00")
    loan.approve()
    row = _row("100.00", date(2026, 1, 1))
    loan.disburse(disbursed, Decimal("100.00"), [row], NOW)
    loan.check_overdue(date(2026, 1, 5), NOW)
    return loan, row


def test_apply_default_policy_sets_defaulted_when_overdue_beyond_threshold():
    loan, row = _overdue_loan()
    assert row.is_overdue()
    loan.apply_default_policy(date(2026, 4, 10), 90)
    assert loan.status == LoanStatus.DEFAULTED


def test_apply_default_policy_no_op_when_within_grace():
    loan, _ = _overdue_loan()
    loan.apply_default_policy(date(2026, 1, 20), 90)
    assert loan.status == LoanStatus.DISBURSED


def test_apply_repayment_allowed_when_defaulted():
    loan, _ = _overdue_loan()
    loan.apply_default_policy(date(2026, 5, 1), 0)
    assert loan.status == LoanStatus.DEFAULTED
    loan.apply_repayment(Decimal("100.00"))
    assert loan.status == LoanStatus.CLOSED


def test_apply_repayment_rejects_when_already_closed():
    loan = _loan()
    loan.approve()
    loan.disburse(date(2026, 4, 1), Decimal("100.00"), [_row("100.00")], NOW)
    loan.apply_repayment(Decimal("100.00"))
    assert loan.status == LoanStatus.CLOSED
    with pytest.raises(DomainStateError, match="^Loan is not active for repayment$"):
        loan.apply_repayment(Decimal("1.00"))


def test_summary_and_credit_to_release():
    loan = _loan("100.00")
    assert loan.credit_to_release == Decimal("100.00")
    loan.approve()
    first, second = _row("60.00", date(2026, 1, 1)), _row("60.00", date(2026, 2, 1))
    loan.disburse(date(2025, 12, 1), Decimal("120.00"), [first, second], NOW)
    loan.check_overdue(date(2026, 1, 10), NOW)
    first.record_penalty_accrual(Decimal("0.60"), date(2026, 1, 10))
    loan.apply_repayment(Decimal("20.00"))

    summary = loan.summary()
    assert loan.credit_to_release == Decimal("120.00")
    assert summary.principal == Decimal("100.00")
    assert summary.paid == Decimal("20.00")
    assert summary.remaining == Decimal("100.00")
    assert summary.overdue == Decimal("40.00")
    assert summary.penalties == Decimal("0.60")


# --- LoanOverdueTest ---------------------------------------------------------------------------------------


def test_check_overdue_marks_schedule_overdue_does_not_set_loan_to_defaulted():
    loan = _loan("100.00")
    loan.approve()
    row = _row("100.00", date(2026, 1, 1), "2025-12-01T12:00:00")
    loan.disburse(date(2025, 12, 1), Decimal("100.00"), [row], NOW)
    loan.pull_events()

    loan.check_overdue(date(2026, 1, 15), NOW)

    assert loan.status == LoanStatus.DISBURSED
    assert row.status == ScheduleStatus.OVERDUE
    events = loan.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], LoanOverdueEvent)

    loan.check_overdue(date(2026, 1, 16), NOW)
    assert loan.pull_events() == []  # only newly-overdue rows raise an event


def test_repay_after_overdue_closes_schedule():
    loan = _loan("100.00")
    loan.approve()
    row = _row("100.00", date(2026, 1, 1), "2025-12-01T12:00:00")
    loan.disburse(date(2025, 12, 1), Decimal("100.00"), [row], NOW)
    loan.check_overdue(date(2026, 2, 1), NOW)
    assert row.status == ScheduleStatus.OVERDUE

    loan.apply_repayment(Decimal("100.00"))

    assert row.status == ScheduleStatus.PAID
    assert loan.status == LoanStatus.CLOSED
