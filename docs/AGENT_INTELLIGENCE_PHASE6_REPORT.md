# ENIGMA — Phase 6: Dynamic Agent Orchestration & Recoverable Execution Report

**Status:** Complete  
**Date:** October 2026  
**System Architecture:** Autonomous Multi-Agent Property & Financial Orchestration Engine  
**Target Environment:** FastAPI Backend, PostgreSQL 16+, Meterless World Model Event Store, NVIDIA NIM Microservices  

---

## Executive Summary

Phase 6 upgrades ENIGMA's Assistant and Orchestrator from ephemeral in-memory workflow executors into a **durable, dependency-aware, dynamically replanned, and recoverable multi-agent orchestration engine**. 

Prior to Phase 6, workflow coordination existed only as synchronous Python control flows (`execute_invoice_approval_orchestration`, `execute_lease_cross_validation_orchestration`). If the API process restarted, crashed, or encountered transient infrastructure timeouts mid-workflow, all in-flight state was lost, leaving only disconnected step execution logs. Furthermore, workflows could not dynamically adapt to intermediate agent abstentions or invoice discrepancies without hardcoded logic, and lacked formal outcome verification and separation-of-duties enforcement.

In Phase 6, we designed and implemented:
1. **Durable PostgreSQL Workflow State:** Two dedicated tables—[`orchestration_workflows`](../app/database.py#L525) and [`orchestration_steps`](../app/database.py#L552)—track top-level workflow lifecycles and DAG step executions across container restarts.
2. **Topological DAG Execution:** Arbitrary multi-agent task directed acyclic graphs run with dependency tracking, concurrency for independent read-only tasks, and strict operation allowlisting.
3. **Bounded Dynamic Replanning:** When an agent encounters missing document evidence or an accounts-payable discrepancy, the orchestrator autonomously revises the DAG plan (bounded to $\le 2$ revisions), injects authorized recovery steps (e.g., semantic RAG document extraction or maintenance work order correlation), and logs plan lineage in the World Model.
4. **Crash Recovery & Workflow Resumption:** On API process startup or via external recovery API calls, interrupted `running` workflows are recovered from PostgreSQL without re-executing already-completed external actions.
5. **Rigorous Business Outcome Verification:** Workflows complete only after verifying physical database record persistence, active compliance holds, invoice matching thresholds, and separation of duties.
6. **Separation of Duties & Authorization Gates:** The orchestrator agent cannot approve its own restricted workflows; human managerial roles are enforced, and tenant boundaries are strictly isolated with HTTP 403.

All 16 dedicated Phase 6 test scenarios passed (100%), and all 58 existing multi-agent regression tests passed with zero regressions.

---

## 1. Audit Findings: Existing Orchestration Baseline

Before implementing code changes, we performed a thorough audit of the existing orchestration stack:

| Component | Pre-Phase 6 Status | Deficiencies & Gaps Identified |
|---|---|---|
| **Invoice Approval Workflow** | Partially Implemented | Ephemeral in-memory execution in `app/assistant.py`. Step decisions logged to `agent_execution_logs`, but no workflow-level state record, no resumption capability, and no database-backed transaction management across steps. |
| **Lease Cross-Validation Workflow** | Partially Implemented | Ran document cross-validation and finance ledger check concurrently via `ThreadPoolExecutor`, but lacked persistent DAG state and final verification of source primary keys. |
| **Habitability Risk Workflow** | Partially Implemented | Standalone evaluation in `app/maintenance_agent.py` without workflow graph tracking or correlation with multi-agent payment pauses. |
| **AgentDecision & Abstention** | Implemented (Phase 1) | Agents correctly produced `AgentDecision` with `EvidenceReference` and confidence ratings. However, when an agent abstained, the orchestrator merely defaulted to requiring human review without attempting dynamic replanning. |
| **Idempotency & Execution Logs** | Step-Level Only | Idempotency was enforced on individual agent step invocations (`check_idempotency`), but could not coordinate multi-step workflows or resume interrupted DAGs. |
| **Causal Event DAG** | Implemented | Meterless World Model recorded causal event lineage (`record_event`), but events were append-only and not utilized as a state-machine driver for restart recovery. |
| **Approval Authorization** | Partially Implemented | Flagged `requires_human_approval = True` based on dollar thresholds ($500 / $1000), but lacked an API endpoint for authorized human sign-off, lacked separation-of-duties checks, and allowed potential self-approval. |
| **Process Crash & Restart Resilience** | **Missing** | Any API container restart or timeout aborted running workflows; intermediate steps could not be resumed from database records. |

---

## 2. Workflow Persistence & State Machine

### 2.1 Database Schema
In [`app/database.py`](../app/database.py), we created two new persistent tables with strict foreign keys, indices, and constraints:

```sql
CREATE TABLE IF NOT EXISTS orchestration_workflows (
    workflow_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workflow_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    initiating_request JSONB NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'created',
    plan_revision INT NOT NULL DEFAULT 1,
    plan_dag JSONB NOT NULL DEFAULT '[]'::jsonb,
    context_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    approval_requirements JSONB DEFAULT '{}'::jsonb,
    approval_status JSONB DEFAULT '{}'::jsonb,
    verification_results JSONB DEFAULT '{}'::jsonb,
    error_details JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS orchestration_steps (
    step_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES orchestration_workflows(workflow_id) ON DELETE CASCADE,
    plan_revision INT NOT NULL DEFAULT 1,
    agent_id TEXT NOT NULL,
    operation_name TEXT NOT NULL,
    execution_order INT NOT NULL DEFAULT 1,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    state TEXT NOT NULL DEFAULT 'planned',
    inputs JSONB DEFAULT '{}'::jsonb,
    outputs JSONB,
    evidence JSONB DEFAULT '[]'::jsonb,
    attempt_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    duration_ms NUMERIC(10,2),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);
```

### 2.2 Formal State Machine & Valid Transitions
Workflow instances transition strictly according to the validated state transition map in [`app/orchestrator.py`](../app/orchestrator.py#L78):

```
       [created]
           │
           ▼
       [planned] ───────────────┐
           │                     │
           ▼                     ▼
       [running] ─────────► [cancelled] (terminal)
        │  ▲  │
        │  │  ├───────────► [waiting_for_dependency]
        │  │  │                     │
        │  │  │◄────────────────────┘
        │  │  │
        │  │  ├───────────► [waiting_for_approval]
        │  │  │                     │
        │  │  │◄────────────────────┤ (on human approval)
        │  │  │                     ▼
        │  │  ├───────────► [needs_review]
        │  │  │
        │  │  ├───────────► [retrying]
        │  │  │
        │  │  ▼
        │  └──┴───────────► [completed] (verified terminal)
        │
        ▼
     [failed] (recoverable)
```

Transitions are protected via row-level locking (`SELECT ... FOR UPDATE`) in [`update_workflow_state()`](../app/orchestrator.py#L561). Invalid transitions (such as moving from `completed` or `cancelled` to any state, or jumping directly from `planned` to `completed`) raise a `ValueError` (HTTP 400).

---

## 3. Dependency-Aware Orchestration & Strict Allowlist

### 3.1 Strict Operation Allowlist
To prevent model-generated plans or untrusted requests from executing arbitrary shell, SQL, or unapproved code, all executable tasks are bound to the `@register_operation` allowlist:

| Agent Identifier | Permitted Operation Name | Description |
|---|---|---|
| `document_intelligence` | `validate_invoice_document` | Validates invoice document text against entity records. |
| `document_intelligence` | `recover_missing_document_evidence` | Semantic RAG chunk retrieval to locate missing document clauses. |
| `document_intelligence` | `validate_lease_document` | Validates lease agreement terms and parties. |
| `vendor_invoice` | `reconcile_vendor_bill_4way` | 4-way matching of invoice, purchase/work order, delivery receipt, and vendor terms. |
| `financial_operations` | `evaluate_financial_approval_threshold` | Enforces corporate spending limits ($500 manager sign-off, $1,000 controller sign-off). |
| `rent_reconciliation` | `reconcile_lease_ledger` | Verifies lease rent rate against tenant ledger. |
| `compliance_risk` | `evaluate_compliance_controls` | Checks active stop-payment holds, vendor disputes, and license compliance. |
| `maintenance_sla` | `correlate_maintenance_work_order` | Dynamic replanning step: correlates disputed invoices with verified technician work orders. |
| `maintenance_sla` | `assess_habitability_risk` | Assesses emergency work orders against statutory habitability standards. |

### 3.2 Topological Concurrency & Step Execution
In [`execute_workflow_dag()`](../app/orchestrator.py#L740):
1. **Dependency Validation:** A step is only runnable if all step IDs listed in its `dependencies` array have reached state `completed`.
2. **Safe Concurrency:** When multiple steps have all dependencies satisfied and are read-only/independent (such as `step-1-doc` and `step-2-fin` in lease cross-validation), they execute concurrently in a `ThreadPoolExecutor(max_workers=2)`.
3. **Short-Circuit on Approval:** If any step triggers an approval requirement (e.g., spending threshold exceeded), the DAG pauses immediately in `waiting_for_approval` and does not proceed to consequential actions.

---

## 4. Bounded Dynamic Replanning

When an agent reports missing evidence, an AP discrepancy, low confidence, or an abstention, the engine invokes [`attempt_dynamic_replanning()`](../app/orchestrator.py#L820):

1. **Strict Revision Bound:** A maximum of 2 dynamic revisions (`plan_revision <= 3`) are permitted. Attempting a 3rd revision terminates the loop and escalates the workflow to `needs_review`.
2. **Missing Document Evidence Recovery:** If the `document_intelligence` agent abstains due to missing document text, the replanner injects `recover_missing_document_evidence`, querying pgvector semantic RAG embeddings to retrieve itemized invoice text.
3. **AP Discrepancy Work Order Correlation:** If the `vendor_invoice` agent detects a discrepancy (e.g., billed hours exceed work order estimate), the replanner dynamically injects `correlate_maintenance_work_order` with the `maintenance_sla` agent to verify technician dispatch records.
4. **Lineage Preservation:** The original plan and every revision are recorded in the Meterless World Model as `workflow_plan_revised` events with timestamps, reason, and injected step identifiers.
5. **No Blind Approvals:** An abstention or unresolved discrepancy is never treated as an approval; the workflow pauses until authorized evidence is produced.

---

## 5. Retry, Error Classification & Process Restart Recovery

### 5.1 Error Classification & Bounded Retries
Errors during step execution are classified in [`app/orchestrator.py`](../app/orchestrator.py#L605):
- **Transient Errors:** Database connection drops, network timeouts, and NVIDIA NIM rate limits (HTTP 429) / service errors (HTTP 502, 503, 504). Handled via exponential backoff with jitter up to `max_retries` (default: 3).
- **Permanent Validation Errors:** Schema violations, invalid operations not on the allowlist, and bad payloads fail immediately without endless retries.
- **Authorization & Tenant Boundary Failures:** Return HTTP 403 immediately and halt workflow progress.

### 5.2 Restart Recovery (`recover_interrupted_workflows`)
When the API server starts up (invoked in `lifespan` in [`app/main.py`](../app/main.py#L57)) or upon calling `POST /api/orchestrator/workflows/recover`:
1. Scans `orchestration_workflows` for workflows stranded in `running` or `retrying`.
2. Resumes eligible workflows from their persisted state in PostgreSQL.
3. Steps already marked `completed` are **not** re-executed, preventing duplicate payments, double ledger postings, or duplicate tenant emails.
4. Unrecoverable workflows transition safely to `needs_review` with diagnostic error records.

---

## 6. Business Outcome Verification & Separation of Duties

### 6.1 Outcome Verification
A workflow is never marked `completed` merely because a Python function returned. In [`verify_workflow_outcome()`](../app/orchestrator.py#L926), the engine independently verifies:
- **Invoice Approval:** 
  - Invoice record exists in `vendor_invoices` in PostgreSQL.
  - Active compliance stop-payment holds (`risk_findings` in state `open`/`under_review`) are zero.
  - If total amount exceeds $500.00, verified human managerial sign-off exists.
  - Approving identity is verified not to be the orchestrator agent itself.
- **Lease Cross-Validation:** 
  - Authoritative lease record exists in `lease_records`.
  - Tenant organization boundaries are verified against the property table.
- **Habitability Assessment:**
  - Work order exists in `work_order_records`.
  - Emergency status and jurisdiction configuration verified; risk assessment is kept informative and prevented from executing automated unauthorized financial charges.

### 6.2 Separation of Duties Enforcement
In [`approve_workflow()`](../app/orchestrator.py#L1038):
- **Self-Approval Prevention:** Identifiers belonging to AI systems (`assistant_orchestrator`, `system`, `orchestrator`, `ai_agent`) are strictly rejected with HTTP 403: *"Separation of duties violation: Orchestrator agent cannot self-approve restricted workflows."*
- **Role Authorization:** Reviewers must possess authorized roles (`property_manager`, `finance_manager`, `financial_controller`, `compliance_officer`). Unauthorized roles (e.g., `resident` or `vendor`) are rejected with HTTP 403.
- **Terminal State Protection:** Workflows in terminal states (`completed`, `cancelled`) cannot be modified or re-approved.

---

## 7. Workflow Management APIs

We extended the authenticated, tenant-isolated API surface in [`app/main.py`](../app/main.py):

| Method | Endpoint | Description | Tenant Isolated |
|---|---|---|:---:|
| `POST` | `/api/orchestrator/workflows/invoice-approval` | Start multi-agent invoice approval orchestration (persists workflow and steps). | Yes (`X-Organization-Id`) |
| `POST` | `/api/orchestrator/workflows/lease-cross-validation` | Start multi-agent lease document-to-ledger cross-validation. | Yes (`X-Organization-Id`) |
| `POST` | `/api/orchestrator/workflows/habitability-risk` | Assess maintenance work order for habitability failure. | Yes (`X-Organization-Id`) |
| `GET` | `/api/orchestrator/workflows` | List workflows with filtering on `workflow_type`, `current_state`, limit, and offset. | Yes (`X-Organization-Id`) |
| `GET` | `/api/orchestrator/workflows/{workflow_id}` | Retrieve complete workflow status, step DAG details, inputs, outputs, evidence, and verification logs. | Yes (`X-Organization-Id`) |
| `POST` | `/api/orchestrator/workflows/{workflow_id}/approve` | Submit human approval/rejection with separation-of-duties check and resume DAG. | Yes (`X-Organization-Id`) |
| `POST` | `/api/orchestrator/workflows/{workflow_id}/resume` | Resume an interrupted or waiting workflow. | Yes (`X-Organization-Id`) |
| `POST` | `/api/orchestrator/workflows/{workflow_id}/cancel` | Safely cancel an active or waiting workflow. | Yes (`X-Organization-Id`) |
| `POST` | `/api/orchestrator/workflows/recover` | Trigger manual or external recovery scan for interrupted workflows. | Global / Tenant |
| `GET` | `/api/orchestrator/telemetry` | Retrieve operational metrics (latencies, retries, abstentions, review rates). | Yes |

*Backward Compatibility:* All legacy return keys (`workflow_id`, `invoice_id`, `lease_id`, `final_status`, `composite_confidence`, `requires_human_approval`, `approval_role`, `step_decisions`, `causal_event_dag`) remain 100% intact alongside the newly added `current_state` and `verification_results`.

---

## 8. Test Execution & Verification Results

### 8.1 Dedicated Phase 6 Test Suite ([`tests/test_dynamic_orchestration_phase6.py`](../tests/test_dynamic_orchestration_phase6.py))
All 16 required test scenarios were implemented and verified against PostgreSQL:

```bash
docker compose exec -T api pytest tests/test_dynamic_orchestration_phase6.py -v
```

**Results:**
```text
tests/test_dynamic_orchestration_phase6.py::test_1_successful_dependent_workflow_execution PASSED [  6%]
tests/test_dynamic_orchestration_phase6.py::test_2_safe_concurrent_execution_of_independent_steps PASSED [ 12%]
tests/test_dynamic_orchestration_phase6.py::test_3_missing_evidence_and_agent_abstention PASSED [ 18%]
tests/test_dynamic_orchestration_phase6.py::test_4_discrepancy_triggered_replanning PASSED [ 25%]
tests/test_dynamic_orchestration_phase6.py::test_5_bounded_retries_and_permanent_failures PASSED [ 31%]
tests/test_dynamic_orchestration_phase6.py::test_6_duplicate_requests_and_concurrent_execution PASSED [ 37%]
tests/test_dynamic_orchestration_phase6.py::test_7_api_process_restart_and_workflow_resumption PASSED [ 43%]
tests/test_dynamic_orchestration_phase6.py::test_8_partial_completion_and_interrupted_execution PASSED [ 50%]
tests/test_dynamic_orchestration_phase6.py::test_9_approval_required_workflows PASSED [ 56%]
tests/test_dynamic_orchestration_phase6.py::test_10_unauthorized_or_self_approved_actions PASSED [ 62%]
tests/test_dynamic_orchestration_phase6.py::test_11_cross_tenant_access_attempts PASSED [ 68%]
tests/test_dynamic_orchestration_phase6.py::test_12_compliance_holds_during_replanning PASSED [ 75%]
tests/test_dynamic_orchestration_phase6.py::test_13_final_verification_failure PASSED [ 81%]
tests/test_dynamic_orchestration_phase6.py::test_14_cancellation_and_terminal_states PASSED [ 87%]
tests/test_dynamic_orchestration_phase6.py::test_15_nvidia_nim_timeout_and_rate_limit_recovery PASSED [ 93%]
tests/test_dynamic_orchestration_phase6.py::test_16_backward_compatibility_of_existing_workflow_apis PASSED [100%]

======================== 16 passed, 1 warning in 6.41s =========================
```

### 8.2 Full Agent Intelligence Regression Suites
We ran the full regression suite across all existing agents:

```bash
docker compose exec -T api pytest tests/test_agent_intelligence_phase1.py tests/test_communication_templates.py tests/test_compliance_hub.py tests/test_resident_workflows.py tests/test_vendor_agent.py tests/test_saas_persistence.py -v
```

**Results:**
```text
================== 58 passed, 1 warning in 682.96s (0:11:22) ===================
```
- Total Tests Run: **74** (16 Phase 6 + 58 Regression)
- Total Passed: **74**
- Total Failed: **0**
- Success Rate: **100.0%**

---

## 9. Known Limitations & Remaining Gaps

1. **Automatic External Payment Execution (Intentional Boundary):** Conforming to critical rule #6, automated fund disbursements to real banking rails remain disabled. Workflows transition to `waiting_for_approval` or `completed` with verified approval records without executing wire transfers.
2. **WebSocket Real-Time UI Streaming:** As specified for this backend-focused phase, real-time client notifications are not implemented; workflow status is retrieved via polling the durable `GET /api/orchestrator/workflows/{id}` endpoint.
3. **Multi-Region Distributed Coordination:** Current distributed locking relies on PostgreSQL row-level locks (`SELECT ... FOR UPDATE`). In a multi-cluster deployment with cross-region database replication, a distributed consensus coordinator (e.g., Redis Redlock or Raft) would be recommended for sub-millisecond step claims.

---

## Conclusion & Next Phase Readiness

ENIGMA Phase 6 successfully establishes **genuine durability, DAG dependency resolution, crash recovery, and bounded dynamic replanning** across its multi-agent property management workflows. All 13 established agents remain preserved, API contracts remain backward compatible, and PostgreSQL provides the authoritative durable record for autonomous execution. The platform is now fully prepared for the final demo-readiness phase.
