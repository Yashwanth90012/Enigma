# ENIGMA — Live Demonstration Runbook (Evaluator Guide)

**Release:** Phase 6 Final Submission  
**Environment:** Containerized Docker Compose + React 19 Frontend  
**Synthetic Data Policy:** Strictly synthetic fixtures. No real PII, tenant records, or banking writebacks.

---

## 1. Demo Quick-Start & Verification

Ensure the ENIGMA containers and frontend are running:
```bash
# 1. Start backend and databases (Postgres with pgvector)
docker compose up -d

# 2. Verify backend health
curl -s http://localhost:8000/health
# Expected output: {"status":"ok","database":"connected","pgvector":"enabled", ...}

# 3. Access frontend
http://localhost:5173
```

---

## 2. Scenario A — Autonomous Lease Processing & Contextual Memory

### Objective
Demonstrate end-to-end lease onboarding: upload an authentic residential lease contract, extract key contractual fields via Document Intelligence RAG, link the lease to resident entities in the World Model, and index contextual memories into H-MEM.

### Prerequisites
- Backend healthy at `http://localhost:8000`
- Synthetic lease file generated or located at `data/sample_lease.pdf`

### Step 1: Upload and Extract Lease Contract
Send a multipart upload of the synthetic lease to the Document Intelligence endpoint:
```bash
curl -X POST http://localhost:8000/api/documents/upload \
  -H "X-Organization-Id: ORG-APEX" \
  -F "file=@data/sample_lease.pdf;type=application/pdf" \
  -F "document_type=lease" \
  -F "property_id=PROP-APEX-01"
```
**Expected Response:**
```json
{
  "document_id": "DOC-7B42FA",
  "filename": "sample_lease.pdf",
  "sha256": "4a719d3b...",
  "status": "indexed",
  "extracted_fields": {
    "resident_name": "Eleanor Vance",
    "unit": "Unit 402",
    "monthly_rent_usd": 2450.00,
    "security_deposit_usd": 2450.00,
    "lease_start": "2026-11-01",
    "lease_end": "2027-10-31"
  },
  "indexed_chunks": 12,
  "hmem_memory_id": "MEM-9F112D"
}
```

### Step 2: UI Verification in Resident Portal
1. Open the browser to `http://localhost:5173`.
2. Ensure the top organization selector is set to **Apex Horizon**.
3. Click the **Resident Experience & Lease Hub** navigation tab.
4. Verify the newly onboarded resident (`Eleanor Vance`) appears in the active roster.
5. Note the automatic move-in checklist generated with 5 onboarding steps:
   - Key Handover & Access Cards
   - Renter's Insurance Verification
   - Move-in Condition Inspection
   - Payment Portal Setup
   - Emergency Contact Form

### Step 3: Engine Evidence Inspection
Verify that the World Model entity timeline and H-MEM contextual memory are persisted:
```bash
# Query World Model entity events
curl -X POST http://localhost:8000/api/engines/world-model/query \
  -H "Content-Type: application/json" \
  -d '{"case_id": "LEASE-E-VANCE", "entity_id": "DOC-7B42FA"}'
```
**Evidence:** Returns monotonic causal event DAG with `event_type: "document_ingested"` and `lease_created`.

---

## 3. Scenario B — Vendor Invoice Overbilling & Human Approval Gate

### Objective
Demonstrate 4-way AP reconciliation: submit a synthetic contractor invoice where the billed amount exceeds the authorized Work Order quote by >25%, trigger automated discrepancy flags, require property manager approval, and verify that unauthorized payment attempts are strictly blocked.

### Step 1: Inspect Work Order Scope
Work Order `WO-0001` (Emergency Plumbing Pipe Repair) has an authorized quote of **$450.00**.
```bash
curl -s http://localhost:8000/api/work-orders/WO-0001
```

### Step 2: Submit Overbilled Vendor Invoice
Submit a synthetic vendor invoice billing **$720.00** (+60% over quote without an approved change order):
```bash
curl -X POST http://localhost:8000/api/vendor-bills/submit \
  -H "Content-Type: application/json" \
  -d '{
    "vendor_id": "VEND-PLUMB-01",
    "work_order_id": "WO-0001",
    "property_id": "PROP-APEX-01",
    "invoice_number": "INV-2026-9912",
    "total_usd": 720.00,
    "item_summary": "Emergency pipe repair, replacement valves, overtime surcharge"
  }'
```

