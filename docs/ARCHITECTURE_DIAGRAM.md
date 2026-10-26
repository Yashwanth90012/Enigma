# EQUILIBRA — Enterprise Autonomous Property Management Platform
## System Architecture & Technical Topology

```mermaid
graph TB
    %% STYLING DEFINITIONS
    classDef client fill:#3b82f6,stroke:#1d4ed8,stroke-width:2px,color:#fff;
    classDef api fill:#6366f1,stroke:#4338ca,stroke-width:2px,color:#fff;
    classDef agent fill:#8b5cf6,stroke:#6d28d9,stroke-width:2px,color:#fff;
    classDef ai fill:#ec4899,stroke:#be185d,stroke-width:2px,color:#fff;
    classDef zetaris fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff;
    classDef storage fill:#10b981,stroke:#047857,stroke-width:2px,color:#fff;
    classDef meterless fill:#06b6d4,stroke:#0891b2,stroke-width:2px,color:#fff;

    %% 1. PRESENTATION TIER
    subgraph PRESENTATION["Presentation Tier (Vite + React 18 SPA)"]
        UI_DASH["Executive Command Center"]:::client
        UI_AR["Tenant AR Hub (3-Way Match)"]:::client
        UI_AP["Vendor AP Hub (4-Way Match)"]:::client
        UI_COMP["Compliance & Statutory Risk Register"]:::client
        UI_DOCS["Document Intelligence & OCR Vault"]:::client
        UI_EXPLORER["Zetaris Lakehouse Explorer"]:::client
    end

    %% 2. API & MULTI-TENANT GATEWAY TIER
    subgraph GATEWAY["API & Orchestration Tier (FastAPI + Uvicorn)"]
        AUTH_ROUTER["Multi-Tenant Isolation Router<br/>(X-Organization-Id: ORG-APEX, ORG-BEACON)"]:::api
        DAG_ORCH["Multi-Agent Workflow DAG Orchestrator<br/>(Human-in-the-Loop Review Gates)"]:::api
        
        subgraph AGENTS["Specialized Autonomous Agent Cluster"]
            AGT_FIN["Finance Reconciliation Agent<br/>(3-Way AR & Over/Under Ledger)"]:::agent
            AGT_VEND["Vendor Maintenance Agent<br/>(AP Match & OCR Bill Parsing)"]:::agent
            AGT_RES["Resident Experience Agent<br/>(Renewals, Move-In/Out Checklist)"]:::agent
            AGT_COMP["Statutory Compliance Agent<br/>(16 Rules across CA, NY, TX, WA)"]:::agent
            AGT_DOC["Document Intelligence Agent<br/>(PaddleOCR + Text Classifier)"]:::agent
        end
    end

    %% 3. MULTI-TIER AI INFERENCE TIER
    subgraph AI_ROUTING["Multi-Tier AI Reasoning Tier (UnifiedAIProvider)"]
        AI_GATEWAY{"Intelligent Failover Router<br/>(Auto Provider Selector)"}:::ai
        TIER_METERLESS["Tier 1: Meterless Nightshift<br/>(Local/Seated Lane: meterless/auto)"]:::ai
        TIER_NIM["Tier 2: NVIDIA NIM Cloud API<br/>(nvidia/llama-3.1-nemotron-70b)"]:::ai
        TIER_OFFLINE["Tier 3: Offline Deterministic Engine<br/>(Exact Decimal Cents Arithmetic)"]:::ai
    end

    %% 4. FEDERATED DATA LAKEHOUSE TIER
    subgraph FEDERATION["Data Federation Tier (Zetaris Cloud Platform)"]
        ZET_API["Zetaris REST API & Security Proxy<br/>(/sql-editor/sqls/run)"]:::zetaris
        ZET_GUARD["Read-Only Safety Guardrail<br/>(Blocks INSERT, UPDATE, DELETE, DROP)"]:::zetaris
        ZET_SPARK["Apache Spark Lightning Engine<br/>(Distributed SQL Federation)"]:::zetaris
        
        subgraph ZET_VIEWS["Mounted Federated Lakehouse Views"]
            V_INV["enigma_invoices"]:::zetaris
            V_PAY["enigma_payments"]:::zetaris
            V_BANK["enigma_bank_transactions"]:::zetaris
            V_VINV["enigma_vendor_invoices"]:::zetaris
            V_VPAY["enigma_vendor_payments"]:::zetaris
            V_VBANK["enigma_vendor_bank_transactions"]:::zetaris
        end
    end

    %% 5. PERSISTENCE & WORLD MODEL TIER
    subgraph PERSISTENCE["Storage & Immutable Event Sourcing Tier"]
        DB_PG[("PostgreSQL 16 (System of Record)<br/>Leases, Work Orders, Vendors, Orgs")]:::storage
        DB_VEC[("pgvector Extension<br/>HNSW 384-dim Nemotron Embeddings")]:::storage
        
        subgraph WORLD_MODEL["Meterless World Model Engine (app/world_model.py)"]
            WM_ID["Canonical Stable Entity IDs<br/>(SHA-256 UUIDv5 Namespacing)"]:::meterless
            WM_EVENTS[("Append-Only Event Store<br/>world_events (14,394+ Events)")]:::meterless
            WM_DAG["Causal Lineage DAG<br/>(caused_by & parent tracking)"]:::meterless
            WM_STATE["Derived State Projections<br/>(Deterministic Event Replay)"]:::meterless
        end
    end

    %% RELATIONSHIPS & DATA FLOWS
    PRESENTATION -->|HTTPS / REST API| AUTH_ROUTER
    AUTH_ROUTER --> DAG_ORCH
    DAG_ORCH --> AGENTS

    %% Agent to AI Routing
    AGENTS -->|Inference Prompts| AI_GATEWAY
    AI_GATEWAY -->|Primary Lane| TIER_METERLESS
    AI_GATEWAY -.->|Failover on Timeout/Error| TIER_NIM
    AI_GATEWAY -.->|Failover on Network Drop| TIER_OFFLINE

    %% Agent to Zetaris Lakehouse
    AGT_FIN -->|Federated SQL Queries| ZET_API
    AGT_VEND -->|Federated Bill Queries| ZET_API
    UI_EXPLORER -->|Lakehouse Probes| ZET_API
    ZET_API --> ZET_GUARD
    ZET_GUARD --> ZET_SPARK
    ZET_SPARK --> ZET_VIEWS
    ZET_VIEWS -.->|JDBC Driver Connection| DB_PG

    %% Agent to World Model & Vector Storage
    AGENTS -->|Record Event Mutation| WM_EVENTS
    WM_EVENTS --> WM_DAG
    WM_DAG --> WM_STATE
    WM_STATE -.->|State Context Hydration| DAG_ORCH
    AGT_DOC -->|Cosine Similarity Search| DB_VEC
    AGENTS -->|Transactional CRUD| DB_PG
```

