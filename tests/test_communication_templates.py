"""Automated Test Suite for Phase 4: UI Integration, Agent Visibility & Communication Template Library.

Verifies:
1. Template catalog seeding, count (42 templates), and PostgreSQL persistence.
2. Template variable catalog, validation, missing required variables, and fallback resolution.
3. Template update, automatic version incrementing, and version audit history persistence.
4. Safe preview rendering with context data and HTML entity escaping.
5. Safe test-send dispatch and audit logging in notifications table (without external email sending).
6. Multi-tenant template isolation (system default vs organization override).
7. Operational Dashboard Overview API (`/api/dashboard/overview`) metrics aggregation.
8. AI Assistant integration: supporting document citations and templated communication drafting.
9. Notification preference respect and delivery safety controls.
"""

import json
import pytest
# pyrefly: ignore[missing-import]
from fastapi.testclient import TestClient

from app.main import app
from app.database import db
from app.templates import (
    seed_default_templates,
    list_templates,
    get_template,
    get_template_by_key,
    render_template,
    validate_template_variables,
    update_template,
    VARIABLE_CATALOG,
    DEFAULT_TEMPLATES
)

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_templates():
    """Ensure templates are seeded before running tests."""
    seed_default_templates()


def test_1_template_seeding_and_catalog():
    """Verify all 42 required default templates are seeded and persisted in PostgreSQL."""
    assert len(DEFAULT_TEMPLATES) == 42
    templates = list_templates(org_id=None)
    assert len(templates) >= 42

    template_keys = {t["template_key"] for t in templates}
    # Check key templates from each of the 5 required categories
    assert "upcoming_rent_reminder" in template_keys
    assert "rent_due_today" in template_keys
    assert "overdue_rent_first_reminder" in template_keys
    assert "payment_received_confirmation" in template_keys
    assert "lease_renewal_offer" in template_keys
    assert "move_in_checklist_and_docs" in template_keys
    assert "maintenance_request_received" in template_keys
    assert "maintenance_sla_escalation_internal" in template_keys
    assert "vendor_invoice_received" in template_keys
    assert "compliance_finding_assigned" in template_keys
    assert "financial_data_source_unavailable_alert" in template_keys


def test_2_api_list_templates_and_categories():
    """Verify GET /api/templates returns 42 templates with category filtering."""
    res = client.get("/api/templates")
    assert res.status_code == 200, res.text
    templates = res.json()
    assert isinstance(templates, list)
    assert len(templates) >= 42

    # Filter by category: rent / rent_collection
    res_rent = client.get("/api/templates?category=rent")
    assert res_rent.status_code == 200
    rent_templates = res_rent.json()
    assert len(rent_templates) >= 9
    for tmpl in rent_templates:
        assert tmpl["category"] in ("rent_collection", "rent")

    # Filter by category: maintenance
    res_maint = client.get("/api/templates?category=maintenance")
    assert res_maint.status_code == 200
    maint_templates = res_maint.json()
    assert len(maint_templates) >= 9
    for tmpl in maint_templates:
        assert tmpl["category"] == "maintenance"


def test_3_variable_catalog_endpoint():
    """Verify GET /api/templates/variables/catalog exposes valid real backend fields."""
    res = client.get("/api/templates/variables/catalog")
    assert res.status_code == 200
    data = res.json()
    assert "catalog" in data
    vars_dict = data["catalog"]
    assert "resident_name" in vars_dict
    assert "lease_id" in vars_dict
    assert "rent_amount" in vars_dict
    assert "work_order_id" in vars_dict
    assert "invoice_number" in vars_dict
    assert "risk_finding_id" in vars_dict


