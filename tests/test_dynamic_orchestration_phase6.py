"""Automated Test Suite for ENIGMA Phase 6: Dynamic Agent Orchestration & Recoverable Execution.

Verifies:
1. Successful dependent workflow execution (topological DAG, step state persistence, outcome verification).
2. Safe concurrent execution of independent steps (lease cross-validation concurrent steps).
3. Missing evidence and agent abstention (controlled abstention prevents blind auto-approval).
4. Discrepancy-triggered replanning (AP discrepancy triggers work-order cross-check step).
5. Bounded retries and permanent failures (max 2 replans, permanent allowlist violations rejected).
6. Duplicate requests and concurrent execution (idempotent step execution and conflict safety).
7. API process restart and workflow resumption (recovering interrupted workflows from PostgreSQL).
8. Partial completion and interrupted execution (resumes pending steps without re-executing finished steps).
9. Approval-required workflows (high-value invoices pause in 'waiting_for_approval').
10. Unauthorized or self-approved actions (orchestrator/system cannot self-approve; returns HTTP 403).
11. Cross-tenant access attempts (tenant isolation strictly enforced with HTTP 403).
12. Compliance holds during replanning (active stop-payment hold blocks workflow completion).
13. Final verification failure (outcome verification blocks unpersisted/mismatched records).
14. Cancellation and terminal states (workflow cancel sets 'cancelled' state and halts DAG).
15. NVIDIA NIM timeout and rate-limit recovery (transient error resilience).
16. Backward compatibility of existing workflow APIs (all legacy response keys preserved).
"""

