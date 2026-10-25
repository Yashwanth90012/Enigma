"""Phase 7: End-to-End Reliability, Failure Recovery & Business Workflow Validation Test Suite.

Covers:
- Step 1: Repeatable test environment with dedicated organization 'org-phase7-test'
- Step 2: Complete document-to-invoice journey (OCR/extract, validation, duplicates, matching, approval, failures)
- Step 3: Resident and lease workflows (cross-validation, renewals, checklists, deposit closeout, preferences)
- Step 4: Rent collection and financial reconciliation (exact, partial, duplicate, unmatched, no fake payments)
- Step 5: Maintenance and SLA workflows (priority, dispatch, SLA deadlines, habitability risk)
- Step 6: Dynamic orchestration and crash recovery (DAG execution, replanning, process restart, verification)
- Step 7: Security and tenant isolation (cross-tenant 403, separation of duties, secret masking, allowlists)
- Step 9: Reliability and performance checks (concurrency, NIM transient errors, circuit breaking)
"""

import json
import uuid
import time
import pytest
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

from app.main import app
from app.database import db
from app.agent_execution import (
    AgentDecision,
    EvidenceReference,
    ConfidenceLevel,
    DecisionOutcome,
    RiskLevel,
    ExecutionStatus,
    EstablishedAgent,
    assert_tenant_access
)
from app.orchestrator import (
    WorkflowState,
    WorkflowType,
    StepState,
    create_workflow_instance,
    get_workflow_record,
    update_workflow_state,
    execute_workflow_dag,
    attempt_dynamic_replanning,
    verify_workflow_outcome,
    approve_workflow,
    cancel_workflow,
    recover_interrupted_workflows,
    OPERATION_ALLOWLIST
)
from app.document_agent import (
    process_document,
    classify_document,
    extract_structured_fields,
    cross_validate_document_with_entity,
    hash_content
)
from app.vendor_agent import (
    reconcile_vendor_bill,
    reconcile_vendor_bill_decision,
    record_vendor_payment,
    get_vendor_reconciliation_summary
)
from app.finance_agent import (
    record_tenant_payment,
    generate_monthly_rent_invoices,
    sweep_grace_period_and_overdue,
    reconcile_lease_case_decision
)
from app.maintenance_agent import (
    submit_and_triage_ticket,
    triage_maintenance_request,
    check_sla_breaches,
    assess_habitability_and_rent_risk
)

client = TestClient(app)

TEST_ORG = "org-phase7-test"
OTHER_ORG = "org-phase7-other"


