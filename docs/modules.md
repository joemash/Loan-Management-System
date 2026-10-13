# Domain modules

Business rules live in `src/application/domain/` (one module per concept) and are orchestrated by the use
cases in `src/application/usecases/`; see [architecture.md](architecture.md) for the layering. Aggregates
reference each other **by id**, never through cross-aggregate ORM relationships, so any one of them could
be extracted into a service later.

## Loan (`domain/loan.py`, `usecases/loans.py`)

The `Loan` aggregate owns its `RepaymentSchedule` rows (`cascade="all, delete-orphan"`) but **not**
payments. State changes only happen through aggregate methods:

| Method | Transition / effect |
|--------|---------------------|
| `Loan.apply(customer_id, product_id, principal)` | new loan in `CREATED` |
| `approve()` | `CREATED → APPROVED`, otherwise `DomainStateError` |
| `disburse(date, total, schedules)` | `APPROVED → DISBURSED`; no-op if already disbursed; schedule amounts must sum to `total`; raises `LoanDisbursedEvent` |
| `apply_repayment(amount)` | FIFO by due date across unpaid rows; rejects overpayment; closes the loan when fully paid |
| `check_overdue(today)` | marks past-due rows `OVERDUE`; raises `LoanOverdueEvent` when any row newly transitions |
| `apply_default_policy(today, days)` | `DISBURSED → DEFAULTED` when an overdue row is `days` past due |
| `pull_events()` | drains pending domain events (called by the after-commit hook) |

Use cases in `LoanUseCases`:

- `apply`: validates customer status, product strategies/config, amount bounds, and principal ≤ available credit.
- `disburse`: generates the plan from the product, validates tenure, **reserves the full contractual
  total** on the customer's credit line, posts the ledger entry (principal), and publishes events after commit.
- `repay`: idempotent on `external_reference`. Persists the payment, allocates it, posts the ledger
  entry, releases credit on closure, and writes an audit row.
- `summary`: principal, paid, remaining, overdue, penalties.

Jobs in `LoanMaintenanceUseCases` (`usecases/maintenance.py`, triggered by `adapters/scheduling`):

- `process_overdues_and_penalties`: overdue marking → daily penalty accrual → default policy.
  Defaults: 01:00 daily, `PENALTY_DAILY_RATE=0.001`, `LOAN_DEFAULT_AFTER_DAYS_PAST_DUE=90`.
- `publish_due_reminders`: emits `PaymentDueEvent` for rows due in exactly `REMINDER_DAYS_BEFORE_DUE`
  days. Defaults: 08:00 daily, 3 days.

## Loan product (`domain/loan_product*.py`, `domain/pricing.py`)

- Strategy whitelists: interest `NONE | SIMPLE_APR`; repayment `EQUAL_INSTALLMENTS | EQUAL_PRINCIPAL_INSTALLMENTS`;
  fee `NONE | FLAT_ORIGINATION` (defaults to `NONE`). Input is case-insensitive and stored upper-case.
- `config` keys: `installments` (≥1, default 1), `installment_period_months` (≥1, default 1),
  `apr` ∈ [0, 1] (required for `SIMPLE_APR`), `origination_fee` ≥ 0 (required for `FLAT_ORIGINATION`).
  Unknown keys are rejected. A PATCH with `config` replaces the whole object.
- Finance charge: `principal × apr × installments / 12`, rounded half-up to cents.

## Repayment (`domain/repayment.py`, `domain/schedule.py`)

- `RepaymentSchedule` holds expected amounts; `Payment` holds actual cash received. Only `apply_payment`
  changes `amount_paid`, and it sets `PAID` once the row is settled.
- `EqualInstallmentsScheduleGenerator`: total = principal + finance charge + fees, split evenly with the
  last row absorbing rounding. Due dates step by `installment_period_months` with month-end clamping.
  `EQUAL_PRINCIPAL_INSTALLMENTS` currently routes to the same generator (as in the Java source).
- `apply_penalties`: `remaining_due × daily_rate`, at most once per row per business date.

## Ledger (`domain/ledger.py`)

Append-only double entry, with accounts created lazily per `(account_type, reference_id)`:

| Event | Debit | Credit | Amount |
|-------|-------|--------|--------|
| Disbursement | `LOAN` | `CUSTOMER` | principal |
| Repayment | `CUSTOMER` | `LOAN` | payment amount |

Payment insert, allocation, ledger write and loan update commit or roll back together. Concurrent
first-time requests with the same `external_reference` are serialised by the `UNIQUE` constraint
(the loser gets 409).

## Customer (`domain/customer.py`, `usecases/customers.py`)

`available_credit` starts equal to `credit_limit`. Changing the limit shifts available credit by the same
delta; the request is rejected if that would go negative, and the result is capped at the new limit.

## Notification and audit

See [notifications.md](notifications.md). `AuditLog.record` (`domain/audit.py`) is persisted via `uow.audit` (currently on
repayment).
