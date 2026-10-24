"""Hybrid Retrieval-Augmented Generation (RAG) Engine with Semantic Embeddings & RRF.

Pipeline:
1. Document chunking with clause boundary detection (CLAUSE_SPLIT)
2. Semantic vector embedding (UnifiedEmbeddingProvider via NVIDIA NIM Nemotron or deterministic fallback)
3. pgvector cosine similarity search (HNSW index)
4. PostgreSQL Full-Text Search (search_tsv GIN index)
5. Reciprocal Rank Fusion (RRF) reranking
6. Source citation provenance and tenant/lease/property access scoping
"""

import re
from typing import List, Dict, Any, Optional
import numpy as np
from .database import db
from .embeddings import embedding_service

CLAUSE_SPLIT = re.compile(r'(?m)(?=^\s*\d{1,2}\.\s+[A-Z])')


def chunk_document(body: str, max_chars: int = 1050) -> List[str]:
    """Split document into structured clause blocks with maximum character threshold."""
    blocks = [x.strip() for x in CLAUSE_SPLIT.split(body) if x.strip()]
    if len(blocks) == 1:
        blocks = [x.strip() for x in body.split('\n\n') if x.strip()]
    chunks = []
    for block in blocks:
        while len(block) > max_chars:
            at = block.rfind(' ', 0, max_chars)
            at = at if at > max_chars // 2 else max_chars
            chunks.append(block[:at].strip())
            block = block[at:].strip()
        if block:
            chunks.append(block)
    return chunks


