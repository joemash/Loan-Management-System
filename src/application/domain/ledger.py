"""Append-only double-entry ledger.

Disbursement: debit LOAN, credit CUSTOMER. Repayment: debit CUSTOMER, credit LOAN.
"""

import uuid
from datetime import datetime
from decimal import Decimal

ACCOUNT_CUSTOMER = "CUSTOMER"
ACCOUNT_LOAN = "LOAN"

REFERENCE_DISBURSEMENT = "DISBURSEMENT"
REFERENCE_REPAYMENT = "REPAYMENT"


class LedgerAccount:
    def __init__(
        self, *, id: uuid.UUID, account_type: str, reference_id: uuid.UUID | None, created_at: datetime
    ):
        self.id = id
        self.account_type = account_type
        self.reference_id = reference_id
        self.created_at = created_at

    @classmethod
    def open(cls, account_type: str, reference_id: uuid.UUID, now: datetime) -> "LedgerAccount":
        return cls(id=uuid.uuid4(), account_type=account_type, reference_id=reference_id, created_at=now)


class LedgerEntry:
    def __init__(
        self,
        *,
        id: uuid.UUID,
        debit_account_id: uuid.UUID,
        credit_account_id: uuid.UUID,
        amount: Decimal,
        reference_type: str | None,
        reference_id: uuid.UUID | None,
        created_at: datetime,
    ):
        self.id = id
        self.debit_account_id = debit_account_id
        self.credit_account_id = credit_account_id
        self.amount = amount
        self.reference_type = reference_type
        self.reference_id = reference_id
        self.created_at = created_at

    @classmethod
    def post(
        cls,
        debit: LedgerAccount,
        credit: LedgerAccount,
        amount: Decimal,
        reference_type: str,
        reference_id: uuid.UUID,
        now: datetime,
    ) -> "LedgerEntry":
        return cls(
            id=uuid.uuid4(),
            debit_account_id=debit.id,
            credit_account_id=credit.id,
            amount=amount,
            reference_type=reference_type,
            reference_id=reference_id,
            created_at=now,
        )