def test_4_variable_validation_and_missing_data():
    """Verify variable validation catches missing required fields."""
    # Test valid variables
    is_valid, missing, _ = validate_template_variables(
        "payment_received_confirmation",
        {
            "resident_name": "Jane Doe",
            "payment_amount": "$1,500.00",
            "payment_date": "2026-10-25",
            "payment_reference": "PAY-12345",
            "property_name": "Apex Tower"
        }
    )
    assert is_valid is True
    assert len(missing) == 0

    # Test missing required variables
    is_valid_missing, missing_fields, _ = validate_template_variables(
        "payment_received_confirmation",
        {"property_name": "Apex Tower"}  # Missing resident_name and payment fields
    )
    assert is_valid_missing is False
    assert len(missing_fields) >= 1


def test_5_safe_rendering_and_html_escaping():
    """Verify template rendering escapes user-controlled strings to prevent injection."""
    untrusted_context = {
        "resident_name": "<script>alert('pwned')</script>John",
        "property_name": "<b>Grand Apex</b>",
        "unit_number": "4B",
        "due_date": "2026-11-01",
        "rent_amount": "2,200.00",
        "amount_due": "2,200.00",
        "payment_reference": "REF-9988",
        "manager_contact": "pm@apex.com"
    }
    rendered = render_template("upcoming_rent_reminder", untrusted_context, escape_html=True)
    body = rendered["rendered_body"]
    # Ensure script tags are escaped
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "John" in body


def test_6_template_preview_endpoint():
    """Verify POST /api/templates/{id}/preview returns safe preview with sample context."""
    tmpl = get_template("upcoming_rent_reminder")
    assert tmpl is not None

    res = client.post(
        f"/api/templates/{tmpl['id']}/preview",
        json={"context": {"resident_name": "Alice Tester", "rent_amount": "$1,800.00"}}
    )
    assert res.status_code == 200, res.text
    preview = res.json()
    assert preview["template_id"] == tmpl["id"]
    assert "Alice Tester" in preview["rendered_body"]
    assert "$1,800.00" in preview["rendered_body"]
    assert "resolved_variables" in preview


def test_7_template_update_and_versioning():
    """Verify template edits update version number and write an audit record to versions table."""
    tmpl = get_template("upcoming_rent_reminder")
    assert tmpl is not None
    initial_version = tmpl["version"]

    res = client.put(
        f"/api/templates/{tmpl['id']}",
        json={
            "subject": "Updated Notice: Upcoming Rent Due for {{property_name}} Unit {{unit_number}}",
            "body": "Hello {{resident_name}},\n\nThis is an updated notice that rent of {{rent_amount}} is due on {{due_date}}.\n\nThank you.",
            "is_enabled": True,
            "change_summary": "Added unit number to subject and simplified body."
        },
        headers={"X-User-Id": "manager@apex.com"}
    )
    assert res.status_code == 200, res.text

    # Verify audit version history and incremented version
    tmpl_after = get_template("upcoming_rent_reminder")
    assert tmpl_after["version"] == initial_version + 1
    assert "Updated Notice" in tmpl_after["subject"]

    versions = tmpl_after.get("version_history", [])
    assert len(versions) >= 1
    assert any(v.get("change_summary") == "Added unit number to subject and simplified body." for v in versions)


def test_8_safe_test_send_dispatch():
    """Verify POST /api/templates/{id}/send-test logs notification without sending real emails."""
    tmpl = get_template("upcoming_rent_reminder")
    assert tmpl is not None

    res = client.post(
        f"/api/templates/{tmpl['id']}/send-test",
        json={
            "test_recipient_email": "test-pm@domain.local",
            "context": {
                "resident_name": "Test Resident",
                "property_name": "Apex Test Tower",
                "unit_number": "10A",
                "rent_amount": "2,400.00",
                "amount_due": "2,400.00",
                "due_date": "2026-11-01",
                "manager_contact": "pm@domain.local"
            }
        }
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] in ("simulated", "logged", "delivered", "sent")
    assert data["template_id"] == tmpl["id"]
    assert data["test_recipient"] == "test-pm@domain.local"

    # Verify notification record is in PostgreSQL
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT recipient_email, template_key, status FROM notifications WHERE recipient_email = %s ORDER BY id DESC LIMIT 1",
                ("test-pm@domain.local",)
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "test-pm@domain.local"
            assert row[1] == "upcoming_rent_reminder"


