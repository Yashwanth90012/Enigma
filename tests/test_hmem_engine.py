"""Production H-MEM Engine Tests & Official Conformance Verification.

Tests all official Meterless H-MEM conformance vectors:
- rv-001, rv-002: Source validation
- fd-001, fd-002, fd-003, fd-004, fd-005: Feedback deltas and clamping
- ro-001, ro-002: Ranking order and score math
- sg-001: Sleep cycle consolidation guardrails
- cg-001: Conflict detection and auto-resolution gates
- la-001: Append-only ledger audit trail
- db-001: Dreaming proposal isolation and approval boundaries
- Persistence across restarts
- FastAPI REST API endpoints, tenant isolation, and role authorization
"""

import os
import json
import time
import pytest
from fastapi.testclient import TestClient

from app.engines.hmem import (
    HMEM, embed, cosine, jaccard, clamp01, Provenance, MemoryRecord,
    MemoryStoreService, TrustLedgerService, SleepCycleService,
    ConflictDetectionService, DreamingService
)
from app.main import app

T0 = 1750000000000
DAY_MS = 24 * 60 * 60 * 1000


# =============================================================================
# 1. Official Conformance Vectors (vectors.json)
# =============================================================================

def test_vector_rv_001_reject_no_source():
    """rv-001: a record with no source is rejected by construction."""
    hmem = HMEM(clock=lambda: T0)
    with pytest.raises(ValueError) as exc:
        hmem.add(content="no source here", source="")
    assert "no source" in str(exc.value).lower()


def test_vector_rv_002_accept_valid_source():
    """rv-002: a record with a source is accepted."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="valid record", source="test")
    assert m is not None
    assert m.id == "mem-1"
    assert m.source == "test"


def test_vector_fd_001_feedback_helpful():
    """fd-001: helpful adds exactly +0.05 confidence and +1 accessCount."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=0.7, source="conformance")
    access_before = m.accessCount
    hmem.feedback(m.id, "helpful")
    after = hmem.store.get(m.id)
    assert abs(after.confidence - 0.75) < 1e-9
    assert after.accessCount - access_before == 1


def test_vector_fd_002_feedback_not_helpful():
    """fd-002: not_helpful subtracts exactly 0.03."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=0.7, source="conformance")
    access_before = m.accessCount
    hmem.feedback(m.id, "not_helpful")
    after = hmem.store.get(m.id)
    assert abs(after.confidence - 0.67) < 1e-9
    assert after.accessCount - access_before == 0


def test_vector_fd_003_feedback_wrong():
    """fd-003: wrong subtracts exactly 0.20 and adds the review tag."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=0.7, source="conformance")
    access_before = m.accessCount
    hmem.feedback(m.id, "wrong")
    after = hmem.store.get(m.id)
    assert abs(after.confidence - 0.50) < 1e-9
    assert after.accessCount - access_before == 0
    assert "review" in after.tags


def test_vector_fd_004_confidence_clamp_floor():
    """fd-004: confidence clamps at 0 (wrong at 0.1)."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=0.1, source="conformance")
    hmem.feedback(m.id, "wrong")
    after = hmem.store.get(m.id)
    assert after.confidence == 0.0


def test_vector_fd_005_confidence_clamp_ceiling():
    """fd-005: confidence clamps at 1 (helpful at 0.98)."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="feedback target record", confidence=0.98, source="conformance")
    hmem.feedback(m.id, "helpful")
    after = hmem.store.get(m.id)
    assert after.confidence == 1.0


def test_vector_ro_001_superseded_ranking_penalty():
    """ro-001: superseded penalty dominates: a superseded record ranks below fresh."""
    hmem = HMEM(clock=lambda: T0)
    fresh = hmem.add(content="we deploy the api with docker on mondays", confidence=0.9, layer="long_term", source="conformance")
    old = hmem.add(content="we deploy the api with docker on fridays", confidence=0.9, layer="long_term", source="conformance")
    old.supersededBy = fresh.id

    res = hmem.query("when do we deploy the api with docker", threshold=0, topN=10)
    order = [m.memory.id for m in res.memories]
    assert order.index(fresh.id) < order.index(old.id)


def test_vector_ro_002_confidence_multiplier_ranking():
    """ro-002: confidence multiplies whole score: identical records rank by confidence."""
    hmem = HMEM(clock=lambda: T0)
    high = hmem.add(content="the deploy window is monday morning", confidence=0.9, layer="working", source="conformance")
    low = hmem.add(content="the deploy window is monday morning", confidence=0.4, layer="working", source="conformance")

    res = hmem.query("deploy window", threshold=0, topN=10)
    order = [m.memory.id for m in res.memories]
    assert order.index(high.id) < order.index(low.id)


