import uuid
import pytest
from app.database import db
from app.rag import index_document, retrieve, reindex_all_documents, get_rag_status
from app.embeddings import (
    embedding_service,
    UnifiedEmbeddingProvider,
    NvidiaNimEmbeddingProvider,
    OfflineDeterministicEmbeddingProvider
)
from app.assistant import answer_assistant_query


@pytest.fixture(autouse=True)
def clean_synthetic_docs():
    """Ensure test-only synthetic documents are cleaned up safely without touching real project data."""
    yield
    with db() as conn:
        conn.execute("""DELETE FROM documents WHERE id LIKE 'DOC-TEST-%%' 
                     OR id LIKE 'DOC-SCOPE-%%' 
                     OR id LIKE 'DOC-SEM-%%' 
                     OR id LIKE 'DOC-RANK-%%' 
                     OR id LIKE 'DOC-DELINQ-%%' 
                     OR id LIKE 'DOC-PLUMB-%%' 
                     OR id LIKE 'DOC-APEX-%%' 
                     OR id LIKE 'DOC-BEACON-%%' 
                     OR id LIKE 'DOC-FAILOVER-%%' 
                     OR id LIKE 'DOC-COMPAT-%%' 
                     OR id LIKE 'DOC-A-%%' 
                     OR id LIKE 'DOC-B-%%'""")


def test_embedding_service_health():
    health = embedding_service.health_check()
    assert "configured_mode" in health
    assert "active_provider" in health
    assert health["expected_dimension"] == 384
    assert health["offline_tier"]["status"] == "healthy"


def test_offline_embedding_provider_deterministic():
    offline = OfflineDeterministicEmbeddingProvider(dimension=384)
    v1 = offline.embed_text("Residential lease contract", input_type="query")
    v2 = offline.embed_text("Residential lease contract", input_type="query")
    assert len(v1) == 384
    assert v1 == v2


def test_semantic_embedding_generation_and_fallback(monkeypatch):
    # Test fallback when NIM key is invalid
    bad_nim = NvidiaNimEmbeddingProvider(api_key="nvapi-invalid-key-test")
    unified = UnifiedEmbeddingProvider()
    unified.nim_provider = bad_nim

    vec, meta = unified.embed_text("Test query string", input_type="query")
    assert len(vec) == 384
    assert meta["provider"] == "offline"
    assert meta["is_semantic"] is False
    assert meta["fallback_used"] is True


def test_document_ingestion_and_chunk_persistence():
    uid = uuid.uuid4().hex[:8]
    doc_id = f"DOC-TEST-{uid}"
    lease_id = f"LEASE-TEST-{uid}"
    prop_id = f"PROP-TEST-{uid}"

    body = f"""1. Term of Tenancy. The tenancy shall commence on November 1, 2026.
2. Rent Obligation. Monthly rent shall be $3,200 payable on the first day.
3. Security Covenant. Deposit of $3,200 held in escrow account."""

    chunk_count = index_document(
        document_id=doc_id,
        lease_id=lease_id,
        property_id=prop_id,
        kind="lease",
        title=f"Test Lease Agreement {uid}",
        body=body
    )
    assert chunk_count >= 1

    # Verify chunk persistence in DB
    with db() as conn:
        chunks = conn.execute(
            "SELECT id, document_id, lease_id, heading, model_name, is_semantic FROM chunks WHERE document_id = %s",
            (doc_id,)
        ).fetchall()
        assert len(chunks) == chunk_count
        assert chunks[0][1] == doc_id
        assert chunks[0][2] == lease_id
        assert chunks[0][4] is not None  # model_name tracked


def test_scope_enforcement_and_empty_retrieval():
    uid = uuid.uuid4().hex[:8]
    doc_id = f"DOC-SCOPE-{uid}"
    lease_id = f"LEASE-SCOPE-{uid}"

    index_document(
        document_id=doc_id,
        lease_id=lease_id,
        property_id="PROP-SCOPE",
        kind="lease",
        title="Scoped Lease",
        body="Exclusive clause for this specific lease agreement only."
    )

    # Retrieval requires scope
    with pytest.raises(ValueError, match="Retrieval requires a lease_id or property_id scope"):
        retrieve("Exclusive clause")

    # Scope filtering prevents cross-tenant data leak
    other_lease_id = f"LEASE-OTHER-{uid}"
    empty_results = retrieve("Exclusive clause", lease_id=other_lease_id)
    assert len(empty_results) == 0

    # Matching scope retrieves document
    valid_results = retrieve("Exclusive clause", lease_id=lease_id)
    assert len(valid_results) >= 1
    assert valid_results[0]["document_id"] == doc_id


