"""Loan product: configurable lending rules selected by strategy names plus a JSON ``config``."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any


class LoanProduct:
    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        name: str = "",
        interest_strategy: str | None = None,
        repayment_strategy: str | None = None,
        fee_strategy: str | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        min_tenure_days: int | None = None,
        max_tenure_days: int | None = None,
        config: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.name = name
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.min_tenure_days = min_tenure_days
        self.max_tenure_days = max_tenure_days
        self.interest_strategy = interest_strategy
        self.repayment_strategy = repayment_strategy
        self.fee_strategy = fee_strategy
        self.config = config
        self.created_at = created_at