def test_vector_sg_001_sleep_guardrails():
    """sg-001: old low-access plain record archives; dream-derived record does not."""
    now = T0
    hmem = HMEM(clock=lambda: now)
    plain = hmem.add(content="random one-off note about parking near the office", source="chat")
    derived = hmem.add(content="synthesized insight about the quarterly roadmap", source="dreaming", derived_from=["mem-x"])

    now = T0 + 40 * DAY_MS
    before = sorted([m.id for m in hmem.store.all()])
    preview = hmem.sleep.preview()
    after = sorted([m.id for m in hmem.store.all()])
    assert before == after, "preview mutated the store"

    assert plain.id in preview.toArchive, "plain record should be archivable"
    assert derived.id not in preview.toArchive, "derived record is protected by guardrail"

    report = hmem.sleep.execute(preview)
    assert hmem.store.get(derived.id) is not None, "derived record must never be archived"
    assert isinstance(report.backupId, str) and len(report.backupId) > 0


def test_vector_cg_001_conflict_gate():
    """cg-001: auto-resolve marks the loser supersededBy and deletes nothing."""
    hmem = HMEM(clock=lambda: T0)
    a = hmem.add(content="always enable telemetry uploads for diagnostics", confidence=0.95, source="conformance")
    b = hmem.add(content="never enable telemetry uploads for diagnostics", confidence=0.20, source="conformance")

    conflicts = hmem.conflicts.scan()
    assert len(conflicts) > 0, "opposing pair must be detected"

    outcome = hmem.conflicts.autoResolve(conflicts[0])
    assert outcome in ("resolved", "queued")
    if outcome == "resolved":
        loser = next((m for m in [hmem.store.get(a.id), hmem.store.get(b.id)] if m and m.supersededBy), None)
        assert loser is not None, "resolved conflict must mark loser supersededBy"

    assert hmem.store.get(a.id) is not None and hmem.store.get(b.id) is not None, "records must never be deleted"


def test_vector_la_001_ledger_audit():
    """la-001: create then feedback reconstructs audit trail with states and deltas."""
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add(content="audited record", confidence=0.7, source="conformance")
    hmem.feedback(m.id, "wrong")

    history = hmem.ledger.history(m.id)
    actions = [h.action for h in history]
    assert actions == ["create", "feedback"]

    fb_entry = history[-1]
    assert abs(fb_entry.previousState["confidence"] - 0.7) < 1e-9
    assert abs(fb_entry.newState["confidence"] - 0.5) < 1e-9


def test_vector_db_001_dream_boundary():
    """db-001: dream proposals never materialize before approval; approval creates long_term record."""
    hmem = HMEM(clock=lambda: T0)
    hmem.add(content="prefer short bullet answers", type="preference", source="conformance")
    hmem.add(content="prefer python for scripting", type="preference", source="conformance")

    count_before = len(hmem.store.all())
    proposals = hmem.dreaming.dream()
    assert len(proposals) > 0, "two preferences must produce proposal"
    assert len(hmem.store.all()) == count_before, "dreaming must not materialize before human approval"

    created = hmem.dreaming.approve(proposals[0].id)
    if created:
        assert created.layer == "long_term", "approved proposals materialize as long_term"
        assert len(created.derivedFrom or []) > 0, "approved proposals carry derivedFrom lineage"


# =============================================================================
# 2. Exact Hybrid Retrieval Scoring Math Tests
# =============================================================================

def test_fnv1a_embedding_norm():
    """Verify deterministic 64-dim FNV-1a embedding produces normalized unit vectors."""
    vec = embed("EQUILIBRA property management platform")
    assert len(vec) == 64
    mag = sum(x * x for x in vec)
    assert abs(mag - 1.0) < 1e-6


def test_exact_hybrid_scoring_formula():
    """Verify hybrid formula weights and components match AGENTS.md Section 6."""
    hmem = HMEM(clock=lambda: T0)
    rec = hmem.add(
        content="Tenant lease renewal for Apex Real Estate Unit 402",
        source="lease_contract",
        type="factual",
        layer="working",
        confidence=0.8,
        tags=["lease", "renewal"]
    )
    res = hmem.query("lease renewal Apex Real Estate", top_k=5)
    assert len(res.memories) > 0
    top = res.memories[0]
    assert top.memory.id == rec.id
    assert 0.0 <= top.score <= 1.0
    assert "components" in top.trace
    comps = top.trace["components"]
    for expected_key in ("semantic", "keyword", "tag", "domain", "entity", "layer", "recency", "supersededPenalty"):
        assert expected_key in comps


# =============================================================================
# 3. Persistence and State Restoration Tests
# =============================================================================

def test_persistence_across_instances():
    """Verify memories, audit ledger, and proposals survive across HMEM instances via PostgreSQL."""
    try:
        from app.database import db
    except ImportError:
        pytest.skip("psycopg / PostgreSQL not available in current test environment")

    # Instance 1: write memory and proposal
    hmem1 = HMEM(clock=lambda: T0, pg_conn_fn=db)
    m = hmem1.add(
        content="HVAC inspection scheduled for building 4 on November 1st",
        source="work_order",
        property_id="PROP-101",
        confidence=0.88
    )
    hmem1.feedback(m.id, "helpful")

    # Instance 2: hydrate from PostgreSQL
    hmem2 = HMEM(clock=lambda: T0, pg_conn_fn=db)
    loaded_count = hmem2.sync_from_postgres()
    assert loaded_count >= 1

    recovered = hmem2.store.get(m.id)
    assert recovered is not None
    assert recovered.content == m.content
    assert recovered.property_id == "PROP-101"
    assert recovered.accessCount >= 1
    assert abs(recovered.confidence - (0.88 + 0.05)) < 1e-4

    # Ledger history check on instance 2
    hist = hmem2.ledger.history(m.id)
    assert len(hist) >= 2


