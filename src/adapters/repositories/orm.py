"""Table definitions and imperative mapping of the plain domain classes.

The domain layer never imports SQLAlchemy: ``start_mappers()`` instruments the domain classes so the
repositories can persist them. Tables mirror ``migrations/sql`` exactly (``alembic check`` must stay clean).
"""

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    TypeDecorator,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import registry, relationship

from src.application.domain.audit import AuditLog
from src.application.domain.customer import Customer
from src.application.domain.ledger import LedgerAccount, LedgerEntry
from src.application.domain.loan import Loan, LoanStatus
from src.application.domain.loan_product import LoanProduct
from src.application.domain.notification import Notification, NotificationOutbox
from src.application.domain.repayment import Payment, RepaymentSchedule, ScheduleStatus

# JSONB on PostgreSQL, plain JSON elsewhere (SQLite in tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(18, 2)


class TextEnum(TypeDecorator):
    """Python ``StrEnum`` stored in a plain ``TEXT`` column (no database enum type)."""

    impl = Text
    cache_ok = True

    def __init__(self, enum_cls: type[enum.StrEnum]):
        super().__init__()
        self.enum_cls = enum_cls

    def process_bind_param(self, value, dialect):
        return None if value is None else self.enum_cls(value).value

    def process_result_value(self, value, dialect):
        return None if value is None else self.enum_cls(value)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


metadata = MetaData()

customers = Table(
    "customers",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("email", Text, nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("credit_limit", Money, nullable=False),
    Column("available_credit", Money, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

loan_products = Table(
    "loan_products",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("min_amount", Money),
    Column("max_amount", Money),
    Column("min_tenure_days", Integer),
    Column("max_tenure_days", Integer),
    Column("interest_strategy", Text, nullable=False),
    Column("repayment_strategy", Text, nullable=False),
    Column("fee_strategy", Text),
    Column("config", JsonType),
    Column("created_at", DateTime, nullable=False),
)

loans = Table(
    "loans",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("customer_id", Uuid, ForeignKey("customers.id"), nullable=False),
    Column("product_id", Uuid, ForeignKey("loan_products.id"), nullable=False),
    Column("principal", Money, nullable=False),
    Column("total_amount", Money),
    Column("status", TextEnum(LoanStatus), nullable=False),
    Column("disbursement_date", Date),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False, onupdate=_utcnow),
    Column("version", BigInteger, nullable=False),
)

repayment_schedules = Table(
    "repayment_schedules",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("loan_id", Uuid, ForeignKey("loans.id"), nullable=False),
    Column("due_date", Date, nullable=False),
    Column("amount_due", Money, nullable=False),
    Column("amount_paid", Money),
    Column("status", TextEnum(ScheduleStatus), nullable=False),
    Column("penalty_accrued", Money, nullable=False),
    Column("penalty_last_accrual_date", Date),
    Column("created_at", DateTime, nullable=False),
    Index("idx_schedule_due_date", "due_date"),
)

payments = Table(
    "payments",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("loan_id", Uuid, ForeignKey("loans.id"), nullable=False),
    Column("amount", Money, nullable=False),
    Column("payment_date", DateTime, nullable=False),
    Column("external_reference", Text, unique=True),
    Column("created_at", DateTime, nullable=False),
)

ledger_accounts = Table(
    "ledger_accounts",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("account_type", Text, nullable=False),
    Column("reference_id", Uuid),
    Column("created_at", DateTime, nullable=False),
)

ledger_entries = Table(
    "ledger_entries",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("debit_account_id", Uuid, ForeignKey("ledger_accounts.id"), nullable=False),
    Column("credit_account_id", Uuid, ForeignKey("ledger_accounts.id"), nullable=False),
    Column("amount", Money, nullable=False),
    Column("reference_type", Text),
    Column("reference_id", Uuid),
    Column("created_at", DateTime, nullable=False),
    Index("idx_ledger_reference", "reference_id"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("customer_id", Uuid),
    Column("event_id", Uuid),
    Column("type", Text),
    Column("channel", Text),
    Column("payload", JsonType),
    Column("status", Text),
    Column("delivery_status", Text),
    Column("ui_status", Text, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("last_error", Text),
    Column("next_retry_at", DateTime),
    Column("sent_at", DateTime),
    Column("read_at", DateTime),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Index("idx_notifications_delivery_status", "delivery_status"),
    Index("idx_notifications_ui_status", "ui_status"),
    Index("idx_notifications_customer_id", "customer_id"),
    Index("idx_notifications_created_at", text("created_at DESC")),
    Index(
        "uk_notifications_event_id",
        "event_id",
        unique=True,
        postgresql_where=text("event_id IS NOT NULL"),
        sqlite_where=text("event_id IS NOT NULL"),
    ),
)

notification_outbox = Table(
    "notification_outbox",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("event_id", Uuid, nullable=False),
    Column("notification_id", Uuid, nullable=False),
    Column("topic", Text, nullable=False),
    Column("event_key", Text, nullable=False),
    Column("payload", JsonType, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text),
    Column("next_retry_at", DateTime),
    Column("created_at", DateTime, nullable=False),
    Column("published_at", DateTime),
    Index("idx_notification_outbox_status_next_retry", "status", "next_retry_at"),
    Index("uk_notification_outbox_event_id", "event_id", unique=True),
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("entity_type", Text),
    Column("entity_id", Uuid),
    Column("action", Text),
    Column("payload", JsonType),
    Column("created_at", DateTime, nullable=False),
)

mapper_registry = registry(metadata=metadata)
_mapped = False


def start_mappers() -> None:
    """Maps domain classes to tables (idempotent)."""
    global _mapped
    if _mapped:
        return
    mapper_registry.map_imperatively(Customer, customers)
    mapper_registry.map_imperatively(LoanProduct, loan_products)
    mapper_registry.map_imperatively(RepaymentSchedule, repayment_schedules)
    mapper_registry.map_imperatively(
        Loan,
        loans,
        properties={
            "schedules": relationship(RepaymentSchedule, cascade="all, delete-orphan", lazy="selectin"),
        },
        # Optimistic locking (Java @Version): a stale update raises StaleDataError → ConcurrencyError.
        version_id_col=loans.c.version,
    )
    mapper_registry.map_imperatively(Payment, payments)
    mapper_registry.map_imperatively(LedgerAccount, ledger_accounts)
    mapper_registry.map_imperatively(LedgerEntry, ledger_entries)
    mapper_registry.map_imperatively(Notification, notifications)
    mapper_registry.map_imperatively(NotificationOutbox, notification_outbox)
    mapper_registry.map_imperatively(AuditLog, audit_log)
    _mapped = True
