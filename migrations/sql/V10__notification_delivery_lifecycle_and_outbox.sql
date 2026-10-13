ALTER TABLE notifications
    ADD COLUMN delivery_status TEXT,
    ADD COLUMN ui_status TEXT NOT NULL DEFAULT 'UNREAD',
    ADD COLUMN event_id UUID,
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN last_error TEXT,
    ADD COLUMN next_retry_at TIMESTAMP,
    ADD COLUMN sent_at TIMESTAMP,
    ADD COLUMN read_at TIMESTAMP,
    ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT NOW();

UPDATE notifications
SET delivery_status = COALESCE(delivery_status, status, 'SENT'),
    updated_at = COALESCE(created_at, NOW())
WHERE delivery_status IS NULL;

CREATE INDEX idx_notifications_customer_id ON notifications(customer_id);
CREATE INDEX idx_notifications_delivery_status ON notifications(delivery_status);
CREATE INDEX idx_notifications_ui_status ON notifications(ui_status);
CREATE INDEX idx_notifications_created_at ON notifications(created_at DESC);
CREATE UNIQUE INDEX uk_notifications_event_id ON notifications(event_id) WHERE event_id IS NOT NULL;

CREATE TABLE notification_outbox (
    id UUID PRIMARY KEY,
    event_id UUID NOT NULL,
    notification_id UUID NOT NULL,
    topic TEXT NOT NULL,
    event_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_retry_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    published_at TIMESTAMP
);

CREATE INDEX idx_notification_outbox_status_next_retry ON notification_outbox(status, next_retry_at);
CREATE UNIQUE INDEX uk_notification_outbox_event_id ON notification_outbox(event_id);
