"""Meterless Hierarchical Memory Engine (H-MEM) for ENIGMA / EQUILIBRA.

Complies strictly with upstream Meterless H-MEM Specification (AGENTS.md):
- Hierarchical memory tiers: short_term, working, long_term
- Canonical MemoryRecord schema with mandatory source & provenance
- Exact hybrid retrieval formula:
    raw = 0.35*semantic + 0.20*keyword + 0.10*tag + 0.10*domain
        + 0.15*entity   + 0.05*layer   + 0.05*recency - 0.20*superseded
    score = clamp01(raw) * confidence
- Feedback adaptation deltas:
    helpful:     +0.05 confidence, +1 accessCount
    not_helpful: -0.03 confidence
    wrong:       -0.20 confidence, adds "review" tag
- Append-only trust ledger with 17 canonical action types
- Conflict detection with opposing-phrases/numeric divergence and loser-superseded resolution
- Sleep cycle consolidation, guardrail-protected archival, and cosine >= 0.82 synthesis
- Dreaming pattern synthesis with strict human-in-the-loop approval boundary
- Dual-mode storage: fast in-memory store for conformance & local runs + PostgreSQL persistence
"""

from __future__ import annotations
import math
import re
import copy
import json
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, Literal
import logging

logger = logging.getLogger("equilibra.hmem")

# --- Canonical Constants & Defaults (AGENTS.md sections 2, 6, 8, 9, 13) ---

MemoryType = Literal["personal", "factual", "preference", "general"]
MemoryLayer = Literal["short_term", "working", "long_term"]
ProvenanceOrigin = Literal[
    "chat_message", "user_correction", "file_save", "file_open", "file_edit",
    "model_response", "plan_completion", "document", "manual", "dream", "sleep_synthesis"
]

LedgerAction = Literal[
    "create", "read", "update", "delete", "feedback", "promote", "demote", "merge",
    "conflict_detected", "conflict_resolved",
    "sleep_consolidate", "sleep_archive", "sleep_synthesize",
    "dream_proposed", "dream_approved", "dream_rejected", "restore"
]

DreamProposalType = Literal["insight", "domain", "invariant"]
FeedbackKind = Literal["helpful", "not_helpful", "wrong"]

FEEDBACK_DELTAS: Dict[FeedbackKind, float] = {
    "helpful": 0.05,
    "not_helpful": -0.03,
    "wrong": -0.20
}

DEFAULTS = {
    "retrievalTopN": 5,
    "retrievalThreshold": 0.35,  # on the final score, after the confidence multiplier
    "consolidationDays": 7,
    "archiveMinDays": 30,
    "archiveMaxAccess": 2,
    "synthesisCosine": 0.82,
    "dreamClusterMinSize": 2,
    "dreamRelatedness": 0.35,
    "maxDreamProposalsPerType": 8,
    "conflictAutoResolveGate": 0.70,
    "entityCap": 10,
    "relatedCap": 5,
    "recencyDays": 14,
}

LAYER_WEIGHT: Dict[MemoryLayer, float] = {
    "long_term": 1.0,
    "working": 0.8,
    "short_term": 0.6
}

DAY_MS = 24 * 60 * 60 * 1000
DIM = 64
HUB_THRESHOLD = 3

TECH_TERMS = [
    "react", "python", "typescript", "javascript", "rust", "sqlite", "postgres", "indexeddb",
    "node", "docker", "graphql", "redis", "webrtc", "tauri", "electron", "llm", "embedding",
]

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "tech": ["code", "bug", "api", "database", "deploy", "framework", "library", "server"] + TECH_TERMS,
    "work": ["meeting", "deadline", "client", "project", "sprint", "review", "report"],
    "personal": ["family", "hobby", "prefer", "like", "dislike", "morning", "evening"],
}

OPPOSING_PAIRS: List[Tuple[re.Pattern, re.Pattern]] = [
    (re.compile(r'\balways\b', re.IGNORECASE), re.compile(r'\bnever\b', re.IGNORECASE)),
    (re.compile(r'\benable[ds]?\b', re.IGNORECASE), re.compile(r'\bdisable[ds]?\b', re.IGNORECASE)),
    (re.compile(r'\bprefer[s]?\b', re.IGNORECASE), re.compile(r'\bavoid[s]?|dislike[s]?\b', re.IGNORECASE)),
    (re.compile(r'\bon\b', re.IGNORECASE), re.compile(r'\boff\b', re.IGNORECASE)),
    (re.compile(r'\byes\b', re.IGNORECASE), re.compile(r'\bno\b', re.IGNORECASE)),
]


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# --- Deterministic FNV-1a Hash & 64-Dim Embedder (reference/src/embeddings.ts) ---

def tokenize(text: str) -> List[str]:
    """Tokenize string into lowercase alphanumeric tokens of length > 1."""
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', str(text).lower())
    return [t for t in cleaned.split() if len(t) > 1]


def fnv1a(s: str) -> int:
    """32-bit FNV-1a hash matching standard JavaScript reference implementation."""
    h = 0x811c9dc5
    for ch in s:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return h


def embed(text: str) -> List[float]:
    """Deterministic 64-dimensional mock embedding vector (unit L2-normalized)."""
    vec = [0.0] * DIM
    for token in tokenize(text):
        h = fnv1a(token)
        idx = h % DIM
        sign = 1.0 if ((h >> 8) % 2 == 0) else -1.0
        mag = 1.0 + float((h >> 16) % 8) / 8.0
        vec[idx] += sign * mag
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity of unit-length vectors (dot product)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def jaccard(a: Union[List[str], Set[str]], b: Union[List[str], Set[str]]) -> float:
    """Jaccard set similarity overlap."""
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa.intersection(sb))
    union = len(sa.union(sb))
    return float(inter) / float(union) if union > 0 else 0.0


# --- Data Models ---

class Provenance:
    """Document and interaction provenance tracking authoritative citations."""

    def __init__(
        self,
        origin: ProvenanceOrigin = "manual",
        learned_at: Optional[int] = None,
        learnedAt: Optional[int] = None,
        label: str = "",
        refs: Optional[List[str]] = None,
        source_id: Optional[str] = None,
        sourceId: Optional[str] = None,
        document_id: Optional[str] = None,
        documentId: Optional[str] = None,
        page_number: Optional[int] = None,
        pageNumber: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ):
        self.origin = origin
        self.learnedAt = learned_at or learnedAt or int(time.time() * 1000)
        self.label = label
        self.refs = refs or []
        self.sourceId = source_id or sourceId or document_id or documentId
        self.documentId = document_id or documentId or self.sourceId
        self.pageNumber = page_number if page_number is not None else pageNumber
        self.metadata = metadata or {}
        for k, v in kwargs.items():
            self.metadata[k] = v

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.metadata.get(key, default)

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        return self.metadata[item]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origin": self.origin,
            "learnedAt": self.learnedAt,
            "label": self.label,
            "refs": self.refs,
            "sourceId": self.sourceId,
            "documentId": self.documentId,
            "pageNumber": self.pageNumber,
            "metadata": self.metadata
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Provenance:
        return cls(
            origin=d.get("origin", "manual"),
            learned_at=d.get("learnedAt") or d.get("learned_at"),
            label=d.get("label", ""),
            refs=d.get("refs", []),
            source_id=d.get("sourceId") or d.get("source_id"),
            document_id=d.get("documentId") or d.get("document_id"),
            page_number=d.get("pageNumber") if d.get("pageNumber") is not None else d.get("page_number"),
            metadata=d.get("metadata", {})
        )


