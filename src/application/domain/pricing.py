"""Interest and fee strategies (Java ``InterestFinanceCalculator`` and ``ProductFeeCalculator``)."""

from decimal import ROUND_HALF_UP, Decimal

from src.application.domain.errors import DomainValidationError
from src.application.domain.loan_product import LoanProduct
from src.application.domain.loan_product_rules import is_number, to_decimal

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def finance_charge(product: LoanProduct, principal: Decimal, installments: int) -> Decimal:
    """Simple APR finance charge: ``principal × apr × installments / 12``, rounded half-up."""
    strategy = product.interest_strategy
    if strategy is None or strategy.upper() == "NONE":
        return ZERO
    if strategy.upper() == "SIMPLE_APR":
        config = product.config
        if not config or "apr" not in config:
            raise DomainValidationError("SIMPLE_APR requires config.apr")
        apr = config["apr"]
        if not is_number(apr):
            raise DomainValidationError("config.apr must be a number")
        return (principal * to_decimal(apr) * installments / Decimal(12)).quantize(CENTS, ROUND_HALF_UP)
    raise DomainValidationError(f"Unknown interest_strategy: {strategy}")


def upfront_fees(product: LoanProduct) -> Decimal:
    """Flat origination fee from ``config.origination_fee`` when ``FLAT_ORIGINATION`` is selected."""
    strategy = product.fee_strategy
    if strategy is None or strategy.upper() == "NONE":
        return ZERO
    if strategy.upper() == "FLAT_ORIGINATION":
        fee = (product.config or {}).get("origination_fee")
        if fee is None:
            raise DomainValidationError("FLAT_ORIGINATION requires config.origination_fee")
        if not is_number(fee):
            raise DomainValidationError("config.origination_fee must be a number")
        return to_decimal(fee).quantize(CENTS, ROUND_HALF_UP)
    raise DomainValidationError(f"Unknown fee_strategy: {strategy}")
