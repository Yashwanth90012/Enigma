# EQUILIBRA — Phase 2B Verification Report: Compliance & Risk Monitoring Hub

## Executive Summary

Phase 2B delivers a centralized, multi-tenant **Compliance & Risk Monitoring Hub** for EQUILIBRA. By interconnecting existing autonomous agents (`resident_agent`, `finance_agent`, `vendor_agent`, `maintenance_agent`, `world_model`, `notifications`, and `scheduler`), the Hub identifies, tracks, prioritizes, and resolves operational, financial, and legal compliance risks without introducing any new top-level agent categories or duplicate business logic.

The Hub is backed by an append-only PostgreSQL Risk Register with unique stable keys to guarantee 100% idempotent scans, an explicit statutory jurisdiction registry (handling state-by-state deposit return deadlines with authoritative citations while treating unverified jurisdictions safely as operational risks), an authoritative approval queue enforcing separation of duties, and a complete single-page application dashboard integrated into the EQUILIBRA design system.

---

## 1. Existing Functionality Reused

In strict conformance with architectural constraints:
- **`app/database.py`**: Reused the PostgreSQL connection pool (`db()`), schema initializer (`init_database`), and existing entity tables (`properties`, `lease_records`, `work_order_records`, `vendor_invoices`, `notifications`, `approvals`, `lease_renewals`, `move_in_checklists`, `move_out_records`).
- **`app/world_model.py`**: Reused append-only event sourcing (`record_event`) and deterministic identity resolution (`canonical_id`) to record all finding status transitions, escalations, and approval decisions.
- **`app/engine.py`**: Reused the 3-way financial reconciliation engine (`fixture_rows`, `calculate`) to detect financial variances, balance mismatches, and overdue tenant rent past the 3-day grace period.
- **`app/vendor_agent.py`**: Reused the 4-way Accounts Payable matching engine (`reconcile_vendor_bill`) to detect overbilling quotes, unauthorized credit card surcharges, uncashed stale checks, and bank clearing variances.
- **`app/maintenance_agent.py`**: Reused triage priorities and SLA monitoring calculations (`check_sla_breaches`) to identify breached or approaching SLA deadlines.
- **`app/resident_agent.py`**: Reused Phase 2A resident lifecycle queries to identify upcoming lease expirations, pending renewal manager approvals, incomplete move-in onboarding checklists, and pending move-out deposit closeouts.
- **`app/notifications.py`**: Reused durable notification queueing (`queue_notification`) and delivery status tracking (`queued`, `sent`, `simulated`, `failed`).
- **`app/scheduler.py`**: Integrated the compliance risk scan directly into `run_autonomous_jobs()` alongside existing SLA and delinquency sweeps.
- **`frontend/src/App.jsx` & `frontend/src/components/HubSwitcher.jsx`**: Extended the existing navigation menubar and telemetry rack with dedicated Compliance & Risk Hub views without altering existing portal behavior.

---

## 2. Central Risk Register & Database Changes

Executed in [app/database.py](../app/database.py):

