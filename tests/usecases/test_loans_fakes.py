"""Loan use cases against in-memory fakes: no database, broker or container."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.application.domain.customer import Customer
from src.application.domain.errors import DomainStateError, DomainValidationError, NotFoundError
from src.application.domain.events import LoanDisbursedEvent, PaymentReceivedEvent
from src.application.domain.ledger import (
    ACCOUNT_CUSTOMER,
    ACCOUNT_LOAN,
    REFERENCE_DISBURSEMENT,
    REFERENCE_REPAYMENT,
)
from src.application.domain.loan import LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.schedule import RoutingScheduleGenerator
from src.application.ports.pagination import PageQuery
from src.application.usecases.loans import LoanUseCases
from tests.fakes import FakeClock, FakeUnitOfWork

NOW = datetime(2026, 6, 15, 9, 0)


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def loans(uow, clock) -> LoanUseCases:
    return LoanUseCases(uow, clock, RoutingScheduleGenerator())


def _customer(uow, limit="5000.00", status="ACTIVE") -> Customer:
    customer = Customer.register("Jane", f"{uuid.uuid4()}@x.io", Decimal(limit), status, NOW)
    uow.customers.add(customer)
    return customer


def _product(uow, **overrides) -> LoanProduct:
    fields = dict(
        name="P",
        interest_strategy="NONE",
        repayment_strategy="EQUAL_INSTALLMENTS",
        fee_strategy="NONE",
        config={"installments": 2},
        created_at=NOW,
    )
    fields.update(overrides)
    product = LoanProduct(**fields)
    uow.products.add(product)
    return product


def _disbursed(uow, loans, principal="1000.00", **product_overrides):
    customer = _customer(uow)
    product = _product(uow, **product_overrides)
    loan = loans.apply(customer.id, product.id, Decimal(principal))
    loans.approve(loan.id)
    loans.disburse(loan.id)
    return customer, loan


# --- apply / approve -------------------------------------------------------------------------------------


def test_apply_stores_created_loan_and_commits(uow, loans):
    customer, product = _customer(uow), _product(uow)
    loan = loans.apply(customer.id, product.id, Decimal("500.00"))
    assert uow.loans.get(loan.id) is loan
    assert loan.status == LoanStatus.CREATED
    assert loan.created_at == NOW
    assert uow.commits == 1


@pytest.mark.parametrize(
    ("customer_kwargs", "product_kwargs", "amount", "message"),
    [
        ({"status": "SUSPENDED"}, {}, "100.00", "Customer is not active"),
        ({"limit": "50.00"}, {}, "100.00", "exceeds available credit"),
        ({}, {"min_amount": Decimal("500.00")}, "100.00", "below product minimum"),
        ({}, {"interest_strategy": "MAGIC"}, "100.00", "Unsupported interestStrategy"),
    ],
)
def test_apply_validation_failures_roll_back(uow, loans, customer_kwargs, product_kwargs, amount, message):
    customer, product = _customer(uow, **customer_kwargs), _product(uow, **product_kwargs)
    with pytest.raises(DomainValidationError, match=message):
        loans.apply(customer.id, product.id, Decimal(amount))
    assert uow.loans.items == {}
    assert uow.rollbacks == 1


def test_apply_unknown_customer_is_not_found(uow, loans):
    with pytest.raises(NotFoundError, match="Customer not found"):
        loans.apply(uuid.uuid4(), _product(uow).id, Decimal("1"))


def test_approve_transitions_and_rejects_twice(uow, loans):
    loan = loans.apply(_customer(uow).id, _product(uow).id, Decimal("100.00"))
    assert loans.approve(loan.id).status == LoanStatus.APPROVED
    with pytest.raises(DomainStateError):
        loans.approve(loan.id)


# --- disburse --------------------------------------------------------------------------------------------


def test_disburse_reserves_total_posts_ledger_and_publishes_after_commit(uow, loans):
    customer, loan = _disbursed(
        uow,
        loans,
        interest_strategy="SIMPLE_APR",
        fee_strategy="FLAT_ORIGINATION",
        config={"installments": 6, "apr": 0.12, "origination_fee": 25},
    )

    assert loan.status == LoanStatus.DISBURSED
    assert loan.disbursement_date == date(2026, 6, 15)
    assert loan.total_amount == Decimal("1085.00")
    assert customer.available_credit == Decimal("3915.00")  # full contractual total reserved

    (entry,) = uow.ledger.entries
    assert uow.ledger.account(entry.debit_account_id).account_type == ACCOUNT_LOAN
    assert uow.ledger.account(entry.credit_account_id).account_type == ACCOUNT_CUSTOMER
    assert (entry.amount, entry.reference_type, entry.reference_id) == (
        Decimal("1000.00"),
        REFERENCE_DISBURSEMENT,
        loan.id,
    )

    (event,) = uow.publisher.of_type(LoanDisbursedEvent)
    assert (event.loan_id, event.total_amount, event.occurred_at) == (loan.id, Decimal("1085.00"), NOW)


def test_disburse_is_idempotent(uow, loans):
    customer, loan = _disbursed(uow, loans)
    loans.disburse(loan.id)
    assert customer.available_credit == Decimal("4000.00")
    assert len(uow.ledger.entries) == 1
    assert len(uow.publisher.of_type(LoanDisbursedEvent)) == 1


def test_disburse_failure_rolls_back_and_publishes_nothing(uow, loans):
    loan = loans.apply(_customer(uow).id, _product(uow).id, Decimal("100.00"))
    loans.approve(loan.id)
    with (
        patch.object(uow.ledger, "add_entry", side_effect=RuntimeError("ledger down")),
        pytest.raises(RuntimeError, match="ledger down"),
    ):
        loans.disburse(loan.id)
    assert uow.rollbacks == 1
    assert uow.publisher.events == []


def test_disburse_rejects_tenure_outside_product_bounds(uow, loans):
    loan = loans.apply(_customer(uow).id, _product(uow, max_tenure_days=30).id, Decimal("100.00"))
    loans.approve(loan.id)
    with pytest.raises(DomainValidationError, match="exceeds product maximum"):
        loans.disburse(loan.id)
    assert uow.publisher.events == []


# --- repay -----------------------------------------------------------------------------------------------


def test_repay_is_idempotent_on_external_reference(uow, loans):
    _, loan = _disbursed(uow, loans)
    loans.repay(loan.id, Decimal("100.00"), "pay-1")
    loans.repay(loan.id, Decimal("100.00"), "pay-1")

    assert len(uow.payments.items) == 1
    assert len(uow.publisher.of_type(PaymentReceivedEvent)) == 1
    assert loan.summary().paid == Decimal("100.00")
    repayment_entries = [e for e in uow.ledger.entries if e.reference_type == REFERENCE_REPAYMENT]
    assert len(repayment_entries) == 1
    assert uow.ledger.account(repayment_entries[0].debit_account_id).account_type == ACCOUNT_CUSTOMER
    assert len(uow.ledger.accounts) == 2  # accounts are opened once and reused
    (audit,) = uow.audit.items
    assert audit.payload == {"amount": "100.00", "externalReference": "pay-1"}


def test_repay_closing_payment_releases_credit(uow, loans):
    customer, loan = _disbursed(uow, loans)
    loans.repay(loan.id, Decimal("1000.00"), "full")
    assert loan.status == LoanStatus.CLOSED
    assert customer.available_credit == Decimal("5000.00")


def test_repay_overpayment_raises_and_publishes_nothing(uow, loans):
    _, loan = _disbursed(uow, loans)
    published = len(uow.publisher.events)
    with pytest.raises(DomainValidationError, match="exceeds remaining obligation"):
        loans.repay(loan.id, Decimal("5000.00"), "too-much")
    assert len(uow.publisher.events) == published
    assert uow.rollbacks == 1


def test_repay_skips_unknown_loan_when_reference_already_processed(uow, loans):
    _, loan = _disbursed(uow, loans)
    loans.repay(loan.id, Decimal("10.00"), "dup")
    loans.repay(uuid.uuid4(), Decimal("10.00"), "dup")  # never loads the loan → no NotFoundError
    assert len(uow.payments.items) == 1


# --- queries ---------------------------------------------------------------------------------------------


def test_detail_sorts_schedules_and_lists_payments_newest_first(uow, loans, clock):
    _, loan = _disbursed(uow, loans)
    loans.repay(loan.id, Decimal("10.00"), "first")
    clock.set(datetime(2026, 6, 16, 9, 0))
    loans.repay(loan.id, Decimal("10.00"), "second")

    detail = loans.detail(loan.id)
    assert [s.due_date for s in detail.schedules] == sorted(s.due_date for s in loan.schedules)
    assert [p.external_reference for p in detail.payments] == ["second", "first"]
    assert detail.summary.paid == Decimal("20.00")


def test_list_rejects_unknown_status(loans):
    with pytest.raises(DomainValidationError, match="Invalid loan status: nope"):
        loans.list(PageQuery(), status="nope")
