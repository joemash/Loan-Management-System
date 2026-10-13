"""``LoanApiIT`` cases not covered by ``test_loan_api.py``."""

from tests.conftest import make_customer, make_product


def test_apply_and_approve_return_loan_status(client, session, user_headers):
    customer = make_customer(session)
    product = make_product(session)
    res = client.post(
        "/loans/apply",
        json={"customerId": str(customer.id), "productId": str(product.id), "amount": 1000.00},
        headers=user_headers,
    )
    assert res.status_code == 201
    assert res.json()["status"] == "CREATED"
    res = client.post(f"/loans/{res.json()['id']}/approve", headers=user_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "APPROVED"


def test_apply_returns_400_when_amount_exceeds_available_credit(client, session, user_headers):
    broke = make_customer(session, credit_limit="100.00")
    broke.available_credit = broke.available_credit / 2
    session.commit()
    product = make_product(session)
    res = client.post(
        "/loans/apply",
        json={"customerId": str(broke.id), "productId": str(product.id), "amount": 200.00},
        headers=user_headers,
    )
    assert res.status_code == 400
    assert "error" in res.json()


def test_get_customer_returns_profile(client, session, user_headers):
    customer = make_customer(session)
    res = client.get(f"/customers/{customer.id}", headers=user_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == customer.email
    assert body["availableCredit"] == 50000
    assert body["creditLimit"] == 50000


def test_get_summary_returns_aggregates_for_fresh_disbursement(client, session, user_headers):
    customer = make_customer(session)
    product = make_product(session)
    res = client.post(
        "/loans/apply",
        json={"customerId": str(customer.id), "productId": str(product.id), "amount": 1000.00},
        headers=user_headers,
    )
    loan_id = res.json()["id"]
    assert client.post(f"/loans/{loan_id}/approve", headers=user_headers).status_code == 200
    assert client.post(f"/loans/{loan_id}/disburse", headers=user_headers).status_code == 204

    res = client.get(f"/loans/{loan_id}/summary", headers=user_headers)
    assert res.status_code == 200
    assert res.json() == {"principal": 1000, "paid": 0, "remaining": 1000, "overdue": 0, "penalties": 0}


def test_core_endpoints_require_authentication(client, session):
    customer = make_customer(session)
    assert client.get(f"/customers/{customer.id}").status_code == 401


def test_actuator_info_and_prometheus_are_public(client):
    assert client.get("/actuator/info").json() == {"app": {"name": "lms"}}
    assert client.get("/actuator/health/liveness").json() == {"status": "UP"}
    metrics = client.get("/actuator/prometheus").text
    assert "lms_notifications_unread_count" in metrics
