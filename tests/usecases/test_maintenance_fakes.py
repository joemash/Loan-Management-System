"""Scheduled maintenance use cases against in-memory fakes."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from src.application.config import LoanPolicy
from src.application.domain.events import LoanOverdueEvent, PaymentDueEvent
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.repayment import RepaymentSchedule, ScheduleStatus
from src.application.usecases.maintenance import LoanMaintenanceUseCases
from tests.fakes import FakeClock, FakeUnitOfWork

START = datetime(2026, 1, 1, 1, 0)
POLICY = LoanPolicy(
    daily_penalty_rate=Decimal("0.01"), default_after_days_past_due=90, reminder_days_before_due=3
)


def _disbursed_loan(uow: FakeUnitOfWork) -> Loan:
    """100.00 over two installments due 2026-02-01 and 2026-03-01."""
    loan = Loan.apply(uuid.uuid4(), uuid.uuid4(), Decimal("100.00"), START)
    loan.approve()
    rows = [
        RepaymentSchedule(due_date=date(2026, 2, 1), amount_due=Decimal("50.00"), created_at=START),
        RepaymentSchedule(due_date=date(2026, 3, 1), amount_due=Decimal("50.00"), created_at=START),
    ]
    loan.disburse(date(2026, 1, 1), Decimal("100.00"), rows, START)
    loan.pull_events()
    uow.loans.add(loan)
    return loan


def _maintenance(day: date) -> tuple[LoanMaintenanceUseCases, FakeUnitOfWork, FakeClock]:
    uow, clock = FakeUnitOfWork(), FakeClock(datetime.combine(day, datetime.min.time()).replace(hour=1))
    return LoanMaintenanceUseCases(uow, clock, POLICY), uow, clock


def test_overdue_run_marks_overdue_accrues_penalty_once_per_day_and_notifies_once():
    maintenance, uow, _ = _maintenance(date(2026, 2, 5))
    loan = _disbursed_loan(uow)

    assert maintenance.process_overdues_and_penalties() == 1
    maintenance.process_overdues_and_penalties()

    first, second = sorted(loan.schedules, key=lambda s: s.due_date)
    assert first.status == ScheduleStatus.OVERDUE
    assert first.penalty_accrued == Decimal("0.50")
    assert second.status == ScheduleStatus.PENDING
    assert loan.status == LoanStatus.DISBURSED
    assert len(uow.publisher.of_type(LoanOverdueEvent)) == 1
    assert uow.commits == 2


def test_overdue_run_defaults_loan_at_threshold():
    maintenance, uow, clock = _maintenance(date(2026, 2, 5))
    loan = _disbursed_loan(uow)
    maintenance.process_overdues_and_penalties()

    clock.set(datetime(2026, 5, 1, 1, 0))  # 89 days past the first due date
    maintenance.process_overdues_and_penalties()
    assert loan.status == LoanStatus.DISBURSED

    clock.set(datetime(2026, 5, 2, 1, 0))  # 90 days
    maintenance.process_overdues_and_penalties()
    assert loan.status == LoanStatus.DEFAULTED

    # Defaulted loans are no longer "active", so later runs skip them.
    assert maintenance.process_overdues_and_penalties() == 0


def test_reminders_queue_payment_due_only_on_lookahead_day():
    maintenance, uow, clock = _maintenance(date(2026, 1, 28))
    loan = _disbursed_loan(uow)
    assert maintenance.publish_due_reminders() == 0

    clock.set(datetime(2026, 1, 29, 1, 0))
    assert maintenance.publish_due_reminders() == 1
    (event,) = uow.publisher.of_type(PaymentDueEvent)
    assert (event.loan_id, event.customer_id, event.due_date) == (loan.id, loan.customer_id, date(2026, 2, 1))


def test_reminders_skip_paid_installments():
    maintenance, uow, _ = _maintenance(date(2026, 1, 29))
    loan = _disbursed_loan(uow)
    loan.apply_repayment(Decimal("50.00"))
    assert maintenance.publish_due_reminders() == 0
    assert uow.publisher.events == []
