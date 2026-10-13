"""Loan use cases resolved from the container against SQLite (Java ``ApplyLoanServiceTest``,
``LoanApplicationValidatorTest``, ``DisburseLoanServiceTest``, ``RepayLoanServiceTest`` and
``DefaultLedgerServiceTest``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from src.application.domain.customer import Customer
from src.application.domain.errors import DomainValidationError
from src.application.domain.ledger import (
    ACCOUNT_CUSTOMER,
    ACCOUNT_LOAN,
    REFERENCE_DISBURSEMENT,
    REFERENCE_REPAYMENT,
    LedgerAccount,
    LedgerEntry,
)
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.repayment import Payment, RepaymentSchedule
from src.application.domain.schedule import DisbursementPlan
from src.application.ports.services import IClock
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import ILoanUseCases
from src.application.usecases.loans import LoanUseCases
from tests.conftest import make_customer, make_product

FIXED_NOW = datetime(2026, 6, 15, 0, 0)
FIXED_DATE = date(2026, 6, 15)


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def loans(injector) -> ILoanUseCases:
    return injector.get(ILoanUseCases)


# --- ApplyLoanServiceTest / LoanApplicationValidatorTest -------------------------------------------------


def test_apply_persists_new_loan(session, loans):
    customer = make_customer(session)
    product = make_product(session)
    amount = Decimal("5000.00")

    saved = loans.apply(customer.id, product.id, amount)

    persisted = session.get(Loan, saved.id)
    assert persisted.customer_id == customer.id
    assert persisted.product_id == product.id
    assert persisted.principal == amount
    assert persisted.status == LoanStatus.CREATED


def test_apply_throws_when_customer_inactive(session, loans):
    customer = make_customer(session, status="SUSPENDED")
    with pytest.raises(DomainValidationError, match="not active"):
        loans.apply(customer.id, uuid.uuid4(), Decimal("100.00"))


def test_apply_throws_when_principal_exceeds_available_credit(session, loans):
    customer = make_customer(session, credit_limit="50.00")
    product = make_product(session)
    with pytest.raises(DomainValidationError, match="available credit"):
        loans.apply(customer.id, product.id, Decimal("100.00"))


def test_apply_throws_when_below_product_minimum(session, loans):
    customer = make_customer(session, credit_limit="50000.00")
    product = make_product(session, min_amount=Decimal("500.00"))
    with pytest.raises(DomainValidationError, match="minimum"):
        loans.apply(customer.id, product.id, Decimal("100.00"))
    assert _count(session, Loan) == 0


# --- DisburseLoanServiceTest -----------------------------------------------------------------------------


def _approved_loan(session, loans, principal: str = "1200.00", **product_overrides):
    customer = make_customer(session)
    product = make_product(session, **product_overrides)
    loan = loans.apply(customer.id, product.id, Decimal(principal))
    loans.approve(loan.id)
    return customer, product, loan


def test_disburse_generates_schedules_reserves_credit_posts_ledger_and_saves(session, loans, clock):
    customer, _, loan = _approved_loan(session, loans, config={"installments": 1})
    clock.freeze(FIXED_NOW)

    loans.disburse(loan.id)

    saved = session.get(Loan, loan.id)
    assert saved.status == LoanStatus.DISBURSED
    assert saved.disbursement_date == FIXED_DATE
    assert saved.total_amount == Decimal("1200.00")
    assert len(saved.schedules) == 1
    assert saved.schedules[0].due_date == date(2026, 7, 15)

    session.expire_all()  # the customer was cached in this session by make_customer
    assert session.get(Customer, customer.id).available_credit == Decimal("48800.00")
    entry = session.scalars(select(LedgerEntry)).one()
    assert entry.amount == Decimal("1200.00")
    assert entry.reference_type == REFERENCE_DISBURSEMENT
    assert entry.reference_id == loan.id
    assert session.get(LedgerAccount, entry.debit_account_id).account_type == ACCOUNT_LOAN
    assert session.get(LedgerAccount, entry.credit_account_id).account_type == ACCOUNT_CUSTOMER
    assert entry.created_at == FIXED_NOW


def test_disburse_uses_schedule_generator_with_todays_business_date(session, injector, clock):
    clock.freeze(FIXED_NOW)
    row = RepaymentSchedule(due_date=date(2026, 7, 15), amount_due=Decimal("1200.00"), created_at=FIXED_NOW)
    generator = MagicMock()
    generator.generate.return_value = DisbursementPlan(FIXED_DATE, Decimal("1200.00"), [row])
    loans = LoanUseCases(injector.get(IUnitOfWork), injector.get(IClock), generator)
    _, product, loan = _approved_loan(session, loans)

    loans.disburse(loan.id)

    generator.generate.assert_called_once()
    called_loan, called_date, called_product, called_now = generator.generate.call_args.args
    assert called_loan.id == loan.id
    assert called_date == FIXED_DATE
    assert called_product.id == product.id
    assert called_now == FIXED_NOW
    saved = session.get(Loan, loan.id)
    assert saved.status == LoanStatus.DISBURSED
    assert saved.total_amount == Decimal("1200.00")
    assert len(saved.schedules) == 1


def test_disburse_rolls_back_when_ledger_fails(session, loans):
    customer, _, loan = _approved_loan(session, loans)
    with (
        patch.object(LoanUseCases, "_post", side_effect=RuntimeError("ledger down")),
        pytest.raises(RuntimeError, match="ledger down"),
    ):
        loans.disburse(loan.id)

    session.expire_all()
    assert session.get(Loan, loan.id).status == LoanStatus.APPROVED
    assert _count(session, RepaymentSchedule) == 0
    assert session.get(Customer, customer.id).available_credit == Decimal("50000.00")


# --- RepayLoanServiceTest / DefaultLedgerServiceTest -----------------------------------------------------


def test_repay_skips_when_external_reference_already_processed(session, loans):
    _, _, loan = _approved_loan(session, loans)
    loans.disburse(loan.id)
    session.add(Payment.create(loan.id, Decimal("10.00"), datetime(2026, 8, 1, 12), "dup"))
    session.commit()
    ledger_before = _count(session, LedgerEntry)

    # An unknown loan id proves the loan is never loaded (no NotFoundError) once the reference is known.
    loans.repay(uuid.uuid4(), Decimal("10.00"), "dup")

    assert _count(session, Payment) == 1
    assert _count(session, LedgerEntry) == ledger_before


def test_repay_posts_customer_to_loan_entries_reusing_accounts(session, loans):
    customer, _, loan = _approved_loan(session, loans)
    loans.disburse(loan.id)

    loans.repay(loan.id, Decimal("40.00"), "r-1")
    loans.repay(loan.id, Decimal("60.00"), "r-2")

    assert _count(session, LedgerAccount) == 2
    entries = session.scalars(
        select(LedgerEntry).where(LedgerEntry.reference_type == REFERENCE_REPAYMENT)
    ).all()
    assert sorted(e.amount for e in entries) == [Decimal("40.00"), Decimal("60.00")]
    for entry in entries:
        debit = session.get(LedgerAccount, entry.debit_account_id)
        credit = session.get(LedgerAccount, entry.credit_account_id)
        assert (debit.account_type, debit.reference_id) == (ACCOUNT_CUSTOMER, customer.id)
        assert (credit.account_type, credit.reference_id) == (ACCOUNT_LOAN, loan.id)
        assert entry.reference_id == loan.id
