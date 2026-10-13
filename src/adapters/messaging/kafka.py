"""Kafka adapters: a driven producer and a driving consumer (Java ``NotificationKafkaConfig``,
``NotificationOutboxPublisher`` transport and ``NotificationConsumer``)."""

import json
import logging
import threading
from collections.abc import Callable

from src.application.domain.notification import NotificationEventMessage
from src.application.ports.services import INotificationProducer
from src.application.ports.usecases import INotificationUseCases

log = logging.getLogger(__name__)


class KafkaNotificationProducer(INotificationProducer):
    """Synchronous send: waits for broker acknowledgement so failures reach the outbox retry logic."""

    def __init__(self, bootstrap_servers: str, timeout_seconds: float = 10.0):
        from confluent_kafka import Producer

        self._producer = Producer({"bootstrap.servers": bootstrap_servers, "enable.idempotence": True})
        self._timeout = timeout_seconds

    def send(self, topic: str, key: str, message: NotificationEventMessage) -> None:
        errors: list[Exception] = []

        def on_delivery(err, _msg):
            if err is not None:
                errors.append(RuntimeError(str(err)))

        self._producer.produce(
            topic, key=key, value=json.dumps(message.to_dict()).encode(), on_delivery=on_delivery
        )
        if self._producer.flush(self._timeout) > 0:
            raise TimeoutError("Timed out waiting for Kafka delivery")
        if errors:
            raise errors[0]


class DisabledNotificationProducer(INotificationProducer):
    """Used when Kafka is disabled: outbox rows simply stay ``PENDING``."""

    def send(self, topic: str, key: str, message: NotificationEventMessage) -> None:
        raise RuntimeError("Kafka notifications are disabled")


class KafkaNotificationConsumer:
    """Polls the topic in a daemon thread and hands each message to the notification use cases."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        usecases_factory: Callable[[], INotificationUseCases],
    ):
        self._config = {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
        }
        self._topic = topic
        self._usecases_factory = usecases_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="notification-consumer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        from confluent_kafka import Consumer

        consumer = Consumer(self._config)
        consumer.subscribe([self._topic])
        try:
            while not self._stop.is_set():
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    log.warning("Kafka consumer error: %s", msg.error())
                    continue
                try:
                    message = NotificationEventMessage.from_dict(json.loads(msg.value()))
                    self._usecases_factory().handle_delivery(message)
                except Exception:
                    log.exception("Notification consumption failed")
        finally:
            consumer.close()
