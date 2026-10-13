"""Admin endpoints over HTTP (Java ``AdminApiTest``)."""

import uuid

PRODUCT_JSON = {
    "name": "Admin Product",
    "interestStrategy": "NONE",
    "repaymentStrategy": "EQUAL_INSTALLMENTS",
    "feeStrategy": "NONE",
    "config": {"installments": 2},
}


def _create_customer(client, admin_headers, **overrides):
    body = {"name": "Admin Customer", "email": f"admin-{uuid.uuid4()}@example.com", "creditLimit": 50000}
    body.update(overrides)
    res = client.post("/admin/customers", json=body, headers=admin_headers)
    assert res.status_code == 201, res.text
    return res.json()


def _create_product(client, admin_headers, **overrides):
    res = client.post("/admin/loan-products", json={**PRODUCT_JSON, **overrides}, headers=admin_headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_admin_creates_customer_and_product_then_loan_flow_and_admin_lists_and_detail(
    client, admin_headers, user_headers
):
    customer = _create_customer(client, admin_headers, status="ACTIVE")
    assert customer["id"]
    assert customer["availableCredit"] == 50000
    customer_id = customer["id"]
    product_id = _create_product(client, admin_headers)

    res = client.post(
        "/loans/apply",
        json={"customerId": customer_id, "productId": product_id, "amount": 1000.00},
        headers=user_headers,
    )
    assert res.status_code == 201, res.text
    loan_id = res.json()["id"]

    assert client.post(f"/loans/{loan_id}/approve", headers=user_headers).status_code == 200
    assert client.post(f"/loans/{loan_id}/disburse", headers=user_headers).status_code == 204
    res = client.post(
        f"/loans/{loan_id}/repay",
        json={"amount": 400, "externalReference": "admin-txn-1"},
        headers=user_headers,
    )
    assert res.status_code == 204, res.text

    res = client.get("/admin/loans", params={"customerId": customer_id}, headers=admin_headers)
    assert res.status_code == 200
    content = res.json()["content"]
    assert len(content) == 1
    assert content[0]["id"] == loan_id

    res = client.get(f"/admin/loans/{loan_id}", headers=admin_headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["loan"]["status"] == "DISBURSED"
    assert detail["summary"]["principal"] == 1000
    assert len(detail["schedules"]) == 2
    assert [s["remainingDue"] for s in detail["schedules"]] == [100, 500]
    assert len(detail["payments"]) == 1
    assert detail["payments"][0]["externalReference"] == "admin-txn-1"

    res = client.get("/admin/customers", params={"size": 5}, headers=admin_headers)
    assert res.status_code == 200
    assert isinstance(res.json()["content"], list)

    res = client.get("/admin/loan-products", params={"size": 5}, headers=admin_headers)
    assert res.status_code == 200
    assert isinstance(res.json()["content"], list)

    res = client.get("/admin/notifications", params={"size": 10}, headers=admin_headers)
    assert res.status_code == 200
    notifications = res.json()["content"]
    # LOAN_DISBURSED + PAYMENT_RECEIVED are recorded synchronously after commit.
    assert len(notifications) == 2
    notification_id = notifications[0]["id"]
    res = client.get(f"/admin/notifications/{notification_id}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["id"] == notification_id
    res = client.post(f"/admin/notifications/{notification_id}/read", headers=admin_headers)
    assert res.status_code == 204
    res = client.get("/admin/notifications", params={"uiStatus": "read"}, headers=admin_headers)
    assert [n["id"] for n in res.json()["content"]] == [notification_id]


def test_register_duplicate_email_returns_400(client, admin_headers):
    body = {"name": "A", "email": f"dup-{uuid.uuid4()}@example.com", "creditLimit": 100}
    assert client.post("/admin/customers", json=body, headers=admin_headers).status_code == 201
    res = client.post("/admin/customers", json=body, headers=admin_headers)
    assert res.status_code == 400
    assert "error" in res.json()


def test_invalid_loan_status_filter_returns_400(client, admin_headers):
    res = client.get("/admin/loans", params={"status": "NOT_A_STATUS"}, headers=admin_headers)
    assert res.status_code == 400
    assert res.json() == {"error": "Invalid loan status: NOT_A_STATUS"}


def test_patch_customer_and_patch_loan_product_work(client, admin_headers):
    customer = _create_customer(
        client, admin_headers, name="Patch Customer", creditLimit=5000, status="ACTIVE"
    )

    res = client.patch(
        f"/admin/customers/{customer['id']}",
        json={"status": "SUSPENDED", "creditLimit": 7000},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "SUSPENDED"
    assert res.json()["creditLimit"] == 7000

    product_id = _create_product(client, admin_headers, name="Patch Product")

    res = client.patch(
        f"/admin/loan-products/{product_id}",
        json={
            "name": "Patch Product v2",
            "interestStrategy": "SIMPLE_APR",
            "feeStrategy": "FLAT_ORIGINATION",
            "config": {"installments": 6, "apr": 0.12, "origination_fee": 15},
        },
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Patch Product v2"
    assert body["interestStrategy"] == "SIMPLE_APR"
    assert body["feeStrategy"] == "FLAT_ORIGINATION"
    assert body["config"]["installments"] == 6

    res = client.patch(
        f"/admin/loan-products/{product_id}",
        json={"interestStrategy": "NONE", "feeStrategy": "NONE", "config": {"installments": 4}},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    config = res.json()["config"]
    assert config["installments"] == 4
    assert "apr" not in config
    assert "origination_fee" not in config


def test_patch_requires_at_least_one_field(client, admin_headers):
    customer = _create_customer(client, admin_headers)
    res = client.patch(f"/admin/customers/{customer['id']}", json={}, headers=admin_headers)
    assert res.status_code == 400
    product_id = _create_product(client, admin_headers)
    res = client.patch(f"/admin/loan-products/{product_id}", json={}, headers=admin_headers)
    assert res.json() == {"error": "At least one field must be provided"}


def test_admin_endpoints_require_admin_role(client, user_headers):
    assert client.get("/admin/loans").status_code == 401
    assert client.get("/admin/loans", headers=user_headers).status_code == 403
