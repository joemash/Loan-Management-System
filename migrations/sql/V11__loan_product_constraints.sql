-- Strengthen loan_products invariants at the database layer.
ALTER TABLE loan_products
    ADD CONSTRAINT chk_loan_products_amount_bounds
        CHECK (min_amount IS NULL OR max_amount IS NULL OR min_amount <= max_amount),
    ADD CONSTRAINT chk_loan_products_tenure_bounds
        CHECK (min_tenure_days IS NULL OR max_tenure_days IS NULL OR min_tenure_days <= max_tenure_days),
    ADD CONSTRAINT chk_loan_products_interest_strategy
        CHECK (UPPER(interest_strategy) IN ('NONE', 'SIMPLE_APR')),
    ADD CONSTRAINT chk_loan_products_repayment_strategy
        CHECK (UPPER(repayment_strategy) IN ('EQUAL_INSTALLMENTS', 'EQUAL_PRINCIPAL_INSTALLMENTS')),
    ADD CONSTRAINT chk_loan_products_fee_strategy
        CHECK (fee_strategy IS NULL OR UPPER(fee_strategy) IN ('NONE', 'FLAT_ORIGINATION'));
