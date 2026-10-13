-- Audit — see docs/SCHEMA.md § audit_log (optional)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    entity_type TEXT,
    entity_id UUID,
    action TEXT,
    payload JSONB,
    created_at TIMESTAMP NOT NULL
);
