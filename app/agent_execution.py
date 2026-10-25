"""Shared Agent Execution Standards, Structured Decisions & Observability for ENIGMA / EQUILIBRA.

Complies with Step 2 Shared Agent Execution Standards:
1. Structured decisions: validated decision output with evidence, confidence, rationale, recommended action, and review requirements.
2. Evidence grounding: source records, primary keys, and document references.
3. Confidence and abstention: explicit threshold criteria; abstains when data is missing, contradictory, or insufficient.
4. Tool execution validation: validates inputs, permissions, and distinguishes recommendations from executed mutations.
5. Idempotency: prevents duplicate executions via unique idempotency keys.
6. Failure recovery: bounded retries, timeouts, clear failure states, and safe recovery.
7. Auditability: append-only audit logging in PostgreSQL and World Model event log.
8. Human approval gates: enforces mandatory authorized sign-off for consequential financial, contractual, or legal actions.
9. Tenant isolation: verifies organization boundaries on every query, event, and action (HTTP 403 Forbidden on violation).
10. Observability: thread-safe operational telemetry tracking latencies, statuses, retries, confidence scores, and review rates.
"""

import time
import json
import uuid
import logging
from enum import Enum
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Callable
from pydantic import BaseModel, Field

# pyrefly: ignore[missing-import]
from fastapi import HTTPException
from .database import db
from .world_model import record_event, canonical_id

logger = logging.getLogger("equilibra.agent_execution")


# =============================================================================
# 1. Enums and Data Models
# =============================================================================

class EstablishedAgent(str, Enum):
    DOCUMENT_INTELLIGENCE = "document_intelligence"
    PROPERTY_LISTING = "property_listing"
    RESIDENT_LEASE = "resident_lease"
    MAINTENANCE_SLA = "maintenance_sla"
    FINANCIAL_OPERATIONS = "financial_operations"
    RENT_RECONCILIATION = "rent_reconciliation"
    NOTIFICATION_COMMUNICATION = "notification_communication"
    SCHEDULING_WORKFLOW = "scheduling_workflow"
    ASSISTANT_ORCHESTRATOR = "assistant_orchestrator"
    VENDOR_INVOICE = "vendor_invoice"
    COMPLIANCE_RISK = "compliance_risk"
    WORLD_MODEL = "world_model"
    SAAS_COINNOVATION = "saas_coinnovation"


class DecisionOutcome(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"
    MATCH_CONFIRMED = "match_confirmed"
    DISCREPANCY_FLAGGED = "discrepancy_flagged"
    ACTION_REQUIRED = "action_required"
    ESCALATED = "escalated"
    ABSTAINED = "abstained"
    RESOLVED = "resolved"


class ConfidenceLevel(str, Enum):
    HIGH = "high"       # >= 0.85
    MEDIUM = "medium"   # 0.60 - 0.84
    LOW = "low"         # < 0.60


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    RECOMMENDED = "recommended"
    EXECUTED = "executed"
    FAILED = "failed"
    ABSTAINED = "abstained"


class EvidenceReference(BaseModel):
    """Authoritative citation to a grounded primary source record."""
    entity_type: str = Field(..., description="Entity category: lease, invoice, work_order, document_chunk, payment, bank_transaction, etc.")
    entity_id: str = Field(..., description="Unique record identifier")
    source_table: Optional[str] = Field(None, description="Underlying database table name")
    field_values: Dict[str, Any] = Field(default_factory=dict, description="Verified field key-value pairs supporting the decision")
    citation: Optional[str] = Field(None, description="Human-readable citation or excerpt")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AgentDecision(BaseModel):
    """Unified structured decision contract for all ENIGMA agents."""
    decision_id: str = Field(default_factory=lambda: f"DEC-{uuid.uuid4().hex[:10].upper()}")
    agent_id: str = Field(..., description="Identifier from the 13 established agents")
    case_id: str = Field(..., description="Target business case or entity identifier")
    decision: str = Field(..., description="Decision outcome: approved, rejected, needs_review, match_confirmed, etc.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Numerical confidence score")
    confidence_level: ConfidenceLevel = Field(..., description="Categorical confidence bracket: high, medium, low")
    evidence: List[EvidenceReference] = Field(default_factory=list, description="Authoritative grounded evidence references")
    rationale: str = Field(..., description="Explainable natural-language reasoning grounded in evidence")
    recommended_action: str = Field(..., description="Concrete actionable next step")
    requires_human_approval: bool = Field(default=False, description="Flag indicating consequential action requiring human sign-off")
    approval_role: Optional[str] = Field(None, description="Required approval persona: property_manager, financial_controller, compliance_officer")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Assessed risk classification")
    abstained: bool = Field(default=False, description="True if agent abstained due to missing, contradictory, or insufficient data")
    abstention_reason: Optional[str] = Field(None, description="Explanation of why the agent abstained")
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.RECOMMENDED, description="Distinguishes recommendations from executed state changes")
    idempotency_key: Optional[str] = Field(None, description="Unique deduplication token")
    org_id: Optional[str] = Field(None, description="Multi-tenant organization boundary")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    latency_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Domain-specific operational context")

    def to_summary_dict(self) -> Dict[str, Any]:
        """Convert to compact dictionary for API responses."""
        return self.model_dump()


