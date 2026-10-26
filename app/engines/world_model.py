"""Production Meterless World Model Engine for EQUILIBRA / ENIGMA.

Implements the official Meterless World Model specification:
- Canonical stable entity identifiers (content-addressed & externally keyed)
- Unicode NFKD normalization with combining marks and zero-width character stripping
- Levenshtein-based entity resolution with exact boundary banding:
  >= 0.85 -> auto-merge
  0.82 <= sim < 0.85 -> review queue
  < 0.82 -> new entity
- Five write primitives: upsert_entity, upsert_context, relate, assert_fact, snapshot
- Strict provenance boundary enforcement ("no provenance, no write")
- Append-only event store with strictly increasing sequence numbers
- Bitemporal edge management (valid_from, valid_to; superseding edges close previous edge)
- GraphView, FactsView, SnapshotView, TimelineView
- Idempotent batch ingestion pipeline with canonical state hashing
- Non-blocking contextual memory publishing to H-MEM
- PostgreSQL persistence surviving service restarts
"""

import copy
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger("equilibra.world_model")

# -----------------------------------------------------------------------------
# 1. Unicode Normalization & Stable Identifiers
# -----------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize names per Meterless stable-ids specification.
    
    1. Unicode NFKD normalization (decomposes accents/diacritics and non-breaking spaces)
    2. Strip combining diacritical marks (\u0300-\u036F)
    3. Strip zero-width characters (\u200B-\u200D, \uFEFF)
    4. Lowercase
    5. Collapse whitespace runs to a single space
    6. Trim
    """
    if not name:
        return ""
    # 1. NFKD
    decomposed = unicodedata.normalize("NFKD", name)
    # 2. Strip combining diacritical marks
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # 3. Strip zero-width characters
    stripped = re.sub(r'[\u200B-\u200D\uFEFF]', '', stripped)
    # 4. Lowercase
    lowered = stripped.lower()
    # 5. Collapse whitespace & trim
    return re.sub(r'\s+', ' ', lowered).strip()


def sha256_hex(val: str) -> str:
    """Return hex-encoded SHA-256 digest of UTF-8 string."""
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    """Deterministic JSON serialization: object keys sorted, None dropped where appropriate."""
    if value is None:
        return "null"
    if isinstance(value, (int, float, bool, str)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted([k for k in value.keys() if value[k] is not None])
        return "{" + ",".join(f"{json.dumps(k)}:{canonical_json(value[k])}" for k in keys) + "}"
    return json.dumps(str(value), ensure_ascii=False)


def external_id(entity_type: str, system: str, raw_id: str) -> str:
    """Externally keyed entity or context: literal grammar `type:system:externalId`."""
    return f"{entity_type}:{system}:{raw_id}"


def entity_id_from_name(entity_type: str, name: str) -> str:
    """Name-keyed entity: ent_<first 16 hex of sha256(type:normalize_name(name))>."""
    norm = normalize_name(name)
    digest = sha256_hex(f"{entity_type}:{norm}")[:16]
    return f"ent_{digest}"


def context_id_from_attrs(context_type: str, attrs: Dict[str, Any], parent: Optional[str] = None) -> str:
    """Attribute-keyed context: ctx_<first 16 hex of sha256(type:canonical_json(attrs):parent)>."""
    p_str = parent or ""
    digest = sha256_hex(f"{context_type}:{canonical_json(attrs)}:{p_str}")[:16]
    return f"ctx_{digest}"


def relationship_id(
    from_id: str,
    rel_type: str,
    to_id: str,
    context: Optional[str] = None,
    valid_from: Optional[str] = None
) -> str:
    """Content-addressed relationship ID."""
    c_str = context or ""
    vf_str = valid_from or ""
    digest = sha256_hex(f"{from_id}|{rel_type}|{to_id}|{c_str}|{vf_str}")[:16]
    return f"rel_{digest}"


def fact_id(
    about: str,
    predicate: str,
    value: Any,
    asserted_at: str,
    source_kind: str,
    source_url: Optional[str] = None
) -> str:
    """Content-addressed fact ID."""
    u_str = source_url or ""
    digest = sha256_hex(f"{about}|{predicate}|{canonical_json(value)}|{asserted_at}|{source_kind}|{u_str}")[:16]
    return f"fact_{digest}"


# -----------------------------------------------------------------------------
# 2. Entity Resolution & Merge Decision Banding
# -----------------------------------------------------------------------------

def levenshtein(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[n]


def name_similarity(raw_a: str, raw_b: str) -> float:
    """Normalized name similarity: 1 - distance / max(lenA, lenB)."""
    norm_a = normalize_name(raw_a)
    norm_b = normalize_name(raw_b)
    if not norm_a and not norm_b:
        return 1.0
    max_len = max(len(norm_a), len(norm_b))
    if max_len == 0:
        return 1.0
    return 1.0 - (levenshtein(norm_a, norm_b) / max_len)


def decide(similarity: float, auto_merge_at: float = 0.85, review_lower: float = 0.82) -> str:
    """Merge banding per Meterless spec (asserted in band-001):
    >= 0.85 -> auto-merge
    0.82 <= sim < 0.85 -> review
    < 0.82 -> new
    """
    # Floating point precision safety for exact comparisons (0.85, 0.82)
    sim = round(similarity, 6)
    if sim >= round(auto_merge_at, 6):
        return "auto-merge"
    if sim >= round(review_lower, 6):
        return "review"
    return "new"


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity between two sets."""
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa.intersection(sb))
    union = len(sa.union(sb))
    return inter / union if union > 0 else 0.0


# -----------------------------------------------------------------------------
# 3. Core Data Structures & Models
# -----------------------------------------------------------------------------

