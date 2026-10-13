"""Notification recording, outbox relay and delivery tracking (Java ``NotificationService``,
``NotificationOutboxPublisher``, ``NotificationConsumer``, ``AdminNotificationQueryService``).

``record_*`` handlers run in their own unit of work (``REQUIRES_NEW``) and are idempotent on a
deterministic ``event_id``.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from injector import inject

from src.application.config import NotificationPolicy
from src.application.domain.errors import NotFoundError
from src.application.domain.events import (
    LoanDisbursedEvent,
    LoanOverdueEvent,
    PaymentDueEvent,
    PaymentReceivedEvent,
)
from src.application.domain.notification import (
    DeliveryStatus,
    Notification,
    NotificationEventMessage,
    NotificationOutbox,
    NotificationType,
    UiStatus,
    event_id_from,
)
from src.application.ports.pagination import Page, PageQuery
from src.application.ports.repo import NotificationFilter
from src.application.ports.services import (
    IClock,
    INotificationChannel,
    INotificationMetrics,
    INotificationProducer,
)
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import INotificationUseCases

log = logging.getLogger(__name__)


def _str(value: Any) -> str | None:
    return None if value is None else (format(value, "f") if hasattr(value, "as_tuple") else str(value))


class NotificationUseCases(INotificationUseCases):
    @inject
    def __init__(
        self,
        uow: IUnitOfWork,
        clock: IClock,
        policy: NotificationPolicy,
        producer: INotificationProducer,
        channel: INotificationChannel,
        metrics: INotificationMetrics,
    ):
        self.uow = uow
        self.clock = clock
        self.policy = policy
        self.producer = producer
        self.channel = channel
        self.metrics = metrics

    # --- recording (domain event handlers) ---------------------------------------------------------

    def record_loan_disbursed(self, event: LoanDisbursedEvent) -> None:
        event_id = event_id_from(event.loan_id, NotificationType.LOAN_DISBURSED, event.occurred_at)
        payload = {
            "loanId": _str(event.loan_id),
            "totalAmount": _str(event.total_amount),
            "disbursementDate": _str(event.disbursement_date),
            "eventId": str(event_id),
        }
        self._record(NotificationType.LOAN_DISBURSED, event.customer_id, event_id, payload)
        log.info(
            "[notification stub] LOAN_DISBURSED loanId=%s customerId=%s", event.loan_id, event.customer_id
        )

    def record_payment_received(self, event: PaymentReceivedEvent) -> None:
        event_id = event_id_from(event.loan_id, NotificationType.PAYMENT_RECEIVED, event.occurred_at)
        payload = {
            "loanId": str(event.loan_id),
            "amount": _str(event.amount),
            "externalReference": event.external_reference,
            "eventId": str(event_id),
        }
        self._record(NotificationType.PAYMENT_RECEIVED, event.customer_id, event_id, payload)
        log.info("[notification stub] PAYMENT_RECEIVED loanId=%s amount=%s", event.loan_id, event.amount)

    def record_loan_overdue(self, event: LoanOverdueEvent) -> None:
        event_id = event_id_from(event.loan_id, NotificationType.LOAN_OVERDUE, event.occurred_at)
        payload = {"loanId": str(event.loan_id), "eventId": str(event_id)}
        self._record(NotificationType.LOAN_OVERDUE, event.customer_id, event_id, payload)
        log.info("[notification stub] LOAN_OVERDUE loanId=%s", event.loan_id)

    def record_payment_due(self, event: PaymentDueEvent) -> None:
        event_id = event_id_from(event.loan_id, NotificationType.PAYMENT_DUE, event.occurred_at)
        payload = {"loanId": str(event.loan_id), "dueDate": str(event.due_date), "eventId": str(event_id)}
        self._record(NotificationType.PAYMENT_DUE, event.customer_id, event_id, payload)
        log.info("[notification stub] PAYMENT_DUE loanId=%s dueDate=%s", event.loan_id, event.due_date)

    def _record(self, type_: str, customer_id: uuid.UUID | None, event_id: uuid.UUID, payload: dict) -> None:
        with self.uow:
            if self.uow.notifications.get_by_event_id(event_id) is not None:
                return
            now = self.clock.now()
            notification = Notification.for_event(type_, customer_id, event_id, payload, now)
            self.uow.notifications.add(notification)
            self.uow.outbox.add(NotificationOutbox.for_notification(notification, self.policy.topic, now))

    # --- admin ------------------------------------------------------------------------------------

    def get(self, notification_id: uuid.UUID) -> Notification:
        with self.uow:
            return self._notification(notification_id)

    def search(self, criteria: NotificationFilter, query: PageQuery) -> Page[Notification]:
        with self.uow:
            return self.uow.notifications.search(criteria, query)

    def mark_read(self, notification_id: uuid.UUID) -> None:
        with self.uow:
            self._notification(notification_id).mark_read(self.clock.now())

    # --- delivery ---------------------------------------------------------------------------------

    def publish_pending(self) -> int:
        """Relays up to 100 due outbox rows with exponential backoff; dead-letters after max attempts."""
        published = 0
        with self.uow:
            now = self.clock.now()
            for outbox in self.uow.outbox.due_for_publish(now):
                try:
                    self.producer.send(outbox.topic, outbox.event_key, outbox.to_message())
                except Exception as ex:
                    outbox.mark_failed(str(ex), self.policy.max_attempts, now)
                    self.metrics.outbox_failed()
                    log.warning(
                        "Failed publishing notification outbox eventId=%s attempts=%s",
                        outbox.event_id,
                        outbox.attempts,
                        exc_info=True,
                    )
                else:
                    outbox.mark_published(now)
                    self.metrics.outbox_published()
                    published += 1
        return published

    def handle_delivery(self, message: NotificationEventMessage) -> None:
        event_id = uuid.UUID(message.eventId)
        try:
            self.channel.dispatch(message)
        except Exception as ex:
            self.metrics.consume_failed()
            now = self.clock.now()
            with self.uow:
                notification = self.uow.notifications.get_by_event_id(event_id)
                if notification is not None:
                    notification.mark_delivery_failed(
                        str(ex), self.policy.max_attempts, now + timedelta(minutes=5), now
                    )
            raise
        with self.uow:
            notification = self.uow.notifications.get_by_event_id(event_id)
            if notification is not None:
                notification.mark_delivered(self.clock.now())
        self.metrics.consumed()

    def stats(self) -> dict[str, int]:
        with self.uow:
            return {
                "failed": self.uow.notifications.count_by_delivery_status(DeliveryStatus.FAILED.value),
                "unread": self.uow.notifications.count_by_ui_status(UiStatus.UNREAD.value),
                "outbox_due": self.uow.outbox.count_due(self.clock.now()),
            }

    def _notification(self, notification_id: uuid.UUID) -> Notification:
        notification = self.uow.notifications.get(notification_id)
        if notification is None:
            raise NotFoundError(f"Notification not found: {notification_id}")
        return notification
