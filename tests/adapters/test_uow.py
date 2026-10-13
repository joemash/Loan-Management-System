"""SQLAlchemy unit of work: commit/rollback, after-commit event publishing and error translation."""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from src.adapters.repositories.uow_impl import SqlAlchemyUnitOfWork
from src.application.domain.customer import Customer
from src.application.domain.errors import ConcurrencyError, DataConflictError
from src.application.domain.events import PaymentDueEvent
from src.application.domain.loan import Loan, LoanStatus
from tests.conftest import make_customer, make_product
from tests.fakes import FakeEventPublisher

NOW = datetime(2026, 1, 1, 9, 0)


@pytest.fixture
def publisher() -> FakeEventPublisher:
    return FakeEventPublisher()


@pytest.fixture
def new_uow(injector, publisher):
    return lambda: SqlAlchemyUnitOfWork(injector.get(sessionmaker), publisher)


def _event() -> PaymentDueEvent:
    return PaymentDueEvent(
        loan_id=uuid.uuid4(), customer_id=uuid.uuid4(), due_date=date(2026, 2, 1), occurred_at=NOW
    )


def _customer(email: str) -> Customer:
    return Customer.register("Jane", email, Decimal("100.00"), None, NOW)


def test_commit_persists_and_publishes_only_after_exit(new_uow, publisher, session):
    uow = new_uow()
    customer = _customer("a@example.com")
    with uow:
        uow.customers.add(customer)
        uow.add_event(_event())
        assert publisher.events == []
    assert len(publisher.events) == 1
    assert session.get(Customer, customer.id).email == "a@example.com"
    assert uow.session is None  # session closed after the block


def test_rollback_discards_changes_and_events(new_uow, publisher, session):
    uow = new_uow()
    customer = _customer("b@example.com")
    with pytest.raises(RuntimeError, match="boom"), uow:
        uow.customers.add(customer)
        uow.add_event(_event())
        raise RuntimeError("boom")
    assert publisher.events == []
    assert session.get(Customer, customer.id) is None


def test_tracked_loan_events_publish_after_commit(new_uow, publisher, session):
    customer, product = make_customer(session), make_product(session)
    loan = Loan.apply(customer.id, product.id, Decimal("10.00"), NOW)
    loan.register_payment_received(Decimal("1.00"), "x", NOW)
    uow = new_uow()
    with uow:
        uow.loans.add(loan)
    assert len(publisher.events) == 1
    assert loan.pull_events() == []


def test_integrity_error_becomes_data_conflict(new_uow):
    with new_uow() as uow:
        uow.customers.add(_customer("dup@example.com"))
    with pytest.raises(DataConflictError, match="duplicate"), new_uow() as uow:
        uow.customers.add(_customer("dup@example.com"))


def test_stale_loan_update_becomes_concurrency_error(new_uow, session):
    customer, product = make_customer(session), make_product(session)
    loan = Loan.apply(customer.id, product.id, Decimal("10.00"), NOW)
    with new_uow() as uow:
        uow.loans.add(loan)

    with pytest.raises(ConcurrencyError), new_uow() as first:
        stale = first.loans.get(loan.id)
        with new_uow() as second:
            second.loans.get(loan.id).approve()
        stale.status = LoanStatus.APPROVED

    with new_uow() as uow:
        assert uow.loans.get(loan.id).status == LoanStatus.APPROVED


def test_nested_use_of_same_instance_is_rejected(new_uow):
    uow = new_uow()
    with pytest.raises(RuntimeError, match="already active"), uow, uow:
        pass
