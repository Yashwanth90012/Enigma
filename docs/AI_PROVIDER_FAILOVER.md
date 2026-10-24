# EQUILIBRA — Unified AI Provider Failover Architecture

## 1. Architecture Overview

EQUILIBRA implements a multi-tier, zero-downtime AI provider failover system. Individual agents and assistant routes never bind to a single remote LLM provider. Instead, all natural language inference requests pass through the centralized `UnifiedAIProvider` orchestrator (`app/providers.py`).

```
                              [ User Query / Agent Task ]
                                           │
                                           ▼
                               [ UnifiedAIProvider ]
                                           │
         ┌─────────────────────────────────┼────────────────────────────────┐
         │                                 │                                │
         ▼ (Primary)                       ▼ (Secondary)                    ▼ (Final Fallback)
[ Meterless / Nightshift ]       [ NVIDIA NIM Hosted API ]       [ Offline Deterministic Mode ]
  • Port 8088                      • https://integrate.api.nvidia   • Zero network reliance
  • Nemotron Local Lane              .com/v1                        • Exact Decimal 3-way math
  • Fast local inference           • Cloud Nemotron 70B/8B          • Guaranteed uptime
```

---

## 2. Failover Priority Sequence

1. **Meterless / Nightshift (Primary):**
   - Attempted first whenever configured with `METERLESS_TOKEN` and reachable at `METERLESS_BASE_URL`.
   - Optimized for local low-latency inference over the configured NVIDIA Nemotron lane.

2. **NVIDIA NIM Hosted API (Secondary Failover):**
   - Attempted automatically when Meterless is unconfigured, unreachable, returns HTTP 5xx, times out, or fails authentication.
   - Connects to NVIDIA's cloud inference endpoint `https://integrate.api.nvidia.com/v1` using `Authorization: Bearer $NVIDIA_NIM_API_KEY`.
   - Uses explicitly configured model: `NVIDIA_NIM_MODEL` (e.g. `nvidia/llama-3.1-nemotron-70b-instruct` or `meta/llama-3.1-8b-instruct`).

3. **Offline Deterministic Mode (Final Safety Fallback):**
   - Engaged automatically when both remote providers are unreachable, unconfigured, or fail.
   - Produces structured, factual property management reasoning grounded in authoritative database facts.
   - Guarantees 100% platform availability and prevents downtime during external provider outages.

---

## 3. Environment Configuration

The following variables in `.env` govern provider behavior and failover order:

```env
# Provider selection and failover
AI_PROVIDER=auto
AI_FALLBACK_ORDER=meterless,nim,offline

# Meterless/Nightshift (Primary)
METERLESS_BASE_URL=http://host.docker.internal:8088/v1
METERLESS_TOKEN=
METERLESS_MODEL=meterless/auto
METERLESS_TIMEOUT_SECONDS=30

# NVIDIA NIM hosted API (Secondary)
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_NIM_API_KEY=
NVIDIA_NIM_MODEL=nvidia/llama-3.1-nemotron-70b-instruct
NVIDIA_NIM_TIMEOUT_SECONDS=60

# Offline fallback
AI_OFFLINE_FALLBACK=true
AI_MAX_RETRIES_PER_PROVIDER=1
```

### Backward Compatibility:
- Setting `AI_PROVIDER=offline` forces the system directly into deterministic mode without attempting external networks.
- Setting `AI_PROVIDER=meterless` directs requests exclusively to Meterless.
- Setting `AI_PROVIDER=nim` directs requests exclusively to NVIDIA NIM.
- Setting `AI_PROVIDER=auto` (default) enables the full multi-tier failover chain.

---

## 4. Error Classification Taxonomy

The system classifies exceptions into granular categories to govern retry and failover decisions:

| Error Category | HTTP / System Condition | Retry Behavior | Failover Action |
|---|---|---|---|
| `auth_error` | HTTP 401, 403 (Invalid or expired token) | **Never retried** | Advances immediately to next provider |
| `connection_error` | `httpx.ConnectError`, `NetworkError` | Retried up to limit | Advances to next provider |
| `timeout_error` | `httpx.TimeoutException` | Retried up to limit | Advances to next provider |
| `server_error` | HTTP 500, 502, 503, 504 | Retried up to limit | Advances to next provider |
| `model_error` | HTTP 404 or HTTP 400 (model invalid) | **Never retried** | Advances to next provider |
| `malformed_output` | Empty choices, null content | **Never retried** | Advances to next provider |

