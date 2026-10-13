-- Ledger module — see docs/SCHEMA.md § ledger_accounts, ledger_entries
CREATE TABLE ledger_accounts (
    id UUID PRIMARY KEY,
    account_type TEXT NOT NULL,
    reference_id UUID,

    created_at TIMESTAMP NOT NULL
);

CREATE TABLE ledger_entries (
    id UUID PRIMARY KEY,

    debit_account_id UUID NOT NULL REFERENCES ledger_accounts(id),
    credit_account_id UUID NOT NULL REFERENCES ledger_accounts(id),

    amount NUMERIC(18,2) NOT NULL,

    reference_type TEXT,
    reference_id UUID,

    created_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_ledger_reference ON ledger_entries(reference_id);