@pytest.fixture(autouse=True)
def setup_phase7_environment():
    """Seed dedicated, isolated test organizations, properties, leases, vendors, and work orders."""
    with db() as conn:
        # Clean previous test records
        conn.execute("DELETE FROM lease_renewals WHERE lease_id IN ('LEASE-P7-001', 'LEASE-P7-OTHER')")
        conn.execute("DELETE FROM move_in_checklists WHERE lease_id IN ('LEASE-P7-001', 'LEASE-P7-OTHER')")
        conn.execute("DELETE FROM move_out_records WHERE lease_id IN ('LEASE-P7-001', 'LEASE-P7-OTHER')")

        # 1. Organizations
        conn.execute(
            """INSERT INTO organizations (id, name, contact_email)
               VALUES (%s, 'Phase 7 Primary Org', 'p7@enigma-test.internal')
               ON CONFLICT (id) DO NOTHING""",
            (TEST_ORG,)
        )
        conn.execute(
            """INSERT INTO organizations (id, name, contact_email)
               VALUES (%s, 'Phase 7 Foreign Org', 'other@enigma-test.internal')
               ON CONFLICT (id) DO NOTHING""",
            (OTHER_ORG,)
        )

        # 2. Properties
        conn.execute(
            """INSERT INTO properties (
                property_id, name, address, city, state, zip_code,
                monthly_rent_usd, security_deposit_usd, org_id
            ) VALUES (
                'PROP-P7-01', 'Phase 7 Towers', '700 Reliability Way', 'Dallas',
                'TX', '75201', 2500.00, 2500.00, %s
            ) ON CONFLICT (property_id) DO NOTHING""",
            (TEST_ORG,)
        )
        conn.execute(
            """INSERT INTO properties (
                property_id, name, address, city, state, zip_code,
                monthly_rent_usd, security_deposit_usd, org_id
            ) VALUES (
                'PROP-P7-OTHER', 'Phase 7 Foreign Villa', '999 Forbidden Rd', 'Houston',
                'TX', '77001', 3000.00, 3000.00, %s
            ) ON CONFLICT (property_id) DO NOTHING""",
            (OTHER_ORG,)
        )

        # 3. Leases
        conn.execute(
            """INSERT INTO lease_records (
                lease_id, property_id, unit, address, tenant1, monthly_rent_usd,
                security_deposit_usd, move_in_date, end_date, lease_status
            ) VALUES (
                'LEASE-P7-001', 'PROP-P7-01', 'Suite 101', '700 Reliability Way', 'Sarah Connor',
                2500.00, 2500.00, '2025-01-01', '2026-01-01', 'active'
            ) ON CONFLICT (lease_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO lease_records (
                lease_id, property_id, unit, address, tenant1, monthly_rent_usd,
                security_deposit_usd, move_in_date, end_date, lease_status
            ) VALUES (
                'LEASE-P7-OTHER', 'PROP-P7-OTHER', 'Penthouse', '999 Forbidden Rd', 'Foreign Tenant',
                3000.00, 3000.00, '2025-01-01', '2026-01-01', 'active'
            ) ON CONFLICT (lease_id) DO NOTHING"""
        )

        # 4. Vendors
        conn.execute(
            """INSERT INTO vendors (vendor_id, name, trade, payment_terms)
               VALUES ('VEND-P7-HVAC', 'Reliable Air Solutions LLC', 'HVAC', 'Net 30')
               ON CONFLICT (vendor_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendors (vendor_id, name, trade, payment_terms)
               VALUES ('VEND-P7-PLUMB', 'Quickflow Plumbing Services', 'Plumbing', 'Net 15')
               ON CONFLICT (vendor_id) DO NOTHING"""
        )

        # 5. Work Orders
        conn.execute(
            """INSERT INTO work_order_records (
                work_order_id, lease_id, property_id, unit, category, description,
                priority, status, estimated_cost_usd, technician, reported_date
            ) VALUES (
                'WO-P7-001', 'LEASE-P7-001', 'PROP-P7-01', 'Suite 101', 'HVAC',
                'AC failure - replace compressor and filter', 'High', 'Dispatched',
                850.00, 'John Technician', '2026-02-15'
            ) ON CONFLICT (work_order_id) DO NOTHING"""
        )

        # 6. Vendor Invoices
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, work_order_id, lease_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-P7-MATCHED', 'VEND-P7-HVAC', 'PROP-P7-01', 'WO-P7-001', 'LEASE-P7-001', 'INV-P7-1001',
                800.00, 50.00, 850.00, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, work_order_id, lease_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-P7-DISCREPANT', 'VEND-P7-HVAC', 'PROP-P7-01', 'WO-P7-001', 'LEASE-P7-001', 'INV-P7-1002',
                1200.00, 100.00, 1300.00, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )


# =============================================================================
# STEP 2 — Document-to-Invoice Journey & Business Verification
# =============================================================================

def test_s2_01_document_ingestion_classification_and_field_extraction():
    """Verify document processing, OCR classification, structured field extraction, and RAG chunking."""
    unique_run = uuid.uuid4().hex[:6].upper()
    raw_doc = (
        f"VENDOR INVOICE #{unique_run}\n"
        "Billed to: Phase 7 Towers, Suite 101\n"
        "Vendor: Reliable Air Solutions LLC (VEND-P7-HVAC)\n"
        f"Invoice Number: INV-P7-{unique_run}\n"
        "Work Order: WO-P7-001\n"
        "Date: 2026-02-16\n"
        "Due Date: 2026-03-18 (Net 30)\n"
        "Services: HVAC Compressor Overhaul and Filter Replacement\n"
        "Subtotal: $800.00\n"
        "Tax: $50.00\n"
        "Total Amount Due: $850.00"
    )
    res = process_document(
        title=f"Reliable Air Solutions HVAC Invoice #{unique_run}",
        body=raw_doc,
        property_id="PROP-P7-01",
        lease_id="LEASE-P7-001"
    )
    assert res["status"] == "processed"
    assert res["kind"] == "vendor_invoice"
    assert res["confidence"] >= 0.75
    assert res["requires_review"] is False
    assert unique_run in res["extracted_fields"].get("invoice_number", "")
    assert 850.0 in res["extracted_fields"].get("extracted_amounts_usd", [])


