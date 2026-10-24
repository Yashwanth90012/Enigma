# EQUILIBRA — Phase 2A Verification Report: Complete Resident & Lease Workflows

## Executive Summary

Phase 2A delivers comprehensive, production-grade resident lifecycle capabilities to EQUILIBRA by extending existing services, database schemas, and multi-agent coordination rather than creating parallel or redundant modules.

All 4 specified core workflows have been fully implemented, verified with 99 passing backend tests (including 11 dedicated resident lifecycle workflow tests), and integrated into the frontend `ResidentPortal` component with Vite production bundle verification.

---

## 1. Existing Functionality Reused

In strict compliance with architectural constraints ("Complete existing capabilities without creating new agent categories or duplicating existing functionality"):
- **`app/database.py`**: Reused the core PostgreSQL connection pool (`db()`), schema initializer (`init_database`), and existing `lease_records`, `properties`, and `documents` tables.
- **`app/world_model.py`**: Reused append-only event sourcing (`record_event`) and deterministic entity identity (`canonical_id`) to record all lease lifecycle mutations (`lease_renewal_offer_prepared`, `move_in_checklist_created`, `move_in_task_completed`, `move_out_notice_received`, `move_out_closeout_proposed`, `move_out_closeout_approved`).
- **`app/notifications.py`**: Reused the notification engine and persistent queue (`queue_notification`, `list_notifications`), leveraging stable event keys (`event_key`) to enforce idempotency and avoid duplicate emails/alerts.
- **`app/engine.py`**: Reused 3-way financial reconciliation (`fixture_rows`, `calculate`) to determine lease delinquency standing for renewal eligibility and outstanding balances during move-out closeout.
- **`app/scheduler.py`**: Integrated autonomous renewal sweeps (`sweep_expiring_leases_and_renewals`) alongside existing maintenance SLA and overdue rent sweeps.
- **`frontend/src/components/ResidentPortal.jsx`**: Extended the existing single-page component with dedicated workflow hubs (Move-In Checklist, Renewal Hub, Move-Out Closeout, Communication Preferences) while maintaining 100% backward compatibility for rent remittance, maintenance tickets, document processing, and live notification feeds.

---

## 2. Implemented Workflows & Business Rules

### A. Lease Renewal Workflow
1. **Upcoming Expiration Identification**:
   - `get_expiring_leases(days_threshold=90, org_id=None)` scans active leases where `end_date - today <= threshold`.
   - Computes ledger delinquency standing via 3-way reconciliation (accounts with >$500 unpaid rent are flagged `ineligible` or `requires_review`).
2. **Offer Formulation with Configurable Rules**:
   - `prepare_renewal_offer(lease_id, term_months=12, rent_increase_percent=3.5, ...)` applies configurable rent adjustments (+3.5% standard).
   - Generates unique renewal record in `lease_renewals` (`UNIQUE (lease_id, renewal_period)`).
3. **Duplicate Offer Prevention**:
   - Strictly enforces idempotency: attempts to prepare a second offer for the same lease and renewal period return HTTP 400 Bad Request with a clear duplicate prevention notification.
4. **Lifecycle State Transitions**:
   - States tracked: `upcoming` -> `offer_prepared` -> `accepted` / `declined` -> `pending_approval` -> `finalized`.
5. **Human Manager Approval Gate**:
   - **Contractual Safeguard**: A resident accepting a renewal offer transitions the status to `pending_approval` and does **not** modify contract terms in `lease_records`.
   - Authorized manager approval (`approve_lease_renewal`) is strictly required before `monthly_rent_usd`, `end_date`, and `lease_status` are finalized.

### B. Move-In Onboarding Workflow
1. **Checklist Generation**:
   - `initiate_move_in_checklist(lease_id)` idempotently creates structured checklist records linked to resident, lease, and property.
   - 6 standardized onboarding tasks:
     1. `renters_insurance` (Document verification: $100k liability certificate)
     2. `government_id` (Document verification: photo ID)
     3. `deposit_settlement` (Financial verification: initial escrow & 1st month rent)
     4. `pre_inspection` (Inspection walkthrough & condition report)
     5. `utility_transfer` (Utility account transfer verification)
     6. `key_handover` (Access credentials & smart fob issuance)
2. **Task Completion Auditing**:
   - `complete_move_in_task(lease_id, task_key, completed_by, notes)` records user identity, ISO timestamp, and notes.
3. **Overdue & Missing Requirements Flagging**:
   - Automatically computes completion progress percentage and flags overdue status if target move-in date has passed with incomplete tasks.

### C. Move-Out & Closeout Workflow
1. **Notice to Vacate**:
   - `submit_move_out_notice(lease_id, planned_move_out_date, forwarding_address, ...)` initiates notice tracking.
   - **Statutory 21-Day Clock**: Calculates and tracks California Civil Code § 1950.5 escrow refund deadline (`statutory_deadline_date = planned_move_out_date + 21 days`).
