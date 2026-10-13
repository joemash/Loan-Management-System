-- Customer module — see docs/SCHEMA.md § customers
CREATE TABLE customers (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,

    credit_limit NUMERIC(18,2) NOT NULL,
    available_credit NUMERIC(18,2) NOT NULL,

    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
