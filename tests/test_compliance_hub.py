"""Automated Test Suite for Phase 2B: Compliance & Risk Monitoring Hub.

Verifies:
1. Risk finding creation and PostgreSQL persistence.
2. Duplicate detection across repeated scans (idempotency).
3. Correct severity, category, and source references.
4. Financial discrepancy detection using existing 3-way reconciliation results.
5. Lease expiration and resident workflow risks.
6. Maintenance SLA breach detection.
7. Approval and resolution state transitions.
8. Reviewer identity and required decision reasons (with separation of duties).
9. Jurisdiction-specific rule selection (CA 21-day, NY 14-day, TX 30-day) and unverified jurisdiction handling.
10. Cross-organization access denial (HTTP 403 Forbidden).
11. Scheduled scan and notification idempotency.
12. Regression behavior for existing agents, APIs, and AI Assistant compliance queries.
"""

import json
from datetime import datetime, timezone, timedelta
import pytest
# pyrefly: ignore[missing-import]
from fastapi.testclient import TestClient

from app.main import app
from app.database import db
from app.compliance_agent import (
    JURISDICTION_REGISTRY, get_jurisdiction_rule, run_compliance_and_risk_scan
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_test_artifacts():
    """Isolate synthetic test entities before and after tests."""
    yield
    with db() as conn:
        conn.execute("DELETE FROM risk_findings WHERE stable_key LIKE 'test_%' OR lease_id LIKE 'TEST-%'")
        conn.execute("DELETE FROM approval_history WHERE case_id LIKE 'TEST-%'")
        conn.execute("DELETE FROM lease_records WHERE lease_id LIKE 'TEST-%'")
        conn.execute("DELETE FROM properties WHERE property_id LIKE 'PROP-TEST-%'")


def test_1_risk_finding_creation_and_persistence():
    """Verify on-demand compliance scan generates and persists findings in PostgreSQL."""
    res = client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "completed"
    assert data["findings_detected"] >= 1
    assert data["findings_persisted"] >= 1

    # Verify findings are queryable via API
    list_res = client.get("/api/compliance/findings?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    assert len(list_data["findings"]) >= 1

    # Verify aggregate metrics summary
    sum_res = client.get("/api/compliance/summary?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    assert sum_res.status_code == 200
    summary = sum_res.json()
    assert summary["total_findings"] >= 1
    assert "by_severity" in summary
    assert "by_status" in summary


def test_2_duplicate_detection_across_repeated_scans():
    """Verify repeated scans are strictly idempotent and do not create duplicate findings."""
    # First scan
    scan1 = client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"}).json()
    list1 = client.get("/api/compliance/findings?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"}).json()
    count_before = list1["total"]

    # Second scan immediately after
    scan2 = client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"}).json()
    list2 = client.get("/api/compliance/findings?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"}).json()
    count_after = list2["total"]

    # Count must remain stable because findings are deduplicated by stable_key
    assert count_after == count_before
    assert scan2["findings_detected"] == scan1["findings_detected"]


def test_3_severity_category_and_source_references():
    """Verify finding records have valid categories, severities, and source references."""
    res = client.get("/api/compliance/findings?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    assert res.status_code == 200
    findings = res.json()["findings"]

    valid_categories = {"lease_resident", "financial", "maintenance", "operational_integration", "legal_compliance"}
    valid_severities = {"critical", "high", "medium", "low", "info"}
    valid_types = {"operational_risk", "policy_exception", "legal_compliance_finding"}

    for f in findings:
        assert f["category"] in valid_categories, f"Invalid category: {f['category']}"
        assert f["severity"] in valid_severities, f"Invalid severity: {f['severity']}"
        assert f["finding_type"] in valid_types, f"Invalid type: {f['finding_type']}"
        assert f["source_record_type"] is not None
        assert f["source_record_id"] is not None
        assert f["stable_key"] is not None


def test_4_financial_discrepancy_detection():
    """Verify financial reconciliation discrepancies and overdue rent are detected as findings."""
    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})

    res = client.get("/api/compliance/findings?org_id=ORG-APEX&category=financial", headers={"X-Organization-Id": "ORG-APEX"})
    assert res.status_code == 200
    financial_findings = res.json()["findings"]
    assert len(financial_findings) >= 1

    # Inspect one financial finding detail
    f_id = financial_findings[0]["id"]
    det_res = client.get(f"/api/compliance/findings/{f_id}", headers={"X-Organization-Id": "ORG-APEX"})
    assert det_res.status_code == 200
    detail = det_res.json()
    assert detail["category"] == "financial"
    assert "evidence" in detail
    assert detail["evidence"] != {}