class MemoryRecord:
    def __init__(
        self,
        id: str,
        content: str,
        type: MemoryType = "general",
        layer: MemoryLayer = "working",
        timestamp: Optional[int] = None,
        last_accessed: Optional[int] = None,
        access_count: int = 0,
        tags: Optional[List[str]] = None,
        embedding: Optional[List[float]] = None,
        confidence: float = 0.7,
        source: str = "",
        provenance: Optional[Provenance] = None,
        chat_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        goal_run_id: Optional[str] = None,
        property_id: Optional[str] = None,
        lease_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        domain: str = "general",
        namespace: str = "general/notes",
        entities: Optional[List[str]] = None,
        related_to: Optional[List[str]] = None,
        supersedes: Optional[str] = None,
        superseded_by: Optional[str] = None,
        derived_from: Optional[List[str]] = None,
        score: Optional[float] = None
    ):
        self.id = id
        self.content = content
        self.type: MemoryType = type
        self.layer: MemoryLayer = layer
        now_ms = int(time.time() * 1000)
        self.timestamp = timestamp if timestamp is not None else now_ms
        self.lastAccessed = last_accessed if last_accessed is not None else now_ms
        self.accessCount = access_count
        self.tags = list(tags) if tags else []
        self.embedding = list(embedding) if embedding else embed(content)
        self.confidence = clamp01(confidence)
        self.source = source
        self.provenance = provenance or Provenance(origin="manual", learned_at=self.timestamp, label=source)
        self.chatId = chat_id
        self.missionId = mission_id
        self.goalRunId = goal_run_id
        self.propertyId = property_id
        self.leaseId = lease_id
        self.tenantId = tenant_id
        self.domain = domain
        self.namespace = namespace
        self.entities = list(entities[:DEFAULTS["entityCap"]]) if entities else []
        self.relatedTo = list(related_to[:DEFAULTS["relatedCap"]]) if related_to else []
        self.supersedes = supersedes
        self.supersededBy = superseded_by
        self.derivedFrom = list(derived_from) if derived_from else None
        self.score = score

    @property
    def text(self) -> str:
        return self.content

    def to_dict(self, include_embedding: bool = True) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "content": self.content,
            "type": self.type,
            "layer": self.layer,
            "timestamp": self.timestamp,
            "lastAccessed": self.lastAccessed,
            "accessCount": self.accessCount,
            "tags": self.tags,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "provenance": self.provenance.to_dict(),
            "chatId": self.chatId,
            "missionId": self.missionId,
            "goalRunId": self.goalRunId,
            "propertyId": self.propertyId,
            "leaseId": self.leaseId,
            "tenantId": self.tenantId,
            "domain": self.domain,
            "namespace": self.namespace,
            "entities": self.entities,
            "relatedTo": self.relatedTo,
            "supersedes": self.supersedes,
            "supersededBy": self.supersededBy,
            "derivedFrom": self.derivedFrom,
            "score": self.score
        }
        if include_embedding:
            d["embedding"] = self.embedding
        return d

    def snapshot(self) -> Dict[str, Any]:
        """Produce a clean state snapshot excluding heavy embeddings for the audit ledger."""
        return self.to_dict(include_embedding=False)

    @property
    def property_id(self) -> Optional[str]:
        return self.propertyId

    @property
    def lease_id(self) -> Optional[str]:
        return self.leaseId

    @property
    def tenant_id(self) -> Optional[str]:
        return self.tenantId

    @property
    def chat_id(self) -> Optional[str]:
        return self.chatId

    @property
    def mission_id(self) -> Optional[str]:
        return self.missionId

    @property
    def goal_run_id(self) -> Optional[str]:
        return self.goalRunId

    @property
    def last_accessed(self) -> int:
        return self.lastAccessed

    @property
    def access_count(self) -> int:
        return self.accessCount

    @property
    def superseded_by(self) -> Optional[str]:
        return self.supersededBy

    @property
    def derived_from(self) -> Optional[List[str]]:
        return self.derivedFrom

    @property
    def related_to(self) -> List[str]:
        return self.relatedTo


class LedgerEntry:
    def __init__(
        self,
        memory_id: str,
        action: LedgerAction,
        actor: str,
        timestamp: int,
        previous_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.memoryId = memory_id
        self.action = action
        self.actor = actor
        self.timestamp = timestamp
        self.previousState = previous_state
        self.newState = new_state
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memoryId": self.memoryId,
            "action": self.action,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "previousState": self.previousState,
            "newState": self.newState,
            "details": self.details
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()


class DreamProposal:
    def __init__(
        self,
        id: str,
        type: DreamProposalType,
        content: str,
        derived_from: List[str],
        suggested_domain: Optional[str] = None,
        status: Literal["proposed", "approved", "rejected"] = "proposed"
    ):
        self.id = id
        self.type = type
        self.content = content
        self.derivedFrom = derived_from
        self.suggestedDomain = suggested_domain
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "derivedFrom": self.derivedFrom,
            "suggestedDomain": self.suggestedDomain,
            "status": self.status
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()


class SleepPreview:
    def __init__(self, to_consolidate: List[str], to_archive: List[str], to_synthesize: List[List[str]]):
        self.toConsolidate = to_consolidate
        self.toArchive = to_archive
        self.toSynthesize = to_synthesize

    def to_dict(self) -> Dict[str, Any]:
        return {
            "toConsolidate": self.toConsolidate,
            "toArchive": self.toArchive,
            "toSynthesize": self.toSynthesize
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()


class SleepReport:
    def __init__(
        self,
        backup_id: str,
        consolidated: Any = None,
        archived: Any = None,
        synthesized: Any = None,
        log: Optional[List[str]] = None,
        action_log: Optional[List[str]] = None,
        **kwargs: Any
    ):
        self.backupId = backup_id
        self.consolidated = consolidated
        self.archived = archived
        self.synthesized = synthesized
        self.log = log or action_log or []
        self.actionLog = self.log

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backupId": self.backupId,
            "consolidated": self.consolidated,
            "archived": self.archived,
            "synthesized": self.synthesized,
            "log": self.log,
            "actionLog": self.actionLog
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()


class ConflictRecord:
    def __init__(
        self,
        id: str,
        memory_a: str,
        memory_b: str,
        reason: str,
        confidence: float,
        resolved: bool = False,
        resolution: Optional[str] = None
    ):
        self.id = id
        self.memoryA = memory_a
        self.memoryB = memory_b
        self.reason = reason
        self.confidence = confidence
        self.resolved = resolved
        self.resolution = resolution

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "memoryA": self.memoryA,
            "memoryB": self.memoryB,
            "reason": self.reason,
            "confidence": self.confidence,
            "resolved": self.resolved,
            "resolution": self.resolution
        }

    def snapshot(self) -> Dict[str, Any]:
        return self.to_dict()


class RetrievedMemory:
    def __init__(self, memory: MemoryRecord, relevance: float, trace: Optional[Dict[str, Any]] = None):
        self.memory = memory
        self.relevance = relevance
        self.score = relevance
        self.trace = trace or {}

    def snapshot(self) -> Dict[str, Any]:
        return {
            "memory": self.memory.snapshot(),
            "relevance": round(self.relevance, 4),
            "score": round(self.score, 4),
            "trace": self.trace
        }

    def to_dict(self) -> Dict[str, Any]:
        return self.snapshot()

    def model_dump(self) -> Dict[str, Any]:
        return self.snapshot()


class QueryResult:
    def __init__(
        self,
        memories: List[RetrievedMemory],
        context: str,
        trace: Dict[str, Any]
    ):
        self.memories = memories
        self.context = context
        self.context_block = context
        self.trace = trace

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memories": [m.to_dict() for m in self.memories],
            "context": self.context,
            "context_block": self.context,
            "trace": self.trace
        }


