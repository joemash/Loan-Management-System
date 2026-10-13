"""Loan lifecycle use cases (Java ``ApplyLoanService``, ``ApproveLoanService``, ``DisburseLoanService``,
``RepayLoanService``, ``LoanSummaryService``, ``LoanApplicationValidator``, ``AdminLoanQueryService``)."""

import uuid
from decimal import Decimal

from injector import inject

from src.application.domain import loan_product_rules as rules
from src.application.domain.audit import AuditLog
from src.application.domain.customer import Customer
from src.application.domain.errors import DomainValidationError, NotFoundError
from src.application.domain.ledger import (
    ACCOUNT_CUSTOMER,
    ACCOUNT_LOAN,
    REFERENCE_DISBURSEMENT,
    REFERENCE_REPAYMENT,
    LedgerAccount,
    LedgerEntry,
)
from src.application.domain.loan import Loan, LoanStatus, LoanSummary
from src.application.domain.loan_product import LoanProduct
from src.application.domain.repayment import Payment
from src.application.domain.schedule import RoutingScheduleGenerator
from src.application.ports.pagination import Page, PageQuery
from src.application.ports.services import IClock
from src.application.ports.uow import IUnitOfWork
from src.application.ports.usecases import ILoanUseCases, LoanDetail


class LoanUseCases(ILoanUseCases):
    @inject
    def __init__(self, uow: IUnitOfWork, clock: IClock, schedule_generator: RoutingScheduleGenerator):
        self.uow = uow
        self.clock = clock
        self.schedule_generator = schedule_generator

    def apply(self, customer_id: uuid.UUID, product_id: uuid.UUID, amount: Decimal) -> Loan:
        with self.uow:
            customer = self._customer(customer_id)
            if not customer.is_active:
                raise DomainValidationError("Customer is not active")
            product = self._product(product_id)
            rules.validate_strategies(product)
            rules.validate_config(product)
            rules.validate_principal(product, amount)
            if amount > customer.available_credit:
                raise DomainValidationError(
                    f"Principal exceeds available credit: {amount} > {customer.available_credit}"
                )
            loan = Loan.apply(customer_id, product_id, amount, self.clock.now())
            self.uow.loans.add(loan)
        return loan

    def approve(self, loan_id: uuid.UUID) -> Loan:
        with self.uow:
            loan = self._loan(loan_id)
            loan.approve()
        return loan

    def disburse(self, loan_id: uuid.UUID) -> None:
        """Builds schedules from the product, reserves the contractual total on the customer's credit line,
        posts the ledger entry and disburses on today's business date. Idempotent once disbursed."""
        with self.uow:
            loan = self._loan(loan_id)
            if loan.status == LoanStatus.DISBURSED:
                return
            today, now = self.clock.today(), self.clock.now()
            product = self._product(loan.product_id)
            plan = self.schedule_generator.generate(loan, today, product, now)
            rules.validate_strategies(product)
            rules.validate_config(product)
            last_due = max((s.due_date for s in plan.schedules), default=today)
            rules.validate_tenure_days(product, max(0, (last_due - today).days))

            self._customer_for_update(loan.customer_id).reserve_credit(plan.total_amount)
            loan.disburse(plan.disbursement_date, plan.total_amount, plan.schedules, now)
            self._post(ACCOUNT_LOAN, ACCOUNT_CUSTOMER, loan, loan.principal, REFERENCE_DISBURSEMENT)

    def repay(self, loan_id: uuid.UUID, amount: Decimal, external_reference: str) -> None:
        """Idempotent on ``external_reference``. Order: persist payment → allocate → payment event → ledger →
        release credit on closure → audit; events publish after commit."""
        with self.uow:
            if self.uow.payments.exists_by_external_reference(external_reference):
                return
            loan = self._loan(loan_id)
            now = self.clock.now()
            self.uow.payments.add(Payment.create(loan_id, amount, now, external_reference))

            loan.apply_repayment(amount)
            loan.register_payment_received(amount, external_reference, now)
            self._post(ACCOUNT_CUSTOMER, ACCOUNT_LOAN, loan, amount, REFERENCE_REPAYMENT)

            if loan.status == LoanStatus.CLOSED:
                self._customer_for_update(loan.customer_id).release_credit(loan.credit_to_release)

            self.uow.audit.add(
                AuditLog.record(
                    "LOAN",
                    loan_id,
                    "REPAYMENT",
                    {"amount": format(amount, "f"), "externalReference": external_reference},
                    now,
                )
            )

    def summary(self, loan_id: uuid.UUID) -> LoanSummary:
        with self.uow:
            return self._loan(loan_id).summary()

    def detail(self, loan_id: uuid.UUID) -> LoanDetail:
        with self.uow:
            loan = self._loan(loan_id)
            return LoanDetail(
                loan=loan,
                schedules=sorted(loan.schedules, key=lambda s: s.due_date),
                summary=loan.summary(),
                payments=self.uow.payments.list_for_loan(loan_id),
            )

    def list(
        self, query: PageQuery, customer_id: uuid.UUID | None = None, status: str | None = None
    ) -> Page[Loan]:
        parsed = None
        if status and status.strip():
            try:
                parsed = LoanStatus(status.strip().upper())
            except ValueError:
                raise DomainValidationError(f"Invalid loan status: {status}") from None
        with self.uow:
            return self.uow.loans.list(query, customer_id=customer_id, status=parsed)

    # --- helpers -------------------------------------------------------------------------------------

    def _loan(self, loan_id: uuid.UUID) -> Loan:
        loan = self.uow.loans.get(loan_id)
        if loan is None:
            raise NotFoundError(f"Loan not found: {loan_id}")
        return loan

    def _product(self, product_id: uuid.UUID) -> LoanProduct:
        product = self.uow.products.get(product_id)
        if product is None:
            raise NotFoundError(f"Loan product not found: {product_id}")
        return product

    def _customer(self, customer_id: uuid.UUID) -> Customer:
        customer = self.uow.customers.get(customer_id)
        if customer is None:
            raise NotFoundError(f"Customer not found: {customer_id}")
        return customer

    def _customer_for_update(self, customer_id: uuid.UUID) -> Customer:
        customer = self.uow.customers.get_for_update(customer_id)
        if customer is None:
            raise NotFoundError(f"Customer not found: {customer_id}")
        return customer

    def _post(
        self, debit_type: str, credit_type: str, loan: Loan, amount: Decimal, reference_type: str
    ) -> None:
        """Double-entry posting between the customer and loan accounts (opened on first use)."""
        refs = {ACCOUNT_CUSTOMER: loan.customer_id, ACCOUNT_LOAN: loan.id}
        debit = self._account(debit_type, refs[debit_type])
        credit = self._account(credit_type, refs[credit_type])
        self.uow.ledger.add_entry(
            LedgerEntry.post(debit, credit, amount, reference_type, loan.id, self.clock.now())
        )

    def _account(self, account_type: str, reference_id: uuid.UUID) -> LedgerAccount:
        account = self.uow.ledger.find_account(account_type, reference_id)
        if account is None:
            account = LedgerAccount.open(account_type, reference_id, self.clock.now())
            self.uow.ledger.add_account(account)
        return account