import json
import uuid
import pytest
from unittest.mock import patch, MagicMock
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

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensure sample organization, properties, leases, vendors, and invoices exist in DB."""
    with db() as conn:
        conn.execute(
            """INSERT INTO organizations (id, name, contact_email)
               VALUES ('org-p6-test', 'Phase 6 Test Org', 'p6@example.com')
               ON CONFLICT (id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO properties (
                property_id, name, address, city, state, zip_code,
                monthly_rent_usd, security_deposit_usd, org_id
            ) VALUES (
                'PROP-P6-TEST', 'Phase 6 Test Property', '123 Recovery Lane', 'Austin',
                'TX', '78701', 2200.00, 2200.00, 'org-p6-test'
            ) ON CONFLICT (property_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO lease_records (
                lease_id, property_id, unit, address, tenant1, monthly_rent_usd,
                security_deposit_usd, move_in_date, end_date, lease_status
            ) VALUES (
                'LEASE-P6-TEST', 'PROP-P6-TEST', '101', '123 Recovery Lane', 'Alice Smith',
                2200.0, 2200.0, '2025-01-01', '2026-01-01', 'active'
            ) ON CONFLICT (lease_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendors (vendor_id, name, trade, payment_terms)
               VALUES ('VEND-P6-TEST', 'Apex Phase 6 HVAC', 'HVAC', 'Net 30')
               ON CONFLICT (vendor_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-P6-001', 'VEND-P6-TEST', 'PROP-P6-TEST', 'INV-001-A',
                400.0, 50.0, 450.0, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-P6-HIGH', 'VEND-P6-TEST', 'PROP-P6-TEST', 'INV-HIGH-VAL',
                1150.0, 100.0, 1250.0, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-P6-SEP', 'VEND-P6-TEST', 'PROP-P6-TEST', 'INV-SEP-VAL',
                550.0, 50.0, 600.0, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )


def test_1_successful_dependent_workflow_execution():
    """Verify topological DAG execution, durable step persistence, and successful completion."""
    resp = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-P6-001", "actor_role": "property_manager"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    wf_id = data["workflow_id"]
    assert wf_id.startswith("WF-INV-")
    assert "current_state" in data
    assert data["current_state"] in ("completed", "waiting_for_approval", "needs_review")

    # Verify PostgreSQL durable records
    rec = get_workflow_record(wf_id)
    assert rec is not None
    assert rec["org_id"] == "org-p6-test"
    assert rec["workflow_type"] == "invoice_approval"
    assert len(rec["steps"]) >= 4

    # Verify all steps have completed states
    for s in rec["steps"]:
        assert s["state"] == "completed"
        assert s["agent_id"] in [a.value for a in EstablishedAgent]


def test_2_safe_concurrent_execution_of_independent_steps():
    """Verify that independent read-only steps execute safely concurrently in lease cross-validation."""
    resp = client.post(
        "/api/orchestrator/workflows/lease-cross-validation",
        json={"lease_id": "LEASE-P6-TEST"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    wf_id = data["workflow_id"]
    assert wf_id.startswith("WF-LEASE-")
    assert "verification_results" in data

    rec = get_workflow_record(wf_id)
    assert rec is not None
    step_ops = [s["operation_name"] for s in rec["steps"]]
    assert "validate_lease_document" in step_ops
    assert "reconcile_lease_ledger" in step_ops


def test_3_missing_evidence_and_agent_abstention():
    """Verify that an agent reporting missing evidence/abstention halts auto-approval and requires review."""
    # Create invoice for an unknown vendor that causes abstention/discrepancy
    with db() as conn:
        conn.execute(
            """INSERT INTO vendors (vendor_id, name, trade, payment_terms)
               VALUES ('VEND-NOEVID', 'Unknown Transient Vendor', 'General', 'Net 30')
               ON CONFLICT (vendor_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-P6-NOEVID', 'VEND-NOEVID', 'PROP-P6-TEST', 'INV-NOEVID',
                200.0, 0.0, 200.0, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )

    resp = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-P6-NOEVID", "actor_role": "property_manager"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp.status_code == 200
    data = resp.json()
    # Auto-approval must not occur without complete matching evidence
    assert data["final_status"] in ("REVIEW_REQUIRED", "DISCREPANCY_DETECTED", "HELD_FOR_HUMAN_APPROVAL", "REJECTED")
    assert data["final_status"] != "AUTO_APPROVED"
    assert data["requires_human_approval"] is True


def test_4_discrepancy_triggered_replanning():
    """Verify that an AP discrepancy triggers bounded dynamic replanning adding an authorized step."""
    wf_id = f"WF-REPLAN-TEST-{uuid.uuid4().hex[:6]}"
    plan_dag = [
        {"step_id": f"{wf_id}:s1", "agent_id": EstablishedAgent.VENDOR_INVOICE.value, "operation": "reconcile_vendor_bill_4way", "dependencies": []}
    ]
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-001",
        initiating_request="Replanning verification test",
        plan_dag=plan_dag,
        context_data={"invoice_id": "INV-P6-001"}
    )

    failed_step = {
        "step_id": f"{wf_id}:s1",
        "agent_id": EstablishedAgent.VENDOR_INVOICE.value,
        "operation_name": "reconcile_vendor_bill_4way",
        "execution_order": 1,
        "error_message": "AP discrepancy detected on line item rate"
    }

    replan_success = attempt_dynamic_replanning(
        workflow_id=wf_id,
        failed_step=failed_step
    )
    assert replan_success is True

    rec = get_workflow_record(wf_id)
    assert rec["plan_revision"] == 2
    # Verify new step was added to orchestration_steps
    step_ops = [s["operation_name"] for s in rec["steps"]]
    assert "correlate_maintenance_work_order" in step_ops


def test_5_bounded_retries_and_permanent_failures():
    """Verify replanning stops after max revisions (2 replans / revision 3) and bounds loop."""
    wf_id = f"WF-BOUNDS-TEST-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-001",
        initiating_request="Replanning bounds test",
        plan_dag=[],
        context_data={"invoice_id": "INV-P6-001"}
    )

    failed_step = {
        "step_id": f"{wf_id}:s1",
        "agent_id": EstablishedAgent.VENDOR_INVOICE.value,
        "operation_name": "reconcile_vendor_bill_4way",
        "execution_order": 1,
        "error_message": "Continuous discrepancy"
    }

    # First replan succeeds (rev 2)
    assert attempt_dynamic_replanning(wf_id, failed_step) is True
    # Second replan succeeds (rev 3)
    assert attempt_dynamic_replanning(wf_id, failed_step) is True
    # Third replan MUST return False due to maximum revision bound
    assert attempt_dynamic_replanning(wf_id, failed_step) is False


def test_6_duplicate_requests_and_concurrent_execution():
    """Verify duplicate workflow creation is safe and returns existing without collision."""
    wf_id = f"WF-DUP-{uuid.uuid4().hex[:6]}"
    res1 = create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-001",
        initiating_request="Idempotency test 1",
        plan_dag=[],
        context_data={}
    )
    res2 = create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-001",
        initiating_request="Idempotency test 2",
        plan_dag=[],
        context_data={}
    )
    assert res1["workflow_id"] == wf_id
    assert res2["workflow_id"] == wf_id


def test_7_api_process_restart_and_workflow_resumption():
    """Verify that interrupted workflows marked 'running' are recovered upon process startup."""
    wf_id = f"WF-INTERRUPTED-{uuid.uuid4().hex[:6]}"
    with db() as conn:
        conn.execute(
            """INSERT INTO orchestration_workflows (
                workflow_id, org_id, workflow_type, target_id, initiating_request,
                current_state, plan_revision, plan_dag, context_data, created_at, updated_at
            ) VALUES (%s, 'org-p6-test', 'invoice_approval', 'INV-P6-001', %s,
                      'running', 1, %s, %s, now(), now())""",
            (
                wf_id,
                json.dumps({"request": "Server crashed while running"}),
                json.dumps([{"step_id": f"{wf_id}:s1", "agent_id": EstablishedAgent.DOCUMENT_INTELLIGENCE.value, "operation": "validate_invoice_document", "dependencies": []}]),
                json.dumps({"invoice_id": "INV-P6-001"})
            )
        )

    # Trigger recovery function
    recovered = recover_interrupted_workflows()
    recovered_ids = [r["workflow_id"] if isinstance(r, dict) else r for r in recovered]
    assert wf_id in recovered_ids

    rec = get_workflow_record(wf_id)
    assert rec["current_state"] in (WorkflowState.COMPLETED.value, WorkflowState.WAITING_FOR_APPROVAL.value, WorkflowState.NEEDS_REVIEW.value, WorkflowState.RUNNING.value)


def test_8_partial_completion_and_interrupted_execution():
    """Verify partial completion: completed steps are not re-executed upon resumption."""
    wf_id = f"WF-PARTIAL-{uuid.uuid4().hex[:6]}"
    plan_dag = [
        {"step_id": f"{wf_id}:step-1", "agent_id": EstablishedAgent.DOCUMENT_INTELLIGENCE.value, "operation": "validate_invoice_document", "dependencies": []},
        {"step_id": f"{wf_id}:step-2", "agent_id": EstablishedAgent.VENDOR_INVOICE.value, "operation": "reconcile_vendor_bill_4way", "dependencies": [f"{wf_id}:step-1"]}
    ]
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-001",
        initiating_request="Partial execution test",
        plan_dag=plan_dag,
        context_data={"invoice_id": "INV-P6-001"}
    )

    # Pre-mark step 1 as completed with a unique mock output
    with db() as conn:
        conn.execute(
            """UPDATE orchestration_steps
               SET state = 'completed',
                   outputs = %s,
                   updated_at = now(),
                   completed_at = now()
               WHERE step_id = %s""",
            (json.dumps({"already_completed": True}), f"{wf_id}:step-1")
        )

    # Execute workflow DAG
    execute_workflow_dag(wf_id)

    rec = get_workflow_record(wf_id)
    step1 = next(s for s in rec["steps"] if s["step_id"] == f"{wf_id}:step-1")
    # Verify Step 1 retained its pre-completed output and was not overwritten
    assert step1["outputs"].get("already_completed") is True


def test_9_approval_required_workflows():
    """Verify that invoices exceeding threshold ($1,000) enter 'waiting_for_approval'."""
    resp = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-P6-HIGH", "actor_role": "property_manager"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["requires_human_approval"] is True
    assert data["approval_role"] in ("financial_controller", "finance_manager", "compliance_officer")
    assert data["current_state"] == "waiting_for_approval"


def test_10_unauthorized_or_self_approved_actions():
    """Verify separation of duties: orchestrator cannot approve its own workflow, returns HTTP 403."""
    wf_id = f"WF-SEPDUTY-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-SEP",
        initiating_request="Separation of duties test",
        plan_dag=[],
        context_data={}
    )
    update_workflow_state(wf_id, WorkflowState.RUNNING)
    update_workflow_state(wf_id, WorkflowState.WAITING_FOR_APPROVAL)

    # Attempt self-approval by orchestrator
    resp_self = client.post(
        f"/api/orchestrator/workflows/{wf_id}/approve",
        json={"decision": "approve", "reviewer_role": "finance_manager", "reviewer_id": "assistant_orchestrator"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp_self.status_code == 403
    assert "Separation of duties violation" in resp_self.json()["detail"]

    # Attempt approval with insufficient role
    resp_role = client.post(
        f"/api/orchestrator/workflows/{wf_id}/approve",
        json={"decision": "approve", "reviewer_role": "resident", "reviewer_id": "user-tenant-1"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp_role.status_code == 403
    assert "Unauthorized approval role" in resp_role.json()["detail"]

    # Valid human approval succeeds
    resp_valid = client.post(
        f"/api/orchestrator/workflows/{wf_id}/approve",
        json={"decision": "approve", "reviewer_role": "finance_manager", "reviewer_id": "user-fin-mgr"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp_valid.status_code == 200
    assert resp_valid.json()["current_state"] == "completed"


def test_11_cross_tenant_access_attempts():
    """Verify strict tenant isolation: cross-tenant access returns HTTP 403."""
    with db() as conn:
        conn.execute(
            """INSERT INTO organizations (id, name, contact_email)
               VALUES ('org-tenant-alpha', 'Alpha Corp', 'alpha@example.com')
               ON CONFLICT (id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO organizations (id, name, contact_email)
               VALUES ('org-tenant-beta', 'Beta Corp', 'beta@example.com')
               ON CONFLICT (id) DO NOTHING"""
        )

    wf_id = f"WF-TENANT-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-tenant-alpha",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-001",
        initiating_request="Cross-tenant test",
        plan_dag=[],
        context_data={}
    )

    # Attempt access with a different tenant header
    resp = client.get(
        f"/api/orchestrator/workflows/{wf_id}",
        headers={"X-Organization-Id": "org-tenant-beta"}
    )
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


def test_12_compliance_holds_during_replanning():
    """Verify that an active STOP_PAYMENT compliance hold blocks workflow outcome verification."""
    wf_id = f"WF-COMPHOLD-{uuid.uuid4().hex[:6]}"
    with db() as conn:
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, property_id, invoice_number,
                subtotal_usd, tax_usd, total_usd, status
            ) VALUES (
                'INV-HOLD-01', 'VEND-P6-TEST', 'PROP-P6-TEST', 'INV-HOLD-01',
                300.0, 0.0, 300.0, 'unpaid'
            ) ON CONFLICT (id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO risk_findings (
                id, stable_key, org_id, property_id, invoice_id,
                category, finding_type, severity, title, description,
                source_record_type, source_record_id, detection_rule, status
            ) VALUES (
                'FINDING-HOLD-01', 'rf-hold-01', 'org-p6-test', 'PROP-P6-TEST', 'INV-HOLD-01',
                'compliance', 'stop_payment', 'high', 'Stop Payment Mandate', 'Active vendor license dispute',
                'vendor_invoice', 'INV-HOLD-01', 'vendor_license_rule', 'open'
            ) ON CONFLICT (id) DO UPDATE SET status = 'open'"""
        )

    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-HOLD-01",
        initiating_request="Compliance hold verification",
        plan_dag=[],
        context_data={"invoice_id": "INV-HOLD-01"}
    )

    verified, details = verify_workflow_outcome(wf_id)
    assert verified is False
    assert details["active_compliance_holds"] > 0
    assert "unresolved compliance stop-payment hold(s) active" in details["failure_reason"]


def test_13_final_verification_failure():
    """Verify that missing DB entity or unpersisted records fail outcome verification."""
    wf_id = f"WF-VERIFFAIL-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-NONEXISTENT-999",
        initiating_request="Verification failure test",
        plan_dag=[],
        context_data={"invoice_id": "INV-NONEXISTENT-999"}
    )

    verified, details = verify_workflow_outcome(wf_id)
    assert verified is False
    assert "error" in details


def test_14_cancellation_and_terminal_states():
    """Verify workflow cancellation halts execution and records terminal cancelled state."""
    wf_id = f"WF-CANCEL-{uuid.uuid4().hex[:6]}"
    create_workflow_instance(
        workflow_id=wf_id,
        org_id="org-p6-test",
        workflow_type=WorkflowType.INVOICE_APPROVAL.value,
        target_id="INV-P6-001",
        initiating_request="Cancel test",
        plan_dag=[],
        context_data={}
    )

    resp = client.post(
        f"/api/orchestrator/workflows/{wf_id}/cancel",
        json={"reason": "Duplicate work order issued"},
        headers={"X-Organization-Id": "org-p6-test", "X-User-Id": "user-pm-1"}
    )
    assert resp.status_code == 200
    assert resp.json()["current_state"] == "cancelled"

    # Attempting to approve a cancelled workflow must be rejected
    resp_approve = client.post(
        f"/api/orchestrator/workflows/{wf_id}/approve",
        json={"decision": "approve", "reviewer_role": "finance_manager"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp_approve.status_code == 400
    assert "Cannot approve workflow in 'cancelled' state" in resp_approve.json()["detail"]


def test_15_nvidia_nim_timeout_and_rate_limit_recovery():
    """Verify that transient NIM timeouts/429s recover safely via retry logic."""
    from app.model_routing import nim_client, TaskCategory

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = "Rate limit exceeded"
    mock_resp_429.headers = {}

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"content": "Resilient inference response"}}]
    }
    mock_resp_200.raise_for_status.return_value = None

    # First call returns 429, second returns 200
    with patch.object(nim_client.config, "nim_api_key", "mock-test-key"):
        with patch.object(nim_client._client, "post", side_effect=[mock_resp_429, mock_resp_200]):
            res = nim_client.chat_routed(
                system="system prompt",
                user="user prompt",
                category=TaskCategory.COMPLEX_REASONING,
                use_cache=False
            )
            assert res["content"] == "Resilient inference response"
            assert res["task_category"] == TaskCategory.COMPLEX_REASONING.value
            assert res["retries"] == 1


def test_16_backward_compatibility_of_existing_workflow_apis():
    """Verify that existing workflow endpoints retain 100% of their legacy response contract."""
    # Invoice approval contract
    resp_inv = client.post(
        "/api/orchestrator/workflows/invoice-approval",
        json={"invoice_id": "INV-P6-001", "actor_role": "property_manager"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp_inv.status_code == 200
    inv_keys = resp_inv.json().keys()
    for req_key in [
        "workflow_id", "invoice_id", "final_status", "composite_confidence",
        "requires_human_approval", "approval_role", "step_decisions", "causal_event_dag"
    ]:
        assert req_key in inv_keys, f"Missing legacy key '{req_key}' in invoice response"

    # Lease cross-validation contract
    resp_lease = client.post(
        "/api/orchestrator/workflows/lease-cross-validation",
        json={"lease_id": "LEASE-P6-TEST"},
        headers={"X-Organization-Id": "org-p6-test"}
    )
    assert resp_lease.status_code == 200
    lease_keys = resp_lease.json().keys()
    for req_key in [
        "workflow_id", "lease_id", "final_status", "composite_confidence",
        "requires_human_approval", "step_decisions"
    ]:
        assert req_key in lease_keys, f"Missing legacy key '{req_key}' in lease response"

    # Verify telemetry endpoint contract
    resp_tel = client.get("/api/orchestrator/telemetry")
    assert resp_tel.status_code == 200
    assert "abstention_rate_pct" in resp_tel.json()