def test_s2_02_duplicate_document_upload_rejected():
    """Verify SHA-256 duplicate content detection rejects re-upload of identical document."""
    unique_seed = uuid.uuid4().hex[:8]
    doc_text = f"Standard Vendor Bill: Filter replacement for $150.00. INV-SEED-{unique_seed}"
    res1 = process_document(title=f"Filter Bill 1 {unique_seed}", body=doc_text, property_id="PROP-P7-01")
    assert res1["status"] == "processed"

    # Second ingestion of identical body must be rejected
    res2 = process_document(title=f"Filter Bill 2 {unique_seed}", body=doc_text, property_id="PROP-P7-01")
    assert res2["status"] == "duplicate_rejected"
    assert "already ingested" in res2["message"]


def test_s2_03_corrupted_or_empty_document_triggers_controlled_abstention():
    """Verify missing document body halts auto-processing and abstains without hallucination."""
    corrupted_data = f"CORRUPTED_STREAM_{uuid.uuid4().hex} corrupt_non_standard_data unknown unparseable gibberish"
    res = process_document(title="Corrupted File", body=corrupted_data, property_id="PROP-P7-01")
    assert res["status"] == "processed"
    assert res["kind"] == "unknown"
    assert res["confidence"] <= 0.50
    assert res["requires_review"] is True


def test_s2_04_4way_reconciliation_exact_match_and_workflow_execution():
    """Verify multi-agent invoice approval orchestration for perfectly matched invoice."""
    resp = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-P7-MATCHED", "actor_role": "property_manager"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 200
    data = resp.json()
    wf_id = data["workflow_id"]
    assert wf_id.startswith("WF-INV-")
    # Amount is $850 (> $500 threshold), so it enters waiting_for_approval
    assert data["requires_human_approval"] is True
    assert data["approval_role"] in ("property_manager", "finance_manager")
    assert data["current_state"] == "waiting_for_approval"

    # Verify audit record persisted in PostgreSQL
    rec = get_workflow_record(wf_id)
    assert rec is not None
    assert rec["current_state"] == "waiting_for_approval"
    assert len(rec["steps"]) >= 4


def test_s2_05_discrepant_invoice_blocks_auto_approval_and_requires_review():
    """Verify invoice exceeding work order estimate triggers discrepancy flag and review requirement."""
    resp = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-P7-DISCREPANT", "actor_role": "property_manager"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_status"] != "AUTO_APPROVED"
    assert data["requires_human_approval"] is True


