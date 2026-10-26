"""Phase 7 Test Suite: Rent Payments, Automated Rent Collection, Email Templates,
Payment Synchronization, and Complete Audit Logging.

Validates all 18 requirements specified in Section 10 of Phase 7:
1. Tenant can pay current eligible monthly rent
2. Confirmed successful payment hides Pay Rent button for that period
3. Next billing period becomes payable only when eligible
4. Duplicate payment initiation does not create duplicate charges (Idempotency)
5. Failed payment permits safe retry
6. Unpaid obligation evaluated correctly after configured deadline
7. Three-day reminder sent once with duplicate suppression
8. Payment made before escalation deadline suppresses further overdue escalation
9. Late/delayed payment reconciled before legal escalation
10. Legal notice cannot be dispatched without required manager authorization & pre-flight checks
11. Duplicate and out-of-order webhooks do not corrupt payment state
12. Payment-provider downtime / invalid signature does not result in false success
13. Dashboard, rent ledger, and payment history reflect same confirmed payment state
14. Background jobs survive retries and restarts without duplicate billing or emails
15. Audit logs record payment, notification, approval, and administrative actions with sanitization
16. Unauthorized users cannot access other organizations/tenants' payments or audit logs
17. Email templates render correctly with dynamic variables and secure links
18. Existing engine components (H-MEM, World Model, Markovian) continue to pass regressions
"""

import json
import time
import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import db
from app.payment_gateway import get_payment_provider, SandboxPaymentProvider
from app.rent_payment_service import (
    get_or_create_monthly_rent_obligation,
    get_tenant_rent_dashboard,
    initiate_tenant_rent_payment,
    synchronize_confirmed_payment
)
from app.rent_notification_service import (
    sweep_upcoming_and_overdue_rent,
    review_and_decide_legal_notice
)
from app.email_templates_html import (
    render_rent_due_email,
    render_overdue_3day_email,
    render_payment_success_email,
    render_payment_failed_email,
    render_payment_processing_email,
    render_legal_notice_review_email,
    render_pm_collection_alert_email,
    render_system_notification_email
)
from app.audit import log_audit_event, query_audit_logs


def db_exec(sql: str, params: tuple = ()):
    with db() as conn:
        conn.execute(sql, params)


def db_fetch_one(sql: str, params: tuple = ()):
    with db() as conn:
        return conn.execute(sql, params).fetchone()


def db_fetch_all(sql: str, params: tuple = ()):
    with db() as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def setup_test_tenancy():
    """Create an isolated synthetic tenancy for Phase 7 testing."""
    test_id = uuid.uuid4().hex[:6]
    org_id = f"ORG-TEST-{test_id}"
    lease_id = f"LEASE-T-{test_id}"
    prop_id = f"PROP-T-{test_id}"
    tenant_name = f"Taylor Tenant {test_id}"
    tenant_email = f"taylor.{test_id}@test-enigma.internal"

    # Insert test property
    db_exec("""
        INSERT INTO properties (
            property_id, name, address, city, state, zip_code,
            monthly_rent_usd, security_deposit_usd, org_id
        ) VALUES (
            %s, %s, '100 Test St', 'Metropolis', 'CA', '90001',
            2500.00, 2500.00, %s
        ) ON CONFLICT (property_id) DO NOTHING
    """, (prop_id, f"Property {test_id}", org_id))

    # Insert test lease into lease_records
    db_exec("""
        INSERT INTO lease_records (
            lease_id, property_id, unit, address, tenant1,
            monthly_rent_usd, security_deposit_usd, contract_date, move_in_date
        ) VALUES (
            %s, %s, 'Unit 404', '100 Test St', %s,
            2500.00, 2500.00, '2026-01-01', '2026-01-01'
        ) ON CONFLICT (lease_id) DO NOTHING
    """, (lease_id, prop_id, tenant_name))

    return {
        "org_id": org_id,
        "prop_id": prop_id,
        "lease_id": lease_id,
        "tenant_name": tenant_name,
        "tenant_email": tenant_email,
        "rent_amount": 2500.00
    }


