"""Test fixtures: file-backed SQLite schema per test, wired through the real injector container."""

import uuid
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from injector import Injector
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.repositories.database import create_schema, drop_schema
from src.adapters.web.security import JwtTokenService
from src.application.domain.customer import Customer
from src.application.domain.loan_product import LoanProduct
from src.application.ports.services import IClock
from src.infrastructure.clock import SystemClock
from src.infrastructure.config.settings import Settings, get_settings
from src.infrastructure.container import build_injector

TEST_SECRET = "test-secret-test-secret-test-secret"
TEST_ISSUER = "lms-api-test"


class ControllableClock(IClock):
    """Real time by default; ``freeze(...)`` pins it for time-dependent tests."""

    def __init__(self) -> None:
        self._system = SystemClock()
        self._now: datetime | None = None
        self._today: date | None = None

    def freeze(self, now: datetime, today: date | None = None) -> None:
        self._now, self._today = now, today or now.date()

    def now(self) -> datetime:
        return self._now or self._system.now()

    def today(self) -> date:
        return self._today or self._system.today()


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Iterator[Settings]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'lms.db'}")
    monkeypatch.setenv("SCHEDULING_ENABLED", "false")
    monkeypatch.setenv("NOTIFICATIONS_KAFKA_ENABLED", "false")
    monkeypatch.setenv("AUTH_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("AUTH_JWT_ISSUER", TEST_ISSUER)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def clock() -> ControllableClock:
    return ControllableClock()


@pytest.fixture
def injector(settings, clock) -> Iterator[Injector]:
    container = build_injector(settings, clock)
    engine = container.get(Engine)
    container.get(sessionmaker)  # maps the domain classes
    create_schema(engine)
    yield container
    drop_schema(engine)
    engine.dispose()


@pytest.fixture
def app(settings, injector):
    from src.main import create_app

    return create_app(settings, start_background=False, injector=injector)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(injector) -> Iterator[Session]:
    """Raw session for arranging data and asserting on persisted state."""
    with injector.get(sessionmaker)() as s:
        yield s


@pytest.fixture
def tokens(settings) -> JwtTokenService:
    return JwtTokenService.from_settings(settings)


@pytest.fixture
def admin_headers(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.issue('admin-user', ['ADMIN'])}"}


@pytest.fixture
def user_headers(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens.issue('regular-user', ['USER'])}"}


def make_customer(session: Session, credit_limit: str = "50000.00", status: str = "ACTIVE") -> Customer:
    now = SystemClock().now()
    customer = Customer(
        id=uuid.uuid4(),
        name="Test Customer",
        email=f"test-{uuid.uuid4()}@example.com",
        status=status,
        credit_limit=Decimal(credit_limit),
        available_credit=Decimal(credit_limit),
        created_at=now,
        updated_at=now,
    )
    session.add(customer)
    session.commit()
    return customer


def make_product(session: Session, **overrides) -> LoanProduct:
    fields = {
        "name": "Test Product",
        "interest_strategy": "NONE",
        "repayment_strategy": "EQUAL_INSTALLMENTS",
        "fee_strategy": "NONE",
        "config": {"installments": 2},
        "created_at": SystemClock().now(),
    }
    fields.update(overrides)
    product = LoanProduct(**fields)
    session.add(product)
    session.commit()
    return product
