"""Composition root: binds ports to adapters (``configure(binder)``).

Use cases and the unit of work are *not* singletons: every ``injector.get(ILoanUseCases)`` builds a fresh
use case with its own unit of work, so concurrent requests, scheduled jobs and the Kafka consumer never
share a session. Stateless infrastructure (engine, session factory, clock, bus, producer) is shared.
"""

from injector import Binder, Injector, Module, provider, singleton
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from src.adapters.messaging.channel import StubLogChannel
from src.adapters.messaging.event_bus import InProcessEventBus
from src.adapters.messaging.kafka import DisabledNotificationProducer, KafkaNotificationProducer
from src.adapters.observability.metrics import PrometheusNotificationMetrics
from src.adapters.repositories.database import create_db_engine, create_session_factory
from src.adapters.repositories.uow_impl import SqlAlchemyUnitOfWork
from src.adapters.web.security import JwtTokenService
from src.application.config import LoanPolicy, NotificationPolicy
from src.application.domain.events import (
    LoanDisbursedEvent,
    LoanOverdueEvent,
    PaymentDueEvent,
    PaymentReceivedEvent,
)
from src.application.domain.schedule import RoutingScheduleGenerator
from src.application.ports.services import (
    IClock,
    IEventPublisher,
    INotificationChannel,
    INotificationMetrics,
    INotificationProducer,
)
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import (
    ICustomerUseCases,
    ILoanMaintenanceUseCases,
    ILoanProductUseCases,
    ILoanUseCases,
    INotificationUseCases,
)
from src.application.usecases.customers import CustomerUseCases
from src.application.usecases.loan_products import LoanProductUseCases
from src.application.usecases.loans import LoanUseCases
from src.application.usecases.maintenance import LoanMaintenanceUseCases
from src.application.usecases.notifications import NotificationUseCases
from src.infrastructure.clock import SystemClock
from src.infrastructure.config.settings import Settings


class AppModule(Module):
    def __init__(self, settings: Settings, clock: IClock | None = None):
        self.settings = settings
        self.clock = clock or SystemClock()

    def configure(self, binder: Binder) -> None:
        binder.bind(Settings, to=self.settings)
        binder.bind(IClock, to=self.clock)
        binder.bind(IUnitOfWork, to=SqlAlchemyUnitOfWork)
        binder.bind(ICustomerUseCases, to=CustomerUseCases)
        binder.bind(ILoanProductUseCases, to=LoanProductUseCases)
        binder.bind(ILoanUseCases, to=LoanUseCases)
        binder.bind(ILoanMaintenanceUseCases, to=LoanMaintenanceUseCases)
        binder.bind(INotificationUseCases, to=NotificationUseCases)
        binder.bind(INotificationChannel, to=StubLogChannel, scope=singleton)
        binder.bind(INotificationMetrics, to=PrometheusNotificationMetrics, scope=singleton)
        binder.bind(RoutingScheduleGenerator, to=RoutingScheduleGenerator, scope=singleton)

    @singleton
    @provider
    def engine(self) -> Engine:
        return create_db_engine(self.settings.database_url, echo=self.settings.database_echo)

    @singleton
    @provider
    def session_factory(self, engine: Engine) -> sessionmaker:
        return create_session_factory(engine)

    @singleton
    @provider
    def event_bus(self) -> InProcessEventBus:
        return InProcessEventBus()

    @singleton
    @provider
    def event_publisher(self, bus: InProcessEventBus) -> IEventPublisher:
        return bus

    @singleton
    @provider
    def producer(self) -> INotificationProducer:
        if not self.settings.notifications_kafka_enabled:
            return DisabledNotificationProducer()
        return KafkaNotificationProducer(self.settings.notifications_kafka_bootstrap_servers)

    @singleton
    @provider
    def loan_policy(self) -> LoanPolicy:
        return LoanPolicy(
            daily_penalty_rate=self.settings.penalty_daily_rate,
            default_after_days_past_due=self.settings.loan_default_after_days_past_due,
            reminder_days_before_due=self.settings.reminder_days_before_due,
        )

    @singleton
    @provider
    def notification_policy(self) -> NotificationPolicy:
        return NotificationPolicy(
            topic=self.settings.notifications_kafka_topic,
            max_attempts=self.settings.notifications_retry_max_attempts,
        )

    @singleton
    @provider
    def token_service(self) -> JwtTokenService:
        return JwtTokenService.from_settings(self.settings)


def subscribe_event_handlers(injector: Injector) -> None:
    """Domain events → notification recording. Each handler resolves fresh use cases (own transaction)."""
    bus = injector.get(InProcessEventBus)

    def notifications() -> INotificationUseCases:
        return injector.get(INotificationUseCases)

    bus.subscribe(LoanDisbursedEvent, lambda e: notifications().record_loan_disbursed(e))
    bus.subscribe(PaymentReceivedEvent, lambda e: notifications().record_payment_received(e))
    bus.subscribe(LoanOverdueEvent, lambda e: notifications().record_loan_overdue(e))
    bus.subscribe(PaymentDueEvent, lambda e: notifications().record_payment_due(e))


def build_injector(settings: Settings, clock: IClock | None = None) -> Injector:
    injector = Injector([AppModule(settings, clock)])
    subscribe_event_handlers(injector)
    return injector
