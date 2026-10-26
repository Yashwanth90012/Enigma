"""Meterless World Model Implementation for ENIGMA Autonomous Rental Reconciliation.

Complies with upstream Meterless World Model reference specification:
- Canonical stable entity identifiers
- Append-only event sourcing
- Monotonic versioning & change tracking
- Derived latest state projection with deterministic event replay
- Structured context builder for autonomous agents
- Causal lineage DAG tracking
"""

import json
import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .database import db

logger = logging.getLogger("equilibra.world_model")

# Re-export official Meterless World Model specification & engine primitives
from .engines.world_model import (
    WorldModel,
    get_world_model,
    normalize_name,
    entity_id_from_name,
    external_id,
    context_id_from_attrs,
    relationship_id,
    fact_id,
    canonical_json,
    levenshtein,
    name_similarity,
    decide,
    jaccard,
    WorldEntity,
    WorldRelationship,
    WorldFact,
    WorldContext,
    AuditEntry,
    MergeProposal
)

def canonical_id(entity_type: str, raw_id: str) -> str:
    """Normalize raw identifiers into canonical stable entity IDs."""
    clean_type = entity_type.strip().lower()
    clean_id = str(raw_id).strip()
    if clean_type == 'tenant':
        clean_id = re.sub(r'[^a-zA-Z0-9]+', '-', clean_id).strip('-').lower()
    return f"{clean_type}:{clean_id}"

def parse_canonical_id(cid: str) -> tuple[str, str]:
    """Parse a canonical ID back to (type, raw_id)."""
    parts = cid.split(':', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return 'unknown', cid

def get_next_version(conn, case_id: str) -> int:
    """Compute the next monotonic version for a case."""
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM world_events WHERE case_id = %s",
        (case_id,)
    ).fetchone()
    return row[0] if row else 1

def record_event(
    case_id: str,
    entity_id: str,
    event_type: str,
    payload: Dict[str, Any],
    caused_by: Optional[List[int]] = None,
    actor: str = "system",
    source: Optional[str] = None,
    **kwargs
) -> int:
    """Record an append-only event into the World Model and update the derived projection."""
    c_id = canonical_id('case' if entity_id == case_id else 'entity', entity_id)
    caused_by = caused_by or []
    
    with db() as conn:
        version = get_next_version(conn, case_id)
        cursor = conn.execute(
            """INSERT INTO world_events (case_id, entity_id, canonical_id, event_type, payload, version, caused_by)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
               RETURNING id""",
            (case_id, entity_id, c_id, event_type, json.dumps(payload, default=str), version, json.dumps(caused_by))
        )
        row = cursor.fetchone()
        event_id = row[0] if row else None
        
        # Deterministically compute and persist derived latest state projection
        derived = replay_events_for_state(conn, case_id)
        conn.execute(
            """INSERT INTO derived_states (case_id, canonical_id, version, state, updated_at)
               VALUES (%s, %s, %s, %s::jsonb, now())
               ON CONFLICT (case_id) DO UPDATE
               SET version = excluded.version, canonical_id = excluded.canonical_id,
                   state = excluded.state, updated_at = now()""",
            (case_id, c_id, version, json.dumps(derived, default=str))
        )

    # Step 4: Non-blocking H-MEM Contextual Memory Integration
    _publish_event_to_hmem_safely(case_id, entity_id, event_type, payload, event_id)
    return event_id

