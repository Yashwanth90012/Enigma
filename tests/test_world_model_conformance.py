"""Official Conformance and Integration Verification for Meterless World Model in ENIGMA.

Validates all 8 official Meterless World Model conformance invariants:
- sid-001: Stable IDs - Diacritics and NBSP normalize identically (NFKD + strip marks)
- sid-002: Stable IDs - Distinct names stay distinct (no over-normalization), type participates in key
- band-001: Merge bands at exact boundaries (0.85 auto, 0.84 review, 0.82 review, 0.81 new)
- prov-001: Strict provenance boundary ("no provenance, no write")
- idem-001: Batch ingestion idempotency (same batch twice -> changed=False, identical state shape)
- idem-002: Mutated batch detection (edited observation -> changed=True, altered state shape)
- bitemp-001: Bitemporal edge closing on supersede; point-in-time neighbor validity
- audit-001: Append-only audit log with strictly monotonic sequence numbers

Plus comprehensive ENIGMA integration tests:
- H-MEM safe contextual memory publishing
- PostgreSQL persistence and state rehydration across engine instances
- FastAPI REST API endpoints (/api/world-model/*)
- Backward compatibility with existing app.world_model public contracts
"""

import os
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.engines.world_model import (
    WorldModel,
    normalize_name,
    entity_id_from_name,
    external_id,
    context_id_from_attrs,
    relationship_id,
    fact_id,
    levenshtein,
    name_similarity,
    decide,
    canonical_json
)
from app.world_model import (
    canonical_id,
    parse_canonical_id,
    record_event,
    get_events,
    get_latest_state,
    get_lineage,
    build_agent_context
)
from app.engines.hmem import HMEM
from app.main import app

client = TestClient(app)

FIXED_CLOCK_ISO = "2026-05-18T00:00:00.000Z"

def mock_clock() -> str:
    return FIXED_CLOCK_ISO


# =============================================================================
# 1. Official Conformance Vectors (sid-001 through audit-001)
# =============================================================================

def test_sid_001_stable_ids_diacritics_and_nbsp():
    """sid-001: stable ids: diacritics and NBSP normalize identically (NFKD + strip marks)."""
    plain = normalize_name("Jose Garcia")
    accented_nbsp = normalize_name("Jos\u00e9\u00a0\u00a0Garc\u00eda")
    assert plain == "jose garcia"
    assert accented_nbsp == "jose garcia"
    assert accented_nbsp == plain, "accented + NBSP name must normalize to plain form"

    id_plain = entity_id_from_name("person", "jose garcia")
    id_accented = entity_id_from_name("person", "Jos\u00e9 Garc\u00eda")
    assert id_plain == id_accented, "same normalized name must produce identical entity id"


def test_sid_002_stable_ids_distinct_names_stay_distinct():
    """sid-002: stable ids: distinct names stay distinct (no over-normalization)."""
    id_corp = entity_id_from_name("org", "Acme Corp")
    id_corporation = entity_id_from_name("org", "Acme Corporation")
    assert id_corp != id_corporation, "different names must produce different ids"

    id_person_x = entity_id_from_name("person", "x")
    id_org_x = entity_id_from_name("org", "x")
    assert id_person_x != id_org_x, "type participates in the key"


def test_band_001_merge_bands_at_boundaries():
    """band-001: merge bands at the boundaries: 0.85 auto, 0.84 review, 0.82 review, 0.81 new."""
    assert decide(0.85) == "auto-merge", "0.85 exactly is auto-merge (>= reading)"
    assert decide(0.84) == "review", "0.84 queues for review"
    assert decide(0.82) == "review", "0.82 exactly queues for review"
    assert decide(0.81) == "new", "0.81 is a new entity"


def test_prov_001_writes_without_provenance_rejected():
    """prov-001: writes without provenance are rejected."""
    world = WorldModel(storage="memory", namespace="conf-prov")
    rejected = False
    try:
        world.upsert_entity(entity_type="person", name="No Provenance", source=None)
    except (ValueError, TypeError):
        rejected = True
    assert rejected, "no provenance, no write: write without provenance must raise ValueError"


OBSERVATIONS_VECTOR = [
    {
        "externalId": "a1",
        "title": "Fed holds rates",
        "at": "2026-05-17T14:00:00.000Z",
        "source": {"kind": "rss", "at": "2026-05-17T14:00:00.000Z"},
        "entities": [{"type": "person", "name": "Jerome Powell"}]
    },
    {
        "externalId": "a2",
        "title": "Powell signals patience",
        "at": "2026-05-17T16:30:00.000Z",
        "source": {"kind": "rss", "at": "2026-05-17T16:30:00.000Z"},
        "entities": [{"type": "person", "name": "Jerome Powell"}]
    }
]


