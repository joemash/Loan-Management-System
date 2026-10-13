import logging

from src.application.domain.notification import NotificationEventMessage
from src.application.ports.services import INotificationChannel

log = logging.getLogger(__name__)


class StubLogChannel(INotificationChannel):
    """``STUB_LOG`` channel: logs instead of sending. Swap for an email/SMS adapter behind the same port."""

    def dispatch(self, message: NotificationEventMessage) -> None:
        log.info("[notification dispatch] eventId=%s payload=%s", message.eventId, message.payload)
