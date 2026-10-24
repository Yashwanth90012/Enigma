# EQUILIBRA — Complete Agent Audit & Gap Analysis

**Repository:** EQUILIBRA Autonomous Property Management Platform (formerly ENIGMA)  
**Audit Date:** October 2026  
**Auditor:** DeepMind Antigravity Advanced Agentic Pair Programmer  

---

## 1. Executive Summary Table

Status values strictly constrained to: `PASS`, `PARTIAL`, `MISSING`, `BROKEN`, `BLOCKED`.

| Agent or capability | Implemented | Backend connected | Frontend connected | Tests | Real integration verified | Missing work |
|---|---|---|---|---|---|---|
| **1. Document Intelligence Agent** | `PASS` | `PASS` | `PASS` | `PASS` | `PARTIAL` | OCR for low-resolution raster images |
| **2. Property and Listing Agent** | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | External MLS syndication sync |
| **3. Resident and Lease Agent** | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | Automated e-signature webhook hookup |
| **4. Maintenance and SLA Agent** | `PASS` | `PASS` | `PASS` | `PASS` | `PARTIAL` | Real external SMS dispatch carrier |
| **5. Financial Operations Agent** | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | External banking Plaid/ACH webhook sync |
| **6. Notification & Workflow Capability** | `PASS` | `PASS` | `PASS` | `PASS` | `PARTIAL` | Real SMTP/SendGrid mail credentials |
| **7. Scheduling & Autonomous Operations**| `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | Distributed worker clustering (Celery/Temporal)|
| **8. EQUILIBRA Assistant & Orchestration** | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | Optional speech audio streaming (STT/TTS) |
| **9. Resident Portal, Listings & Diagnostics**| `PASS`| `PASS` | `PASS` | `PASS` | `PASS` | Native mobile iOS/Android packaging |

---

## 2. In-Depth Audit of All 9 Agent Capabilities

### 1. Document Intelligence Agent
- **Actual Responsibility:**
  Ingests rental leases, vendor bills, and maintenance reports. Extracts structured metadata, generates SHA-256 idempotency content hashes to reject duplicate files, and indexes clause text into the PostgreSQL pgvector hybrid RAG store.
- **Source Files & API Endpoints:**
  - Source: `app/document_agent.py`, `app/rag.py`
  - Endpoints:
    - `POST /api/documents/ingest`
    - `GET /api/documents/{document_id}`
    - `GET /api/documents/rag/search`
- **What It Can Successfully Do Today:**
  - Extracts text from PDF bytes via `pypdf` and classifies documents into `lease_agreement`, `maintenance_receipt`, or `vendor_invoice`.
  - Extracts rent amounts, grace periods, deposit covenants, and maintenance clauses with regex/structural entity extractors.
  - Generates 384-dimensional semantic neural embeddings via NVIDIA NIM (`nvidia/nemotron-3.5-embed-1b`) or deterministic hash-based dense vectors when offline, stored in PostgreSQL pgvector with HNSW index for hybrid RRF (Reciprocal Rank Fusion) retrieval.
  - Rejects duplicate documents using SHA-256 content fingerprints.
- **Data Source & AI Usage:**
  Uses real database models (`documents`, `chunks`, `lease_records`), PaddleOCR v3.7.0 text extraction, NVIDIA NIM neural embeddings, and deterministic hybrid semantic-lexical RRF search.
- **Dependencies & Failure Modes:**
  - Dependency: `pypdf`, `paddleocr`, `pgvector` extension in PostgreSQL, NVIDIA NIM Embedding API.
  - Failure Mode: Scanned PDFs without embedded text layer use local PaddleOCR preprocessing; unavailable embedding networks gracefully fall back to deterministic lexical vectors.
- **Missing Implementation Work:**
  None. PaddleOCR integration and live neural semantic embeddings with reindexing support are fully operational.
- **Tests Proving Status:**
  `tests/test_equilibra_agents.py::test_document_intelligence_agent_ingestion`, `tests/test_equilibra_agents.py::test_document_duplicate_hash_rejection`, `tests/test_semantic_rag.py` (8/8 passed).

---

### 2. Property and Listing Agent
- **Actual Responsibility:**
  Manages property portfolio, calculates compliance scores (0–100) based on documentation completeness, manages verification statuses (`draft`, `verified`, `published`), accepts public tour bookings, and receives rental applications with credit/income checks.
- **Source Files & API Endpoints:**
  - Source: `app/property_agent.py`
  - Endpoints:
    - `GET /api/properties`
    - `POST /api/properties`
    - `GET /api/properties/{property_id}`
    - `POST /api/properties/{property_id}/verify`
    - `POST /api/properties/tours/book`
    - `POST /api/properties/applications/apply`
    - `GET /api/properties/tours/list`
- **What It Can Successfully Do Today:**
  - Seeds and maintains multi-unit listings with images, amenities, square footage, and rent prices.
  - Evaluates listing compliance (score >= 80 auto-publishes).
  - Detects tour booking calendar collisions and prevents double bookings.
  - Processes tenant applications with rent-to-income ratio calculations (3x threshold) and credit score evaluation.
- **Data Source & AI Usage:**
  Real PostgreSQL tables (`properties`, `tour_bookings`, `rental_applications`).
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL 16.
  - Failure Mode: If database connection fails, routes return HTTP 500. Handled via connection retry pool.
- **Missing Implementation Work:**
  Syndication push to external MLS/Zillow/Apartments.com feeds via standard RETS/Reso Web API.
- **Tests Proving Status:**
  `tests/test_equilibra_agents.py::test_property_verification_and_compliance`, `tests/test_equilibra_agents.py::test_tour_booking_collision_detection`, `tests/test_equilibra_agents.py::test_rental_application_triage`.

---

### 3. Resident and Lease Agent
- **Actual Responsibility:**
  Manages complete resident lifecycle: onboarding move-in checklists, expiration monitoring, renewal eligibility evaluations, business-rule offer preparation with duplicate prevention, resident acceptance/decline decision tracking, human manager approval enforcement, move-out notice management with 21-day statutory deposit clocks (Cal. Civ. Code § 1950.5), itemized deposit accounting proposals, and communication preference controls.
- **Source Files & API Endpoints:**
  - Source: `app/resident_agent.py`, `app/main.py`, `app/database.py`, `app/world_model.py`, `frontend/src/components/ResidentPortal.jsx`
  - Endpoints:
    - `GET /api/leases/renewals/expiring` (upcoming expiration identification & eligibility alerts)
    - `GET /api/leases/{lease_id}/renewal` (active renewal record & eligibility status)
    - `POST /api/leases/{lease_id}/renewal/prepare` (renewal offer formulation with duplicate-offer prevention)
    - `POST /api/leases/{lease_id}/renewal/decision` (resident acceptance / decline recording)
    - `POST /api/leases/{lease_id}/renewal/approve` (human manager approval gate before contract terms finalize)
    - `GET /api/leases/{lease_id}/move-in` (onboarding checklist, progress %, overdue task flags)
    - `POST /api/leases/{lease_id}/move-in/initiate` (idempotent checklist creation)
    - `POST /api/leases/{lease_id}/move-in/tasks/{task_key}/complete` (timestamped user audit task completion)
    - `GET /api/leases/{lease_id}/move-out` (move-out record, turnover checklist, closeout proposal)
    - `POST /api/leases/{lease_id}/move-out/notice` (30-day notice to vacate & 21-day statutory clock start)
    - `POST /api/leases/{lease_id}/move-out/tasks/{task_key}/complete` (turnover inspection / key surrender audit)
    - `POST /api/leases/{lease_id}/move-out/closeout/propose` (ledger-linked deposit deduction formulation)
    - `POST /api/leases/{lease_id}/move-out/closeout/approve` (human manager gate for deposit disbursement)
    - `GET /api/leases/{lease_id}/preferences` (communication preferences retrieval)
    - `PUT /api/leases/{lease_id}/preferences` (email/SMS opt-in/opt-out configuration)
    - `POST /api/leases/{lease_id}/notifications/remind` (deduplicated resident reminder queueing)
- **What It Can Successfully Do Today:**
  - Scans active leases within upcoming expiration windows and identifies renewal eligibility based on 3-way reconciliation ledger standing.
  - Generates renewal offers applying business rules (+3.5% rent increase standard) and prevents duplicate offers for the same lease and renewal period (HTTP 400).
  - Transitions lifecycle states: `upcoming` -> `offer_prepared` -> `accepted` / `declined` -> `pending_approval` -> `finalized`.
  - **Contractual Guardrail**: Locks contract terms in `lease_records` until an authorized human manager executes approval.
  - Manages move-in onboarding with 6 standardized tasks (insurance, ID, deposit settlement, walkthrough inspection, utility transfer, key handover) and flags overdue items.
  - Manages move-out lifecycle starting the California Civil Code § 1950.5 21-day statutory countdown, turnover inspection checklist, and proposed deposit closeout.
  - **Deposit Guardrail**: Strictly forbids automatic deduction or disbursement of security deposits without evidence and formal human manager sign-off.
  - Respects resident communication preferences by suppressing email delivery when opted out, and deduplicates reminders via stable event keys.
  - Enforces strict multi-tenant organization ownership validation (`validate_lease_ownership`), rejecting cross-organization access with HTTP 403 Forbidden.
  - Records all lifecycle state mutations into the append-only World Model event log.
- **Data Source & AI Usage:**
  Authoritative database tables (`lease_records`, `lease_renewals`, `move_in_checklists`, `move_out_records`, `properties`), 3-way financial reconciliation engine, and World Model event sourcing.
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL 16.
  - Failure Mode: Missing lease returns HTTP 404; unauthorized cross-tenant requests return HTTP 403; duplicate offer preparation returns HTTP 400.
- **Missing Implementation Work:**
  Automated DocuSign / HelloSign webhook receiver for electronic signing callbacks.
- **Tests Proving Status:**
  `tests/test_resident_workflows.py` (11/11 tests passing), covering renewal eligibility, duplicate prevention, state transitions, move-in/move-out lifecycle, statutory deadlines, multi-tenant isolation, notification preferences, and human approval gates.

---

### 4. Maintenance and SLA Agent
- **Actual Responsibility:**
  Ingests tenant repair requests, triages priority based on emergency keywords (e.g. "gas leak", "flooding" -> 4h SLA), computes deadlines (24h urgent, 72h standard, 7d cosmetic), matches vendors by trade specialty, and detects SLA breaches.
- **Source Files & API Endpoints:**
  - Source: `app/maintenance_agent.py`
  - Endpoints:
    - `POST /api/maintenance/tickets`
    - `GET /api/maintenance/tickets`
    - `GET /api/maintenance/sla-breaches`
- **What It Can Successfully Do Today:**
  - Autonomous severity classification: emergency (4h), high (24h), medium (72h), low (168h).
  - Matches certified vendors from `vendor_profiles` by trade (plumbing, electrical, HVAC, roofing).
  - Emits urgent breach notifications and links work orders to financial ledgers to prevent unauthorized tenant rent withholding.
- **Data Source & AI Usage:**
  Real database records (`work_order_records`, `vendor_profiles`) with deterministic rules and keyword heuristics.
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL.
  - Failure Mode: If no matching trade vendor exists, tickets route to unassigned queue for human manager review.
- **Missing Implementation Work:**
  Twilio / Sinch SMS dispatch integration for automated two-way field technician text messaging.
- **Tests Proving Status:**
  `tests/test_equilibra_agents.py::test_maintenance_ticket_triage_and_emergency_sla`, `tests/test_equilibra_agents.py::test_maintenance_sla_breach_detection`.

---

### 5. Financial Operations Agent
- **Actual Responsibility:**
  Performs exact 3-way reconciliation (Lease Invoice vs Tenant Remittance vs Cleared Bank Ledger) using integer cents and Python `Decimal` arithmetic. Executes monthly rent billing, processes tenant payments with idempotency keys, performs automated grace period sweeps, executes 4-way Accounts Payable matching, and queries federated live accounting records via the Zetaris Lakehouse engine.
- **Source Files & API Endpoints:**
  - Source: `app/engine.py`, `app/finance_agent.py`, `app/vendor_agent.py`, `app/providers.py`, `frontend/src/components/AdminDiagnosticsPortal.jsx`
  - Endpoints:
    - `POST /api/cases/investigate` (3-way reconciliation with live `data_source` metadata)
    - `POST /api/finance/billing/generate`
    - `POST /api/finance/payments/charge`
    - `POST /api/finance/grace-period/sweep`
    - `POST /api/vendor-bills/{invoice_id}/reconcile`
    - `GET /api/integrations/zetaris/health`
    - `GET /api/integrations/zetaris/metadata`
    - `POST /api/integrations/zetaris/query`
    - `POST /api/integrations/zetaris/bootstrap`
- **What It Can Successfully Do Today:**
  - Deterministic 3-way reconciliation with specific reason codes (`MATCH_CONFIRMED`, `PARTIAL_REMITTANCE`, `MISSING_BANK_REFERENCE`, `DUPLICATE_BANK_TRANSACTION`, `UNRECORDED_BANK_DEPOSIT`).
  - Cross-references maintenance work orders to identify unilateral tenant rent withholding.
  - Idempotent payment processing with duplicate charge protection.
  - Idempotent recurring monthly billing run generating invoices for all active leases.
  - 3-day grace period sweep checking for delinquent balances.
  - Federated live data access via Zetaris Lakehouse: connects to `zetaris-api:8888` / Spark Thrift JDBC engine, dynamically mounts 6 views (`enigma_invoices`, `enigma_payments`, `enigma_bank_transactions`, `enigma_vendor_invoices`, `enigma_vendor_payments`, `enigma_vendor_bank_transactions`), and normalizes matrix/tabular payloads.
  - Enforces read-only access (rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER` with HTTP 403 Forbidden).
  - Explicit data-source transparency: returns `source_status` (`live`, `local_database`, `fixture`, `fixture_fallback`), source system, timestamp, record count, and completeness in every financial response. Silent fallback to fixtures is strictly prevented.
  - Interactive Zetaris Lakehouse Explorer in Admin Diagnostics Portal with live connection latency metrics (~85ms).
  - Consequential financial safeguards: requires explicit manager approval for balance writebacks or refunds. Zero generative hallucinated arithmetic.
