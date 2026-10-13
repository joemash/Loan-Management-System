import uuid

from fastapi import APIRouter, Depends, Response, status

from src.adapters.web.dependencies import Inject
from src.adapters.web.schemas import ApplyLoanRequest, LoanResponse, LoanSummaryResponse, RepayLoanRequest
from src.adapters.web.security import require_authenticated
from src.application.ports.usecases import ILoanUseCases

router = APIRouter(prefix="/loans", tags=["loans"], dependencies=[Depends(require_authenticated)])


@router.post(
    "/apply",
    status_code=status.HTTP_201_CREATED,
    response_model=LoanResponse,
    summary="Create a loan (apply)",
    description="Creates a loan application in CREATED status after validating customer, product and credit.",
)
def apply(body: ApplyLoanRequest, loans: ILoanUseCases = Inject(ILoanUseCases)):
    return loans.apply(body.customer_id, body.product_id, body.amount)


@router.post("/{loan_id}/approve", response_model=LoanResponse, summary="Underwriting: CREATED → APPROVED")
def approve(loan_id: uuid.UUID, loans: ILoanUseCases = Inject(ILoanUseCases)):
    return loans.approve(loan_id)


@router.post("/{loan_id}/disburse", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def disburse(loan_id: uuid.UUID, loans: ILoanUseCases = Inject(ILoanUseCases)):
    loans.disburse(loan_id)


@router.post(
    "/{loan_id}/repay",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Record a payment; idempotent on externalReference",
)
def repay(loan_id: uuid.UUID, body: RepayLoanRequest, loans: ILoanUseCases = Inject(ILoanUseCases)):
    loans.repay(loan_id, body.amount, body.external_reference)


@router.get("/{loan_id}/summary", response_model=LoanSummaryResponse)
def summary(loan_id: uuid.UUID, loans: ILoanUseCases = Inject(ILoanUseCases)):
    return loans.summary(loan_id)