class IngestReport(dict):
    """Result report from batch ingestion pipeline supporting both dict and attribute access."""
    def __init__(self, processed: int, changed: bool, observations_count: int, canonical_shape_hash: str):
        super().__init__(
            processed=processed,
            changed=changed,
            observations_count=observations_count,
            canonical_shape_hash=canonical_shape_hash
        )
        self.processed = processed
        self.changed = changed
        self.observations_count = observations_count
        self.canonical_shape_hash = canonical_shape_hash


class StoredProvenance:
    def __init__(self, kind: str, at: str, by: Optional[str] = None, url: Optional[str] = None,
                 checksum: Optional[str] = None, run_id: Optional[str] = None, **kwargs):
        self.kind = kind
        self.at = at
        self.by = by or "system"
        self.url = url
        self.checksum = checksum
        self.run_id = run_id
        self.extra = kwargs

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        d = {"kind": self.kind, "at": self.at, "by": self.by}
        if self.url:
            d["url"] = self.url
        if self.checksum:
            d["checksum"] = self.checksum
        if self.run_id:
            d["runId"] = self.run_id
        return d


class WorldEntity:
    def __init__(self, entity_type: Optional[str] = None, entity_id: Optional[str] = None, attrs: Optional[Dict[str, Any]] = None, source: Optional[Any] = None,
                 created_at: Optional[str] = None, updated_at: Optional[str] = None, name: Optional[str] = None, aliases: Optional[List[str]] = None,
                 state: str = "active", schema_version: int = 1, **kwargs):
        now_iso = datetime.now(timezone.utc).isoformat()
        self.type = entity_type or kwargs.get("type", "entity")
        self.id = entity_id or kwargs.get("id", "")
        self.attrs = attrs or kwargs.get("properties", {})
        raw_source = source or kwargs.get("source")
        if isinstance(raw_source, StoredProvenance):
            self.source = raw_source
        elif isinstance(raw_source, dict):
            self.source = StoredProvenance(**raw_source)
        else:
            self.source = StoredProvenance(kind="manual", at=now_iso, by="system")
        self.created_at = created_at or now_iso
        self.updated_at = updated_at or now_iso
        self.name = name or kwargs.get("name")
        self.aliases = aliases or ([self.name] if self.name else [])
        self.state = state
        self.schema_version = schema_version
        self.organization_id = kwargs.get("organization_id", "default")

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "attrs": self.attrs,
            "aliases": self.aliases,
            "state": self.state,
            "schemaVersion": self.schema_version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "source": self.source.to_dict() if isinstance(self.source, StoredProvenance) else self.source
        }


class WorldRelationship:
    def __init__(self, rel_id: str, from_id: str, rel_type: str, to_id: str, source: StoredProvenance,
                 created_at: str, context: Optional[str] = None, attrs: Optional[Dict[str, Any]] = None,
                 valid_from: Optional[str] = None, valid_to: Optional[str] = None,
                 superseded_by: Optional[str] = None, schema_version: int = 1):
        self.id = rel_id
        self.from_id = from_id
        self.type = rel_type
        self.to_id = to_id
        self.context = context
        self.attrs = attrs or {}
        self.valid_from = valid_from or source.at
        self.valid_to = valid_to
        self.superseded_by = superseded_by
        self.source = source
        self.created_at = created_at
        self.schema_version = schema_version

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "from": self.from_id,
            "type": self.type,
            "to": self.to_id,
            "attrs": self.attrs,
            "validFrom": self.valid_from,
            "schemaVersion": self.schema_version,
            "createdAt": self.created_at,
            "source": self.source.to_dict() if isinstance(self.source, StoredProvenance) else self.source
        }
        if self.context:
            d["context"] = self.context
        if self.valid_to:
            d["validTo"] = self.valid_to
        if self.superseded_by:
            d["supersededBy"] = self.superseded_by
        return d


class WorldFact:
    def __init__(self, fact_id_val: Optional[str] = None, about: Optional[str] = None, predicate: Optional[str] = None, value: Any = None, source: Optional[Any] = None,
                 asserted_at: Optional[str] = None, confidence: float = 0.5, context: Optional[str] = None,
                 superseded_by: Optional[str] = None, **kwargs):
        now_iso = datetime.now(timezone.utc).isoformat()
        self.id = fact_id_val or kwargs.get("id") or f"fact-{uuid.uuid4().hex[:8]}"
        self.about = about or kwargs.get("entity_id", "")
        self.predicate = predicate or kwargs.get("predicate", "")
        self.value = value if value is not None else kwargs.get("value")
        self.confidence = confidence if confidence is not None else float(kwargs.get("confidence", 0.5))
        self.context = context or kwargs.get("context")
        raw_source = source or kwargs.get("source")
        if isinstance(raw_source, StoredProvenance):
            self.source = raw_source
        elif isinstance(raw_source, dict):
            self.source = StoredProvenance(**raw_source)
        else:
            self.source = StoredProvenance(kind="manual", at=now_iso, by=str(raw_source or "system"))
        self.asserted_at = asserted_at or now_iso
        self.superseded_by = superseded_by
        self.organization_id = kwargs.get("organization_id", "default")

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "about": self.about,
            "predicate": self.predicate,
            "value": self.value,
            "confidence": self.confidence,
            "assertedAt": self.asserted_at,
            "source": self.source.to_dict() if isinstance(self.source, StoredProvenance) else self.source
        }
        if self.context:
            d["context"] = self.context
        if self.superseded_by:
            d["supersededBy"] = self.superseded_by
        return d


