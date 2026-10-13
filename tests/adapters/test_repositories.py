"""SQLAlchemy repositories: paging/sorting, filters and ordering."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.adapters.repositories.repo_impl import (
    CustomerRepository,
    NotificationRepository,
    OutboxRepository,
    PaymentRepository,
)
from src.application.domain.customer import Customer
from src.application.domain.errors import DomainValidationError
from src.application.domain.notification import Notification, NotificationOutbox
from src.application.domain.repayment import Payment
from src.application.ports.pagination import PageQuery
from src.application.ports.repo import NotificationFilter
from tests.conftest import make_customer, make_product

NOW = datetime(2026, 3, 10, 12, 0)


def _customers(session, n: int) -> list[Customer]:
    created = []
    for i in range(n):
        c = Customer.register(
            f"C{i}", f"c{i}@example.com", Decimal("10.00"), None, NOW + timedelta(minutes=i)
        )
        session.add(c)
        created.append(c)
    session.commit()
    return created


def test_list_pages_and_sorts_by_camel_case_property(session):
    created = _customers(session, 5)
    repo = CustomerRepository(session)

    page = repo.list(PageQuery(page=1, size=2, sort=("createdAt,desc",)))

    assert (page.total, page.total_pages, page.page, page.size) == (5, 3, 1, 2)
    assert [c.name for c in page.items] == [created[2].name, created[1].name]


def test_list_rejects_unknown_sort_property(session):
    with pytest.raises(DomainValidationError, match="No property 'nope'"):
        CustomerRepository(session).list(PageQuery(sort=("nope",)))


def test_get_for_update_and_find_by_email(session):
    (customer,) = _customers(session, 1)
    repo = CustomerRepository(session)
    assert repo.get_for_update(customer.id) is customer
    assert repo.find_by_email("c0@example.com") is customer
    assert repo.find_by_email("missing@example.com") is None


def test_payments_listed_newest_first(session):
    customer, product = make_customer(session), make_product(session)
    from src.application.domain.loan import Loan

    loan = Loan.apply(customer.id, product.id, Decimal("10.00"), NOW)
    session.add(loan)
    session.add_all(
        [
            Payment.create(loan.id, Decimal("1"), NOW, "old"),
            Payment.create(loan.id, Decimal("1"), NOW + timedelta(days=1), "new"),
        ]
    )
    session.commit()
    repo = PaymentRepository(session)
    assert [p.external_reference for p in repo.list_for_loan(loan.id)] == ["new", "old"]
    assert repo.exists_by_external_reference("old")
    assert not repo.exists_by_external_reference("other")


def _notification(customer_id, type_, created: datetime, delivery="PENDING") -> Notification:
    n = Notification.for_event(type_, customer_id, uuid.uuid4(), {}, created)
    n.delivery_status = delivery
    return n


def test_notification_search_combines_filters_and_date_bounds(session):
    me, other = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            _notification(me, "LOAN_OVERDUE", datetime(2026, 3, 1, 23, 59)),
            _notification(me, "LOAN_OVERDUE", datetime(2026, 3, 2, 0, 0), delivery="FAILED"),
            _notification(me, "PAYMENT_DUE", datetime(2026, 3, 2, 10, 0)),
            _notification(other, "LOAN_OVERDUE", datetime(2026, 3, 2, 10, 0)),
        ]
    )
    session.commit()
    repo = NotificationRepository(session)

    def search(**criteria) -> int:
        return repo.search(NotificationFilter(**criteria), PageQuery()).total

    assert search(customer_id=me) == 3
    assert search(customer_id=me, type="loan_overdue") == 2
    assert search(customer_id=me, type="LOAN_OVERDUE", delivery_status="failed") == 1
    assert search(from_date=date(2026, 3, 2)) == 3
    assert search(to_date=date(2026, 3, 1)) == 1
    assert search(from_date=date(2026, 3, 2), to_date=date(2026, 3, 2), customer_id=other) == 1
    assert repo.count_by_delivery_status("FAILED") == 1
    assert repo.count_by_ui_status("UNREAD") == 4


def test_outbox_due_rows_oldest_first_and_count(session):
    rows = []
    for i, retry in enumerate(
        [NOW - timedelta(minutes=1), NOW + timedelta(minutes=1), NOW - timedelta(minutes=5)]
    ):
        n = _notification(uuid.uuid4(), "LOAN_OVERDUE", NOW)
        outbox = NotificationOutbox.for_notification(n, "t", NOW + timedelta(seconds=i))
        outbox.next_retry_at = retry
        rows.append(outbox)
    rows[2].status = "PUBLISHED"
    session.add_all(rows)
    session.commit()
    repo = OutboxRepository(session)

    due = repo.due_for_publish(NOW)

    assert due == [rows[0]]
    assert repo.count_due(NOW) == 1