### A. Table `risk_findings`
Persists detected issues with comprehensive metadata, evidence JSON, statutory citations, and stable deduplication keys:
```sql
CREATE TABLE IF NOT EXISTS risk_findings (
    id TEXT PRIMARY KEY,
    stable_key TEXT UNIQUE NOT NULL,
    org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    property_id TEXT REFERENCES properties(property_id) ON DELETE SET NULL,
    lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE SET NULL,
    invoice_id TEXT,
    vendor_id TEXT,
    work_order_id TEXT,
    resident_id TEXT,
    category TEXT NOT NULL,               -- lease_resident, financial, maintenance, operational_integration, legal_compliance
    finding_type TEXT NOT NULL,           -- operational_risk, policy_exception, legal_compliance_finding
    severity TEXT NOT NULL,               -- critical, high, medium, low, info
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    source_record_type TEXT NOT NULL,     -- lease, invoice, work_order, checklist, notification, approval, move_out
    source_record_id TEXT NOT NULL,
    detection_rule TEXT NOT NULL,
    originating_event TEXT,
    evidence JSONB DEFAULT '{}'::jsonb,
    jurisdiction TEXT,                   -- 'US-CA', 'US-NY', 'US-TX', 'US-WA', 'unverified'
    statutory_source TEXT,               -- e.g. 'Cal. Civ. Code § 1950.5'
    effective_date TEXT,
    compliance_status TEXT DEFAULT 'not_applicable', -- compliant, warning, potential_violation, unverified, not_applicable
    status TEXT NOT NULL DEFAULT 'open',  -- open, under_review, action_required, resolved, dismissed
    assigned_reviewer TEXT,
    due_date TIMESTAMPTZ,
    last_reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT,
    resolution_notes TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### B. Table `approval_history`
Indexed audit log tracking every reviewer action, decision rationale, prior and post state transitions:
```sql
CREATE TABLE IF NOT EXISTS approval_history (
    id BIGSERIAL PRIMARY KEY,
    case_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,            -- lease_renewal, move_out_closeout, vendor_bill, risk_finding, general
    action TEXT NOT NULL,                 -- approved, rejected, escalated, assigned, under_review, resolved, dismissed
    reviewer TEXT NOT NULL,
    decision_reason TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT,
    org_id TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 3. Risk Detection Rules & Evidence Sources

The risk scanner ([app/compliance_agent.py](../app/compliance_agent.py)) executes automated evaluation across four core operational domains:

### A. Lease & Resident Workflows
1. `RULE_LEASE_EXPIRATION_APPROACHING`: Active lease approaching expiration ($\le 90$ days) without a confirmed resident decision (`severity: high` if $\le 30$ days else `medium`).
2. `RULE_DOCUMENT_RETENTION_INTEGRITY`: Active lease with zero documents or missing executed lease agreement in the document store (`severity: medium`).
3. `RULE_MOVE_IN_CHECKLIST_OVERDUE`: Target move-in onboarding date has passed with incomplete tasks (`severity: high`).
4. `RULE_MOVE_IN_CHECKLIST_APPROACHING`: Move-in scheduled within 7 days with pending onboarding tasks (`severity: medium`).
5. `RULE_CONTRACTUAL_APPROVAL_REQUIRED`: Tenant accepted renewal offer awaiting authorized manager sign-off before contract terms are updated (`severity: high`).
6. `RULE_SECURITY_DEPOSIT_APPROVAL_REQUIRED`: Proposed move-out deposit closeout awaiting authorized manager sign-off (`severity: high`).

### B. Financial Operations
7. `RULE_3WAY_RECONCILIATION_VARIANCE`: Lease, invoice, and bank-clearing reconciliation mismatch or balance difference (`severity: high`).
8. `RULE_RENT_DELINQUENCY_POST_GRACE`: Tenant rent balance remaining unpaid past the 3-day grace period (`severity: high`).
9. `RULE_VENDOR_4WAY_MATCH_OVERBILLING`: Vendor invoice billed amount exceeds maintenance quote by $>10\%$ without authorized change order (`severity: high`).
10. `RULE_VENDOR_4WAY_MATCH_SURCHARGE_VARIANCE`: Unauthorized credit card processing surcharge detected on bank debit statement (`severity: high`).
11. `RULE_VENDOR_4WAY_MATCH_UNCASHED_CHECK`: Issued check has not cleared bank feed within the escheatment tracking window (`severity: medium`).

### C. Maintenance & SLA Monitoring
12. `RULE_MAINTENANCE_SLA_BREACH`: Work order past configured triage SLA deadline (4h emergency, 24h high, 72h standard) (`severity: critical/high`).
13. `RULE_MAINTENANCE_SLA_APPROACHING`: Work order with $<4$ hours remaining before SLA deadline breach (`severity: medium`).
14. `RULE_REPEATED_MAINTENANCE_INCIDENT`: Unit with $\ge 2$ tickets in the same trade category within 30 days (`severity: medium`).

### D. Operational & Integration Risks
15. `RULE_NOTIFICATION_DELIVERY_FAILURE`: Outbound notification in `failed` status requiring manual follow-up (`severity: medium`).
16. `RULE_APPROVAL_ESCALATION_OVERDUE`: Approval case in `pending` or `escalated` status for $>7$ calendar days (`severity: high`).

---

## 4. Jurisdiction Handling & Statutory Deadlines

Strictly enforcing architectural guideline: **"Separate operational risk, business-policy exception, and legal compliance finding. Universal legal deadlines are prohibited."**

### Authoritative Statutory Registry
| State | Jurisdiction | Statutory Citation | Effective Date | Deposit Return Deadline | Itemized Statement Required |
|---|---|---|---|---|---|
| **California** | `US-CA` | Cal. Civ. Code § 1950.5(g)(1) | 2003-01-01 | **21 calendar days** | Yes |
| **New York** | `US-NY` | N.Y. Gen. Oblig. Law § 7-108(1-a)(e) | 2019-07-14 | **14 calendar days** | Yes |
| **Texas** | `US-TX` | Tex. Prop. Code § 92.103 | 1995-09-01 | **30 calendar days** | Yes |
| **Washington** | `US-WA` | RCW 59.18.280 | 2023-07-23 | **30 calendar days** | Yes |

### Unverified Jurisdiction Protection
If a property's `state` is missing, invalid, or not present in the statutory registry:
- `jurisdiction = "unverified"`
- `statutory_source = None`
- `finding_type = "operational_risk"` (strictly prevented from being labeled a legal violation)
- `compliance_status = "unverified"`
- Description explicitly notes: *"Property state has no registered statutory deposit rule in the compliance database. Evaluated as operational process risk without statutory claim."*

---

## 5. API Endpoints Mounted & Verified

Mounted in [app/main.py](../app/main.py):

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/compliance/jurisdictions` | Returns statutory registry rules (CA 21-day, NY 14-day, TX 30-day, citations) |
| `GET` | `/api/compliance/summary` | Aggregate metric counts by severity, status, category, and finding type |
| `GET` | `/api/compliance/findings` | Filterable, searchable, paginated list of risk findings |
| `GET` | `/api/compliance/findings/{id}` | Full finding detail with evidence JSON, statutory basis, and decision history |
| `POST` | `/api/compliance/findings/{id}/assign` | Assign designated reviewer to a risk finding |
| `POST` | `/api/compliance/findings/{id}/review` | Transition finding state (`under_review`, `action_required`) with audit notes |
| `POST` | `/api/compliance/findings/{id}/resolve` | Resolve or dismiss finding with mandatory reviewer name & decision reason |
| `GET` | `/api/compliance/approvals/pending` | Centralized queue aggregating pending renewals, deposit closeouts, and escalations |
| `POST` | `/api/compliance/approvals/{case_id}/decision` | Authoritative approval execution with separation of duties enforcement |
| `GET` | `/api/compliance/approvals/history` | Immutable audit log of reviewer approvals, reasons, and timestamps |
| `POST` | `/api/compliance/scan` | Trigger on-demand idempotent portfolio risk scan |

---

## 6. Frontend Dashboard Integration

Implemented in [frontend/src/components/ComplianceRiskHub.jsx](../frontend/src/components/ComplianceRiskHub.jsx) and wired into [frontend/src/App.jsx](../frontend/src/App.jsx) and [frontend/src/components/HubSwitcher.jsx](../frontend/src/components/HubSwitcher.jsx):

1. **Metrics Summary Rack**: Real-time counters for High Priority Risks, Pending Approvals, Total Active Findings, and Resolved/Dismissed.
2. **Tabbed Navigation**:
   - **Central Risk Register**: Multi-facet filtering by search text, category, severity, status, and finding type.
   - **Pending Approvals Queue**: Centralized list of renewal rent updates and deposit dispositions awaiting manager sign-off.
   - **Statutory Jurisdictions & Deadlines**: Visual cards for California, New York, Texas, Washington laws and countdowns.
   - **Audit History**: Complete timeline table of reviewer identity, prior/new state transitions, and decision rationales.
3. **Interactive Inspection Modal**: Displays full source evidence payload JSON, statutory citations, and decision timelines.
4. **Action Dialogs**: Dedicated modals for Assignment, Escalation, Resolution, and Approval Sign-Off with mandatory rationale validation.
5. **Production Build Verified**:
   ```bash
   ✓ 54 modules transformed.
   dist/index.html                   1.43 kB │ gzip:   0.72 kB
   dist/assets/index-57Giyvij.css   37.55 kB │ gzip:   7.23 kB
   dist/assets/index-CTUUQa9e.js   437.56 kB │ gzip: 113.76 kB
   ✓ built in 2.75s (0 errors)
   ```

---

## 7. AI Assistant Integration

Extended [app/assistant.py](../app/assistant.py):
- Detects compliance, risk, finding, statutory, or approval intents.
- Invokes backend tool `query_compliance_risk_register`.
- Retrieves verified findings from PostgreSQL, explains triggering rules using underlying evidence, references source record IDs, and recommends next steps without bypassing human approval gates.
- Strictly separates recorded facts, configured business rules, and AI recommendations.

---

## 8. Authorization, Multi-Tenant Isolation & Audit Controls

1. **Organization Scoping**: Every finding record is linked to `org_id` (`REFERENCES organizations(id)`).
2. **Access Control**: Endpoints resolve the user's organization from `X-Organization-Id` header and query parameter `org_id`. Cross-organization requests return `HTTP 403 Forbidden` (`validate_finding_ownership`).
3. **Separation of Duties**: Server rejects self-approval if `submitted_by == reviewer` on financial or contractual resolutions (`HTTP 403 Forbidden`).
4. **Mandatory Audit Rationale**: Server strictly rejects empty decision reasons or reasons shorter than 3 characters (`HTTP 400 Bad Request`).
5. **Append-Only Event Sourcing**: Every state transition and approval logs an immutable event into `world_events` with canonical IDs.

---

## 9. Verification & Automated Test Results

### Suite 1: Dedicated Compliance Hub Tests
Command:
```bash
docker compose exec -T api pytest -v tests/test_compliance_hub.py
```
Results:
- `test_1_risk_finding_creation_and_persistence`: **PASSED**
- `test_2_duplicate_detection_across_repeated_scans`: **PASSED** (idempotency verified)
- `test_3_severity_category_and_source_references`: **PASSED**
- `test_4_financial_discrepancy_detection`: **PASSED** (3-way recon integration)
- `test_5_lease_expiration_and_resident_workflow_risks`: **PASSED**
- `test_6_maintenance_sla_breach_detection`: **PASSED**
- `test_7_approval_and_resolution_state_transitions`: **PASSED**
- `test_8_reviewer_identity_and_required_decision_reasons`: **PASSED** (separation of duties & validation)
- `test_9_jurisdiction_rule_selection_and_unverified_handling`: **PASSED** (CA, NY, TX, WA & unverified state)
- `test_10_cross_organization_access_denial`: **PASSED** (HTTP 403 verified)
- `test_11_scheduled_scan_and_notification_idempotency`: **PASSED** (scheduler integration)
- `test_12_regression_existing_agents_and_assistant_query`: **PASSED** (assistant tool dispatch)

**Status:** `12 passed in 174.72s (0:02:54)`

---

## 10. Remaining Gaps & Future Enhancements

1. **Configurable Webhook Alerts**: Pushing critical legal deadline breach notifications directly to Slack or PagerDuty.
2. **Live County Court Docket Feed**: Ingesting real-time eviction filing notices from county municipal courts into the jurisdiction registry.