### Step 3: Run 4-Way Reconciliation
Execute reconciliation on the invoice:
```bash
curl -s http://localhost:8000/api/vendor-bills/INV-2026-9912/reconcile
```
**Expected Response:**
```json
{
  "invoice_id": "INV-2026-9912",
  "status": "needs_review",
  "reason_code": "OVERBILLING_FLAGGED",
  "billed_cents": 72000,
  "quote_cents": 45000,
  "variance_cents": 27000,
  "diagnosis": [
    "Vendor billed $720.00, exceeding Work Order WO-0001 quote ($450.00) by $270.00 (+60.0%). No written change order on file."
  ],
  "action_required": "Request itemized justification from vendor before approving final settlement."
}
```

### Step 4: Verify Unauthorized Disbursement is Blocked
Attempt to disburse payment without property manager sign-off:
```bash
curl -X POST http://localhost:8000/api/vendor-payments/disburse \
  -H "Content-Type: application/json" \
  -H "X-User-Role: junior_accountant" \
  -d '{
    "invoice_id": "INV-2026-9912",
    "amount_usd": 720.00,
    "payment_method": "corporate_check"
  }'
```
**Expected Response:** HTTP 403 Forbidden:
```json
{
  "detail": "Disbursement blocked: Invoice INV-2026-9912 requires property_manager or executive approval due to OVERBILLING_FLAGGED."
}
```

### Step 5: Approval via Compliance & Risk Hub UI
1. In the frontend at `http://localhost:5173`, navigate to **Compliance & Risk Hub**.
2. Locate the pending approval request in **Pending Approval Queue**:
   - `Type: VENDOR_OVERBILLING_VARIANCE`
   - `Entity: INV-2026-9912 ($720.00 vs $450.00)`
3. Switch role to **Property Manager** or click **Review & Resolve**.
4. Enter justification `"Authorized partial settlement at $550.00 after vendor itemization review"` and submit.
5. The invoice status transitions from `needs_review` to `approved_partial` with an immutable audit entry in the World Model.

---

## 4. Scenario C — Recoverable Markovian Workflow & Checkpointing

### Objective
Demonstrate high-reliability workflow execution: launch a multi-step property renewal and reconciliation workflow, simulate an abrupt network/process crash mid-execution, verify the durable checkpoint, and resume execution without repeating already-completed side effects.

### Step 1: Initiate Multi-Step Lease Renewal Workflow
```bash
curl -X POST http://localhost:8000/api/workflows/renewal/start \
  -H "Content-Type: application/json" \
  -d '{
    "lease_id": "LEASE-0001",
    "proposed_rent_usd": 2200.00,
    "simulate_failure_at_step": "send_tenant_notification"
  }'
```
**Expected Response:**
```json
{
  "workflow_id": "WF-MARKOV-842B1",
  "status": "failed",
  "last_successful_step": "evaluate_payment_history",
  "checkpoint_id": "CHK-842B1-STEP2",
  "completed_side_effects": [
    "calculate_eligibility_score",
    "generate_renewal_document"
  ],
  "error": "Simulated connection drop during notification dispatch"
}
```

### Step 2: Inspect Durable Checkpoint
Verify the checkpoint recorded in PostgreSQL:
```bash
curl -s http://localhost:8000/api/workflows/WF-MARKOV-842B1/checkpoint
```
**Evidence:**
- Current state: `AWAITING_NOTIFICATION_DISPATCH`
- Checkpoint payload contains generated document ID `DOC-REN-0001`.
- Step 1 (`calculate_eligibility_score`) and Step 2 (`generate_renewal_document`) are registered with idempotency keys in `completed_side_effects`.

### Step 3: Trigger Recovery & Safe Resume
Execute workflow recovery:
```bash
curl -X POST http://localhost:8000/api/workflows/WF-MARKOV-842B1/recover \
  -H "Content-Type: application/json"
```
**Expected Response:**
```json
{
  "workflow_id": "WF-MARKOV-842B1",
  "status": "completed",
  "resumed_from_step": "send_tenant_notification",
  "skipped_steps": [
    "calculate_eligibility_score",
    "generate_renewal_document"
  ],
  "total_steps_executed": 3,
  "final_state": "RENEWAL_OFFER_DISPATCHED"
}
```
**Result:** No duplicate document was generated, and no duplicate charge was posted. The workflow resumed safely from the precise failure boundary.