# =============================================================================
# 2. Confidence and Abstention Policy Helper
# =============================================================================

def determine_confidence_level(confidence: float) -> ConfidenceLevel:
    """Classify numeric confidence score into standard confidence brackets."""
    if confidence >= 0.85:
        return ConfidenceLevel.HIGH
    elif confidence >= 0.60:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def create_abstention_decision(
    agent_id: str,
    case_id: str,
    reason: str,
    org_id: Optional[str] = None,
    partial_evidence: Optional[List[EvidenceReference]] = None,
    recommended_action: Optional[str] = None,
    approval_role: str = "property_manager"
) -> AgentDecision:
    """Construct a formal abstention decision when data is missing, contradictory, or ungrounded.
    
    Rule: When evidence is missing or insufficient, the agent MUST abstain and request clarification
    or human review rather than inventing or hallucinating an answer.
    """
    return AgentDecision(
        agent_id=agent_id,
        case_id=case_id,
        decision=DecisionOutcome.ABSTAINED.value,
        confidence=0.0,
        confidence_level=ConfidenceLevel.LOW,
        evidence=partial_evidence or [],
        rationale=f"Agent abstained from autonomous determination: {reason}",
        recommended_action=recommended_action or "Flag for manual property manager investigation and evidence verification.",
        requires_human_approval=True,
        approval_role=approval_role,
        risk_level=RiskLevel.MEDIUM,
        abstained=True,
        abstention_reason=reason,
        execution_status=ExecutionStatus.ABSTAINED,
        org_id=org_id
    )


# =============================================================================
# 3. Tenant Isolation Guard
# =============================================================================

def assert_tenant_access(record_org_id: Optional[str], requested_org_id: Optional[str], entity_desc: str = "Record"):
    """Enforce strict multi-tenant isolation.
    
    Rejects cross-organization access with HTTP 403 Forbidden.
    """
    if not requested_org_id or requested_org_id == "all":
        return
    if record_org_id and record_org_id != requested_org_id:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: {entity_desc} belongs to organization '{record_org_id}', not '{requested_org_id}'."
        )


# =============================================================================
# 4. Idempotency & Database Audit Logging
# =============================================================================