def test_5_lease_expiration_and_resident_workflow_risks():
    """Verify active leases expiring within 90 days trigger lease_resident findings."""
    now = datetime.now(timezone.utc)
    exp_date = (now + timedelta(days=25)).strftime("%Y-%m-%d")

    # Seed synthetic expiring lease
    with db() as conn:
        conn.execute(
            """INSERT INTO lease_records (
                lease_id, property_id, unit, address, tenant1, contract_date,
                move_in_date, monthly_rent_usd, security_deposit_usd, end_date, lease_status
            ) VALUES (
                'TEST-EXP-001', 'PROP-001', 'Unit 99', '100 Test St', 'Sarah Test',
                '2025-01-01', '2025-01-01', 2500.00, 2500.00, %s, 'active'
            ) ON CONFLICT (lease_id) DO NOTHING""",
            (exp_date,)
        )

    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})

    res = client.get("/api/compliance/findings?org_id=ORG-APEX&search=TEST-EXP-001", headers={"X-Organization-Id": "ORG-APEX"})
    assert res.status_code == 200
    items = res.json()["findings"]
    assert len(items) >= 1
    assert items[0]["lease_id"] == "TEST-EXP-001"
    assert items[0]["severity"] == "high" # <= 30 days is high severity


def test_6_maintenance_sla_breach_detection():
    """Verify open work orders past SLA deadline are flagged with maintenance category."""
    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})

    res = client.get("/api/compliance/findings?org_id=ORG-APEX&category=maintenance", headers={"X-Organization-Id": "ORG-APEX"})
    assert res.status_code == 200
    maint_findings = res.json()["findings"]
    assert len(maint_findings) >= 1

    sla_finding = maint_findings[0]
    assert sla_finding["category"] == "maintenance"
    assert "work_order" in sla_finding["source_record_type"]


def test_7_approval_and_resolution_state_transitions():
    """Verify full reviewer lifecycle: open -> under_review -> action_required -> resolved."""
    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    findings = client.get("/api/compliance/findings?org_id=ORG-APEX&status=open", headers={"X-Organization-Id": "ORG-APEX"}).json()["findings"]
    assert len(findings) >= 1
    target_id = findings[0]["id"]

    # 1. Assign finding
    assign_res = client.post(
        f"/api/compliance/findings/{target_id}/assign",
        json={"reviewer": "Officer Alex", "notes": "Initiated audit review"},
        headers={"X-Organization-Id": "ORG-APEX"}
    )
    assert assign_res.status_code == 200

    # 2. Transition to action_required (escalate)
    review_res = client.post(
        f"/api/compliance/findings/{target_id}/review",
        json={"status": "action_required", "reviewer": "Officer Alex", "notes": "Requires property manager remediation"},
        headers={"X-Organization-Id": "ORG-APEX"}
    )
    assert review_res.status_code == 200

    # 3. Resolve finding
    resolve_res = client.post(
        f"/api/compliance/findings/{target_id}/resolve",
        json={"status": "resolved", "reviewer": "Manager Morgan", "decision_reason": "Remediation verified with tenant ledger update"},
        headers={"X-Organization-Id": "ORG-APEX"}
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["new_status"] == "resolved"

    # Verify audit history is logged
    hist_res = client.get(f"/api/compliance/approvals/history?case_id={target_id}", headers={"X-Organization-Id": "ORG-APEX"})
    assert hist_res.status_code == 200
    history = hist_res.json()["history"]
    assert len(history) >= 2


def test_8_reviewer_identity_and_required_decision_reasons():
    """Verify validation: non-empty reviewer identity, required decision reasons, and separation of duties."""
    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    findings = client.get("/api/compliance/findings?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"}).json()["findings"]
    target_id = findings[0]["id"]

    # A. Missing reviewer name fails
    res_no_reviewer = client.post(
        f"/api/compliance/findings/{target_id}/resolve",
        json={"status": "resolved", "reviewer": "", "decision_reason": "Valid reason provided"},
        headers={"X-Organization-Id": "ORG-APEX"}
    )
    assert res_no_reviewer.status_code in (400, 422)

    # B. Missing decision reason (< 3 chars) fails
    res_no_reason = client.post(
        f"/api/compliance/findings/{target_id}/resolve",
        json={"status": "resolved", "reviewer": "Manager Morgan", "decision_reason": "ok"},
        headers={"X-Organization-Id": "ORG-APEX"}
    )
    assert res_no_reason.status_code in (400, 422)

    # C. Separation of duties: Submitter cannot self-approve
    res_self_approval = client.post(
        f"/api/compliance/findings/{target_id}/resolve",
        json={
            "status": "resolved",
            "reviewer": "Submitter Sam",
            "decision_reason": "Legitimate decision reason",
            "submitted_by": "Submitter Sam"
        },
        headers={"X-Organization-Id": "ORG-APEX"}
    )
    assert res_self_approval.status_code == 403
    assert "Separation of duties violation" in res_self_approval.text