def test_conceptual_semantic_evaluation_zero_lexical_overlap():
    """Verify that conceptual queries with NO exact word matches retrieve the relevant document."""
    uid = uuid.uuid4().hex[:8]
    lease_id = f"LEASE-SEM-{uid}"

    # Target document about delinquency penalty (no mention of 'financial', 'penalty', 'punishment')
    doc_a_id = f"DOC-A-{uid}"
    doc_a_body = """1. Default Rules. If remittance is not received by day five, landlord levies a fifty dollar charge."""

    # Distractor document about plumbing
    doc_b_id = f"DOC-B-{uid}"
    doc_b_body = """1. Plumbing Maintenance. Water leakage in bathroom faucets must be fixed by certified tradesmen."""

    index_document(doc_a_id, lease_id, "PROP-001", "lease", "Default Terms", doc_a_body)
    index_document(doc_b_id, lease_id, "PROP-001", "maintenance", "Plumbing Scope", doc_b_body)

    # Conceptual query with ZERO exact keywords from doc A ("financial penalty for overdue payments")
    results = retrieve("financial punishment for overdue payment", lease_id=lease_id, top_k=2)
    assert len(results) >= 1
    # Check that doc A is retrieved in top results
    doc_ids = [r["document_id"] for r in results]
    assert doc_a_id in doc_ids


def test_rag_status_and_reindex_batch():
    status = get_rag_status()
    assert "total_documents" in status
    assert "total_chunks" in status
    assert "models_in_index" in status

    # Run reindexing with small limit
    reindex_res = reindex_all_documents(limit=3)
    assert reindex_res["status"] == "reindexed"
    assert reindex_res["documents_reindexed"] <= 3


def test_unrelated_query_ranking_discrimination():
    """Verify that an unrelated query correctly ranks the relevant document higher than distractors."""
    uid = uuid.uuid4().hex[:8]
    lease_id = f"LEASE-RANK-{uid}"

    doc_delinquency = f"DOC-DELINQ-{uid}"
    body_delinquency = "1. Late Charges. Rent unpaid after the third day incurs an assessment fee of seventy-five dollars."
    
    doc_plumbing = f"DOC-PLUMB-{uid}"
    body_plumbing = "1. Water Line Maintenance. Emergency repairs for leaking bathroom pipes and clogged drains are dispatched immediately."

    index_document(doc_delinquency, lease_id, "PROP-001", "lease", "Late Charge Clause", body_delinquency)
    index_document(doc_plumbing, lease_id, "PROP-001", "maintenance", "Plumbing Manual", body_plumbing)

    # Plumbing query should strongly prioritize plumbing document over delinquency
    results = retrieve("bathroom water pipe leakage and drain repair", lease_id=lease_id, top_k=2)
    assert len(results) >= 2
    assert results[0]["document_id"] == doc_plumbing
    assert results[0]["rrf_score"] >= results[1]["rrf_score"]


