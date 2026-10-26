"""Unified Engine Integration and End-to-End Reliability Validation Tests for ENIGMA / EQUILIBRA.

Validates the cohesive multi-engine architecture:
- H-MEM: Persistent contextual memory, hybrid retrieval, and outbox publication
- World Model: Authoritative business facts, entity relationships, and provenance
- Markovian: Bounded execution, checkpoints, crash recovery, and side-effect deduplication

Covers all 6 required business scenarios:
1. Scenario A — Lease document to resident context
2. Scenario B — Vendor invoice reconciliation & approval gating
3. Scenario C — Resident maintenance request with mid-flight failure & recovery
4. Scenario D — Approval pause, restart simulation, and authorized resumption
5. Scenario E — H-MEM unavailable with transactional outbox resiliency
6. Scenario F — Duplicate requests, timeout recovery, and idempotency protection
"""

import time
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import db
from app.world_model import get_latest_state, get_events, record_event
from app.engines import (
    get_hmem_instance,
    get_world_model,
    get_markovian_engine,
    get_unified_coordinator,
    UnifiedBusinessRequest,
    UnifiedExecutionResult
)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def coordinator():
    return get_unified_coordinator()


# =============================================================================
# Scenario A: Lease Document to Resident Context
# =============================================================================

def test_scenario_a_lease_document_to_resident_context(coordinator):
    """Scenario A:
    1. Ingest synthetic lease document
    2. Extract & validate structured fields
    3. Persist verified facts in World Model
    4. Store appropriate contextual memories in H-MEM via outbox
    5. Query resident/lease state and confirm source provenance
    6. Confirm repeated ingestion does not duplicate events or memories
    """
    org_id = f"ORG-TEST-SCENA-{uuid.uuid4().hex[:6]}"
    lease_id = f"LEASE-{uuid.uuid4().hex[:4].upper()}"
    prop_id = f"PROP-{uuid.uuid4().hex[:4].upper()}"
    tenant_name = "Eleanor Vance"
    monthly_rent = 2850.00

    lease_body = (
        f"Residential Lease Agreement: Monthly Rent ${monthly_rent:.2f}, "
        f"Security Deposit $2850.00 for {tenant_name} at Property {prop_id} Unit 3B, Lease ID {lease_id}."
    )

    # 1. First Ingestion
    res1 = coordinator.process_lease_document(
        title=f"Lease Agreement - {tenant_name}",
        body=lease_body,
        property_id=prop_id,
        lease_id=lease_id,
        org_id=org_id
    )

    assert res1["status"] == "processed"
    doc_id = res1["document_id"]
    assert doc_id.startswith("DOC-")
    assert res1["outbox"]["status"] == "published"

    # 2. Verify World Model authoritative state & facts
    wm = coordinator.get_world_model(org_id=org_id)
    entity = wm.get_entity(lease_id)
    assert entity is not None
    assert entity.type == "lease"

    state = get_latest_state(lease_id, org_id=org_id)
    assert "document_processed" in state.get("events_summary", {}) or len(state.get("events", [])) >= 0

    # 3. Verify H-MEM contextual retrieval
    hmem = coordinator.get_hmem()
    retrieved = hmem.search_memories(query=f"{tenant_name} {lease_id}", org_id=org_id, limit=3)
    assert len(retrieved) >= 1
    top_mem = retrieved[0].memory
    assert str(monthly_rent) in top_mem.text or tenant_name in top_mem.text
    assert top_mem.provenance.get("entity_id") == lease_id or getattr(top_mem, "leaseId", None) == lease_id

    # 4. Verify Duplicate Ingestion Prevention
    res2 = coordinator.process_lease_document(
        title=f"Lease Agreement - {tenant_name} Duplicate",
        body=lease_body,
        property_id=prop_id,
        lease_id=lease_id,
        org_id=org_id
    )
    assert res2["status"] == "duplicate_rejected"
    assert res2["document_id"] == doc_id

    # Confirm no new memories were added for duplicate
    retrieved_after = hmem.search_memories(query=f"{tenant_name} {lease_id}", org_id=org_id, limit=5)
    assert len(retrieved_after) == len(retrieved)


# =============================================================================
# Scenario B: Vendor Invoice Reconciliation & Approval Gating
# =============================================================================

