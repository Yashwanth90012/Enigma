"""Comprehensive Unit and Integration Tests for EQUILIBRA Agents and Services.

Tests:
1. Property Verification Agent: scoring, policy rules, and auto-publishing
2. Public Discovery & Tour Booking: slot collision prevention and notifications
3. Rental Applications: preliminary screening and status determination
4. Autonomous Maintenance & SLA Agent: emergency triage, SLA calculation, vendor matching, breach escalation
5. Document Intelligence Agent: classification, field extraction, duplicate hash rejection, review routing
6. Financial Operations & Rent Billing: monthly invoice generation, idempotent payment handling, grace period sweep
7. Durable Notifications: queuing, deduplication by event_key, delivery state
8. Scheduler Lifecycle: status, execution history, and manual trigger
9. AI Assistant: tool calling over backend records and contextual synthesis
10. Integration Diagnostics: Zetaris Cloud and Meterless AI health reporting
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.property_agent import verify_property, book_tour, submit_rental_application, list_properties
from app.maintenance_agent import triage_maintenance_request, find_eligible_vendor, submit_and_triage_ticket
from app.document_agent import classify_document, extract_structured_fields, process_document, hash_content
from app.finance_agent import record_tenant_payment, generate_monthly_rent_invoices, sweep_grace_period_and_overdue
from app.notifications import queue_notification, list_notifications
from app.assistant import answer_assistant_query

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

# -------------------------------------------------------------
# 1. Property Verification & Public Discovery Tests
# -------------------------------------------------------------

def test_property_verification_scoring():
    # Verify PROP-001 has high score and auto-publishes
    res = verify_property("PROP-001")
    assert res["property_id"] == "PROP-001"
    assert res["verification_score"] >= 85.0
    assert res["verification_status"] == "verified"
    assert res["is_published"] is True
    assert res["findings"]["address_valid"] is True
    assert res["findings"]["rent_valid"] is True

def test_public_properties_endpoint(client):
    resp = client.get("/api/properties?published_only=true")
    assert resp.status_code == 200
    props = resp.json()
    assert len(props) >= 1
    assert all(p["is_published"] is True for p in props)

def test_tour_booking_and_duplicate_prevention():
    import uuid
    uid = uuid.uuid4().hex[:6]
    test_email = f"jordan.{uid}@example.com"
    # First booking
    res = book_tour(
        property_id="PROP-001",
        unit="Unit 4B",
        resident_name="Jordan Reed",
        resident_email=test_email,
        resident_phone="555-0199",
        booking_date="2026-11-10",
        booking_time="14:00"
    )
    assert res["status"] == "confirmed"
    assert "booking_id" in res

    # Attempt duplicate booking for same email & date -> should raise ValueError
    with pytest.raises(ValueError, match="already have a confirmed tour booking"):
        book_tour(
            property_id="PROP-001",
            unit="Unit 4B",
            resident_name="Jordan Reed",
            resident_email=test_email,
            resident_phone="555-0199",
            booking_date="2026-11-10",
            booking_time="16:00"
        )

def test_rental_application_screening():
    res = submit_rental_application(
        property_id="PROP-001",
        unit="Unit 101",
        applicant_name="Taylor Swift",
        applicant_email="taylor@example.com",
        applicant_phone="555-0244",
        monthly_income_usd=10000.00, # Well over 2.5x rent
        credit_score=780
    )
    assert res["status"] == "pre_approved"
    assert res["income_ratio"] >= 2.5

# -------------------------------------------------------------
# 2. Autonomous Maintenance & SLA Agent Tests
# -------------------------------------------------------------

def test_maintenance_emergency_triage():
    # Emergency scenario: active flood
    res = triage_maintenance_request("Water pipe burst in kitchen, flooding onto hardwood floor!")
    assert res["is_emergency"] is True
    assert res["priority"] == "Emergency"
    assert res["sla_hours"] == 4
    assert res["category"] == "Plumbing & Sinks"

def test_maintenance_standard_triage():
    # Non-emergency scenario: slow drain
    res = triage_maintenance_request("Bathroom sink drain is a bit slow and makes gurgling sound.")
    assert res["is_emergency"] is False
    assert res["priority"] in ("Medium", "Low")
    assert res["sla_hours"] >= 24

def test_vendor_matching_by_trade():
    vendor = find_eligible_vendor("Plumbing & Sinks")
    assert vendor is not None
    assert "Plumbing" in vendor["name"] or "plumb" in vendor["trade"].lower()

def test_submit_and_triage_ticket():
    ticket = submit_and_triage_ticket(
        lease_id="LEASE-0001",
        property_id="PROP-001",
        unit="Unit 2A",
        description="Kitchen light fixture sparks when flipping the switch on wall",
        reported_by="Alex Morgan",
        estimated_cost_usd=350.00
    )
    assert ticket["work_order_id"].startswith("WO-")
    assert ticket["category"] == "Electrical & Lighting"
    assert ticket["priority"] in ("Emergency", "High")
    assert ticket["assigned_vendor"] is not None

# -------------------------------------------------------------
# 3. Document Intelligence Agent Tests
# -------------------------------------------------------------

def test_document_classification():
    lease_sample = "Residential Lease Agreement LEASE-0045 between Landlord and Tenant. Monthly rent $2,400 due 1st."
    cls_lease = classify_document(lease_sample)
    assert cls_lease["kind"] == "lease"
    assert cls_lease["confidence"] >= 0.70

    invoice_sample = "INVOICE INV-PLUMB-9021. Billed to Property Management. Subtotal $450.00 Tax $37.12 Total $487.12. Net 30."
    cls_inv = classify_document(invoice_sample)
    assert cls_inv["kind"] == "vendor_invoice"
    assert cls_inv["confidence"] >= 0.70

def test_document_deduplication_by_content_hash():
    import uuid
    uid = uuid.uuid4().hex[:8]
    doc_body = f"Unique maintenance work order inspection report with serial {uid}."
    res1 = process_document("Inspection Report A", doc_body, "PROP-001", "LEASE-0001")
    assert res1["status"] == "processed"

    # Attempting to process identical document body
    res2 = process_document("Inspection Report Copy", doc_body, "PROP-001", "LEASE-0001")
    assert res2["status"] == "duplicate_rejected"
    assert res2["document_id"] == res1["document_id"]

def test_paddle_ocr_integration(monkeypatch):
    from unittest.mock import MagicMock
    import uuid
    from app.document_agent import extract_text_with_paddle_ocr, process_document

    # Test paddleocr import availability
    import paddleocr
    assert hasattr(paddleocr, "PaddleOCR")

    uid = uuid.uuid4().hex[:8]
    # Mock paddleocr instance to test extraction formatting without downloading heavy models in CI
    mock_ocr = MagicMock()
    mock_ocr.ocr.return_value = [
        [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], (f"RESIDENTIAL LEASE AGREEMENT REF-{uid}", 0.99)],
            [[[0, 25], [100, 25], [100, 45], [0, 45]], ("Monthly rent: $2,850.00", 0.98)],
            [[[0, 50], [100, 50], [100, 70], [0, 70]], (f"Tenant: Alice Walker {uid}", 0.95)]
        ]
    ]

    monkeypatch.setattr("app.document_agent.get_paddle_ocr", lambda: mock_ocr)
    extracted = extract_text_with_paddle_ocr("dummy_lease_scan.png")
    assert extracted is not None
    assert f"RESIDENTIAL LEASE AGREEMENT REF-{uid}" in extracted
    assert "$2,850.00" in extracted

    # Test end-to-end process_document with OCR file trigger
    dummy_file = f"/tmp/scanned_{uid}.png"
    doc_res = process_document(
        title="Scanned Lease Agreement",
        body="",  # Empty body triggers OCR
        file_path=dummy_file
    )
    assert doc_res["status"] == "processed"
    assert doc_res["ocr_applied"] is True
    assert doc_res["ocr_provider"] == "paddleocr"
    assert doc_res["kind"] == "lease"


# -------------------------------------------------------------
# 4. Financial Operations & Rent Collection Tests
# -------------------------------------------------------------

def test_generate_rent_billing():
    res = generate_monthly_rent_invoices("2026-11")
    assert "billing_period" in res
    assert res["billing_period"] == "2026-11"
    assert res["invoices_created"] >= 0

def test_record_tenant_payment_idempotency():
    import uuid
    ref = f"TEST-REF-{uuid.uuid4().hex[:8].upper()}"
    # First payment
    res1 = record_tenant_payment(
        lease_id="LEASE-0001",
        amount_usd=100.00,
        payment_method="ach_transfer",
        reference=ref,
        simulate_bank_clearing=True
    )
    assert res1["status"] in ("payment_applied", "duplicate_prevented")

    # Second payment with exact same reference
    res2 = record_tenant_payment(
        lease_id="LEASE-0001",
        amount_usd=100.00,
        payment_method="ach_transfer",
        reference=ref,
        simulate_bank_clearing=True
    )
    assert res2["status"] == "duplicate_prevented"

def test_grace_period_sweep():
    delinquencies = sweep_grace_period_and_overdue()
    assert isinstance(delinquencies, list)

# -------------------------------------------------------------
# 5. Durable Notifications Tests
# -------------------------------------------------------------

def test_notification_deduplication():
    import uuid
    key = f"unique-event-key-{uuid.uuid4().hex[:8]}"
    n1 = queue_notification("test@tenant.com", "tenant", "Rent Notice", "Your rent is due", "rent", event_key=key)
    assert n1["duplicate"] is False

    # Second queue call with same key
    n2 = queue_notification("test@tenant.com", "tenant", "Rent Notice", "Your rent is due", "rent", event_key=key)
    assert n2["duplicate"] is True

def test_list_notifications_endpoint(client):
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

# -------------------------------------------------------------
# 6. Scheduler Health & AI Assistant Tests
# -------------------------------------------------------------

def test_scheduler_status_and_trigger(client):
    status_resp = client.get("/api/scheduler/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert "status" in data

    trigger_resp = client.post("/api/scheduler/trigger")
    assert trigger_resp.status_code == 200
    trigger_data = trigger_resp.json()
    assert "timestamp" in trigger_data

def test_assistant_chat_query():
    ans = answer_assistant_query("What is the rent status and reconciliation for LEASE-0001?")
    assert "lease" in ans["retrieved_context"] or "LEASE-0001" in ans["response"]
    assert len(ans["tool_calls"]) >= 1

def test_integration_diagnostics(client):
    z_resp = client.get("/api/integrations/zetaris/health")
    assert z_resp.status_code == 200
    z_data = z_resp.json()
    assert z_data["service"] == "Zetaris Cloud SQL Federation"
    assert "connection_status" in z_data

    m_resp = client.get("/api/integrations/meterless/health")
    assert m_resp.status_code == 200
    m_data = m_resp.json()
    assert m_data["service"] == "Meterless AI / Nightshift"
    assert "connection_status" in m_data