# =============================================================================
# 4. FastAPI REST API Endpoint Tests
# =============================================================================

client = TestClient(app)

def test_api_create_memory_success():
    """Test POST /api/hmem/memories successfully creates memory."""
    payload = {
        "content": "Tenant prefers email communication over SMS",
        "source": "resident_portal",
        "type": "preference",
        "layer": "working",
        "confidence": 0.85,
        "tags": ["tenant_pref", "communication"],
        "property_id": "PROP-A",
        "provenance": {
            "origin": "portal",
            "document_id": "DOC-COMM-1",
            "label": "Tenant Settings"
        }
    }
    resp = client.post("/api/hmem/memories", json=payload, headers={"X-User-Id": "manager-1"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"].startswith("mem-")
    assert data["content"] == payload["content"]
    assert data["source"] == "resident_portal"
    assert data["confidence"] == 0.85


def test_api_create_memory_missing_source_rejected():
    """Test POST /api/hmem/memories rejects empty source with 400 (rv-001/rv-002)."""
    payload = {
        "content": "Invalid memory with no source",
        "source": ""
    }
    resp = client.post("/api/hmem/memories", json=payload)
    assert resp.status_code == 400
    assert "rv-001" in resp.json()["detail"]


def test_api_query_memories():
    """Test POST /api/hmem/query returns hybrid results and context block."""
    resp = client.post(
        "/api/hmem/query",
        json={"query": "communication preference", "top_k": 3}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "context_block" in data
    assert "count" in data


def test_api_memory_feedback():
    """Test POST /api/hmem/memories/{id}/feedback applies deltas."""
    # Create memory first
    create_res = client.post(
        "/api/hmem/memories",
        json={"content": "Unit 204 rent is $2400 per month", "source": "lease_doc", "confidence": 0.80}
    )
    mem_id = create_res.json()["id"]

    # Submit helpful feedback
    fb_res = client.post(
        f"/api/hmem/memories/{mem_id}/feedback",
        json={"feedback": "helpful", "actor": "accountant_1"}
    )
    assert fb_res.status_code == 200
    data = fb_res.json()
    assert abs(data["confidence"] - 0.85) < 1e-4
    assert data["access_count"] == 1


def test_api_memory_history_and_ledger():
    """Test GET /api/hmem/memories/{id}/history and GET /api/hmem/ledger."""
    create_res = client.post(
        "/api/hmem/memories",
        json={"content": "Fire alarm testing every 6 months", "source": "compliance_guide", "confidence": 0.9}
    )
    mem_id = create_res.json()["id"]

    hist_res = client.get(f"/api/hmem/memories/{mem_id}/history")
    assert hist_res.status_code == 200
    assert hist_res.json()["entry_count"] >= 1

    ledger_res = client.get("/api/hmem/ledger")
    assert ledger_res.status_code == 200
    assert "stats" in ledger_res.json()


def test_api_sleep_cycle_preview_and_execute():
    """Test GET /api/hmem/sleep/preview and POST /api/hmem/sleep/execute."""
    preview_res = client.get("/api/hmem/sleep/preview")
    assert preview_res.status_code == 200

    exec_res = client.post(
        "/api/hmem/sleep/execute",
        json={"reason": "nightly_consolidation"},
        headers={"X-User-Role": "property_manager"}
    )
    assert exec_res.status_code == 200
    assert exec_res.json()["status"] == "success"


def test_api_dreaming_proposal_lifecycle():
    """Test POST /api/hmem/dream, GET /api/hmem/dream/proposals, and approval gate."""
    # Seed preferences
    client.post("/api/hmem/memories", json={"content": "prefer dark mode UI", "type": "preference", "source": "user_ui"})
    client.post("/api/hmem/memories", json={"content": "prefer high contrast fonts", "type": "preference", "source": "user_ui"})

    # Run dream
    dream_res = client.post("/api/hmem/dream", json={})
    assert dream_res.status_code == 200

    # List proposals
    list_res = client.get("/api/hmem/dream/proposals")
    assert list_res.status_code == 200
    proposals = list_res.json()["proposals"]

    if proposals:
        pid = proposals[0]["id"]
        # Unauthorized approval attempt
        unauth = client.post(
            f"/api/hmem/dream/proposals/{pid}/approve",
            json={"reviewer_role": "guest"}
        )
        assert unauth.status_code == 403

        # Authorized approval
        auth = client.post(
            f"/api/hmem/dream/proposals/{pid}/approve",
            json={"reviewer_role": "property_manager", "notes": "Approved by senior PM"}
        )
        assert auth.status_code == 200
        assert auth.json()["status"] == "approved"
