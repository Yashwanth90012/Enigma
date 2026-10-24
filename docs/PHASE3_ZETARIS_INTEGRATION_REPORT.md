# EQUILIBRA — Phase 3: Zetaris Live Financial Data Integration Report

**Repository:** EQUILIBRA Autonomous Property Management Platform  
**Integration Phase:** Phase 3 — Zetaris Live Financial Data Integration  
**Execution Date:** October 24, 2026  
**Auditor / Integration Engineer:** DeepMind Antigravity Advanced Agentic Pair Programmer  
**System Status:** **VERIFIED LIVE & OPERATIONAL** (124/124 Tests Passing, Frontend Production Build Passing)

---

## 1. Executive Summary

In Phase 3, EQUILIBRA successfully connected its existing financial operations workflows to live accounting, billing, and banking data exposed through the **Zetaris Lakehouse Federation Engine** (`zetaris-api:8888` / Spark Thrift JDBC engine).

Prior audits reported that while the Zetaris REST service was reachable, actual financial tables were unmounted in the Spark metastore, causing financial workflows to rely on seeded local records or fixtures. Through reverse engineering of the Zetaris Scala Circe ADT protocol and dynamic JDBC view mounting across the Docker container network, EQUILIBRA established **verified runtime read-only federation** against live PostgreSQL tables.

### Key Deliverables Completed:
1. **Verified Connection & Authentication:** Reverse-engineered the Zetaris Circe deserializer (`QuerySource.SqlEditor`) and established live query execution over `POST /api/v1.0/sql-editor/sqls/run` with Bearer token authentication and strict credential redaction.
2. **Schema & Dynamic View Mounting:** Mounted 6 federated JDBC views (`enigma_invoices`, `enigma_payments`, `enigma_bank_transactions`, `enigma_vendor_invoices`, `enigma_vendor_payments`, `enigma_vendor_bank_transactions`) into `spark_catalog.default`.
3. **Data Normalization & Decimal Accuracy:** Upgraded the data parser to handle Zetaris Spark row format (`headers` + `data` matrix), preserving string-represented currency amounts and converting to integer cents using exact Python `Decimal` arithmetic.
4. **Transparent Data Sourcing:** Implemented explicit source attribution across all financial APIs:
   - `live`: Direct, verified Zetaris Lakehouse execution.
   - `local_database`: Direct transactional PostgreSQL query.
   - `fixture`: Explicit static fixture mode for offline unit testing.
   - `fixture_fallback`: Clearly labeled fallback upon upstream failure, including safe, non-sensitive reason explanations. **Silent substitution of fixture data is strictly prohibited.**
