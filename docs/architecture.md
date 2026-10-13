# Architecture: hexagonal (ports and adapters)

The codebase follows the hexagonal layout: an **application** core that knows nothing
about frameworks, **ports** (abstract interfaces) at its edges, and **adapters** that plug real technology
into those ports. One composition root wires them together with `injector`.

```
                    driving adapters                                   driven adapters
              (call into the application)                     (called by the application)

  HTTP  ─▶ adapters/web/routes ─┐                         ┌─▶ adapters/repositories  ─▶ PostgreSQL
  Cron  ─▶ adapters/scheduling ─┼─▶ ports/usecases ─▶ usecases ─▶ ports ─┼─▶ adapters/messaging ─▶ Kafka, event bus
  Kafka ─▶ adapters/messaging  ─┘         │            │          ├─▶ adapters/observability ─▶ Prometheus
                                          └── domain ──┘          └─▶ infrastructure/clock
```

## Layers

| Layer | Path | Depends on | Contents |
|-------|------|-----------|----------|
| Domain | `src/application/domain/` | nothing (stdlib only) | Entities and aggregates (`Loan`, `Customer`, `RepaymentSchedule`, …), domain services (schedule generation, pricing, product rules, penalties), domain events, errors |
| Ports | `src/application/ports/` | domain | ABCs: `IUnitOfWork`, repository interfaces (`repo.py`), use-case interfaces (`usecases.py`), `IClock`, `IEventPublisher`, `INotificationProducer`, `INotificationChannel`, `INotificationMetrics`; pagination value objects |
| Use cases | `src/application/usecases/` | domain, ports (+ `injector.inject`) | `CustomerUseCases`, `LoanProductUseCases`, `LoanUseCases`, `LoanMaintenanceUseCases`, `NotificationUseCases` |
| Adapters | `src/adapters/` | application, frameworks | `repositories/` (SQLAlchemy tables, imperative mapping, repositories, unit of work), `web/` (FastAPI routes, schemas, JWT, error mapping, docs, actuator), `messaging/` (in-process event bus, Kafka producer/consumer, stub channel), `observability/` (Prometheus), `scheduling/` (APScheduler) |
| Infrastructure | `src/infrastructure/` | everything | `config/settings.py`, `clock.py`, `container.py` (composition root) |

`tests/test_architecture.py` enforces that nothing under `src/application` imports SQLAlchemy, FastAPI,
Kafka, Prometheus, APScheduler, PyJWT, Pydantic, or any adapter/infrastructure module.

## Key mechanics

**Pure domain + imperative mapping.** Domain classes are plain Python. `adapters/repositories/orm.py`
declares the tables (mirroring `migrations/sql` exactly) and calls `map_imperatively` so SQLAlchemy can
persist those classes without the domain importing it. Optimistic locking (`loans.version`) and the
`Loan → schedules` cascade are configured in the mapping.

**Unit of work.** Every use-case method runs inside `with self.uow:`. The base
`IUnitOfWork` commits on success, rolls back on error, translates persistence errors
(`StaleDataError → ConcurrencyError`, `IntegrityError → DataConflictError`), and, **only after a
successful commit**, publishes the domain events raised by aggregates the repositories loaded (or that
were queued with `uow.add_event`).

**Fresh instances per call.**  use cases and units of work are bound
without a scope: each `injector.get(ILoanUseCases)` builds a new use case with its own unit of work and
session. Web requests, scheduled jobs and the Kafka consumer therefore never share a transaction. Only
stateless services (engine, session factory, clock, event bus, producer, metrics) are singletons.

**Events → notifications.** `container.subscribe_event_handlers` subscribes the in-process bus to
`INotificationUseCases.record_*`. Each handler resolves a fresh use case, so recording runs in its own
transaction (Spring's `REQUIRES_NEW`).

**Time.** Domain methods take `now`/`today` explicitly; use cases read them from `IClock`. Tests swap
in a controllable clock through the container.

## Adding a feature

1. Model the behaviour in `application/domain` (plain classes, no I/O).
2. If it needs new persistence or an external system, add/extend a port in `application/ports`.
3. Orchestrate it in a use case (`application/usecases`), inside `with self.uow:`.
4. Implement the port in `adapters/…` and, for new tables, add them to `orm.py` + `start_mappers()` and
   generate a migration (`alembic revision --autogenerate`).
5. Bind the port to the adapter in `infrastructure/container.py`.
6. Expose it through a driving adapter (route, job, consumer) that depends only on the use-case port.

## Testing strategy

| Level | Location | How |
|-------|----------|-----|
| Domain | `tests/domain/` | Plain objects, no database |
| Use cases | `tests/usecases/` | In-memory `FakeUnitOfWork` and fake ports (`tests/fakes.py`), plus container-wired tests on SQLite |
| Adapters | `tests/adapters/` | Real SQLAlchemy on SQLite, security, scheduler cron parsing, message serialisation |
| Web | `tests/web/` | FastAPI `TestClient` through the real container |
| Architecture | `tests/test_architecture.py` | Import-boundary rules |
