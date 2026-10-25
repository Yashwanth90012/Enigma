# EQUILIBRA — Phase 4: UI Integration, Agent Visibility & Communication Template Library Report

**Author:** DeepMind Antigravity Advanced Agentic Pair Programmer  
**Date:** October 25, 2026  
**Scope:** Integration of frontend UI with backend agent capabilities, centralized communication template engine with 42 predefined email templates, variable catalogs, safe preview, test-send capability, and operational telemetry.  

---

## 1. Executive Summary & Mandatory Codebase Audit Gap Analysis

### A. Context & Purpose
The backend of EQUILIBRA implements multi-agent autonomous property workflows across document intelligence, property and lease management, resident lifecycle, maintenance and SLA monitoring, financial operations (3-way lease AR and 4-way vendor AP matching), compliance and risk monitoring, scheduling, notifications, semantic RAG, and Zetaris virtual financial data lakehouse integration.

**Phase 4 Goal:** Update and integrate the existing frontend UI with all implemented backend capabilities without rebuilding the application, preserve the design system, connect UI components to actual backend APIs, and establish a centralized, persistent communication template library supporting 42 predefined email templates across 5 operational categories.

### B. Mandatory Codebase Audit & Gap Analysis

| Component / Subsystem | Pre-Phase 4 State | Phase 4 Implemented State | Connected Backend API | Status |
|---|---|---|---|---|
| **Main Operational Dashboard** | Displayed high-level static KPI cards with lease count and AR totals. Lacked unified cross-agent telemetry for expirations, SLAs, vendor exceptions, compliance risks, and data freshness. | Mounted `OperationalDashboardOverview` at top of workspace with real-time operational telemetry rack across all workflows. | `GET /api/dashboard/overview` | `COMPLETE` |
| **Resident & Lease UI** | Resident portal had tabs for move-in, renewal, move-out, preferences, but lacked direct verification gating on payment settlement status and template-driven communication previews. | Added verified ledger settlement gating (`reconciliation_status` check), and exposed communication preferences & message logs with template tracking. | `GET /api/leases/{id}/details`, `POST /api/finance/pay`, `GET /api/notifications` | `COMPLETE` |
| **Rent Collection & Financial UI** | Showed 3-way reconciliation without consolidated ledger status badges or clear live Zetaris vs PostgreSQL fixture indicators. | Added live financial source indicator pill, data freshness timestamps, and overdue balance tracking. | `GET /api/dashboard/overview`, `GET /api/portfolio/summary` | `COMPLETE` |
| **Maintenance UI** | Work orders lacked real-time SLA countdown badges, escalation tracking, and template-driven clarification/completion notices. | Connected real-time SLA breach counters, emergency triage indicators, and automated communication templates. | `GET /api/work-orders`, `GET /api/dashboard/overview` | `COMPLETE` |
| **Vendor & Invoice AP UI** | 4-way matching existed, but lacked vendor communication logs and explicit uncashed float detection badges. | Integrated vendor communication trigger support and uncashed float detection (`$36,000` gross billed tracking). | `GET /api/vendor-invoices/summary`, `GET /api/dashboard/overview` | `COMPLETE` |
| **Compliance & Risk UI** | Had compliance scan and risk findings, but lacked centralized template-based approval notifications and escalations. | Linked risk findings and pending approval gates to compliance email templates with immutable version audit tracking. | `GET /api/compliance/findings`, `GET /api/compliance/summary` | `COMPLETE` |
| **Document Intelligence & AI Assistant** | Assistant provided deterministic/Meterless text without structured supporting document reference citations or draft communication preview cards. | Integrated `query_supporting_documents` and `prepare_templated_communication` tools into assistant, returning structured citations and preview cards. | `POST /api/assistant/chat` | `COMPLETE` |
| **Communication Template Library** | Completely missing. Notifications used hardcoded strings inside Python modules. | Built full PostgreSQL-backed communication template engine (`communication_templates`, `communication_template_versions`) with 42 predefined templates, variable validation, HTML escaping, and UI manager. | `GET/POST/PUT /api/templates`, `POST /api/templates/{id}/preview`, `POST /api/templates/{id}/send-test` | `COMPLETE` |

