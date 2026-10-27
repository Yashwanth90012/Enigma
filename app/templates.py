"""Centralized Communication Template Library for EQUILIBRA.

Provides:
- PostgreSQL-backed template persistence with versioning and audit history
- 42 predefined production templates covering Rent, Lease, Maintenance, Vendor, and Compliance
- Standard variable catalog mapping to real backend records
- Variable validation, HTML escaping, and safe fallback rendering
- Organization-scoped multi-tenant customization with system default fallbacks
- Safe preview and test-send capabilities
- Direct integration with EQUILIBRA notification dispatch and deduplication
"""

import re
import html
import uuid
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .database import db
from .config import settings
from .notifications import queue_notification
from .world_model import record_event, canonical_id

# =============================================================================
# 1. Standard Variable Catalog
# =============================================================================

VARIABLE_CATALOG: Dict[str, Dict[str, Any]] = {
    # Resident & Property
    "resident_name": {
        "description": "Full name of the primary resident / tenant",
        "category": "resident",
        "sample": "Sarah Jenkins",
        "fallback": "Resident"
    },
    "resident_email": {
        "description": "Registered contact email address of the resident",
        "category": "resident",
        "sample": "tenant@example.com",
        "fallback": "tenant@example.com"
    },
    "property_name": {
        "description": "Commercial building or community name",
        "category": "property",
        "sample": "Skyline Terrace Apartments",
        "fallback": "Property Management"
    },
    "property_address": {
        "description": "Street address of the property",
        "category": "property",
        "sample": "535 Mission St, San Francisco, CA 94105",
        "fallback": "On file"
    },
    "unit_number": {
        "description": "Specific residential unit or suite number",
        "category": "property",
        "sample": "Unit 4B",
        "fallback": "Your unit"
    },
    # Lease Lifecycle
    "lease_id": {
        "description": "Unique lease agreement contract identifier",
        "category": "lease",
        "sample": "LEASE-0001",
        "fallback": "[Lease ID on file]"
    },
    "lease_start_date": {
        "description": "Effective commencement date of current lease term",
        "category": "lease",
        "sample": "2025-11-01",
        "fallback": "[Commencement Date]"
    },
    "lease_end_date": {
        "description": "Expiration date of current lease term",
        "category": "lease",
        "sample": "2026-10-31",
        "fallback": "[Expiration Date]"
    },
    "renewal_term_months": {
        "description": "Duration in months of offered lease renewal",
        "category": "lease",
        "sample": "12",
        "fallback": "12"
    },
    "rent_increase_pct": {
        "description": "Proposed rent adjustment percentage",
        "category": "lease",
        "sample": "3.5",
        "fallback": "3.5"
    },
    "proposed_rent": {
        "description": "Proposed monthly rent under renewal offer",
        "category": "lease",
        "sample": "$2,949.75",
        "fallback": "[Proposed Rent Amount]"
    },
    # Financial & Rent
    "rent_amount": {
        "description": "Contractual base monthly rent amount",
        "category": "financial",
        "sample": "$2,850.00",
        "fallback": "[Contractual Rent]"
    },
    "amount_due": {
        "description": "Current total outstanding balance due",
        "category": "financial",
        "sample": "$2,850.00",
        "fallback": "[Outstanding Balance]"
    },
    "due_date": {
        "description": "Payment due date (typically 1st of the calendar month)",
        "category": "financial",
        "sample": "November 1, 2026",
        "fallback": "1st of the month"
    },
    "grace_period_end_date": {
        "description": "Final date before late enforcement / statutory notice",
        "category": "financial",
        "sample": "November 4, 2026",
        "fallback": "4th of the month"
    },
    "payment_amount": {
        "description": "Verified monetary amount remitted or settled",
        "category": "financial",
        "sample": "$2,850.00",
        "fallback": "[Verified Remittance]"
    },
    "payment_date": {
        "description": "Verified bank clearance / ledger settlement date",
        "category": "financial",
        "sample": "October 24, 2026",
        "fallback": "[Settlement Date]"
    },
    "payment_reference": {
        "description": "Authoritative bank or ACH transaction reference code",
        "category": "financial",
        "sample": "ACH-99482103",
        "fallback": "[Reference on file]"
    },
    "payment_method": {
        "description": "Remittance instrument (ACH, Wire, Check, Portal)",
        "category": "financial",
        "sample": "ACH Electronic Funds Transfer",
        "fallback": "Electronic Transfer"
    },
    "remaining_balance": {
        "description": "Unpaid balance remaining after remittance application",
        "category": "financial",
        "sample": "$0.00",
        "fallback": "$0.00"
    },
    "payment_link": {
        "description": "Verified resident portal payment URL",
        "category": "financial",
        "sample": "https://portal.equilibra.ai/resident/pay?lease=LEASE-0001",
        "fallback": "https://portal.equilibra.ai/resident/pay"
    },
    "discrepancy_details": {
        "description": "Summary of financial reconciliation variance",
        "category": "financial",
        "sample": "Payment amount of $2,400.00 does not match invoiced amount of $2,850.00 ($450.00 variance)",
        "fallback": "Ledger variance under review"
    },
    # Maintenance
    "work_order_id": {
        "description": "Unique maintenance ticket / work order identifier",
        "category": "maintenance",
        "sample": "WO-1049",
        "fallback": "[Work Order ID]"
    },
    "maintenance_issue": {
        "description": "Description of resident reported maintenance condition",
        "category": "maintenance",
        "sample": "Kitchen sink pipe leak beneath basin",
        "fallback": "Reported issue"
    },
    "priority": {
        "description": "Triage severity priority (Emergency, High, Medium, Low)",
        "category": "maintenance",
        "sample": "High",
        "fallback": "Standard"
    },
    "category": {
        "description": "Trade discipline (Plumbing, HVAC, Electrical, Appliances)",
        "category": "maintenance",
        "sample": "Plumbing & Sinks",
        "fallback": "General Maintenance"
    },
    "appointment_date": {
        "description": "Confirmed service dispatch date",
        "category": "maintenance",
        "sample": "October 26, 2026",
        "fallback": "[To be confirmed]"
    },
    "appointment_window": {
        "description": "Confirmed technician arrival window",
        "category": "maintenance",
        "sample": "10:00 AM – 1:00 PM PST",
        "fallback": "[To be scheduled]"
    },
    "technician_name": {
        "description": "Assigned technician or trades vendor contact",
        "category": "maintenance",
        "sample": "Apex Plumbing & Sinks",
        "fallback": "Assigned Contractor"
    },
    "sla_deadline": {
        "description": "Authoritative contract SLA resolution deadline",
        "category": "maintenance",
        "sample": "October 26, 2026 14:00 UTC (24-Hour SLA)",
        "fallback": "[SLA Target]"
    },
    "elapsed_hours": {
        "description": "Hours elapsed since ticket logging or SLA breach",
        "category": "maintenance",
        "sample": "28",
        "fallback": "N/A"
    },
    "status_update_note": {
        "description": "Verified operational notes from technician or manager",
        "category": "maintenance",
        "sample": "Replacement valve sourced; technician arriving at scheduled window.",
        "fallback": "Work in progress"
    },
    "revised_eta": {
        "description": "Operational estimated completion time",
        "category": "maintenance",
        "sample": "October 27, 2026 by 5:00 PM PST (Estimated)",
        "fallback": "Estimated window pending parts arrival"
    },
    # Vendor AP
    "vendor_name": {
        "description": "Registered trade vendor business name",
        "category": "vendor",
        "sample": "Apex Plumbing & Sinks",
        "fallback": "Vendor Partner"
    },
    "vendor_email": {
        "description": "Accounts receivable contact email for vendor",
        "category": "vendor",
        "sample": "billing@vendor.example.com",
        "fallback": "billing@vendor.example.com"
    },
    "invoice_number": {
        "description": "Vendor billing invoice number",
        "category": "vendor",
        "sample": "INV-APEX-2026-088",
        "fallback": "[Invoice Number]"
    },
    "invoice_amount": {
        "description": "Total amount billed on vendor invoice",
        "category": "vendor",
        "sample": "$385.50",
        "fallback": "[Invoice Amount]"
    },
    "invoice_due_date": {
        "description": "Payment due date per agreed vendor payment terms",
        "category": "vendor",
        "sample": "November 15, 2026",
        "fallback": "Net 30"
    },
    "discrepancy_reason": {
        "description": "Explanation of vendor invoice matching exception",
        "category": "vendor",
        "sample": "Billed line item labor exceeds approved work order estimate by 2.5 hours",
        "fallback": "Itemized variance requiring clarification"
    },
    # Compliance & Operations
    "approval_reference": {
        "description": "Unique identifier of pending manager sign-off record",
        "category": "compliance",
        "sample": "APP-RENEW-LEASE-0001",
        "fallback": "[Approval Reference]"
    },
    "approval_type": {
        "description": "Type of consequential action requiring human approval",
        "category": "compliance",
        "sample": "Lease Renewal Finalization",
        "fallback": "Consequential Action"
    },
    "submitter_name": {
        "description": "Identity of user or autonomous agent submitting approval",
        "category": "compliance",
        "sample": "Resident Agent",
        "fallback": "System Workflow"
    },
    "approver_name": {
        "description": "Designated authorized reviewer / property manager",
        "category": "compliance",
        "sample": "Regional Property Manager",
        "fallback": "Authorized Manager"
    },
    "risk_finding_id": {
        "description": "Central Risk Register finding identifier",
        "category": "compliance",
        "sample": "RISK-3F4A9B10",
        "fallback": "[Risk Finding ID]"
    },
    "finding_title": {
        "description": "Concise summary title of detected risk finding",
        "category": "compliance",
        "sample": "Security Deposit Return Approaching Statutory 21-Day Window",
        "fallback": "Compliance Notice"
    },
    "finding_severity": {
        "description": "Risk severity classification (critical, high, medium, low)",
        "category": "compliance",
        "sample": "high",
        "fallback": "standard"
    },
    "jurisdiction": {
        "description": "Applicable statutory jurisdiction identifier",
        "category": "compliance",
        "sample": "US-CA (California)",
        "fallback": "Operational Standard"
    },
    "statutory_citation": {
        "description": "Authoritative legal statutory code reference",
        "category": "compliance",
        "sample": "Cal. Civ. Code § 1950.5",
        "fallback": "Applicable Tenancy Covenants"
    },
    "reviewer_notes": {
        "description": "Recorded notes and decision justification",
        "category": "compliance",
        "sample": "Itemized receipts verified; final closeout statement signed off.",
        "fallback": "Reviewed and verified"
    },
    "system_alert_details": {
        "description": "Operational diagnostics for internal engineering team",
        "category": "compliance",
        "sample": "Zetaris Lakehouse federation query timed out after 3 retries",
        "fallback": "Diagnostic alert logged"
    },
    "manager_contact": {
        "description": "Property management office email address",
        "category": "operational",
        "sample": "manager@equilibra.ai",
        "fallback": "manager@equilibra.ai"
    },
    "manager_phone": {
        "description": "Property management office telephone number",
        "category": "operational",
        "sample": "+1 (415) 555-0199",
        "fallback": "+1 (415) 555-0199"
    }
}


