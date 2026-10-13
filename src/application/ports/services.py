"""Driven ports for infrastructure services used by the use cases."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from src.application.domain.events import DomainEvent
from src.application.domain.notification import NotificationEventMessage


class IClock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current instant as naive UTC."""
        raise NotImplementedError

    @abstractmethod
    def today(self) -> date:
        """Business date (local system date)."""
        raise NotImplementedError


class IEventPublisher(ABC):
    @abstractmethod
    def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError


class INotificationProducer(ABC):
    """Sends a notification message to the broker; raises if delivery is not acknowledged."""

    @abstractmethod
    def send(self, topic: str, key: str, message: NotificationEventMessage) -> None:
        raise NotImplementedError


class INotificationChannel(ABC):
    """Delivers a notification to the customer (email, SMS, …)."""

    @abstractmethod
    def dispatch(self, message: NotificationEventMessage) -> None:
        raise NotImplementedError


class INotificationMetrics(ABC):
    @abstractmethod
    def outbox_published(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def outbox_failed(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def consumed(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def consume_failed(self) -> None:
        raise NotImplementedError