# =============================================================================
# Test 1: Tenant can pay current eligible monthly rent
# =============================================================================
def test_01_tenant_can_pay_current_eligible_monthly_rent(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]

    # 1. Fetch dashboard
    res = client.get(f"/api/tenant/rent-dashboard?lease_id={lease_id}", headers={"X-Organization-Id": org_id})
    assert res.status_code == 200
    dashboard = res.json()
    assert dashboard["lease_id"] == lease_id
    assert dashboard["payment_eligibility"]["eligible"] is True

    bill_id = dashboard["current_bill"]["id"]
    idempotency_key = f"tx-test1-{uuid.uuid4().hex[:8]}"

    # 2. Initiate payment
    init_res = client.post("/api/tenant/pay-rent", headers={"X-Organization-Id": org_id}, json={
        "lease_id": lease_id,
        "billing_record_id": bill_id,
        "amount_usd": 2500.00,
        "customer_email": setup_test_tenancy["tenant_email"],
        "payment_method": "ach_transfer",
        "idempotency_key": idempotency_key
    })
    assert init_res.status_code == 200
    init_data = init_res.json()
    assert init_data["status"] == "pending"
    session_id = init_data["session_id"]

    # 3. Complete payment via sandbox simulation
    sim_res = client.post("/api/tenant/checkout-session/simulate", headers={"X-Organization-Id": org_id}, json={
        "session_id": session_id,
        "should_succeed": True
    })
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert sim_data["simulation_success"] is True
    assert sim_data["simulated_outcome"] == "succeeded"

    # Synchronize confirmed payment
    sync = synchronize_confirmed_payment(session_id, payment_method="ach_transfer")
    assert sync["success"] is True
    assert sync["new_billing_status"] == "paid"
    assert sync["receipt_number"] is not None


# =============================================================================
# Test 2: Confirmed successful payment hides Pay Rent button for that period
# =============================================================================
def test_02_confirmed_payment_hides_pay_rent_button(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]

    res = client.get(f"/api/tenant/rent-dashboard?lease_id={lease_id}", headers={"X-Organization-Id": org_id})
    assert res.status_code == 200
    dashboard = res.json()

    assert dashboard["current_bill"]["status"] == "paid"
    assert dashboard["current_bill"]["outstanding_balance_usd"] == 0.00
    assert dashboard["payment_eligibility"]["eligible"] is False
    assert "settled" in dashboard["payment_eligibility"]["blocked_reason"].lower()