class WorldContext:
    def __init__(self, context_type: str, context_id: str, attrs: Dict[str, Any], source: StoredProvenance,
                 created_at: str, updated_at: str, parent: Optional[str] = None, schema_version: int = 1):
        self.type = context_type
        self.id = context_id
        self.attrs = attrs or {}
        self.parent = parent
        self.source = source
        self.created_at = created_at
        self.updated_at = updated_at
        self.schema_version = schema_version

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "type": self.type,
            "id": self.id,
            "attrs": self.attrs,
            "schemaVersion": self.schema_version,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "source": self.source.to_dict() if isinstance(self.source, StoredProvenance) else self.source
        }
        if self.parent:
            d["parent"] = self.parent
        return d


class AuditEntry:
    def __init__(self, seq: int, action: str, actor: str, summary: str, target_id: Optional[str] = None,
                 timestamp: Optional[str] = None, run_id: Optional[str] = None):
        self.seq = seq
        self.action = action
        self.actor = actor
        self.summary = summary
        self.target_id = target_id
        self.run_id = run_id
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "action": self.action,
            "actor": self.actor,
            "summary": self.summary,
            "targetId": self.target_id,
            "runId": self.run_id,
            "timestamp": self.timestamp
        }


class MergeProposal:
    def __init__(self, proposal_id: str, left_id: str, right_id: str, left_name: str, right_name: str,
                 similarity: float, reason: str, proposed_at: str, status: str = "pending",
                 resolved_at: Optional[str] = None, resolved_by: Optional[str] = None):
        self.id = proposal_id
        self.left_id = left_id
        self.right_id = right_id
        self.left_name = left_name
        self.right_name = right_name
        self.similarity = similarity
        self.reason = reason
        self.proposed_at = proposed_at
        self.status = status
        self.resolved_at = resolved_at
        self.resolved_by = resolved_by

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "leftId": self.left_id,
            "rightId": self.right_id,
            "leftName": self.left_name,
            "rightName": self.right_name,
            "similarity": self.similarity,
            "reason": self.reason,
            "status": self.status,
            "proposedAt": self.proposed_at,
            "resolvedAt": self.resolved_at,
            "resolvedBy": self.resolved_by
        }


# -----------------------------------------------------------------------------
# 4. Graph & Read Views
# -----------------------------------------------------------------------------

class GraphView:
    def __init__(self, model: "WorldModel"):
        self.model = model

    def entity(self, entity_id: str) -> Optional[WorldEntity]:
        real_id = self.model.resolve_alias(entity_id)
        return self.model.entities.get(real_id)

    def neighbors_of(self, entity_id: str, opts: Optional[Dict[str, Any]] = None, **kwargs) -> List[WorldEntity]:
        opts = {**(opts or {}), **kwargs}
        rid = self.model.resolve_alias(entity_id)
        via = opts.get("via")
        in_context = opts.get("inContext") or opts.get("in_context")
        at = opts.get("at")
        out = []

        for rel in self.model.relationships.values():
            if via and rel.type != via:
                continue
            if in_context and rel.context != in_context:
                continue
            if at:
                # Point-in-time temporal check
                if rel.valid_from and at < rel.valid_from:
                    continue
                if rel.valid_to and at >= rel.valid_to:
                    continue
            else:
                # Current state excludes closed edges
                if rel.valid_to:
                    continue

            other_id = None
            if rel.from_id == rid:
                other_id = rel.to_id
            elif rel.to_id == rid:
                other_id = rel.from_id

            if other_id:
                ent = self.model.entities.get(other_id)
                if ent and ent not in out:
                    out.append(ent)

        out.sort(key=lambda x: x.id)
        return out

    def incoming(self, entity_id: str, opts: Optional[Dict[str, Any]] = None, **kwargs) -> List[WorldEntity]:
        opts = {**(opts or {}), **kwargs}
        rid = self.model.resolve_alias(entity_id)
        via = opts.get("via")
        out = []
        for rel in self.model.relationships.values():
            if rel.to_id != rid:
                continue
            if via and rel.type != via:
                continue
            if rel.valid_to:
                continue
            ent = self.model.entities.get(rel.from_id)
            if ent and ent not in out:
                out.append(ent)
        out.sort(key=lambda x: x.id)
        return out

    def entities_in_context(self, context_id: str, opts: Optional[Dict[str, Any]] = None, **kwargs) -> List[WorldEntity]:
        opts = {**(opts or {}), **kwargs}
        ent_type = opts.get("type")
        seen = {}
        for rel in self.model.relationships.values():
            if rel.context != context_id:
                continue
            for nid in [rel.from_id, rel.to_id]:
                ent = self.model.entities.get(nid)
                if ent and (not ent_type or ent.type == ent_type):
                    seen[ent.id] = ent
        out = list(seen.values())
        out.sort(key=lambda x: x.id)
        return out

    def traverse(self, start_id: str, opts: Dict[str, Any]) -> List[WorldEntity]:
        via = opts.get("via")
        direction = opts.get("direction", "ancestors")
        max_depth = opts.get("maxDepth", opts.get("max_depth", 5))

        out = []
        visited = set()
        frontier = [self.model.resolve_alias(start_id)]

        for _ in range(max_depth):
            if not frontier:
                break
            nxt = []
            for cur_id in frontier:
                for rel in self.model.relationships.values():
                    if via and rel.type != via:
                        continue
                    if rel.valid_to:
                        continue
                    target = None
                    if direction == "ancestors":
                        if rel.from_id == cur_id:
                            target = rel.to_id
                    else:
                        if rel.to_id == cur_id:
                            target = rel.from_id

                    if target and target not in visited:
                        visited.add(target)
                        ent = self.model.entities.get(target)
                        if ent:
                            out.append(ent)
                        nxt.append(target)
            frontier = nxt

        return out

    def query(self, opts: Optional[Dict[str, Any]] = None) -> List[WorldEntity]:
        opts = opts or {}
        target_type = opts.get("type")
        where_fn = opts.get("where")
        res = []
        for ent in self.model.entities.values():
            if target_type and ent.type != target_type:
                continue
            if where_fn and not where_fn(ent):
                continue
            res.append(ent)
        res.sort(key=lambda x: x.id)
        return res


