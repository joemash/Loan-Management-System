-- Demo seed data for local development (see README). Safe to re-run only on empty DB; Flyway runs once per version.
INSERT INTO customers (id, name, email, status, credit_limit, available_credit, created_at, updated_at)
VALUES (
    'a0000000-0000-4000-8000-000000000001',
    'Demo Customer',
    'demo@example.com',
    'ACTIVE',
    50000.00,
    50000.00,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);

INSERT INTO loan_products (
    id,
    name,
    min_amount,
    max_amount,
    min_tenure_days,
    max_tenure_days,
    interest_strategy,
    repayment_strategy,
    fee_strategy,
    config,
    created_at
)
VALUES (
    'b0000000-0000-4000-8000-000000000001',
    'Demo 12-month installment loan',
    100.00,
    25000.00,
    30,
    1825,
    'NONE',
    'EQUAL_INSTALLMENTS',
    'NONE',
    '{"installments": 12}'::jsonb,
    CURRENT_TIMESTAMP
);
