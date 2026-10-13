"""Repayment schedule generation and penalty accrual (pure domain services)."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from src.application.domain import loan_product_rules as rules
from src.application.domain import pricing
from src.application.domain.errors import DomainValidationError
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.repayment import RepaymentSchedule

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class DisbursementPlan:
    """What to pass into ``Loan.disburse``."""

    disbursement_date: date
    total_amount: Decimal
    schedules: list[RepaymentSchedule]


class ScheduleGenerator(Protocol):
    def generate(
        self, loan: Loan, disbursement_date: date, product: LoanProduct, now: datetime
    ) -> DisbursementPlan: ...


def add_months(d: date, months: int) -> date:
    """Like Java ``LocalDate.plusMonths``: clamps to the last day of the target month."""
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


class EqualInstallmentsScheduleGenerator:
    """Equal installments over ``config.installments`` every ``config.installment_period_months`` months.

    The contractual total is principal + simple-APR finance charge + origination fee; the last installment
    absorbs rounding so the rows sum exactly to the total.
    """

    def generate(
        self, loan: Loan, disbursement_date: date, product: LoanProduct, now: datetime
    ) -> DisbursementPlan:
        installments = rules.config_int(product.config, rules.CONFIG_INSTALLMENTS)
        period_months = rules.config_int(product.config, rules.CONFIG_INSTALLMENT_PERIOD_MONTHS)
        if installments <= 0:
            raise DomainValidationError("installments must be positive")
        if period_months <= 0:
            raise DomainValidationError("installment_period_months must be positive")

        principal = loan.principal
        total = (
            principal
            + pricing.finance_charge(product, principal, installments)
            + pricing.upfront_fees(product)
        )
        per_installment = (total / installments).quantize(CENTS, ROUND_HALF_UP)

        rows: list[RepaymentSchedule] = []
        allocated = Decimal(0)
        for i in range(installments):
            if i == installments - 1:
                amount_due = total - allocated
            else:
                amount_due = per_installment
                allocated += amount_due
            rows.append(
                RepaymentSchedule(
                    due_date=add_months(disbursement_date, (i + 1) * period_months),
                    amount_due=amount_due,
                    created_at=now,
                )
            )
        return DisbursementPlan(disbursement_date, total, rows)


class RoutingScheduleGenerator:
    """Selects the generator from ``product.repayment_strategy``.

    ``EQUAL_PRINCIPAL_INSTALLMENTS`` currently shares the equal-installment generator (as in the Java source).
    """

    def __init__(self, equal_installments: EqualInstallmentsScheduleGenerator | None = None):
        self._equal_installments = equal_installments or EqualInstallmentsScheduleGenerator()

    def generate(
        self, loan: Loan, disbursement_date: date, product: LoanProduct, now: datetime
    ) -> DisbursementPlan:
        strategy = product.repayment_strategy
        if not strategy or not strategy.strip():
            raise DomainValidationError("repayment_strategy is required")
        match strategy.upper():
            case rules.REPAYMENT_EQUAL_INSTALLMENTS | rules.REPAYMENT_EQUAL_PRINCIPAL_INSTALLMENTS:
                return self._equal_installments.generate(loan, disbursement_date, product, now)
            case _:
                raise DomainValidationError(f"Unknown repayment_strategy: {strategy}")


def apply_penalties(loan: Loan, accrual_date: date, daily_rate: Decimal) -> None:
    """``penalty = remaining_due × daily_rate`` per overdue row; idempotent per row per ``accrual_date``."""
    if loan.status != LoanStatus.DISBURSED:
        return
    for schedule in loan.schedules:
        if not schedule.is_overdue():
            continue
        if schedule.penalty_last_accrual_date == accrual_date:
            continue
        overdue_amount = schedule.remaining_due()
        if overdue_amount <= 0:
            continue
        schedule.record_penalty_accrual(overdue_amount * daily_rate, accrual_date)
