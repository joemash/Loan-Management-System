import uuid
from decimal import Decimal

from injector import inject

from src.application.domain.customer import Customer
from src.application.domain.errors import DomainValidationError, NotFoundError
from src.application.ports.pagination import Page, PageQuery
from src.application.ports.services import IClock
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import ICustomerUseCases


class CustomerUseCases(ICustomerUseCases):
    @inject
    def __init__(self, uow: IUnitOfWork, clock: IClock):
        self.uow = uow
        self.clock = clock

    def register(self, name: str, email: str, credit_limit: Decimal, status: str | None = None) -> Customer:
        with self.uow:
            if self.uow.customers.find_by_email(email.strip()) is not None:
                raise DomainValidationError(f"Email already registered: {email.strip()}")
            customer = Customer.register(name, email, credit_limit, status, self.clock.now())
            self.uow.customers.add(customer)
        return customer

    def update(
        self,
        customer_id: uuid.UUID,
        name: str | None = None,
        status: str | None = None,
        credit_limit: Decimal | None = None,
    ) -> Customer:
        with self.uow:
            customer = _require(self.uow.customers.get(customer_id), customer_id)
            customer.update(self.clock.now(), name=name, status=status, credit_limit=credit_limit)
        return customer

    def get(self, customer_id: uuid.UUID) -> Customer:
        with self.uow:
            return _require(self.uow.customers.get(customer_id), customer_id)

    def list(self, query: PageQuery) -> Page[Customer]:
        with self.uow:
            return self.uow.customers.list(query)


def _require(customer: Customer | None, customer_id: uuid.UUID) -> Customer:
    if customer is None:
        raise NotFoundError(f"Customer not found: {customer_id}")
    return customer