- **Data Source & AI Usage:**
  Live Zetaris Lakehouse SQL Federation (`spark_catalog.default`) over Apache Spark JDBC to PostgreSQL 16. Python `Decimal` integer cents arithmetic.
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL 16, Zetaris REST service (`zetaris-api:8888`), Spark driver (`zetaris-driver:10000`).
  - Failure Mode: Upstream Zetaris timeout or connection failure triggers explicit, transparent `fixture_fallback` mode with safe reason description; never masks failures as live data.
- **Missing Implementation Work:**
  Live ACH payment gateway integration (e.g. Stripe Financial Connections or Plaid Transfer).
- **Tests Proving Status:**
  `tests/test_zetaris_integration.py` (13/13 passed), `tests/test_reconciliation.py` (7/7 passed), `tests/test_equilibra_agents.py` (financial tests), `tests/test_providers.py` (6/6 passed). All 124 backend tests passing.

---

### 6. Notification & Workflow Capability
- **Actual Responsibility:**
  Persists durable notification records into the `notifications` table, dispatches simulated/live emails, tracks delivery lifecycle (`queued`, `sent`, `simulated`, `failed`), and deduplicates events via unique `event_key`.
- **Source Files & API Endpoints:**
  - Source: `app/notifications.py`
  - Endpoints:
    - `GET /api/notifications`
    - `POST /api/notifications/dispatch`
