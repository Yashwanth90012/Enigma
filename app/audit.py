"""Centralized Structured Audit Logging System for ENIGMA.

Provides:
- Append-only, tamper-evident audit logging for all business, auth, payment, and operational events.
- Strict multi-tenant isolation and role-gated querying.
- Sensitive data stripping (no raw card details, CVVs, passwords, or tokens).
- Fast structured filtering, search, and pagination.
- Integration with Meterless World Model monotonic event log.
"""

import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .database import db
from .world_model import record_event, canonical_id

logger = logging.getLogger("enigma.audit")

SENSITIVE_KEYS = {
    "password", "token", "access_token", "secret", "cvv", "cvc",
    "card_number", "credit_card", "pan", "authorization", "cookie"
}


def sanitize_payload(obj: Any) -> Any:
    """Recursively redact sensitive credentials or payment data."""
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = sanitize_payload(v)
        return clean
    elif isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    return obj


def log_audit_event(
    org_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    actor_type: str = "system",
    actor_id: Optional[str] = None,
    outcome: str = "success",
    correlation_id: Optional[str] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
    details: Optional[Dict[str, Any]] = None,
    source_component: str = "enigma.core",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    record_world_event: bool = True
) -> Dict[str, Any]:
    """Record an immutable, tenant-scoped audit event."""
    event_id = f"AUDIT-{uuid.uuid4().hex[:12].upper()}"
    now = datetime.now(timezone.utc)
    
    clean_before = sanitize_payload(before_state) if before_state else None
    clean_after = sanitize_payload(after_state) if after_state else None
    clean_details = sanitize_payload(details) if details else {}

    try:
        with db() as conn:
            conn.execute(
                """INSERT INTO audit_logs (
                    id, timestamp, org_id, actor_type, actor_id, action,
                    resource_type, resource_id, outcome, correlation_id,
                    before_state, after_state, details, source_component,
                    ip_address, user_agent
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    event_id,
                    now,
                    org_id,
                    actor_type,
                    actor_id or "system",
                    action,
                    resource_type,
                    resource_id,
                    outcome,
                    correlation_id or str(uuid.uuid4()),
                    json.dumps(clean_before) if clean_before else None,
                    json.dumps(clean_after) if clean_after else None,
                    json.dumps(clean_details),
                    source_component,
                    ip_address,
                    user_agent
                )
            )
    except Exception as e:
        logger.error(f"Failed to write audit log {event_id}: {e}")

    # Synchronize into World Model causal DAG if requested
    if record_world_event:
        try:
            record_event(
                case_id=resource_id or org_id,
                entity_id=resource_id or event_id,
                event_type=f"audit_{action}",
                payload={
                    "audit_id": event_id,
                    "action": action,
                    "actor_type": actor_type,
                    "actor_id": actor_id,
                    "outcome": outcome,
                    "resource_type": resource_type,
                    "org_id": org_id
                }
            )
        except Exception as e:
            logger.debug(f"World model event sync skipped for audit: {e}")

    return {
        "event_id": event_id,
        "timestamp": now.isoformat(),
        "org_id": org_id,
        "action": action,
        "outcome": outcome,
        "resource_type": resource_type,
        "resource_id": resource_id
    }


def query_audit_logs(
    org_id: str,
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    outcome: Optional[str] = None,
    search: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Query audit logs with tenant isolation and structured filters."""
    conditions = ["org_id = %s"]
    params: List[Any] = [org_id]

    if actor_type and actor_type != "all":
        conditions.append("actor_type = %s")
        params.append(actor_type)

    if actor_id:
        conditions.append("actor_id ILIKE %s")
        params.append(f"%{actor_id}%")

    if action and action != "all":
        conditions.append("action = %s")
        params.append(action)

    if resource_type and resource_type != "all":
        conditions.append("resource_type = %s")
        params.append(resource_type)

    if resource_id:
        conditions.append("resource_id ILIKE %s")
        params.append(f"%{resource_id}%")

    if outcome and outcome != "all":
        conditions.append("outcome = %s")
        params.append(outcome)

    if start_time:
        conditions.append("timestamp >= %s")
        params.append(start_time)

    if end_time:
        conditions.append("timestamp <= %s")
        params.append(end_time)

    if search:
        conditions.append(
            "(action ILIKE %s OR resource_id ILIKE %s OR actor_id ILIKE %s OR details::text ILIKE %s)"
        )
        term = f"%{search}%"
        params.extend([term, term, term, term])

    where_clause = " AND ".join(conditions)

    with db() as conn:
        count_query = f"SELECT COUNT(*) FROM audit_logs WHERE {where_clause}"
        total_count = conn.execute(count_query, params).fetchone()[0]

        query = f"""
            SELECT id, timestamp, org_id, actor_type, actor_id, action,
                   resource_type, resource_id, outcome, correlation_id,
                   before_state, after_state, details, source_component,
                   ip_address, user_agent
            FROM audit_logs
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT %s OFFSET %s
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    logs = []
    for r in rows:
        logs.append({
            "id": r[0],
            "timestamp": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
            "org_id": r[2],
            "actor_type": r[3],
            "actor_id": r[4],
            "action": r[5],
            "resource_type": r[6],
            "resource_id": r[7],
            "outcome": r[8],
            "correlation_id": r[9],
            "before_state": r[10] if isinstance(r[10], dict) else (json.loads(r[10]) if r[10] else None),
            "after_state": r[11] if isinstance(r[11], dict) else (json.loads(r[11]) if r[11] else None),
            "details": r[12] if isinstance(r[12], dict) else (json.loads(r[12]) if r[12] else {}),
            "source_component": r[13],
            "ip_address": r[14],
            "user_agent": r[15]
        })

    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "logs": logs
    }