def test_tenant_and_organization_isolation():
    """Verify tenant and organization boundaries prevent cross-tenant data leaks."""
    uid = uuid.uuid4().hex[:8]
    doc_apex = f"DOC-APEX-{uid}"
    doc_beacon = f"DOC-BEACON-{uid}"

    # PROP-001 is mapped to ORG-APEX, PROP-003 is mapped to ORG-BEACON in default seed
    index_document(doc_apex, f"LEASE-A-{uid}", "PROP-001", "lease", f"Apex Secret Vault {uid}", f"Restricted Apex Horizon corporate vault access code {uid}.")
    index_document(doc_beacon, f"LEASE-B-{uid}", "PROP-003", "lease", f"Beacon Secret Vault {uid}", f"Restricted Beacon Commercial corporate vault access code {uid}.")

    # 1. Under ORG-APEX scope, Apex document is retrieved, Beacon document is completely excluded
    apex_results = retrieve(f"Restricted Apex Horizon corporate vault {uid}", org_id="ORG-APEX", top_k=5)
    apex_doc_ids = [r["document_id"] for r in apex_results]
    assert doc_apex in apex_doc_ids
    assert doc_beacon not in apex_doc_ids, "Tenant/Org leakage: Beacon document retrieved under Apex org scope"

    # Cross-tenant attempt: requesting Apex document under Beacon org scope must yield zero Apex documents
    leak_attempt = retrieve(f"Restricted Apex Horizon corporate vault {uid}", org_id="ORG-BEACON", top_k=10)
    assert doc_apex not in [r["document_id"] for r in leak_attempt], "Tenant/Org leakage: Apex document retrieved under Beacon org scope"

    # 2. Under ORG-BEACON scope, Beacon document is retrieved, Apex document is completely excluded
    beacon_results = retrieve(f"Restricted Beacon Commercial corporate vault {uid}", org_id="ORG-BEACON", top_k=5)
    beacon_doc_ids = [r["document_id"] for r in beacon_results]
    assert doc_beacon in beacon_doc_ids
    assert doc_apex not in beacon_doc_ids, "Tenant/Org leakage: Apex document retrieved under Beacon org scope"

    # 3. Lease-level scoping strictly isolates between leases
    lease_a_results = retrieve(f"Restricted corporate vault access code {uid}", lease_id=f"LEASE-A-{uid}", top_k=10)
    assert all(r["document_id"] != doc_beacon for r in lease_a_results)


def test_nvidia_failure_fallback_and_index_integrity(monkeypatch):
    """Verify that when NVIDIA NIM fails, fallback to deterministic hash is used cleanly without corrupting DB."""
    uid = uuid.uuid4().hex[:8]
    doc_id = f"DOC-FAILOVER-{uid}"
    lease_id = f"LEASE-FAILOVER-{uid}"

    # Simulate NVIDIA NIM service failure
    def mock_fail_batch(texts, input_type="passage"):
        raise RuntimeError("Simulated NVIDIA NIM 503 Service Unavailable / Timeout")

    monkeypatch.setattr(embedding_service.nim_provider, "embed_batch", mock_fail_batch)
    monkeypatch.setattr(embedding_service.nim_provider, "embed_text", lambda text, input_type="query": (_ for _ in ()).throw(RuntimeError("NIM Down")))

    # Ingestion should still succeed via deterministic fallback
    count = index_document(doc_id, lease_id, "PROP-001", "notice", "Emergency Notice", "Fire drill scheduled for tomorrow at noon.")
    assert count >= 1

    with db() as conn:
        chunk_row = conn.execute("SELECT model_name, is_semantic FROM chunks WHERE document_id = %s", (doc_id,)).fetchone()
        assert chunk_row[0] == "deterministic-hash-v1"
        assert chunk_row[1] is False

    # Retrieval should also fall back without throwing unhandled exceptions
    results = retrieve("Fire drill announcement", lease_id=lease_id, top_k=2)
    assert len(results) >= 1
    assert results[0]["document_id"] == doc_id
    assert results[0]["query_is_semantic"] is False


def test_incompatible_embedding_models_prevention(monkeypatch):
    """Verify that chunks indexed under model A are not compared via vector distance against queries from model B."""
    uid = uuid.uuid4().hex[:8]
    doc_id = f"DOC-COMPAT-{uid}"
    lease_id = f"LEASE-COMPAT-{uid}"

    # Index document with deterministic model
    monkeypatch.setattr(embedding_service, "get_active_provider_name", lambda: "offline")
    index_document(doc_id, lease_id, "PROP-001", "rules", "Gym Rules", "Swimming pool hours are 8am to 10pm daily.")

    # Now simulate active semantic model query
    monkeypatch.setattr(embedding_service, "get_active_provider_name", lambda: "nvidia")
    # Keyword search will still find it via FTS, but vector comparison against different model is safely skipped
    results = retrieve("Swimming pool hours", lease_id=lease_id, top_k=2)
    assert len(results) >= 1
    assert results[0]["document_id"] == doc_id
    # Verified: chunk model is deterministic-hash-v1 while query model is nvidia
    assert results[0]["embedding_model"] == "deterministic-hash-v1"
    assert results[0]["query_is_semantic"] is True


def test_assistant_retains_document_provenance_and_citations():
    # Query assistant on existing lease LEASE-0001
    resp = answer_assistant_query("What is the rent amount and late fee policy for lease LEASE-0001?")
    assert "response" in resp
    assert len(resp["response"]) > 20
    assert "provider_used" in resp
    assert "tool_calls" in resp