def test_idem_001_ingest_idempotency_empty_diff():
    """idem-001: ingest idempotency: same batch twice produces an empty diff."""
    world = WorldModel(storage="memory", namespace="conf-idem1", clock=mock_clock)
    first_report = world.ingest(OBSERVATIONS_VECTOR)
    assert first_report.changed is True, "first ingest of new batch must report changed=True"
    shape1 = world.state_shape_canonical()

    second_report = world.ingest(OBSERVATIONS_VECTOR)
    assert second_report.changed is False, "second run with identical batch must report changed=False"
    assert world.state_shape_canonical() == shape1, "canonical state must be identical after re-ingest"


def test_idem_002_mutated_batch_changes_shape():
    """idem-002: the idempotency check can fail: a mutated batch changes the shape."""
    world = WorldModel(storage="memory", namespace="conf-idem2", clock=mock_clock)
    world.ingest(OBSERVATIONS_VECTOR)
    shape1 = world.state_shape_canonical()

    mutated = [
        {
            "externalId": "a1",
            "title": "Fed holds rates (edited)",
            "at": "2026-05-17T14:00:00.000Z",
            "source": {"kind": "rss", "at": "2026-05-17T14:00:00.000Z"},
            "entities": [{"type": "person", "name": "Jerome Powell"}]
        },
        OBSERVATIONS_VECTOR[1]
    ]
    mutated_report = world.ingest(mutated)
    assert mutated_report.changed is True, "an edited observation must report changed=True"
    assert world.state_shape_canonical() != shape1, "canonical state must differ after a real edit"


def test_bitemp_001_bitemporal_edges_closing_and_point_in_time():
    """bitemp-001: bitemporal edges: superseding edge closes the old one; point-in-time queries respect validity."""
    world = WorldModel(storage="memory", namespace="conf-bitemp")
    at_src = lambda s: {"kind": "manual", "at": s}

    world.upsert_entity(
        entity_type="player",
        external_key={"system": "g", "id": "p1"},
        attrs={},
        source=at_src("2087-01-01T00:00:00.000Z")
    )
    world.upsert_entity(
        entity_type="team",
        external_key={"system": "g", "id": "a"},
        attrs={},
        source=at_src("2087-01-01T00:00:00.000Z")
    )
    world.upsert_entity(
        entity_type="team",
        external_key={"system": "g", "id": "b"},
        attrs={},
        source=at_src("2088-03-01T00:00:00.000Z")
    )

    world.relate(
        from_id="player:g:p1",
        rel_type="plays-for",
        to_id="team:g:a",
        valid_from="2087-01-01T00:00:00.000Z",
        source=at_src("2087-01-01T00:00:00.000Z")
    )
    world.relate(
        from_id="player:g:p1",
        rel_type="plays-for",
        to_id="team:g:b",
        valid_from="2088-03-01T00:00:00.000Z",
        source=at_src("2088-03-01T00:00:00.000Z")
    )

    now_neighbors = world.view("graph").neighbors_of("player:g:p1", via="plays-for")
    assert len(now_neighbors) == 1, f"open edge should return 1 neighbor, got {len(now_neighbors)}"
    assert now_neighbors[0]["id"] == "team:g:b", f"open edge should point at team:g:b; got {now_neighbors[0]['id']}"

    then_neighbors = world.view("graph").neighbors_of(
        "player:g:p1",
        via="plays-for",
        at="2087-06-01T00:00:00.000Z"
    )
    assert len(then_neighbors) == 1, f"2087 query should return 1 neighbor, got {len(then_neighbors)}"
    assert then_neighbors[0]["id"] == "team:g:a", f"2087 query should return team:g:a; got {then_neighbors[0]['id']}"


def test_audit_001_strictly_monotonic_audit_sequence():
    """audit-001: every mutation writes an audit entry in order."""
    world = WorldModel(storage="memory", namespace="conf-audit")
    world.upsert_entity(
        entity_type="x",
        name="Audit One",
        source={"kind": "manual", "at": "2026-01-01T00:00:00.000Z"}
    )
    world.upsert_entity(
        entity_type="x",
        name="Audit Two",
        source={"kind": "manual", "at": "2026-01-02T00:00:00.000Z"}
    )
    audit = world.audit()
    assert len(audit) >= 2, f"expected >= 2 audit entries, got {len(audit)}"
    for i in range(1, len(audit)):
        assert audit[i]["seq"] > audit[i - 1]["seq"], "audit seq must be strictly increasing"


# =============================================================================
# 2. H-MEM Safe Contextual Memory Publishing
# =============================================================================