---

## 5. Demonstration Scenario C: Monthly Rent Payment, Sandbox Gateway, 3-Stage Overdue Escalation, and Audit Trail (Phase 7)

### Step 1: Check Tenant Rent Obligation Dashboard
1. In the frontend at `http://localhost:5173`, select **Resident Portal**.
2. Select Tenancy **LEASE-0001 (ORG-APEX · Active)**.
3. Observe the **Monthly Rent Obligation** card:
   - Billing Period: `2026-10`
   - Due Date: `2026-10-01`
   - Grace Period End: `2026-10-04`
   - Status Badge: `OVERDUE` (Red alert banner: *STATUTORY NOTICE OF OVERDUE RENT — 3-DAY PAYMENT DEADLINE*)
   - Strict Payment Deadline: `2026-10-07 23:59:59 UTC`
   - Outstanding Balance: `$2,125.00`

### Step 2: Settle Rent via Authoritative Payment Gateway
1. Select payment method: **Direct Bank ACH Wire (Zero Surcharge · Reconciled)**.
2. Click **💳 Pay Rent Now ($2,125.00)**.
3. The server creates an authoritative checkout session with unique idempotency key and initiates sandbox processing.
4. Upon confirmed settlement:
   - Status updates in real-time to **✓ Paid & Reconciled**.
   - The **Pay Rent** button is immediately hidden/disabled for that billing period.
   - An official confirmation card appears: *Rent Paid In Full*.
   - Click **📄 View Official Receipt** to open the responsive, printable receipt modal showing receipt number, transaction reference, amount, and UTC timestamp.
   - The payment is automatically appended to the **Previous Rent Payments & Reconciled Receipts** table.

### Step 3: Verify 3-Way Atomic Synchronization
Verify via API that database records across `rent_billing_records`, `payments`, and `bank_transactions` are 100% reconciled:
```bash
curl -s "http://localhost:8000/api/tenant/rent-dashboard?lease_id=LEASE-0001" | jq .current_bill
```
Expected: `status == "paid"`, `outstanding_balance_usd == 0.0`.

### Step 4: Run Property Manager Overdue & Escalation Sweep
1. Switch to **Tenant Accounts Receivable (AR)** hub.
2. Click the **💳 Rent Collection** tab.
3. Observe the collection overview KPIs (Total Billed, Total Collected, Payment Due, Overdue & Escalated, Gateway Processing).
4. Click **⚡ Trigger Autonomous Overdue Sweep**:
   - The background scheduler evaluates all active leases.
   - Tenancies past the 4th of the month are flagged as overdue with $50.00 late fees.
   - Delinquencies past the 3-day deadline (7th) are queued in the **Statutory Legal Notice Review Queue**.

### Step 5: Guarded Legal Notice Authorization Gate
1. Inspect the **Statutory Legal Notice Review Queue** in the Property Manager portal.
2. Observe pending cases awaiting review:
   - Notice that cases with confirmed payments were automatically cancelled (`cancelled_by_payment`).
   - For an overdue case, click **Approve Notice**:
     - Pre-flight check verifies no payment was made in the interim.
     - Transitions state to `approved` / `dispatched`.
     - An immutable audit record is logged.

### Step 6: Inspect Centralized Audit Trail
1. In the sidebar or HubSwitcher, select **Audit Trail** (`Audit Logs`).
2. Observe all real-time events:
   - Filter by Action: `rent_billing.payment_initiated`, `rent_billing.payment_confirmed`, `rent_billing.overdue_sweep_completed`, `legal_notice_approved`.
   - Click any event to open the **Audit Event Inspector** drawer.
   - Observe sanitized JSON details with masked credentials and tenant isolation.

---

## 6. Cleanup Instructions

To reset the demonstration environment back to baseline:
```bash
# 1. Clean synthetic test records from database
docker exec -i enigma-project-api-1 python -c "
from app.database import db
with db() as conn:
    conn.execute(\"DELETE FROM vendor_invoices WHERE id = 'INV-2026-9912'\")
    conn.execute(\"DELETE FROM approval_requests WHERE action_type = 'VENDOR_OVERBILLING_VARIANCE'\")
"

# 2. Check system status
curl -s http://localhost:8000/health
```

