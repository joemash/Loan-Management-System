import uuid
from decimal import Decimal
from typing import Any

from injector import inject

from src.application.domain import loan_product_rules as rules
from src.application.domain.errors import NotFoundError
from src.application.domain.loan_product import LoanProduct
from src.application.ports.pagination import Page, PageQuery
from src.application.ports.services import IClock
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import ILoanProductUseCases


class LoanProductUseCases(ILoanProductUseCases):
    @inject
    def __init__(self, uow: IUnitOfWork, clock: IClock):
        self.uow = uow
        self.clock = clock

    def create(
        self,
        *,
        name: str,
        interest_strategy: str,
        repayment_strategy: str,
        fee_strategy: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        min_tenure_days: int | None = None,
        max_tenure_days: int | None = None,
        config: dict[str, Any] | None = None,
    ) -> LoanProduct:
        product = rules.define_product(
            name=name,
            interest_strategy=interest_strategy,
            repayment_strategy=repayment_strategy,
            fee_strategy=fee_strategy,
            min_amount=min_amount,
            max_amount=max_amount,
            min_tenure_days=min_tenure_days,
            max_tenure_days=max_tenure_days,
            config=config,
            now=self.clock.now(),
        )
        with self.uow:
            self.uow.products.add(product)
        return product

    def update(self, product_id: uuid.UUID, **changes: Any) -> LoanProduct:
        with self.uow:
            product = _require(self.uow.products.get(product_id), product_id)
            rules.revise_product(product, **changes)
        return product

    def get(self, product_id: uuid.UUID) -> LoanProduct:
        with self.uow:
            return _require(self.uow.products.get(product_id), product_id)

    def list(self, query: PageQuery) -> Page[LoanProduct]:
        with self.uow:
            return self.uow.products.list(query)


def _require(product: LoanProduct | None, product_id: uuid.UUID) -> LoanProduct:
    if product is None:
        raise NotFoundError(f"Loan product not found: {product_id}")
    return product