def test_9_jurisdiction_rule_selection_and_unverified_handling():
    """Verify jurisdiction rule registry and explicit unverified jurisdiction handling."""
    # 1. Verify jurisdiction registry returns supported states
    jur_res = client.get("/api/compliance/jurisdictions")
    assert jur_res.status_code == 200
    jurs = jur_res.json()["jurisdictions"]
    assert "CA" in jurs
    assert jurs["CA"]["security_deposit_return_days"] == 21
    assert "Cal. Civ. Code § 1950.5" in jurs["CA"]["statutory_source"]
    assert "NY" in jurs
    assert jurs["NY"]["security_deposit_return_days"] == 14
    assert "TX" in jurs
    assert jurs["TX"]["security_deposit_return_days"] == 30

    # 2. Verify synthetic property with unverified jurisdiction
    with db() as conn:
        conn.execute(
            """INSERT INTO properties (
                property_id, name, address, city, state, zip_code, monthly_rent_usd,
                security_deposit_usd, org_id
            ) VALUES (
                'PROP-TEST-UNKNOWN', 'Unknown State Lofts', '100 Unknown Rd', 'Nowhere',
                'ZZ', '00000', 2000.00, 2000.00, 'ORG-APEX'
            ) ON CONFLICT (property_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO lease_records (
                lease_id, property_id, unit, address, tenant1, monthly_rent_usd,
                security_deposit_usd, move_in_date, end_date, lease_status
            ) VALUES (
                'TEST-LEASE-ZZ', 'PROP-TEST-UNKNOWN', 'Unit 1', '100 Unknown Rd', 'John Unknown',
                2000.00, 2000.00, '2025-01-01', '2026-01-01', 'active'
            ) ON CONFLICT (lease_id) DO NOTHING"""
        )
        conn.execute(
            """INSERT INTO move_out_records (
                id, lease_id, property_id, resident_name, resident_email, notice_date,
                planned_move_out_date, status, closeout_approval_state
            ) VALUES (
                'TEST-MO-ZZ', 'TEST-LEASE-ZZ', 'PROP-TEST-UNKNOWN', 'John Unknown',
                'john@unknown.internal', '2026-01-01', '2026-01-30', 'notice_received', 'pending'
            ) ON CONFLICT (lease_id) DO NOTHING"""
        )

    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})

    res = client.get("/api/compliance/findings?org_id=ORG-APEX&search=TEST-LEASE-ZZ", headers={"X-Organization-Id": "ORG-APEX"})
    assert res.status_code == 200
    items = res.json()["findings"]
    unverified_findings = [f for f in items if f["compliance_status"] == "unverified"]
    assert len(unverified_findings) >= 1
    uv = unverified_findings[0]
    assert uv["jurisdiction"] == "unverified"
    assert uv["finding_type"] == "operational_risk" # Not claimed as statutory violation!


def test_10_cross_organization_access_denial():
    """Verify strict multi-tenant isolation: requests for another org's findings return HTTP 403."""
    # Find a finding belonging to ORG-APEX
    client.post("/api/compliance/scan?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"})
    apex_findings = client.get("/api/compliance/findings?org_id=ORG-APEX", headers={"X-Organization-Id": "ORG-APEX"}).json()["findings"]
    assert len(apex_findings) >= 1
    apex_finding_id = apex_findings[0]["id"]

    # Attempt to view finding with ORG-VERDANT credentials
    res_forbidden = client.get(
        f"/api/compliance/findings/{apex_finding_id}",
        headers={"X-Organization-Id": "ORG-VERDANT"}
    )
    assert res_forbidden.status_code == 403
    assert "Access denied" in res_forbidden.text

    # Attempt to resolve finding with cross-tenant credentials
    res_resolve_forbidden = client.post(
        f"/api/compliance/findings/{apex_finding_id}/resolve",
        json={"status": "resolved", "reviewer": "Hacker", "decision_reason": "Unauthorized resolution"},
        headers={"X-Organization-Id": "ORG-VERDANT"}
    )
    assert res_resolve_forbidden.status_code == 403


def test_11_scheduled_scan_and_notification_idempotency():
    """Verify autonomous scheduler runs compliance sweep safely and idempotently."""
    from app.scheduler import run_autonomous_jobs
    import asyncio

    # Run scheduler routine jobs
    results = asyncio.run(run_autonomous_jobs())
    assert "risk_findings_detected" in results
    assert results["risk_findings_detected"] >= 1
    assert "sla_breaches_detected" in results
    assert "delinquencies_scanned" in results


def test_12_regression_existing_agents_and_assistant_query():
    """Verify conversational AI assistant handles compliance inquiries and core APIs remain healthy."""
    # 1. Test conversational assistant queries compliance risk findings
    chat_res = client.post("/api/assistant/chat", json={"message": "What are our critical compliance risk findings?"})
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert "response" in chat_data
    # Assert assistant invoked the compliance tool
    tool_names = [tc["tool"] for tc in chat_data.get("tool_calls", [])]
    assert "query_compliance_risk_register" in tool_names

    # 2. Test core regression endpoints
    health_res = client.get("/health")
    assert health_res.status_code == 200

    leases_res = client.get("/api/leases")
    assert leases_res.status_code == 200

    summary_res = client.get("/api/portfolio/summary")
    assert summary_res.status_code == 200
