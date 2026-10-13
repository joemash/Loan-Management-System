-- Loan module — see docs/SCHEMA.md § loans
CREATE TABLE loans (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customers(id),
    product_id UUID NOT NULL REFERENCES loan_products(id),

    principal NUMERIC(18,2) NOT NULL,
    total_amount NUMERIC(18,2),

    status TEXT NOT NULL,

    disbursement_date DATE,

    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