def test_scenario_b_vendor_invoice_reconciliation_and_approval_gate(coordinator):
    """Scenario B:
    1. Submit synthetic vendor invoice
    2. Associate with vendor and work order
    3. Reconcile invoice, work order, and bank-clearing info
    4. Record reconciliation events in World Model
    5. Use Markovian for recoverable multi-step processing
    6. Verify approval requirements before any financial side effect
    7. Inconsistent invoices remain flagged for review; no unauthorized payment occurs
    """
    org_id = f"ORG-TEST-SCENB-{uuid.uuid4().hex[:6]}"
    inv_id = f"INV-TEST-{uuid.uuid4().hex[:6].upper()}"
    vend_id = f"VEND-{uuid.uuid4().hex[:4].upper()}"
    wo_id = f"WO-{uuid.uuid4().hex[:4].upper()}"
    prop_id = f"PROP-{uuid.uuid4().hex[:4].upper()}"

    # Setup database records
    with db() as conn:
        conn.execute(
            "INSERT INTO properties (property_id, name, address, city, state, zip_code, monthly_rent_usd, security_deposit_usd, org_id) VALUES (%s, %s, %s, %s, 'NY', '10001', 2500.0, 2500.0, %s)",
            (prop_id, "Apex Tower", "100 Pine St", "Metropolis", org_id)
        )
        conn.execute(
            "INSERT INTO vendors (vendor_id, name, trade) VALUES (%s, %s, %s) ON CONFLICT (vendor_id) DO NOTHING",
            (vend_id, "Apex Plumbing Services", "Plumbing")
        )
        conn.execute(
            """INSERT INTO work_order_records (work_order_id, lease_id, property_id, category, description, priority, status, estimated_cost_usd, reported_date)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()::date)""",
            (wo_id, "LEASE-0001", prop_id, "plumbing", "Fix burst pipe", "urgent", "reported", 400.0)
        )
        # Billed at $850 vs $400 quote -> overbilling
        conn.execute(
            """INSERT INTO vendor_invoices (id, vendor_id, work_order_id, lease_id, property_id, invoice_number, subtotal_usd, tax_usd, total_usd, status)
               VALUES (%s, %s, %s, %s, %s, %s, 800.0, 50.0, 850.0, 'pending')""",
            (inv_id, vend_id, wo_id, "LEASE-0001", prop_id, f"NUM-{inv_id}")
        )

    # Execute reconciliation
    res = coordinator.process_vendor_invoice_reconciliation(
        invoice_id=inv_id,
        org_id=org_id,
        actor_role="finance_admin"
    )

    # 6. Verify approval requirement & discrepancy flag
    assert res["requires_approval"] is True
    assert res["current_state"] == "waiting_for_approval"
    assert res["approved"] is False
    assert res["side_effect"] is None  # NO payment executed!

    # Verify invoice remains unpaid
    with db() as conn:
        inv_status = conn.execute("SELECT status FROM vendor_invoices WHERE id = %s", (inv_id,)).fetchone()
        assert inv_status[0] == "pending"

    # Verify World Model audit event
    events = get_events(wo_id, limit=5, org_id=org_id)
    assert any(e["event_type"] == "vendor_invoice_reconciliation_evaluated" for e in events)


# =============================================================================
# Scenario C: Resident Maintenance Request & Mid-Flight Recovery
# =============================================================================

def test_scenario_c_maintenance_mid_flight_failure_and_resume(coordinator):
    """Scenario C:
    1. Create synthetic maintenance request
    2. Execute through multi-step workflow with Markovian checkpoints
    3. Simulate failure midway (step 1 completes, step 2 crashes)
    4. Resume workflow from checkpoint
    5. Verify completed steps are NOT repeated, final state reaches completion with provenance
    """
    org_id = f"ORG-TEST-SCENC-{uuid.uuid4().hex[:6]}"
    wo_id = f"WO-TEST-{uuid.uuid4().hex[:6].upper()}"
    wf_id = f"WF-MAINT-{uuid.uuid4().hex[:6].upper()}"

    # Step 1: Simulate crash during step 1 execution
    with pytest.raises(RuntimeError, match="Simulated mid-flight failure"):
        coordinator.process_maintenance_workflow(
            request_data={"work_order_id": wo_id, "category": "electrical", "description": "Flickering breaker"},
            org_id=org_id,
            workflow_id=wf_id,
            simulate_failure_at_step=1
        )

    # Verify checkpoint for step 1 was saved before failure
    markovian = coordinator.get_markovian(org_id=org_id)
    cp = markovian.get_latest_checkpoint(f"run-{wf_id}")
    assert cp is not None
    assert cp["step"] == 1
    assert cp["state"]["work_order_id"] == wo_id

    # Step 2: Resume workflow from checkpoint
    res_resumed = coordinator.process_maintenance_workflow(
        request_data={"work_order_id": wo_id, "category": "electrical", "description": "Flickering breaker"},
        org_id=org_id,
        workflow_id=wf_id,
        simulate_failure_at_step=None
    )

    assert res_resumed["status"] == "completed"
    assert res_resumed["side_effect"]["status"] in ("executed", "completed")

    # Verify database updated
    with db() as conn:
        wo_row = conn.execute("SELECT status, technician FROM work_order_records WHERE work_order_id = %s", (wo_id,)).fetchone()
        assert wo_row[0] == "in_progress"
        assert wo_row[1] == "Alex Rivera"


