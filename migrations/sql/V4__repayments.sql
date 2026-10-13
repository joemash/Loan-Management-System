-- Repayments — see docs/SCHEMA.md § repayment_schedules, payments
CREATE TABLE repayment_schedules (
    id UUID PRIMARY KEY,
    loan_id UUID NOT NULL REFERENCES loans(id),

    due_date DATE NOT NULL,
    amount_due NUMERIC(18,2) NOT NULL,
    amount_paid NUMERIC(18,2) DEFAULT 0,

    status TEXT NOT NULL,

    created_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_schedule_due_date ON repayment_schedules(due_date);

CREATE TABLE payments (
    id UUID PRIMARY KEY,
    loan_id UUID NOT NULL REFERENCES loans(id),

    amount NUMERIC(18,2) NOT NULL,
    payment_date TIMESTAMP NOT NULL,

    external_reference TEXT UNIQUE,

    created_at TIMESTAMP NOT NULL
);