def _publish_event_to_hmem_safely(
    case_id: str,
    entity_id: str,
    event_type: str,
    payload: Dict[str, Any],
    event_id: Optional[int]
) -> None:
    """Store concise contextual memory referencing the authoritative World Model event.
    
    Guarantees:
    - Does not copy the entire event log into H-MEM.
    - Decoupled: H-MEM errors never roll back or fail the committed World Model event.
    - Stores source provenance (case_id, entity_id, event_type, event_id).
    """
    CONSEQUENTIAL_EVENTS = {
        "lease_signed", "lease_renewal_approved", "move_out_approved",
        "vendor_invoice_generated", "vendor_bill_reconciled", "vendor_payment_recorded",
        "work_order_created", "emergency_maintenance_triaged", "approval_recorded",
        "compliance_scan_completed", "investigation_completed"
    }
    if event_type not in CONSEQUENTIAL_EVENTS:
        return

    try:
        from .engines.hmem import get_hmem_instance, Provenance
        hmem = get_hmem_instance()
        summary_items = []
        for k in ("status", "reason_code", "total_usd", "amount_usd", "monthly_rent_usd", "decision", "reviewer"):
            if k in payload:
                summary_items.append(f"{k}={payload[k]}")
        detail_str = f" ({', '.join(summary_items)})" if summary_items else ""
        text = f"[WorldModel Event #{event_id}] {event_type} on {entity_id}{detail_str}."

        prov = Provenance(
            source_id=f"world_event:{event_id}",
            document_id=f"case:{case_id}",
            metadata={
                "event_id": event_id,
                "case_id": case_id,
                "entity_id": entity_id,
                "event_type": event_type
            }
        )
        hmem.store.add(
            tier="working",
            text=text,
            tags=["world_event", event_type, f"case:{case_id}"],
            domain="property_management",
            provenance=prov,
            confidence=0.92
        )
    except Exception as exc:
        logger.debug(f"Non-blocking H-MEM event hook notice: {exc}")


