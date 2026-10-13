"""Scheduled maintenance (Java ``LoanMaintenanceScheduler`` and ``PaymentDueReminderScheduler``).

Both are idempotent and safe to re-run for the same business date.
"""

import logging

from injector import inject

from src.application.config import LoanPolicy
from src.application.domain.events import PaymentDueEvent
from src.application.domain.loan import LoanStatus
from src.application.domain.schedule import apply_penalties
from src.application.ports.services import IClock
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import ILoanMaintenanceUseCases

log = logging.getLogger(__name__)


class LoanMaintenanceUseCases(ILoanMaintenanceUseCases):
    @inject
    def __init__(self, uow: IUnitOfWork, clock: IClock, policy: LoanPolicy):
        self.uow = uow
        self.clock = clock
        self.policy = policy

    def process_overdues_and_penalties(self) -> int:
        """Marks overdue rows, accrues daily penalties and applies the default policy for each active loan."""
        today, now = self.clock.today(), self.clock.now()
        with self.uow:
            loans = self.uow.loans.list_by_status(LoanStatus.DISBURSED)
            for loan in loans:
                loan.check_overdue(today, now)
                apply_penalties(loan, today, self.policy.daily_penalty_rate)
                loan.apply_default_policy(today, self.policy.default_after_days_past_due)
        log.info("Overdue/penalty run complete for %d active loans (business date %s)", len(loans), today)
        return len(loans)

    def publish_due_reminders(self) -> int:
        """Queues ``PaymentDueEvent`` for unpaid rows due exactly ``reminder_days_before_due`` days out."""
        today, now = self.clock.today(), self.clock.now()
        count = 0
        with self.uow:
            for loan in self.uow.loans.list_by_status(LoanStatus.DISBURSED):
                for row in loan.schedules:
                    if row.is_fully_paid():
                        continue
                    if (row.due_date - today).days == self.policy.reminder_days_before_due:
                        self.uow.add_event(
                            PaymentDueEvent(
                                loan_id=loan.id,
                                customer_id=loan.customer_id,
                                due_date=row.due_date,
                                occurred_at=now,
                            )
                        )
                        count += 1
        return count
