"""Customer credit line, ledger postings and notification/outbox entities."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.application.domain.customer import Customer
from src.application.domain.errors import DomainStateError, DomainValidationError
from src.application.domain.ledger import (
    ACCOUNT_CUSTOMER,
    ACCOUNT_LOAN,
    REFERENCE_DISBURSEMENT,
    LedgerAccount,
    LedgerEntry,
)
from src.application.domain.notification import (
    DeliveryStatus,
    Notification,
    NotificationEventMessage,
    NotificationOutbox,
    OutboxStatus,
    UiStatus,
    event_id_from,
    name_uuid_from_bytes,
)

NOW = datetime(2026, 3, 1, 12, 0)


def _customer(limit: str = "1000.00", status: str | None = None) -> Customer:
    return Customer.register("  Jane  ", " jane@example.com ", Decimal(limit), status, NOW)


# --- customer ---


def test_register_trims_and_defaults_to_active_with_full_credit():
    c = _customer()
    assert (c.name, c.email, c.status) == ("Jane", "jane@example.com", "ACTIVE")
    assert c.available_credit == c.credit_limit == Decimal("1000.00")


def test_reserve_and_release_credit():
    c = _customer()
    c.reserve_credit(Decimal("400.00"))
    assert c.available_credit == Decimal("600.00")
    with pytest.raises(DomainValidationError, match="Insufficient available credit"):
        c.reserve_credit(Decimal("601.00"))
    c.release_credit(Decimal("400.00"))
    assert c.available_credit == Decimal("1000.00")


def test_reserve_credit_requires_active_customer():
    c = _customer(status="SUSPENDED")
    with pytest.raises(DomainStateError, match="not active"):
        c.reserve_credit(Decimal("1.00"))


def test_update_credit_limit_shifts_available_by_delta_and_caps():
    c = _customer()
    c.reserve_credit(Decimal("300.00"))  # available 700
    later = NOW + timedelta(hours=1)
    c.update(later, credit_limit=Decimal("1500.00"))
    assert (c.credit_limit, c.available_credit, c.updated_at) == (
        Decimal("1500.00"),
        Decimal("1200.00"),
        later,
    )
    with pytest.raises(DomainValidationError, match="below outstanding reservation"):
        c.update(later, credit_limit=Decimal("200.00"))


# --- ledger ---


def test_ledger_post_links_accounts_by_id():
    loan_id, customer_id = uuid.uuid4(), uuid.uuid4()
    loan_acc = LedgerAccount.open(ACCOUNT_LOAN, loan_id, NOW)
    cust_acc = LedgerAccount.open(ACCOUNT_CUSTOMER, customer_id, NOW)
    entry = LedgerEntry.post(loan_acc, cust_acc, Decimal("500.00"), REFERENCE_DISBURSEMENT, loan_id, NOW)
    assert (entry.debit_account_id, entry.credit_account_id) == (loan_acc.id, cust_acc.id)
    assert (entry.amount, entry.reference_type, entry.reference_id, entry.created_at) == (
        Decimal("500.00"),
        REFERENCE_DISBURSEMENT,
        loan_id,
        NOW,
    )


# --- notification ---


def test_name_uuid_from_bytes_matches_java():
    # Java: UUID.nameUUIDFromBytes("hello".getBytes(UTF_8))
    assert str(name_uuid_from_bytes(b"hello")) == "5d41402a-bc4b-3a76-b971-9d911017c592"


def test_event_id_is_deterministic():
    loan_id = uuid.uuid4()
    assert event_id_from(loan_id, "LOAN_OVERDUE", NOW) == event_id_from(loan_id, "LOAN_OVERDUE", NOW)
    assert event_id_from(loan_id, "LOAN_OVERDUE", NOW) != event_id_from(loan_id, "PAYMENT_DUE", NOW)


def _notification(customer_id=None) -> Notification:
    return Notification.for_event("LOAN_OVERDUE", customer_id, uuid.uuid4(), {"k": "v"}, NOW)


def test_notification_lifecycle():
    n = _notification(uuid.uuid4())
    assert (n.delivery_status, n.ui_status, n.channel) == ("PENDING", "UNREAD", "STUB_LOG")
    later = NOW + timedelta(minutes=1)
    n.mark_read(later)
    n.mark_read(later + timedelta(minutes=1))  # idempotent
    assert (n.ui_status, n.read_at) == (UiStatus.READ, later)
    n.mark_delivery_failed("boom", 3, later, later)
    assert (n.delivery_status, n.attempt_count, n.last_error) == (DeliveryStatus.FAILED, 3, "boom")
    n.mark_delivered(later)
    assert (n.delivery_status, n.last_error, n.sent_at) == (DeliveryStatus.SENT, None, later)


def test_outbox_event_key_falls_back_to_system_and_builds_message():
    n = _notification()
    outbox = NotificationOutbox.for_notification(n, "topic", NOW)
    assert outbox.event_key == "system"
    assert (outbox.status, outbox.next_retry_at) == (OutboxStatus.PENDING, NOW)
    message = outbox.to_message()
    assert message == NotificationEventMessage(
        eventId=str(n.event_id), notificationId=str(n.id), payload={"k": "v"}
    )


def test_outbox_mark_failed_backs_off_then_dead_letters():
    outbox = NotificationOutbox.for_notification(_notification(uuid.uuid4()), "topic", NOW)
    outbox.mark_failed("down", 3, NOW)
    assert (outbox.status, outbox.attempts, outbox.next_retry_at) == (
        "PENDING",
        1,
        NOW + timedelta(seconds=2),
    )
    outbox.mark_failed("down", 3, NOW)
    assert outbox.next_retry_at == NOW + timedelta(seconds=4)
    outbox.mark_failed("down", 3, NOW)
    assert (outbox.status, outbox.attempts, outbox.last_error) == (OutboxStatus.DLQ, 3, "down")
    outbox.mark_published(NOW)
    assert (outbox.status, outbox.last_error) == (OutboxStatus.PUBLISHED, None)
