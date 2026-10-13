from injector import inject
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from src.adapters.repositories.repo_impl import (
    AuditRepository,
    CustomerRepository,
    LedgerRepository,
    LoanProductRepository,
    LoanRepository,
    NotificationRepository,
    OutboxRepository,
    PaymentRepository,
)
from src.application.domain.errors import ConcurrencyError, DataConflictError
from src.application.ports.services import IEventPublisher
from src.application.ports.uow import IUnitOfWork


class SqlAlchemyUnitOfWork(IUnitOfWork):
    """Opens a fresh session per ``with`` block; never shared between concurrent requests."""

    @inject
    def __init__(self, session_factory: sessionmaker, event_publisher: IEventPublisher):
        super().__init__(event_publisher)
        self._session_factory = session_factory
        self.session: Session | None = None

    def _begin(self) -> None:
        if self.session is not None:
            raise RuntimeError("Unit of work is already active (nested use is not supported)")
        self.session = self._session_factory()
        self.customers = CustomerRepository(self.session)
        self.products = LoanProductRepository(self.session)
        self.loans = LoanRepository(self.session, self.track)
        self.payments = PaymentRepository(self.session)
        self.ledger = LedgerRepository(self.session)
        self.audit = AuditRepository(self.session)
        self.notifications = NotificationRepository(self.session)
        self.outbox = OutboxRepository(self.session)

    def _end(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def _translate(self, exc: BaseException) -> Exception | None:
        if isinstance(exc, StaleDataError):
            return ConcurrencyError("Concurrent modification; please retry")
        if isinstance(exc, IntegrityError):
            return DataConflictError("Data conflict: duplicate or invalid reference")
        return None