2. **Inspection & Turnover Tasks**:
   - Standard turnover checklist: 30-day notice verification, pre-move-out walkthrough, key/remote surrender, cleaning turnover inspection, and final utility meter read.
3. **Deposit Accounting Proposal**:
   - `propose_move_out_closeout(lease_id, itemized_deductions)` cross-references unpaid ledger balances and tenant-caused damage work orders with evidence receipts.
   - Calculates proposed net refund (`security_deposit_usd - unpaid_rent - itemized_deductions`).
4. **Strict Human Approval Gate**:
   - **Absolute Guardrail**: Security deposits are **never automatically deducted or disbursed**. The system generates a proposal requiring formal property manager sign-off (`approve_move_out_closeout`) before funds are released and tenancy closed.

### D. Resident Communications & Multi-Tenant Isolation
1. **Communication Preferences**:
   - `get_communication_preferences` and `update_communication_preferences` manage email and SMS opt-in/opt-out states per resident.
   - If a resident has opted out of email (`email: false`), reminder deliveries are cleanly suppressed (`status: preference_suppressed`) without error.
2. **Deduplication via Stable Event Keys**:
   - Reminders use daily unique event keys (`reminder:{type}:{lease_id}:{YYYYMMDD}`) ensuring scheduled sweeps never spam residents.
3. **Delivery Status Transparency**:
   - When external SMTP or Twilio gateways are unconfigured, notifications clearly display `queued` or simulated status rather than claiming false external delivery.
4. **Multi-Tenant Scoping & Access Control**:
   - Every resident endpoint enforces organization ownership via `validate_lease_ownership(lease_id, org_id)`.
   - Leases are mapped through `properties.org_id`. Cross-tenant requests (e.g. `ORG-VERDANT` attempting to query `LEASE-0001` owned by `ORG-APEX`) are rejected with `HTTP 403 Forbidden`.

---

## 3. Database Changes & Schema Integrity

Non-destructive migrations were applied to PostgreSQL (`app/database.py`):

```sql
-- 1. Lease Records Extensions
ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS end_date TEXT;
ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS lease_status TEXT DEFAULT 'active';
ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS resident_email TEXT;
ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS communication_preferences JSONB DEFAULT '{"email": true, "sms": false}'::jsonb;

-- 2. Lease Renewals Table
CREATE TABLE IF NOT EXISTS lease_renewals (
    id TEXT PRIMARY KEY,
    lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE CASCADE,
    property_id TEXT REFERENCES properties(property_id),
    renewal_period TEXT NOT NULL,
    current_rent_usd NUMERIC(12, 2) NOT NULL,
    proposed_rent_usd NUMERIC(12, 2) NOT NULL,
    term_months INT DEFAULT 12,
    eligibility_status TEXT DEFAULT 'eligible',
    status TEXT DEFAULT 'offer_prepared',
    offer_terms TEXT,
    resident_decision TEXT,
    decision_date TIMESTAMPTZ,
    manager_approval_state TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lease_id, renewal_period)
);

-- 3. Move-In Checklists Table
CREATE TABLE IF NOT EXISTS move_in_checklists (
    id TEXT PRIMARY KEY,
    lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE CASCADE,
    property_id TEXT REFERENCES properties(property_id),
    resident_name TEXT NOT NULL,
    resident_email TEXT,
    target_move_in_date TEXT NOT NULL,
    status TEXT DEFAULT 'in_progress',
    tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    UNIQUE (lease_id)
);

-- 4. Move-Out Records Table
CREATE TABLE IF NOT EXISTS move_out_records (
    id TEXT PRIMARY KEY,
    lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE CASCADE,
    property_id TEXT REFERENCES properties(property_id),
    resident_name TEXT NOT NULL,
    resident_email TEXT,
    notice_date TEXT NOT NULL,
    planned_move_out_date TEXT NOT NULL,
    actual_move_out_date TEXT,
    forwarding_address TEXT NOT NULL,
    status TEXT DEFAULT 'notice_received',
    tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    security_deposit_usd NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    outstanding_balance_usd NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    proposed_deductions JSONB DEFAULT '[]'::jsonb,
    proposed_refund_usd NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    statutory_deadline_date TEXT NOT NULL,
    closeout_approval_state TEXT DEFAULT 'pending',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    approval_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lease_id)
);
```

Idempotent backfill automatically populated `end_date` (`move_in_date + INTERVAL '1 year'`), `lease_status = 'active'`, and `resident_email` for legacy seeded leases.

---

## 4. API Endpoints Catalog

