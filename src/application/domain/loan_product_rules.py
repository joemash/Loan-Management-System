"""Loan product constraints for configuration, applications and disbursement (Java ``LoanProductRules``)."""

from decimal import Decimal
from typing import Any

from src.application.domain.errors import DomainValidationError
from src.application.domain.loan_product import LoanProduct

INTEREST_NONE = "NONE"
INTEREST_SIMPLE_APR = "SIMPLE_APR"
REPAYMENT_EQUAL_INSTALLMENTS = "EQUAL_INSTALLMENTS"
REPAYMENT_EQUAL_PRINCIPAL_INSTALLMENTS = "EQUAL_PRINCIPAL_INSTALLMENTS"
FEE_NONE = "NONE"
FEE_FLAT_ORIGINATION = "FLAT_ORIGINATION"

CONFIG_INSTALLMENTS = "installments"
CONFIG_APR = "apr"
CONFIG_ORIGINATION_FEE = "origination_fee"
CONFIG_INSTALLMENT_PERIOD_MONTHS = "installment_period_months"

ALLOWED_INTEREST_STRATEGIES = (INTEREST_NONE, INTEREST_SIMPLE_APR)
ALLOWED_REPAYMENT_STRATEGIES = (REPAYMENT_EQUAL_INSTALLMENTS, REPAYMENT_EQUAL_PRINCIPAL_INSTALLMENTS)
ALLOWED_FEE_STRATEGIES = (FEE_NONE, FEE_FLAT_ORIGINATION)
ALLOWED_CONFIG_KEYS = frozenset(
    {CONFIG_INSTALLMENTS, CONFIG_APR, CONFIG_ORIGINATION_FEE, CONFIG_INSTALLMENT_PERIOD_MONTHS}
)