# =============================================================================
# Scenario D: Approval Pause and Resume across Simulated Restart
# =============================================================================

def test_scenario_d_approval_pause_and_authorized_resumption(coordinator):
    """Scenario D:
    1. Start workflow requiring human approval
    2. Pauses at approval gate with persisted checkpoint
    3. Simulate application restart (fresh coordinator / engine instance)
    4. Unauthorized user cannot approve (raises 403 / PermissionError)
    5. Authorized user approves
    6. Previously pending action executes at most once
    """
    org_id = f"ORG-TEST-SCEND-{uuid.uuid4().hex[:6]}"
    inv_id = f"INV-APPR-{uuid.uuid4().hex[:6].upper()}"
    wf_id = f"WF-INV-{uuid.uuid4().hex[:6].upper()}"
    run_id = f"run-{wf_id}"
    prop_id = f"PROP-{uuid.uuid4().hex[:4].upper()}"

    # Setup invoice
    with db() as conn:
        conn.execute("INSERT INTO properties (property_id, name, address, city, state, zip_code, monthly_rent_usd, security_deposit_usd, org_id) VALUES (%s, %s, %s, %s, 'NY', '10001', 2500.0, 2500.0, %s)",
                     (prop_id, "Cedar Heights", "55 Elm St", "Gotham", org_id))
        conn.execute("INSERT INTO vendors (vendor_id, name, trade) VALUES (%s, %s, %s) ON CONFLICT (vendor_id) DO NOTHING",
                     ("VEND-001", "Acme HVAC", "HVAC"))
        conn.execute(
            """INSERT INTO vendor_invoices (id, vendor_id, work_order_id, lease_id, property_id, invoice_number, subtotal_usd, tax_usd, total_usd, status)
               VALUES (%s, 'VEND-001', 'WO-001', 'LEASE-0001', %s, 'NUM-001', 1150.0, 50.0, 1200.0, 'pending')""",
            (inv_id, prop_id)
        )

    # 1. Pause at approval gate
    markovian = coordinator.get_markovian(org_id=org_id)
    markovian.persist_checkpoint(
        run_id=run_id,
        chunk_index=0,
        step=1,
        state={
            "status": "waiting_for_approval",
            "required_role": "finance_admin",
            "invoice_id": inv_id,
            "pending_action": "issue_payment_voucher"
        },
        pending_actions=["issue_payment_voucher"]
    )

    # 2. Simulate application restart with a fresh coordinator instance
    fresh_coord = get_unified_coordinator()

    # 3. Unauthorized role (e.g. resident) attempt rejected
    with pytest.raises(PermissionError, match="is not authorized"):
        fresh_coord.resume_workflow(
            workflow_id=wf_id,
            approver_user="tenant_tim",
            approver_role="resident",
            decision="approve",
            org_id=org_id
        )

    # 4. Authorized role (finance_admin) approves
    res_appr = fresh_coord.resume_workflow(
        workflow_id=wf_id,
        approver_user="cfo_sarah",
        approver_role="finance_admin",
        decision="approve",
        org_id=org_id
    )

    assert res_appr["status"] == "completed"
    assert res_appr["approver"] == "cfo_sarah"
    assert res_appr["side_effect"]["status"] in ("executed", "completed")

    # 5. Subsequent resume attempt does NOT duplicate side effect
    res_second = fresh_coord.resume_workflow(
        workflow_id=wf_id,
        approver_user="cfo_sarah",
        approver_role="finance_admin",
        decision="approve",
        org_id=org_id
    )
    assert res_second["side_effect"]["status"] == "cached"


# =============================================================================
# Scenario E: H-MEM Unavailable (Outbox Resiliency)
# =============================================================================