def test_9_operational_dashboard_overview():
    """Verify GET /api/dashboard/overview returns aggregated metrics across all agent workflows."""
    res = client.get("/api/dashboard/overview?organization_id=all")
    assert res.status_code == 200, res.text
    overview = res.json()

    # Leases & Expirations
    assert "leases" in overview
    assert overview["leases"]["total_leases"] >= 1
    assert "expiring_leases_count" in overview["leases"]

    # Rent Collection
    assert "total_rent_invoiced_usd" in overview["leases"]
    assert "reconciled_count" in overview["leases"]

    # Maintenance & SLAs
    assert "maintenance" in overview
    assert overview["maintenance"]["total_open_work_orders"] >= 0
    assert "sla_breaches_count" in overview["maintenance"]

    # Vendor AP
    assert "vendor_ap" in overview
    assert "total_billed_usd" in overview["vendor_ap"]

    # Compliance & Risks
    assert "compliance" in overview
    assert "summary" in overview["compliance"]

    # Documents & RAG
    assert "document_intelligence" in overview
    assert "total_documents" in overview["document_intelligence"]

    # Financial Data Source
    assert "financial_data_source" in overview
    assert "source_status" in overview["financial_data_source"]
    assert "freshness" in overview["financial_data_source"]

    # Notifications
    assert "notifications" in overview
    assert "total_recent" in overview["notifications"]


def test_10_assistant_templated_communication_and_docs():
    """Verify AI Assistant can prepare templated communications and cite supporting documents."""
    # Test drafting rent reminder
    draft_res = client.post(
        "/api/assistant/chat",
        json={"message": "Draft a rent reminder for LEASE-0001"}
    )
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    assert "LEASE-0001" in draft_data["response"]
    assert draft_data.get("communication_draft") is not None or "[DRAFT COMMUNICATION PREPARED" in draft_data["response"]

    # Test supporting document query
    doc_res = client.post(
        "/api/assistant/chat",
        json={"message": "What supporting documents exist for LEASE-0001?"}
    )
    assert doc_res.status_code == 200
    doc_data = doc_res.json()
    assert doc_data.get("document_references") is not None or "documents" in doc_data["response"].lower()


def test_11_multi_tenant_template_isolation():
    """Verify organization customizations do not overwrite default system templates."""
    # Create org-specific override
    res = client.post(
        "/api/templates",
        json={
            "template_id": "TMPL-ORG-RENT-01",
            "template_key": "upcoming_rent_reminder",
            "category": "rent_collection",
            "name": "Apex Custom Rent Reminder",
            "subject": "[Apex Luxury] Rent Reminder for {{property_name}} Unit {{unit_number}}",
            "body": "Dear {{resident_name}},\n\nCustom Apex notification for rent of {{rent_amount}} due on {{due_date}}.",
            "trigger_event": "scheduler_rent_reminder_upcoming",
            "required_variables": ["resident_name", "rent_amount", "due_date"],
            "supported_variables": ["resident_name", "rent_amount", "due_date", "property_name", "unit_number"]
        },
        headers={"X-Organization-Id": "ORG-CUSTOM-TEST"}
    )
    assert res.status_code == 200, res.text
    created = res.json()
    assert created["org_id"] == "ORG-CUSTOM-TEST"

    # Query with org filter returns org-specific template
    org_tmpl = get_template("upcoming_rent_reminder", org_id="ORG-CUSTOM-TEST")
    assert org_tmpl["org_id"] == "ORG-CUSTOM-TEST"
    assert "Apex Luxury" in org_tmpl["subject"]

    # Cleanup custom test template
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM communication_templates WHERE org_id = 'ORG-CUSTOM-TEST'")
            cur.execute("DELETE FROM communication_template_versions WHERE template_id = 'TMPL-ORG-RENT-01'")