def get_events(case_id: str, limit: Optional[int] = None, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all chronological events for a case."""
    with db() as conn:
        limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
        rows = conn.execute(
            f"""SELECT id, entity_id, canonical_id, event_type, payload, version, caused_by, created_at
               FROM world_events WHERE case_id = %s ORDER BY id ASC{limit_sql}""",
            (case_id,)
        ).fetchall()
    return [
        {
            'id': r[0],
            'entity_id': r[1],
            'canonical_id': r[2] or canonical_id('entity', r[1]),
            'event_type': r[3],
            'payload': r[4],
            'version': r[5] or 1,
            'caused_by': r[6] or [],
            'created_at': r[7].isoformat() if hasattr(r[7], 'isoformat') else str(r[7])
        }
        for r in rows
    ]

def replay_events_for_state(conn, case_id: str) -> Dict[str, Any]:
    """Pure deterministic state fold/replay over all events for this case."""
    rows = conn.execute(
        """SELECT id, canonical_id, event_type, payload, version, created_at
           FROM world_events WHERE case_id = %s ORDER BY id ASC""",
        (case_id,)
    ).fetchall()

    state = {
        'case_id': case_id,
        'canonical_id': canonical_id('case', case_id),
        'version': 0,
        'status': 'uninitialized',
        'requires_human_approval': True,
        'currency': 'USD',
        'invoice_cents': 0,
        'verified_paid_cents': 0,
        'difference_cents': 0,
        'verified_bank_ids': [],
        'unmatched_payment_ids': [],
        'unmatched_bank_ids': [],
        'entities': {
            'lease': canonical_id('lease', case_id),
        },
        'approval': {'state': 'pending', 'note': None, 'updated_at': None},
        'recommendation': None,
        'narrative': None,
        'work_order_deductions_flagged': False,
        'last_run_id': None,
        'event_count': len(rows),
        'last_updated': None
    }

    for row in rows:
        eid, cid, etype, payload, ver, created_at = row
        state['version'] = max(state['version'], ver or 0)
        state['last_updated'] = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
        
        if etype in ('opened', 'case_opened'):
            state['status'] = 'opened'
            state['last_run_id'] = payload.get('run_id')
        elif etype in ('finance_calculated', 'finance_normalized'):
            state['status'] = payload.get('status', state['status'])
            state['currency'] = payload.get('currency', state['currency'])
            state['invoice_cents'] = payload.get('invoice_cents', state['invoice_cents']) or 0
            state['verified_paid_cents'] = payload.get('verified_paid_cents', state['verified_paid_cents']) or 0
            state['difference_cents'] = payload.get('difference_cents', state['difference_cents']) or 0
            state['verified_bank_ids'] = payload.get('verified_bank_ids', [])
            state['unmatched_payment_ids'] = payload.get('unmatched_payment_ids', [])
            state['unmatched_bank_ids'] = payload.get('unmatched_bank_ids', [])
        elif etype in ('investigation_completed',):
            state['status'] = payload.get('status', state['status'])
            state['requires_human_approval'] = payload.get('requires_approval', True)
            state['last_run_id'] = payload.get('run_id', state['last_run_id'])
            if 'recommendation' in payload:
                state['recommendation'] = payload['recommendation']
            if 'narrative' in payload:
                state['narrative'] = payload['narrative']
        elif etype in ('approval_recorded', 'approved', 'rejected'):
            state['approval'] = {
                'state': payload.get('state', 'pending'),
                'note': payload.get('note'),
                'reviewer': payload.get('reviewer', 'Property Manager'),
                'updated_at': state['last_updated']
            }
            if payload.get('state') == 'approved' and state['status'] != 'needs_review':
                state['requires_human_approval'] = False

    return state

def get_latest_state(case_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch the latest derived state projection (from cache or computed)."""
    with db() as conn:
        row = conn.execute(
            "SELECT state, version, updated_at FROM derived_states WHERE case_id = %s",
            (case_id,)
        ).fetchone()
        if row:
            state = row[0]
            if isinstance(state, str):
                state = json.loads(state)
            return state
        # Fallback to computing live
        return replay_events_for_state(conn, case_id)

def get_lineage(case_id: str) -> Dict[str, Any]:
    """Construct causal lineage Directed Acyclic Graph (DAG) for a case."""
    events = get_events(case_id)
    nodes = []
    edges = []
    
    for ev in events:
        nodes.append({
            'id': str(ev['id']),
            'label': f"{ev['event_type']} (v{ev['version']})",
            'type': ev['event_type'],
            'canonical_id': ev['canonical_id'],
            'time': ev['created_at'],
            'payload': ev['payload']
        })
        for parent_id in ev.get('caused_by', []):
            edges.append({
                'source': str(parent_id),
                'target': str(ev['id']),
                'type': 'caused_by'
            })
            
    # Also link chronological sequential steps if no explicit caused_by exists
    if len(edges) == 0 and len(nodes) > 1:
        for i in range(len(nodes) - 1):
            edges.append({
                'source': nodes[i]['id'],
                'target': nodes[i+1]['id'],
                'type': 'sequential'
            })
            
    return {
        'case_id': case_id,
        'canonical_id': canonical_id('case', case_id),
        'nodes': nodes,
        'edges': edges,
        'total_events': len(nodes)
    }

def build_agent_context(case_id: str, question: str = "") -> Dict[str, Any]:
    """Context Builder: aggregates canonical entities, latest state, and grounded records."""
    state = get_latest_state(case_id)
    with db() as conn:
        lease = conn.execute(
            """SELECT lease_id, property_id, unit, address, tenant1, tenant2,
                      contract_date, move_in_date, monthly_rent_usd, security_deposit_usd
               FROM lease_records WHERE lease_id = %s""",
            (case_id,)
        ).fetchone()
        
        work_orders = conn.execute(
            """SELECT work_order_id, category, description, priority, status,
                      estimated_cost_usd, technician_notes, reported_date
               FROM work_order_records WHERE lease_id = %s ORDER BY reported_date DESC""",
            (case_id,)
        ).fetchall()

    lease_info = {}
    if lease:
        lease_info = {
            'lease_id': lease[0],
            'canonical_id': canonical_id('lease', lease[0]),
            'property_id': lease[1],
            'property_canonical_id': canonical_id('property', lease[1]),
            'unit': lease[2],
            'address': lease[3],
            'tenants': [lease[4]] + ([lease[5]] if lease[5] else []),
            'tenant_canonical_ids': [canonical_id('tenant', lease[4])] + ([canonical_id('tenant', lease[5])] if lease[5] else []),
            'contract_date': str(lease[6]),
            'move_in_date': str(lease[7]),
            'monthly_rent_usd': float(lease[8]),
            'security_deposit_usd': float(lease[9])
        }

    wo_list = [
        {
            'work_order_id': w[0],
            'canonical_id': canonical_id('work_order', w[0]),
            'category': w[1],
            'description': w[2],
            'priority': w[3],
            'status': w[4],
            'estimated_cost_usd': float(w[5]),
            'technician_notes': w[6],
            'reported_date': str(w[7])
        }
        for w in work_orders
    ]

    return {
        'case_id': case_id,
        'canonical_id': canonical_id('case', case_id),
        'question': question,
        'latest_state': state,
        'lease': lease_info,
        'work_orders': wo_list,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