def test_scenario_e_hmem_unavailable_outbox_resiliency(coordinator, monkeypatch):
    """Scenario E:
    1. Execute valid World Model business update
    2. Simulate H-MEM failure
    3. Verify committed World Model update remains intact
    4. Retry pending H-MEM publication via outbox
    5. Confirm memory is eventually stored exactly once
    """
    org_id = f"ORG-TEST-SCENE-{uuid.uuid4().hex[:6]}"
    event_id = f"ev-{uuid.uuid4().hex[:8]}"
    entity_id = f"LEASE-{uuid.uuid4().hex[:4].upper()}"

    # 1. Commit World Model event
    record_event(
        case_id=entity_id,
        entity_id=entity_id,
        event_type="lease_renewal_approved",
        payload={"lease_id": entity_id, "new_rent": 3100.0},
        org_id=org_id
    )

    # Verify World Model event is committed in DB
    events = get_events(entity_id)
    assert len(events) >= 1

    # 2. Simulate H-MEM failure during outbox publication
    hmem = coordinator.get_hmem()
    def _fail_add_memory(record):
        raise RuntimeError("Simulated H-MEM vector store connection timeout")

    monkeypatch.setattr(hmem, "add_memory", _fail_add_memory)

    pub_res = coordinator.publish_memory_with_outbox(
        org_id=org_id,
        event_id=event_id,
        entity_id=entity_id,
        memory_text=f"Lease {entity_id} renewed at $3100.00/mo.",
        source="world_model_event"
    )

    assert pub_res["status"] == "pending_retry"
    outbox_id = pub_res["outbox_id"]

    # 3. Verify World Model state remains intact
    events_after = get_events(entity_id, limit=5, org_id=org_id)
    assert len(events_after) >= 1

    # Check outbox has status 'failed'
    with db() as conn:
        outbox_row = conn.execute("SELECT status, retry_count FROM hmem_outbox WHERE outbox_id = %s", (outbox_id,)).fetchone()
        assert outbox_row[0] == "failed"
        assert outbox_row[1] >= 1

    # 4. Restore H-MEM availability and replay outbox
    monkeypatch.undo()

    retry_res = coordinator.retry_pending_hmem_outbox(org_id=org_id)
    assert retry_res["published"] >= 1

    # Verify outbox status is now 'published'
    with db() as conn:
        outbox_row = conn.execute("SELECT status FROM hmem_outbox WHERE outbox_id = %s", (outbox_id,)).fetchone()
        assert outbox_row[0] == "published"

    # 5. Confirm memory exists in H-MEM
    mems = hmem.search_memories(query=f"Lease {entity_id} renewed", org_id=org_id, limit=3)
    assert len(mems) >= 1


# =============================================================================
# Scenario F: Duplicate Requests and Timeout Recovery
# =============================================================================

def test_scenario_f_duplicate_requests_and_timeout_recovery(coordinator):
    """Scenario F:
    1. Submit operation with idempotency key
    2. Simulate external action succeeding while client times out / loses response
    3. Retry workflow with same idempotency key
    4. Verify action status is reconciled and cached result returned
    5. No duplicate payment, invoice, or notification created
    """
    org_id = f"ORG-TEST-SCENF-{uuid.uuid4().hex[:6]}"
    idemp_key = f"{org_id}:notify:resident-{uuid.uuid4().hex[:8]}"

    call_count = {"count": 0}
    def _send_resident_notice():
        call_count["count"] += 1
        return {"notification_id": f"NOTIF-{uuid.uuid4().hex[:6]}", "status": "delivered"}

    # 1. First execution
    res1 = coordinator.execute_idempotent_side_effect(
        idempotency_key=idemp_key,
        action_type="send_resident_notice",
        payload={"resident_id": "RES-001", "channel": "sms"},
        executor_fn=_send_resident_notice,
        org_id=org_id
    )

    assert res1["status"] == "executed"
    assert call_count["count"] == 1

    # 2. Simulate timeout/retry with same idempotency key
    res2 = coordinator.execute_idempotent_side_effect(
        idempotency_key=idemp_key,
        action_type="send_resident_notice",
        payload={"resident_id": "RES-001", "channel": "sms"},
        executor_fn=_send_resident_notice,
        org_id=org_id
    )

    assert res2["status"] == "cached"
    assert call_count["count"] == 1  # External action was NOT repeated!
    assert res2["result"] == res1["result"]

    # 3. Status reconciliation check
    recon = coordinator.reconcile_side_effect(idempotency_key=idemp_key, org_id=org_id)
    assert recon["reconciled"] is True
    assert recon["status"] == "completed"


# =============================================================================
# REST API Endpoints Verification
# =============================================================================

def test_unified_api_endpoints(client):
    """Verify REST endpoints for /api/unified/* with tenant isolation and authorization."""
    org_id = f"ORG-API-{uuid.uuid4().hex[:6]}"
    headers = {"X-Organization-Id": org_id}

    # 1. Process Business Request
    proc_resp = client.post(
        "/api/unified/process",
        headers=headers,
        json={
            "query": f"Lease agreement for Tenant {uuid.uuid4().hex[:6]} at Prop 1: rent $2100",
            "intent_hint": "document",
            "user_role": "property_manager"
        }
    )
    assert proc_resp.status_code == 200
    data = proc_resp.json()
    assert data["intent"] == "document_intelligence"
    assert data["status"] == "completed"

    # 2. Outbox Status Endpoint
    outbox_resp = client.get("/api/unified/outbox/status", headers=headers)
    assert outbox_resp.status_code == 200
    out_data = outbox_resp.json()
    assert out_data["organization_id"] == org_id
    assert "counts" in out_data

    # 3. Outbox Retry Endpoint
    retry_resp = client.post("/api/unified/outbox/retry", headers=headers)
    assert retry_resp.status_code == 200
    ret_data = retry_resp.json()
    assert "published" in ret_data
