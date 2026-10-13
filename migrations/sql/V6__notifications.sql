-- Notification module — see docs/SCHEMA.md § notifications (optional stub)
CREATE TABLE notifications (
    id UUID PRIMARY KEY,
    customer_id UUID,
    type TEXT,
    channel TEXT,
    payload JSONB,
    status TEXT,
    created_at TIMESTAMP NOT NULL
);