class FactsView:
    def __init__(self, model: "WorldModel"):
        self.model = model

    def about(self, entity_id: str) -> List[WorldFact]:
        rid = self.model.resolve_alias(entity_id)
        facts = [f for f in self.model.facts.values() if f.about == rid]
        facts.sort(key=lambda x: x.asserted_at)
        return facts


class SnapshotView:
    def __init__(self, model: "WorldModel"):
        self.model = model

    def entity_at(self, entity_id: str, at: str) -> Optional[WorldEntity]:
        iso = f"{at}T23:59:59.999Z" if len(at) == 10 else at
        # Point-in-time replay: fold up to timestamp iso
        folded_aliases = {}
        folded_entities = {}

        for ev in self.model.events_log:
            if ev.get("at", "") > iso:
                continue
            kind = ev.get("kind")
            payload = ev.get("payload", {})
            if kind == "alias":
                folded_aliases[payload.get("aliasId")] = payload.get("primaryId")
            elif kind == "upsertEntity":
                eid = payload.get("id")
                folded_entities[eid] = WorldEntity(
                    entity_type=payload.get("type"),
                    entity_id=eid,
                    attrs=copy.deepcopy(payload.get("attrs", {})),
                    source=payload.get("source"),
                    created_at=payload.get("createdAt"),
                    updated_at=payload.get("updatedAt"),
                    name=payload.get("name"),
                    aliases=payload.get("aliases", []),
                    state=payload.get("state", "active")
                )

        # Resolve alias
        cur = entity_id
        seen = set()
        while cur in folded_aliases and cur not in seen:
            seen.add(cur)
            cur = folded_aliases[cur]

        return folded_entities.get(cur)


class TimelineView:
    def __init__(self, model: "WorldModel"):
        self.model = model

    def get(self) -> List[Dict[str, Any]]:
        return list(self.model.events_log)


# -----------------------------------------------------------------------------
# 5. Full Meterless WorldModel Implementation
# -----------------------------------------------------------------------------