---

## 2. Updated UI Screens & Connected Backend APIs

### 1. Navigation & Hub Switcher (`HubSwitcher.jsx`)
- Added dedicated **Communication Templates** tab (`activeHub === 'templates'`) with `42 Templates` status pill.
- Maintained exact design system tokens (`var(--surface)`, `var(--primary)`, `var(--emerald)`, `var(--rose)`).

### 2. Operational Command Center (`OperationalDashboardOverview.jsx` mounted in `TenantARModule.jsx` and `App.jsx`)
Aggregates real-time telemetry from `GET /api/dashboard/overview`:
- **Leases & Expirations:** Real count of active leases (100) and upcoming 90-day lease expirations (57) based on real lease dates.
- **Rent AR & Overdue:** Total gross invoiced ($214,650.00), settled zero-variance leases (92), flagged overdue discrepancies (8), and uncollected variance ($9,750.00).
- **Maintenance & SLAs:** Total open work orders (98), urgent/emergency count (12), and active SLA breaches (78).
- **Vendor AP 4-Way Matching:** Total billed AP ($36,000.00), pending uncashed float checks (2), disputed invoices (1), and unpaid bills (16).
- **Compliance & Risk Register:** Active compliance findings (7), critical/high risks (0), and pending human approval gates (0).
- **Document Intelligence:** Total vectorized documents (94), indexed chunks in pgvector (9,300), and OCR verification readiness.
- **Financial Data Fabric Status:** Shows active connection (`Zetaris Virtual Data Fabric` vs `PostgreSQL Live Fixture`) with real-time sync timestamp.
- **Notification Pipeline:** Dispatches logged, delivery failure counters, and simulated vs sent counters.

### 3. Centralized Communication Templates Hub (`CommunicationTemplatesHub.jsx`)
A complete, enterprise-grade management UI providing:
- **Category Filter Tabs:** All (42), Rent Collection (9), Lease Lifecycle (11), Maintenance (9), Vendor Operations (5), Compliance & Risk (8).
- **Search & Filtering:** Real-time search across template names, keys, subjects, and trigger events.
- **Template Editor:** Subject line input, multi-line body editor, clickable variable insertion chips from the real backend catalog, and change summary notes.
- **Safe Live Preview Panel:** Renders dynamic email preview with sender/recipient envelopes, resolved variable values, and highlights missing variables in red before sending.
- **Variable Catalog Drawer:** Lists all 35+ backend fields with descriptions, fallback values, and sample data.
- **Audit Version History Tab:** Lists immutable version history (`version`, `modified_by`, `change_summary`, `created_at`).
- **Safe Test-Send Modal:** Allows property managers to dispatch test emails strictly to a configured test recipient (e.g. `manager@domain.local`) without contacting residents.

### 4. Resident Portal Settlement Gating (`ResidentPortal.jsx`)
- Enforced strict financial verification logic: rent payments are **never** displayed as successful merely because a payment request was submitted.
- Only displays `✓ Verified Settlement` when `reconciliation_status` is verified (`settled`, `reconciled`, or `matched`) on the PostgreSQL ledger.
- If pending bank clearing or awaiting webhook confirmation, clearly displays `⏳ Payment Submitted (Pending Settlement Verification)`.

### 5. AI Assistant Citations & Templated Drafting (`EquilibraAssistant.jsx`)
- Integrated structured `documentReferences` badge pills showing document ID, title, and document type.
- Integrated `communicationDraft` preview card rendering the rendered template subject, recipient, template key, and body directly in the chat stream.
- Added quick action buttons: `✉️ Draft Rent Reminder`, `📄 Supporting Docs`, `📊 LEASE-0001`, `🚨 Active Emergencies`.

---

## 3. Communication Template Library Architecture & Database Persistence

### Database Schema (PostgreSQL)

