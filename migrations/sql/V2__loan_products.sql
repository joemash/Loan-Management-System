-- Loan product module — see docs/SCHEMA.md § loan_products
CREATE TABLE loan_products (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,

    min_amount NUMERIC(18,2),
    max_amount NUMERIC(18,2),

    min_tenure_days INT,
    max_tenure_days INT,

    interest_strategy TEXT NOT NULL,
    repayment_strategy TEXT NOT NULL,
    fee_strategy TEXT,

    config JSONB,

    created_at TIMESTAMP NOT NULL
);