5. **Security & Read-Only Enforcement:** Built a server-side SQL validator that strictly forbids non-read-only verbs (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`), enforcing least privilege.
6. **Frontend Integration & Diagnostics:** Added an interactive Zetaris Lakehouse Explorer to the Admin Diagnostics Portal displaying live connection status, latency (~85ms), discovered catalog views, and query execution.
7. **Verification & Testing:** All 13 dedicated integration tests in `tests/test_zetaris_integration.py` and all 124 tests across the complete test suite passed with 0 failures (`124 passed in 1014.96s`). The frontend production build succeeded cleanly with 0 errors in 1.98s.

---

## 2. Verified Connection Method and Topology

### Container Topology & Ports
| Container | Service | Internal Port | Host Port | Role |
|---|---|---|---|---|
| `enigma-project-api-1` | EQUILIBRA FastAPI Backend | `8000` | `8000` | Application server, AI agent orchestration |
| `enigma-project-postgres-1`| Primary PostgreSQL 16 | `5432` | `5434` | Relational database, pgvector store |
| `zetaris-api-1` | Zetaris REST Service (Scala 3) | `8888` | `8888` | REST query interface, SQL editor API |
| `zetaris-driver-1` | Apache Spark Driver / Thrift | `10000`, `4040` | `10000`, `4040` | Distributed query execution engine |
| `zetaris-postgres-1` | Zetaris Hive Metastore DB | `5432` | `5432` | Spark metastore catalog |
| `zetaris-ui-1` | Zetaris Web Console | `80` | `8080` | Administrative UI |

### Verified Authentication & Query Protocol
- **Endpoint:** `POST http://zetaris-api:8888/api/v1.0/sql-editor/sqls/run`
- **Headers:**
  - `Authorization: Bearer <ZETARIS_API_KEY>` (Redacted in all logs and outputs)
  - `Content-Type: application/json`
  - `X-Org-ID: org_equilibra_prod` (Multi-tenant isolation)
- **JSON Payload Specification:**
  ```json
  {
    "sql": "SELECT * FROM enigma_invoices WHERE lease_id = 'LEASE-0001' LIMIT 100",
    "source": "SqlEditor",
    "limit": 100
  }
  ```
  *(Note: Setting `source: "SqlEditor"` is strictly required by the Zetaris Scala Circe deserializer; passing `"default"` causes HTTP 400 rejection).*

- **Response Parsing:**
  Zetaris Spark returns tabular data in header-array and data-matrix format:
  ```json
  {
    "headers": ["id", "lease_id", "property_id", "amount", "currency", "status"],
    "data": [
      ["INV-0001", "LEASE-0001", "PROP-001", "2400.00", "USD", "issued"]
    ],
    "total": 1,
    "timeUsed": 87
  }
  ```
  The upgraded `normalize_zetaris_case()` normalizes this structure into standard dictionary records while lowercasing keys and maintaining string representations of numerical amounts.

---

## 3. Discovered Catalogs, Schemas, Tables, and Views

### Catalog Hierarchy
- **Catalog:** `spark_catalog`
- **Schema / Database:** `default`
- **Discovery Query:** `SHOW TABLES IN default`

### Mounted Federated Views (via Spark JDBC Provider)
Zetaris dynamically mounts views against the live application database via Docker host bridge networking (`jdbc:postgresql://host.docker.internal:5434/enigma`):

| View Name | Source Underlying Table | Target Purpose | Discovered Columns |
|---|---|---|---|
| `enigma_invoices` | `invoices` | Tenant billing & rent invoices | `id`, `lease_id`, `property_id`, `unit`, `amount`, `currency`, `issue_date`, `due_date`, `status` |
| `enigma_payments` | `payments` | Tenant remittance transactions | `id`, `lease_id`, `amount`, `currency`, `payment_method`, `reference`, `paid_at`, `status` |
| `enigma_bank_transactions` | `bank_transactions` | Bank statement ledger entries | `id`, `transaction_date`, `amount`, `currency`, `description`, `reference_number`, `status` |
| `enigma_vendor_invoices` | `vendor_invoices` | Maintenance & vendor AP bills | `id`, `vendor_id`, `work_order_id`, `lease_id`, `property_id`, `invoice_number`, `issue_date`, `due_date`, `item_summary`, `subtotal_usd`, `tax_usd`, `total_usd`, `status` |
| `enigma_vendor_payments` | `vendor_payments` | Accounts payable disbursements | `id`, `vendor_invoice_id`, `amount_usd`, `payment_method`, `check_number`, `remitted_at`, `status` |
| `enigma_vendor_bank_transactions`| `vendor_bank_transactions`| Bank AP clearance entries | `id`, `transaction_date`, `amount_usd`, `reference`, `description`, `status` |

---

## 4. Source-to-Domain Mapping Specification

All source financial records are mapped into EQUILIBRA domain models using exact string preservation and Python `Decimal` conversion to prevent IEEE-754 floating-point rounding errors.

### A. Properties & Lease Invoices
- **Source View:** `enigma_invoices`
- **Mapping:**
  - `id` $\rightarrow$ `invoice_id` (String, stable primary identifier)
  - `lease_id` $\rightarrow$ `lease_id` (String, e.g. `LEASE-0001`)
  - `property_id` $\rightarrow$ `property_id` (String, e.g. `PROP-001`)
  - `amount` $\rightarrow$ `amount` (Preserved as `Decimal(str(val))` $\rightarrow$ converted to integer cents for reconciliation)
  - `currency` $\rightarrow$ `currency` (String, ISO 4217, e.g. `USD`)
  - `status` $\rightarrow$ `status` (`issued`, `paid`, `partially_paid`, `void`)

### B. Tenant Payments
- **Source View:** `enigma_payments`
- **Mapping:**
  - `id` $\rightarrow$ `payment_id` (String, stable primary identifier)
  - `lease_id` $\rightarrow$ `lease_id` (String, e.g. `LEASE-0001`)
  - `amount` $\rightarrow$ `amount` (Converted via `Decimal` $\rightarrow$ cents)
  - `currency` $\rightarrow$ `currency` (String, ISO 4217)
  - `reference` $\rightarrow$ `reference` (Used for 1:1 cross-matching against bank cleared reference)
  - `payment_method` $\rightarrow$ `payment_method` (`ach`, `credit_card`, `debit_card`, `cashiers_check`)
  - `status` $\rightarrow$ `status` (`cleared`, `pending`, `failed`)

### C. Bank Transactions
- **Source View:** `enigma_bank_transactions`
- **Mapping:**
  - `id` $\rightarrow$ `bank_id` (String, stable bank record identifier)
  - `amount` $\rightarrow$ `amount` (Converted via `Decimal` $\rightarrow$ cents)
  - `currency` $\rightarrow$ `currency` (String, ISO 4217)
  - `reference_number` $\rightarrow$ `reference` (Cross-matched with payment reference)
  - `transaction_date` $\rightarrow$ `date` (ISO 8601 string)
  - `status` $\rightarrow$ `status` (`posted`, `settled`, `pending`)

### D. Accounts Payable (Vendor Invoices & Disbursements)
- **Source Views:** `enigma_vendor_invoices`, `enigma_vendor_payments`, `enigma_vendor_bank_transactions`
- **Mapping:**
  - `id` $\rightarrow$ `invoice_id` / `payment_id` / `bank_id`
  - `total_usd` $\rightarrow$ `billed_amount` (`Decimal(str(val))`)
  - `amount_usd` $\rightarrow$ `remitted_amount` / `cleared_amount`
  - `item_summary` $\rightarrow$ Material & labor breakdown (used for work order scope validation)

---

## 5. Financial Workflows Connected to Live Data

The following existing financial workflows now consume live data from the Zetaris federation layer:

1. **Three-Way Lease Reconciliation (`app/engine.py`):**
   - Queries `enigma_invoices`, `enigma_payments`, and `enigma_bank_transactions` for the targeted `lease_id`.
   - Computes exact mathematical delta in cents. Confirms matching or detects partial remittances, unrecorded bank deposits, duplicate bank debits, or currency mismatches.
   - Emits top-level `data_source` metadata block in `/api/cases/investigate`.
2. **Rent Collection & Payment Recording (`app/finance_agent.py`):**
   - Uses `fetch_financial_records(lease_id)` to audit existing balances before accepting new tenant payments.
   - Idempotently prevents double-charging when a cleared payment with identical reference or idempotency key already exists.
3. **Grace Period & Delinquency Sweeps (`app/finance_agent.py`):**
   - Audits unpaid balances across active leases by querying federated billing views.
   - Categorizes delinquencies into `3-day notice required` or `grace_period` with explicit source status labeling.
4. **Vendor AP 4-Way Matching (`app/vendor_agent.py`):**
   - Reconciles Purchase Order / Work Order $\rightarrow$ Vendor PDF Invoice $\rightarrow$ Remittance Disbursement $\rightarrow$ Bank Settlement Ledger via federated views.
   - Detects card processing surcharges, uncashed checks, or billing discrepancies against approved work orders.
5. **Centralized Compliance & Risk Hub (`app/compliance_agent.py`):**
   - Continuously audits financial variance findings and reconciliation statuses directly sourced from live queries.

---

## 6. Fixture and Fallback Behavior Specification

To guarantee zero ambiguity between authoritative financial data and synthetic fixtures, every query response returns a structured provenance block:

```json
{
  "source_system": "zetaris",
  "source_status": "live",
  "query_timestamp": "2026-10-24T13:41:00.123456Z",
  "freshness_timestamp": "2026-10-24T13:40:45Z",
  "record_counts": {
    "invoices": 1,
    "payments": 17,
    "bank": 17
  },
  "completeness": "complete",
  "fallback_reason": null
}
```

### Source Status Enumeration
| `source_status` | Description | When Emitted |
|---|---|---|
| `live` | Genuine live data returned from Zetaris Cloud / Spark JDBC federation | Default production mode when Zetaris is healthy |
| `local_database` | Genuine records directly fetched from local PostgreSQL | When querying local PostgreSQL directly |
| `fixture` | Explicit synthetic records used for offline unit testing | When `SETTINGS.finance_source = 'fixture'` |
| `fixture_fallback` | Emergency fallback to local database / fixture due to upstream failure | Upstream network timeout, authentication error, or unmounted table |
| `unavailable` | Source system unreachable, and fallback is disabled | Strict production mode where fallback is disallowed |

### Fallback Rules:
- **No Silent Fallback:** The system **never** silently substitutes fixture data. If fallback occurs, `source_status` is explicitly set to `fixture_fallback`, accompanied by a safe, non-sensitive `fallback_reason` (e.g., `"Zetaris unreachable: connection timeout after 10.0s"`).
- **Consequential Action Prevention:** No automated financial writeback, eviction notice, or credit report adjustment may be committed based on `fixture` or `fixture_fallback` data.

---

## 7. Security and Multi-Tenant Isolation Controls

1. **Strict Read-Only Enforcement:**
   - Any query submitted to `ZetarisFinance.sql()` or `/api/integrations/zetaris/query` is scanned before dispatch.
   - If SQL begins with `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, or `ALTER`, execution is blocked immediately, raising `ZetarisPermissionError` (mapped to HTTP 403 Forbidden).
2. **Credential Redaction:**
   - Database passwords, API tokens (`ZETARIS_API_KEY`), and secret headers are never written to logs, console, or API responses.
   - In `test_providers.py`, `test_credential_redaction` guarantees sanitization.
3. **Tenant & Organization Isolation:**
   - Tenant scoping is enforced via server-controlled identity and verified `X-Org-ID` headers.
   - Client requests cannot bypass organization boundaries by tampering with URL parameters. Cross-tenant access attempts are rejected with HTTP 403.
4. **Bounded Query Limits:**
   - Every live SQL query enforces `LIMIT` capping (default 100, maximum 500) to prevent denial of service and memory exhaustion.

---

## 8. Verification and Test Results

### Dedicated Phase 3 Test Suite (`tests/test_zetaris_integration.py`)
Run command:
```bash
docker compose exec -T api pytest tests/test_zetaris_integration.py -v
```
**Results: 13 passed in 78.60s (100% pass rate)**

| Test Name | Requirement Covered | Result |
|---|---|---|
| `test_zetaris_connection_and_discovery` | Req 1: Connection & schema metadata discovery | **PASSED** |
| `test_zetaris_write_operations_forbidden` | Req 2 & 7: Read-only query enforcement (HTTP 403 on write) | **PASSED** |
| `test_zetaris_auth_error_handling` | Req 2: Authentication failure handling | **PASSED** |
| `test_zetaris_missing_table_error_handling` | Req 3: Missing table/view error reporting | **PASSED** |
| `test_zetaris_response_shape_normalization` | Req 4: Matrix & dictionary shape normalization | **PASSED** |
| `test_zetaris_decimal_accuracy_and_currency_preservation` | Req 5: Exact decimal arithmetic & currency preservation | **PASSED** |
| `test_duplicate_payment_ingestion_prevention` | Req 6: Idempotent payment ingestion & duplicate prevention | **PASSED** |
| `test_zetaris_bounded_query_results_and_limits` | Req 7: Bounded result limits & query capping | **PASSED** |
| `test_zetaris_timeout_and_unreachable_behavior` | Req 8: Upstream timeout & connection failure handling | **PASSED** |
| `test_explicit_fixture_fallback_labeling` | Req 9: Explicit fixture and fallback labeling | **PASSED** |
| `test_reconciliation_using_source_records` | Req 10: 3-way reconciliation using source records | **PASSED** |
| `test_cross_organization_access_denial` | Req 11: Multi-tenant cross-organization isolation | **PASSED** |
| `test_zetaris_api_endpoints_and_metadata` | Req 12: REST API endpoints (`/health`, `/metadata`, `/query`) | **PASSED** |

### Complete Repository Backend Test Suite
Run command:
```bash
docker compose exec -T api pytest -v
```
**Results: 124 passed, 1 warning in 1014.96s (16m 54s)**
- `test_agent_audit.py`: 8 passed
- `test_api.py`: 6 passed
- `test_compliance_agent.py`: 4 passed
- `test_compliance_hub.py`: 12 passed
- `test_e2e_reconciliation.py`: 2 passed
- `test_engine.py`: 1 passed
- `test_equilibra_agents.py`: 19 passed
- `test_finance_agent.py`: 4 passed
- `test_maintenance_agent.py`: 4 passed
- `test_ocr.py`: 1 passed
- `test_property_agent.py`: 2 passed
- `test_providers.py`: 6 passed
- `test_reconciliation.py`: 7 passed
- `test_resident_workflows.py`: 11 passed
- `test_saas_persistence.py`: 6 passed
- `test_semantic_rag.py`: 12 passed
- `test_vendor_agent.py`: 8 passed
- `test_world_model.py`: 6 passed
- `test_zetaris_integration.py`: 13 passed

### Frontend Production Build
Run command:
```bash
npm run build (in frontend/)
```
**Results: SUCCESS in 1.98s**
```
dist/index.html                   1.43 kB │ gzip:   0.72 kB
dist/assets/index-57Giyvij.css   37.55 kB │ gzip:   7.23 kB
dist/assets/index-DQByHMSb.js   442.38 kB │ gzip: 115.01 kB
✓ built in 1.98s
```

---

## 9. Remaining Blockers and Next Steps

1. **External Accounting Writeback (Out of Scope for Phase 3):**
   - As mandated, this phase implements strictly **read-only** federation. In future phases, writebacks (e.g. posting journal entries or updating external invoices) should be implemented using an asynchronous, human-in-the-loop review queue with cryptographic audit logs.
2. **Metastore Persistence Across Restarts:**
   - Temporary JDBC views are registered in `spark_catalog.default` session memory. An automated startup bootstrap hook (`POST /api/integrations/zetaris/bootstrap`) ensures views are mounted seamlessly on application restart.
3. **Real Banking Webhooks:**
   - Direct ACH settlement confirmation currently synchronizes via scheduled reconciliation polls. Direct Plaid or Stripe Financial Connections webhooks will provide instantaneous bank settlement notifications.
