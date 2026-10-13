"""Event bus, Kafka producer adapter and broker message (de)serialisation."""

import json
import uuid
from datetime import date, datetime

import pytest

from src.adapters.messaging import kafka
from src.adapters.messaging.channel import StubLogChannel
from src.adapters.messaging.event_bus import InProcessEventBus
from src.application.domain.events import DomainEvent, LoanOverdueEvent, PaymentDueEvent
from src.application.domain.notification import NotificationEventMessage

NOW = datetime(2026, 1, 1, 9, 0)


def _overdue() -> LoanOverdueEvent:
    return LoanOverdueEvent(loan_id=uuid.uuid4(), customer_id=uuid.uuid4(), occurred_at=NOW)


# --- event bus ---


def test_bus_dispatches_by_type_including_base_class_subscribers():
    bus = InProcessEventBus()
    overdue, everything = [], []
    bus.subscribe(LoanOverdueEvent, overdue.append)
    bus.subscribe(DomainEvent, everything.append)

    event = _overdue()
    bus.publish(event)
    bus.publish(
        PaymentDueEvent(
            loan_id=uuid.uuid4(), customer_id=uuid.uuid4(), due_date=date.today(), occurred_at=NOW
        )
    )

    assert overdue == [event]
    assert len(everything) == 2


def test_bus_isolates_failing_handlers():
    bus = InProcessEventBus()
    received = []

    def boom(_):
        raise RuntimeError("handler failed")

    bus.subscribe(LoanOverdueEvent, boom)
    bus.subscribe(LoanOverdueEvent, received.append)
    bus.publish(_overdue())

    assert len(received) == 1


# --- broker message ---


def test_message_round_trips_through_json():
    message = NotificationEventMessage(eventId="e", notificationId="n", payload={"loanId": "l"})
    wire = json.dumps(message.to_dict())
    assert json.loads(wire) == {
        "eventId": "e",
        "notificationId": "n",
        "customerId": None,
        "type": None,
        "channel": None,
        "payload": {"loanId": "l"},
    }
    assert NotificationEventMessage.from_dict({**json.loads(wire), "extra": 1}) == message


def test_disabled_producer_raises():
    with pytest.raises(RuntimeError, match="disabled"):
        kafka.DisabledNotificationProducer().send(
            "t", "k", NotificationEventMessage(eventId="e", notificationId="n")
        )


def test_stub_channel_logs(caplog):
    caplog.set_level("INFO")
    StubLogChannel().dispatch(NotificationEventMessage(eventId="evt-1", notificationId="n"))
    assert "evt-1" in caplog.text


# --- kafka producer adapter (confluent_kafka replaced by a stub) ---


class _StubProducer:
    def __init__(self, config, error=None, undelivered=0):
        self.config, self.error, self.undelivered = config, error, undelivered
        self.produced = []

    def produce(self, topic, key, value, on_delivery):
        self.produced.append((topic, key, value))
        on_delivery(self.error, None)

    def flush(self, timeout):
        return self.undelivered


@pytest.fixture
def stub_producer(monkeypatch):
    holder = {}

    def factory(**behaviour):
        def make(config):
            holder["producer"] = _StubProducer(config, **behaviour)
            return holder["producer"]

        import confluent_kafka

        monkeypatch.setattr(confluent_kafka, "Producer", make)
        return holder

    return factory


def test_kafka_producer_sends_json_with_idempotence(stub_producer):
    holder = stub_producer()
    producer = kafka.KafkaNotificationProducer("broker:9092")

    producer.send("topic", "key", NotificationEventMessage(eventId="e", notificationId="n"))

    stub = holder["producer"]
    assert stub.config == {"bootstrap.servers": "broker:9092", "enable.idempotence": True}
    ((topic, key, value),) = stub.produced
    assert (topic, key, json.loads(value)["eventId"]) == ("topic", "key", "e")


def test_kafka_producer_raises_on_delivery_error(stub_producer):
    stub_producer(error="broker said no")
    with pytest.raises(RuntimeError, match="broker said no"):
        kafka.KafkaNotificationProducer("b").send(
            "t", "k", NotificationEventMessage(eventId="e", notificationId="n")
        )


def test_kafka_producer_raises_on_flush_timeout(stub_producer):
    stub_producer(undelivered=1)
    with pytest.raises(TimeoutError):
        kafka.KafkaNotificationProducer("b").send(
            "t", "k", NotificationEventMessage(eventId="e", notificationId="n")
        )