# --- Trust Ledger Service (AGENTS.md section 9.1) ---

class TrustLedgerService:
    """Append-only trust ledger tracking all 17 canonical mutation actions."""

    def __init__(self, clock: Callable[[], int], pg_conn_fn: Optional[Callable] = None):
        self._clock = clock
        self._entries: List[LedgerEntry] = []
        self._pg_conn_fn = pg_conn_fn

    def log(
        self,
        memory_id: str,
        action: LedgerAction,
        actor: str,
        previous_state: Optional[Dict[str, Any]] = None,
        new_state: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> LedgerEntry:
        ts = self._clock()
        entry = LedgerEntry(
            memory_id=memory_id,
            action=action,
            actor=actor,
            timestamp=ts,
            previous_state=previous_state,
            new_state=new_state,
            details=details
        )
        self._entries.append(entry)

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        """INSERT INTO hmem_audit_ledger
                           (memory_id, action, actor, timestamp, previous_state, new_state, details)
                           VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)""",
                        (
                            memory_id, action, actor, ts,
                            json.dumps(previous_state or {}),
                            json.dumps(new_state or {}),
                            json.dumps(details or {})
                        )
                    )
            except Exception:
                pass  # Fallback to in-memory audit log
        return entry

    def history(self, memory_id: str) -> List[LedgerEntry]:
        return [e for e in self._entries if e.memoryId == memory_id]

    def filter(self, memory_id: Optional[str] = None, action: Optional[str] = None) -> List[LedgerEntry]:
        res = self._entries
        if memory_id:
            res = [e for e in res if e.memoryId == memory_id]
        if action:
            res = [e for e in res if e.action == action]
        return res

    def all(self) -> List[LedgerEntry]:
        return list(self._entries)

    def stats(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for e in self._entries:
            out[e.action] = out.get(e.action, 0) + 1
        return out


# --- Memory Store Service (AGENTS.md sections 2, 3, 5) ---

class MemoryStoreService:
    """Tiered memory store handling enrichment, entities, domains, and persistence."""

    def __init__(
        self,
        clock: Callable[[], int],
        ledger: TrustLedgerService,
        actor: str = "system",
        pg_conn_fn: Optional[Callable] = None
    ):
        self._clock = clock
        self.ledger = ledger
        self.actor = actor
        self._records: Dict[str, MemoryRecord] = {}
        self._seq = 0
        self._pg_conn_fn = pg_conn_fn

    def add(
        self,
        content: str,
        source: str,
        type: MemoryType = "general",
        layer: MemoryLayer = "working",
        confidence: float = 0.7,
        tags: Optional[List[str]] = None,
        provenance: Optional[Provenance] = None,
        chat_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        goal_run_id: Optional[str] = None,
        property_id: Optional[str] = None,
        lease_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        supersedes: Optional[str] = None,
        derived_from: Optional[List[str]] = None,
        **kwargs: Any
    ) -> MemoryRecord:
        # Mandatory source validation (conformance check rv-001, rv-002)
        if not source or not str(source).strip():
            raise ValueError("H-MEM: a memory record with no source must be rejected by construction (AGENTS.md section 2)")

        # Support dictionary input compatibility
        if isinstance(content, dict):
            kwargs = content
            content = kwargs.get("content", "")
            source = kwargs.get("source", source)

        now = self._clock()
        self._seq += 1
        mem_id = f"mem-{self._seq}"
        in_tags = list(tags) if tags else []
        domain = self.classify_domain(content, in_tags, type)
        namespace = self.generate_namespace(domain, type)

        prov = provenance or Provenance(origin="manual", learned_at=now, label=source)

        record = MemoryRecord(
            id=mem_id,
            content=content,
            type=type,
            layer=layer,
            timestamp=now,
            last_accessed=now,
            access_count=0,
            tags=in_tags,
            embedding=embed(content),
            confidence=clamp01(confidence),
            source=source,
            provenance=prov,
            chat_id=chat_id,
            mission_id=mission_id,
            goal_run_id=goal_run_id,
            property_id=property_id,
            lease_id=lease_id,
            tenant_id=tenant_id,
            domain=domain,
            namespace=namespace,
            entities=self.extract_entities(content),
            related_to=[],
            supersedes=supersedes,
            derived_from=derived_from
        )

        self._discover_relationships(record)
        self._records[mem_id] = record

        # Append to audit ledger
        self.ledger.log(mem_id, "create", self.actor, new_state=record.snapshot())

        # Persist to PostgreSQL if configured
        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        """INSERT INTO hmem_memories
                           (id, content, type, layer, timestamp, last_accessed, access_count, tags,
                            embedding, confidence, source, provenance, chat_id, mission_id, goal_run_id,
                            property_id, lease_id, tenant_id, domain, namespace, entities, related_to,
                            supersedes, superseded_by, derived_from, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                                   %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                                   %s, %s, %s::jsonb, now(), now())
                           ON CONFLICT (id) DO UPDATE SET
                           content=excluded.content, confidence=excluded.confidence,
                           last_accessed=excluded.last_accessed, access_count=excluded.access_count,
                           tags=excluded.tags, layer=excluded.layer, superseded_by=excluded.superseded_by,
                           updated_at=now()""",
                        (
                            record.id, record.content, record.type, record.layer, record.timestamp,
                            record.lastAccessed, record.accessCount, json.dumps(record.tags),
                            json.dumps(record.embedding), record.confidence, record.source,
                            json.dumps(record.provenance.to_dict()), record.chatId, record.missionId,
                            record.goalRunId, record.propertyId, record.leaseId, record.tenantId,
                            record.domain, record.namespace, json.dumps(record.entities),
                            json.dumps(record.relatedTo), record.supersedes, record.supersededBy,
                            json.dumps(record.derivedFrom or [])
                        )
                    )
            except Exception:
                pass

        return record

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        return self._records.get(memory_id)

    def all(self) -> List[MemoryRecord]:
        return list(self._records.values())

    def update(self, memory_id: str, patch: Dict[str, Any]) -> MemoryRecord:
        rec = self._must_get(memory_id)
        prev = rec.snapshot()
        for k, v in patch.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        self.ledger.log(memory_id, "update", self.actor, previous_state=prev, new_state=rec.snapshot())

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        """UPDATE hmem_memories SET
                           content = %s, layer = %s, confidence = %s, tags = %s::jsonb,
                           domain = %s, supersedes = %s, superseded_by = %s, updated_at = now()
                           WHERE id = %s""",
                        (
                            rec.content, rec.layer, rec.confidence, json.dumps(rec.tags),
                            rec.domain, rec.supersedes, rec.supersededBy, memory_id
                        )
                    )
            except Exception:
                pass

        return rec

    def delete(self, memory_id: str, reason: str = "deleted") -> None:
        rec = self._must_get(memory_id)
        prev = rec.snapshot()
        del self._records[memory_id]
        self.ledger.log(memory_id, "delete", self.actor, previous_state=prev, details={"reason": reason})

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute("DELETE FROM hmem_memories WHERE id = %s", (memory_id,))
            except Exception:
                pass

    def touch(self, memory_id: str) -> None:
        rec = self._must_get(memory_id)
        rec.lastAccessed = self._clock()
        rec.accessCount += 1

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        "UPDATE hmem_memories SET last_accessed = %s, access_count = %s WHERE id = %s",
                        (rec.lastAccessed, rec.accessCount, memory_id)
                    )
            except Exception:
                pass

    def promote(self, memory_id: str, layer: MemoryLayer) -> None:
        rec = self._must_get(memory_id)
        prev = rec.snapshot()
        rec.layer = layer
        self.ledger.log(memory_id, "promote", self.actor, previous_state=prev, new_state=rec.snapshot())

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        "UPDATE hmem_memories SET layer = %s, updated_at = now() WHERE id = %s",
                        (layer, memory_id)
                    )
            except Exception:
                pass

    def snapshot_all(self) -> Dict[str, Any]:
        return {
            "seq": self._seq,
            "records": [copy.deepcopy(r) for r in self._records.values()]
        }

    def restore_all(self, records: List[MemoryRecord], seq: int) -> None:
        self._records = {r.id: copy.deepcopy(r) for r in records}
        self._seq = seq

    def _must_get(self, memory_id: str) -> MemoryRecord:
        rec = self._records.get(memory_id)
        if not rec:
            raise KeyError(f"H-MEM: unknown memory id {memory_id}")
        return rec

    def classify_domain(self, content: str, tags: List[str], type: MemoryType) -> str:
        for t in tags:
            if t.startswith("project:"):
                return t[len("project:"):]
            if t.startswith("tech:"):
                return "tech"
        tokens = set(tokenize(content))
        best = "general"
        best_score = 0
        for domain, kws in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in tokens)
            if domain == "personal" and (type == "personal" or type == "preference"):
                score += 1
            if score > best_score:
                best = domain
                best_score = score
        return best if best_score > 0 else "general"

    def generate_namespace(self, domain: str, type: MemoryType) -> str:
        bucket = "profile" if type in ("preference", "personal") else "facts" if type == "factual" else "notes"
        return f"{domain}/{bucket}"

    def extract_entities(self, content: str) -> List[str]:
        entities: Set[str] = set()
        for t in tokenize(content):
            if t in TECH_TERMS:
                entities.add(t)
        for m in re.finditer(r'\b([A-Z][a-zA-Z]{2,})\b', content):
            norm = m.group(1).lower()
            if norm not in ("the", "this", "that", "with"):
                entities.add(norm)
        return sorted(list(entities))[:DEFAULTS["entityCap"]]

    def _discover_relationships(self, record: MemoryRecord) -> None:
        CORRECTION = re.compile(r'\b(actually|instead|no longer|not anymore|changed to|correction)\b', re.IGNORECASE)
        for other in self._records.values():
            if len(record.relatedTo) >= DEFAULTS["relatedCap"]:
                break
            shared_entities = [e for e in other.entities if e in record.entities]
            sim = cosine(record.embedding, other.embedding)
            if not record.supersedes and sim > 0.85 and CORRECTION.search(record.content):
                record.supersedes = other.id
                continue
            if len(shared_entities) >= 1 and other.domain == record.domain:
                record.relatedTo.append(other.id)
                if len(other.relatedTo) < DEFAULTS["relatedCap"] and record.id not in other.relatedTo:
                    other.relatedTo.append(record.id)  # Bidirectional


