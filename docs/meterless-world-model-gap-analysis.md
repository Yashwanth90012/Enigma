# Meterless World Model Gap Analysis and Compatibility Matrix

## Executive Summary

This document presents a specification-driven gap analysis between ENIGMA's existing World Model (`app/world_model.py`) and the official Meterless World Model specification and reference implementation (`Meterless/engines/world-model/`).

The analysis assesses 11 core functional dimensions, evaluates compatibility, identifies verified gaps, and outlines an additive compatibility architecture that preserves all existing ENIGMA public interfaces, PostgreSQL event histories, and agent integrations while bringing ENIGMA into full alignment with the Meterless World Model specification.

---

## Capability Comparison Matrix

| # | Capability Area | Status | ENIGMA Current Reference | Meterless Official Reference | Conformance Vector |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Canonical ID Generation & Normalization** | **Partially Compatible** | `app/world_model.py:18` (`canonical_id`), `parse_canonical_id` | `reference/src/stableIds.ts:120` (`normalizeName`), `entityIdFromName`, `externalId`, `relationshipId`, `factId` | `sid-001`, `sid-002` |
| **2** | **Event Sourcing & Monotonic Versioning** | **Partially Compatible** | `app/world_model.py:41` (`record_event`), `world_events` table | `reference/src/types.ts:148` (`WorldEvent`), `store.ts:60` (`append`), monotonic `seq` | `audit-001` |
| **3** | **Deterministic State Projection & Replay** | **Partially Compatible** | `app/world_model.py:97` (`replay_events_for_state`), `get_latest_state` | `reference/src/index.ts:354` (`stateShape`), `store.ts:80` (`foldUntil`), `SnapshotView:entityAt` | `idem-001`, `idem-002` |
| **4** | **Entity & Relationship Graph Behavior** | **Missing** | Basic DAG lineage in `get_lineage()` linking `caused_by` IDs | `reference/src/index.ts:369` (`GraphView`: `neighborsOf`, `incoming`, `entitiesInContext`, `traverse`) | `bitemp-001` |
| **5** | **Bitemporal Relationship Tracking** | **Missing** | None (only point events) | `reference/src/types.ts:78` (`validFrom`, `validTo`, superseding close), `index.ts:382` | `bitemp-001` |
| **6** | **Idempotent Batch Ingestion** | **Missing** | Ad-hoc single event insertion | `reference/src/ingest.ts:30` (`runIngestPipeline`), `canonicalJson`, diff detection | `idem-001`, `idem-002` |
| **7** | **Entity Merge Thresholds & Review Gates** | **Missing** | None | `reference/src/resolve.ts:45` (`decide`), `nameSimilarity`, `mergeQueue`, `approveMerge`, `rejectMerge` | `band-001` |
| **8** | **Provenance & Causal Lineage** | **Partially Compatible** | `caused_by` in `world_events`, `get_lineage()` | `reference/src/types.ts:18` (`Provenance`), `normalizeProvenance` ("no provenance, no write") | `prov-001` |
| **9** | **Tenant & Namespace Scoping** | **Fully Compatible** | `case_id`, `lease_id`, `property_id`, `org_id` | `opts.namespace` per `WorldModel` instance | N/A |
| **10** | **Persistence & Recovery** | **Partially Compatible** | `world_events`, `derived_states` in PostgreSQL | In-memory / file in reference; PostgreSQL production tables needed for full entities/relationships | N/A |
| **11** | **Integration with H-MEM & Agents** | **Partially Compatible** | Agents call `record_event()`; H-MEM operates separately | Event-driven contextual memory publishing with decoupled non-blocking guarantees | N/A |

---

## Detailed Gap Findings

### 1. Canonical ID Generation and Unicode Normalization
- **Existing State:** `canonical_id(entity_type, raw_id)` in `app/world_model.py` creates string keys formatted as `type:clean_id`. For `tenant`, non-alphanumeric characters are converted to hyphens and lowercased.
- **Official Meterless Spec:**
  - `normalizeName(name)`: NFKD Unicode normalization $\to$ strip combining marks (`[\u0300-\u036F]`) $\to$ strip zero-width characters (`[\u200B-\u200D\uFEFF]`) $\to$ lowercase $\to$ collapse whitespace runs $\to$ trim.
  - `entityIdFromName(type, name)`: `ent_` + first 16 hex characters of `sha256(type + ":" + normalizeName(name))`.
  - Content-addressed relationship ID: `relationshipId(from, type, to, context, validFrom)`.
  - Content-addressed fact ID: `factId(about, predicate, value, assertedAt, sourceKind, sourceUrl)`.