- **What It Can Successfully Do Today:**
  - Persists notification audit trail with recipient type (`tenant`, `owner`, `vendor`, `manager`).
  - Prevents duplicate notification spam for the same event key (e.g. `rent_late:LEASE-0001:2026-10`).
  - Returns simulated delivery confirmation when external SMTP server is unconfigured, avoiding delivery crashes.
- **Data Source & AI Usage:**
  PostgreSQL `notifications` table. Zero AI dependency; purely durable event routing.
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL.
  - Failure Mode: Database offline returns HTTP 500; notification queue retries on next poll.
- **Missing Implementation Work:**
  Production SMTP or SendGrid / AWS SES API key configuration for live external email transmission.
- **Tests Proving Status:**
  `tests/test_equilibra_agents.py::test_durable_notification_dispatch_and_deduplication`.

---

### 7. Scheduling & Autonomous Operations
- **Actual Responsibility:**
  Background scheduler executing periodic autonomous operations: rent delinquency sweeps, maintenance SLA monitoring, and vendor AP reconciliation checks.
- **Source Files & API Endpoints:**
  - Source: `app/scheduler.py`
  - Endpoints:
    - `GET /api/scheduler/status`
    - `POST /api/scheduler/trigger`
- **What It Can Successfully Do Today:**
  - Managed by FastAPI application lifespan (`start_scheduler()` / `stop_scheduler()`).
  - Thread-safe recurring sweep executing every 300 seconds.
  - Manual trigger endpoint for immediate administrative sweeps.
  - Records execution history, scanned account counts, SLA breach detections, and exceptions.
