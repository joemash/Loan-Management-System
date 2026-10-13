"""Prometheus adapter for the metrics port, plus scrape-time gauges and HTTP latency middleware."""

import time
from collections.abc import Callable

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.application.ports.services import INotificationMetrics
from src.application.ports.usecases import INotificationUseCases

HTTP_REQUESTS = Histogram(
    "http_server_requests_seconds", "HTTP server request latency", ["method", "uri", "status"]
)

OUTBOX_PUBLISHED = Counter("lms_notifications_outbox_published", "Outbox rows published to Kafka")
OUTBOX_FAILED = Counter("lms_notifications_outbox_failed", "Outbox publish failures")
CONSUMED = Counter("lms_notifications_consumed", "Notification events consumed and dispatched")
CONSUME_FAILED = Counter("lms_notifications_consume_failed", "Notification dispatch failures")

FAILED_COUNT = Gauge("lms_notifications_failed_count", "Notifications with delivery_status=FAILED")
UNREAD_COUNT = Gauge("lms_notifications_unread_count", "Notifications with ui_status=UNREAD")
OUTBOX_PENDING_COUNT = Gauge(
    "lms_notifications_outbox_pending_count", "Outbox rows due for publishing (max 100)"
)


class PrometheusNotificationMetrics(INotificationMetrics):
    def outbox_published(self) -> None:
        OUTBOX_PUBLISHED.inc()

    def outbox_failed(self) -> None:
        OUTBOX_FAILED.inc()

    def consumed(self) -> None:
        CONSUMED.inc()

    def consume_failed(self) -> None:
        CONSUME_FAILED.inc()


def register_notification_gauges(usecases_factory: Callable[[], INotificationUseCases]) -> None:
    """Gauges query current counts through the use cases on each scrape."""
    FAILED_COUNT.set_function(lambda: usecases_factory().stats()["failed"])
    UNREAD_COUNT.set_function(lambda: usecases_factory().stats()["unread"])
    OUTBOX_PENDING_COUNT.set_function(lambda: usecases_factory().stats()["outbox_due"])


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        uri = getattr(request.scope.get("route"), "path", "UNKNOWN")
        HTTP_REQUESTS.labels(request.method, uri, str(response.status_code)).observe(
            time.perf_counter() - start
        )
        return response
