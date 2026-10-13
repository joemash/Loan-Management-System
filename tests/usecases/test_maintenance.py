"""Scheduled maintenance through the container: overdue/penalty/default runs and reminders, with
notifications recorded by the event bus after commit."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.application.config import LoanPolicy
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.notification import Notification
from src.application.domain.repayment import ScheduleStatus
from src.application.ports.services import IClock
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import ILoanUseCases
from src.application.usecases.maintenance import LoanMaintenanceUseCases
from tests.conftest import make_customer, make_product

POLICY = LoanPolicy(
    daily_penalty_rate=Decimal("0.01"), default_after_days_past_due=90, reminder_days_before_due=3
)


@pytest.fixture
def at(clock):
    def _at(day: date) -> None:
        clock.freeze(datetime.combine(day, datetime.min.time()).replace(hour=1))

    return _at


@pytest.fixture
def maintenance(injector):
    """Fresh use case (own unit of work) per run, like the scheduler adapter."""
    return lambda: LoanMaintenanceUseCases(injector.get(IUnitOfWork), injector.get(IClock), POLICY)


@pytest.fixture
def loans(injector) -> ILoanUseCases:
    return injector.get(ILoanUseCases)


def _disbursed_loan(session, loans, at) -> Loan:
    """100.00 over two installments, disbursed 2026-01-01 → due 2026-02-01 and 2026-03-01."""
    at(date(2026, 1, 1))
    customer = make_customer(session)
    product = make_product(session)
    loan = loans.apply(customer.id, product.id, Decimal("100.00"))
    loans.approve(loan.id)
    loans.disburse(loan.id)
    return loan


def _notification_types(session) -> list[str]:
    session.expire_all()
    return sorted(session.scalars(select(Notification.type)).all())


def _run(maintenance, at, day: date) -> None:
    at(day)
    maintenance().process_overdues_and_penalties()


def test_process_overdues_marks_overdue_accrues_penalty_and_notifies_once_per_day(
    session, loans, maintenance, at
):
    loan = _disbursed_loan(session, loans, at)

    _run(maintenance, at, date(2026, 2, 5))
    _run(maintenance, at, date(2026, 2, 5))

    session.expire_all()
    first, second = sorted(session.get(Loan, loan.id).schedules, key=lambda s: s.due_date)
    assert first.status == ScheduleStatus.OVERDUE
    assert first.penalty_accrued == Decimal("0.50")
    assert first.penalty_last_accrual_date == date(2026, 2, 5)
    assert second.status == ScheduleStatus.PENDING
    assert second.penalty_accrued == 0
    assert session.get(Loan, loan.id).status == LoanStatus.DISBURSED
    assert _notification_types(session) == ["LOAN_DISBURSED", "LOAN_OVERDUE"]

    summary = loans.summary(loan.id)
    assert summary.overdue == Decimal("50.00")
    assert summary.penalties == Decimal("0.50")


def test_process_overdues_defaults_loan_after_threshold(session, loans, maintenance, at):
    loan = _disbursed_loan(session, loans, at)

    _run(maintenance, at, date(2026, 2, 5))
    _run(maintenance, at, date(2026, 5, 1))  # 89 days past the first due date
    session.expire_all()
    assert session.get(Loan, loan.id).status == LoanStatus.DISBURSED

    _run(maintenance, at, date(2026, 5, 2))  # 90 days
    session.expire_all()
    assert session.get(Loan, loan.id).status == LoanStatus.DEFAULTED


def test_publish_due_reminders_emits_payment_due_only_on_lookahead_day(session, loans, maintenance, at):
    _disbursed_loan(session, loans, at)

    at(date(2026, 1, 28))
    maintenance().publish_due_reminders()
    assert _notification_types(session) == ["LOAN_DISBURSED"]

    at(date(2026, 1, 29))
    maintenance().publish_due_reminders()
    assert _notification_types(session) == ["LOAN_DISBURSED", "PAYMENT_DUE"]
    payload = session.scalars(select(Notification.payload).where(Notification.type == "PAYMENT_DUE")).one()
    assert payload["dueDate"] == "2026-02-01"


def test_publish_due_reminders_skips_paid_installments(session, loans, maintenance, at):
    loan = _disbursed_loan(session, loans, at)
    loans.repay(loan.id, Decimal("50.00"), "early-pay")

    at(date(2026, 1, 29))
    maintenance().publish_due_reminders()

    assert "PAYMENT_DUE" not in _notification_types(session)
