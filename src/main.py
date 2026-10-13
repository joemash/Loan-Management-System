"""FastAPI application factory: builds the container, registers driving adapters."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from injector import Injector

from src.adapters.observability.metrics import HttpMetricsMiddleware, register_notification_gauges
from src.adapters.web.errors import register_exception_handlers
from src.adapters.web.routes import admin, customers, loans, system
from src.application.ports.services import IClock
from src.application.ports.usecases import INotificationUseCases
from src.infrastructure.config.settings import Settings, get_settings
from src.infrastructure.container import build_injector


def create_app(
    settings: Settings | None = None,
    *,
    start_background: bool = True,
    injector: Injector | None = None,
    clock: IClock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    injector = injector or build_injector(settings, clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler = consumer = None
        if start_background:
            from src.adapters.scheduling.scheduler import build_scheduler

            scheduler = build_scheduler(injector, settings)
            scheduler.start()
            if settings.notifications_kafka_enabled:
                from src.adapters.messaging.kafka import KafkaNotificationConsumer

                consumer = KafkaNotificationConsumer(
                    settings.notifications_kafka_bootstrap_servers,
                    settings.notifications_kafka_topic,
                    settings.notifications_kafka_group_id,
                    lambda: injector.get(INotificationUseCases),
                )
                consumer.start()
        try:
            yield
        finally:
            if consumer:
                consumer.stop()
            if scheduler:
                scheduler.shutdown(wait=False)

    app = FastAPI(
        title="LMS API",
        description="Loan management APIs for admin operations and loan lifecycle flows.",
        version="v1",
        contact={"name": "Ezra LMS Team"},
        openapi_url="/api-docs",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.injector = injector
    register_exception_handlers(app)
    app.add_middleware(HttpMetricsMiddleware)
    app.include_router(loans.router)
    app.include_router(customers.router)
    app.include_router(admin.router)
    system.register_docs(app)
    system.register_actuator(app)
    register_notification_gauges(lambda: injector.get(INotificationUseCases))
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory src.main:app_factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    return create_app()