- **Verdict & Resolution:** Implement `normalize_name()`, `entity_id_from_name()`, `relationship_id()`, `fact_id()`, and `context_id()` while retaining `canonical_id()` for backward compatibility with existing agent code.

### 2. Entity Resolution & Merge Decision Banding
- **Existing State:** None. Name variants (e.g. "Apex Plumbing" vs "Apex Plumbing LLC") create separate records without merge evaluation.
- **Official Meterless Spec (`resolve.ts`, vector `band-001`):**
  - Levenshtein-based similarity on normalized names: $1 - \frac{\text{distance}}{\max(\text{lenA}, \text{lenB})}$.
  - Strict boundary banding:
    - $\ge 0.85$: **`auto-merge`** (aliased immediately, alias event appended to log).
    - $0.82 \le \text{similarity} < 0.85$: **`review`** (staged into `mergeQueue` for operator approval).
    - $< 0.82$: **`new`** (retained as independent entity).
  - Human review operations: `approve_merge(proposal_id, by)` and `reject_merge(proposal_id, by)`.
- **Verdict & Resolution:** Implement Levenshtein similarity, the exact boundary thresholds, merge queue staging, and human approval/rejection endpoints.

### 3. Bitemporal Relationship Graph
- **Existing State:** Lineage DAG exists for causal event sequences (`caused_by`), but there is no entity-to-entity relationship graph supporting temporal validity.
- **Official Meterless Spec (`types.ts`, `GraphView`, vector `bitemp-001`):**
  - Edges have `validFrom` and `validTo`.
  - Adding a superseding relationship closes the existing edge (`validTo = newValidFrom`) without deleting historical records.
  - `neighborsOf(id, opts)` filters open edges for current queries, while supporting point-in-time validity via `opts.at`.
  - Graph traversal: `traverse(start_id, via, direction, max_depth)`.
- **Verdict & Resolution:** Add `relate()` primitive with bitemporal edge closing, point-in-time filtering, and `GraphView` queries.

### 4. Idempotent Ingestion Pipeline
- **Existing State:** Events are written individually via `record_event()`. No batch ingestion or diff detection exists.
- **Official Meterless Spec (`ingest.ts`, vectors `idem-001`, `idem-002`):**
  - Ingestion processes observation batches.
  - Running the identical batch twice yields `changed: false` and identical canonical state shapes (`canonicalJson()`).
  - Mutated batches detect differences and yield `changed: true`.
- **Verdict & Resolution:** Implement `ingest(observations)` pipeline, canonical state hashing, and idempotency verification.

### 5. Provenance Boundary Gate
- **Existing State:** Events accept arbitrary payloads; provenance is optional.
- **Official Meterless Spec (`prov-001`):**
  - "No provenance, no write" boundary invariant.
  - Every entity, context, relationship, and fact requires valid provenance (`kind` + `at`). Writes lacking provenance are rejected by construction.
- **Verdict & Resolution:** Enforce provenance validation on all core World Model write primitives.

### 6. Persistence & H-MEM Integration
- **Existing State:** `world_events` and `derived_states` tables exist in PostgreSQL.
- **Official Meterless Spec & Integration Contract:**
  - Persist entities, relationships, facts, and merge proposals into PostgreSQL so state survives service restarts.
  - When key events occur (e.g. lease signing, dispute resolution, work order completion, vendor bill reconciliation), publish concise contextual memory entries to H-MEM referencing authoritative World Model IDs.
  - Decouple H-MEM publishing in a try/except block so H-MEM errors never roll back or block the primary World Model transaction.

---

## Architectural Compatibility Design

To satisfy all requirements:
1. **Preserve `app/world_model.py`:** Retain all existing public functions (`canonical_id`, `parse_canonical_id`, `record_event`, `get_events`, `get_latest_state`, `get_lineage`, `build_agent_context`, `replay_events_for_state`) so all 12 calling agent modules and existing tests continue running without disruption.
2. **Implement `app/engines/world_model.py` & Extend `app/world_model.py`:** Expose the complete Meterless World Model class (`WorldModel`), stable ID derivations (`normalize_name`, `entity_id_from_name`, `external_id`, `relationship_id`, `fact_id`), resolution banding (`decide`, `levenshtein`, `name_similarity`), bitemporal graph views (`GraphView`, `FactsView`, `SnapshotView`, `TimelineView`), and ingestion pipeline.
3. **Additive PostgreSQL Tables:** Add `world_entities`, `world_relationships`, `world_facts`, and `world_merge_proposals` to `app/database.py`.
4. **H-MEM Event Hook:** Provide an idempotent post-commit event subscriber that stores durable context in H-MEM with full provenance references.
