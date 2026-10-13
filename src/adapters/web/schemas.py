"""Request/response schemas (camelCase JSON, same wire format as the Java API)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, PlainSerializer
from pydantic.alias_generators import to_camel

from src.application.domain.loan import LoanStatus
from src.application.domain.repayment import ScheduleStatus
from src.application.ports.pagination import Page

# --- JSON conventions -------------------------------------------------------------------------------------

# Money is serialised as a JSON number (like Jackson's BigDecimal), not as a string (Pydantic's default).
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


def _iso_instant(value: datetime) -> str:
    # Stored as naive UTC; render like Java's Instant.toString().
    return value.isoformat() + "Z" if value.tzinfo is None else value.isoformat()


Instant = Annotated[datetime, PlainSerializer(_iso_instant, return_type=str, when_used="json")]


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NotBlankStr = Annotated[str, AfterValidator(_not_blank)]


class CamelModel(BaseModel):
    """camelCase on the wire, snake_case in Python; accepts both on input."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)



class PageMetadata(BaseModel):
    size: int
    number: int
    total_elements: int
    total_pages: int

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PageResponse[T](BaseModel):
    content: list[T]
    page: PageMetadata


def to_page_response(page: Page, schema: type[BaseModel]) -> dict[str, Any]:
    return {
        "content": [schema.model_validate(item) for item in page.items],
        "page": {
            "size": page.size,
            "number": page.page,
            "totalElements": page.total,
            "totalPages": page.total_pages,
        },
    }


# --- customers ---


class CustomerResponse(CamelModel):
    id: uuid.UUID
    name: str
    email: str
    status: str
    credit_limit: Money
    available_credit: Money
    created_at: Instant
    updated_at: Instant


# --- loans ---


class ApplyLoanRequest(CamelModel):
    customer_id: uuid.UUID
    product_id: uuid.UUID
    amount: Annotated[Decimal, Field(gt=0)]


class RepayLoanRequest(CamelModel):
    amount: Annotated[Decimal, Field(gt=0)]
    external_reference: NotBlankStr


class LoanResponse(CamelModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    product_id: uuid.UUID
    principal: Money
    status: LoanStatus
    total_amount: Money | None
    disbursement_date: date | None


class LoanSummaryResponse(CamelModel):
    principal: Money
    paid: Money
    remaining: Money
    overdue: Money
    penalties: Money


# --- admin: customers ---


class RegisterCustomerRequest(CamelModel):
    name: NotBlankStr
    email: EmailStr
    credit_limit: Annotated[Decimal, Field(ge=Decimal("0.01"))]
    status: str | None = None


class UpdateCustomerRequest(CamelModel):
    """Partial update: ``null``/absent fields are left unchanged."""

    name: str | None = None
    status: str | None = None
    credit_limit: Decimal | None = None


# --- loan products ---


class CreateLoanProductRequest(CamelModel):
    name: NotBlankStr
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    min_tenure_days: int | None = None
    max_tenure_days: int | None = None
    interest_strategy: Annotated[NotBlankStr, Field(description="NONE | SIMPLE_APR")]
    repayment_strategy: Annotated[
        NotBlankStr, Field(description="EQUAL_INSTALLMENTS | EQUAL_PRINCIPAL_INSTALLMENTS")
    ]
    fee_strategy: Annotated[str | None, Field(description="NONE | FLAT_ORIGINATION (default NONE)")] = None
    config: Annotated[
        dict[str, Any] | None,
        Field(description="Keys: installments, installment_period_months, apr, origination_fee"),
    ] = None


class UpdateLoanProductRequest(CamelModel):
    """Partial update; a provided ``config`` replaces the whole config object."""

    name: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    min_tenure_days: int | None = None
    max_tenure_days: int | None = None
    interest_strategy: str | None = None
    repayment_strategy: str | None = None
    fee_strategy: str | None = None
    config: dict[str, Any] | None = None


class AdminLoanProductResponse(CamelModel):
    id: uuid.UUID
    name: str
    min_amount: Money | None
    max_amount: Money | None
    min_tenure_days: int | None
    max_tenure_days: int | None
    interest_strategy: str
    repayment_strategy: str
    fee_strategy: str | None
    config: dict[str, Any] | None
    created_at: Instant


# --- loans ---


class AdminLoanListItem(CamelModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    product_id: uuid.UUID
    principal: Money
    status: LoanStatus
    total_amount: Money | None
    disbursement_date: date | None


class AdminScheduleRow(CamelModel):
    id: uuid.UUID
    due_date: date
    amount_due: Money
    amount_paid: Money | None
    status: ScheduleStatus
    penalty_accrued: Money
    remaining_due: Money


class AdminPaymentRow(CamelModel):
    id: uuid.UUID
    amount: Money
    payment_date: datetime
    external_reference: str | None


class AdminLoanDetailResponse(CamelModel):
    loan: LoanResponse
    summary: LoanSummaryResponse
    schedules: list[AdminScheduleRow]
    payments: list[AdminPaymentRow]


# --- notifications ---


class AdminNotificationResponse(CamelModel):
    id: uuid.UUID
    event_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    type: str | None
    channel: str | None
    payload: dict[str, Any] | None
    delivery_status: str | None
    ui_status: str
    attempt_count: int
    last_error: str | None
    next_retry_at: Instant | None
    sent_at: Instant | None
    read_at: Instant | None
    created_at: Instant
    updated_at: Instant