def index_document(document_id: str, lease_id: str, property_id: str, kind: str, title: str, body: str) -> int:
    """Chunk, embed, and index document into PostgreSQL pgvector and FTS stores."""
    parts = chunk_document(body)
    if not parts:
        parts = [body]

    vecs, meta = embedding_service.embed_batch(parts, input_type="passage")
    model_name = meta.get("model", "deterministic-hash-v1")
    is_semantic = meta.get("is_semantic", False)

    with db() as conn:
        conn.execute(
            '''INSERT INTO documents(id, lease_id, property_id, kind, title, body)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT(id) DO UPDATE SET body=excluded.body, title=excluded.title,
                 lease_id=excluded.lease_id, property_id=excluded.property_id''',
            (document_id, lease_id, property_id, kind, title, body)
        )
        conn.execute('DELETE FROM chunks WHERE document_id=%s', (document_id,))
        for chunk, vec in zip(parts, vecs):
            conn.execute(
                '''INSERT INTO chunks(document_id, lease_id, property_id, heading, body, embedding, model_name, is_semantic)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (
                    document_id, lease_id, property_id, chunk[:75], chunk,
                    np.asarray(vec, dtype=np.float32), model_name, is_semantic
                )
            )
    return len(parts)


def retrieve(
    query: str,
    lease_id: Optional[str] = None,
    property_id: Optional[str] = None,
    org_id: Optional[str] = None,
    top_k: int = 6
) -> List[Dict[str, Any]]:
    """Execute hybrid semantic + lexical search with Reciprocal Rank Fusion (RRF).
    
    Guarantees:
    - Scoped strictly to lease_id, property_id, and/or org_id.
    - Prevents mixing incompatible vector spaces: vector search only compares embeddings
      within the same model space.
    - FTS keyword search runs across all matching chunks regardless of embedding state.
    """
    if not (lease_id or property_id or org_id):
        raise ValueError('Retrieval requires a lease_id or property_id scope')

    conditions = []
    scope_params = []
    if lease_id:
        conditions.append("lease_id = %s")
        scope_params.append(lease_id)
    if property_id:
        conditions.append("property_id = %s")
        scope_params.append(property_id)
    if org_id:
        conditions.append("property_id IN (SELECT property_id FROM properties WHERE org_id = %s)")
        scope_params.append(org_id)

    where_clause = " AND ".join(conditions)

    emb_vec, meta = embedding_service.embed_text(query, input_type="query")
    emb = np.asarray(emb_vec, dtype=np.float32)
    query_model = meta.get("model", "deterministic-hash-v1")

    # In pgvector, only compare vectors within the compatible embedding space.
    # If the model does not match indexed chunks, vector comparison is skipped
    # to prevent mixing incompatible vector spaces, falling back to lexical search.
    sem_where = f"{where_clause} AND model_name = %s"
    sem_params = scope_params + [query_model, emb]

    with db() as conn:
        semantic = conn.execute(
            f'''SELECT id, document_id, heading, body, model_name, is_semantic FROM chunks WHERE {sem_where}
                ORDER BY embedding <=> %s LIMIT 15''',
            sem_params
        ).fetchall()
        
        kw_where = where_clause
        kw_params = scope_params + [query, query]
        keyword = conn.execute(
            f'''SELECT id, document_id, heading, body, model_name, is_semantic FROM chunks WHERE {kw_where}
                AND search_tsv @@ plainto_tsquery('english', %s)
                ORDER BY ts_rank(search_tsv, plainto_tsquery('english', %s)) DESC LIMIT 15''',
            kw_params
        ).fetchall()

    ranks = {}
    records = {}
    for group in (semantic, keyword):
        for i, r in enumerate(group, 1):
            ranks[r[0]] = ranks.get(r[0], 0) + 1 / (60 + i)
            records[r[0]] = r

    return [
        {
            'chunk_id': k,
            'document_id': records[k][1],
            'heading': records[k][2],
            'text': records[k][3],
            'rrf_score': round(v, 6),
            'embedding_model': records[k][4],
            'is_semantic': records[k][5],
            'query_model': query_model,
            'query_is_semantic': meta.get('is_semantic', False)
        }
        for k, v in sorted(ranks.items(), key=lambda item: -item[1])[:top_k]
    ]


def reindex_all_documents(limit: Optional[int] = None, only_stale: bool = False) -> Dict[str, Any]:
    """Re-index documents in the database using the active embedding model.
    
    Safe, repeatable, and resumable:
    - If only_stale=True, only documents with missing, non-semantic, or mismatched model chunks are processed.
    - If limit is set, stale documents are prioritized first so incremental runs finish migrations.
    """
    health = embedding_service.health_check()
    active_prov = health.get("active_provider")
    active_is_semantic = health.get("is_semantic", False)
    active_model = health.get("nvidia_tier", {}).get("model") if active_prov == "nvidia" else "deterministic-hash-v1"

    if only_stale:
        sql = """SELECT d.id, d.lease_id, d.property_id, d.kind, d.title, d.body
                 FROM documents d
                 WHERE EXISTS (
                     SELECT 1 FROM chunks c
                     WHERE c.document_id = d.id
                     AND (c.model_name IS DISTINCT FROM %s OR c.is_semantic IS DISTINCT FROM %s)
                 ) OR NOT EXISTS (
                     SELECT 1 FROM chunks c WHERE c.document_id = d.id
                 )
                 ORDER BY d.id ASC"""
        params = [active_model, active_is_semantic]
    else:
        sql = """SELECT d.id, d.lease_id, d.property_id, d.kind, d.title, d.body
                 FROM documents d
                 ORDER BY (
                     EXISTS (
                         SELECT 1 FROM chunks c
                         WHERE c.document_id = d.id
                         AND (c.model_name IS DISTINCT FROM %s OR c.is_semantic IS DISTINCT FROM %s)
                     )
                 ) DESC, d.id ASC"""
        params = [active_model, active_is_semantic]

    if limit:
        sql += f" LIMIT {int(limit)}"

    with db() as conn:
        docs = conn.execute(sql, params).fetchall()

    reindexed_docs = 0
    total_chunks = 0
    for doc in docs:
        doc_id, lease_id, prop_id, kind, title, body = doc
        count = index_document(doc_id, lease_id, prop_id, kind, title, body)
        reindexed_docs += 1
        total_chunks += count

    # Count remaining stale documents after this batch
    with db() as conn:
        remaining_stale = conn.execute(
            """SELECT COUNT(DISTINCT d.id)
               FROM documents d
               LEFT JOIN chunks c ON d.id = c.document_id
               WHERE c.model_name IS DISTINCT FROM %s OR c.is_semantic IS DISTINCT FROM %s OR c.id IS NULL""",
            (active_model, active_is_semantic)
        ).fetchone()[0]

    return {
        "status": "reindexed",
        "documents_reindexed": reindexed_docs,
        "total_chunks_indexed": total_chunks,
        "active_model": active_model,
        "is_semantic": active_is_semantic,
        "remaining_stale_documents": remaining_stale,
        "reindex_complete": (remaining_stale == 0),
        "embedding_tier": health.get("nvidia_tier" if active_prov == "nvidia" else "offline_tier")
    }


def get_rag_status() -> Dict[str, Any]:
    """Retrieve RAG subsystem diagnostics, index counts, and active embedding provider status."""
    health = embedding_service.health_check()
    active_prov = health.get("active_provider")
    is_semantic = health.get("is_semantic", False)
    active_model = health.get("nvidia_tier", {}).get("model") if active_prov == "nvidia" else "deterministic-hash-v1"

    with db() as conn:
        total_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        semantic_chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE is_semantic = TRUE").fetchone()[0]
        offline_chunks = total_chunks - semantic_chunks
        models_used = conn.execute("SELECT DISTINCT model_name FROM chunks").fetchall()
        stale_docs = conn.execute(
            """SELECT COUNT(DISTINCT d.id)
               FROM documents d
               LEFT JOIN chunks c ON d.id = c.document_id
               WHERE c.model_name IS DISTINCT FROM %s OR c.is_semantic IS DISTINCT FROM %s OR c.id IS NULL""",
            (active_model, is_semantic)
        ).fetchone()[0]

    return {
        "embedding_health": health,
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "semantic_chunks": semantic_chunks,
        "offline_chunks": offline_chunks,
        "stale_documents_count": stale_docs,
        "models_in_index": [m[0] for m in models_used if m[0]],
        "reindex_recommended": bool(stale_docs > 0)
    }
