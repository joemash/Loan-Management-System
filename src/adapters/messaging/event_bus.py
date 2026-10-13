"""In-process domain event bus.

Handlers run synchronously after the originating unit of work has committed. A failing handler is logged
and does not affect other handlers or the caller.
"""

import logging
from collections import defaultdict
from collections.abc import Callable

from src.application.domain.events import DomainEvent
from src.application.ports.services import IEventPublisher

log = logging.getLogger(__name__)

Handler = Callable[[DomainEvent], None]


class InProcessEventBus(IEventPublisher):
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        for event_type, handlers in list(self._handlers.items()):
            if isinstance(event, event_type):
                for handler in list(handlers):
                    try:
                        handler(event)
                    except Exception:
                        log.exception("Domain event handler failed for %r", event)
