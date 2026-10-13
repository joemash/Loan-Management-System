"""Loan product constraints (Java ``LoanProductRulesTest``) plus product define/revise."""

from datetime import datetime
from decimal import Decimal

import pytest

from src.application.domain import loan_product_rules as rules
from src.application.domain.errors import DomainValidationError
from src.application.domain.loan_product import LoanProduct

NOW = datetime(2026, 1, 1, 9, 0)


def _product(interest="NONE", repayment="EQUAL_INSTALLMENTS", fee="NONE", config=None) -> LoanProduct:
    return LoanProduct(
        interest_strategy=interest, repayment_strategy=repayment, fee_strategy=fee, config=config
    )


def test_validate_principal_rejects_below_min():
    p = LoanProduct(min_amount=Decimal("100.00"))
    with pytest.raises(DomainValidationError, match="minimum"):
        rules.validate_principal(p, Decimal("50.00"))


def test_validate_tenure_days_rejects_above_max():
    p = LoanProduct(max_tenure_days=30)
    with pytest.raises(DomainValidationError, match="maximum"):
        rules.validate_tenure_days(p, 400)


def test_validate_config_rejects_negative_installments():
    with pytest.raises(DomainValidationError, match="installments"):
        rules.validate_config(_product(config={"installments": -1}))


def test_validate_config_accepts_valid_installments_and_apr():
    rules.validate_config(_product(interest="SIMPLE_APR", config={"installments": 6, "apr": 0.05}))


def test_validate_strategies_rejects_unknown_interest_strategy():
    with pytest.raises(DomainValidationError, match="Unsupported interestStrategy"):
        rules.validate_strategies(_product(interest="MAGIC"))


def test_validate_config_rejects_simple_apr_without_apr():
    with pytest.raises(DomainValidationError, match="SIMPLE_APR requires config.apr"):
        rules.validate_config(_product(interest="SIMPLE_APR", config={"installments": 6}))


def test_validate_config_rejects_negative_origination_fee():
    product = _product(fee="FLAT_ORIGINATION", config={"installments": 6, "origination_fee": -1})
    with pytest.raises(DomainValidationError, match="origination_fee"):
        rules.validate_config(product)


def test_validate_config_rejects_unknown_config_keys():
    with pytest.raises(DomainValidationError, match="unsupported keys"):
        rules.validate_config(_product(config={"installments": 6, "unexpected": True}))


def test_validate_config_rejects_non_positive_installment_period_months():
    with pytest.raises(DomainValidationError, match="installment_period_months"):
        rules.validate_config(_product(config={"installments": 6, "installment_period_months": 0}))


def test_define_product_normalizes_strategies_and_defaults_fee():
    product = rules.define_product(
        name="  Six month  ",
        interest_strategy="simple_apr",
        repayment_strategy="equal_installments",
        fee_strategy=None,
        min_amount=None,
        max_amount=None,
        min_tenure_days=None,
        max_tenure_days=None,
        config={"installments": 6, "apr": 0.1},
        now=NOW,
    )
    assert product.name == "Six month"
    assert (product.interest_strategy, product.repayment_strategy, product.fee_strategy) == (
        "SIMPLE_APR",
        "EQUAL_INSTALLMENTS",
        "NONE",
    )
    assert product.created_at == NOW


def test_define_product_rejects_inverted_bounds():
    with pytest.raises(DomainValidationError, match="minAmount must be <= maxAmount"):
        rules.define_product(
            name="x",
            interest_strategy="NONE",
            repayment_strategy="EQUAL_INSTALLMENTS",
            fee_strategy=None,
            min_amount=Decimal("10"),
            max_amount=Decimal("5"),
            min_tenure_days=None,
            max_tenure_days=None,
            config=None,
            now=NOW,
        )


def test_revise_product_replaces_config_and_ignores_none():
    product = _product(interest="SIMPLE_APR", config={"installments": 6, "apr": 0.1})
    product.name = "Old"
    rules.revise_product(product, name=None, interest_strategy="none", config={"installments": 4})
    assert product.name == "Old"
    assert product.interest_strategy == "NONE"
    assert product.config == {"installments": 4}
