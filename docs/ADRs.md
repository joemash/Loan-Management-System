# Architectural Decision Records (ADRs)

This document captures key architectural decisions made during the design of this system, along with their context and trade-offs.

---

### ADR-001: Modular Monolith Architecture

**Status:** Accepted

**Context:**
The system is expected to evolve over 12-18 months with multiple teams contributing. Early-stage systems often suffer from premature microservice adoption, leading to operational complexity.

**Decision:**
Adopt a **modular monolith architecture**, with clear domain boundaries (Customer, Loan, Ledger, etc.).

**Consequences:**

* Faster development and iteration
* Lower operational overhead
* Easier refactoring in early stages
* Requires discipline to maintain module boundaries

**Future Evolution:**
Modules can be extracted into microservices (e.g., Ledger, Notifications) when scaling demands it.

---

### ADR-002: Use of Double-Entry Ledger for Financial Transactions

**Status:** Accepted

**Context:**
Financial systems require strong guarantees around correctness, traceability, and auditability of money movement.

**Decision:**
Implement a **double-entry ledger system** with immutable (append-only) entries.

**Consequences:**

* Full audit trail of all financial transactions
* Enables reconciliation and debugging
* Aligns with standard financial system design
* Adds complexity compared to simple balance updates

**Alternatives Considered:**

* Direct balance mutation (rejected due to lack of auditability)

---

### ADR-003: Event-Driven Internal Architecture

**Status:** Accepted

**Context:**
The system must support future integrations (notifications, analytics, risk engines) without tightly coupling components.

**Decision:**
Use **domain events** to communicate between modules internally.

**Consequences:**

* Loose coupling between core logic and secondary concerns
* Enables asynchronous processing in future
* Improves extensibility
* Requires careful event design and tracing

**Implementation Note:**
Currently implemented with an in-process event bus (`src.adapters.messaging.event_bus`, published by the unit of work) dispatched after commit, with an outbox → Kafka path for notifications.

---

### ADR-004: Strategy Pattern for Loan Product Behavior

**Status:** Accepted

**Context:**
Loan products vary in how interest, fees, and repayment schedules are calculated.

**Decision:**
Encapsulate loan product behavior behind strategy-driven components and routing:

* `InterestFinanceCalculator` (e.g. `NONE`, `SIMPLE_APR`)
* `ProductFeeCalculator` (e.g. `NONE`, `FLAT_ORIGINATION`)
* `RoutingScheduleGenerator` delegating to concrete schedule generators by `repayment_strategy`

**Consequences:**

* Supports multiple loan types without code duplication
* Makes business rules explicit and testable
* Enables future extension without modifying core logic
* Slight increase in abstraction complexity

---

### ADR-005: PostgreSQL as Primary Data Store

**Status:** Accepted

**Context:**
The system requires strong consistency for financial data and support for relational queries.

**Decision:**
Use **PostgreSQL** as the primary database.

**Consequences:**

* ACID compliance ensures data integrity
* Strong support for relational modeling
* JSONB enables flexible configurations
* Scaling requires careful indexing and optimization

---

### ADR-006: Separation of Repayment Schedules and Payments

**Status:** Accepted

**Context:**
Loan repayment involves expected payments (schedules) and actual payments (transactions), which may not align perfectly.

**Decision:**
Model **repayment schedules** and **payments** as separate entities.

**Consequences:**

* Supports partial payments
* Enables overdue tracking
* Improves clarity of financial state
* Requires allocation logic to map payments to schedules

---

### ADR-007: Idempotent Payment Processing

**Status:** Accepted

**Context:**
Payment systems often involve retries, which can lead to duplicate processing.

**Decision:**
Introduce an `external_reference` field to enforce **idempotency**.

**Consequences:**

* Prevents duplicate payments
* Improves system reliability
* Requires validation and uniqueness constraints

---

### ADR-008: Background Jobs for Time-Based State Changes

**Status:** Accepted

**Context:**
Certain state transitions (e.g., overdue loans) depend on time rather than user actions.

**Decision:**
Use **scheduled background jobs** for time-based processing.

**Consequences:**

* Decouples time-based logic from APIs
* Enables periodic reconciliation
* Requires idempotency and careful monitoring

---

### ADR-009: Use of JSONB for Extensible Configuration

**Status:** Accepted

**Context:**
Loan products may require evolving configuration without frequent schema changes.

**Decision:**
Use **JSONB fields** for flexible configuration storage.

**Consequences:**

* Reduces schema churn
* Enables rapid experimentation
* Requires validation at application level