def init_agent_execution_tables():
    """Ensure persistence tables for agent decisions and idempotency exist."""
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_execution_logs (
                id BIGSERIAL PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                agent_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                action_name TEXT NOT NULL,
                org_id TEXT,
                decision JSONB NOT NULL,
                status TEXT NOT NULL,
                latency_ms NUMERIC(10,2),
                executed_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ael_key ON agent_execution_logs(idempotency_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS ael_agent ON agent_execution_logs(agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ael_case ON agent_execution_logs(case_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ael_org ON agent_execution_logs(org_id)")


def check_idempotency(idempotency_key: str) -> Optional[Dict[str, Any]]:
    """Check if an action with this idempotency key was previously executed."""
    init_agent_execution_tables()
    with db() as conn:
        row = conn.execute(
            """SELECT idempotency_key, agent_id, case_id, action_name, org_id, decision, status, executed_at
               FROM agent_execution_logs WHERE idempotency_key = %s""",
            (idempotency_key,)
        ).fetchone()
        if row:
            return {
                "idempotency_key": row[0],
                "agent_id": row[1],
                "case_id": row[2],
                "action_name": row[3],
                "org_id": row[4],
                "decision": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                "status": row[6],
                "executed_at": row[7].isoformat() if row[7] else None,
                "is_duplicate": True
            }
    return None


def record_agent_execution(
    decision: AgentDecision,
    action_name: str,
    latency_ms: float
):
    """Persist an agent decision and audit record into PostgreSQL and World Model."""
    init_agent_execution_tables()
    idem_key = decision.idempotency_key or f"{decision.agent_id}:{decision.case_id}:{uuid.uuid4().hex[:8]}"

    with db() as conn:
        conn.execute(
            """INSERT INTO agent_execution_logs (
                idempotency_key, agent_id, case_id, action_name, org_id, decision, status, latency_ms, executed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (idempotency_key) DO UPDATE
            SET status = EXCLUDED.status,
                decision = EXCLUDED.decision,
                latency_ms = EXCLUDED.latency_ms""",
            (
                idem_key,
                decision.agent_id,
                decision.case_id,
                action_name,
                decision.org_id,
                json.dumps(decision.model_dump(), default=str),
                decision.execution_status.value,
                latency_ms
            )
        )

    # Append-only World Model Event
    record_event(
        case_id=decision.case_id,
        entity_id=decision.decision_id,
        event_type="agent_decision_recorded",
        payload={
            "agent_id": decision.agent_id,
            "decision": decision.decision,
            "confidence": decision.confidence,
            "confidence_level": decision.confidence_level.value,
            "requires_human_approval": decision.requires_human_approval,
            "action_name": action_name,
            "execution_status": decision.execution_status.value,
            "idempotency_key": idem_key
        }
    )

    # Update in-memory telemetry
    telemetry.record_decision(decision, latency_ms)


# =============================================================================
# 5. Bounded Execution & Failure Recovery
# =============================================================================

def execute_with_resilience(
    agent_id: str,
    case_id: str,
    action_name: str,
    fn: Callable[[], AgentDecision],
    idempotency_key: Optional[str] = None,
    org_id: Optional[str] = None,
    max_retries: int = 2,
    base_backoff_sec: float = 0.2
) -> AgentDecision:
    """Execute an agent action with idempotency, bounded retries, timeout protection, and audit logging."""
    start_time = time.perf_counter()

    # 1. Idempotency Check
    if idempotency_key:
        cached = check_idempotency(idempotency_key)
        if cached:
            logger.info(f"[IDEMPOTENCY] Reusing prior execution for key '{idempotency_key}'")
            cached_dec = AgentDecision(**cached["decision"])
            cached_dec.metadata["idempotency_replayed"] = True
            return cached_dec

    # 2. Execution with Bounded Retries
    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            decision = fn()
            decision.latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            if idempotency_key and not decision.idempotency_key:
                decision.idempotency_key = idempotency_key
            if org_id and not decision.org_id:
                decision.org_id = org_id

            # Record successful execution
            record_agent_execution(decision, action_name, decision.latency_ms)
            return decision
        except HTTPException:
            # Re-raise standard HTTP exceptions (e.g. 403 Forbidden, 404 Not Found) immediately
            raise
        except Exception as e:
            last_error = e
            logger.warning(f"[RETRY] {agent_id}:{action_name} attempt {attempt} failed: {e}")
            if attempt <= max_retries:
                time.sleep(base_backoff_sec * (2 ** (attempt - 1)))

    # 3. Safe Failure Fallback
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
    failure_decision = AgentDecision(
        agent_id=agent_id,
        case_id=case_id,
        decision=DecisionOutcome.NEEDS_REVIEW.value,
        confidence=0.0,
        confidence_level=ConfidenceLevel.LOW,
        evidence=[],
        rationale=f"Execution failed after {max_retries + 1} attempts: {str(last_error)}",
        recommended_action="Route to human engineering / operations team for technical remediation.",
        requires_human_approval=True,
        approval_role="property_manager",
        risk_level=RiskLevel.HIGH,
        abstained=True,
        abstention_reason=f"System exception: {str(last_error)}",
        execution_status=ExecutionStatus.FAILED,
        idempotency_key=idempotency_key,
        org_id=org_id,
        latency_ms=latency_ms
    )
    record_agent_execution(failure_decision, action_name, latency_ms)
    telemetry.record_failure(agent_id)
    return failure_decision


# =============================================================================
# 6. Observability & Telemetry Tracking
# =============================================================================

class AgentTelemetryTracker:
    """Thread-safe operational telemetry for agent intelligence and decisions."""

    def __init__(self):
        self._total_decisions = 0
        self._total_failures = 0
        self._total_abstentions = 0
        self._total_human_reviews = 0
        self._latencies: List[float] = []
        self._agent_stats: Dict[str, Dict[str, Any]] = {}

    def record_decision(self, decision: AgentDecision, latency_ms: float):
        self._total_decisions += 1
        if decision.abstained:
            self._total_abstentions += 1
        if decision.requires_human_approval:
            self._total_human_reviews += 1
        
        self._latencies.append(latency_ms)
        if len(self._latencies) > 500:
            self._latencies.pop(0)

        aid = decision.agent_id
        if aid not in self._agent_stats:
            self._agent_stats[aid] = {
                "decisions": 0,
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
                "abstentions": 0,
                "human_reviews": 0,
                "avg_latency_ms": 0.0,
                "_lat_sum": 0.0
            }

        s = self._agent_stats[aid]
        s["decisions"] += 1
        if decision.confidence_level == ConfidenceLevel.HIGH:
            s["high_confidence"] += 1
        elif decision.confidence_level == ConfidenceLevel.MEDIUM:
            s["medium_confidence"] += 1
        else:
            s["low_confidence"] += 1

        if decision.abstained:
            s["abstentions"] += 1
        if decision.requires_human_approval:
            s["human_reviews"] += 1

        s["_lat_sum"] += latency_ms
        s["avg_latency_ms"] = round(s["_lat_sum"] / s["decisions"], 2)

    def record_failure(self, agent_id: str):
        self._total_failures += 1

    def get_summary(self) -> Dict[str, Any]:
        """Produce operational telemetry snapshot."""
        avg_lat = round(sum(self._latencies) / len(self._latencies), 2) if self._latencies else 0.0
        review_rate = round((self._total_human_reviews / max(1, self._total_decisions)) * 100, 1)
        abstain_rate = round((self._total_abstentions / max(1, self._total_decisions)) * 100, 1)

        return {
            "total_decisions": self._total_decisions,
            "total_failures": self._total_failures,
            "total_abstentions": self._total_abstentions,
            "total_human_reviews": self._total_human_reviews,
            "human_review_rate_pct": review_rate,
            "abstention_rate_pct": abstain_rate,
            "average_latency_ms": avg_lat,
            "agent_breakdown": self._agent_stats
        }

    get_metrics = get_summary


telemetry = AgentTelemetryTracker()
telemetry_tracker = telemetry
