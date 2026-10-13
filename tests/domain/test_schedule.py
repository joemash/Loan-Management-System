"""Schedule generators and penalty accrual (Java ``EqualInstallmentsScheduleGeneratorTest``,
``RoutingScheduleGeneratorTest`` and ``PenaltyAccrualServiceTest``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.application.domain.errors import DomainValidationError
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.repayment import RepaymentSchedule, ScheduleStatus
from src.application.domain.schedule import (
    DisbursementPlan,
    EqualInstallmentsScheduleGenerator,
    RoutingScheduleGenerator,
    add_months,
    apply_penalties,
)

NOW = datetime(2026, 1, 1, 9, 0)


def _loan_and_product(principal: str, config=None, interest="NONE") -> tuple[Loan, LoanProduct]:
    product_id = uuid.uuid4()
    loan = Loan.create(uuid.uuid4(), product_id, Decimal(principal), NOW)
    product = LoanProduct(
        id=product_id,
        interest_strategy=interest,
        repayment_strategy="EQUAL_INSTALLMENTS",
        fee_strategy="NONE",
        config=config,
    )
    return loan, product


def _total(plan: DisbursementPlan) -> Decimal:
    return sum((s.amount_due for s in plan.schedules), Decimal(0))


generator = EqualInstallmentsScheduleGenerator()


def test_generate_equal_installments_from_config():
    loan, product = _loan_and_product("300.00", {"installments": 3})
    disbursement = date(2026, 1, 10)

    plan = generator.generate(loan, disbursement, product, NOW)

    assert plan.disbursement_date == disbursement
    assert plan.total_amount == Decimal("300.00")
    assert len(plan.schedules) == 3
    assert _total(plan) == Decimal("300.00")
    assert plan.schedules[0].due_date == date(2026, 2, 10)
    assert plan.schedules[2].due_date == date(2026, 4, 10)
    assert all(s.created_at == NOW for s in plan.schedules)


def test_generate_adds_simple_apr_finance_charge():
    loan, product = _loan_and_product("1200.00", {"installments": 12, "apr": 0.1}, interest="SIMPLE_APR")

    plan = generator.generate(loan, date(2026, 1, 1), product, NOW)

    # Finance charge: 1200 * 0.1 * 12/12 = 120
    assert plan.total_amount == Decimal("1320.00")
    assert _total(plan) == Decimal("1320.00")


def test_generate_last_installment_absorbs_rounding():
    loan, product = _loan_and_product("1000.00", {"installments": 6, "apr": 0.12, "origination_fee": 25})
    product.interest_strategy, product.fee_strategy = "SIMPLE_APR", "FLAT_ORIGINATION"

    plan = generator.generate(loan, date(2026, 1, 1), product, NOW)

    assert plan.total_amount == Decimal("1085.00")
    assert [s.amount_due for s in plan.schedules] == [Decimal("180.83")] * 5 + [Decimal("180.85")]


def test_generate_defaults_to_single_installment_when_config_missing():
    loan, product = _loan_and_product("100.00")

    plan = generator.generate(loan, date(2026, 3, 1), product, NOW)

    assert len(plan.schedules) == 1
    assert plan.schedules[0].amount_due == Decimal("100.00")


def test_generate_uses_installment_period_months_when_configured():
    loan, product = _loan_and_product("200.00", {"installments": 2, "installment_period_months": 2})

    plan = generator.generate(loan, date(2026, 1, 15), product, NOW)

    assert len(plan.schedules) == 2
    assert plan.schedules[0].due_date == date(2026, 3, 15)
    assert plan.schedules[1].due_date == date(2026, 5, 15)


def test_add_months_clamps_to_end_of_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


# --- RoutingScheduleGeneratorTest --------------------------------------------------------------------------


def test_routing_delegates_to_equal_installments():
    loan, product = _loan_and_product("100.00")
    d = date(2026, 1, 1)
    equal = MagicMock(spec=EqualInstallmentsScheduleGenerator)
    equal.generate.return_value = DisbursementPlan(d, Decimal("100"), [])

    RoutingScheduleGenerator(equal).generate(loan, d, product, NOW)

    equal.generate.assert_called_once_with(loan, d, product, NOW)


def test_routing_throws_for_unknown_strategy():
    loan, product = _loan_and_product("100.00")
    product.repayment_strategy = "UNKNOWN_XYZ"
    with pytest.raises(DomainValidationError, match="Unknown repayment_strategy"):
        RoutingScheduleGenerator().generate(loan, date(2026, 1, 1), product, NOW)


# --- PenaltyAccrualServiceTest -----------------------------------------------------------------------------


def test_apply_penalties_idempotent_per_day():
    loan = Loan.create(uuid.uuid4(), uuid.uuid4(), Decimal("200.00"), NOW)
    loan.approve()
    row = RepaymentSchedule(
        due_date=date(2026, 1, 1), amount_due=Decimal("200.00"), created_at=datetime(2025, 12, 1, 12)
    )
    loan.disburse(date(2025, 12, 1), Decimal("200.00"), [row], NOW)
    loan.check_overdue(date(2026, 2, 1), NOW)
    assert row.status == ScheduleStatus.OVERDUE

    day = date(2026, 2, 1)
    rate = Decimal("0.01")
    apply_penalties(loan, day, rate)
    apply_penalties(loan, day, rate)

    assert row.penalty_accrued == Decimal("2.00")
    assert row.penalty_last_accrual_date == day


def test_apply_penalties_skips_non_disbursed():
    loan = Loan.create(uuid.uuid4(), uuid.uuid4(), Decimal("50.00"), NOW)
    apply_penalties(loan, date.today(), Decimal("0.1"))
    assert loan.status == LoanStatus.CREATED
