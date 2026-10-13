# Lending Platform Backend (Python / FastAPI)

## 1. Overview

This project implements a simplified backend for a digital lending platform using **Python, FastAPI and SQLAlchemy**.
The system supports loan product configuration, loan lifecycle management, customer management and event-driven notifications.

The design prioritises:

* **Extensibility** — to support multiple loan products and evolving business rules
* **Auditability** — critical for financial systems handling money movement
* **Separation of concerns** — to enable multiple teams to work independently over time
* **Production readiness** — with considerations for scaling, observability, and failure handling

---

## 2. High-Level Architecture

The system is implemented as a **modular monolith**, structured around domain boundaries rather than technical layers.

### Core Modules

* **Customer** — manages customer profiles and credit limits
* **Loan Product** — defines configurable lending rules and strategies
* **Loan** — core lifecycle management of loans
* **Repayment** — schedules and payment allocation
* **Ledger** — tracks all financial movements (double-entry)
* **Notification** — event-driven communication layer

This structure allows the system to evolve into microservices in the future without significant refactoring.

Internally the code follows a **hexagonal (ports and adapters)** architecture: a framework-free application core (domain + use cases) talks to the outside world only through ports, with SQLAlchemy, FastAPI, Kafka, Prometheus and APScheduler as swappable adapters. See [docs/architecture.md](docs/architecture.md).

### Architecture Diagram

```
                          +----------------------+
                          |      API Clients     |
                          | (Web / Mobile / Ops) |
                          +----------+-----------+
                                     |
                                     v
                          +----------------------+
                          |   FastAPI App        |
                          |  (Modular Monolith)  |
                          +----------+-----------+
                                     |
        ------------------------------------------------------------------
        |            |             |              |              |         |
        v            v             v              v              v         v

+-------------+ +-------------+ +-------------+ +-------------+ +-------------+ +-------------+
|  Customer   | | LoanProduct | |    Loan     | |  Repayment  | |   Ledger    | | Notification|
|   Module    | |   Module    | |   Module    | |   Module    | |   Module    | |   Module    |
+------+------+ +------+------+ +------+------+ +------+------+ +------+------+ +------+------+
       |               |               |               |               |               |
       -------------------------------------------------------------------------------
                                     |
                                     v
                          +----------------------+
                          |   Domain Events Bus  |
                          | (in-process bus,     |
                          |  after-commit)       |
                          +----------+-----------+
                                     |
                                     v
                          +----------------------+
                          | Notification Handlers|
                          | (Email/SMS - stubbed)|
                          +----------------------+

                                     |
                                     v
                          +----------------------+
                          |     PostgreSQL       |
                          |----------------------|
                          | customers            |
                          | loan_products        |
                          | loans                |
                          | repayment_schedules  |
                          | payments             |
                          | ledger_accounts      |
                          | ledger_entries       |
                          | notifications        |
                          | notification_outbox  |
                          | audit_log            |
                          +----------------------+
```

### Notes

* Each module encapsulates its own domain logic and data access
* Communication between modules happens via **well-defined interfaces and domain events**
* The system is designed to evolve toward **asynchronous processing** without major refactoring
* The **Ledger module** is isolated to ensure financial correctness and auditability

---

## 3. Key Design Decisions

### 3.1 Modular Monolith

Rather than prematurely adopting microservices, the system is built as a modular monolith with strong internal boundaries.

**Why:**

* Reduces operational complexity early on
* Enables faster iteration
* Keeps domain logic cohesive

**Future path:**
Modules can be extracted into services (e.g., Ledger, Notifications) as scale and team structure evolve.

---

### 3.2 Event-Driven Architecture

The system uses domain events to decouple core business logic from secondary concerns.

**Examples:**

* `LoanDisbursedEvent`
* `PaymentReceivedEvent`
* `LoanOverdueEvent`
* `PaymentDueEvent` (reminder jobs)

**Benefits:**

* Notifications are triggered without coupling to loan logic
* Enables future integrations (analytics, risk engines, external systems)
* Supports asynchronous processing

---

### 3.3 Ledger-Based Accounting (Double Entry)

All monetary movements are recorded using a **double-entry ledger**.

**Example:**