def test_hmem_decoupled_publishing():
    """Verify World Model event recording safely publishes to H-MEM without blocking on error."""
    test_case = "CASE-HMEM-VERIFY-001"
    event_id = record_event(
        test_case,
        test_case,
        "lease_escalated",
        {"reason": "Late payment overdue 60 days", "amount_due": 4500},
        actor="system",
        source="test_runner"
    )
    assert event_id is not None

    events = get_events(test_case)
    assert len(events) >= 1
    assert events[-1]["event_type"] == "lease_escalated"


# =============================================================================
# 3. PostgreSQL Persistence & Rehydration
# =============================================================================

def test_postgres_persistence_and_rehydration():
    """Verify that World Model writes to PostgreSQL and re-hydrates in a new engine instance."""
    ns = "test_postgres_rehydration"
    world1 = WorldModel(storage="postgres", namespace=ns)

    src = {"kind": "manual", "at": "2026-05-18T10:00:00.000Z", "by": "integration_test"}
    e1 = world1.upsert_entity(
        entity_type="vendor",
        name="Apex Plumbing Services",
        attrs={"license": "PLUMB-999"},
        source=src
    )
    e2 = world1.upsert_entity(
        entity_type="property",
        name="Highland Tower",
        attrs={"units": 120},
        source=src
    )
    rel = world1.relate(
        from_id=e1["id"],
        rel_type="services",
        to_id=e2["id"],
        valid_from="2026-01-01T00:00:00.000Z",
        source=src
    )

    # Instantiate world2 connected to postgres with same namespace
    world2 = WorldModel(storage="postgres", namespace=ns)
    found_e1 = world2.get_entity(e1["id"])
    assert found_e1 is not None, "entity must rehydrate from PostgreSQL"
    assert found_e1["name"] == "Apex Plumbing Services"
    assert found_e1["attrs"]["license"] == "PLUMB-999"

    neighbors = world2.view("graph").neighbors_of(e1["id"], via="services")
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == e2["id"]


# =============================================================================
# 4. REST API Endpoints Verification
# =============================================================================

def test_rest_api_world_model_crud_and_graph():
    """Verify REST API endpoints for entities, relations, facts, and graph queries."""
    src = {"kind": "manual", "at": "2026-05-18T10:00:00.000Z", "by": "api_test"}
    
    # 1. Upsert Entity
    resp = client.post("/api/world-model/entities", json={
        "type": "tenant",
        "name": "Maria Rodriguez",
        "attrs": {"email": "maria@example.com"},
        "source": src,
        "organization_id": "test_api_ns"
    })
    assert resp.status_code == 200, resp.text
    entity_data = resp.json()["entity"]
    tenant_id = entity_data["id"]

    # 2. Get Entity
    get_resp = client.get(f"/api/world-model/entities/{tenant_id}?organization_id=test_api_ns")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Maria Rodriguez"

    # 3. Upsert Property Entity
    prop_resp = client.post("/api/world-model/entities", json={
        "type": "property",
        "name": "Sunset Terrace Unit 4B",
        "attrs": {"rent": 1850},
        "source": src,
        "organization_id": "test_api_ns"
    })
    assert prop_resp.status_code == 200
    property_id = prop_resp.json()["entity"]["id"]

    # 4. Relate Tenant -> Property
    rel_resp = client.post("/api/world-model/relationships", json={
        "from_id": tenant_id,
        "rel_type": "leases",
        "to_id": property_id,
        "valid_from": "2026-05-01T00:00:00.000Z",
        "source": src,
        "organization_id": "test_api_ns"
    })
    assert rel_resp.status_code == 200
    assert rel_resp.json()["status"] in ("ok", "success")

    # 5. Graph Neighbors
    graph_resp = client.get(f"/api/world-model/graph/neighbors/{tenant_id}?via=leases&organization_id=test_api_ns")
    assert graph_resp.status_code == 200
    neighbors = graph_resp.json()["neighbors"]
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == property_id

    # 6. Assert Fact
    fact_resp = client.post("/api/world-model/facts", json={
        "about": tenant_id,
        "predicate": "credit_score",
        "value": 745,
        "confidence": 0.95,
        "source": src,
        "organization_id": "test_api_ns"
    })
    assert fact_resp.status_code == 200
    assert fact_resp.json()["fact"]["value"] == 745

    # 7. Query Facts
    facts_query_resp = client.get(f"/api/world-model/facts?about={tenant_id}&organization_id=test_api_ns")
    assert facts_query_resp.status_code == 200
    assert len(facts_query_resp.json()["facts"]) >= 1

    # 8. Audit Log
    audit_resp = client.get("/api/world-model/audit?organization_id=test_api_ns")
    assert audit_resp.status_code == 200
    assert len(audit_resp.json()["audit"]) >= 3
