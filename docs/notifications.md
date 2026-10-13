# Notifications

This document describes the notification capability used by the LMS backend. Notifications are not a standalone module, but a cross-cutting flow triggered by loan domain events and delivered asynchronously.

---

## Purpose

- Persist notification intent for audit and operator visibility.
- Decouple loan lifecycle APIs from delivery side effects.
- Queue delivery through Kafka so processing can retry safely.
- Expose notification tracking in admin APIs and frontend UI.

---

## Event sources

Notifications are currently triggered from loan-related domain events:

- `LOAN_DISBURSED`
- `PAYMENT_RECEIVED`
- `LOAN_OVERDUE`
- `PAYMENT_DUE`

Events raised by aggregates are published by the unit of work (`IUnitOfWork`) only after its transaction commits, through the in-process bus (`src.adapters.messaging.event_bus`). `src.infrastructure.container.subscribe_event_handlers` routes them to `INotificationUseCases.record_*`; each handler resolves a fresh use case, so it writes in its own transaction (REQUIRES_NEW equivalent).

---

## Delivery architecture

1. Domain event is handled by `NotificationUseCases.record_*` (`src/application/usecases/notifications.py`).
2. A `notifications` row is created with `delivery_status=PENDING` and `ui_status=UNREAD`.
3. A matching `notification_outbox` row is created in the same flow.
4. `NotificationUseCases.publish_pending` (driven by the APScheduler adapter, every `NOTIFICATIONS_OUTBOX_POLL_DELAY_MS`) polls pending outbox rows and sends them through the `INotificationProducer` port (Kafka adapter) to topic `notifications.events`.
5. `KafkaNotificationConsumer` (driving adapter, daemon thread) receives messages and calls `NotificationUseCases.handle_delivery`, which dispatches through the `INotificationChannel` port (`StubLogChannel`).
6. Delivery status is updated (`SENT` on success, failed/retry metadata on errors).

Current channel dispatch is `STUB_LOG` for local/dev behavior; email/SMS adapters can be added behind the dispatcher.

---

## Data model

### `notifications`

Key fields:

- identity: `id`, `event_id`, `customer_id`, `type`, `channel`
- content: `payload` (JSONB)
- delivery lifecycle: `delivery_status`, `attempt_count`, `last_error`, `next_retry_at`, `sent_at`
- UI lifecycle: `ui_status`, `read_at`
- audit timestamps: `created_at`, `updated_at`

### `notification_outbox`

Key fields:

- identity: `id`, `event_id`, `notification_id`
- publish metadata: `topic`, `event_key`, `payload`
- processing lifecycle: `status`, `attempts`, `last_error`, `next_retry_at`, `published_at`
- audit timestamp: `created_at`

Schema migration: `migrations/sql/V10__notification_delivery_lifecycle_and_outbox.sql` (Alembic revision `v10`).

---

## Statuses

### Delivery status

- `PENDING`: persisted, waiting for queue/consumer processing
- `SENT`: successfully processed by consumer/dispatcher
- `FAILED`: processing failed
- `RETRYING`: reserved for retry transitions
- `DLQ`: exceeded retry policy

### UI status

- `UNREAD`
- `READ`

---

## Admin/API and UI tracking

Backend endpoints:

- `GET /admin/notifications`
- `GET /admin/notifications/{id}`
- `POST /admin/notifications/{id}/read`

Frontend screens:

- `/notifications` (list, filters, pagination)
- `/notifications/:id` (detail, mark as read)

---

## Operations and observability

- Kafka broker expected at `NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS` (local default `localhost:9092`); set `NOTIFICATIONS_KAFKA_ENABLED=false` to disable relay and consumer.
- Outbox publisher poll delay and retry max attempts are configurable via `NOTIFICATIONS_OUTBOX_POLL_DELAY_MS` and `NOTIFICATIONS_RETRY_MAX_ATTEMPTS`.
- Metrics include counters/gauges for published, failed, consumed, unread, and failed notification counts.

See `docs/observability/README.md` for local stack and metrics usage.