| Method | Route | Description | Auth / Scope |
|---|---|---|---|
| `GET` | `/api/leases/renewals/expiring` | Retrieve leases expiring within window (default 90d) | Multi-tenant scoped |
| `GET` | `/api/leases/{lease_id}/renewal` | Get active renewal record and eligibility status | Multi-tenant scoped |
| `POST` | `/api/leases/{lease_id}/renewal/prepare` | Formulate renewal offer (+3.5% rent, terms) | Duplicate-offer prevented (400) |
| `POST` | `/api/leases/{lease_id}/renewal/decision` | Record resident decision (`accepted`/`declined`) | Transitions to `pending_approval` |
| `POST` | `/api/leases/{lease_id}/renewal/approve` | Property Manager approval to finalize contract | Human Gate |
| `GET` | `/api/leases/{lease_id}/move-in` | Get onboarding checklist, progress %, overdue flags | Multi-tenant scoped |
| `POST` | `/api/leases/{lease_id}/move-in/initiate` | Idempotently initiate onboarding checklist | Multi-tenant scoped |
| `POST` | `/api/leases/{lease_id}/move-in/tasks/{task_key}/complete` | Mark move-in task complete with audit metadata | Timestamped user audit |
| `GET` | `/api/leases/{lease_id}/move-out` | Retrieve move-out record, tasks, and closeout summary | Multi-tenant scoped |
| `POST` | `/api/leases/{lease_id}/move-out/notice` | Submit 30-day notice to vacate & start 21-day clock | Statutory compliance |
| `POST` | `/api/leases/{lease_id}/move-out/tasks/{task_key}/complete` | Complete inspection or key surrender task | Timestamped user audit |
| `POST` | `/api/leases/{lease_id}/move-out/closeout/propose` | Formulate proposed deposit deductions | Ledger-linked evidence |
| `POST` | `/api/leases/{lease_id}/move-out/closeout/approve` | Property Manager approval for deposit disbursement | Human Gate |
| `GET` | `/api/leases/{lease_id}/preferences` | Get resident notification preferences | Multi-tenant scoped |
| `PUT` | `/api/leases/{lease_id}/preferences` | Update email/SMS opt-in preferences | Multi-tenant scoped |
| `POST` | `/api/leases/{lease_id}/notifications/remind` | Queue resident alert respecting preferences | Deduplicated |

---

## 5. Verification & Test Results

### Dedicated Resident Workflows Suite (`tests/test_resident_workflows.py`)
11 tests executed directly inside Docker container:
- `test_1_expiring_leases_and_renewal_eligibility`: **PASSED**
- `test_1b_prepare_renewal_offer_and_prevent_duplicate`: **PASSED** (verifies HTTP 400 on duplicate)
- `test_2_renewal_status_transitions_lifecycle`: **PASSED** (`offer_prepared` -> `accepted` -> `pending_approval` -> `finalized`)
- `test_2b_resident_declines_renewal`: **PASSED**
- `test_3_move_in_checklist_lifecycle`: **PASSED** (6 tasks, progress bar, completion audit)
- `test_3b_move_out_checklist_lifecycle`: **PASSED** (21-day statutory clock, inspections)
- `test_4_and_5_organization_ownership_and_cross_tenant_isolation`: **PASSED** (HTTP 403 Forbidden verified)
- `test_6_communication_preferences_and_duplicate_prevention`: **PASSED** (opt-out suppression & key deduplication)
- `test_7_contractual_changes_require_human_approval`: **PASSED** (contract rent locked until manager approves)
- `test_7b_move_out_deposit_closeout_requires_human_approval`: **PASSED** (escrow disbursement locked until manager approves)
- `test_8_existing_endpoints_regression`: **PASSED** (leases, 360 details, notifications)

### Full Repository Regression Suite
- Total tests collected and executed: **99 items**
- Results: **99 passed, 0 failed**
- Duration: ~4 minutes 14 seconds

### Frontend Production Build
```
> frontend@0.0.0 build
> vite build
✓ 53 modules transformed.
dist/index.html                   1.43 kB │ gzip:   0.72 kB
dist/assets/index-57Giyvij.css   37.55 kB │ gzip:   7.23 kB
dist/assets/index-Bd29YGiR.js   402.35 kB │ gzip: 107.35 kB
✓ built in 2.38s
```

---

## 6. Remaining Gaps & Future Roadmap (Phase 2B+)

1. **Compliance Hub**: Integration of jurisdictional compliance checks (local rent control ordinances, lead paint disclosure forms, fair housing guidelines) deferred to Phase 2B.
2. **Zetaris Cloud Federation**: Live remote federated queries across multiple data warehouses remain optional in live mode and default to resilient fixture fallback.
3. **PaddleOCR Document Pipeline**: Dedicated OCR scanning for uploaded lease PDFs and inspection photos.