class WorldModel:
    """Production Meterless World Model engine with PostgreSQL persistence and H-MEM hooks."""

    def __init__(self, namespace: str = "default", storage: str = "postgres", clock: Optional[Callable[[], datetime]] = None):
        self.namespace = namespace
        self.storage = storage
        self.clock = clock or (lambda: datetime.now(timezone.utc))

        self.entities: Dict[str, WorldEntity] = {}
        self.contexts: Dict[str, WorldContext] = {}
        self.relationships: Dict[str, WorldRelationship] = {}
        self.facts: Dict[str, WorldFact] = {}
        self.aliases: Dict[str, str] = {}
        self.merge_queue_items: List[MergeProposal] = []
        self.audit_log: List[AuditEntry] = []
        self.events_log: List[Dict[str, Any]] = []
        self._seq = 0

        if self.storage == "postgres":
            self.hydrate_from_postgres()

    def resolve_alias(self, entity_id: str) -> str:
        """Resolve primary canonical entity ID across alias chains."""
        cur = entity_id
        seen = set()
        while cur in self.aliases and cur not in seen:
            seen.add(cur)
            cur = self.aliases[cur]
        return cur

    def _normalize_provenance(self, source: Optional[Any]) -> StoredProvenance:
        """Enforce load-bearing provenance gate: no provenance, no write (prov-001)."""
        if not source:
            raise ValueError("World Model: every write carries provenance (kind + at). No provenance, no write.")
        if isinstance(source, StoredProvenance):
            return source
        if isinstance(source, dict):
            kind = source.get("kind")
            at = source.get("at")
            if not kind or at is None:
                raise ValueError("World Model: provenance requires 'kind' and 'at'. No provenance, no write.")
            at_str = at.isoformat() if isinstance(at, datetime) else str(at)
            return StoredProvenance(
                kind=kind,
                at=at_str,
                by=source.get("by", "system"),
                url=source.get("url"),
                checksum=source.get("checksum"),
                run_id=source.get("runId", source.get("run_id"))
            )
        raise ValueError("World Model: invalid provenance object shape.")

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _log_audit(self, action: str, actor: str, summary: str, target_id: Optional[str] = None,
                   run_id: Optional[str] = None, timestamp: Optional[str] = None) -> AuditEntry:
        seq = self._next_seq()
        entry = AuditEntry(seq=seq, action=action, actor=actor, summary=summary,
                           target_id=target_id, timestamp=timestamp or self.clock().isoformat(), run_id=run_id)
        self.audit_log.append(entry)
        if self.storage == "postgres":
            self._persist_audit_entry(entry)
        return entry

    # -------------------------------------------------------------------------
    # Core Write Primitives
    # -------------------------------------------------------------------------

    def upsert_entity(
        self,
        entity_type: str,
        name: Optional[str] = None,
        external_key: Optional[Dict[str, str]] = None,
        attrs: Optional[Dict[str, Any]] = None,
        source: Optional[Any] = None,
        state: str = "active"
    ) -> WorldEntity:
        """Upsert entity with provenance validation and resolution pass (band-001, sid-001)."""
        if isinstance(entity_type, WorldEntity):
            ent = entity_type
            prov = self._normalize_provenance(ent.source)
            return self._fold_entity_upsert(
                ent_id=ent.id,
                entity_type=ent.type,
                name=ent.name,
                attrs=ent.attrs,
                source=prov,
                state=ent.state
            )

        prov = self._normalize_provenance(source)
        attrs = attrs or {}
        display_name = name or attrs.get("name")

        if external_key:
            ent_id = external_id(entity_type, external_key["system"], external_key["id"])
        elif display_name:
            ent_id = entity_id_from_name(entity_type, display_name)
        else:
            raise ValueError("World Model: name-keyed entities need a name (or provide an externalKey)")

        # Resolution pass for name-keyed entities
        if not external_key and display_name:
            for other in list(self.entities.values()):
                if other.type != entity_type or other.id == ent_id or not other.name:
                    continue
                sim = name_similarity(display_name, other.name)
                decision = decide(sim)

                if decision == "auto-merge":
                    # Aliasing event
                    self.aliases[ent_id] = other.id
                    alias_event = {
                        "id": f"ev_{self._next_seq()}",
                        "kind": "alias",
                        "payload": {
                            "aliasId": ent_id,
                            "primaryId": other.id,
                            "mergedAt": prov.at,
                            "mergedBy": "resolver",
                            "reason": f"similarity {sim:.3f}"
                        },
                        "at": prov.at
                    }
                    self.events_log.append(alias_event)
                    self._log_audit("auto-merge", "resolver", f"{display_name} -> {other.name} ({sim:.3f})",
                                    target_id=other.id, timestamp=prov.at)
                    return self._fold_entity_upsert(other.id, entity_type, display_name, attrs, prov, state)

                elif decision == "review":
                    # Stage merge proposal
                    prop_id = f"merge_{len(self.merge_queue_items) + 1}"
                    already_queued = any(
                        (p.left_id == ent_id and p.right_id == other.id) or (p.left_id == other.id and p.right_id == ent_id)
                        for p in self.merge_queue_items
                    )
                    if not already_queued:
                        proposal = MergeProposal(
                            proposal_id=prop_id,
                            left_id=ent_id,
                            right_id=other.id,
                            left_name=display_name,
                            right_name=other.name,
                            similarity=sim,
                            reason="name similarity in review band [0.82, 0.85)",
                            proposed_at=prov.at,
                            status="pending"
                        )
                        self.merge_queue_items.append(proposal)
                        self._log_audit("merge-proposed", "resolver", f"{display_name} ~ {other.name} ({sim:.3f}) queued",
                                        target_id=prop_id, timestamp=prov.at)
                        if self.storage == "postgres":
                            self._persist_merge_proposal(proposal)

        return self._fold_entity_upsert(ent_id, entity_type, display_name, attrs, prov, state)

    def _fold_entity_upsert(
        self,
        ent_id: str,
        entity_type: str,
        name: Optional[str],
        attrs: Dict[str, Any],
        source: StoredProvenance,
        state: str
    ) -> WorldEntity:
        resolved_id = self.resolve_alias(ent_id)
        existing = self.entities.get(resolved_id)

        if existing:
            merged_attrs = copy.deepcopy(existing.attrs)
            merged_attrs.update(attrs)
            aliases = list(existing.aliases)
            if name and name not in aliases:
                aliases.append(name)
            entity = WorldEntity(
                entity_type=entity_type,
                entity_id=resolved_id,
                attrs=merged_attrs,
                source=source,
                created_at=existing.created_at,
                updated_at=source.at,
                name=existing.name or name,
                aliases=aliases,
                state=state
            )
        else:
            entity = WorldEntity(
                entity_type=entity_type,
                entity_id=resolved_id,
                attrs=copy.deepcopy(attrs),
                source=source,
                created_at=source.at,
                updated_at=source.at,
                name=name,
                aliases=[name] if name else [],
                state=state
            )

        self.entities[resolved_id] = entity
        ev = {
            "id": f"ev_{self._next_seq()}",
            "kind": "upsertEntity",
            "payload": entity.to_dict(),
            "at": source.at
        }
        self.events_log.append(ev)
        self._log_audit("upsertEntity", source.by, f"{resolved_id} ({entity_type})", target_id=resolved_id,
                        run_id=source.run_id, timestamp=source.at)

        if self.storage == "postgres":
            self._persist_entity(entity)

        # Notify H-MEM safely
        self._publish_to_hmem(
            action="upsert_entity",
            text=f"World Model Entity {entity.type} '{entity.name or entity.id}' updated: {list(entity.attrs.keys())}",
            entity_id=entity.id,
            source_id=source.run_id or entity.id
        )

        return entity

    def upsert_context(
        self,
        context_type: str,
        attrs: Optional[Dict[str, Any]] = None,
        external_key: Optional[Dict[str, str]] = None,
        parent: Optional[str] = None,
        source: Optional[Any] = None
    ) -> WorldContext:
        prov = self._normalize_provenance(source)
        attrs = attrs or {}
        if external_key:
            cid = external_id(context_type, external_key["system"], external_key["id"])
        else:
            cid = context_id_from_attrs(context_type, attrs, parent)

        ctx = WorldContext(
            context_type=context_type,
            context_id=cid,
            attrs=copy.deepcopy(attrs),
            source=prov,
            created_at=prov.at,
            updated_at=prov.at,
            parent=parent
        )
        self.contexts[cid] = ctx
        ev = {
            "id": f"ev_{self._next_seq()}",
            "kind": "upsertContext",
            "payload": ctx.to_dict(),
            "at": prov.at
        }
        self.events_log.append(ev)
        self._log_audit("upsertContext", prov.by, f"{cid} ({context_type})", target_id=cid,
                        run_id=prov.run_id, timestamp=prov.at)
        return ctx

    def relate(
        self,
        from_id: str,
        rel_type: str,
        to_id: str,
        context: Optional[str] = None,
        attrs: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        source: Optional[Any] = None
    ) -> WorldRelationship:
        """Create bitemporal relationship; superseding edges close previous edge (bitemp-001)."""
        prov = self._normalize_provenance(source)
        real_from = self.resolve_alias(from_id)
        real_to = self.resolve_alias(to_id)
        vf = valid_from or prov.at

        rid = relationship_id(real_from, rel_type, real_to, context, vf)
        if rid in self.relationships:
            return self.relationships[rid]

        # Bitemporal edge closing: find prior open edge with same (from, type, context) and close it
        for prior_rel in list(self.relationships.values()):
            if prior_rel.from_id == real_from and prior_rel.type == rel_type and prior_rel.context == context and not prior_rel.valid_to:
                if prior_rel.to_id != real_to and prior_rel.valid_from <= vf:
                    prior_rel.valid_to = vf
                    prior_rel.superseded_by = rid
                    if self.storage == "postgres":
                        self._persist_relationship(prior_rel)

        rel = WorldRelationship(
            rel_id=rid,
            from_id=real_from,
            rel_type=rel_type,
            to_id=real_to,
            source=prov,
            created_at=prov.at,
            context=context,
            attrs=attrs or {},
            valid_from=vf,
            valid_to=valid_to
        )
        self.relationships[rid] = rel
        ev = {
            "id": f"ev_{self._next_seq()}",
            "kind": "relate",
            "payload": rel.to_dict(),
            "at": prov.at
        }
        self.events_log.append(ev)
        self._log_audit("relate", prov.by, f"{real_from} -[{rel_type}]-> {real_to}", target_id=rid,
                        run_id=prov.run_id, timestamp=prov.at)

        if self.storage == "postgres":
            self._persist_relationship(rel)

        return rel

    def assert_fact(
        self,
        about: str,
        predicate: str,
        value: Any,
        confidence: float = 0.5,
        context: Optional[str] = None,
        source: Optional[Any] = None,
        conflict_policy: str = "most-recent-wins"
    ) -> WorldFact:
        """Assert grounded fact with conflict resolution policy."""
        if isinstance(about, WorldFact):
            f = about
            about = f.about
            predicate = f.predicate
            value = f.value
            confidence = f.confidence
            context = f.context
            source = f.source

        prov = self._normalize_provenance(source)
        real_about = self.resolve_alias(about)
        fid = fact_id(real_about, predicate, value, prov.at, prov.kind, prov.url)

        if fid in self.facts:
            return self.facts[fid]

        fact = WorldFact(
            fact_id_val=fid,
            about=real_about,
            predicate=predicate,
            value=value,
            source=prov,
            asserted_at=prov.at,
            confidence=confidence,
            context=context
        )

        rivals = [f for f in self.facts.values() if f.about == real_about and f.predicate == predicate and not f.superseded_by]
        winner = fact
        for rival in rivals:
            rival_wins = False
            if conflict_policy == "highest-confidence-wins":
                rival_wins = rival.confidence > winner.confidence
            else:
                rival_wins = rival.asserted_at > winner.asserted_at
            if rival_wins:
                winner = rival

        self.facts[fid] = fact
        for f in [fact] + rivals:
            if f.id != winner.id:
                f.superseded_by = winner.id
                if self.storage == "postgres":
                    self._persist_fact(f)

        # Update subject entity attribute
        if real_about not in self.entities:
            inf_type = real_about.split(":")[0] if ":" in real_about else "entity"
            self._fold_entity_upsert(real_about, inf_type, None, {}, prov, "emerging")

        ent = self.entities[real_about]
        ent.attrs[predicate] = winner.value
        ent.updated_at = prov.at

        ev = {
            "id": f"ev_{self._next_seq()}",
            "kind": "assertFact",
            "payload": fact.to_dict(),
            "at": prov.at
        }
        self.events_log.append(ev)
        self._log_audit("assertFact", prov.by, f"{real_about}.{predicate} = {json.dumps(winner.value)} ({conflict_policy})",
                        target_id=fid, run_id=prov.run_id, timestamp=prov.at)

        if self.storage == "postgres":
            self._persist_fact(fact)
            self._persist_entity(ent)

        return fact

    # -------------------------------------------------------------------------
    # Batch Ingest Pipeline (idem-001, idem-002)
    # -------------------------------------------------------------------------

    def state_shape_canonical(self) -> str:
        """Deterministic canonical representation of current world model state."""
        shape = {
            "entities": {
                eid: {
                    "type": e.type,
                    "name": e.name,
                    "attrs": e.attrs,
                    "aliases": sorted(e.aliases),
                    "state": e.state
                }
                for eid, e in sorted(self.entities.items())
            },
            "relationships": {
                rid: {
                    "from": r.from_id,
                    "type": r.type,
                    "to": r.to_id,
                    "validFrom": r.valid_from,
                    "validTo": r.valid_to
                }
                for rid, r in sorted(self.relationships.items())
            },
            "facts": {
                fid: {
                    "about": f.about,
                    "predicate": f.predicate,
                    "value": f.value,
                    "supersededBy": f.superseded_by
                }
                for fid, f in sorted(self.facts.items())
            }
        }
        return canonical_json(shape)

    def ingest(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ingest batch of observations idempotently.
        
        Returns IngestReport with `changed: bool` and processed counts.
        Identical batch re-run returns `changed: False` (idem-001).
        """
        initial_canonical = self.state_shape_canonical()
        processed_count = 0

        for obs in observations:
            src = obs.get("source") or {"kind": "ingest", "at": obs.get("at") or self.clock().isoformat()}
            if "at" not in src and "at" in obs:
                src["at"] = obs["at"]
            prov = self._normalize_provenance(src)

            # Ingest item as an entity
            ext_id = obs.get("externalId") or obs.get("id") or sha256_hex(obs.get("title", ""))[:12]
            item_type = obs.get("type", "item")
            title = obs.get("title", "")

            item_ent = self.upsert_entity(
                entity_type=item_type,
                name=title,
                external_key={"system": "ingest", "id": ext_id},
                attrs={"title": title, "text": obs.get("text", "")},
                source=prov
            )
            processed_count += 1

            # Ingest mentioned entities and link them
            for mention in obs.get("entities", []):
                m_type = mention.get("type", "entity")
                m_name = mention.get("name", "")
                if m_name:
                    m_ent = self.upsert_entity(
                        entity_type=m_type,
                        name=m_name,
                        source=prov
                    )
                    self.relate(
                        from_id=item_ent.id,
                        rel_type="mentions",
                        to_id=m_ent.id,
                        valid_from=prov.at,
                        source=prov
                    )

        final_canonical = self.state_shape_canonical()
        changed = (initial_canonical != final_canonical)

        return IngestReport(
            processed=processed_count,
            changed=changed,
            observations_count=len(observations),
            canonical_shape_hash=sha256_hex(final_canonical)
        )

    # -------------------------------------------------------------------------
    # Views & Operator API
    # -------------------------------------------------------------------------

    def view(self, name: str) -> Any:
        if name == "graph":
            return GraphView(self)
        if name == "facts":
            return FactsView(self)
        if name == "snapshot":
            return SnapshotView(self)
        if name == "timeline":
            return TimelineView(self)
        raise ValueError(f"World Model: unknown view '{name}'")

    def get_entity(self, entity_id: str) -> Optional[WorldEntity]:
        """Convenience accessor to get entity by ID or alias from graph view."""
        return self.view("graph").entity(entity_id)

    def audit(self) -> List[AuditEntry]:
        return list(self.audit_log)

    def events(self) -> List[Dict[str, Any]]:
        return list(self.events_log)

    def merge_queue(self) -> List[MergeProposal]:
        return [p for p in self.merge_queue_items if p.status == "pending"]

    def approve_merge(self, proposal_id: str, by: str) -> None:
        prop = next((p for p in self.merge_queue_items if p.id == proposal_id and p.status == "pending"), None)
        if not prop:
            raise KeyError(f"World Model: no pending merge proposal {proposal_id}")
        at = self.clock().isoformat()
        prop.status = "approved"
        prop.resolved_at = at
        prop.resolved_by = by

        # Create alias event
        self.aliases[prop.left_id] = prop.right_id
        alias_ev = {
            "id": f"ev_{self._next_seq()}",
            "kind": "alias",
            "payload": {
                "aliasId": prop.left_id,
                "primaryId": prop.right_id,
                "mergedAt": at,
                "mergedBy": by,
                "reason": prop.reason
            },
            "at": at
        }
        self.events_log.append(alias_ev)
        self._log_audit("merge-approved", by, f"{prop.left_name} -> {prop.right_name}",
                        target_id=prop.right_id, timestamp=at)

        if self.storage == "postgres":
            self._persist_merge_proposal(prop)

    def reject_merge(self, proposal_id: str, by: str) -> None:
        prop = next((p for p in self.merge_queue_items if p.id == proposal_id and p.status == "pending"), None)
        if not prop:
            raise KeyError(f"World Model: no pending merge proposal {proposal_id}")
        at = self.clock().isoformat()
        prop.status = "rejected"
        prop.resolved_at = at
        prop.resolved_by = by
        self._log_audit("merge-rejected", by, f"{prop.left_name} stays separate from {prop.right_name}",
                        target_id=proposal_id, timestamp=at)

        if self.storage == "postgres":
            self._persist_merge_proposal(prop)

    # -------------------------------------------------------------------------
    # H-MEM Contextual Memory Integration (Non-blocking)
    # -------------------------------------------------------------------------

    def _publish_to_hmem(self, action: str, text: str, entity_id: str, source_id: str) -> None:
        """Publish contextual memory to H-MEM. Non-blocking: failures never break World Model."""
        try:
            from app.engines.hmem import get_hmem_instance, Provenance
            hmem = get_hmem_instance()
            prov = Provenance(
                source_id=source_id,
                document_id=f"world_model:{self.namespace}",
                metadata={"entity_id": entity_id, "action": action, "namespace": self.namespace}
            )
            hmem.store.add(
                tier="working",
                text=f"[WorldModel:{self.namespace}] {text}",
                tags=["world_model", action, f"entity:{entity_id}"],
                domain="property_management",
                provenance=prov,
                confidence=0.9
            )
        except Exception as exc:
            logger.debug(f"H-MEM non-blocking contextual publish skipped: {exc}")

    # -------------------------------------------------------------------------
    # PostgreSQL Persistence
    # -------------------------------------------------------------------------

    def hydrate_from_postgres(self) -> int:
        """Load persistent World Model state from PostgreSQL."""
        try:
            from app.database import db
            with db() as conn:
                # Load entities
                rows = conn.execute(
                    "SELECT id, entity_type, name, attrs, aliases, state, created_at, updated_at, source FROM world_entities WHERE namespace = %s",
                    (self.namespace,)
                ).fetchall()
                for r in rows:
                    eid, etype, name, attrs, aliases, st, ca, ua, src = r
                    self.entities[eid] = WorldEntity(
                        entity_type=etype,
                        entity_id=eid,
                        name=name,
                        attrs=attrs or {},
                        aliases=aliases or [],
                        state=st,
                        created_at=ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                        updated_at=ua.isoformat() if hasattr(ua, "isoformat") else str(ua),
                        source=src or {"kind": "database", "at": str(ca)}
                    )

                # Load relationships
                rel_rows = conn.execute(
                    "SELECT id, from_id, rel_type, to_id, context, attrs, valid_from, valid_to, superseded_by, created_at, source FROM world_relationships WHERE namespace = %s",
                    (self.namespace,)
                ).fetchall()
                for r in rel_rows:
                    rid, fid, rtype, tid, ctx, attrs, vf, vt, sby, ca, src = r
                    self.relationships[rid] = WorldRelationship(
                        rel_id=rid,
                        from_id=fid,
                        rel_type=rtype,
                        to_id=tid,
                        context=ctx,
                        attrs=attrs or {},
                        valid_from=str(vf) if vf else None,
                        valid_to=str(vt) if vt else None,
                        superseded_by=sby,
                        created_at=ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
                        source=src or {"kind": "database", "at": str(ca)}
                    )

                # Load merge proposals
                p_rows = conn.execute(
                    "SELECT id, left_id, right_id, left_name, right_name, similarity, reason, status, proposed_at, resolved_at, resolved_by FROM world_merge_proposals WHERE namespace = %s",
                    (self.namespace,)
                ).fetchall()
                for r in p_rows:
                    pid, lid, rid, lname, rname, sim, rsn, st, pa, ra, rb = r
                    self.merge_queue_items.append(MergeProposal(
                        proposal_id=pid,
                        left_id=lid,
                        right_id=rid,
                        left_name=lname,
                        right_name=rname,
                        similarity=float(sim),
                        reason=rsn,
                        status=st,
                        proposed_at=str(pa),
                        resolved_at=str(ra) if ra else None,
                        resolved_by=rb
                    ))

            logger.info(f"Hydrated {len(self.entities)} entities and {len(self.relationships)} relationships from PostgreSQL.")
            return len(self.entities)
        except Exception as exc:
            logger.warning(f"World Model database hydration notice: {exc}")
            return 0

    def _persist_entity(self, entity: WorldEntity) -> None:
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO world_entities (id, namespace, entity_type, name, attrs, aliases, state, created_at, updated_at, source)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (id) DO UPDATE SET
                           name = excluded.name,
                           attrs = excluded.attrs,
                           aliases = excluded.aliases,
                           state = excluded.state,
                           updated_at = excluded.updated_at""",
                    (
                        entity.id,
                        self.namespace,
                        entity.type,
                        entity.name,
                        json.dumps(entity.attrs, default=str),
                        json.dumps(entity.aliases, default=str),
                        entity.state,
                        entity.created_at,
                        entity.updated_at,
                        json.dumps(entity.source.to_dict() if isinstance(entity.source, StoredProvenance) else entity.source)
                    )
                )
        except Exception as exc:
            logger.debug(f"Entity persistence notice: {exc}")

    def _persist_relationship(self, rel: WorldRelationship) -> None:
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO world_relationships (id, namespace, from_id, rel_type, to_id, context, attrs, valid_from, valid_to, superseded_by, created_at, source)
                       VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (id) DO UPDATE SET
                           valid_to = excluded.valid_to,
                           superseded_by = excluded.superseded_by,
                           attrs = excluded.attrs""",
                    (
                        rel.id,
                        self.namespace,
                        rel.from_id,
                        rel.type,
                        rel.to_id,
                        rel.context,
                        json.dumps(rel.attrs, default=str),
                        rel.valid_from,
                        rel.valid_to,
                        rel.superseded_by,
                        rel.created_at,
                        json.dumps(rel.source.to_dict() if isinstance(rel.source, StoredProvenance) else rel.source)
                    )
                )
        except Exception as exc:
            logger.debug(f"Relationship persistence notice: {exc}")

    def _persist_fact(self, fact: WorldFact) -> None:
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO world_facts (id, namespace, about, predicate, value, confidence, context, asserted_at, superseded_by, source)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (id) DO UPDATE SET
                           superseded_by = excluded.superseded_by,
                           confidence = excluded.confidence""",
                    (
                        fact.id,
                        self.namespace,
                        fact.about,
                        fact.predicate,
                        json.dumps(fact.value, default=str),
                        fact.confidence,
                        fact.context,
                        fact.asserted_at,
                        fact.superseded_by,
                        json.dumps(fact.source.to_dict() if isinstance(fact.source, StoredProvenance) else fact.source)
                    )
                )
        except Exception as exc:
            logger.debug(f"Fact persistence notice: {exc}")

    def _persist_merge_proposal(self, prop: MergeProposal) -> None:
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO world_merge_proposals (id, namespace, left_id, right_id, left_name, right_name, similarity, reason, status, proposed_at, resolved_at, resolved_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET
                           status = excluded.status,
                           resolved_at = excluded.resolved_at,
                           resolved_by = excluded.resolved_by""",
                    (
                        prop.id,
                        self.namespace,
                        prop.left_id,
                        prop.right_id,
                        prop.left_name,
                        prop.right_name,
                        prop.similarity,
                        prop.reason,
                        prop.status,
                        prop.proposed_at,
                        prop.resolved_at,
                        prop.resolved_by
                    )
                )
        except Exception as exc:
            logger.debug(f"Merge proposal persistence notice: {exc}")

    def _persist_audit_entry(self, entry: AuditEntry) -> None:
        try:
            from app.database import db
            with db() as conn:
                conn.execute(
                    """INSERT INTO world_audit_ledger (seq, namespace, action, actor, summary, target_id, run_id, timestamp)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (seq, namespace) DO NOTHING""",
                    (
                        entry.seq,
                        self.namespace,
                        entry.action,
                        entry.actor,
                        entry.summary,
                        entry.target_id,
                        entry.run_id,
                        entry.timestamp
                    )
                )
        except Exception as exc:
            logger.debug(f"Audit ledger persistence notice: {exc}")


_model_instances: Dict[str, WorldModel] = {}

def get_world_model(namespace: str = "default", org_id: Optional[str] = None) -> WorldModel:
    """Retrieve or create singleton WorldModel per namespace/tenant."""
    global _model_instances
    ns = org_id or namespace
    if ns not in _model_instances:
        _model_instances[ns] = WorldModel(namespace=ns)
    return _model_instances[ns]
