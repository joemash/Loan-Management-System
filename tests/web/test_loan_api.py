"""End-to-end loan lifecycle over HTTP (Java ``LoanApiIT`` / ``RepayLoanServiceIT``)."""

from decimal import Decimal

from sqlalchemy import func, select

from src.application.domain.audit import AuditLog
from src.application.domain.ledger import LedgerEntry
from src.application.domain.notification import Notification, NotificationOutbox
from src.application.domain.repayment import Payment, RepaymentSchedule
from tests.conftest import make_customer, make_product


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def _disbursed_loan(client, session, user_headers, admin_headers, amount=100.00):
    customer = make_customer(session)
    product = make_product(session)
    res = client.post(
        "/loans/apply",
        json={"customerId": str(customer.id), "productId": str(product.id), "amount": amount},
        headers=user_headers,
    )
    assert res.status_code == 201, res.text
    loan_id = res.json()["id"]
    assert client.post(f"/loans/{loan_id}/approve", headers=admin_headers).status_code == 200
    assert client.post(f"/loans/{loan_id}/disburse", headers=admin_headers).status_code == 204
    return customer, product, loan_id


def test_apply_approve_disburse_persists_schedules(client, session, user_headers, admin_headers):
    customer, _, loan_id = _disbursed_loan(client, session, user_headers, admin_headers)

    assert _count(session, RepaymentSchedule) == 2
    assert _count(session, LedgerEntry) == 1
    session.expire_all()
    session.refresh(customer)
    assert customer.available_credit == Decimal("49900.00")

    loan = client.get(f"/admin/loans/{loan_id}", headers=admin_headers).json()["loan"]
    assert loan["status"] == "DISBURSED"
    assert loan["totalAmount"] == 100.0

    # Notification + outbox row written after commit by the event listener.
    assert session.scalars(select(Notification.type)).all() == ["LOAN_DISBURSED"]
    assert _count(session, NotificationOutbox) == 1


def test_disburse_is_idempotent(client, session, user_headers, admin_headers):
    customer, _, loan_id = _disbursed_loan(client, session, user_headers, admin_headers)
    assert client.post(f"/loans/{loan_id}/disburse", headers=admin_headers).status_code == 204
    assert _count(session, RepaymentSchedule) == 2
    assert _count(session, LedgerEntry) == 1
    session.refresh(customer)
    assert customer.available_credit == Decimal("49900.00")


def test_repay_is_idempotent_on_external_reference_and_closes_loan(
    client, session, user_headers, admin_headers
):
    customer, _, loan_id = _disbursed_loan(client, session, user_headers, admin_headers)

    body = {"amount": 50.00, "externalReference": "pay-1"}
    assert client.post(f"/loans/{loan_id}/repay", json=body, headers=user_headers).status_code == 204
    assert client.post(f"/loans/{loan_id}/repay", json=body, headers=user_headers).status_code == 204
    assert _count(session, Payment) == 1

    summary = client.get(f"/loans/{loan_id}/summary", headers=user_headers).json()
    assert summary == {"principal": 100.0, "paid": 50.0, "remaining": 50.0, "overdue": 0.0, "penalties": 0.0}

    body = {"amount": 50.00, "externalReference": "pay-2"}
    assert client.post(f"/loans/{loan_id}/repay", json=body, headers=user_headers).status_code == 204

    detail = client.get(f"/admin/loans/{loan_id}", headers=admin_headers).json()
    assert detail["loan"]["status"] == "CLOSED"
    assert [p["externalReference"] for p in detail["payments"]] == ["pay-2", "pay-1"]
    assert all(s["status"] == "PAID" for s in detail["schedules"])

    session.refresh(customer)
    assert customer.available_credit == Decimal("50000.00")
    assert _count(session, LedgerEntry) == 3
    assert _count(session, AuditLog) == 2


def test_overpayment_is_rejected_and_rolled_back(client, session, user_headers, admin_headers):
    _, _, loan_id = _disbursed_loan(client, session, user_headers, admin_headers)
    res = client.post(
        f"/loans/{loan_id}/repay",
        json={"amount": 150.00, "externalReference": "too-much"},
        headers=user_headers,
    )
    assert res.status_code == 400
    assert "exceeds remaining obligation" in res.json()["error"]
    assert _count(session, Payment) == 0


def test_approve_twice_conflicts(client, session, user_headers, admin_headers):
    _, _, loan_id = _disbursed_loan(client, session, user_headers, admin_headers)
    res = client.post(f"/loans/{loan_id}/approve", headers=admin_headers)
    assert res.status_code == 409
    assert "only be approved when CREATED" in res.json()["error"]


def test_apply_validation_errors(client, session, user_headers):
    customer = make_customer(session)
    product = make_product(session, min_amount=Decimal("100.00"))
    res = client.post(
        "/loans/apply",
        json={"customerId": str(customer.id), "productId": str(product.id), "amount": 50},
        headers=user_headers,
    )
    assert res.status_code == 400
    assert "below product minimum" in res.json()["error"]

    res = client.post("/loans/apply", json={"customerId": str(customer.id)}, headers=user_headers)
    assert res.status_code == 400
    assert res.json()["error"].endswith("must not be null")


def test_unknown_loan_is_404(client, user_headers):
    res = client.get("/loans/00000000-0000-0000-0000-000000000000/summary", headers=user_headers)
    assert res.status_code == 404
    assert res.json() == {"error": "Loan not found: 00000000-0000-0000-0000-000000000000"}


def test_security_rules(client, user_headers, admin_headers):
    assert client.get("/admin/loans").json() == {"error": "Authentication is required"}
    assert client.get("/admin/loans").status_code == 401
    res = client.get("/admin/loans", headers=user_headers)
    assert res.status_code == 403
    assert res.json() == {"error": "You are not allowed to access this resource"}
    res = client.get("/admin/loans", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json() == {"error": "Invalid or expired bearer token"}
    assert client.get("/admin/loans", headers=admin_headers).status_code == 200
    assert client.get("/actuator/health").status_code == 200
    assert client.get("/api-docs").status_code == 200
    swagger = client.get("/swagger-ui")
    assert swagger.status_code == 200
    # StandaloneLayout (API group selector) needs the standalone preset script.
    assert "swagger-ui-standalone-preset.js" in swagger.text
    assert '"urls.primaryName": "all"' in swagger.text  # every endpoint visible by default
    assert client.get("/api-docs/admin").status_code == 200
