"""Notification + outbox recording through the container (Java ``NotificationServiceTest``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from src.application.domain.events import LoanDisbursedEvent
from src.application.domain.notification import Notification, NotificationOutbox
from src.application.ports.usecases import INotificationUseCases


def _event(customer_id=None) -> LoanDisbursedEvent:
    return LoanDisbursedEvent(
        loan_id=uuid.uuid4(),
        customer_id=customer_id or uuid.uuid4(),
        total_amount=Decimal("1100.00"),
        disbursement_date=date(2026, 3, 1),
        occurred_at=datetime(2026, 3, 1, 12, 0),
    )


def test_record_loan_disbursed_persists_stub_notification_and_outbox(session, injector):
    customer_id = uuid.uuid4()
    event = _event(customer_id)

    injector.get(INotificationUseCases).record_loan_disbursed(event)

    saved = session.scalars(select(Notification)).one()
    assert saved.type == "LOAN_DISBURSED"
    assert saved.channel == "STUB_LOG"
    assert saved.delivery_status == "PENDING"
    assert saved.customer_id == customer_id
    assert saved.payload["loanId"] == str(event.loan_id)
    assert saved.payload["totalAmount"] == "1100.00"

    outbox = session.scalars(select(NotificationOutbox)).one()
    assert outbox.status == "PENDING"
    assert outbox.notification_id == saved.id
    assert outbox.event_id == saved.event_id
    assert outbox.event_key == str(customer_id)


def test_record_loan_disbursed_is_idempotent_on_event_id(session, injector):
    event = _event()

    injector.get(INotificationUseCases).record_loan_disbursed(event)
    injector.get(INotificationUseCases).record_loan_disbursed(event)

    assert len(session.scalars(select(Notification)).all()) == 1
    assert len(session.scalars(select(NotificationOutbox)).all()) == 1