---

## 5. Side Effects & Financial Safety Rules

A critical principle of autonomous property management is that **consequential side effects must never be repeated due to model inference failures**:

1. **Pure LLM Requests vs Consequential Operations:**
   - Pure synthesis requests (e.g. summarizing a lease, answering assistant chat, formatting an executive briefing) may be retried across providers.
   - Consequential actions (charging a tenant's bank account, issuing a refund, dispatching a vendor, creating a work order, sending an eviction notice) are guarded by **idempotency keys** and **never repeated** if a subsequent narrative generation step times out.
2. **Deterministic Arithmetic:**
   - All financial balances, rent variances, and late fees are calculated using exact Python `Decimal` arithmetic. The LLM is strictly prohibited from performing financial calculations.
3. **Approval Gates:**
   - Any variance detected on tenant ledgers automatically sets `requires_human_approval = True`. The agent never writes back ledger balances without property manager authorization.

---

## 6. Secret Redaction & Audit Integrity

- All API keys, tokens, and authorization headers are scrubbed before writing to logs, traces, or HTTP responses.
- `redact_secret(val)` preserves the first 4 characters and masks the remainder (`nvap...***...88`).
- `redact_headers(headers)` automatically strips `Authorization`, `x-api-key`, and `meterless-token`.
- `sanitize_for_audit(payload)` recursively masks any dict key containing `token`, `key`, `secret`, `password`, or `auth`.

---

## 7. Real Verification & Health Observability

EQUILIBRA does not rely on superficial HTTP 200 checks or static configuration presence. The diagnostics endpoints perform real lightweight network probes:

- **`GET /api/integrations/ai/health`**:
  Reports active mode, fallback order, last provider used, last fallback reason, and probe statuses for all three providers.
- **`GET /api/integrations/meterless/health`**:
  Executes a lightweight `GET /models` probe against `METERLESS_BASE_URL`.
- **`GET /api/integrations/nim/health`**:
  Executes a lightweight `GET /models` probe against `NVIDIA_NIM_BASE_URL` with bearer authorization, validating the presence of the configured model.
- **`GET /api/integrations/zetaris/health`**:
  Executes a read-only query probe against the Zetaris SQL runner endpoint, accurately reporting whether it is `live` or in `fixture_fallback` mode.

---

## 8. Zetaris Independence

**Zetaris is strictly an independent data federation system; it is NOT an AI inference provider.**
- Zetaris federates SQL queries across heterogeneous accounting data stores.
- It is never included in the LLM failover order.
- In the event that live Zetaris SQL views (`enigma_invoices`, `enigma_payments`, `enigma_bank_transactions`) are unmounted, the financial engine gracefully falls back to local PostgreSQL fixture tables, clearly labeling the data as `fixture_fallback` in audit traces and user interfaces.

---

## 9. Vector Embedding Provider Failover

Retaining zero-downtime guarantees for document intelligence, vector embeddings operate under a separate failover abstraction (`UnifiedEmbeddingProvider` in `app/embeddings.py`):

1. **Primary Semantic Tier (NVIDIA NIM):**
   - Calls `https://integrate.api.nvidia.com/v1/embeddings` using configured model (`EMBEDDING_MODEL=nvidia/nemotron-3.5-embed-1b`).
   - Uses Matryoshka Representation Learning (MRL) dimension truncation (`EMBEDDING_DIMENSION=384`) to match PostgreSQL `pgvector(384)` with HNSW cosine distance indexing (`chunks_hnsw`).
   - Verified live with conceptual semantic query discrimination.
2. **Offline Deterministic Fallback:**
   - Engaged automatically if NVIDIA NIM times out, fails authentication, or during network-isolated development.
   - Employs deterministic token-hashed 384-dimensional lexical vectors (`model_name='deterministic-hash-v1'`).
   - Accurately tracks vector provenance (`is_semantic: False`, `fallback_used: True`) in database chunk metadata.
3. **Observability Endpoint:**
   - **`GET /api/integrations/embeddings/health`**: Probes both the NVIDIA NIM embedding tier and offline deterministic tier, reporting active model, dimension, and semantic status.