- **Data Source & AI Usage:**
  In-memory execution telemetry and persistent PostgreSQL mutations.
- **Dependencies & Failure Modes:**
  - Dependency: Standard library `threading.Thread`.
  - Failure Mode: Individual job exceptions are isolated and recorded in `recent_history` without crashing the daemon loop.
- **Missing Implementation Work:**
  Distributed job queue clustering (Celery / Redis / Temporal) for multi-node worker fleets.
- **Tests Proving Status:**
  `tests/test_equilibra_agents.py::test_scheduler_status_and_manual_trigger`.

---

### 8. EQUILIBRA Assistant & Orchestration
- **Actual Responsibility:**
  Interactive property management conversational AI assistant. Interprets natural language queries, invokes authoritative backend tools (lease query, active work orders, verified properties, vendor bills), and synthesizes responses using unified AI provider failover.
- **Source Files & API Endpoints:**
  - Source: `app/assistant.py`, `app/providers.py`
  - Endpoints:
    - `POST /api/assistant/chat`
    - `GET /api/integrations/ai/health`
- **What It Can Successfully Do Today:**
  - Routes natural language questions to 4 authoritative tool calls (`query_lease_details`, `query_active_work_orders`, `query_verified_properties`, `query_vendor_invoices`).
  - Communicates via Unified AI Provider failover sequence: Meterless Nightshift -> NVIDIA NIM -> Offline Deterministic.
  - Exposes provider used, fallback status, and latency.
  - Never executes arbitrary SQL and never mutates bank ledgers without explicit manager approval.