#### Table: `communication_templates`
```sql
CREATE TABLE IF NOT EXISTS communication_templates (
    id VARCHAR(64) PRIMARY KEY,
    template_key VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    trigger_event VARCHAR(255),
    subject VARCHAR(512) NOT NULL,
    body TEXT NOT NULL,
    supported_variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    org_id VARCHAR(64) DEFAULT 'system',
    is_default BOOLEAN DEFAULT TRUE,
    enabled BOOLEAN DEFAULT TRUE,
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_template_key_org UNIQUE (template_key, org_id)
);
```

#### Table: `communication_template_versions`
```sql
CREATE TABLE IF NOT EXISTS communication_template_versions (
    id SERIAL PRIMARY KEY,
    template_id VARCHAR(64) NOT NULL,
    template_key VARCHAR(128) NOT NULL,
    version INT NOT NULL,
    subject VARCHAR(512) NOT NULL,
    body TEXT NOT NULL,
    modified_by VARCHAR(128) DEFAULT 'Property Manager',
    change_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 4. Documented 42 Predefined Production Templates Catalog

| # | Template ID | Template Key | Category | Trigger Event | Required Variables | Supported Variables |
|---|---|---|---|---|---|---|
| **1** | `TMPL-RENT-001` | `upcoming_rent_reminder` | `rent_collection` | Scheduled autonomous advance rent sweep (3-5 days prior to 1st) | `resident_name`, `rent_amount`, `due_date`, `unit_number` | `resident_name`, `property_name`, `unit_number`, `rent_amount`, `due_date`, `payment_link`, `manager_contact`, `manager_phone` |
| **2** | `TMPL-RENT-002` | `rent_due_today` | `rent_collection` | Scheduled autonomous sweep on 1st of month | `resident_name`, `rent_amount`, `due_date`, `unit_number` | `resident_name`, `property_name`, `unit_number`, `rent_amount`, `due_date`, `payment_link`, `manager_contact` |
| **3** | `TMPL-RENT-003` | `overdue_rent_first_reminder` | `rent_collection` | Scheduled sweep after grace period expiration (Day 4/5) with positive variance | `resident_name`, `amount_due`, `unit_number`, `due_date` | `resident_name`, `property_name`, `unit_number`, `amount_due`, `rent_amount`, `due_date`, `grace_period_days`, `payment_link`, `manager_contact` |
| **4** | `TMPL-RENT-004` | `overdue_rent_follow_up` | `rent_collection` | Scheduled 10-day overdue escalation sweep | `resident_name`, `amount_due`, `unit_number`, `due_date` | `resident_name`, `property_name`, `unit_number`, `amount_due`, `rent_amount`, `due_date`, `payment_link`, `manager_contact`, `manager_phone` |
| **5** | `TMPL-RENT-005` | `payment_received_confirmation` | `rent_collection` | Verified ledger payment recorded or bank transaction settled | `resident_name`, `payment_amount`, `payment_date`, `payment_reference` | `resident_name`, `payment_amount`, `payment_date`, `payment_reference`, `payment_method`, `property_name`, `unit_number`, `remaining_balance` |
| **6** | `TMPL-RENT-006` | `partial_payment_received` | `rent_collection` | Verified ledger payment recorded with remaining positive variance | `resident_name`, `payment_amount`, `remaining_balance`, `payment_reference` | `resident_name`, `payment_amount`, `payment_date`, `payment_reference`, `remaining_balance`, `property_name`, `unit_number`, `due_date`, `manager_contact` |
| **7** | `TMPL-RENT-007` | `payment_failed_or_unconfirmed` | `rent_collection` | Webhook return code, ACH return (NSF), or card decline event | `resident_name`, `amount_due`, `unit_number`, `payment_reference` | `resident_name`, `amount_due`, `payment_reference`, `payment_date`, `property_name`, `unit_number`, `payment_link`, `manager_contact` |
| **8** | `TMPL-RENT-008` | `payment_reconciliation_exception` | `rent_collection` | Autonomous 3-way reconciliation audit flag (unmatched bank transaction or ledger discrepancy) | `lease_id`, `amount_due`, `payment_reference` | `lease_id`, `resident_name`, `property_name`, `unit_number`, `amount_due`, `payment_reference`, `ledger_balance`, `discrepancy_details` |
| **9** | `TMPL-RENT-009` | `payment_plan_request_ack` | `rent_collection` | Resident payment arrangement submission via portal | `resident_name`, `amount_due`, `unit_number` | `resident_name`, `amount_due`, `property_name`, `unit_number`, `manager_contact`, `manager_phone` |
| **10** | `TMPL-LEAS-010` | `lease_expiration_advance_notice` | `lease_lifecycle` | Autonomous expiration scanner (90/60 days prior to lease end) | `resident_name`, `lease_id`, `lease_end_date`, `unit_number` | `resident_name`, `lease_id`, `lease_end_date`, `property_name`, `unit_number`, `manager_contact`, `manager_phone` |
| **11** | `TMPL-LEAS-011` | `lease_renewal_offer` | `lease_lifecycle` | Approved renewal offer generated by Resident Agent or human manager | `resident_name`, `lease_id`, `renewal_rent_amount`, `renewal_term_months`, `offer_expiration_date` | `resident_name`, `lease_id`, `property_name`, `unit_number`, `renewal_rent_amount`, `renewal_term_months`, `offer_expiration_date`, `portal_url`, `manager_contact` |
| **12** | `TMPL-LEAS-012` | `lease_renewal_reminder` | `lease_lifecycle` | Renewal offer pending expiration reminder sweep (14 days prior to offer expiration) | `resident_name`, `lease_id`, `offer_expiration_date` | `resident_name`, `lease_id`, `property_name`, `unit_number`, `renewal_rent_amount`, `offer_expiration_date`, `portal_url`, `manager_contact` |
| **13** | `TMPL-LEAS-013` | `lease_renewal_approved` | `lease_lifecycle` | Manager approval gate finalized and lease term updated | `resident_name`, `lease_id`, `renewal_rent_amount`, `lease_end_date` | `resident_name`, `lease_id`, `property_name`, `unit_number`, `renewal_rent_amount`, `renewal_term_months`, `lease_end_date`, `manager_contact` |
| **14** | `TMPL-LEAS-014` | `lease_renewal_declined` | `lease_lifecycle` | Resident declines renewal or offer expiration without response | `resident_name`, `lease_id`, `lease_end_date`, `unit_number` | `resident_name`, `lease_id`, `property_name`, `unit_number`, `lease_end_date`, `manager_contact`, `manager_phone` |
| **15** | `TMPL-LEAS-015` | `move_in_checklist_and_docs` | `lease_lifecycle` | Move-in workflow initiated upon lease execution | `resident_name`, `lease_id`, `unit_number` | `resident_name`, `lease_id`, `property_name`, `unit_number`, `move_in_date`, `portal_url`, `manager_contact`, `manager_phone` |
| **16** | `TMPL-LEAS-016` | `move_in_reminder` | `lease_lifecycle` | Scheduled move-in reminder (3 days prior to occupancy) | `resident_name`, `move_in_date`, `unit_number` | `resident_name`, `property_name`, `unit_number`, `move_in_date`, `manager_contact`, `manager_phone` |
| **17** | `TMPL-LEAS-017` | `move_out_notice_ack` | `lease_lifecycle` | Resident submits notice to vacate | `resident_name`, `lease_id`, `move_out_date`, `unit_number` | `resident_name`, `lease_id`, `property_name`, `unit_number`, `move_out_date`, `statutory_deadline_days`, `forwarding_address`, `manager_contact` |
| **18** | `TMPL-LEAS-018` | `move_out_inspection_scheduling` | `lease_lifecycle` | Move-out inspection coordination (Cal. Civ. Code § 1950.5(f) pre-move out inspection right) | `resident_name`, `unit_number`, `move_out_date` | `resident_name`, `property_name`, `unit_number`, `move_out_date`, `inspection_date`, `manager_contact`, `manager_phone` |
| **19** | `TMPL-LEAS-019` | `outstanding_move_out_requirements` | `lease_lifecycle` | Incomplete move-out checklist reminder (keys, forwarding address) | `resident_name`, `unit_number`, `move_out_date` | `resident_name`, `property_name`, `unit_number`, `move_out_date`, `manager_contact`, `manager_phone` |
| **20** | `TMPL-LEAS-020` | `security_deposit_closeout_summary` | `lease_lifecycle` | Approved security deposit closeout accounting proposal | `resident_name`, `deposit_original_amount`, `deposit_refund_amount`, `statutory_deadline_days` | `resident_name`, `property_name`, `unit_number`, `deposit_original_amount`, `deposit_deductions_total`, `deposit_refund_amount`, `statutory_deadline_days`, `manager_contact` |
| **21** | `TMPL-MNT-021` | `maintenance_request_received` | `maintenance` | Resident submits maintenance ticket | `resident_name`, `work_order_id`, `maintenance_issue`, `sla_priority` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `sla_priority`, `sla_target_hours`, `manager_contact` |
| **22** | `TMPL-MNT-022` | `maintenance_request_clarification` | `maintenance` | Technician/manager requests additional details or entry permission | `resident_name`, `work_order_id`, `unit_number` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `clarification_questions`, `portal_url`, `manager_contact` |
| **23** | `TMPL-MNT-023` | `maintenance_request_scheduled` | `maintenance` | Vendor or technician appointment window confirmed | `resident_name`, `work_order_id`, `appointment_date`, `appointment_window` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `vendor_name`, `technician_name`, `appointment_date`, `appointment_window`, `manager_contact` |
| **24** | `TMPL-MNT-024` | `maintenance_appointment_reminder` | `maintenance` | Scheduled reminder 24 hours prior to service appointment | `resident_name`, `work_order_id`, `appointment_date`, `appointment_window` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `technician_name`, `appointment_date`, `appointment_window`, `manager_contact` |
| **25** | `TMPL-MNT-025` | `maintenance_status_update` | `maintenance` | Work order status change (parts ordered, in progress) | `resident_name`, `work_order_id`, `work_order_status` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `work_order_status`, `status_details`, `manager_contact` |
| **26** | `TMPL-MNT-026` | `maintenance_delay_notification` | `maintenance` | Work order delay or rescheduled appointment | `resident_name`, `work_order_id`, `delay_reason` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `delay_reason`, `estimated_completion_date`, `manager_contact` |
| **27** | `TMPL-MNT-027` | `maintenance_work_completed` | `maintenance` | Work order marked completed by technician | `resident_name`, `work_order_id`, `unit_number` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `completion_date`, `portal_url`, `manager_contact` |
| **28** | `TMPL-MNT-028` | `maintenance_feedback_request` | `maintenance` | 24 hours post-completion feedback survey trigger | `resident_name`, `work_order_id`, `unit_number` | `resident_name`, `work_order_id`, `property_name`, `unit_number`, `technician_name`, `survey_link`, `manager_contact` |
| **29** | `TMPL-MNT-029` | `maintenance_sla_escalation_internal` | `maintenance` | Autonomous SLA monitor detects approaching breach (<2h) or active breach | `work_order_id`, `sla_priority`, `sla_deadline`, `elapsed_hours` | `work_order_id`, `property_name`, `unit_number`, `maintenance_issue`, `sla_priority`, `sla_deadline`, `elapsed_hours`, `technician_name`, `assigned_manager` |
| **30** | `TMPL-VND-030` | `vendor_invoice_received` | `vendor_operations` | Vendor PDF invoice submitted and vectorized | `vendor_name`, `invoice_number`, `invoice_amount` | `vendor_name`, `invoice_number`, `invoice_amount`, `property_name`, `work_order_id`, `submission_date` |
| **31** | `TMPL-VND-031` | `vendor_invoice_missing_info` | `vendor_operations` | Invoice missing lien waiver, W-9, or work order reference | `vendor_name`, `invoice_number`, `missing_documentation` | `vendor_name`, `invoice_number`, `property_name`, `work_order_id`, `missing_documentation`, `contact_email` |
| **32** | `TMPL-VND-032` | `invoice_discrepancy_internal_review` | `vendor_operations` | 4-way matching discrepancy detected (overbilling vs work order cap) | `invoice_number`, `vendor_name`, `invoice_amount`, `variance_amount` | `invoice_number`, `vendor_name`, `property_name`, `work_order_id`, `invoice_amount`, `work_order_cap`, `variance_amount`, `discrepancy_details` |
| **33** | `TMPL-VND-033` | `invoice_approval_notification` | `vendor_operations` | Property manager sign-off on 4-way matched invoice | `vendor_name`, `invoice_number`, `invoice_amount`, `approval_date` | `vendor_name`, `invoice_number`, `property_name`, `work_order_id`, `invoice_amount`, `approval_date`, `payment_schedule_terms` |
| **34** | `TMPL-VND-034` | `payment_status_update_to_vendor` | `vendor_operations` | Vendor payment disbursed or check cleared | `vendor_name`, `invoice_number`, `payment_amount`, `payment_reference`, `clearing_status` | `vendor_name`, `invoice_number`, `payment_amount`, `payment_method`, `payment_reference`, `clearing_status`, `disbursement_date` |
| **35** | `TMPL-CMP-035` | `approval_required` | `compliance_risk` | Action gate requires human reviewer sign-off (renewal, closeout, dispute) | `approval_reference`, `action_category`, `assigned_reviewer` | `approval_reference`, `action_category`, `property_name`, `entity_reference`, `action_summary`, `assigned_reviewer`, `portal_url` |
| **36** | `TMPL-CMP-036` | `approval_reminder` | `compliance_risk` | Pending approval aging reminder (>48 hours) | `approval_reference`, `action_category`, `pending_hours` | `approval_reference`, `action_category`, `entity_reference`, `pending_hours`, `assigned_reviewer`, `portal_url` |
| **37** | `TMPL-CMP-037` | `overdue_approval_escalation` | `compliance_risk` | Approval gate approaching statutory deadline | `approval_reference`, `action_category`, `statutory_deadline_hours` | `approval_reference`, `action_category`, `property_name`, `entity_reference`, `statutory_deadline_hours`, `supervisor_name`, `portal_url` |
| **38** | `TMPL-CMP-038` | `compliance_finding_assigned` | `compliance_risk` | New compliance risk finding detected during autonomous scan | `risk_finding_id`, `finding_severity`, `compliance_category`, `assigned_party` | `risk_finding_id`, `property_name`, `unit_number`, `finding_severity`, `compliance_category`, `finding_description`, `statutory_rule_citation`, `assigned_party`, `portal_url` |
| **39** | `TMPL-CMP-039` | `compliance_finding_resolved` | `compliance_risk` | Risk finding verified resolved and closed by reviewer | `risk_finding_id`, `resolution_summary`, `resolved_by` | `risk_finding_id`, `property_name`, `compliance_category`, `resolution_summary`, `resolved_by`, `resolution_date` |
| **40** | `TMPL-CMP-040` | `document_verification_required` | `compliance_risk` | OCR low confidence or missing human review for ingested doc | `document_id`, `document_title`, `verification_issue` | `document_id`, `document_title`, `property_name`, `verification_issue`, `portal_url` |
| **41** | `TMPL-CMP-041` | `workflow_failure_internal_alert` | `compliance_risk` | Scheduler job failure, API exception, or retry exhaustion | `workflow_name`, `error_summary`, `failure_timestamp` | `workflow_name`, `error_summary`, `failure_timestamp`, `affected_entity_id`, `stack_trace_snippet` |
| **42** | `TMPL-CMP-042` | `financial_data_source_unavailable_alert` | `compliance_risk` | Zetaris virtual data fabric or financial ledger connection failure | `source_name`, `connection_status`, `error_details` | `source_name`, `connection_status`, `error_details`, `outage_timestamp`, `fallback_state` |

---

## 5. Variable Catalog & Validation System

### Real Backend Fields Mapped
All variables in `VARIABLE_CATALOG` are mapped directly to authoritative backend entities:
- **Resident:** `resident_name`, `resident_email`, `resident_phone`, `forwarding_address`.
- **Property & Lease:** `property_name`, `property_address`, `unit_number`, `lease_id`, `lease_end_date`, `move_in_date`, `move_out_date`, `manager_contact`, `manager_phone`.
- **Financial AR:** `rent_amount`, `amount_due`, `due_date`, `payment_amount`, `payment_date`, `payment_reference`, `payment_method`, `remaining_balance`, `payment_link`, `portal_url`.
- **Renewals & Closeouts:** `renewal_rent_amount`, `renewal_term_months`, `offer_expiration_date`, `deposit_original_amount`, `deposit_deductions_total`, `deposit_refund_amount`, `statutory_deadline_days`.
- **Maintenance & SLAs:** `work_order_id`, `maintenance_issue`, `sla_priority`, `sla_target_hours`, `sla_deadline`, `elapsed_hours`, `technician_name`, `vendor_name`, `appointment_date`, `appointment_window`.
- **Vendor AP:** `invoice_number`, `invoice_amount`, `work_order_cap`, `variance_amount`, `discrepancy_details`, `missing_documentation`, `clearing_status`.
- **Compliance & Operations:** `approval_reference`, `risk_finding_id`, `finding_severity`, `compliance_category`, `statutory_rule_citation`, `source_name`, `workflow_name`.

### Security & Sanitization
1. **HTML Entity Escaping:** User-provided context values are escaped using `html.escape()` prior to HTML preview rendering, neutralizing potential script injection or DOM tampering.
2. **Graceful Fallbacks:** Missing variables are never rendered as misleading `0` or `1970-01-01` values; instead, descriptive fallbacks (e.g. `[Rent Due Date]`, `[Resident Name]`) are displayed.
3. **Multi-Tenant Isolation:** System default templates are flagged with `org_id = 'system'`. Customer organizations (e.g. `ORG-APEX`) can override templates without mutating the default baseline for other tenants.

---

## 6. Verification & Automated Test Results

### A. Communication Templates Test Suite
```bash
docker compose exec -T api pytest tests/test_communication_templates.py -v
```
**Results:** `11 passed, 1 warning in 28.52s` (100% pass rate).
- `test_1_template_seeding_and_catalog`: PASSED
- `test_2_api_list_templates_and_categories`: PASSED
- `test_3_variable_catalog_endpoint`: PASSED
- `test_4_variable_validation_and_missing_data`: PASSED
- `test_5_safe_rendering_and_html_escaping`: PASSED
- `test_6_template_preview_endpoint`: PASSED
- `test_7_template_update_and_versioning`: PASSED
- `test_8_safe_test_send_dispatch`: PASSED
- `test_9_operational_dashboard_overview`: PASSED
- `test_10_assistant_templated_communication_and_docs`: PASSED
- `test_11_multi_tenant_template_isolation`: PASSED

### B. Frontend Production Build
```bash
cd frontend && npm run build
```
**Output:**
```
vite v5.4.21 building for production...
transforming...
✓ 56 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   1.43 kB │ gzip:   0.72 kB
dist/assets/index-57Giyvij.css   37.55 kB │ gzip:   7.23 kB
dist/assets/index-BEoQRDVA.js   476.05 kB │ gzip: 121.55 kB
✓ built in 3.81s
```
Zero errors, zero warnings.

---

## 7. Remaining Gaps & Limitations
1. **External SMTP Delivery:** For automated testing and local safety, `SMTP_ENABLED=false` is enforced in `.env`. Notifications are safely queued and marked `simulated`. When production SMTP credentials (e.g. AWS SES or SendGrid) are provided, the dispatcher will send real messages without code changes.
2. **Rich Text / WYSIWYG Editor:** The template editor currently uses a monospaced syntax-highlighted textarea with variable token chips. A full WYSIWYG HTML canvas (such as TipTap) could be introduced in a future release if desired.
3. **SMS Carrier Dispatch:** Maintenance dispatch and renewal alerts currently log SMS dispatches to the notification ledger; integration with Twilio/Telnyx API credentials will be required for external cellular carrier transmission.