---

### Tier-by-Tier Architecture Breakdown

#### 1. Presentation Tier (React 18 + Vanilla CSS SPA)
* **Modular Command Center:** 10 specialized operational hubs (Tenant AR, Vendor AP, Compliance Risk Register, Resident Experience, Document Intelligence, SaaS Co-Innovation, and Lakehouse Explorer).
* **Zero Configuration in UI:** Strict production posture where API keys and infrastructure URLs reside solely in backend `.env` variables.
* **Diagnostics Explorer:** Real-time observability UI displaying multi-tier AI latency, active providers, and direct SQL exploration of the Zetaris Lakehouse.

#### 2. Orchestration & Agent Cluster (FastAPI + Python 3.11)
* **Multi-Tenant Routing:** Hardware/software tenant isolation enforced at the gateway via `X-Organization-Id` headers across 29 customer organizations.
* **Deterministic DAG Orchestration:** Autonomous task sequencing with human-in-the-loop review gates for statutory legal notices, high-dollar approvals, and habitability escalations.
* **Specialized Agent Roles:** Dedicated domain agents (`FinanceAgent`, `VendorAgent`, `ResidentAgent`, `ComplianceAgent`, `DocumentAgent`, `NotificationAgent`) ensuring clean separation of duties without business logic overlap.

#### 3. Multi-Tier AI Reasoning Tier (`UnifiedAIProvider`)
* **Tier 1 (Primary): Meterless Nightshift:** Local/seated daemon (`http://host.docker.internal:8088/v1`) running the `meterless/auto` model for low-latency operational reasoning.
* **Tier 2 (Failover): NVIDIA NIM Cloud:** Hosted enterprise endpoint (`https://integrate.api.nvidia.com/v1`) serving `nvidia/llama-3.1-nemotron-70b-instruct` with 85-model failover capacity.
* **Tier 3 (Safety Net): Offline Deterministic Engine:** Zero-external-network mathematical engine executing exact decimal-cent arithmetic to guarantee 0% hallucination for monetary transactions.

#### 4. Data Federation Tier (Zetaris Cloud Platform)
* **Independent Virtual Lakehouse:** Decouples analytical and AI agent queries from the operational database to prevent table locks and unauthorized data mutations.
* **Read-Only Safety Enforcement:** Rejects write commands (`INSERT`, `UPDATE`, `DELETE`, `DROP`) before execution.
* **6 Federated Spark Views:** Mounts operational tables (`invoices`, `payments`, `bank_transactions`, `vendor_invoices`, `vendor_payments`, `vendor_bank_transactions`) via `org.apache.spark.sql.jdbc` on Spark Lightning.

#### 5. Storage & Meterless World Model Tier
* **PostgreSQL 16:** ACID transactional System of Record for property records, tenant leases, and maintenance work orders.
* **pgvector:** HNSW vector index storing 384-dimensional embeddings generated via NVIDIA Nemotron 3.5 1B.
* **Meterless World Model:** Cryptographically traceable, append-only event log (`world_events`) with deterministic UUIDv5 canonical IDs, causal DAG tracking (`caused_by`), and point-in-time state replay.
