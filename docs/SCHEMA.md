# Database Schema — Lending Platform

## Overview

This document defines the database schema for the lending platform. The design prioritises:

* **Financial correctness** — accurate handling of money
* **Auditability** — full traceability of transactions
* **Extensibility** — ability to evolve without major schema changes
* **Separation of concerns** — clear boundaries between domain concepts

---

## Design Principles

1. **Use NUMERIC for monetary values**
   All monetary fields use `NUMERIC(18,2)` to avoid floating-point precision issues.

2. **Append-only ledger**
   Financial transactions are recorded in an immutable ledger.

3. **Separate expected vs actual payments**
   Repayment schedules (expected) are distinct from payments (actual).

4. **Idempotency for external operations**
   Payments include unique external references to prevent duplication.

5. **Flexible configuration**
   JSONB fields allow evolving product configurations without schema churn.

---

## Tables

---

### 1. customers

Stores customer profile and credit information.

```sql
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
```

---

### 2. loan_products

Defines configurable loan products and rules.

```sql
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
```

Additional constraints (migration `V11__loan_product_constraints.sql`):

```sql
CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount)
CHECK (min_tenure_days IS NULL OR max_tenure_days IS NULL OR min_tenure_days <= max_tenure_days)
CHECK (UPPER(interest_strategy) IN ('NONE', 'SIMPLE_APR'))
CHECK (UPPER(repayment_strategy) IN ('EQUAL_INSTALLMENTS', 'EQUAL_PRINCIPAL_INSTALLMENTS'))
CHECK (fee_strategy IS NULL OR UPPER(fee_strategy) IN ('NONE', 'FLAT_ORIGINATION'))
```

---

### 3. loans

Represents a loan issued to a customer.

```sql
CREATE TABLE loans (
    id UUID PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customers(id),
    product_id UUID NOT NULL REFERENCES loan_products(id),

    principal NUMERIC(18,2) NOT NULL,
    total_amount NUMERIC(18,2),

    status TEXT NOT NULL,

    disbursement_date DATE,

    version BIGINT NOT NULL DEFAULT 0,

    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

`version` supports optimistic locking (SQLAlchemy `version_id_col`; stale writes return HTTP 409).

---

### 4. repayment_schedules

Represents expected repayments over time.

```sql
CREATE TABLE repayment_schedules (
    id UUID PRIMARY KEY,
    loan_id UUID NOT NULL REFERENCES loans(id),

    due_date DATE NOT NULL,
    amount_due NUMERIC(18,2) NOT NULL,
    amount_paid NUMERIC(18,2) DEFAULT 0,

    penalty_accrued NUMERIC(18,2) NOT NULL DEFAULT 0,
    penalty_last_accrual_date DATE,

    status TEXT NOT NULL,

    created_at TIMESTAMP NOT NULL
);
```

`penalty_last_accrual_date` idempotently marks the last calendar day penalty was applied for that schedule.

#### Index

```sql
CREATE INDEX idx_schedule_due_date ON repayment_schedules(due_date);
```

---

### 5. payments

Represents actual payments made by customers. **Not** modeled as part of the `loans` aggregate in the application: the `payments` table references `loans(id)` by FK, but the **`Payment`** model holds **`loan_id`** only (no navigable association from payment to loan on the domain model). Schedules = expected; payments = actual.

```sql
CREATE TABLE payments (
    id UUID PRIMARY KEY,
    loan_id UUID NOT NULL REFERENCES loans(id),

    amount NUMERIC(18,2) NOT NULL,
    payment_date TIMESTAMP NOT NULL,

    external_reference TEXT UNIQUE,

    created_at TIMESTAMP NOT NULL
);
```

---

### 6. ledger_accounts

Represents accounts used in financial transactions.

```sql
CREATE TABLE ledger_accounts (
    id UUID PRIMARY KEY,
    account_type TEXT NOT NULL,
    reference_id UUID,

    created_at TIMESTAMP NOT NULL
);
```

#### Account Types

* CUSTOMER
* LOAN
* PLATFORM

---

### 7. ledger_entries

Stores all financial transactions using double-entry accounting.

```sql
CREATE TABLE ledger_entries (
    id UUID PRIMARY KEY,

    debit_account_id UUID NOT NULL REFERENCES ledger_accounts(id),
    credit_account_id UUID NOT NULL REFERENCES ledger_accounts(id),

    amount NUMERIC(18,2) NOT NULL,

    reference_type TEXT,
    reference_id UUID,

    created_at TIMESTAMP NOT NULL
);
```

#### Index

```sql
CREATE INDEX idx_ledger_reference ON ledger_entries(reference_id);
```

---

### 8. notifications (optional)

Stub table for tracking notifications.

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY,
    customer_id UUID,
    type TEXT,
    channel TEXT,
    payload JSONB,
    status TEXT,
    created_at TIMESTAMP NOT NULL
);
```

---

### 9. audit_log (optional)

Tracks changes across the system.

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    entity_type TEXT,
    entity_id UUID,
    action TEXT,
    payload JSONB,
    created_at TIMESTAMP NOT NULL
);
```

---

## Relationships

```text
Customer → Loans → RepaymentSchedules
                     ↓
                  Payments

Loan ↔ LedgerAccounts
Payments → LedgerEntries
```

---

## Key Design Decisions

### 1. Ledger-Based Accounting

All financial movements are recorded using double-entry ledger entries to ensure:

* Auditability
* Traceability
* Financial correctness

---

### 2. Separation of Schedules and Payments

* Schedules represent expected repayments
* Payments represent actual money received

This enables:

* Partial payments
* Accurate overdue tracking

---

### 3. Idempotent Payments

The `external_reference` field ensures that duplicate payment requests do not result in duplicate records.

---

### 4. JSONB for Product Configuration

Loan products use JSONB for flexible configuration, allowing:

* Rapid iteration
* Reduced schema changes

---

### 5. Stored Derived Values

Fields like `available_credit` are stored for performance but can be reconciled from underlying data.

---

## Future Enhancements

* Introduce `loan_events` table for event sourcing
* Add currency support for multi-currency systems
* Partition ledger tables for scalability
* Add stricter constraints and validation rules

---

## Summary

This schema is designed to:

* Safely handle financial transactions
* Support evolving business requirements
* Provide a strong foundation for scaling the platform

It balances simplicity for initial development with the structure needed for long-term growth.