# --- Memory Retrieval Service (AGENTS.md section 6) ---

class MemoryRetrievalService:
    """Exact hybrid scoring algorithm and context reinjection."""

    def __init__(
        self,
        store: MemoryStoreService,
        ledger: TrustLedgerService,
        clock: Callable[[], int],
        actor: str = "system"
    ):
        self.store = store
        self.ledger = ledger
        self._clock = clock
        self.actor = actor

    def score_one(self, memory: MemoryRecord, query: str) -> float:
        q_embed = embed(query)
        q_tokens = tokenize(query)[:8]
        q_entities = self.store.extract_entities(query)
        q_domain = self.store.classify_domain(query, [], "general")
        score, _ = self._score(memory, q_embed, q_tokens, q_entities, q_domain)
        return score

    def _score(
        self,
        m: MemoryRecord,
        query_embed: List[float],
        query_tokens: List[str],
        query_entities: List[str],
        query_domain: str
    ) -> Tuple[float, Dict[str, float]]:
        semantic = clamp01(cosine(query_embed, m.embedding))
        keyword = jaccard(query_tokens, tokenize(m.content))
        tag = jaccard(query_tokens, [t.lower() for t in m.tags])
        domain = 1.0 if m.domain == query_domain else 0.0
        entity = jaccard(query_entities, m.entities)
        layer = LAYER_WEIGHT.get(m.layer, 0.8)
        age_days = (self._clock() - m.lastAccessed) / DAY_MS
        recency = math.exp(-age_days / DEFAULTS["recencyDays"])
        superseded = 1.0 if m.supersededBy else 0.0

        raw = (
            0.35 * semantic +
            0.20 * keyword +
            0.10 * tag +
            0.10 * domain +
            0.15 * entity +
            0.05 * layer +
            0.05 * recency -
            0.20 * superseded
        )
        final_score = clamp01(raw) * m.confidence
        components = {
            "semantic": round(semantic, 4),
            "keyword": round(keyword, 4),
            "tag": round(tag, 4),
            "domain": round(domain, 4),
            "entity": round(entity, 4),
            "layer": round(layer, 4),
            "recency": round(recency, 4),
            "supersededPenalty": round(0.20 * superseded, 4),
            "raw": round(raw, 4),
            "final": round(final_score, 4)
        }
        return final_score, components

    def query(
        self,
        query_str: Optional[str] = None,
        top_n: Optional[int] = None,
        threshold: Optional[float] = None,
        chat_id: Optional[str] = None,
        property_id: Optional[str] = None,
        lease_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        text: Optional[str] = None,
        query: Optional[str] = None,
        top_k: Optional[int] = None,
        topN: Optional[int] = None,
        min_score: Optional[float] = None,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        budget_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> QueryResult:
        q_str = query_str or text or query or ""
        thresh = threshold if threshold is not None else (min_score if min_score is not None else DEFAULTS["retrievalThreshold"])
        limit = top_k if top_k is not None else (top_n if top_n is not None else (topN if topN is not None else DEFAULTS["retrievalTopN"]))

        q_embed = embed(q_str)
        q_tokens = tokenize(q_str)[:8]
        q_entities = entities or self.store.extract_entities(q_str)
        q_domain = domain or self.store.classify_domain(q_str, tags or [], "general")

        scored: List[RetrievedMemory] = []
        for m in self.store.all():
            # Scoping filters
            if chat_id and m.chatId and m.chatId != chat_id:
                continue
            if property_id and m.propertyId and m.propertyId != property_id:
                continue
            if lease_id and m.leaseId and m.leaseId != lease_id:
                continue
            if tenant_id and m.tenantId and m.tenantId != tenant_id:
                continue

            score, comps = self._score(m, q_embed, q_tokens, q_entities, q_domain)
            if score >= thresh:
                scored.append(RetrievedMemory(memory=m, relevance=score, trace={"components": comps}))

        # Sort desc by relevance, tie-break by memory ID asc
        scored.sort(key=lambda rm: (-rm.relevance, rm.memory.id))
        top = scored[:limit]

        # Audit and touch retrieved records
        for item in top:
            self.store.touch(item.memory.id)
            self.ledger.log(item.memory.id, "read", self.actor, details={"query": q_str})

        strategy: Literal["minimal", "personal", "comprehensive"] = (
            "minimal" if len(top) <= 1 else
            "personal" if any(t.memory.type in ("personal", "preference") for t in top) else
            "comprehensive"
        )

        context_block = self.format_reinjection(top)
        scores_map = {t.memory.id: round(t.relevance, 4) for t in top}
        top_components = {t.memory.id: t.trace.get("components", {}) for t in top}

        trace = {
            "retrievalReason": f'hybrid ranking for "{q_str}" (domain: {q_domain})',
            "strategy": strategy,
            "scores": scores_map,
            "components": top_components.get(top[0].memory.id, {}) if top else {}
        }

        return QueryResult(memories=top, context=context_block, trace=trace)

    def feedback(self, memory_id: str, kind: FeedbackKind) -> None:
        rec = self.store.get(memory_id)
        if not rec:
            raise KeyError(f"H-MEM: unknown memory id {memory_id}")
        prev = rec.snapshot()

        delta = FEEDBACK_DELTAS.get(kind, 0.0)
        if kind == "helpful":
            rec.accessCount += 1
        rec.confidence = clamp01(rec.confidence + delta)

        if kind == "wrong" and "review" not in rec.tags:
            rec.tags.append("review")

        self.ledger.log(
            memory_id,
            "feedback",
            self.actor,
            previous_state=prev,
            new_state=rec.snapshot(),
            details={"kind": kind, "delta": delta}
        )

        if self.store._pg_conn_fn:
            try:
                with self.store._pg_conn_fn() as conn:
                    conn.execute(
                        """UPDATE hmem_memories SET
                           confidence = %s, access_count = %s, tags = %s::jsonb, updated_at = now()
                           WHERE id = %s""",
                        (rec.confidence, rec.accessCount, json.dumps(rec.tags), memory_id)
                    )
            except Exception:
                pass

    def format_reinjection(self, items: List[RetrievedMemory]) -> str:
        if not items:
            return ""
        by_domain: Dict[str, List[RetrievedMemory]] = {}
        for it in items:
            by_domain.setdefault(it.memory.domain, []).append(it)

        lines = ["[MEMORY CONTEXT]"]
        for domain in sorted(by_domain.keys()):
            lines.append(f"## {domain}")
            for it in by_domain[domain]:
                m = it.memory
                marker = "LT" if m.layer == "long_term" else "WK" if m.layer == "working" else "ST"
                ents = f" (entities: {', '.join(m.entities)})" if m.entities else ""
                lines.append(f"- [{marker}] {m.content}{ents} <{m.id}>")
        lines.append("[/MEMORY CONTEXT]")
        return "\n".join(lines)


# --- Conflict Detection & Auto-Resolution Service (AGENTS.md section 10) ---

class ConflictDetectionService:
    """Detects opposing statements or numerical conflicts without destructive deletion."""

    def __init__(
        self,
        store: MemoryStoreService,
        ledger: TrustLedgerService,
        clock: Callable[[], int],
        actor: str = "system"
    ):
        self.store = store
        self.ledger = ledger
        self._clock = clock
        self.actor = actor
        self._conflicts: List[ConflictRecord] = []
        self._seq = 0

    def scan(self) -> List[ConflictRecord]:
        found: List[ConflictRecord] = []
        all_records = self.store.all()
        for i in range(len(all_records)):
            for j in range(i + 1, len(all_records)):
                conflict = self.check(all_records[i], all_records[j])
                if conflict:
                    found.append(conflict)
                    self._conflicts.append(conflict)
                    self.ledger.log(
                        conflict.memoryA,
                        "conflict_detected",
                        self.actor,
                        details={"with": conflict.memoryB, "reason": conflict.reason, "confidence": conflict.confidence}
                    )
        return found

    def check(self, a: MemoryRecord, b: MemoryRecord) -> Optional[ConflictRecord]:
        # Supersedes relation suppresses conflict (intentional replacement)
        if a.supersedes == b.id or b.supersedes == a.id or a.supersededBy == b.id or b.supersededBy == a.id:
            return None

        sim = cosine(a.embedding, b.embedding)
        reason = ""
        conf = 0.0

        for p, q in OPPOSING_PAIRS:
            if (p.search(a.content) and q.search(b.content)) or (q.search(a.content) and p.search(b.content)):
                if sim > 0.5:
                    reason = "opposing phrase pair on similar content"
                    conf = 0.5 + 0.3 * sim
                    break

        if not reason and sim > 0.8:
            nums_a = re.findall(r'\d+(?:\.\d+)?', a.content)
            nums_b = re.findall(r'\d+(?:\.\d+)?', b.content)
            if nums_a and nums_b and nums_a != nums_b:
                reason = "high-similarity conflicting numeric values"
                conf = 0.55 + 0.25 * sim

        if not reason:
            return None

        # Confidence modifiers
        shared_entities = [e for e in a.entities if e in b.entities]
        if shared_entities:
            conf += 0.10
        if a.domain == b.domain:
            conf += 0.05
        if b.id in a.relatedTo:
            conf -= 0.10

        self._seq += 1
        return ConflictRecord(
            id=f"conflict-{self._seq}",
            memory_a=a.id,
            memory_b=b.id,
            reason=reason,
            confidence=clamp01(conf),
            resolved=False
        )

    def auto_resolve(self, conflict: ConflictRecord) -> Literal["resolved", "queued"]:
        a = self.store.get(conflict.memoryA)
        b = self.store.get(conflict.memoryB)
        if not a or not b:
            return "queued"

        now = max(1, self._clock())
        def score_of(m: MemoryRecord) -> float:
            return (
                0.30 * (m.lastAccessed / now) +
                0.20 * min(1.0, m.accessCount / 10.0) +
                0.25 * m.confidence +
                0.10 * min(1.0, len(m.content) / 200.0) +
                0.15 * (1.0 if m.provenance.origin == "user_correction" else 0.5)
            )

        sa = score_of(a)
        sb = score_of(b)
        denom = max(sa, sb) or 1.0
        margin = abs(sa - sb) / denom
        decision_confidence = clamp01(conflict.confidence * 0.6 + margin * 0.8)

        if decision_confidence < DEFAULTS["conflictAutoResolveGate"]:
            return "queued"

        winner = a if sa >= sb else b
        loser = b if sa >= sb else a
        prev_loser = loser.snapshot()

        loser.supersededBy = winner.id  # Kept and penalized, NEVER deleted
        conflict.resolved = True
        conflict.resolution = "keep_a" if winner.id == conflict.memoryA else "keep_b"

        self.ledger.log(
            loser.id,
            "conflict_resolved",
            self.actor,
            previous_state=prev_loser,
            new_state=loser.snapshot(),
            details={"conflictId": conflict.id, "winner": winner.id, "decisionConfidence": round(decision_confidence, 3)}
        )
        return "resolved"

    autoResolve = auto_resolve

    def queue(self) -> List[ConflictRecord]:
        return [c for c in self._conflicts if not c.resolved]


# --- Sleep Cycle Service (AGENTS.md section 8) ---

class SleepCycleService:
    """Preview-first consolidation, archival, and synthesis with safety snapshots."""

    def __init__(
        self,
        store: MemoryStoreService,
        ledger: TrustLedgerService,
        clock: Callable[[], int],
        actor: str = "system"
    ):
        self.store = store
        self.ledger = ledger
        self._clock = clock
        self.actor = actor
        self._backups: Dict[str, Dict[str, Any]] = {}
        self._backup_seq = 0

    def preview(self) -> SleepPreview:
        now = self._clock()
        all_records = self.store.all()

        referenced: Set[str] = set()
        for m in all_records:
            for r in m.relatedTo:
                referenced.add(r)
            if m.supersedes:
                referenced.add(m.supersedes)
            for d in (m.derivedFrom or []):
                referenced.add(d)

        to_consolidate = [
            m.id for m in all_records
            if m.layer == "short_term" and (now - m.lastAccessed) >= DEFAULTS["consolidationDays"] * DAY_MS
        ]

        to_archive = []
        for m in all_records:
            old_enough = (now - m.timestamp) >= DEFAULTS["archiveMinDays"] * DAY_MS
            low_access = m.accessCount <= DEFAULTS["archiveMaxAccess"]
            unref = m.id not in referenced

            if not (old_enough and low_access and unref):
                continue

            # Strict guardrails: never archive superseding, derived, or hub records
            if m.supersedes:
                continue
            if m.derivedFrom and len(m.derivedFrom) > 0:
                continue
            if len(m.relatedTo) >= HUB_THRESHOLD:
                continue

            to_archive.append(m.id)

        to_synthesize: List[List[str]] = []
        used: Set[str] = set()
        for i in range(len(all_records)):
            if all_records[i].id in used:
                continue
            group = [all_records[i]]
            for j in range(i + 1, len(all_records)):
                if all_records[j].id in used:
                    continue
                if cosine(all_records[i].embedding, all_records[j].embedding) >= DEFAULTS["synthesisCosine"]:
                    group.append(all_records[j])
            if len(group) >= 2:
                for g in group:
                    used.add(g.id)
                to_synthesize.append([g.id for g in group])

        return SleepPreview(to_consolidate=to_consolidate, to_archive=to_archive, to_synthesize=to_synthesize)

    def execute(self, preview_plan: Optional[SleepPreview] = None) -> SleepReport:
        plan = preview_plan or self.preview()
        self._backup_seq += 1
        backup_id = f"backup-{self._backup_seq}"
        self._backups[backup_id] = self.store.snapshot_all()
        action_log: List[str] = [f"backup {backup_id} created"]

        for mem_id in plan.toConsolidate:
            m = self.store.get(mem_id)
            if not m:
                continue
            self.store.promote(mem_id, "long_term")
            self.ledger.log(mem_id, "sleep_consolidate", self.actor, details={"from": "short_term", "to": "long_term"})
            action_log.append(f"consolidated {mem_id}")

        for mem_id in plan.toArchive:
            m = self.store.get(mem_id)
            if not m:
                continue
            self.ledger.log(mem_id, "sleep_archive", self.actor, details={"age": self._clock() - m.timestamp, "accessCount": m.accessCount})
            self.store.delete(mem_id, reason="sleep archive")
            action_log.append(f"archived {mem_id}")

        synthesized = 0
        for group in plan.toSynthesize:
            members = [self.store.get(gid) for gid in group]
            valid_members = [m for m in members if m is not None]
            if len(valid_members) < 2:
                continue

            merged_content = f"Synthesis: {' | '.join(m.content for m in valid_members)}"
            merged_tags = sorted(list(set(t for m in valid_members for t in m.tags)))
            max_conf = max(m.confidence for m in valid_members)

            merged = self.store.add(
                content=merged_content,
                source="sleep:synthesis",
                type="factual",
                layer="long_term",
                tags=merged_tags,
                confidence=max_conf,
                provenance=Provenance(origin="sleep_synthesis", learned_at=self._clock(), label=f"synthesized from {len(valid_members)} memories"),
                derived_from=[m.id for m in valid_members]
            )
            self.ledger.log(merged.id, "sleep_synthesize", self.actor, details={"sources": group})
            for m in valid_members:
                self.store.delete(m.id, reason="merged by sleep synthesis")
            synthesized += 1
            action_log.append(f"synthesized {merged.id} from {', '.join(group)}")

        return SleepReport(
            backup_id=backup_id,
            consolidated=len(plan.toConsolidate),
            archived=len(plan.toArchive),
            synthesized=synthesized,
            action_log=action_log
        )

    def restore(self, backup_id: str) -> None:
        backup = self._backups.get(backup_id)
        if not backup:
            raise KeyError(f"H-MEM: unknown backup {backup_id}")
        self.store.restore_all(backup["records"], backup["seq"])
        self.ledger.log("*", "restore", self.actor, details={"backupId": backup_id})


# --- Dreaming System (AGENTS.md section 7) ---

class DreamingService:
    """Higher-order knowledge synthesis proposals with strict human approval gates."""

    def __init__(
        self,
        store: MemoryStoreService,
        ledger: TrustLedgerService,
        clock: Callable[[], int],
        actor: str = "system",
        pg_conn_fn: Optional[Callable] = None
    ):
        self.store = store
        self.ledger = ledger
        self._clock = clock
        self.actor = actor
        self._proposals: Dict[str, DreamProposal] = {}
        self._seq = 0
        self._pg_conn_fn = pg_conn_fn

    def _relatedness(self, a: MemoryRecord, b: MemoryRecord) -> float:
        return (
            0.50 * max(0.0, cosine(a.embedding, b.embedding)) +
            0.20 * jaccard(a.tags, b.tags) +
            0.10 * (1.0 if a.domain == b.domain else 0.0) +
            0.20 * jaccard(a.entities, b.entities)
        )

    def _cluster(self) -> List[List[MemoryRecord]]:
        all_records = self.store.all()
        used: Set[str] = set()
        clusters: List[List[MemoryRecord]] = []

        for seed in all_records:
            if seed.id in used:
                continue
            group = [seed]
            for other in all_records:
                if other.id == seed.id or other.id in used:
                    continue
                if self._relatedness(seed, other) >= DEFAULTS["dreamRelatedness"]:
                    group.append(other)
            if len(group) >= DEFAULTS["dreamClusterMinSize"]:
                for g in group:
                    used.add(g.id)
                clusters.append(group)
        return clusters

    def dream(self) -> List[DreamProposal]:
        created: List[DreamProposal] = []

        def propose(ptype: DreamProposalType, content: str, derived_from: List[str], suggested_domain: Optional[str] = None):
            self._seq += 1
            pid = f"dream-{self._seq}"
            proposal = DreamProposal(
                id=pid,
                type=ptype,
                content=content,
                derived_from=derived_from,
                suggested_domain=suggested_domain,
                status="proposed"
            )
            self._proposals[pid] = proposal
            created.append(proposal)
            self.ledger.log(pid, "dream_proposed", self.actor, details={"type": ptype, "derivedFrom": derived_from})

            if self._pg_conn_fn:
                try:
                    with self._pg_conn_fn() as conn:
                        conn.execute(
                            """INSERT INTO hmem_dream_proposals
                               (id, type, content, derived_from, suggested_domain, status, created_at, updated_at)
                               VALUES (%s, %s, %s, %s::jsonb, %s, %s, now(), now())
                               ON CONFLICT (id) DO UPDATE SET
                               status = excluded.status, updated_at = now()""",
                            (
                                pid, ptype, content, json.dumps(derived_from),
                                suggested_domain, "proposed"
                            )
                        )
                except Exception:
                    pass

        # 1. Insights from clusters
        insights = 0
        for cluster in self._cluster():
            if insights >= DEFAULTS["maxDreamProposalsPerType"]:
                break
            domains = "/".join(sorted(list(set(m.domain for m in cluster))))
            content = f"Across {len(cluster)} related memories ({domains}): {' + '.join(m.content for m in cluster)}"
            propose("insight", content, [m.id for m in cluster])
            insights += 1

        # 2. Domain suggestions for general memories
        domains_count = 0
        for m in self.store.all():
            if domains_count >= DEFAULTS["maxDreamProposalsPerType"]:
                break
            if m.domain != "general":
                continue
            suggested = self.store.classify_domain(m.content, m.tags, m.type)
            if suggested != "general":
                propose("domain", f'Reclassify "{m.content[:60]}" as {suggested}', [m.id], suggested_domain=suggested)
                domains_count += 1

        # 3. Invariants from preferences/corrections
        invariants = 0
        prefs = [m for m in self.store.all() if m.type in ("preference", "personal") or "event:user_correction" in m.tags]
        by_domain: Dict[str, List[MemoryRecord]] = {}
        for p in prefs:
            by_domain.setdefault(p.domain, []).append(p)

        for domain, group in by_domain.items():
            if invariants >= DEFAULTS["maxDreamProposalsPerType"]:
                break
            if len(group) < 2:
                continue
            content = f"Stable pattern in {domain}: {'; '.join(m.content for m in group)}"
            propose("invariant", content, [m.id for m in group])
            invariants += 1

        return created

    def pending(self) -> List[DreamProposal]:
        return [p for p in self._proposals.values() if p.status == "proposed"]

    def approve(self, proposal_id: str) -> Optional[MemoryRecord]:
        p = self._proposals.get(proposal_id)
        if not p or p.status != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        p.status = "approved"
        self.ledger.log(proposal_id, "dream_approved", self.actor, details={"type": p.type})

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        "UPDATE hmem_dream_proposals SET status = 'approved', updated_at = now() WHERE id = %s",
                        (proposal_id,)
                    )
            except Exception:
                pass

        if p.type == "domain":
            for mem_id in p.derivedFrom:
                m = self.store.get(mem_id)
                if m and p.suggestedDomain:
                    self.store.update(mem_id, {"domain": p.suggestedDomain})
            return None

        # Insight -> long-term factual; Invariant -> long-term preference
        return self.store.add(
            content=p.content,
            source="dreaming",
            type="factual" if p.type == "insight" else "preference",
            layer="long_term",
            tags=[f"dream:{p.type}"],
            confidence=0.75,
            provenance=Provenance(origin="dream", learned_at=self._clock(), label=f"approved {p.type} proposal"),
            derived_from=p.derivedFrom
        )

    def reject(self, proposal_id: str) -> None:
        p = self._proposals.get(proposal_id)
        if not p or p.status != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        p.status = "rejected"
        self.ledger.log(proposal_id, "dream_rejected", self.actor, details={"type": p.type})

        if self._pg_conn_fn:
            try:
                with self._pg_conn_fn() as conn:
                    conn.execute(
                        "UPDATE hmem_dream_proposals SET status = 'rejected', updated_at = now() WHERE id = %s",
                        (proposal_id,)
                    )
            except Exception:
                pass