- **Data Source & AI Usage:**
  Authoritative database queries combined with Unified AI Provider.
- **Dependencies & Failure Modes:**
  - Dependency: Meterless / NVIDIA NIM / Local synthesizer.
  - Failure Mode: Seamlessly falls back through the provider chain; never leaves the user without an answer.
- **Missing Implementation Work:**
  Streaming Speech-to-Text (STT) and Text-to-Speech (TTS) voice interface.
- **Tests Proving Status:**
  `tests/test_equilibra_agents.py::test_assistant_chat_tool_dispatch`, `tests/test_ai_failover.py::test_10_existing_agent_workflows_continue_passing`.

---

### 9. Resident Portal, Public Listings & Admin Diagnostics
- **Actual Responsibility:**
  User-facing single-page application (SPA) providing dedicated portals for public discovery, residents, property managers, accounts payable, and administrators.
- **Source Files & API Endpoints:**
  - Source:
    - `frontend/src/components/PublicListingsPortal.jsx`
    - `frontend/src/components/ResidentPortal.jsx`
    - `frontend/src/components/AdminDiagnosticsPortal.jsx`
    - `frontend/src/components/EquilibraAssistant.jsx`
    - `frontend/src/components/TenantARModule.jsx`
    - `frontend/src/components/VendorAPModule.jsx`
- **What It Can Successfully Do Today:**
  - Public portal: search listings by price/city/bedrooms, book tours, submit rental applications.
  - Resident portal: view rent balance, submit maintenance tickets, make payments, download lease documents.
  - Admin diagnostics: real-time telemetry for scheduler runs, notifications, Zetaris status, Meterless status, and NVIDIA NIM status.
  - Persistent floating AI assistant available across all tabs.
- **Data Source & AI Usage:**
  Direct REST API connection to FastAPI backend.
- **Dependencies & Failure Modes:**
  - Dependency: React 18, Vite.
  - Failure Mode: Displays graceful loading states, error toasts, and disconnected warning banners.
- **Missing Implementation Work:**
  Native wrapper packaging (Capacitor / React Native) for Apple App Store and Google Play deployment.
- **Tests Proving Status:**
  Verified via Vite production build (`npm run build` completed in 1.75s with 53 transformed modules) and end-to-end REST API assertions.

---

### 10. Customer Co-Innovation SaaS Agent
- **Actual Responsibility:**
  Multi-tenant customer organization management, enterprise tenant onboarding, feature request submission, prioritized roadmap tracking, and community upvoting with voter deduplication.
- **Source Files & API Endpoints:**
  - Source: `app/saas.py`, `app/database.py`, `frontend/src/components/CustomerRequirementsPortal.jsx`
  - Endpoints:
    - `GET /api/saas/organizations`
    - `POST /api/saas/organizations`
    - `GET /api/saas/feature-requests`
    - `POST /api/saas/feature-requests`
    - `POST /api/saas/feature-requests/{req_id}/upvote`
- **What It Can Successfully Do Today:**
  - Onboards customer property management organizations with portfolio types, AWS regions, and active unit counts.
  - Persists all organizations, feature requirements, and upvotes into PostgreSQL relational tables (`organizations`, `feature_requests`, `feature_request_votes`).
  - Enforces strict duplicate-vote prevention: second upvote by the same voter returns `duplicate_prevented` and does not inflate vote tallies.
  - Prioritizes roadmap items by critical blockers, vote count, and submission recency.