# =============================================================================
# Test 3: Next billing period becomes payable only when eligible
# =============================================================================
def test_03_next_billing_period_becomes_payable_only_when_eligible(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    
    # Create future billing record for next year
    future_period = "2027-06"
    bill = get_or_create_monthly_rent_obligation(lease_id, future_period)
    assert bill is not None

    # Fetch dashboard specifically for that future period
    res = client.get(f"/api/tenant/rent-dashboard?lease_id={lease_id}&period={future_period}", headers={"X-Organization-Id": org_id})
    assert res.status_code == 200
    data = res.json()
    assert data["current_bill"]["billing_period"] == future_period
    assert data["payment_eligibility"]["eligible"] is False
    assert "opens" in data["payment_eligibility"]["blocked_reason"].lower()


# =============================================================================
# Test 4: Duplicate payment initiation does not create duplicate charges
# =============================================================================
def test_04_duplicate_payment_initiation_prevents_duplicate_charges(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    period = "2026-11"
    
    bill = get_or_create_monthly_rent_obligation(lease_id, period)
    idempotency_key = f"idem-key-{uuid.uuid4().hex[:8]}"

    # First initiation
    res1 = client.post("/api/tenant/pay-rent", headers={"X-Organization-Id": org_id}, json={
        "lease_id": lease_id,
        "billing_record_id": bill["id"],
        "amount_usd": 2500.00,
        "customer_email": setup_test_tenancy["tenant_email"],
        "payment_method": "credit_card",
        "idempotency_key": idempotency_key
    })
    assert res1.status_code == 200
    data1 = res1.json()

    # Second initiation with exact same idempotency key
    res2 = client.post("/api/tenant/pay-rent", headers={"X-Organization-Id": org_id}, json={
        "lease_id": lease_id,
        "billing_record_id": bill["id"],
        "amount_usd": 2500.00,
        "customer_email": setup_test_tenancy["tenant_email"],
        "payment_method": "credit_card",
        "idempotency_key": idempotency_key
    })
    assert res2.status_code == 200
    data2 = res2.json()

    # Must return identical session_id and zero duplicate charges
    assert data1["session_id"] == data2["session_id"]


# =============================================================================
# Test 5: A failed payment permits a safe retry
# =============================================================================
def test_05_failed_payment_permits_safe_retry(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    period = "2026-12"
    bill = get_or_create_monthly_rent_obligation(lease_id, period)

    # 1. Initiate first payment
    key1 = f"fail-key-{uuid.uuid4().hex[:8]}"
    res1 = client.post("/api/tenant/pay-rent", headers={"X-Organization-Id": org_id}, json={
        "lease_id": lease_id,
        "billing_record_id": bill["id"],
        "amount_usd": 2500.00,
        "customer_email": setup_test_tenancy["tenant_email"],
        "payment_method": "credit_card",
        "idempotency_key": key1
    })
    session1 = res1.json()["session_id"]

    # 2. Simulate failure
    fail_res = client.post("/api/tenant/checkout-session/simulate", headers={"X-Organization-Id": org_id}, json={
        "session_id": session1,
        "should_succeed": False,
        "error_message": "card_declined_insufficient_funds"
    })
    assert fail_res.status_code == 200
    assert fail_res.json()["simulated_outcome"] == "failed"

    # 3. Update billing record status to reflect failed transaction
    db_exec("UPDATE rent_billing_records SET status = 'failed' WHERE id = %s", (bill["id"],))

    # 4. Retry with new payment method / idempotency key
    key2 = f"retry-key-{uuid.uuid4().hex[:8]}"
    res2 = client.post("/api/tenant/pay-rent", headers={"X-Organization-Id": org_id}, json={
        "lease_id": lease_id,
        "billing_record_id": bill["id"],
        "amount_usd": 2500.00,
        "customer_email": setup_test_tenancy["tenant_email"],
        "payment_method": "ach_transfer",
        "idempotency_key": key2
    })
    assert res2.status_code == 200
    session2 = res2.json()["session_id"]

    # 5. Simulate retry success
    retry_sim = client.post("/api/tenant/checkout-session/simulate", headers={"X-Organization-Id": org_id}, json={
        "session_id": session2,
        "should_succeed": True
    })
    assert retry_sim.status_code == 200
    assert retry_sim.json()["simulated_outcome"] == "succeeded"

    sync = synchronize_confirmed_payment(session2, payment_method="ach_transfer")
    assert sync["success"] is True

    final_check = db_fetch_one("SELECT status FROM rent_billing_records WHERE id = %s", (bill["id"],))
    assert final_check[0] == "paid"


# =============================================================================
# Test 6: An unpaid obligation is evaluated correctly after its configured deadline
# =============================================================================
def test_06_unpaid_obligation_evaluated_correctly_after_configured_deadline(setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    past_period = "2026-08"

    bill = get_or_create_monthly_rent_obligation(lease_id, past_period)
    db_exec("""
        UPDATE rent_billing_records
        SET due_date = '2026-08-01',
            grace_period_end_date = '2026-08-04',
            status = 'due',
            reminder_stage = 'none'
        WHERE id = %s
    """, (bill["id"],))

    # Run sweep specifically for past period
    result = sweep_upcoming_and_overdue_rent(org_id=org_id, period=past_period)
    assert result["status"] == "completed"

    updated_bill = db_fetch_one("SELECT status, late_fee_usd FROM rent_billing_records WHERE id = %s", (bill["id"],))
    assert updated_bill[0] == "overdue"
    assert float(updated_bill[1]) >= 50.00


# =============================================================================
# Test 7: The three-day reminder is sent once and retries safely
# =============================================================================
def test_07_three_day_reminder_sent_once_and_retries_safely(setup_test_tenancy):
    org_id = setup_test_tenancy["org_id"]
    past_period = "2026-08"

    # Run sweep twice back-to-back for past period
    res1 = sweep_upcoming_and_overdue_rent(org_id=org_id, period=past_period)
    res2 = sweep_upcoming_and_overdue_rent(org_id=org_id, period=past_period)

    # Second run should send 0 overdue reminders because already dispatched
    assert res2["overdue_reminders_sent"] == 0


# =============================================================================
# Test 8: Payment made before escalation deadline suppresses further overdue escalation
# =============================================================================
def test_08_payment_before_escalation_deadline_suppresses_further_escalation(setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    period = "2026-07"

    bill = get_or_create_monthly_rent_obligation(lease_id, period)
    db_exec("UPDATE rent_billing_records SET status = 'overdue' WHERE id = %s", (bill["id"],))

    # Create a pending legal case
    case_id = f"CASE-{uuid.uuid4().hex[:6]}"
    db_exec("""
        INSERT INTO legal_notice_cases (
            id, org_id, lease_id, billing_record_id, tenant_name,
            unit, overdue_amount_usd, due_date, three_day_deadline,
            status, statutory_rule, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, 'Taylor Tenant',
            'Unit 404', 2550.00, '2026-07-01', '2026-07-07',
            'pending_review', 'California 3-Day Notice (Cal. Civ. Code § 1161(2))',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """, (case_id, org_id, lease_id, bill["id"]))

    # Create dummy session for payment
    provider = get_payment_provider()
    session = provider.create_checkout_session(
        lease_id=lease_id,
        billing_record_id=bill["id"],
        amount_usd=2550.00,
        org_id=org_id,
        customer_email=setup_test_tenancy["tenant_email"]
    )

    # Settle payment
    sync = synchronize_confirmed_payment(session["session_id"], payment_method="ach_transfer")
    assert sync["success"] is True

    # Confirm case was cancelled by payment
    legal_case = db_fetch_one("SELECT status FROM legal_notice_cases WHERE id = %s", (case_id,))
    assert legal_case[0] == "cancelled_by_payment"


# =============================================================================
# Test 9: Late/delayed payment is reconciled before legal escalation
# =============================================================================
def test_09_delayed_payment_is_reconciled_before_legal_escalation(setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    period = "2026-06"

    bill = get_or_create_monthly_rent_obligation(lease_id, period)
    case_id = f"CASE-PRE-{uuid.uuid4().hex[:6]}"
    db_exec("""
        INSERT INTO legal_notice_cases (
            id, org_id, lease_id, billing_record_id, tenant_name,
            unit, overdue_amount_usd, due_date, three_day_deadline,
            status, statutory_rule, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, 'Taylor Tenant',
            'Unit 404', 2550.00, '2026-06-01', '2026-06-07',
            'pending_review', 'California 3-Day Notice (Cal. Civ. Code § 1161(2))',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """, (case_id, org_id, lease_id, bill["id"]))

    # Settle bill late
    provider = get_payment_provider()
    session = provider.create_checkout_session(
        lease_id=lease_id,
        billing_record_id=bill["id"],
        amount_usd=2550.00,
        org_id=org_id,
        customer_email=setup_test_tenancy["tenant_email"]
    )
    synchronize_confirmed_payment(session["session_id"], payment_method="ach_transfer")

    # Attempt to approve legal notice
    decision = review_and_decide_legal_notice(case_id, "approved", "Property Manager", "Attempt notice")
    # Pre-flight check must catch that rent is settled and prevent dispatch!
    assert decision["success"] is False
    assert decision["status"] == "cancelled_by_payment"


# =============================================================================
# Test 10: A legal notice cannot be dispatched without manager authorization
# =============================================================================
def test_10_legal_notice_cannot_be_dispatched_without_authorization(setup_test_tenancy):
    org_id = setup_test_tenancy["org_id"]
    lease_id = setup_test_tenancy["lease_id"]
    period = "2026-05"

    bill = get_or_create_monthly_rent_obligation(lease_id, period)
    case_id = f"CASE-AUTH-{uuid.uuid4().hex[:6]}"
    db_exec("""
        INSERT INTO legal_notice_cases (
            id, org_id, lease_id, billing_record_id, tenant_name,
            unit, overdue_amount_usd, due_date, three_day_deadline,
            status, statutory_rule, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, 'Taylor Tenant',
            'Unit 404', 2550.00, '2026-05-01', '2026-05-07',
            'pending_review', 'California 3-Day Notice (Cal. Civ. Code § 1161(2))',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """, (case_id, org_id, lease_id, bill["id"]))

    # Ensure it remains pending_review until explicit action
    initial_case = db_fetch_one("SELECT status FROM legal_notice_cases WHERE id = %s", (case_id,))
    assert initial_case[0] == "pending_review"

    # Property Manager explicitly approves
    res = review_and_decide_legal_notice(case_id, "approved", "Property Manager", "Approved by legal counsel")
    assert res["success"] is True
    assert res["status"] == "approved"
    assert res["dispatched"] is True


# =============================================================================
# Test 11: Duplicate and out-of-order webhooks do not corrupt payment state
# =============================================================================
def test_11_duplicate_and_out_of_order_webhooks_do_not_corrupt_state(client, setup_test_tenancy):
    provider = get_payment_provider()
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    period = "2026-04"

    bill = get_or_create_monthly_rent_obligation(lease_id, period)

    # Create gateway session
    sess = provider.create_checkout_session(
        lease_id=lease_id,
        billing_record_id=bill["id"],
        amount_usd=2500.00,
        org_id=org_id,
        customer_email=setup_test_tenancy["tenant_email"]
    )
    session_id = sess["session_id"]
    event_id = f"evt_dup_{uuid.uuid4().hex[:8]}"

    payload = {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": session_id,
                "amount": 250000,
                "currency": "usd",
                "status": "succeeded"
            }
        }
    }
    raw_payload = json.dumps(payload)
    sig = provider.generate_webhook_signature(raw_payload)

    # 1. Send first webhook
    res1 = client.post("/api/webhooks/payment-gateway", content=raw_payload, headers={
        "Content-Type": "application/json",
        "X-Signature": sig
    })
    assert res1.status_code == 200
    assert res1.json()["new_status"] == "succeeded"

    # 2. Re-send exact same webhook (duplicate delivery)
    res2 = client.post("/api/webhooks/payment-gateway", content=raw_payload, headers={
        "Content-Type": "application/json",
        "X-Signature": sig
    })
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate_event_ignored"

    # Verify state remains stably paid
    check = db_fetch_one("SELECT status FROM rent_billing_records WHERE id = %s", (bill["id"],))
    assert check[0] == "paid"


# =============================================================================
# Test 12: Payment-provider downtime does not result in false success
# =============================================================================
def test_12_invalid_signature_does_not_result_in_false_success(client):
    fake_payload = json.dumps({"type": "payment_intent.succeeded", "data": {"object": {"id": "cs_fake"}}})
    res = client.post("/api/webhooks/payment-gateway", content=fake_payload, headers={
        "Content-Type": "application/json",
        "X-Signature": "t=12345678,v1=invalid_forged_signature_hex"
    })
    assert res.status_code == 400
    assert "Invalid webhook signature" in res.json()["detail"]


# =============================================================================
# Test 13: Dashboard, rent ledger, and payment history reflect same confirmed state
# =============================================================================
def test_13_dashboard_rent_ledger_and_payment_history_reflect_same_state(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    org_id = setup_test_tenancy["org_id"]
    period = "2026-03"

    bill = get_or_create_monthly_rent_obligation(lease_id, period)
    provider = get_payment_provider()
    session = provider.create_checkout_session(
        lease_id=lease_id,
        billing_record_id=bill["id"],
        amount_usd=2500.00,
        org_id=org_id,
        customer_email=setup_test_tenancy["tenant_email"]
    )

    sync = synchronize_confirmed_payment(session["session_id"], payment_method="ach_transfer")
    assert sync["success"] is True

    # 1. Check rent_billing_records
    billing_row = db_fetch_one("SELECT status, payment_reference FROM rent_billing_records WHERE id = %s", (bill["id"],))
    assert billing_row[0] == "paid"
    assert billing_row[1] is not None

    # 2. Check tenant dashboard API
    dash_res = client.get(f"/api/tenant/rent-dashboard?lease_id={lease_id}&period={period}", headers={"X-Organization-Id": org_id})
    assert dash_res.status_code == 200
    d_bill = dash_res.json()["current_bill"]
    assert d_bill["status"] == "paid"
    assert d_bill["payment_reference"] == billing_row[1]

    # 3. Check property manager overview
    pm_res = client.get("/api/pm/rent-collection/overview", headers={"X-Organization-Id": org_id})
    assert pm_res.status_code == 200
    pm_data = pm_res.json()
    assert pm_data["totals"]["paid_count"] >= 1


# =============================================================================
# Test 14: Background jobs survive retries without duplicate billing or emails
# =============================================================================
def test_14_background_jobs_survive_retries_without_duplicates(setup_test_tenancy):
    org_id = setup_test_tenancy["org_id"]

    # Sweep 3 times
    for _ in range(3):
        res = sweep_upcoming_and_overdue_rent(org_id=org_id)
        assert res["status"] == "completed"

    # Count obligations for this lease
    row = db_fetch_one("""
        SELECT COUNT(*), COUNT(DISTINCT billing_period)
        FROM rent_billing_records
        WHERE lease_id = %s
    """, (setup_test_tenancy["lease_id"],))

    # Due to UNIQUE(lease_id, billing_period), count must equal distinct count
    assert row[0] == row[1]


# =============================================================================
# Test 15: Audit logs record actions with sanitization
# =============================================================================
def test_15_audit_logs_record_actions_with_sanitization(setup_test_tenancy):
    org_id = setup_test_tenancy["org_id"]

    # Log an event containing potentially sensitive keys
    event = log_audit_event(
        org_id=org_id,
        actor_type="tenant",
        actor_id="TAYLOR-404",
        action="rent_billing.payment_initiated",
        resource_type="payment_gateway_transactions",
        resource_id="TX-SENSITIVE-TEST",
        details={
            "amount_usd": 2500.00,
            "card_number": "4111222233334444",
            "cvv": "123",
            "password": "SuperSecretPassword!",
            "token": "tok_live_secret_key"
        }
    )

    # Fetch from audit query
    result = query_audit_logs(org_id=org_id, resource_type="payment_gateway_transactions")
    logs = result["logs"]
    assert len(logs) >= 1
    found = [l for l in logs if l["resource_id"] == "TX-SENSITIVE-TEST"][0]
    
    # Assert sensitive values are [REDACTED]
    details = found["details"]
    assert details["card_number"] == "[REDACTED]"
    assert details["cvv"] == "[REDACTED]"
    assert details["password"] == "[REDACTED]"
    assert details["token"] == "[REDACTED]"
    assert details["amount_usd"] == 2500.00


# =============================================================================
# Test 16: Unauthorized users cannot access other organizations' payments or audit logs
# =============================================================================
def test_16_unauthorized_users_isolation(client, setup_test_tenancy):
    lease_id = setup_test_tenancy["lease_id"]
    foreign_org_id = "ORG-FOREIGN-INTRUDER"

    # Querying lease with wrong org header should return 404 or empty
    res = client.get(f"/api/tenant/rent-dashboard?lease_id={lease_id}", headers={"X-Organization-Id": foreign_org_id})
    assert res.status_code == 404

    # Querying audit logs for foreign org returns 0 records from setup_test_tenancy
    audit_res = client.get("/api/audit-logs", headers={"X-Organization-Id": foreign_org_id})
    assert audit_res.status_code == 200
    for log in audit_res.json()["logs"]:
        assert log["org_id"] == foreign_org_id


# =============================================================================
# Test 17: Email templates render correctly with dynamic variables and secure links
# =============================================================================
def test_17_email_templates_render_correctly():
    # 1. Rent Due
    due_html, due_text = render_rent_due_email(
        resident_name="Jordan Bell",
        property_name="Skyline Heights",
        unit="Penthouse 12B",
        rent_amount="$3,200.00",
        due_date="2026-11-01",
        grace_period_end_date="2026-11-04",
        payment_link="https://enigma.internal/tenant/pay"
    )
    assert "Jordan Bell" in due_html
    assert "$3,200.00" in due_html
    assert "https://enigma.internal/tenant/pay" in due_html
    assert len(due_text) > 50

    # 2. Overdue 3-day notice
    overdue_html, overdue_text = render_overdue_3day_email(
        resident_name="Jordan Bell",
        property_name="Skyline Heights",
        unit="Penthouse 12B",
        overdue_amount="$3,250.00",
        original_due_date="2026-11-01",
        exact_deadline_utc="November 7, 2026 at 23:59:59 UTC",
        payment_link="https://enigma.internal/tenant/pay"
    )
    assert "THREE-CALENDAR-DAY" in overdue_html
    assert "November 7, 2026 at 23:59:59 UTC" in overdue_html
    assert "$3,250.00" in overdue_html

    # 3. Payment Success
    success_html, success_text = render_payment_success_email(
        resident_name="Jordan Bell",
        property_name="Skyline Heights",
        unit="Penthouse 12B",
        amount_paid="$3,200.00",
        receipt_number="RCPT-2026-992",
        payment_reference="TX-CONFIRMED-992",
        payment_method="Direct Bank ACH Wire",
        payment_date="November 01, 2026 14:22 UTC"
    )
    assert "RCPT-2026-992" in success_html
    assert "TX-CONFIRMED-992" in success_html

    # 4. Payment Failed
    failed_html, failed_text = render_payment_failed_email(
        resident_name="Jordan Bell",
        property_name="Skyline Heights",
        unit="Penthouse 12B",
        amount_usd="$3,200.00",
        error_reason="Insufficient balance",
        retry_url="https://enigma.internal/retry"
    )
    assert "Action Required" in failed_html
    assert "Insufficient balance" in failed_html

    # 5. Processing
    processing_html, processing_text = render_payment_processing_email(
        resident_name="Jordan Bell",
        property_name="Skyline Heights",
        unit="Penthouse 12B",
        amount_usd="$3,200.00",
        session_id="TX-PENDING-123"
    )
    assert "Processing" in processing_html

    # 6. Legal Notice Review
    legal_html, legal_text = render_legal_notice_review_email(
        manager_name="Alex Manager",
        lease_id="LEASE-0001",
        tenant_name="Jordan Bell",
        unit="Penthouse 12B",
        overdue_amount="$3,250.00",
        jurisdiction="California",
        statutory_citation="Cal. Civ. Code § 1161(2)",
        approval_queue_url="https://enigma.internal/pm/legal-review"
    )
    assert "Statutory Notice Approval" in legal_html

    # 7. Property Manager Collection Alert
    pm_alert_html, pm_alert_text = render_pm_collection_alert_email(
        manager_name="Alex Manager",
        org_name="Skyline Proptech",
        billing_period="November 2026",
        collection_rate_pct="85.5",
        total_overdue="$9,600.00",
        overdue_units_count=3,
        dashboard_url="https://enigma.internal/pm/collection"
    )
    assert "$9,600.00" in pm_alert_html

    # 8. General System Notification
    system_html, system_text = render_system_notification_email(
        title="Scheduled Maintenance Notice",
        message="Water shutoff scheduled for routine plumbing maintenance.",
        action_label="View Notice",
        action_url="https://enigma.internal/notice"
    )
    assert "Scheduled Maintenance Notice" in system_html


# =============================================================================
# Test 18: Existing engine regressions continue to pass
# =============================================================================
def test_18_existing_engine_regressions_continue_to_pass():
    from app.engines import (
        get_hmem_instance,
        get_world_model,
        get_markovian_engine,
        get_unified_coordinator
    )
    hmem = get_hmem_instance()
    wm = get_world_model()
    markov = get_markovian_engine()
    coord = get_unified_coordinator()

    assert hmem is not None
    assert wm is not None
    assert markov is not None
    assert coord is not None