# --- Memory Mining Service (AGENTS.md section 4) ---

class MemoryMiningService:
    """Acquisition pipeline extracting structured memories from interaction events."""

    def __init__(self, store: MemoryStoreService, clock: Callable[[], int]):
        self.store = store
        self._clock = clock

    def mine_interaction(
        self,
        event_type: ProvenanceOrigin,
        text: str,
        chat_id: Optional[str] = None,
        property_id: Optional[str] = None,
        lease_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> List[MemoryRecord]:
        """Extract validated memories from interaction events (deterministic fallback when offline)."""
        if not text or not str(text).strip():
            return []

        cleaned = str(text).strip()
        now = self._clock()
        mem_type: MemoryType = "preference" if "prefer" in cleaned.lower() or "like" in cleaned.lower() else "factual"
        layer: MemoryLayer = "working" if event_type in ("user_correction", "document") else "short_term"

        prov = Provenance(origin=event_type, learned_at=now, label=f"mined from {event_type}")
        tags = [f"event:{event_type}"]

        rec = self.store.add(
            content=cleaned,
            source=f"interaction:{event_type}",
            type=mem_type,
            layer=layer,
            confidence=0.85 if event_type == "user_correction" else 0.70,
            tags=tags,
            provenance=prov,
            chat_id=chat_id,
            property_id=property_id,
            lease_id=lease_id,
            tenant_id=tenant_id
        )
        return [rec]


# --- Master Unified H-MEM Class ---

class HMEM:
    """Master H-MEM Engine orchestrating store, ledger, retrieval, conflicts, sleep, and dreaming."""

    def __init__(
        self,
        clock: Optional[Callable[[], int]] = None,
        actor: str = "system",
        pg_conn_fn: Optional[Callable] = None
    ):
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.actor = actor
        self.ledger = TrustLedgerService(clock=self._clock, pg_conn_fn=pg_conn_fn)
        self.store = MemoryStoreService(clock=self._clock, ledger=self.ledger, actor=actor, pg_conn_fn=pg_conn_fn)
        self.retrieval = MemoryRetrievalService(store=self.store, ledger=self.ledger, clock=self._clock, actor=actor)
        self.conflicts = ConflictDetectionService(store=self.store, ledger=self.ledger, clock=self._clock, actor=actor)
        self.sleep_service = SleepCycleService(store=self.store, ledger=self.ledger, clock=self._clock, actor=actor)
        self.dreaming = DreamingService(store=self.store, ledger=self.ledger, clock=self._clock, actor=actor, pg_conn_fn=pg_conn_fn)
        self.mining = MemoryMiningService(store=self.store, clock=self._clock)
        self.sleep = self.sleep_service

    def add(self, *args: Any, **kwargs: Any) -> MemoryRecord:
        """Convenience method matching AGENTS.md."""
        if args and isinstance(args[0], dict):
            return self.store.add(**args[0])
        return self.store.add(*args, **kwargs)

    def query(self, *args: Any, **kwargs: Any) -> QueryResult:
        """Convenience query method matching AGENTS.md."""
        if args and isinstance(args[0], str) and len(args) > 1 and isinstance(args[1], dict):
            return self.retrieval.query(args[0], **args[1])
        return self.retrieval.query(*args, **kwargs)

    def add_memory(self, record_or_content: Any, **kwargs: Any) -> str:
        """Compatibility helper for adding memories."""
        if isinstance(record_or_content, MemoryRecord):
            rec = self.store.add(
                content=record_or_content.content or getattr(record_or_content, 'text', ''),
                source=record_or_content.source or 'unknown',
                confidence=record_or_content.confidence,
                tags=record_or_content.tags,
                lease_id=getattr(record_or_content, 'lease_id', None),
                property_id=getattr(record_or_content, 'property_id', None)
            )
            return rec.id
        elif isinstance(record_or_content, dict):
            rec = self.store.add(**record_or_content)
            return rec.id
        else:
            rec = self.store.add(content=str(record_or_content), **kwargs)
            return rec.id

    def search_memories(
        self,
        query: str,
        org_id: Optional[str] = None,
        limit: int = 5,
        min_confidence: float = 0.0
    ) -> List[RetrievedMemory]:
        """Compatibility helper for retrieving memories."""
        res = self.retrieval.query(query, limit=limit, min_confidence=min_confidence)
        return res.memories

    def feedback(self, memory_id: str, kind: FeedbackKind) -> None:
        """Convenience feedback method matching AGENTS.md."""
        self.retrieval.feedback(memory_id, kind)

    def run_sleep_cycle(self) -> Dict[str, Any]:
        """Execute sleep consolidation cycle with safety snapshot."""
        return self.sleep_service.execute()

    def run_dream(self, domain: Optional[str] = None, min_confidence: float = 0.7) -> List[DreamProposal]:
        """Generate synthesis proposals for uncommitted higher-order patterns."""
        return self.dreaming.dream()

    def approve_proposal(self, proposal_id: str) -> Optional[MemoryRecord]:
        """Human approval boundary: promotes dream proposal into durable long-term memory."""
        return self.dreaming.approve(proposal_id)

    def reject_proposal(self, proposal_id: str) -> None:
        """Reject unapproved dream proposal."""
        self.dreaming.reject(proposal_id)

    def sync_from_postgres(self) -> int:
        """Hydrate in-memory state from PostgreSQL tables."""
        if not self.store._pg_conn_fn:
            return 0
        count = 0
        try:
            with self.store._pg_conn_fn() as conn:
                # 1. Hydrate memories
                rows = conn.execute(
                    """SELECT id, content, type, layer, timestamp, last_accessed, access_count,
                              tags, embedding, confidence, source, provenance, chat_id, mission_id,
                              goal_run_id, property_id, lease_id, tenant_id, domain, namespace,
                              entities, related_to, supersedes, superseded_by, derived_from
                       FROM hmem_memories"""
                ).fetchall()
                max_seq = 0
                for r in rows:
                    mem_id = r[0]
                    if mem_id.startswith("mem-"):
                        try:
                            seq_val = int(mem_id.split("-")[1])
                            if seq_val > max_seq:
                                max_seq = seq_val
                        except Exception:
                            pass
                    prov_val = r[11]
                    if isinstance(prov_val, dict):
                        prov = Provenance.from_dict(prov_val)
                    else:
                        prov = Provenance(origin="manual", learned_at=r[4], label=r[10])

                    rec = MemoryRecord(
                        id=r[0],
                        content=r[1],
                        type=r[2],
                        layer=r[3],
                        timestamp=r[4],
                        last_accessed=r[5],
                        access_count=r[6],
                        tags=r[7] if isinstance(r[7], list) else (json.loads(r[7]) if r[7] else []),
                        embedding=r[8] if isinstance(r[8], list) else (json.loads(r[8]) if r[8] else []),
                        confidence=float(r[9]),
                        source=r[10],
                        provenance=prov,
                        chat_id=r[12],
                        mission_id=r[13],
                        goal_run_id=r[14],
                        property_id=r[15],
                        lease_id=r[16],
                        tenant_id=r[17],
                        domain=r[18],
                        namespace=r[19],
                        entities=r[20] if isinstance(r[20], list) else (json.loads(r[20]) if r[20] else []),
                        related_to=r[21] if isinstance(r[21], list) else (json.loads(r[21]) if r[21] else []),
                        supersedes=r[22],
                        superseded_by=r[23],
                        derived_from=r[24] if isinstance(r[24], list) else (json.loads(r[24]) if r[24] else [])
                    )
                    self.store._records[rec.id] = rec
                    count += 1
                if max_seq > self.store._seq:
                    self.store._seq = max_seq

                # 2. Hydrate dream proposals
                prows = conn.execute(
                    """SELECT id, type, content, derived_from, suggested_domain, status
                       FROM hmem_dream_proposals"""
                ).fetchall()
                max_dseq = 0
                for pr in prows:
                    pid = pr[0]
                    if pid.startswith("dream-"):
                        try:
                            dseq = int(pid.split("-")[1])
                            if dseq > max_dseq:
                                max_dseq = dseq
                        except Exception:
                            pass
                    p = DreamProposal(
                        id=pr[0],
                        type=pr[1],
                        content=pr[2],
                        derived_from=pr[3] if isinstance(pr[3], list) else (json.loads(pr[3]) if pr[3] else []),
                        suggested_domain=pr[4],
                        status=pr[5]
                    )
                    self.dreaming._proposals[p.id] = p
                if max_dseq > self.dreaming._seq:
                    self.dreaming._seq = max_dseq

                # 3. Hydrate audit ledger
                lrows = conn.execute(
                    """SELECT id, memory_id, action, actor, timestamp, previous_state, new_state, details
                       FROM hmem_audit_ledger ORDER BY timestamp ASC, id ASC"""
                ).fetchall()
                for lr in lrows:
                    entry = LedgerEntry(
                        memory_id=lr[1],
                        action=lr[2],
                        actor=lr[3],
                        timestamp=lr[4],
                        previous_state=lr[5] if isinstance(lr[5], dict) else (json.loads(lr[5]) if lr[5] else None),
                        new_state=lr[6] if isinstance(lr[6], dict) else (json.loads(lr[6]) if lr[6] else None),
                        details=lr[7] if isinstance(lr[7], dict) else (json.loads(lr[7]) if lr[7] else None)
                    )
                    self.ledger._entries.append(entry)
        except Exception as exc:
            logger.warning(f"Failed to sync H-MEM state from PostgreSQL: {exc}")
        return count


# --- Application Singleton Accessor ---

_hmem_singleton: Optional[HMEM] = None

def get_hmem_instance() -> HMEM:
    """Obtain or initialize thread-safe global H-MEM singleton wired to PostgreSQL."""
    global _hmem_singleton
    if _hmem_singleton is None:
        from ..database import db
        _hmem_singleton = HMEM(pg_conn_fn=db)
    return _hmem_singleton