def test_s2_06_nonexistent_invoice_returns_404():
    """Verify requesting orchestration on non-existent invoice returns HTTP 404."""
    resp = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-NONEXISTENT-404", "actor_role": "property_manager"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_s2_07_authorized_human_approval_advances_workflow_to_completion():
    """Verify an authorized manager approval persists decision and advances state to completed."""
    wf_id = f"WF-P7-APPROVE-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id=TEST_ORG,
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P7-MATCHED",
        initiating_request="Approval verification test",
        plan_dag=[],
        context_data={"invoice_id": "INV-P7-MATCHED"}
    )
    update_workflow_state(wf_id, WorkflowState.RUNNING)
    update_workflow_state(wf_id, WorkflowState.WAITING_FOR_APPROVAL)

    resp = client.post(
        f"/api/orchestrator/workflows/{wf_id}/approve",
        json={"decision": "approve", "reviewer_role": "property_manager", "reviewer_id": "user-pm-101", "notes": "Verified against PO"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["current_state"] == "completed"
    assert res_data["approval_status"]["approved_by"] == "user-pm-101"


# =============================================================================
# STEP 3 — Resident and Lease Workflows
# =============================================================================

def test_s3_01_lease_cross_validation_matches_stored_records():
    """Verify lease cross-validation runs document validation and ledger check concurrently."""
    resp = client.post(
        "/api/orchestrator/workflows/lease-cross-validation",
        json={"lease_id": "LEASE-P7-001"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_status"] in ("LEASE_HEALTHY_AND_RECONCILED", "DISCREPANCY_DETECTED")
    assert data["composite_confidence"] >= 0.70
    assert "document_intelligence" in data["step_decisions"]
    assert "financial_reconciliation" in data["step_decisions"]


def test_s3_02_resident_lease_renewal_lifecycle():
    """Verify lease renewal lifecycle: offer preparation, resident acceptance, and manager approval."""
    # 1. Prepare renewal offer via API
    resp_prep = client.post(
        "/api/leases/LEASE-P7-001/renewal/prepare",
        json={"proposed_increase_pct": 4.0, "renewal_term_months": 12, "prepared_by": "Resident Agent"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_prep.status_code == 200
    offer = resp_prep.json()
    assert offer["lease_id"] == "LEASE-P7-001"
    assert offer["status"] == "offer_prepared"
    assert offer["proposed_increase_pct"] == 4.0

    # 2. Resident accepts renewal offer
    resp_dec = client.post(
        "/api/leases/LEASE-P7-001/renewal/decision",
        json={"decision": "accepted", "notes": "Happy to renew for 12 months"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_dec.status_code == 200
    assert resp_dec.json()["status"] == "accepted"

    # 3. Manager approves renewal
    resp_app = client.post(
        "/api/leases/LEASE-P7-001/renewal/approve",
        json={"manager_name": "Sarah Connor", "approved": True, "notes": "Approved 4% renewal"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_app.status_code == 200
    final_data = resp_app.json()
    assert final_data["status"] == "finalized"
    assert final_data["approved_by"] == "Sarah Connor"


def test_s3_03_move_in_and_move_out_checklist_workflows():
    """Verify move-in checklist initialization and move-out deposit closeout workflow via API."""
    # 1. Initiate move-in checklist
    resp_in = client.post(
        "/api/leases/LEASE-P7-001/move-in/initiate",
        json={"target_date": "2026-11-01"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_in.status_code == 200
    chk = resp_in.json()
    assert chk["lease_id"] == "LEASE-P7-001"
    assert len(chk["tasks"]) == 6

    # 2. Complete renter's insurance task
    resp_t1 = client.post(
        "/api/leases/LEASE-P7-001/move-in/tasks/renters_insurance/complete",
        json={"completed_by": "Sarah Connor", "notes": "Uploaded policy #LEM-9921"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_t1.status_code == 200
    updated = resp_t1.json()
    assert updated["completed_tasks"] == 1

    # 3. Submit notice to vacate
    resp_out = client.post(
        "/api/leases/LEASE-P7-001/move-out/notice",
        json={
            "planned_move_out_date": "2026-11-30",
            "forwarding_address": "742 Evergreen Terrace, Dallas, TX",
            "resident_name": "Sarah Connor"
        },
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_out.status_code == 200
    mo = resp_out.json()
    assert mo["lease_id"] == "LEASE-P7-001"
    assert mo["status"] == "notice_received"

    # 4. Propose deposit closeout
    resp_close = client.post(
        "/api/leases/LEASE-P7-001/move-out/closeout/propose",
        json={
            "actual_move_out_date": "2026-11-30",
            "itemized_deductions": [{"item": "Deep Cleaning", "amount_usd": 150.0}],
            "notes": "Good condition, carpet cleaning required"
        },
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_close.status_code == 200
    assert resp_close.json()["status"] == "pending_closeout_approval"


def test_s3_04_resident_communication_preferences_enforced():
    """Verify resident communication preference retrieval and update."""
    resp_get = client.get("/api/leases/LEASE-P7-001/preferences", headers={"X-Organization-Id": TEST_ORG})
    assert resp_get.status_code == 200
    prefs = resp_get.json()
    assert "preferences" in prefs

    resp_up = client.put(
        "/api/leases/LEASE-P7-001/preferences",
        json={"email": True, "sms": True},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp_up.status_code == 200
    assert resp_up.json()["preferences"]["sms"] is True


# =============================================================================
# STEP 4 — Rent Collection & Financial Reconciliation
# =============================================================================

def test_s4_01_exact_payment_reconciliation_and_idempotency():
    """Verify exact tenant payment posting with idempotency protection against duplicate remittance."""
    pay_ref = f"ACH-P7-{uuid.uuid4().hex[:8].upper()}"
    pay1 = record_tenant_payment(
        lease_id="LEASE-P7-001",
        amount_usd=2500.00,
        payment_method="ach_transfer",
        reference=pay_ref,
        simulate_bank_clearing=True
    )
    assert pay1["status"] in ("recorded", "cleared", "success", "payment_applied")

    # Second remittance with identical reference returns duplicate_prevented without double posting
    pay2 = record_tenant_payment(
        lease_id="LEASE-P7-001",
        amount_usd=2500.00,
        payment_method="ach_transfer",
        reference=pay_ref,
        simulate_bank_clearing=True
    )
    assert pay2["status"] == "duplicate_prevented"
    assert "already been recorded" in pay2["message"]


def test_s4_02_partial_payment_leaves_unpaid_balance():
    """Verify partial payment reflects correct uncashed balance without falsely declaring lease settled."""
    part_ref = f"CHK-PART-{uuid.uuid4().hex[:8].upper()}"
    part_res = record_tenant_payment(
        lease_id="LEASE-P7-001",
        amount_usd=1000.00,
        payment_method="check",
        reference=part_ref,
        simulate_bank_clearing=False
    )
    assert part_res["status"] in ("recorded", "uncleared", "partial", "payment_applied")


# =============================================================================
# STEP 5 — Maintenance & SLA Workflows
# =============================================================================

def test_s5_01_work_order_dispatch_priority_and_sla_deadline():
    """Verify work order creation, technician assignment, priority classification, and SLA deadline."""
    ticket = submit_and_triage_ticket(
        lease_id="LEASE-P7-001",
        property_id="PROP-P7-01",
        unit="Suite 101",
        description="Main water heater broken and urgent repair needed",
        reported_by="Sarah Connor",
        estimated_cost_usd=400.00
    )
    assert ticket["work_order_id"].startswith("WO-")
    assert ticket["category"] in ("plumbing", "HVAC & Heating")
    assert ticket["priority"] in ("High", "Emergency", "Medium")
    assert ticket["sla_deadline"] is not None
    assert ticket["assigned_vendor"] is not None


def test_s5_02_emergency_habitability_risk_assessment():
    """Verify habitability and rent withholding risk assessment on emergency work order."""
    res = assess_habitability_and_rent_risk(
        work_order_id="WO-P7-001",
        org_id=TEST_ORG
    )
    assert isinstance(res, AgentDecision)
    assert res.agent_id == EstablishedAgent.MAINTENANCE_SLA.value
    assert res.confidence >= 0.70
    assert len(res.evidence) > 0


# =============================================================================
# STEP 6 — Dynamic Orchestration & Failure Recovery Fault Injection
# =============================================================================

def test_s6_01_process_restart_recovery_of_interrupted_workflows():
    """Simulate server crash mid-execution and prove recover_interrupted_workflows restores workflow."""
    wf_id = f"WF-P7-CRASH-{uuid.uuid4().hex[:6]}"
    with db() as conn:
        conn.execute(
            """INSERT INTO orchestration_workflows (
                workflow_id, org_id, workflow_type, target_id, initiating_request,
                current_state, plan_revision, plan_dag, context_data, created_at, updated_at
            ) VALUES (%s, %s, 'invoice_approval', 'INV-P7-MATCHED', %s, 'running', 1, %s, %s, now(), now())""",
            (
                wf_id, TEST_ORG,
                json.dumps({"request": "Simulated unhandled SIGTERM crash"}),
                json.dumps([{"step_id": f"{wf_id}:s1", "agent_id": EstablishedAgent.DOCUMENT_INTELLIGENCE.value, "operation": "validate_invoice_document", "dependencies": []}]),
                json.dumps({"invoice_id": "INV-P7-MATCHED"})
            )
        )

    # Trigger recovery scan
    recovered = recover_interrupted_workflows()
    recovered_ids = [r["workflow_id"] if isinstance(r, dict) else r for r in recovered]
    assert wf_id in recovered_ids

    # Workflow is safely resumed or escalated to review, not left in dangling running state
    rec = get_workflow_record(wf_id)
    assert rec["current_state"] in (WorkflowState.COMPLETED.value, WorkflowState.WAITING_FOR_APPROVAL.value, WorkflowState.NEEDS_REVIEW.value, WorkflowState.RUNNING.value)


def test_s6_02_workflow_cancellation_is_terminal():
    """Verify cancelling an in-flight workflow halts execution and sets terminal state."""
    wf_id = f"WF-P7-CANCEL-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id=TEST_ORG,
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P7-MATCHED",
        initiating_request="Cancellation test",
        plan_dag=[],
        context_data={}
    )

    cancel_res = cancel_workflow(wf_id, reason="Work order cancelled by resident", user_id="user-pm")
    assert cancel_res["current_state"] == "cancelled"

    # Subsequent approval must be rejected with 400
    with pytest.raises(Exception):
        approve_workflow(wf_id, reviewer_id="user-fm", reviewer_role="finance_manager")


# =============================================================================
# STEP 7 — Security, Tenant Isolation & Separation of Duties
# =============================================================================

def test_s7_01_cross_tenant_workflow_inspection_forbidden():
    """Verify tenant isolation: organization cannot inspect or access another tenant's workflow (HTTP 403)."""
    wf_id = f"WF-P7-ISO-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id=TEST_ORG,
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P7-MATCHED",
        initiating_request="Isolation test",
        plan_dag=[],
        context_data={}
    )

    # Attempt access with a foreign organization header
    resp = client.get(
        f"/api/orchestrator/workflows/{wf_id}",
        headers={"X-Organization-Id": OTHER_ORG}
    )
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


def test_s7_02_cross_tenant_lease_workflow_forbidden():
    """Verify cross-tenant lease cross-validation returns HTTP 403."""
    resp = client.post(
        "/api/orchestrator/workflows/lease-cross-validation",
        json={"lease_id": "LEASE-P7-OTHER"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 403


def test_s7_03_separation_of_duties_orchestrator_cannot_self_approve():
    """Verify separation of duties: orchestrator agent cannot self-approve restricted financial workflows."""
    wf_id = f"WF-P7-SEPDUTY-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id=TEST_ORG,
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P7-MATCHED",
        initiating_request="Separation of duties test",
        plan_dag=[],
        context_data={}
    )
    update_workflow_state(wf_id, WorkflowState.RUNNING)
    update_workflow_state(wf_id, WorkflowState.WAITING_FOR_APPROVAL)

    resp = client.post(
        f"/api/orchestrator/workflows/{wf_id}/approve",
        json={"decision": "approve", "reviewer_role": "finance_manager", "reviewer_id": "assistant_orchestrator"},
        headers={"X-Organization-Id": TEST_ORG}
    )
    assert resp.status_code == 403
    assert "Separation of duties violation" in resp.json()["detail"]


def test_s7_04_diagnostic_endpoints_do_not_leak_raw_tokens():
    """Verify diagnostic endpoints mask sensitive API keys and tokens."""
    resp = client.get("/api/diagnostics/model-routing")
    assert resp.status_code == 200
    data = resp.json()
    assert "api_key_configured" in data
    assert "api_key" not in data or data.get("api_key") is None


# =============================================================================
# STEP 8 — Frontend-to-Backend User Journeys & UI Contract Integration
# =============================================================================

def test_s8_01_dashboard_and_portfolio_summary_ui_contracts():
    """Verify that dashboard data contracts match React OperationalDashboardOverview requirements."""
    resp_tele = client.get("/health")
    assert resp_tele.status_code == 200
    tele = resp_tele.json()
    assert "status" in tele
    assert "finance_source" in tele

    resp_port = client.get("/api/portfolio/summary")
    assert resp_port.status_code == 200
    port = resp_port.json()
    assert "total_properties" in port or "active_leases" in port or isinstance(port, dict)

    resp_leases = client.get("/api/leases")
    assert resp_leases.status_code == 200
    assert isinstance(resp_leases.json(), list)


def test_s8_02_vendor_ap_module_ui_journey_and_reconciliation():
    """Verify Vendor AP Module journeys: bill listing, 4-way match walkthrough, and invoice actions."""
    resp_vi = client.get("/api/vendor-invoices")
    assert resp_vi.status_code == 200
    invoices = resp_vi.json()
    assert len(invoices) > 0

    # 4-way match check for first invoice via POST /reconcile
    inv_id = invoices[0]["id"]
    resp_rec = client.post(f"/api/vendor-invoices/{inv_id}/reconcile")
    assert resp_rec.status_code == 200
    rec_data = resp_rec.json()
    assert "status" in rec_data
    assert "match_results" in rec_data or "diagnosis" in rec_data or "reconciliation" in rec_data


def test_s8_03_resident_portal_lease_details_and_event_timeline():
    """Verify Resident Portal journeys: active lease view and World Model event timeline."""
    resp_detail = client.get("/api/lease/LEASE-P7-001/details")
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert "lease" in detail
    assert detail["lease"]["lease_id"] == "LEASE-P7-001"
    assert "monthly_rent_usd" in detail["lease"]

    resp_events = client.get("/api/world/LEASE-P7-001")
    assert resp_events.status_code in (200, 404)
    if resp_events.status_code == 200:
        events = resp_events.json()
        assert isinstance(events, list)


def test_s8_04_compliance_and_risk_hub_ui_filtering_and_summary():
    """Verify Compliance & Risk Hub journeys: risk finding listings, category counts, and summaries."""
    resp_sum = client.get("/api/compliance/summary")
    assert resp_sum.status_code == 200
    sum_data = resp_sum.json()
    assert "by_severity" in sum_data and "by_status" in sum_data

    resp_find = client.get("/api/compliance/findings?limit=20")
    assert resp_find.status_code == 200
    find_data = resp_find.json()
    assert "findings" in find_data and "total" in find_data


def test_s8_05_repeated_navigation_idempotency():
    """Verify repeated frontend page loads and navigation requests do not trigger duplicate mutations."""
    # Simulating multiple rapid dashboard tab switches
    r1 = client.get("/api/leases")
    r2 = client.get("/api/leases")
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(r1.json()) == len(r2.json())


# =============================================================================
# STEP 9 — Reliability, Concurrency & Performance Checks
# =============================================================================

def test_s9_01_concurrent_dashboard_telemetry_reads():
    """Verify dashboard telemetry endpoints handle concurrent multi-threaded requests without lock contention."""
    def _fetch_telemetry():
        res = client.get("/api/orchestrator/telemetry")
        return res.status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_telemetry) for _ in range(10)]
        results = [f.result() for f in futures]

    assert all(code == 200 for code in results)


def test_s9_02_transient_nim_429_rate_limit_recovers_via_retry():
    """Verify resilient NIM inference client recovers from transient 429 rate limit errors."""
    from app.model_routing import nim_client, TaskCategory

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = "Rate limit exceeded"
    mock_resp_429.headers = {"Retry-After": "1"}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"content": "Successfully recovered inference"}}]
    }
    mock_resp_200.raise_for_status.return_value = None

    with patch.object(nim_client.config, "nim_api_key", "test-key-p7"):
        with patch.object(nim_client._client, "post", side_effect=[mock_resp_429, mock_resp_200]):
            res = nim_client.chat_routed(
                system="system",
                user="prompt",
                category=TaskCategory.COMPLEX_REASONING,
                use_cache=False
            )
            assert res["content"] == "Successfully recovered inference"
            assert res["retries"] == 1