def is_number(value: Any) -> bool:
    """JSON numbers only (``bool`` is an ``int`` subclass in Python but not a number in JSON)."""
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def to_decimal(value: int | float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def normalize_interest_strategy(strategy: str | None) -> str:
    return _normalize_required(strategy, "interestStrategy")


def normalize_repayment_strategy(strategy: str | None) -> str:
    return _normalize_required(strategy, "repaymentStrategy")


def normalize_fee_strategy(strategy: str | None) -> str:
    if strategy is None or not strategy.strip():
        return FEE_NONE
    return strategy.strip().upper()


def validate_strategies(product: LoanProduct) -> None:
    """Whitelists strategies and writes back their normalized (upper-case) form."""
    interest = normalize_interest_strategy(product.interest_strategy)
    repayment = normalize_repayment_strategy(product.repayment_strategy)
    fee = normalize_fee_strategy(product.fee_strategy)
    _validate_allowed("interestStrategy", interest, ALLOWED_INTEREST_STRATEGIES)
    _validate_allowed("repaymentStrategy", repayment, ALLOWED_REPAYMENT_STRATEGIES)
    _validate_allowed("feeStrategy", fee, ALLOWED_FEE_STRATEGIES)
    product.interest_strategy = interest
    product.repayment_strategy = repayment
    product.fee_strategy = fee


def validate_principal(product: LoanProduct, principal: Decimal) -> None:
    if product.min_amount is not None and principal < product.min_amount:
        raise DomainValidationError(f"Principal {principal} is below product minimum {product.min_amount}")
    if product.max_amount is not None and principal > product.max_amount:
        raise DomainValidationError(f"Principal {principal} exceeds product maximum {product.max_amount}")


def validate_tenure_days(product: LoanProduct, tenure_days: int) -> None:
    """Validates inferred tenure (disbursement to last due date) against product bounds when set."""
    if product.min_tenure_days is not None and tenure_days < product.min_tenure_days:
        raise DomainValidationError(
            f"Loan tenure {tenure_days} days is below product minimum {product.min_tenure_days}"
        )
    if product.max_tenure_days is not None and tenure_days > product.max_tenure_days:
        raise DomainValidationError(
            f"Loan tenure {tenure_days} days exceeds product maximum {product.max_tenure_days}"
        )


def validate_config(product: LoanProduct) -> None:
    """Validates the JSON ``config`` against the known keys and the selected strategies."""
    config = product.config
    if config is not None:
        unknown = set(config) - ALLOWED_CONFIG_KEYS
        if unknown:
            raise DomainValidationError(f"config contains unsupported keys: {sorted(unknown)}")
    installments = _optional_int(config, CONFIG_INSTALLMENTS)
    period_months = _optional_int(config, CONFIG_INSTALLMENT_PERIOD_MONTHS)
    if period_months < 1:
        raise DomainValidationError("config.installment_period_months must be at least 1")
    if installments < 1:
        raise DomainValidationError("config.installments must be at least 1")

    interest = normalize_interest_strategy(product.interest_strategy)
    fee = normalize_fee_strategy(product.fee_strategy)

    apr = _optional_number(config, CONFIG_APR)
    if interest == INTEREST_SIMPLE_APR and apr is None:
        raise DomainValidationError("SIMPLE_APR requires config.apr")
    if apr is not None and not (Decimal(0) <= apr <= Decimal(1)):
        raise DomainValidationError("config.apr must be between 0 and 1 inclusive")

    fee_amount = _optional_number(config, CONFIG_ORIGINATION_FEE)
    if fee == FEE_FLAT_ORIGINATION and fee_amount is None:
        raise DomainValidationError("FLAT_ORIGINATION requires config.origination_fee")
    if fee_amount is not None and fee_amount < 0:
        raise DomainValidationError("config.origination_fee must be non-negative")


def config_int(config: dict[str, Any] | None, key: str) -> int:
    """Reads an integer config value, defaulting to 1 when absent (used by schedule generation)."""
    return _optional_int(config, key)


def _validate_allowed(field: str, value: str, allowed: tuple[str, ...]) -> None:
    if value.strip().upper() not in allowed:
        raise DomainValidationError(f"Unsupported {field}: {value} (allowed: {', '.join(allowed)})")


def _normalize_required(strategy: str | None, field: str) -> str:
    if strategy is None or not strategy.strip():
        raise DomainValidationError(f"{field} is required")
    return strategy.strip().upper()


def _optional_int(config: dict[str, Any] | None, key: str) -> int:
    if not config or config.get(key) is None:
        return 1
    raw = config[key]
    if not is_number(raw):
        raise DomainValidationError(f"config.{key} must be a number")
    return int(raw)


def _optional_number(config: dict[str, Any] | None, key: str) -> Decimal | None:
    if not config or config.get(key) is None:
        return None
    raw = config[key]
    if not is_number(raw):
        raise DomainValidationError(f"config.{key} must be a number")
    return to_decimal(raw)


def define_product(
    *,
    name: str,
    interest_strategy: str,
    repayment_strategy: str,
    fee_strategy: str | None,
    min_amount: Decimal | None,
    max_amount: Decimal | None,
    min_tenure_days: int | None,
    max_tenure_days: int | None,
    config: dict[str, Any] | None,
    now,
) -> LoanProduct:
    """Builds a validated product with normalized strategies."""
    _validate_bounds(min_amount, max_amount, min_tenure_days, max_tenure_days)
    product = LoanProduct(
        name=name.strip(),
        min_amount=min_amount,
        max_amount=max_amount,
        min_tenure_days=min_tenure_days,
        max_tenure_days=max_tenure_days,
        interest_strategy=normalize_interest_strategy(interest_strategy),
        repayment_strategy=normalize_repayment_strategy(repayment_strategy),
        fee_strategy=normalize_fee_strategy(fee_strategy),
        config=dict(config) if config is not None else None,
        created_at=now,
    )
    validate_strategies(product)
    validate_config(product)
    return product


def revise_product(product: LoanProduct, **changes: Any) -> None:
    """Partial update; ``None`` values are ignored. A provided ``config`` replaces the whole object."""
    changes = {k: v for k, v in changes.items() if v is not None}
    if "name" in changes:
        product.name = changes["name"].strip()
    for field in ("min_amount", "max_amount", "min_tenure_days", "max_tenure_days"):
        if field in changes:
            setattr(product, field, changes[field])
    if "interest_strategy" in changes:
        product.interest_strategy = normalize_interest_strategy(changes["interest_strategy"])
    if "repayment_strategy" in changes:
        product.repayment_strategy = normalize_repayment_strategy(changes["repayment_strategy"])
    if "fee_strategy" in changes:
        product.fee_strategy = normalize_fee_strategy(changes["fee_strategy"])
    if "config" in changes:
        product.config = dict(changes["config"])
    if product.fee_strategy is None:
        product.fee_strategy = FEE_NONE
    _validate_bounds(product.min_amount, product.max_amount, product.min_tenure_days, product.max_tenure_days)
    validate_strategies(product)
    validate_config(product)


def _validate_bounds(
    min_amount: Decimal | None, max_amount: Decimal | None, min_days: int | None, max_days: int | None
) -> None:
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise DomainValidationError("minAmount must be <= maxAmount")
    if min_days is not None and max_days is not None and min_days > max_days:
        raise DomainValidationError("minTenureDays must be <= maxTenureDays")
