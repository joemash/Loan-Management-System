"""Customer and credit line.

``available_credit`` is reserved on disbursement (full contractual total) and released when the loan closes.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from src.application.domain.errors import DomainStateError, DomainValidationError

STATUS_ACTIVE = "ACTIVE"


class Customer:
    def __init__(
        self,
        *,
        id: uuid.UUID,
        name: str,
        email: str,
        status: str,
        credit_limit: Decimal,
        available_credit: Decimal,
        created_at: datetime,
        updated_at: datetime,
    ):
        self.id = id
        self.name = name
        self.email = email
        self.status = status
        self.credit_limit = credit_limit
        self.available_credit = available_credit
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def register(
        cls, name: str, email: str, credit_limit: Decimal, status: str | None, now: datetime
    ) -> "Customer":
        """New customer with ``available_credit`` equal to ``credit_limit``."""
        return cls(
            id=uuid.uuid4(),
            name=name.strip(),
            email=email.strip(),
            status=status if status is not None else STATUS_ACTIVE,
            credit_limit=credit_limit,
            available_credit=credit_limit,
            created_at=now,
            updated_at=now,
        )

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def update(
        self,
        now: datetime,
        name: str | None = None,
        status: str | None = None,
        credit_limit: Decimal | None = None,
    ) -> None:
        """Partial update. A credit-limit change shifts ``available_credit`` by the same delta
        (never negative, never above the new limit)."""
        if name is not None:
            self.name = name.strip()
        if status is not None:
            self.status = status.strip()
        if credit_limit is not None:
            new_available = self.available_credit + (credit_limit - self.credit_limit)
            if new_available < 0:
                raise DomainValidationError(
                    "Cannot reduce credit limit below outstanding reservation; "
                    f"available would be {new_available}"
                )
            self.credit_limit = credit_limit
            self.available_credit = min(new_available, credit_limit)
        self.updated_at = now

    def reserve_credit(self, amount: Decimal) -> None:
        if not self.is_active:
            raise DomainStateError("Customer is not active")
        if self.available_credit < amount:
            raise DomainValidationError(
                f"Insufficient available credit: need {amount}, have {self.available_credit}"
            )
        self.available_credit -= amount

    def release_credit(self, amount: Decimal) -> None:
        self.available_credit += amount