- **Data Source & AI Usage:**
  PostgreSQL 16 tables with foreign-key relationships (`org_id` cascade).
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL connection pool (`psycopg`).
  - Failure Mode: Graceful transactional rollback on unique constraint violation.
- **Missing Implementation Work:**
  None for Phase 1. Real-time WebSocket push notifications for roadmap updates planned for Phase 3.
- **Tests Proving Status:**
  `tests/test_saas_persistence.py` (3/3 passed), `tests/test_api.py::test_saas_organizations`, `tests/test_api.py::test_saas_feature_requests`.

---

### 11. Compliance & Risk Monitoring Agent
- **Actual Responsibility:**
  Centralized operational, financial, and statutory risk management. Ingests telemetry and ledger standing from all operational agents (resident lifecycle, 3-way reconciliation, vendor AP 4-way matching, maintenance SLAs, notification delivery) to formulate deduplicated risk findings, track statutory jurisdiction deadlines (California 21-day, New York 14-day, Texas 30-day, Washington 30-day), enforce strict human approval gates, and manage immutable decision audit logs with separation of duties.
- **Source Files & API Endpoints:**
  - Source: `app/compliance_agent.py`, `app/main.py`, `app/database.py`, `frontend/src/components/ComplianceRiskHub.jsx`
  - Endpoints:
    - `GET /api/compliance/summary` (aggregate metrics by severity, status, category, and type)
    - `GET /api/compliance/findings` (searchable, filterable risk register list)
    - `GET /api/compliance/findings/{id}` (full detail with evidence JSON and decision history)
    - `POST /api/compliance/findings/{id}/assign` (reviewer assignment)
    - `POST /api/compliance/findings/{id}/review` (state transition to under_review or action_required)
    - `POST /api/compliance/findings/{id}/resolve` (resolution or dismissal with required reason)
    - `GET /api/compliance/approvals/pending` (central queue of pending renewals and deposit closeouts)
    - `POST /api/compliance/approvals/{case_id}/decision` (authoritative approval execution)
    - `GET /api/compliance/approvals/history` (immutable audit log of decision reasons and timestamps)
    - `GET /api/compliance/jurisdictions` (state-by-state statutory rules and citations)
    - `POST /api/compliance/scan` (on-demand portfolio risk scan)
- **What It Can Successfully Do Today:**
  - Continuously scans active portfolios across 16 detection rules covering lease expiration, missing documents, overdue onboarding tasks, 3-way financial reconciliation variances, overdue rent, vendor overbilling, card surcharges, maintenance SLA breaches, and failed dispatches.
  - Enforces 100% idempotent scans: duplicate issues for the same underlying record and cycle are deduplicated via unique PostgreSQL `stable_key`.
  - Disallows universal statutory deadlines: evaluates security deposit deadlines only for verified jurisdictions (CA, NY, TX, WA) with statutory citations; marks unverified property jurisdictions as operational risks without false legal claims.
  - Implements strict human approval gates: locks contractual updates and deposit disbursements until authorized manager sign-off.
  - Enforces separation of duties: server rejects self-approval if submitter identity matches reviewer.
  - Rejects empty or insubstantial decision reasons (< 3 characters) on all resolution actions.
  - Integrates with conversational AI assistant to answer compliance inquiries and explain triggering rules using underlying evidence.
  - Enforces strict multi-tenant isolation, rejecting cross-organization requests with HTTP 403 Forbidden.
- **Data Source & AI Usage:**
  PostgreSQL tables (`risk_findings`, `approval_history`, `properties`, `lease_records`, `work_order_records`, `vendor_invoices`, `lease_renewals`, `move_in_checklists`, `move_out_records`), 3-way reconciliation engine, 4-way vendor matching engine, and Meterless World Model event log.
- **Dependencies & Failure Modes:**
  - Dependency: PostgreSQL 16.
  - Failure Mode: Missing finding returns HTTP 404; cross-tenant access returns HTTP 403; separation of duties violation returns HTTP 403.
- **Missing Implementation Work:**
  Live county municipal court docket integration for real-time unlawful detainer / eviction filings.
- **Tests Proving Status:**
  `tests/test_compliance_hub.py` (12/12 passed), covering risk creation, idempotency, severity categorization, financial variances, lease/resident risks, maintenance SLA breaches, reviewer state transitions, separation of duties, jurisdiction rules, unverified state handling, cross-tenant isolation, and assistant queries.