# =============================================================================
# 2. Database Schema & Migration
# =============================================================================

def init_templates_tables():
    """Ensure PostgreSQL schema for communication templates and versioning exists."""
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS communication_templates (
                id TEXT PRIMARY KEY,
                template_key TEXT NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                trigger_event TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                supported_variables JSONB DEFAULT '[]'::jsonb,
                required_variables JSONB DEFAULT '[]'::jsonb,
                org_id TEXT DEFAULT 'system',
                is_default BOOLEAN DEFAULT TRUE,
                enabled BOOLEAN DEFAULT TRUE,
                version INT DEFAULT 1,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE (template_key, org_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ct_key ON communication_templates(template_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS ct_cat ON communication_templates(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS ct_org ON communication_templates(org_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS communication_template_versions (
                id BIGSERIAL PRIMARY KEY,
                template_id TEXT NOT NULL REFERENCES communication_templates(id) ON DELETE CASCADE,
                template_key TEXT NOT NULL,
                version INT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                modified_by TEXT NOT NULL,
                change_summary TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ctv_tid ON communication_template_versions(template_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ctv_key ON communication_template_versions(template_key)")


# =============================================================================
# 3. 42 Predefined Production Templates Catalog
# =============================================================================

DEFAULT_TEMPLATES: List[Dict[str, Any]] = [
    # -------------------------------------------------------------------------
    # A. Rent Collection and Payment (Templates 1 to 9)
    # -------------------------------------------------------------------------
    {
        "id": "TMPL-RENT-001",
        "template_key": "upcoming_rent_reminder",
        "category": "rent_collection",
        "name": "Upcoming Rent Reminder",
        "description": "Sent automatically 3-5 days before the configured rent due date.",
        "trigger_event": "Scheduled autonomous advance rent sweep (3-5 days prior to 1st)",
        "subject": "Upcoming Rent Reminder for {{unit_number}} — Due on {{due_date}}",
        "body": """Dear {{resident_name}},

This is a friendly reminder that your monthly rent of {{rent_amount}} for {{property_name}}, {{unit_number}} is due on {{due_date}}.

Accepted Payment Methods:
• Automated ACH Direct Debit via Resident Portal (Zero transaction fees)
• Online Debit/Credit Card via Resident Portal
• Official Cashier's Check payable to {{property_name}}

Payment Instructions:
Please submit your payment by {{due_date}} to maintain your clean ledger standing. You can review your statement and submit payment securely through your resident portal:
{{payment_link}}

If you have already scheduled an automated payment, no further action is required. For any questions, please contact our leasing office at {{manager_contact}} or {{manager_phone}}.

Warm regards,
{{property_name}} Operations Team""",
        "supported_variables": ["resident_name", "rent_amount", "property_name", "unit_number", "due_date", "payment_link", "manager_contact", "manager_phone"],
        "required_variables": ["resident_name", "rent_amount", "due_date"]
    },
    {
        "id": "TMPL-RENT-002",
        "template_key": "rent_due_today",
        "category": "rent_collection",
        "name": "Rent Due Today",
        "description": "Friendly notification dispatched on the morning of the due date.",
        "trigger_event": "Autonomous due-date trigger on 1st of month",
        "subject": "Rent Due Today — {{property_name}} {{unit_number}}",
        "body": """Dear {{resident_name}},

Today is {{due_date}}, and your rent of {{amount_due}} for {{unit_number}} at {{property_name}} is now due.

Please visit your resident portal to finalize your remittance:
{{payment_link}}

Note: Under your lease agreement, a 3-calendar-day grace period is provided through {{grace_period_end_date}}. Payments confirmed prior to this date avoid late notices and balance inquiries.

Thank you for being a valued resident of {{property_name}}.

Sincerely,
Property Management""",
        "supported_variables": ["resident_name", "amount_due", "property_name", "unit_number", "due_date", "grace_period_end_date", "payment_link"],
        "required_variables": ["resident_name", "amount_due", "due_date"]
    },
    {
        "id": "TMPL-RENT-003",
        "template_key": "overdue_rent_first_reminder",
        "category": "rent_collection",
        "name": "Overdue Rent — First Reminder",
        "description": "Polite notification informing resident of an outstanding balance during grace period.",
        "trigger_event": "Autonomous grace-period sweep identifies unpaid ledger balance",
        "subject": "Notice of Outstanding Rent Balance: {{unit_number}} ({{lease_id}})",
        "body": """Dear {{resident_name}},

Our records indicate that we have not yet recorded your monthly rent payment of {{amount_due}} for {{unit_number}} at {{property_name}}, which was due on {{due_date}}.

Your contractual grace period extends through {{grace_period_end_date}}. We kindly ask that you review your ledger and submit your payment at your earliest convenience:
{{payment_link}}

If you believe this notice is in error, or if you have already submitted your payment through your bank within the past 48 hours, please reply with your payment confirmation reference so our finance team can verify bank clearing.

If you are experiencing unexpected difficulties, please contact us at {{manager_contact}} right away to discuss available arrangements.

Thank you,
{{property_name}} Accounting Office""",
        "supported_variables": ["resident_name", "amount_due", "unit_number", "property_name", "due_date", "grace_period_end_date", "payment_link", "lease_id", "manager_contact"],
        "required_variables": ["resident_name", "amount_due", "due_date", "lease_id"]
    },
    {
        "id": "TMPL-RENT-004",
        "template_key": "overdue_rent_follow_up",
        "category": "rent_collection",
        "name": "Overdue Rent — Follow-Up",
        "description": "Urgent reminder dispatched post-grace period referencing past notice.",
        "trigger_event": "Grace period expiration with unsettled rent balance",
        "subject": "Urgent Follow-Up: Past-Due Balance for {{unit_number}} — Action Required",
        "body": """Dear {{resident_name}},

We are following up regarding our previous reminder regarding your past-due rent balance. As of today, our accounting ledger reflects an outstanding balance of {{amount_due}} for {{unit_number}} at {{property_name}}.

The contractual 3-day grace period expired on {{grace_period_end_date}}. To prevent formal statutory notices or account escalation, please remit the outstanding balance immediately via your resident portal:
{{payment_link}}

If you have already remitted funds, please provide the bank transaction reference number immediately to {{manager_contact}}.

If you are facing extenuating circumstances, please contact our management office at {{manager_phone}} without delay so we may assist you before formal escalation.

Sincerely,
Property Management & Operations""",
        "supported_variables": ["resident_name", "amount_due", "unit_number", "property_name", "grace_period_end_date", "payment_link", "manager_contact", "manager_phone"],
        "required_variables": ["resident_name", "amount_due"]
    },
    {
        "id": "TMPL-RENT-005",
        "template_key": "payment_received_confirmation",
        "category": "rent_collection",
        "name": "Payment Received Confirmation",
        "description": "Confirmation issued only after verified payment recording or settlement.",
        "trigger_event": "Verified ledger payment recorded or bank transaction settled",
        "subject": "Payment Confirmation: {{payment_amount}} Recorded for {{unit_number}}",
        "body": """Dear {{resident_name}},

Thank you! We have verified and recorded your rent payment.

Transaction Details:
• Payment Amount: {{payment_amount}}
• Date Received: {{payment_date}}
• Payment Reference: {{payment_reference}}
• Payment Method: {{payment_method}}
• Property: {{property_name}}, {{unit_number}}
• Remaining Account Balance: {{remaining_balance}}

Your ledger has been updated to reflect this transaction. You can view your complete payment history and download a formal receipt at any time on your resident portal.

Thank you for your prompt payment!

Sincerely,
{{property_name}} Accounts Receivable""",
        "supported_variables": ["resident_name", "payment_amount", "payment_date", "payment_reference", "payment_method", "property_name", "unit_number", "remaining_balance"],
        "required_variables": ["resident_name", "payment_amount", "payment_date", "payment_reference"]
    },
    {
        "id": "TMPL-RENT-006",
        "template_key": "partial_payment_received",
        "category": "rent_collection",
        "name": "Partial Payment Received",
        "description": "Confirms partial remittance while accurately noting remaining balance.",
        "trigger_event": "Verified payment applied where remaining ledger balance > $0",
        "subject": "Partial Payment Receipt: {{payment_amount}} Applied — {{remaining_balance}} Remaining",
        "body": """Dear {{resident_name}},

We have received and applied your partial payment of {{payment_amount}} on {{payment_date}} (Reference: {{payment_reference}}).

Current Ledger Standing:
• Amount Applied: {{payment_amount}}
• Remaining Unpaid Balance: {{remaining_balance}}
• Unit: {{unit_number}} at {{property_name}}

Please note that this receipt confirms partial remittance only. An outstanding balance of {{remaining_balance}} remains due on your account. Please arrange for settlement of the remaining balance at your earliest opportunity via the resident portal:
{{payment_link}}

If you have questions regarding this calculation, please contact {{manager_contact}}.

Sincerely,
Accounts Receivable""",
        "supported_variables": ["resident_name", "payment_amount", "payment_date", "payment_reference", "remaining_balance", "unit_number", "property_name", "payment_link", "manager_contact"],
        "required_variables": ["resident_name", "payment_amount", "remaining_balance"]
    },
    {
        "id": "TMPL-RENT-007",
        "template_key": "payment_failed_or_unconfirmed",
        "category": "rent_collection",
        "name": "Payment Failed or Not Confirmed",
        "description": "Explains unconfirmed payment without making false debit claims.",
        "trigger_event": "Bank ACH return, card decline, or unverified transaction",
        "subject": "Payment Processing Unsuccessful for {{unit_number}} — Action Needed",
        "body": """Dear {{resident_name}},

We were unable to confirm settlement for your recent rent payment attempt of {{amount_due}} for {{unit_number}} at {{property_name}} (Reference: {{payment_reference}}).

Reason for Non-Confirmation:
Our bank clearing service reported an unconfirmed or returned transaction. Funds were not successfully credited to your lease ledger.

Safe Next Steps:
1. Please check with your banking institution to verify account status and ensure adequate funds.
2. Log in to your resident portal to retry the payment with an alternate method:
{{payment_link}}
3. If funds were debited from your personal account, please provide a bank statement snippet showing the cleared debit to {{manager_contact}} so we can initiate an immediate tracer.

Please resolve this at your earliest convenience to keep your account current.

Sincerely,
Financial Operations""",
        "supported_variables": ["resident_name", "amount_due", "unit_number", "property_name", "payment_reference", "payment_link", "manager_contact"],
        "required_variables": ["resident_name", "amount_due"]
    },
    {
        "id": "TMPL-RENT-008",
        "template_key": "payment_reconciliation_exception",
        "category": "rent_collection",
        "name": "Payment Reconciliation Exception",
        "description": "Internal alert notifying finance team of a payment variance requiring review.",
        "trigger_event": "3-way reconciliation variance detected on tenant ledger",
        "subject": "[Internal Review] Financial Reconciliation Exception: Lease {{lease_id}}",
        "body": """Attention Property Accounting & Operations:

An autonomous reconciliation exception has been flagged on tenant ledger {{lease_id}} (Property: {{property_name}}, Unit: {{unit_number}}).

Discrepancy Details:
{{discrepancy_details}}

Auditing Context:
• Lease Identifier: {{lease_id}}
• Contract Monthly Rent: {{rent_amount}}
• Current Outstanding Variance: {{amount_due}}
• Originating Source: 3-Way Reconciliation Engine (Zetaris / Postgres / Bank Ledger)

Action Required:
Please log in to the Property Manager AR Command Center to investigate the transaction match, review bank remittance records, and execute appropriate adjustment or tenant notice.

Link to Case: https://portal.equilibra.ai/admin/tenant-ar?lease={{lease_id}}

Autonomous Financial Sentry""",
        "supported_variables": ["lease_id", "property_name", "unit_number", "discrepancy_details", "rent_amount", "amount_due"],
        "required_variables": ["lease_id", "discrepancy_details"]
    },
    {
        "id": "TMPL-RENT-009",
        "template_key": "payment_plan_request_ack",
        "category": "rent_collection",
        "name": "Payment Plan Request Acknowledgement",
        "description": "Confirms receipt of resident request without implying binding approval.",
        "trigger_event": "Resident submits formal payment plan inquiry",
        "subject": "Receipt: Payment Arrangement Request for {{unit_number}}",
        "body": """Dear {{resident_name}},

We have received your formal request regarding a payment plan arrangement for your lease account at {{property_name}}, {{unit_number}} (Current Balance: {{amount_due}}).

Important Notice:
This email acknowledges receipt of your inquiry only. A submitted request does NOT constitute an approved payment plan or deferral agreement.

Next Steps:
A designated property manager will review your account standing and tenancy history within 2 business days. In the meantime, please prepare any supporting documentation regarding your proposed installment schedule.

If you have urgent questions, you may contact our leasing office directly at {{manager_contact}} or {{manager_phone}}.

Sincerely,
Property Management""",
        "supported_variables": ["resident_name", "amount_due", "property_name", "unit_number", "manager_contact", "manager_phone"],
        "required_variables": ["resident_name", "amount_due"]
    },

    # -------------------------------------------------------------------------
    # B. Lease and Resident Lifecycle (Templates 10 to 20)
    # -------------------------------------------------------------------------
    {
        "id": "TMPL-LEASE-010",
        "template_key": "lease_expiration_advance_notice",
        "category": "lease_resident",
        "name": "Lease Expiration — Advance Notice",
        "description": "Advance notification informing resident of approaching lease end date.",
        "trigger_event": "Autonomous sweep flags lease expiring in 60-90 days",
        "subject": "Advance Notice: Your Lease at {{property_name}} Expires on {{lease_end_date}}",
        "body": """Dear {{resident_name}},

We want to thank you for making {{property_name}}, {{unit_number}} your home.

Your current residential lease agreement is scheduled to expire on {{lease_end_date}}.

As a valued resident in good standing, we would love to have you remain with us. Our leasing team is currently formulating your customized lease renewal options with favorable renewal rates.

What to Expect:
• You will receive a formal Lease Renewal Offer within the next two weeks.
• If you plan to explore renewal or have upcoming schedule changes, please feel free to reach out in advance.
• If your plans require relocating at the conclusion of your lease term, please remember that your lease stipulates a 30-day advance notice requirement.

Please feel free to connect with our on-site team at {{manager_contact}} with any questions.

Warm regards,
{{property_name}} Management Team""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "lease_end_date", "manager_contact"],
        "required_variables": ["resident_name", "lease_end_date"]
    },
    {
        "id": "TMPL-LEASE-011",
        "template_key": "lease_renewal_offer",
        "category": "lease_resident",
        "name": "Lease Renewal Offer",
        "description": "Formal renewal proposal with approved terms, rates, and options.",
        "trigger_event": "Renewal offer formulated and approved for resident review",
        "subject": "Exclusive Lease Renewal Offer for {{unit_number}} — Secure Your Home",
        "body": """Dear {{resident_name}},

We are delighted to present your formal Lease Renewal Offer for {{property_name}}, {{unit_number}}!

Proposed Renewal Terms:
• Renewal Term: {{renewal_term_months}} Months
• Proposed Monthly Rent: {{proposed_rent}} (Current: {{rent_amount}}, Adjustment: +{{rent_increase_pct}}%)
• New Effective Term: From {{lease_end_date}} forward

Resident Portal Decision:
You can review the full proposed agreement and record your acceptance directly in your Resident Portal:
https://portal.equilibra.ai/resident/renewals?lease={{lease_id}}

Important Note:
Upon your recorded acceptance, our Property Operations team will conduct final administrative verification before counter-signing the finalized lease addendum.

This renewal offer is reserved for your account through 30 days prior to lease end. Please let us know your decision at your earliest convenience!

Sincerely,
Leasing Management Team""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "renewal_term_months", "proposed_rent", "rent_amount", "rent_increase_pct", "lease_end_date", "lease_id"],
        "required_variables": ["resident_name", "proposed_rent", "renewal_term_months", "lease_end_date"]
    },
    {
        "id": "TMPL-LEASE-012",
        "template_key": "lease_renewal_reminder",
        "category": "lease_resident",
        "name": "Lease Renewal Reminder",
        "description": "Follow-up reminder for pending renewal offer decision.",
        "trigger_event": "Autonomous sweep flags unaccepted offer with < 45 days remaining",
        "subject": "Reminder: Lease Renewal Offer Pending for {{unit_number}}",
        "body": """Dear {{resident_name}},

We recently sent you a renewal offer for your home at {{property_name}}, {{unit_number}} (Current lease expires {{lease_end_date}}).

We have not yet received your decision regarding your renewal. To ensure your preferred rate of {{proposed_rent}} is locked in and avoid automatic month-to-month transition premiums, please record your decision today:
https://portal.equilibra.ai/resident/renewals?lease={{lease_id}}

If you have questions or would like to discuss alternative term lengths, please contact {{manager_contact}} or call us at {{manager_phone}}.

Warm regards,
{{property_name}} Leasing Office""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "lease_end_date", "proposed_rent", "lease_id", "manager_contact", "manager_phone"],
        "required_variables": ["resident_name", "lease_end_date", "proposed_rent"]
    },
    {
        "id": "TMPL-LEASE-013",
        "template_key": "lease_renewal_approved",
        "category": "lease_resident",
        "name": "Lease Renewal Approved",
        "description": "Celebratory notice after human manager executes final approval.",
        "trigger_event": "Human Property Manager approves and finalizes lease renewal",
        "subject": "Congratulations! Your Lease Renewal for {{unit_number}} is Finalized",
        "body": """Dear {{resident_name}},

We are thrilled to confirm that your lease renewal for {{property_name}}, {{unit_number}} has received final manager approval and is officially finalized!

Finalized Terms:
• Extended Term: {{renewal_term_months}} Months
• Monthly Rent: {{proposed_rent}}
• Approved By: {{approver_name}}
• Reviewer Notes: {{reviewer_notes}}

Your updated lease agreement is now archived and accessible in your Resident Portal documents repository.

Thank you for your continued residency with us!

Warmest regards,
{{property_name}} Community Management""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "renewal_term_months", "proposed_rent", "approver_name", "reviewer_notes"],
        "required_variables": ["resident_name", "proposed_rent", "renewal_term_months"]
    },
    {
        "id": "TMPL-LEASE-014",
        "template_key": "lease_renewal_declined",
        "category": "lease_resident",
        "name": "Lease Renewal Declined or Not Finalized",
        "description": "Acknowledges decision not to renew and initiates move-out guidance.",
        "trigger_event": "Resident declines offer or manager rejects proposal",
        "subject": "Acknowledgement: Non-Renewal of Lease for {{unit_number}}",
        "body": """Dear {{resident_name}},

We have recorded that your lease agreement for {{property_name}}, {{unit_number}} will conclude on {{lease_end_date}} and will not be renewed.

We want to thank you for your time in our community. To ensure a smooth transition:
1. Please review your Move-Out Checklist available on your resident portal.
2. Ensure your forwarding address is provided for security deposit itemization and return.
3. Our maintenance coordinator will contact you to schedule your pre-move-out inspection walkthrough.

If this was selected in error or your relocation plans have changed, please contact {{manager_contact}} immediately.

Sincerely,
Property Management""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "lease_end_date", "manager_contact"],
        "required_variables": ["resident_name", "lease_end_date"]
    },
    {
        "id": "TMPL-LEASE-015",
        "template_key": "move_in_checklist_and_docs",
        "category": "lease_resident",
        "name": "Move-In Checklist and Required Documents",
        "description": "Onboarding checklist with required insurance, ID, and escrow verification.",
        "trigger_event": "Move-in checklist initiated for upcoming tenancy",
        "subject": "Welcome Home! Move-In Checklist & Required Items for {{unit_number}}",
        "body": """Dear {{resident_name}},

Welcome to {{property_name}}! We are excited to prepare for your upcoming move-in to {{unit_number}}.

To ensure a seamless key handover, please complete your onboarding checklist tasks prior to move-in:

Mandatory Onboarding Requirements:
1. Renter's Insurance Policy: Upload certificate of insurance with minimum $100,000 liability naming {{property_name}} as interested party.
2. Government Photo ID: Upload valid driver's license or passport.
3. Deposit Settlement: Confirm receipt of initial escrow security deposit and first month's rent.
4. Utility Account Transfer: Connect electrical and municipal utilities effective your move-in date.
5. Move-In Walkthrough Inspection: Schedule condition walkthrough with property staff.
6. Key & Access Credentials: Smart lock fob and building credentials issuance.

Track your progress and upload documents directly on your portal:
https://portal.equilibra.ai/resident/move-in?lease={{lease_id}}

Warm regards,
Onboarding & Resident Experience Team""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "lease_id"],
        "required_variables": ["resident_name", "lease_id"]
    },
    {
        "id": "TMPL-LEASE-016",
        "template_key": "move_in_reminder",
        "category": "lease_resident",
        "name": "Move-In Reminder",
        "description": "Sent 48 hours prior to move-in date with key collection details.",
        "trigger_event": "Move-in date approaching within 48 hours",
        "subject": "Your Move-In to {{unit_number}} is in 2 Days! Arrival Details",
        "body": """Dear {{resident_name}},

Your move-in date for {{property_name}}, {{unit_number}} is almost here!

Move-In Logistics:
• Address: {{property_address}}
• Unit: {{unit_number}}
• Key Collection Window: 9:00 AM – 5:00 PM PST
• Building Access: Your temporary access code has been activated on your Resident Portal.

Please ensure all mandatory onboarding tasks are completed prior to arrival so our team can immediately release your keys and credentials.

Welcome to the community!

{{property_name}} Leasing Team""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "property_address"],
        "required_variables": ["resident_name", "unit_number"]
    },
    {
        "id": "TMPL-LEASE-017",
        "template_key": "move_out_notice_ack",
        "category": "lease_resident",
        "name": "Move-Out Notice Acknowledgement",
        "description": "Acknowledges 30-day notice to vacate and starts statutory clock.",
        "trigger_event": "Resident submits formal 30-day notice to vacate",
        "subject": "Acknowledgement of Notice to Vacate: {{unit_number}} (Planned: {{lease_end_date}})",
        "body": """Dear {{resident_name}},

This email confirms that {{property_name}} has received your formal notice to vacate {{unit_number}} on {{lease_end_date}}.

Turnover Process & Next Steps:
1. Pre-Move-Out Inspection: Under statutory regulations, you have the right to request a pre-move-out inspection to identify any conditions that could result in deductions.
2. Key Surrender: All keys, smart fobs, and garage openers must be surrendered by 12:00 PM on your move-out date.
3. Security Deposit Accounting: Your itemized security deposit statement and any eligible refund will be disbursed within the statutory timeframe (21 days under California Civil Code § 1950.5).

Please confirm your forwarding address on your portal to avoid delays:
https://portal.equilibra.ai/resident/move-out?lease={{lease_id}}

Sincerely,
Property Management""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "lease_end_date", "lease_id"],
        "required_variables": ["resident_name", "lease_end_date"]
    },
    {
        "id": "TMPL-LEASE-018",
        "template_key": "move_out_inspection_scheduling",
        "category": "lease_resident",
        "name": "Move-Out Inspection Scheduling",
        "description": "Invites resident to schedule pre-move-out walkthrough inspection.",
        "trigger_event": "Move-out record created; scheduling window open",
        "subject": "Schedule Your Pre-Move-Out Inspection Walkthrough — {{unit_number}}",
        "body": """Dear {{resident_name}},

As your planned move-out date approaches for {{unit_number}}, we invite you to schedule your pre-move-out walkthrough inspection with our operations team.

Purpose of Pre-Inspection:
The inspection provides you with an advance list of potential repairs or cleaning requirements so you have the opportunity to address them prior to final surrender.

To schedule your preferred walkthrough appointment:
Please reply to this email or call {{manager_phone}} with your preferred dates and times between 9:00 AM and 4:00 PM Monday through Friday.

Thank you,
Maintenance & Inspections Team""",
        "supported_variables": ["resident_name", "unit_number", "manager_phone"],
        "required_variables": ["resident_name", "unit_number"]
    },
    {
        "id": "TMPL-LEASE-019",
        "template_key": "outstanding_move_out_requirements",
        "category": "lease_resident",
        "name": "Outstanding Move-Out Requirements",
        "description": "Flags uncompleted turnover requirements (forwarding address, keys).",
        "trigger_event": "Move-out turnover tasks overdue or missing forwarding address",
        "subject": "Action Needed: Pending Move-Out Tasks for {{unit_number}}",
        "body": """Dear {{resident_name}},

Our move-out coordinator notes that certain turnover requirements remain pending for your file at {{property_name}}, {{unit_number}}:

Pending Items:
• Forwarding Address on File (Strictly required for statutory security deposit disbursement)
• Surrender of all issued physical keys, parking permits, and building credentials
• Final utility transfer confirmation

Please log in to your Resident Portal to provide your forwarding address or contact our office at {{manager_contact}} right away.

Sincerely,
Turnover Operations""",
        "supported_variables": ["resident_name", "property_name", "unit_number", "manager_contact"],
        "required_variables": ["resident_name", "unit_number"]
    },
    {
        "id": "TMPL-LEASE-020",
        "template_key": "security_deposit_closeout_summary",
        "category": "lease_resident",
        "name": "Security Deposit Closeout Summary",
        "description": "Approved itemized closeout statement with statutory deductions and refund amount.",
        "trigger_event": "Property Manager executes authorized sign-off on closeout proposal",
        "subject": "Itemized Security Deposit Disposition Statement — {{unit_number}}",
        "body": """Dear {{resident_name}},

In accordance with statutory escrow closeout standards ({{statutory_citation}}), please find your itemized Security Deposit Closeout Summary for {{property_name}}, {{unit_number}}.

Closeout Accounting:
• Original Security Deposit: {{rent_amount}}
• Approved Itemized Deductions: See attached breakdown
• Reviewer Decision: Approved by {{approver_name}}
• Reviewer Notes: {{reviewer_notes}}
• Net Refund Amount Disbursed: {{payment_amount}}

A formal itemized statement and refund check (or direct bank ACH) has been directed to your forwarding address on file.

You can inspect the complete audited closeout record in your resident portal.

Thank you for your tenancy, and we wish you the very best in your next home.

Sincerely,
{{property_name}} Property Operations""",
        "supported_variables": ["resident_name", "statutory_citation", "property_name", "unit_number", "rent_amount", "approver_name", "reviewer_notes", "payment_amount"],
        "required_variables": ["resident_name", "statutory_citation", "payment_amount"]
    },

    # -------------------------------------------------------------------------
    # C. Maintenance Requests (Templates 21 to 29)
    # -------------------------------------------------------------------------
    {
        "id": "TMPL-MAINT-021",
        "template_key": "maintenance_request_received",
        "category": "maintenance",
        "name": "Maintenance Request Received",
        "description": "Confirms receipt and autonomous triage of a maintenance report.",
        "trigger_event": "Maintenance ticket logged via portal or assistant",
        "subject": "Maintenance Ticket Received: {{work_order_id}} ({{priority}} Priority)",
        "body": """Dear {{resident_name}},

We have received your maintenance service request for {{unit_number}} at {{property_name}}.

Ticket Summary:
• Ticket Number: {{work_order_id}}
• Reported Issue: {{maintenance_issue}}
• Category: {{category}}
• Priority Level: {{priority}}
• Target SLA Window: {{sla_deadline}}

What Happens Next:
Our autonomous maintenance coordinator has triaged your issue and matched it with an approved trades vendor ({{technician_name}}). A representative will contact you shortly to coordinate service access.

You can monitor real-time ticket updates and upload photos on your resident portal.

Thank you,
{{property_name}} Maintenance Department""",
        "supported_variables": ["resident_name", "unit_number", "property_name", "work_order_id", "maintenance_issue", "category", "priority", "sla_deadline", "technician_name"],
        "required_variables": ["resident_name", "work_order_id", "maintenance_issue", "priority"]
    },
    {
        "id": "TMPL-MAINT-022",
        "template_key": "maintenance_request_clarification",
        "category": "maintenance",
        "name": "Maintenance Request Clarification",
        "description": "Requests additional detail or access instructions from resident.",
        "trigger_event": "Technician or coordinator marks ticket requiring information",
        "subject": "Information Needed: Maintenance Request {{work_order_id}} ({{unit_number}})",
        "body": """Dear {{resident_name}},

Regarding your recent service request {{work_order_id}} ("{{maintenance_issue}}"), our maintenance team requires additional clarification to dispatch the appropriate technician:

Please let us know:
1. Specific location of the issue inside the unit (e.g., master bathroom vs hall bath).
2. Permission to enter: Do you grant authorization for our technician to enter if you are not home?
3. Any active pet instructions or gate security codes.

Please reply directly to this message or update your ticket on the Resident Portal.

Thank you,
Maintenance Dispatch""",
        "supported_variables": ["resident_name", "work_order_id", "maintenance_issue", "unit_number"],
        "required_variables": ["resident_name", "work_order_id"]
    },
    {
        "id": "TMPL-MAINT-023",
        "template_key": "maintenance_request_scheduled",
        "category": "maintenance",
        "name": "Maintenance Request Scheduled",
        "description": "Confirms scheduled appointment date, time window, and technician.",
        "trigger_event": "Work order assigned with scheduled appointment timestamp",
        "subject": "Service Scheduled: Ticket {{work_order_id}} on {{appointment_date}}",
        "body": """Dear {{resident_name}},

Good news! A certified technician has been scheduled to address your maintenance ticket {{work_order_id}} ("{{maintenance_issue}}").

Appointment Details:
• Scheduled Date: {{appointment_date}}
• Estimated Window: {{appointment_window}}
• Assigned Service Partner: {{technician_name}}
• Unit: {{unit_number}}, {{property_name}}

Please ensure clear access to the work area. If you need to reschedule, please contact us at least 24 hours in advance at {{manager_phone}}.

Thank you,
Maintenance Coordinator""",
        "supported_variables": ["resident_name", "work_order_id", "maintenance_issue", "appointment_date", "appointment_window", "technician_name", "unit_number", "property_name", "manager_phone"],
        "required_variables": ["resident_name", "work_order_id", "appointment_date", "appointment_window"]
    },
    {
        "id": "TMPL-MAINT-024",
        "template_key": "maintenance_appointment_reminder",
        "category": "maintenance",
        "name": "Maintenance Appointment Reminder",
        "description": "Sent 24 hours prior to scheduled technician arrival.",
        "trigger_event": "Scheduled autonomous reminder 24h prior to appointment",
        "subject": "Reminder: Maintenance Appointment Tomorrow for Ticket {{work_order_id}}",
        "body": """Dear {{resident_name}},

This is a reminder that your maintenance appointment for ticket {{work_order_id}} ("{{maintenance_issue}}") is scheduled for tomorrow, {{appointment_date}}, between {{appointment_window}}.

Assigned Technician: {{technician_name}}

If you will not be home, our technician will enter only if prior authorization to enter was granted. For any last-minute access updates, please call {{manager_phone}}.

Thank you,
{{property_name}} Maintenance Team""",
        "supported_variables": ["resident_name", "work_order_id", "maintenance_issue", "appointment_date", "appointment_window", "technician_name", "manager_phone"],
        "required_variables": ["resident_name", "work_order_id", "appointment_date"]
    },
    {
        "id": "TMPL-MAINT-025",
        "template_key": "maintenance_status_update",
        "category": "maintenance",
        "name": "Maintenance Status Update",
        "description": "Informs resident of progress, parts order, or operational update.",
        "trigger_event": "Verified work order status change or technician progress note",
        "subject": "Status Update: Maintenance Ticket {{work_order_id}}",
        "body": """Dear {{resident_name}},

Here is a verified status update regarding maintenance request {{work_order_id}} for {{unit_number}}:

Latest Update:
{{status_update_note}}

Our team is actively coordinating with {{technician_name}} to ensure complete resolution. You can review full technician notes and updates on your resident portal anytime.

Thank you for your patience!

Sincerely,
Maintenance Operations""",
        "supported_variables": ["resident_name", "work_order_id", "unit_number", "status_update_note", "technician_name"],
        "required_variables": ["resident_name", "work_order_id", "status_update_note"]
    },
    {
        "id": "TMPL-MAINT-026",
        "template_key": "maintenance_delay_notification",
        "category": "maintenance",
        "name": "Maintenance Delay Notification",
        "description": "Transparently communicates operational delays with revised estimate.",
        "trigger_event": "Work order marked delayed or awaiting specialized parts",
        "subject": "Notice of Service Delay: Maintenance Ticket {{work_order_id}}",
        "body": """Dear {{resident_name}},

We want to inform you that service on ticket {{work_order_id}} ("{{maintenance_issue}}") has encountered a temporary delay.

Reason for Delay:
{{status_update_note}}

Revised Estimated Timeline:
{{revised_eta}}

Please note that this timeline is an operational estimate. We are expediting the necessary materials with {{technician_name}} and will notify you as soon as the technician is scheduled to return.

We sincerely apologize for any inconvenience. For questions, please reach out to {{manager_contact}}.

Thank you for your understanding,
Property Management""",
        "supported_variables": ["resident_name", "work_order_id", "maintenance_issue", "status_update_note", "revised_eta", "technician_name", "manager_contact"],
        "required_variables": ["resident_name", "work_order_id", "status_update_note"]
    },
    {
        "id": "TMPL-MAINT-027",
        "template_key": "maintenance_work_completed",
        "category": "maintenance",
        "name": "Maintenance Work Completed",
        "description": "Confirms verified completion only after work order marked completed.",
        "trigger_event": "Work order status verified as 'Completed'",
        "subject": "Work Order Completed: Ticket {{work_order_id}} ({{unit_number}})",
        "body": """Dear {{resident_name}},

Our records indicate that maintenance work order {{work_order_id}} ("{{maintenance_issue}}") has been completed by {{technician_name}}.

Technician Completion Summary:
{{status_update_note}}

Please verify that the repair has been executed to your complete satisfaction. If the issue persists or if you notice any additional concerns, please reply to this email within 48 hours or report it on your Resident Portal so we may reopen the ticket.

Thank you for helping us keep {{property_name}} in great condition!

Sincerely,
Maintenance Department""",
        "supported_variables": ["resident_name", "work_order_id", "maintenance_issue", "unit_number", "technician_name", "status_update_note", "property_name"],
        "required_variables": ["resident_name", "work_order_id"]
    },
    {
        "id": "TMPL-MAINT-028",
        "template_key": "maintenance_feedback_request",
        "category": "maintenance",
        "name": "Maintenance Feedback Request",
        "description": "Invites resident feedback following verified completion.",
        "trigger_event": "Scheduled trigger 24h after verified completion",
        "subject": "How was your service experience? Ticket {{work_order_id}}",
        "body": """Dear {{resident_name}},

Now that work on ticket {{work_order_id}} ("{{maintenance_issue}}") is complete, we would love your quick feedback on the service provided by {{technician_name}}.

Did the technician arrive promptly and resolve the issue cleanly?
Please take 30 seconds to rate your experience:
https://portal.equilibra.ai/resident/feedback?ticket={{work_order_id}}

Your feedback directly impacts how we evaluate our service partners and improve operations.

Thank you!
Resident Experience Team""",
        "supported_variables": ["resident_name", "work_order_id", "maintenance_issue", "technician_name"],
        "required_variables": ["resident_name", "work_order_id"]
    },
    {
        "id": "TMPL-MAINT-029",
        "template_key": "maintenance_sla_escalation_internal",
        "category": "maintenance",
        "name": "Maintenance SLA Escalation — Internal",
        "description": "Internal alert notifying operations leadership of an approaching or breached SLA.",
        "trigger_event": "Autonomous maintenance SLA monitor detects elapsed deadline",
        "subject": "[CRITICAL SLA BREACH] Work Order {{work_order_id}} Overdue ({{priority}})",
        "body": """Attention Property Operations & Facilities Management:

An autonomous SLA breach escalation has been triggered for maintenance work order {{work_order_id}}.

Ticket Details:
• Work Order ID: {{work_order_id}}
• Priority: {{priority}}
• Category: {{category}}
• Assigned Service Partner: {{technician_name}}
• Contract SLA Deadline: {{sla_deadline}}
• Hours Overdue: {{elapsed_hours}} Hours

Reported Condition:
{{maintenance_issue}}

Action Required:
Immediate operational intervention is required. Please contact the assigned contractor immediately or reassign to backup emergency trades provider.

Link to Ticket: https://portal.equilibra.ai/admin/work-orders?id={{work_order_id}}

EQUILIBRA Autonomous Facilities Sentry""",
        "supported_variables": ["work_order_id", "priority", "category", "technician_name", "sla_deadline", "elapsed_hours", "maintenance_issue"],
        "required_variables": ["work_order_id", "priority", "sla_deadline", "elapsed_hours"]
    },

    # -------------------------------------------------------------------------
    # D. Vendor and Invoice Communications (Templates 30 to 34)
    # -------------------------------------------------------------------------
    {
        "id": "TMPL-VEND-030",
        "template_key": "vendor_invoice_received",
        "category": "vendor_invoice",
        "name": "Vendor Invoice Received",
        "description": "Confirms receipt of vendor invoice and entry into 4-way matching queue.",
        "trigger_event": "Vendor bill ingested via PDF OCR or API",
        "subject": "Invoice Received: {{invoice_number}} — {{vendor_name}}",
        "body": """Dear {{vendor_name}},

This email confirms that EQUILIBRA Accounts Payable has received your invoice {{invoice_number}} for {{invoice_amount}} regarding work order {{work_order_id}}.

Processing Pipeline:
Your invoice has been entered into our automated 4-way matching pipeline (Purchase Order/Work Order, Invoiced Scope, Bank Clearance, and Manager Authorization).

Agreed Payment Terms: {{invoice_due_date}}
Payment will be remitted in accordance with your registered vendor agreement upon successful matching.

You can check processing status on your Vendor AP portal.

Thank you,
Accounts Payable Team""",
        "supported_variables": ["vendor_name", "invoice_number", "invoice_amount", "work_order_id", "invoice_due_date"],
        "required_variables": ["vendor_name", "invoice_number", "invoice_amount"]
    },
    {
        "id": "TMPL-VEND-031",
        "template_key": "vendor_invoice_missing_info",
        "category": "vendor_invoice",
        "name": "Vendor Invoice Missing Information",
        "description": "Notifies vendor of missing work order reference, W-9, or line-item receipts.",
        "trigger_event": "Document intelligence flags missing required invoice metadata",
        "subject": "Action Needed: Missing Information for Invoice {{invoice_number}}",
        "body": """Dear {{vendor_name}},

We are reviewing invoice {{invoice_number}} (Amount: {{invoice_amount}}), but our Accounts Payable system cannot proceed with matching due to missing information:

Required Clarification:
{{discrepancy_reason}}

Please upload the revised invoice or supporting documentation via your vendor portal or reply directly with the corrected document so we can release payment without delay.

Thank you,
Accounts Payable Department""",
        "supported_variables": ["vendor_name", "invoice_number", "invoice_amount", "discrepancy_reason"],
        "required_variables": ["vendor_name", "invoice_number", "discrepancy_reason"]
    },
    {
        "id": "TMPL-VEND-032",
        "template_key": "invoice_discrepancy_internal_review",
        "category": "vendor_invoice",
        "name": "Invoice Discrepancy — Internal Review",
        "description": "Internal alert for AP coordinator when 4-way match detects pricing/scope variance.",
        "trigger_event": "4-way matching detects overbilling, unauthorized surcharge, or scope mismatch",
        "subject": "[AP Variance Alert] Invoice {{invoice_number}} Failed Matching ({{vendor_name}})",
        "body": """Attention Accounts Payable & Property Controller:

An autonomous reconciliation exception was triggered during 4-way AP matching for vendor invoice {{invoice_number}} (Vendor: {{vendor_name}}).

Matching Discrepancy:
{{discrepancy_reason}}

Audit Summary:
• Invoiced Amount: {{invoice_amount}}
• Linked Work Order: {{work_order_id}}
• Detection Rule: AP Matching Policy & Authorization Thresholds

Action Required:
Please inspect the line-item variances, review the technician field completion report, and decide whether to approve an authorized variance adjustment or issue a credit inquiry to {{vendor_name}}.

Link to Review: https://portal.equilibra.ai/admin/vendor-ap?invoice={{invoice_number}}

Autonomous AP Reconciliation Sentry""",
        "supported_variables": ["invoice_number", "vendor_name", "discrepancy_reason", "invoice_amount", "work_order_id"],
        "required_variables": ["invoice_number", "vendor_name", "discrepancy_reason"]
    },
    {
        "id": "TMPL-VEND-033",
        "template_key": "invoice_approval_notification",
        "category": "vendor_invoice",
        "name": "Invoice Approval Notification",
        "description": "Informs vendor that invoice has completed 4-way match and is approved for payment.",
        "trigger_event": "Authorized manager signs off on matched vendor bill",
        "subject": "Invoice Approved for Payment: {{invoice_number}} — {{vendor_name}}",
        "body": """Dear {{vendor_name}},

We are pleased to inform you that your invoice {{invoice_number}} for {{invoice_amount}} has completed verification and is approved for payment.

Remittance Schedule:
• Approved Amount: {{invoice_amount}}
• Target Disbursement Date: {{invoice_due_date}}
• Remittance Method: Direct ACH Transfer / Check on file

Thank you for your partnership and quality service to our property portfolio.

Sincerely,
Accounts Payable Operations""",
        "supported_variables": ["vendor_name", "invoice_number", "invoice_amount", "invoice_due_date"],
        "required_variables": ["vendor_name", "invoice_number", "invoice_amount"]
    },
    {
        "id": "TMPL-VEND-034",
        "template_key": "payment_status_update_to_vendor",
        "category": "vendor_invoice",
        "name": "Payment Status Update to Vendor",
        "description": "Confirms disbursement details, check number, or ACH clearance to vendor.",
        "trigger_event": "Vendor disbursement remitted and confirmed in ledger",
        "subject": "Remittance Advice: Payment Processed for Invoice {{invoice_number}}",
        "body": """Dear {{vendor_name}},

Remittance Advice:
We have processed payment for your invoice {{invoice_number}}.

Payment Details:
• Amount Remitted: {{payment_amount}}
• Payment Reference / Check Number: {{payment_reference}}
• Date Processed: {{payment_date}}
• Method: {{payment_method}}

Please allow 1-2 standard banking business days for electronic funds clearance to reflect in your designated account.

Thank you for your business.

Sincerely,
Treasury & Accounts Payable""",
        "supported_variables": ["vendor_name", "invoice_number", "payment_amount", "payment_reference", "payment_date", "payment_method"],
        "required_variables": ["vendor_name", "invoice_number", "payment_amount", "payment_reference"]
    },

    # -------------------------------------------------------------------------
    # E. Compliance, Risk and Internal Operations (Templates 35 to 42)
    # -------------------------------------------------------------------------
    {
        "id": "TMPL-COMP-035",
        "template_key": "approval_required",
        "category": "compliance_risk",
        "name": "Approval Required",
        "description": "Notifies designated manager that a high-consequence action requires review.",
        "trigger_event": "High-cost work order, renewal finalization, or deposit proposal queued",
        "subject": "[Action Required] Manager Sign-Off Required: {{approval_type}} ({{approval_reference}})",
        "body": """Attention {{approver_name}}:

A consequential action requires your authorized review and human sign-off:

Approval Request Details:
• Type: {{approval_type}}
• Reference ID: {{approval_reference}}
• Submitted By: {{submitter_name}}
• Jurisdiction / Policy Standard: {{jurisdiction}}

Separation of Duties Notice:
In accordance with internal compliance governance, this action cannot be executed autonomously or self-approved by the submitter. Your formal sign-off is required before contractual or financial commitments take effect.

Execute Review: https://portal.equilibra.ai/admin/compliance/approvals?id={{approval_reference}}

EQUILIBRA Governance & Compliance Controller""",
        "supported_variables": ["approver_name", "approval_type", "approval_reference", "submitter_name", "jurisdiction"],
        "required_variables": ["approver_name", "approval_type", "approval_reference"]
    },
    {
        "id": "TMPL-COMP-036",
        "template_key": "approval_reminder",
        "category": "compliance_risk",
        "name": "Approval Reminder",
        "description": "Follow-up reminder for pending managerial sign-off approaching statutory/SLA target.",
        "trigger_event": "Autonomous sweep flags pending approval untouched for > 24 hours",
        "subject": "Reminder: Pending Sign-Off Required for {{approval_reference}} ({{approval_type}})",
        "body": """Attention {{approver_name}}:

This is a reminder that approval request {{approval_reference}} ("{{approval_type}}") submitted by {{submitter_name}} remains pending your review.

Timely resolution is critical to maintain compliance deadlines and service level agreements.

Please access your approval queue to record your decision:
https://portal.equilibra.ai/admin/compliance/approvals?id={{approval_reference}}

Thank you,
Compliance Operations""",
        "supported_variables": ["approver_name", "approval_reference", "approval_type", "submitter_name"],
        "required_variables": ["approver_name", "approval_reference"]
    },
    {
        "id": "TMPL-COMP-037",
        "template_key": "overdue_approval_escalation",
        "category": "compliance_risk",
        "name": "Overdue Approval Escalation",
        "description": "Escalates overdue pending approval to regional director or executive oversight.",
        "trigger_event": "Pending approval exceeds maximum threshold (e.g., 48 hours or statutory clock)",
        "subject": "[ESCALATION] Overdue Approval Gate: {{approval_reference}} (Breached Window)",
        "body": """Attention Regional Property Director & Head of Asset Management:

An urgent escalation has been issued for pending approval {{approval_reference}} ({{approval_type}}).

Escalation Summary:
• Action: {{approval_type}}
• Primary Reviewer: {{approver_name}}
• Submitter: {{submitter_name}}
• Statutory / Policy Risk: {{statutory_citation}}
• Status: OVERDUE

This item has breached standard turnaround windows and risks non-compliance with statutory covenants or tenant service thresholds. Immediate executive intervention is requested.

Link to Queue: https://portal.equilibra.ai/admin/compliance/approvals?id={{approval_reference}}

EQUILIBRA Autonomous Risk Escalation""",
        "supported_variables": ["approval_reference", "approval_type", "approver_name", "submitter_name", "statutory_citation"],
        "required_variables": ["approval_reference", "approval_type", "approver_name"]
    },
    {
        "id": "TMPL-COMP-038",
        "template_key": "compliance_finding_assigned",
        "category": "compliance_risk",
        "name": "Compliance Finding Assigned",
        "description": "Notifies designated compliance officer of a new risk finding in their portfolio.",
        "trigger_event": "Central Risk Register scan detects operational/legal risk finding",
        "subject": "[Finding Assigned] {{finding_severity}} Severity: {{finding_title}} ({{risk_finding_id}})",
        "body": """Attention {{approver_name}}:

A new risk finding has been detected and assigned to your compliance oversight queue:

Finding Details:
• Finding ID: {{risk_finding_id}}
• Severity: {{finding_severity}}
• Title: {{finding_title}}
• Jurisdiction: {{jurisdiction}}
• Applicable Statutory Source: {{statutory_citation}}

Detection Analysis:
This finding was generated by autonomous policy scanning against active portfolio records. Please review the underlying evidence and determine the appropriate corrective action.

Inspect Finding: https://portal.equilibra.ai/admin/compliance/findings?id={{risk_finding_id}}

Central Risk Register""",
        "supported_variables": ["approver_name", "risk_finding_id", "finding_severity", "finding_title", "jurisdiction", "statutory_citation"],
        "required_variables": ["approver_name", "risk_finding_id", "finding_severity", "finding_title"]
    },
    {
        "id": "TMPL-COMP-039",
        "template_key": "compliance_finding_resolved",
        "category": "compliance_risk",
        "name": "Compliance Finding Resolved",
        "description": "Records verified resolution and archival of a risk finding.",
        "trigger_event": "Reviewer signs off on finding resolution with mandatory notes",
        "subject": "Finding Resolved: {{risk_finding_id}} — {{finding_title}}",
        "body": """Attention Compliance & Risk Committee:

Risk finding {{risk_finding_id}} ("{{finding_title}}") has been reviewed, resolved, and archived in the Central Risk Register.

Resolution Summary:
• Resolved By: {{approver_name}}
• Decision Reason & Corrective Evidence: {{reviewer_notes}}
• Statutory Jurisdiction: {{jurisdiction}}
• Archived Timestamp: Logged in immutable World Model

The status of this item has been updated to 'Resolved'. No further action is required.

Central Risk Register""",
        "supported_variables": ["risk_finding_id", "finding_title", "approver_name", "reviewer_notes", "jurisdiction"],
        "required_variables": ["risk_finding_id", "finding_title", "approver_name", "reviewer_notes"]
    },
    {
        "id": "TMPL-COMP-040",
        "template_key": "document_verification_required",
        "category": "compliance_risk",
        "name": "Document Verification Required",
        "description": "Flags document exception requiring human validation (e.g. low OCR confidence).",
        "trigger_event": "Document ingestion exception or confidence score below threshold",
        "subject": "[Document Audit] Manual Verification Required for Ingested File",
        "body": """Attention Document Intelligence Coordinator:

An uploaded lease agreement or vendor invoice requires manual validation:

Details:
• Document Reference: {{approval_reference}}
• Property: {{property_name}}
• Detection Reason: OCR text extraction confidence or structural covenant extraction requires human verification.

Please review the side-by-side extracted text against the original PDF and verify the contractual covenants.

Audit Link: https://portal.equilibra.ai/admin/documents?id={{approval_reference}}

Document Intelligence Sentry""",
        "supported_variables": ["approval_reference", "property_name"],
        "required_variables": ["approval_reference"]
    },
    {
        "id": "TMPL-COMP-041",
        "template_key": "workflow_failure_internal_alert",
        "category": "compliance_risk",
        "name": "Workflow Failure — Internal Alert",
        "description": "Alerts engineering & operations team when an autonomous background workflow fails.",
        "trigger_event": "Scheduler or agent job catches unhandled execution error",
        "subject": "[SYSTEM ALERT] Autonomous Workflow Failure: {{finding_title}}",
        "body": """Attention EQUILIBRA Systems Operations & Engineering:

An autonomous background agent workflow has encountered an execution exception:

Alert Details:
• Workflow Category: {{category}}
• Error Summary: {{finding_title}}
• System Diagnostic Details: {{system_alert_details}}

The background scheduler safe boundary isolated this error and maintained application uptime. Please inspect application logs and container health to rectify the underlying exception.

EQUILIBRA Reliability & Resilience Engine""",
        "supported_variables": ["category", "finding_title", "system_alert_details"],
        "required_variables": ["category", "finding_title", "system_alert_details"]
    },
    {
        "id": "TMPL-COMP-042",
        "template_key": "financial_data_source_unavailable_alert",
        "category": "compliance_risk",
        "name": "Financial Data Source Unavailable — Internal Alert",
        "description": "Alerts finance ops when Zetaris federation fails and fallback data is activated.",
        "trigger_event": "Zetaris connection fails, activating fixture_fallback mode",
        "subject": "[DATA SOURCE ALERT] Zetaris Lakehouse Federation Unavailable — Fallback Active",
        "body": """Attention Treasury, Financial Operations & Data Platform Team:

The primary financial data source connection (Zetaris Lakehouse Federation) has encountered connectivity issues:

Diagnostic Details:
{{system_alert_details}}

Operational Safeguard:
EQUILIBRA has automatically activated transparent fallback mode ('fixture_fallback'). All financial screens and reconciliation views are currently displaying explicit fallback source attribution badges.

Live accounting mutations and external writebacks are restricted until upstream federation is re-established and verified.

Please check container connectivity (POST /api/integrations/zetaris/health) and verify metastore catalog mounts.

EQUILIBRA Data Governance & Resilience Engine""",
        "supported_variables": ["system_alert_details"],
        "required_variables": ["system_alert_details"]
    }
]


# =============================================================================
# 4. Template Engine: Validation, Rendering, and Persistence
# =============================================================================

def seed_default_templates(force: bool = False):
    """Seed or update all 42 standard templates in PostgreSQL under org_id='system'."""
    init_templates_tables()
    with db() as conn:
        for t in DEFAULT_TEMPLATES:
            # Check if exists
            existing = conn.execute(
                "SELECT id, version FROM communication_templates WHERE template_key = %s AND org_id = 'system'",
                (t["template_key"],)
            ).fetchone()

            if not existing:
                conn.execute("""
                    INSERT INTO communication_templates (
                        id, template_key, category, name, description, trigger_event,
                        subject, body, supported_variables, required_variables,
                        org_id, is_default, enabled, version, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'system', TRUE, TRUE, 1, now(), now())
                """, (
                    t["id"], t["template_key"], t["category"], t["name"], t["description"],
                    t["trigger_event"], t["subject"], t["body"],
                    json.dumps(t["supported_variables"]), json.dumps(t["required_variables"])
                ))
                # Insert initial version record
                conn.execute("""
                    INSERT INTO communication_template_versions (
                        template_id, template_key, version, subject, body, modified_by, change_summary
                    ) VALUES (%s, %s, 1, %s, %s, 'System Seed', 'Initial predefined system template release')
                """, (t["id"], t["template_key"], t["subject"], t["body"]))
            elif force:
                conn.execute("""
                    UPDATE communication_templates SET
                        category = %s, name = %s, description = %s, trigger_event = %s,
                        subject = %s, body = %s, supported_variables = %s, required_variables = %s,
                        updated_at = now()
                    WHERE template_key = %s AND org_id = 'system'
                """, (
                    t["category"], t["name"], t["description"], t["trigger_event"],
                    t["subject"], t["body"], json.dumps(t["supported_variables"]), json.dumps(t["required_variables"]),
                    t["template_key"]
                ))


def validate_template_variables(
    template_data: Any,
    context: Dict[str, Any]
) -> Tuple[bool, List[str], List[str]]:
    """Validate context against template required and supported variables.
    
    Returns:
        (is_valid, missing_required_vars, unsupported_vars_detected)
    """
    if isinstance(template_data, str):
        template_data = get_template(template_data) or {}

    required = template_data.get("required_variables") or []
    if isinstance(required, str):
        try:
            required = json.loads(required)
        except Exception:
            required = []
            
    supported = template_data.get("supported_variables") or []
    if isinstance(supported, str):
        try:
            supported = json.loads(supported)
        except Exception:
            supported = []

    missing = [var for var in required if not context.get(var) and context.get(var) != 0]

    # Find any variables used in body/subject that are completely absent from global catalog
    content = (template_data.get("subject", "") + " " + template_data.get("body", ""))
    used_in_text = re.findall(r'\{\{([a-zA-Z0-9_]+)\}\}', content)
    unsupported = [v for v in used_in_text if v not in VARIABLE_CATALOG]

    is_valid = len(missing) == 0
    return is_valid, missing, unsupported


def render_template_text(
    template_str: str,
    context: Dict[str, Any],
    escape_html_content: bool = False
) -> str:
    """Safely render double-curly variables in template string with graceful fallbacks."""
    def replacer(match):
        var_name = match.group(1)
        val = context.get(var_name)
        if val is not None and val != "":
            str_val = str(val)
            return html.escape(str_val) if escape_html_content else str_val
        
        # Check catalog fallback
        cat_info = VARIABLE_CATALOG.get(var_name)
        if cat_info and cat_info.get("fallback"):
            return cat_info["fallback"]
        return f"[{var_name}]"

    return re.sub(r'\{\{([a-zA-Z0-9_]+)\}\}', replacer, template_str)


def render_template(
    template_obj: Any,
    context: Dict[str, Any],
    escape_html: bool = False
) -> Dict[str, Any]:
    """Render full subject, body, and resolution details for a template."""
    if isinstance(template_obj, str):
        template_obj = get_template(template_obj) or {}

    is_valid, missing, unsupported = validate_template_variables(template_obj, context)

    rendered_subject = render_template_text(template_obj.get("subject", ""), context, escape_html)
    rendered_body = render_template_text(template_obj.get("body", ""), context, escape_html)

    # Resolution report mapping
    resolved_vars = {}
    content = template_obj.get("subject", "") + " " + template_obj.get("body", "")
    used_vars = set(re.findall(r'\{\{([a-zA-Z0-9_]+)\}\}', content))
    for v in used_vars:
        if v in context and context[v] is not None:
            resolved_vars[v] = {"value": context[v], "source": "provided_context"}
        else:
            cat_entry = VARIABLE_CATALOG.get(v, {})
            resolved_vars[v] = {
                "value": cat_entry.get("fallback", f"[{v}]"),
                "source": "fallback_default" if cat_entry else "undefined"
            }

    return {
        "template_id": template_obj.get("id"),
        "template_key": template_obj.get("template_key"),
        "is_valid": is_valid,
        "missing_required_variables": missing,
        "unsupported_variables": unsupported,
        "rendered_subject": rendered_subject,
        "rendered_body": rendered_body,
        "resolved_variables": resolved_vars
    }


def get_template(
    template_key_or_id: str,
    org_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve template, prioritizing organization override over system default."""
    init_templates_tables()
    sql = """
        SELECT id, template_key, category, name, description, trigger_event,
               subject, body, supported_variables, required_variables,
               org_id, is_default, enabled, version, created_at, updated_at
        FROM communication_templates
        WHERE (id = %s OR template_key = %s)
    """
    params = [template_key_or_id, template_key_or_id]

    with db() as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return None

    # If org_id provided, prefer row with that org_id
    selected_row = None
    if org_id and org_id != "system":
        for r in rows:
            if r[10] == org_id:
                selected_row = r
                break

    if not selected_row:
        # Fallback to system default
        for r in rows:
            if r[10] == "system":
                selected_row = r
                break

    if not selected_row and rows:
        selected_row = rows[0]

    return _row_to_template_dict(selected_row)


get_template_by_key = get_template


def list_templates(
    category: Optional[str] = None,
    search: Optional[str] = None,
    org_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List templates with optional category, search filter, and tenant isolation."""
    init_templates_tables()
    sql = """
        SELECT id, template_key, category, name, description, trigger_event,
               subject, body, supported_variables, required_variables,
               org_id, is_default, enabled, version, created_at, updated_at
        FROM communication_templates
    """
    conditions = []
    params = []

    if category and category != "all":
        category_map = {
            "rent": "rent_collection",
            "lease": "lease_lifecycle",
            "vendor": "vendor_operations",
            "compliance": "compliance_risk",
        }
        normalized_cat = category_map.get(category.lower(), category.lower())
        conditions.append("category = %s")
        params.append(normalized_cat)

    if org_id and org_id != "all":
        conditions.append("(org_id = %s OR org_id = 'system')")
        params.append(org_id)
    else:
        # Default view shows system templates + organization overrides
        pass

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY category ASC, name ASC"

    with db() as conn:
        rows = conn.execute(sql, params).fetchall()

    templates = [_row_to_template_dict(r) for r in rows]

    # If both org override and system exist for same key, deduplicate prioritizing org override
    if org_id and org_id != "all":
        deduped = {}
        for t in templates:
            k = t["template_key"]
            if k not in deduped:
                deduped[k] = t
            elif t["org_id"] == org_id:
                deduped[k] = t
        templates = list(deduped.values())

    # Text search
    if search and search.strip():
        q = search.lower()
        templates = [
            t for t in templates
            if q in t["name"].lower()
            or q in t["template_key"].lower()
            or q in (t["description"] or "").lower()
            or q in t["subject"].lower()
        ]

    return templates


def update_template(
    template_id: str,
    subject: str,
    body: str,
    enabled: Optional[bool] = None,
    change_summary: Optional[str] = "Template updated",
    modified_by: str = "Authorized Administrator",
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Update template and archive new immutable version in audit history."""
    init_templates_tables()
    existing = get_template(template_id, org_id)
    if not existing:
        raise ValueError(f"Template '{template_id}' not found.")

    new_version = existing["version"] + 1
    new_enabled = enabled if enabled is not None else existing["enabled"]

    # Check if this is a system default being customized by an organization
    target_org = org_id or existing["org_id"]
    if target_org != "system" and existing["org_id"] == "system":
        # Create an org-specific override instead of mutating global system default
        new_id = f"TMPL-{target_org}-{existing['template_key']}"
        with db() as conn:
            conn.execute("""
                INSERT INTO communication_templates (
                    id, template_key, category, name, description, trigger_event,
                    subject, body, supported_variables, required_variables,
                    org_id, is_default, enabled, version, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, 1, now(), now())
                ON CONFLICT (template_key, org_id) DO UPDATE SET
                    subject = excluded.subject,
                    body = excluded.body,
                    enabled = excluded.enabled,
                    version = communication_templates.version + 1,
                    updated_at = now()
            """, (
                new_id, existing["template_key"], existing["category"],
                existing["name"], existing["description"], existing["trigger_event"],
                subject, body, json.dumps(existing["supported_variables"]),
                json.dumps(existing["required_variables"]), target_org, new_enabled
            ))
            conn.execute("""
                INSERT INTO communication_template_versions (
                    template_id, template_key, version, subject, body, modified_by, change_summary
                ) VALUES (%s, %s, 1, %s, %s, %s, %s)
            """, (new_id, existing["template_key"], subject, body, modified_by, f"Organization customization for {target_org}: {change_summary}"))

        return get_template(new_id, target_org)

    with db() as conn:
        conn.execute("""
            UPDATE communication_templates SET
                subject = %s,
                body = %s,
                enabled = %s,
                version = %s,
                updated_at = now()
            WHERE id = %s
        """, (subject, body, new_enabled, new_version, existing["id"]))

        conn.execute("""
            INSERT INTO communication_template_versions (
                template_id, template_key, version, subject, body, modified_by, change_summary
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (existing["id"], existing["template_key"], new_version, subject, body, modified_by, change_summary))

    return get_template(existing["id"], target_org)


def get_template_version_history(template_id: str) -> List[Dict[str, Any]]:
    """Retrieve full audit version history for a given template."""
    init_templates_tables()
    with db() as conn:
        rows = conn.execute("""
            SELECT id, template_id, template_key, version, subject, body,
                   modified_by, change_summary, created_at
            FROM communication_template_versions
            WHERE template_id = %s
            ORDER BY version DESC
        """, (template_id,)).fetchall()

    return [
        {
            "id": r[0],
            "template_id": r[1],
            "template_key": r[2],
            "version": r[3],
            "subject": r[4],
            "body": r[5],
            "modified_by": r[6],
            "change_summary": r[7],
            "created_at": r[8].isoformat() if hasattr(r[8], "isoformat") else str(r[8])
        }
        for r in rows
    ]


def build_sample_context() -> Dict[str, Any]:
    """Provide rich representative mock dataset for instant template preview."""
    return {
        k: v["sample"]
        for k, v in VARIABLE_CATALOG.items()
    }


def send_templated_notification(
    template_key: str,
    recipient_email: str,
    recipient_type: str,
    context: Dict[str, Any],
    event_key: Optional[str] = None,
    org_id: Optional[str] = None,
    simulate_delivery: bool = True
) -> Dict[str, Any]:
    """Execute end-to-end templated notification dispatch with deduplication and preference check."""
    template = get_template(template_key, org_id)
    if not template:
        # Graceful fallback to raw title/message if template not found
        title = context.get("title", f"Notification: {template_key}")
        message = context.get("message", "A notification event occurred.")
        return queue_notification(
            recipient_email=recipient_email,
            recipient_type=recipient_type,
            title=title,
            message=message,
            category="general",
            event_key=event_key,
            simulate_delivery=simulate_delivery
        )

    if not template.get("enabled", True):
        return {
            "id": None,
            "status": "skipped_disabled",
            "message": f"Template '{template_key}' is currently disabled in configuration.",
            "duplicate": False
        }

    rendered = render_template(template, context, escape_html=False)

    # Queue durable notification
    result = queue_notification(
        recipient_email=recipient_email,
        recipient_type=recipient_type,
        title=rendered["rendered_subject"],
        message=rendered["rendered_body"],
        category=template["category"],
        event_key=event_key,
        simulate_delivery=simulate_delivery
    )

    result["template_id"] = template["id"]
    result["template_key"] = template["template_key"]
    result["template_version"] = template["version"]
    return result


def _row_to_template_dict(r: Any) -> Dict[str, Any]:
    d = {
        "id": r[0],
        "template_key": r[1],
        "category": r[2],
        "name": r[3],
        "description": r[4],
        "trigger_event": r[5],
        "subject": r[6],
        "body": r[7],
        "supported_variables": r[8] if isinstance(r[8], list) else (json.loads(r[8]) if r[8] else []),
        "required_variables": r[9] if isinstance(r[9], list) else (json.loads(r[9]) if r[9] else []),
        "org_id": r[10],
        "is_default": bool(r[11]),
        "enabled": bool(r[12]),
        "version": r[13],
        "created_at": r[14].isoformat() if hasattr(r[14], "isoformat") else str(r[14]),
        "updated_at": r[15].isoformat() if hasattr(r[15], "isoformat") else str(r[15])
    }
    try:
        d["version_history"] = get_template_version_history(r[0])
    except Exception:
        d["version_history"] = []
    return d
