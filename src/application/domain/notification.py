"""Notifications and their transactional outbox rows."""

import enum
import hashlib
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

CHANNEL_STUB_LOG = "STUB_LOG"


class NotificationType(enum.StrEnum):
    LOAN_DISBURSED = "LOAN_DISBURSED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    LOAN_OVERDUE = "LOAN_OVERDUE"
    PAYMENT_DUE = "PAYMENT_DUE"


class DeliveryStatus(enum.StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DLQ = "DLQ"


class OutboxStatus(enum.StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DLQ = "DLQ"


class UiStatus(enum.StrEnum):
    UNREAD = "UNREAD"
    READ = "READ"


def name_uuid_from_bytes(data: bytes) -> uuid.UUID:
    """Java ``UUID.nameUUIDFromBytes``: MD5-based (version 3) UUID without a namespace."""
    digest = bytearray(hashlib.md5(data).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(digest))


def event_id_from(loan_id: uuid.UUID | None, type_: str, occurred_at: datetime) -> uuid.UUID:
    """Deterministic id so the same domain event is only recorded once."""
    loan = str(loan_id) if loan_id is not None else "null"
    return name_uuid_from_bytes(f"{loan}:{type_}:{occurred_at.isoformat()}".encode())


class Notification:
    def __init__(
        self,
        *,
        id: uuid.UUID,
        customer_id: uuid.UUID | None,
        event_id: uuid.UUID | None,
        type: str | None,
        channel: str | None,
        payload: dict[str, Any] | None,
        created_at: datetime,
        updated_at: datetime,
        delivery_status: str | None = DeliveryStatus.PENDING.value,
        ui_status: str = UiStatus.UNREAD.value,
        attempt_count: int = 0,
        last_error: str | None = None,
        next_retry_at: datetime | None = None,
        sent_at: datetime | None = None,
        read_at: datetime | None = None,
        status: str | None = None,
    ):
        self.id = id
        self.customer_id = customer_id
        self.event_id = event_id
        self.type = type
        self.channel = channel
        self.payload = payload
        self.status = status  # legacy column from V6, superseded by delivery_status
        self.delivery_status = delivery_status
        self.ui_status = ui_status
        self.attempt_count = attempt_count
        self.last_error = last_error
        self.next_retry_at = next_retry_at
        self.sent_at = sent_at
        self.read_at = read_at
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def for_event(
        cls, type_: str, customer_id: uuid.UUID | None, event_id: uuid.UUID, payload: dict, now: datetime
    ) -> "Notification":
        return cls(
            id=uuid.uuid4(),
            customer_id=customer_id,
            event_id=event_id,
            type=str(type_),
            channel=CHANNEL_STUB_LOG,
            payload=payload,
            created_at=now,
            updated_at=now,
        )

    def mark_read(self, now: datetime) -> None:
        if self.ui_status == UiStatus.READ:
            return
        self.ui_status = UiStatus.READ.value
        self.read_at = now
        self.updated_at = now

    def mark_delivered(self, now: datetime) -> None:
        self.delivery_status = DeliveryStatus.SENT.value
        self.sent_at = now
        self.last_error = None
        self.updated_at = now

    def mark_delivery_failed(self, error: str, attempts: int, next_retry_at: datetime, now: datetime) -> None:
        self.attempt_count = attempts
        self.last_error = error
        self.next_retry_at = next_retry_at
        self.delivery_status = DeliveryStatus.FAILED.value
        self.updated_at = now


@dataclass(frozen=True)
class NotificationEventMessage:
    """Message relayed through the broker (wire format matches the Java record)."""

    eventId: str  # noqa: N815
    notificationId: str  # noqa: N815
    customerId: str | None = None  # noqa: N815
    type: str | None = None
    channel: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotificationEventMessage":
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})


class NotificationOutbox:
    """Transactional outbox row, relayed to the broker by the notification use cases."""

    def __init__(
        self,
        *,
        id: uuid.UUID,
        event_id: uuid.UUID,
        notification_id: uuid.UUID,
        topic: str,
        event_key: str,
        payload: dict[str, Any],
        status: str,
        created_at: datetime,
        attempts: int = 0,
        last_error: str | None = None,
        next_retry_at: datetime | None = None,
        published_at: datetime | None = None,
    ):
        self.id = id
        self.event_id = event_id
        self.notification_id = notification_id
        self.topic = topic
        self.event_key = event_key
        self.payload = payload
        self.status = status
        self.attempts = attempts
        self.last_error = last_error
        self.next_retry_at = next_retry_at
        self.created_at = created_at
        self.published_at = published_at

    @classmethod
    def for_notification(cls, notification: Notification, topic: str, now: datetime) -> "NotificationOutbox":
        return cls(
            id=uuid.uuid4(),
            event_id=notification.event_id,
            notification_id=notification.id,
            topic=topic,
            event_key=str(notification.customer_id) if notification.customer_id is not None else "system",
            payload=notification.payload or {},
            status=OutboxStatus.PENDING.value,
            created_at=now,
            next_retry_at=now,
        )

    def to_message(self) -> NotificationEventMessage:
        return NotificationEventMessage(
            eventId=str(self.event_id), notificationId=str(self.notification_id), payload=self.payload
        )

    def mark_published(self, now: datetime) -> None:
        self.status = OutboxStatus.PUBLISHED.value
        self.published_at = now
        self.last_error = None

    def mark_failed(self, error: str, max_attempts: int, now: datetime) -> None:
        """Exponential backoff (2^n s, max 300 s); dead-letters after ``max_attempts``."""
        self.attempts += 1
        self.last_error = error
        if self.attempts >= max_attempts:
            self.status = OutboxStatus.DLQ.value
        else:
            self.status = OutboxStatus.PENDING.value
            self.next_retry_at = now + timedelta(seconds=min(300, 2 ** min(8, self.attempts)))
