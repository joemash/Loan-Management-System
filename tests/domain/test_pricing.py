"""Interest and fee strategies (Java ``InterestFinanceCalculatorTest`` and ``ProductFeeCalculatorTest``)."""

from decimal import Decimal

import pytest

from src.application.domain import pricing
from src.application.domain.errors import DomainValidationError
from src.application.domain.loan_product import LoanProduct

# --- InterestFinanceCalculatorTest -------------------------------------------------------------------------


def test_interest_none_strategy_returns_zero():
    p = LoanProduct(interest_strategy="NONE")
    assert pricing.finance_charge(p, Decimal("1000.00"), 12) == Decimal("0.00")


def test_interest_simple_apr_computes_charge():
    p = LoanProduct(interest_strategy="SIMPLE_APR", config={"apr": Decimal("0.1")})
    # 1200 * 0.1 * 12/12 = 120
    assert pricing.finance_charge(p, Decimal("1200.00"), 12) == Decimal("120.00")


def test_interest_simple_apr_requires_apr_in_config():
    p = LoanProduct(interest_strategy="SIMPLE_APR", config={})
    with pytest.raises(DomainValidationError, match="apr"):
        pricing.finance_charge(p, Decimal("100.00"), 12)


# --- ProductFeeCalculatorTest ------------------------------------------------------------------------------


def test_fee_none_strategy_returns_zero():
    p = LoanProduct(fee_strategy="NONE")
    assert pricing.upfront_fees(p) == Decimal("0.00")


def test_fee_flat_origination_reads_config():
    p = LoanProduct(fee_strategy="FLAT_ORIGINATION", config={"origination_fee": 25.5})
    assert pricing.upfront_fees(p) == Decimal("25.50")


def test_fee_flat_origination_requires_fee():
    p = LoanProduct(fee_strategy="FLAT_ORIGINATION", config={})
    with pytest.raises(DomainValidationError, match="origination_fee"):
        pricing.upfront_fees(p)
