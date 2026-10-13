"""``/admin/**`` endpoints; every route requires ``ROLE_ADMIN``."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from src.adapters.web.dependencies import Inject, PageDep
from src.adapters.web.schemas import (
    AdminLoanDetailResponse,
    AdminLoanListItem,
    AdminLoanProductResponse,
    AdminNotificationResponse,
    AdminPaymentRow,
    AdminScheduleRow,
    CreateLoanProductRequest,
    CustomerResponse,
    LoanResponse,
    LoanSummaryResponse,
    PageResponse,
    RegisterCustomerRequest,
    UpdateCustomerRequest,
    UpdateLoanProductRequest,
    to_page_response,
)
from src.adapters.web.security import require_admin
from src.application.domain.errors import DomainValidationError
from src.application.ports.repo import NotificationFilter
from src.application.ports.usecases import (
    ICustomerUseCases,
    ILoanProductUseCases,
    ILoanUseCases,
    INotificationUseCases,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

Customers = Annotated[ICustomerUseCases, Inject(ICustomerUseCases)]
Products = Annotated[ILoanProductUseCases, Inject(ILoanProductUseCases)]
Loans = Annotated[ILoanUseCases, Inject(ILoanUseCases)]
Notifications = Annotated[INotificationUseCases, Inject(INotificationUseCases)]

# --- customers --------------------------------------------------------------------------------------------


@router.get("/customers", response_model=PageResponse[CustomerResponse], tags=["admin-customers"])
def list_customers(customers: Customers, page: PageDep):
    return to_page_response(customers.list(page), CustomerResponse)


@router.get("/customers/{customer_id}", response_model=CustomerResponse, tags=["admin-customers"])
def get_customer(customer_id: uuid.UUID, customers: Customers):
    return customers.get(customer_id)


@router.post(
    "/customers",
    status_code=status.HTTP_201_CREATED,
    response_model=CustomerResponse,
    tags=["admin-customers"],
)
def create_customer(body: RegisterCustomerRequest, customers: Customers):
    return customers.register(body.name, body.email, body.credit_limit, body.status)


@router.patch("/customers/{customer_id}", response_model=CustomerResponse, tags=["admin-customers"])
def patch_customer(customer_id: uuid.UUID, body: UpdateCustomerRequest, customers: Customers):
    if body.name is None and body.status is None and body.credit_limit is None:
        raise DomainValidationError("At least one of name, status, creditLimit must be provided")
    return customers.update(customer_id, body.name, body.status, body.credit_limit)


# --- loans ------------------------------------------------------------------------------------------------


@router.get("/loans", response_model=PageResponse[AdminLoanListItem], tags=["admin-loans"])
def list_loans(
    loans: Loans,
    page: PageDep,
    customer_id: Annotated[uuid.UUID | None, Query(alias="customerId")] = None,
    loan_status: Annotated[str | None, Query(alias="status")] = None,
):
    return to_page_response(loans.list(page, customer_id=customer_id, status=loan_status), AdminLoanListItem)


@router.get("/loans/{loan_id}", response_model=AdminLoanDetailResponse, tags=["admin-loans"])
def loan_detail(loan_id: uuid.UUID, loans: Loans):
    detail = loans.detail(loan_id)
    return AdminLoanDetailResponse(
        loan=LoanResponse.model_validate(detail.loan),
        summary=LoanSummaryResponse.model_validate(detail.summary),
        schedules=[
            AdminScheduleRow(
                id=s.id,
                due_date=s.due_date,
                amount_due=s.amount_due,
                amount_paid=s.amount_paid,
                status=s.status,
                penalty_accrued=s.penalty_accrued,
                remaining_due=s.remaining_due(),
            )
            for s in detail.schedules
        ],
        payments=[AdminPaymentRow.model_validate(p) for p in detail.payments],
    )


# --- loan products ----------------------------------------------------------------------------------------


@router.get(
    "/loan-products", response_model=PageResponse[AdminLoanProductResponse], tags=["admin-loan-products"]
)
def list_products(products: Products, page: PageDep):
    return to_page_response(products.list(page), AdminLoanProductResponse)


@router.get(
    "/loan-products/{product_id}", response_model=AdminLoanProductResponse, tags=["admin-loan-products"]
)
def get_product(product_id: uuid.UUID, products: Products):
    return products.get(product_id)


@router.post(
    "/loan-products",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminLoanProductResponse,
    tags=["admin-loan-products"],
)
def create_product(body: CreateLoanProductRequest, products: Products):
    return products.create(**body.model_dump())


@router.patch(
    "/loan-products/{product_id}", response_model=AdminLoanProductResponse, tags=["admin-loan-products"]
)
def patch_product(product_id: uuid.UUID, body: UpdateLoanProductRequest, products: Products):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise DomainValidationError("At least one field must be provided")
    return products.update(product_id, **changes)


# --- notifications ----------------------------------------------------------------------------------------


@router.get(
    "/notifications", response_model=PageResponse[AdminNotificationResponse], tags=["admin-notifications"]
)
def list_notifications(
    notifications: Notifications,
    page: PageDep,
    customer_id: Annotated[uuid.UUID | None, Query(alias="customerId")] = None,
    type_: Annotated[str | None, Query(alias="type")] = None,
    delivery_status: Annotated[str | None, Query(alias="deliveryStatus")] = None,
    ui_status: Annotated[str | None, Query(alias="uiStatus")] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query(alias="to")] = None,
):
    criteria = NotificationFilter(customer_id, type_, delivery_status, ui_status, from_, to)
    return to_page_response(notifications.search(criteria, page), AdminNotificationResponse)


@router.get(
    "/notifications/{notification_id}", response_model=AdminNotificationResponse, tags=["admin-notifications"]
)
def get_notification(notification_id: uuid.UUID, notifications: Notifications):
    return notifications.get(notification_id)


@router.post(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["admin-notifications"],
)
def mark_read(notification_id: uuid.UUID, notifications: Notifications):
    notifications.mark_read(notification_id)