* Loan disbursement:

  * Debit: Loan account
  * Credit: Customer account

* Repayment:

  * Debit: Customer account
  * Credit: Loan account

**Why:**

* Ensures auditability and traceability
* Enables reconciliation
* Avoids inconsistencies from mutable balance fields

The ledger is **append-only**, ensuring a complete financial history.

---

### 3.4 Loan Lifecycle as Controlled State Transitions

Loans move through a defined lifecycle (loan-level status). **Overdue** is tracked per repayment schedule row; the loan may transition to **DEFAULTED** after prolonged delinquency (configurable).

```
CREATED → APPROVED → DISBURSED → CLOSED
                    ↘ DEFAULTED (policy)
```

State transitions are enforced in the domain layer to prevent invalid operations.

**Why:**

* Prevents inconsistent states
* Makes business rules explicit
* Simplifies reasoning about edge cases

---

### 3.5 Strategy-Based Loan Product Configuration

Loan products encapsulate behavior using strategies:

* Interest calculation
* Repayment schedule generation
* Fee computation

**Why:**

* Avoids hardcoding business rules
* Supports multiple loan types (e.g., installment, bullet loans)
* Enables safe extension without modifying core logic

Flexible configuration is supported using JSON fields for future extensions.

Current baseline includes strict strategy whitelists, strategy-aware config validation,
installment cadence via `config.installment_period_months`, explicit PATCH config
replacement semantics, and DB-level product constraints.

---

### 3.6 Separation of Payments and Repayment Schedules

* **Repayment schedules** define expected payments
* **Payments** represent actual money received

**Why:**

* Supports partial payments
* Enables overdue tracking
* Allows accurate allocation logic

---

### 3.7 Idempotency in Payment Processing

Payments include an `external_reference` field to ensure idempotency.

**Why:**

* Prevents duplicate processing from retries
* Critical in distributed financial systems

---

### 3.8 Background Processing

Scheduled jobs handle:

* Overdue detection
* Future extensibility (e.g., interest accrual, reminders)

Jobs are designed to be **idempotent and safe to retry**.

---

## 4. Data Model Overview

The schema is designed for **consistency, traceability, and extensibility**.

Key entities:

* `customers`
* `loan_products`
* `loans`
* `repayment_schedules`
* `payments`
* `ledger_accounts`
* `ledger_entries`
* `notifications`
* `notification_outbox`
* `audit_log`

### Key Decisions

* Monetary values use `NUMERIC(18,2)` (Python `Decimal`) to avoid floating-point errors
* Ledger entries are immutable (append-only)
* Loan product configuration supports flexible extensions via JSON
* Derived values (e.g., available credit) are stored for performance but remain reconcilable

---

## 5. API Design

The API is designed around **business workflows**, not CRUD operations.

### Example Endpoints

* `POST /loans/apply`
* `POST /loans/{id}/approve`
* `POST /loans/{id}/disburse`
* `POST /loans/{id}/repay`
* `GET /loans/{id}/summary` (principal, paid, remaining, overdue, penalties)
* `GET /customers/{id}` (profile and credit line)

This aligns the API with real-world operations and reduces ambiguity.

### Swagger / OpenAPI

Swagger UI is available for interactive API exploration and request testing:

* UI: `http://localhost:8080/swagger-ui` (group selector in the top bar)
* OpenAPI JSON: `http://localhost:8080/api-docs` (all), `/api-docs/admin`, `/api-docs/core`

The API docs are grouped into:

* `admin` for `/admin/**`
* `core` for `/loans/**` and `/customers/**`

### Authentication and Authorization

The API uses JWT Bearer authentication.

Access rules:

* `/admin/**` requires `ROLE_ADMIN`
* `/loans/**` and `/customers/**` require any authenticated user
* `/swagger-ui`, `/api-docs/**`, and `/actuator/*` (health, prometheus) are public for local usage

Set JWT settings through environment variables:

* `AUTH_JWT_SECRET` (HMAC secret, required in real deployments)
* `AUTH_JWT_ISSUER` (token issuer expected by API)
* `AUTH_JWT_CLOCK_SKEW_SECONDS` (optional clock skew tolerance)

Example authenticated calls:

```bash
# USER token can call core APIs
curl -X POST "http://localhost:8080/loans/apply" \
  -H "Authorization: Bearer ${USER_JWT}" \
  -H "Content-Type: application/json" \
  -d '{
    "customerId": "a0000000-0000-4000-8000-000000000001",
    "productId": "b0000000-0000-4000-8000-000000000001",
    "amount": 1000.00
  }'

# ADMIN token is required for /admin/**
curl "http://localhost:8080/admin/loans?page=0&size=20" \
  -H "Authorization: Bearer ${ADMIN_JWT}"
```

---

## 6. Notifications

The notification system is **event-driven and pluggable**.

* Triggered by domain events
* Persists a `notifications` row per event, then queues delivery via Kafka using an outbox table
* Tracks delivery lifecycle (`PENDING`, `SENT`, `FAILED`, `RETRYING`, `DLQ`) and UI status (`UNREAD`, `READ`)
* Supports channel dispatch extension points (current channel adapter remains `STUB_LOG`)
* Easily extensible without modifying core logic

Current implementation ships with Kafka queueing (confluent-kafka) plus stubbed channel dispatch for local development.

---

## 7. Observability & Operations

The system is designed with production readiness in mind:

* Structured logging for traceability
* Background jobs designed to be safe and idempotent

Local metrics observability is now available with:

* `prometheus-client` metrics endpoint (`/actuator/prometheus`) and health probes (`/actuator/health`)
* Prometheus scraping backend metrics
* Grafana with auto-provisioned Prometheus datasource

For setup and troubleshooting, see [Observability guide](docs/observability/README.md).

Planned next steps:

* Add alerting around scheduler failures and retry saturation
* Add log aggregation (Loki/Promtail) and distributed tracing (OpenTelemetry/Tempo)

---

## 8. Deployment Considerations

The system currently runs locally with Docker + PostgreSQL. A target cloud-native deployment path is:

* **Database**: PostgreSQL (ACID compliance for financial data)
* **Containerization**: Docker
* **Orchestration (future)**: Kubernetes
* **GitOps (future)**: ArgoCD for deployment management

### Future Enhancements

* Harden queue operations (DLQ policies, consumer scaling, partitioning strategy)
* Extract ledger and notification modules into independent services
* Add caching layer for read-heavy endpoints

---

## 9. Trade-offs and Assumptions

### Trade-offs

* Chose synchronous APIs for simplicity, while designing for async evolution via events
* Stored some derived values (e.g., available credit) for performance; **disbursement** reserves the **full contractual** schedule total (principal plus configured interest/fees), released when the loan **closes**
* Used a modular monolith instead of microservices to reduce early complexity

### Assumptions

* Single currency system (can be extended)
* Simplified interest calculations for MVP
* No external payment provider integration (stubbed)

---

## 10. Running the Application

### Prerequisites

