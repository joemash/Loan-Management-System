"""Notification use cases against in-memory fakes (recording, outbox relay, delivery)."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.application.config import NotificationPolicy
from src.application.domain.errors import NotFoundError
from src.application.domain.events import LoanDisbursedEvent, PaymentDueEvent, PaymentReceivedEvent
from src.application.domain.notification import DeliveryStatus, OutboxStatus, UiStatus
from src.application.ports.pagination import PageQuery
from src.application.ports.repo import NotificationFilter
from src.application.usecases.notifications import NotificationUseCases
from tests.fakes import FakeChannel, FakeClock, FakeMetrics, FakeProducer, FakeUnitOfWork

NOW = datetime(2026, 3, 1, 12, 0)


def _usecases(producer=None, channel=None, max_attempts=5):
    uow, clock, metrics = FakeUnitOfWork(), FakeClock(NOW), FakeMetrics()
    usecases = NotificationUseCases(
        uow,
        clock,
        NotificationPolicy(topic="notifications.events", max_attempts=max_attempts),
        producer or FakeProducer(),
        channel or FakeChannel(),
        metrics,
    )
    return usecases, uow, clock, metrics


def _disbursed_event(customer_id=None) -> LoanDisbursedEvent:
    return LoanDisbursedEvent(
        loan_id=uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        total_amount=Decimal("1100.00"),
        disbursement_date=date(2026, 3, 1),
        occurred_at=NOW,
    )


def test_record_creates_notification_and_outbox_once_per_event():
    usecases, uow, _, _ = _usecases()
    event = _disbursed_event()

    usecases.record_loan_disbursed(event)
    usecases.record_loan_disbursed(event)

    (notification,) = uow.notifications.items.values()
    assert notification.type == "LOAN_DISBURSED"
    assert notification.payload["totalAmount"] == "1100.00"
    assert notification.payload["loanId"] == str(event.loan_id)
    (outbox,) = uow.outbox.items
    assert (outbox.topic, outbox.event_key, outbox.notification_id) == (
        "notifications.events",
        str(event.customer_id),
        notification.id,
    )


def test_record_other_event_types_build_payloads():
    usecases, uow, _, _ = _usecases()
    loan_id, customer_id = uuid.uuid4(), uuid.uuid4()
    usecases.record_payment_received(
        PaymentReceivedEvent(
            loan_id=loan_id,
            customer_id=customer_id,
            amount=Decimal("5.50"),
            external_reference="r",
            occurred_at=NOW,
        )
    )
    usecases.record_payment_due(
        PaymentDueEvent(loan_id=loan_id, customer_id=customer_id, due_date=date(2026, 4, 1), occurred_at=NOW)
    )
    payloads = {n.type: n.payload for n in uow.notifications.items.values()}
    assert payloads["PAYMENT_RECEIVED"]["amount"] == "5.50"
    assert payloads["PAYMENT_DUE"]["dueDate"] == "2026-04-01"


def test_publish_pending_sends_due_rows_and_marks_published():
    producer = FakeProducer()
    usecases, uow, clock, metrics = _usecases(producer=producer)
    usecases.record_loan_disbursed(_disbursed_event())
    clock.set(NOW + timedelta(seconds=1))

    assert usecases.publish_pending() == 1
    (outbox,) = uow.outbox.items
    assert outbox.status == OutboxStatus.PUBLISHED
    ((topic, key, message),) = producer.sent
    assert (topic, key, message.eventId) == ("notifications.events", outbox.event_key, str(outbox.event_id))
    assert metrics.counts["outbox_published"] == 1
    assert usecases.publish_pending() == 0  # nothing left to send


def test_publish_pending_failure_backs_off_then_dead_letters():
    usecases, uow, clock, metrics = _usecases(producer=FakeProducer(fail=True), max_attempts=2)
    usecases.record_loan_disbursed(_disbursed_event())
    later = NOW + timedelta(seconds=1)
    clock.set(later)

    assert usecases.publish_pending() == 0
    (outbox,) = uow.outbox.items
    assert (outbox.status, outbox.attempts, outbox.last_error) == ("PENDING", 1, "broker unavailable")
    assert outbox.next_retry_at == later + timedelta(seconds=2)
    assert usecases.publish_pending() == 0  # still backing off
    assert outbox.attempts == 1

    clock.set(later + timedelta(seconds=3))
    usecases.publish_pending()
    assert (outbox.status, outbox.attempts) == (OutboxStatus.DLQ, 2)
    assert metrics.counts["outbox_failed"] == 2


def test_handle_delivery_success_marks_sent():
    channel = FakeChannel()
    usecases, uow, _, metrics = _usecases(channel=channel)
    usecases.record_loan_disbursed(_disbursed_event())
    message = uow.outbox.items[0].to_message()

    usecases.handle_delivery(message)

    (notification,) = uow.notifications.items.values()
    assert notification.delivery_status == DeliveryStatus.SENT
    assert notification.sent_at == NOW
    assert channel.dispatched == [message]
    assert metrics.counts["consumed"] == 1


def test_handle_delivery_failure_marks_failed_and_reraises():
    usecases, uow, _, metrics = _usecases(channel=FakeChannel(fail=True), max_attempts=5)
    usecases.record_loan_disbursed(_disbursed_event())

    with pytest.raises(RuntimeError, match="smtp down"):
        usecases.handle_delivery(uow.outbox.items[0].to_message())

    (notification,) = uow.notifications.items.values()
    assert notification.delivery_status == DeliveryStatus.FAILED
    assert (notification.attempt_count, notification.last_error) == (5, "smtp down")
    assert notification.next_retry_at == NOW + timedelta(minutes=5)
    assert metrics.counts["consume_failed"] == 1


def test_admin_queries_mark_read_and_stats():
    usecases, uow, _, _ = _usecases()
    customer_id = uuid.uuid4()
    usecases.record_loan_disbursed(_disbursed_event(customer_id))
    usecases.record_loan_disbursed(_disbursed_event())
    (mine,) = usecases.search(NotificationFilter(customer_id=customer_id), PageQuery()).items

    usecases.mark_read(mine.id)

    assert usecases.get(mine.id).ui_status == UiStatus.READ
    assert usecases.stats() == {"failed": 0, "unread": 1, "outbox_due": 0}
    with pytest.raises(NotFoundError):
        usecases.get(uuid.uuid4())