* Python 3.12+ and [uv](https://docs.astral.sh/uv/)
* Docker

### Steps

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Start local infrastructure (PostgreSQL on `5433`, Kafka on `9092`, Prometheus, Grafana):

   ```bash
   docker compose up -d
   ```

   These host ports are the same as the Java project's stack, so stop that stack before starting this one.

3. Apply migrations, which include **seed data** for the local demo:

   ```bash
   uv run alembic upgrade head
   ```

   Demo IDs after migrating: customer `a0000000-0000-4000-8000-000000000001`, loan product `b0000000-0000-4000-8000-000000000001`.

4. Start the API (scheduler and Kafka relay start with it):

   ```bash
   uv run uvicorn --factory src.main:app_factory --port 8080 --reload
   ```

5. Generate local JWTs (see [Authentication guide](docs/authentication.md)):

   ```bash
   export ADMIN_JWT=$(uv run python scripts/make_jwt.py ADMIN)
   export USER_JWT=$(uv run python scripts/make_jwt.py USER)
   ```

6. Open Swagger UI at `http://localhost:8080/swagger-ui`, Prometheus at `http://localhost:9090` and Grafana at `http://localhost:3000` (`admin` / `admin`). See [Using the API from Swagger UI](#using-the-api-from-swagger-ui) below.

### Using the API from Swagger UI

Every endpoint except `/swagger-ui`, `/api-docs` and `/actuator/*` needs a JWT. The examples use port
`8080`; if you changed the port mapping in `docker-compose.yml` (e.g. `"8004:8080"`), use that port instead.

**1. Generate a token** (from the project folder):

```bash
uv run python scripts/make_jwt.py ADMIN    # /admin/** and everything else
uv run python scripts/make_jwt.py USER     # enough for /loans/** and /customers/**
```

It prints a long string starting with `eyJ...`. Tokens last 1 hour by default (`--ttl 28800` for 8 hours).
The script signs with the default secret, which matches the app. If you run the app with a custom
`AUTH_JWT_SECRET`, export the same value before running the script, otherwise the token is rejected with 401.

**2. Authorize in Swagger:**

1. Open `http://localhost:8080/swagger-ui`. It opens on the **all** definition; the **Select a definition**
   dropdown (top right) narrows the list to `admin` or `core`.
2. Click the green **Authorize** button (padlock icon).
3. Paste the token into **Value**: just the token, Swagger adds `Bearer ` itself.
4. Click **Authorize**, then **Close**. The padlocks next to the endpoints now show as locked.

The token is kept across page reloads. To switch roles, use **Authorize → Logout** and paste the other token.

**3. Call an endpoint**, e.g. create a customer:

1. Expand **admin-customers → `POST /admin/customers`**.
2. Click **Try it out** and replace the request body:

   ```json
   {
     "name": "Jane Doe",
     "email": "jane@example.com",
     "creditLimit": 10000.00,
     "status": "ACTIVE"
   }
   ```

3. Click **Execute**. You should get **201** with the new customer; copy its `id` for the next calls.

**Full loan flow** (use the `id`s returned by each step):

| Step | Endpoint | Token | Request body / notes |
|------|----------|-------|----------------------|
| Create product | `POST /admin/loan-products` | ADMIN | `{"name":"6m","minAmount":100,"maxAmount":10000,"interestStrategy":"SIMPLE_APR","repaymentStrategy":"EQUAL_INSTALLMENTS","feeStrategy":"FLAT_ORIGINATION","config":{"installments":6,"apr":0.12,"origination_fee":25}}` |
| Create loan | `POST /loans/apply` ("Create a loan (apply)") | any | `{"customerId":"<id>","productId":"<id>","amount":1000}` |
| Approve | `POST /loans/{loan_id}/approve` | any | path parameter only |
| Disburse | `POST /loans/{loan_id}/disburse` | any | returns 204 |
| Repay | `POST /loans/{loan_id}/repay` | any | `{"amount":300,"externalReference":"pay-1"}`; repeating a reference is a safe no-op |
| Check | `GET /loans/{loan_id}/summary`, `GET /admin/loans/{loan_id}` | any / ADMIN | |

Shortcut: migrations seed customer `a0000000-0000-4000-8000-000000000001` and loan product
`b0000000-0000-4000-8000-000000000001`, so you can go straight to **Create loan**.

**Troubleshooting:**

| Response | Meaning | Fix |
|----------|---------|-----|
| 401 `Authentication is required` | no token sent | click **Authorize** and paste the token |
| 401 `Invalid or expired bearer token` | token expired or signed with another secret | generate a new token (with the app's `AUTH_JWT_SECRET`) |
| 403 `You are not allowed to access this resource` | `USER` token on `/admin/**` | use an `ADMIN` token |

### Running fully in Docker

```bash
docker compose --profile app up -d --build   # entrypoint runs `alembic upgrade head`, then uvicorn on :8080
```

Run it locally:
cd ~/Documents/project/Loan-Management-System-Python
uv sync && docker compose up -d && uv run alembic upgrade head
uv run uvicorn --factory src.main:app_factory --port 8080
export ADMIN_JWT=$(uv run python scripts/make_jwt.py ADMIN)   # then use http://localhost:8080/swagger-ui
It uses the same host ports as the Java stack (5433 for Postgres, 9092 for Kafka), so don't run both at once. Port 8080 is currently taken by another container on your machine; pick a different --port or free it first.

The workflow, also in the README under "Database migrations":
uv run alembic revision --autogenerate --rev-id v12 -m "add customer phone"   # review the generated file
uv run alembic upgrade head
uv run alembic check


### Configuration

All settings live in `src/infrastructure/config/settings.py` and can be overridden with environment variables of the same name in upper case (e.g. `DATABASE_URL`) or a `.env` file (see `.env.example`). The main ones:

| Variable | Default |
|----------|---------|
| `DATABASE_URL` | `postgresql+psycopg://ezra_admin:ezra_admin_pass@localhost:5433/ezra_lms` |
| `AUTH_JWT_SECRET` / `AUTH_JWT_ISSUER` / `AUTH_JWT_CLOCK_SKEW_SECONDS` | `change-me-in-prod-…` / `lms-api` / `60` |
| `SCHEDULING_ENABLED` | `true` |
| `SCHEDULER_OVERDUE_CRON` / `SCHEDULER_REMINDER_CRON` | `0 0 1 * * *` / `0 0 8 * * *` |
| `PENALTY_DAILY_RATE` | `0.001` |
| `LOAN_DEFAULT_AFTER_DAYS_PAST_DUE` | `90` |
| `REMINDER_DAYS_BEFORE_DUE` | `3` |
| `NOTIFICATIONS_KAFKA_ENABLED` / `NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS` | `true` / `localhost:9092` |
| `NOTIFICATIONS_OUTBOX_POLL_DELAY_MS` / `NOTIFICATIONS_RETRY_MAX_ATTEMPTS` | `2000` / `5` |

### Database migrations

Alembic keeps **one project-wide history** in `migrations/versions/` (not per module like Django apps).
Revisions `v01`–`v11` run the original Flyway SQL files in `migrations/sql/`; later revisions are
autogenerated from the table definitions in `src/adapters/repositories/orm.py`.

```bash
# 1. change a table in src/adapters/repositories/orm.py (and the matching domain class)
# 2. generate the next revision (keep the vNN sequence) and review it
uv run alembic revision --autogenerate --rev-id v12 -m "add customer phone"
# 3. apply it
uv run alembic upgrade head
# check whether models and DB are in sync (prints "No new upgrade operations detected.")
uv run alembic check
```

New tables go in `src/adapters/repositories/orm.py` (plus a mapping in `start_mappers()`); autogenerate reads that metadata.
Autogenerate needs a database at `head` to compare against, so run `docker compose up -d db` first.

### Tests and linting

```bash
uv run pytest          # SQLite-backed; no Docker needed
uv run ruff check . && uv run ruff format --check .
```

### Project layout

Hexagonal (ports and adapters) 

```
src/
  main.py                     create_app: builds the container, mounts routes, starts scheduler + consumer
  application/                framework-free core
    domain/                   entities, aggregates, domain services, events, errors (stdlib only)
    ports/                    ABCs: IUnitOfWork, repositories, use cases, clock, event publisher, producer, channel, metrics
    usecases/                 CustomerUseCases, LoanProductUseCases, LoanUseCases, LoanMaintenanceUseCases, NotificationUseCases
    config.py                 LoanPolicy, NotificationPolicy
  adapters/
    repositories/             SQLAlchemy tables + imperative mapping (orm.py), repositories, unit of work
    web/                      FastAPI routes, schemas, JWT security, error mapping, Swagger + actuator
    messaging/                in-process event bus, Kafka producer/consumer, stub notification channel
    observability/            Prometheus metrics adapter and HTTP middleware
    scheduling/               APScheduler jobs
  infrastructure/
    config/settings.py        settings (env vars / .env, e.g. DATABASE_URL)
    clock.py                  SystemClock / FixedClock
    container.py              injector bindings (composition root) + event subscriptions
migrations/                   Alembic env + revisions (v01..v11 run sql/V*.sql ported from Flyway; later ones autogenerated)
scripts/make_jwt.py           local token generator
tests/                        domain / usecases / adapters / web / architecture tests
```

### Documentation map

* [Documentation index](docs/README.md)
* [Architecture (hexagonal)](docs/architecture.md)
* [Domain modules](docs/modules.md)
* [Authentication](docs/authentication.md)
* [Notifications](docs/notifications.md)
* [Observability](docs/observability/README.md)
* [ADRs](docs/ADRs.md)

---

## 11. Admin API

The admin frontend (`../lms_frontend`) works unchanged against this backend: paths, camelCase JSON and the paged response shape (`{"content": [...], "page": {"size", "number", "totalElements", "totalPages"}}`) all match the Java API. List endpoints accept `page`, `size` and repeatable `sort=property,asc|desc`.

* `GET /admin/loans` (optional: `customerId`, `status`)
* `GET /admin/loans/{id}`
* `GET /admin/customers`, `GET /admin/customers/{id}`, `POST /admin/customers`, `PATCH /admin/customers/{id}`
* `GET /admin/loan-products`, `GET /admin/loan-products/{id}`, `POST /admin/loan-products`, `PATCH /admin/loan-products/{id}`
* `GET /admin/notifications` (optional: `customerId`, `type`, `deliveryStatus`, `uiStatus`, `from`, `to`; combined with AND)
* `GET /admin/notifications/{id}`, `POST /admin/notifications/{id}/read`

Loan product contract:

* `interestStrategy`: `NONE`, `SIMPLE_APR`
* `repaymentStrategy`: `EQUAL_INSTALLMENTS`, `EQUAL_PRINCIPAL_INSTALLMENTS`
* `feeStrategy`: `NONE`, `FLAT_ORIGINATION` (stored as `NONE` when omitted)
* `config` keys: `installments` (≥ 1, default 1), `installment_period_months` (≥ 1, default 1), `apr` (in `[0, 1]`, required for `SIMPLE_APR`), `origination_fee` (≥ 0, required for `FLAT_ORIGINATION`)
* PATCH `config` **replaces** the whole config object.

### Happy-path demo script

Assumes `ADMIN_JWT` and `USER_JWT` are exported and `jq` is installed.

```bash
B=http://localhost:8080

CUSTOMER_ID=$(curl -s -X POST "$B/admin/customers" -H "Authorization: Bearer ${ADMIN_JWT}" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Borrower","email":"demo.borrower@example.com","creditLimit":12000.00,"status":"ACTIVE"}' | jq -r '.id')

PRODUCT_ID=$(curl -s -X POST "$B/admin/loan-products" -H "Authorization: Bearer ${ADMIN_JWT}" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Product 6m","minAmount":100.00,"maxAmount":10000.00,"minTenureDays":30,"maxTenureDays":1825,
       "interestStrategy":"SIMPLE_APR","repaymentStrategy":"EQUAL_INSTALLMENTS","feeStrategy":"FLAT_ORIGINATION",
       "config":{"installments":6,"apr":0.12,"origination_fee":25.00}}' | jq -r '.id')

LOAN_ID=$(curl -s -X POST "$B/loans/apply" -H "Authorization: Bearer ${USER_JWT}" \
  -H "Content-Type: application/json" \
  -d "{\"customerId\":\"${CUSTOMER_ID}\",\"productId\":\"${PRODUCT_ID}\",\"amount\":1000.00}" | jq -r '.id')

curl -s -X POST "$B/loans/${LOAN_ID}/approve" -H "Authorization: Bearer ${ADMIN_JWT}"
curl -s -X POST "$B/loans/${LOAN_ID}/disburse" -H "Authorization: Bearer ${ADMIN_JWT}"

for ref in demo-pay-1 demo-pay-2; do
  curl -s -X POST "$B/loans/${LOAN_ID}/repay" -H "Authorization: Bearer ${USER_JWT}" \
    -H "Content-Type: application/json" -d "{\"amount\":300.00,\"externalReference\":\"${ref}\"}"
done

curl -s "$B/loans/${LOAN_ID}/summary" -H "Authorization: Bearer ${USER_JWT}" | jq
# {"principal":1000.0,"paid":600.0,"remaining":485.0,"overdue":0.0,"penalties":0.0}
curl -s "$B/customers/${CUSTOMER_ID}" -H "Authorization: Bearer ${USER_JWT}" | jq '{creditLimit, availableCredit}'
# {"creditLimit":12000.0,"availableCredit":10915.0}   (full contractual total 1085 reserved)
```

Reusing the same `externalReference` is safe: the repeat call is a no-op.

---

## 12. Architectural Decision Records

See [docs/ADRs.md](docs/ADRs.md).
