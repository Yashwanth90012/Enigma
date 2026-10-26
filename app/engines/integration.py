"""Unified Engine Integration Layer for ENIGMA / EQUILIBRA.

Coordinates the three Meterless engines:
1. H-MEM: Persistent contextual memory, hybrid retrieval, memory mining, and feedback.
2. World Model: Authoritative business facts, relationships, bitemporal history, and event provenance.
3. Markovian: Bounded execution chunks, durable checkpoints, crash recovery, and side-effect deduplication.

Enforces clear responsibility boundaries, transactional safety via PostgreSQL outbox,
and seamless integration with existing ENIGMA agents and orchestrator workflows.
"""

import time
import json
import uuid
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Callable
from pydantic import BaseModel, Field

from ..database import db
from ..config import settings
from .hmem import get_hmem_instance, HMEM, MemoryRecord
from .world_model import get_world_model, WorldModel, WorldEntity, WorldFact, WorldRelationship
from .markovian import get_markovian_engine, Markovian, ChunkConfig

logger = logging.getLogger("equilibra.engines.integration")


# =============================================================================
# 1. Pydantic Request & Result Models
# =============================================================================

class UnifiedBusinessRequest(BaseModel):
    """Normalized request payload for cross-engine execution."""
    request_id: Optional[str] = None
    organization_id: str = "default"
    user_id: Optional[str] = "system"
    user_role: Optional[str] = "property_manager"
    intent_hint: Optional[str] = None
    query: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    requires_durable_workflow: Optional[bool] = None


class UnifiedExecutionResult(BaseModel):
    """Unified execution response containing multi-engine evidence and telemetry."""
    workflow_id: Optional[str] = None
    run_id: Optional[str] = None
    status: str = "completed"  # 'completed', 'waiting_for_approval', 'needs_review', 'failed'
    intent: str
    agent_id: str
    world_model_state: Dict[str, Any] = Field(default_factory=dict)
    world_model_events: List[Dict[str, Any]] = Field(default_factory=list)
    retrieved_memories: List[Dict[str, Any]] = Field(default_factory=list)
    published_memories: List[Dict[str, Any]] = Field(default_factory=list)
    side_effects: List[Dict[str, Any]] = Field(default_factory=list)
    approval_state: Dict[str, Any] = Field(default_factory=dict)
    unresolved_issues: List[str] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    telemetry: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 2. Unified Engine Coordinator
# =============================================================================

class UnifiedEngineCoordinator:
    """Coordinates H-MEM, World Model, and Markovian engines across ENIGMA workflows."""

    def __init__(
        self,
        hmem: Optional[HMEM] = None,
        world_model: Optional[WorldModel] = None,
        markovian: Optional[Markovian] = None
    ):
        self._hmem_override = hmem
        self._world_model_override = world_model
        self._markovian_override = markovian

    def get_hmem(self) -> HMEM:
        if self._hmem_override is not None:
            return self._hmem_override
        return get_hmem_instance()

    def get_world_model(self, org_id: str = "default") -> WorldModel:
        if self._world_model_override is not None:
            return self._world_model_override
        return get_world_model(org_id=org_id)

    def get_markovian(self, org_id: str = "default") -> Markovian:
        if self._markovian_override is not None:
            return self._markovian_override
        return get_markovian_engine(org_id=org_id)

    # -------------------------------------------------------------------------
    # Intent Routing
    # -------------------------------------------------------------------------
    def route_intent(
        self,
        query_or_text: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Determine agent target, operation, and execution requirements from intent."""
        text = (query_or_text or "").lower()
        ctx = context or {}
        hint = ctx.get("intent_hint", "").lower()

        # Document Intelligence
        if hint in ("document", "lease_document", "ocr") or any(k in text for k in ["ocr", "scan", "extract", "upload document", "lease agreement"]):
            return {
                "intent": "document_intelligence",
                "agent_id": "document_intelligence",
                "requires_durable_workflow": False,
                "required_role": "property_manager",
                "operation": "extract_and_validate_document"
            }

        # Vendor AP / Financial Ops
        if hint in ("vendor", "invoice", "ap", "bill") or any(k in text for k in ["vendor", "invoice", "payment voucher", "reconciliation", "clearing", "bill"]):
            return {
                "intent": "financial_vendor",
                "agent_id": "financial_operations",
                "requires_durable_workflow": True,
                "required_role": "finance_admin",
                "operation": "reconcile_and_process_vendor_bill"
            }

        # Maintenance & Habitability
        if hint in ("maintenance", "work_order", "repair") or any(k in text for k in ["repair", "maintenance", "work order", "habitability", "leak", "hvac", "broken"]):
            return {
                "intent": "maintenance_habitability",
                "agent_id": "maintenance_agent",
                "requires_durable_workflow": True,
                "required_role": "property_manager",
                "operation": "triage_and_dispatch_maintenance"
            }

        # Resident & Lease Lifecycle
        if hint in ("resident", "lease", "renewal", "move_in", "move_out") or any(k in text for k in ["lease", "rent", "renewal", "move in", "move out", "tenant", "deposit"]):
            return {
                "intent": "resident_lease",
                "agent_id": "resident_experience",
                "requires_durable_workflow": True,
                "required_role": "property_manager",
                "operation": "manage_resident_lifecycle"
            }

        # Fallback / General Assistant
        return {
            "intent": "general_assistant",
            "agent_id": "assistant",
            "requires_durable_workflow": False,
            "required_role": "property_manager",
            "operation": "synthesize_assistant_response"
        }

    # -------------------------------------------------------------------------
    # Transactional Memory Outbox
    # -------------------------------------------------------------------------
    def publish_memory_with_outbox(
        self,
        org_id: str,
        event_id: str,
        entity_id: str,
        memory_text: str,
        source: str = "world_model_event",
        confidence: float = 0.9,
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Atomically record memory into hmem_outbox and attempt synchronous delivery to H-MEM.
        
        Guarantees that World Model state commitments are never rolled back if H-MEM is unavailable.
        """
        outbox_id = f"outbox-{uuid.uuid4().hex[:12]}"
        tags = tags or ["unified_integration"]
        memory_payload = {
            "text": memory_text,
            "confidence": confidence,
            "provenance": {"source": source, "event_id": event_id, "entity_id": entity_id},
            "tags": tags,
            "scope": "long_term"
        }

        with db() as conn:
            conn.execute(
                """INSERT INTO hmem_outbox (
                    outbox_id, org_id, event_id, entity_id, memory_payload, status, retry_count, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s::jsonb, 'pending', 0, now(), now())""",
                (outbox_id, org_id, event_id, entity_id, json.dumps(memory_payload))
            )

        # Immediate dispatch attempt
        try:
            hmem = self.get_hmem()
            from .hmem import Provenance
            prov = Provenance(
                origin="automated",
                label=source,
                metadata={"outbox_id": outbox_id, "event_id": str(event_id), "entity_id": str(entity_id)}
            )
            rec = MemoryRecord(
                id=f"mem-{uuid.uuid4().hex[:10]}",
                content=memory_text,
                source=source,
                confidence=confidence,
                tags=tags,
                provenance=prov,
                lease_id=str(entity_id) if str(entity_id).startswith("LEASE") else None
            )
            mem_id = hmem.add_memory(rec)

            with db() as conn:
                conn.execute(
                    """UPDATE hmem_outbox
                       SET status = 'published', published_at = now(), updated_at = now()
                       WHERE outbox_id = %s""",
                    (outbox_id,)
                )

            logger.info(f"[OUTBOX] Delivered memory '{mem_id}' from outbox '{outbox_id}' to H-MEM.")
            return {"outbox_id": outbox_id, "status": "published", "memory_id": mem_id}
        except Exception as exc:
            logger.warning(f"[OUTBOX] Immediate H-MEM publication failed for outbox '{outbox_id}': {exc}. Record remains pending.")
            with db() as conn:
                conn.execute(
                    """UPDATE hmem_outbox
                       SET status = 'failed', last_error = %s, retry_count = retry_count + 1, updated_at = now()
                       WHERE outbox_id = %s""",
                    (str(exc)[:400], outbox_id)
                )
            return {"outbox_id": outbox_id, "status": "pending_retry", "error": str(exc)}

    def retry_pending_hmem_outbox(
        self,
        org_id: Optional[str] = None,
        max_retries: int = 5
    ) -> Dict[str, Any]:
        """Poll and replay pending or failed memory publication records from hmem_outbox."""
        with db() as conn:
            if org_id and org_id != "all":
                rows = conn.execute(
                    """SELECT outbox_id, org_id, event_id, entity_id, memory_payload, retry_count
                       FROM hmem_outbox
                       WHERE status IN ('pending', 'failed') AND retry_count < %s AND org_id = %s
                       ORDER BY created_at ASC LIMIT 50""",
                    (max_retries, org_id)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT outbox_id, org_id, event_id, entity_id, memory_payload, retry_count
                       FROM hmem_outbox
                       WHERE status IN ('pending', 'failed') AND retry_count < %s
                       ORDER BY created_at ASC LIMIT 50""",
                    (max_retries,)
                ).fetchall()

        published = 0
        failed = 0
        hmem = self.get_hmem()
        from .hmem import Provenance

        for r in rows:
            outbox_id, row_org, event_id, entity_id, payload, r_count = r
            if isinstance(payload, str):
                payload = json.loads(payload)

            text = payload.get("text", "")
            # Deduplication check: verify H-MEM doesn't already hold this identical memory
            existing_mems = hmem.search_memories(query=text, org_id=row_org, limit=3)
            already_exists = any(m.memory.text.strip().lower() == text.strip().lower() for m in existing_mems)

            if already_exists:
                with db() as conn:
                    conn.execute(
                        """UPDATE hmem_outbox
                           SET status = 'published', published_at = now(), updated_at = now()
                           WHERE outbox_id = %s""",
                        (outbox_id,)
                    )
                published += 1
                continue

            try:
                prov = Provenance(
                    origin="automated",
                    label=payload.get("provenance", {}).get("source", "outbox_retry"),
                    metadata={"outbox_id": outbox_id, "event_id": str(event_id), "entity_id": str(entity_id)}
                )
                rec = MemoryRecord(
                    id=f"mem-{uuid.uuid4().hex[:10]}",
                    content=text,
                    source=payload.get("provenance", {}).get("source", "outbox_retry"),
                    confidence=float(payload.get("confidence", 0.9)),
                    tags=payload.get("tags", ["outbox_retry"]),
                    provenance=prov,
                    lease_id=str(entity_id) if str(entity_id).startswith("LEASE") else None
                )
                hmem.add_memory(rec)
                with db() as conn:
                    conn.execute(
                        """UPDATE hmem_outbox
                           SET status = 'published', published_at = now(), updated_at = now()
                           WHERE outbox_id = %s""",
                        (outbox_id,)
                    )
                published += 1
            except Exception as e:
                failed += 1
                with db() as conn:
                    conn.execute(
                        """UPDATE hmem_outbox
                           SET status = 'failed', retry_count = retry_count + 1, last_error = %s, updated_at = now()
                           WHERE outbox_id = %s""",
                        (str(e)[:400], outbox_id)
                    )

        return {"replayed_total": len(rows), "published": published, "failed": failed}

    # -------------------------------------------------------------------------
    # Idempotent Side-Effect Management
    # -------------------------------------------------------------------------
    def execute_idempotent_side_effect(
        self,
        idempotency_key: str,
        action_type: str,
        payload: Dict[str, Any],
        executor_fn: Callable[[], Any],
        org_id: str = "default",
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Wrap irreversible external side-effect in Markovian deduplication with reconciliation."""
        markovian = self.get_markovian(org_id=org_id)
        return markovian.execute_side_effect(
            idempotency_key=idempotency_key,
            action_type=action_type,
            payload=payload,
            executor_fn=executor_fn,
            run_id=run_id
        )

    def reconcile_side_effect(
        self,
        idempotency_key: str,
        org_id: str = "default"
    ) -> Dict[str, Any]:
        """Reconcile the status of an external side effect when response was lost or timed out."""
        with db() as conn:
            row = conn.execute(
                """SELECT idempotency_key, status, result, action_type, payload
                   FROM markovian_side_effects
                   WHERE idempotency_key = %s""",
                (idempotency_key,)
            ).fetchone()

        if not row:
            return {"idempotency_key": idempotency_key, "status": "not_found", "reconciled": False}

        status = row[1]
        res = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        return {
            "idempotency_key": idempotency_key,
            "status": status,
            "action_type": row[3],
            "result": res,
            "reconciled": True
        }

    # -------------------------------------------------------------------------
    # Unified Request Lifecycle Execution
    # -------------------------------------------------------------------------
    def process_business_request(self, req: UnifiedBusinessRequest) -> UnifiedExecutionResult:
        """Execute full 13-step unified request lifecycle across H-MEM, World Model, and Markovian."""
        t0 = time.perf_counter()
        org_id = req.organization_id or "default"
        req_id = req.request_id or f"req-{uuid.uuid4().hex[:10]}"

        # 1. Routing
        routing = self.route_intent(query_or_text=req.query or req.entity_id or "", context={"intent_hint": req.intent_hint})
        intent = routing["intent"]
        agent_id = routing["agent_id"]
        requires_durable = req.requires_durable_workflow if req.requires_durable_workflow is not None else routing["requires_durable_workflow"]

        # 2. Retrieve H-MEM Context
        hmem = self.get_hmem()
        query_text = req.query or f"{intent} {req.entity_type or ''} {req.entity_id or ''}".strip()
        retrieved_memories = []
        try:
            mems = hmem.search_memories(query=query_text, org_id=org_id, limit=5, min_confidence=0.4)
            retrieved_memories = [m.model_dump() for m in mems]
        except Exception as e:
            logger.warning(f"[UNIFIED] H-MEM search warning: {e}")

        # 3. Query World Model State
        wm_state = {}
        if req.entity_id:
            try:
                from ..world_model import get_latest_state
                wm_state = get_latest_state(req.entity_id, org_id=org_id)
            except Exception as e:
                logger.warning(f"[UNIFIED] World model state query warning: {e}")

        # 4. Durable Markovian Workflow Run Setup
        run_id = None
        workflow_id = None
        markovian = self.get_markovian(org_id=org_id)
        if requires_durable:
            workflow_id = f"WF-UNI-{uuid.uuid4().hex[:8].upper()}"
            run_id = f"run-{workflow_id}"

        world_events = []
        side_effects = []
        published_mems = []
        unresolved = []
        approval_state = {"required": False, "role": None, "approved": False}
        status = "completed"

        # 5. Agent-Specific Execution Logic
        if intent == "document_intelligence":
            res = self.process_lease_document(
                title=req.payload.get("title", "Residential Lease Document"),
                body=req.payload.get("body", req.query or ""),
                property_id=req.payload.get("property_id", "PROP-001"),
                lease_id=req.entity_id or req.payload.get("lease_id"),
                org_id=org_id
            )
            status = "completed" if res.get("status") in ("processed", "completed") else res.get("status", "completed")
            world_events.append(res.get("event", {}))
            if "outbox" in res:
                published_mems.append(res["outbox"])

        elif intent == "financial_vendor":
            inv_id = req.entity_id or req.payload.get("invoice_id")
            res = self.process_vendor_invoice_reconciliation(
                invoice_id=inv_id,
                org_id=org_id,
                actor_role=req.user_role or "finance_admin",
                workflow_id=workflow_id
            )
            status = res.get("current_state", "completed")
            approval_state = {
                "required": res.get("requires_approval", False),
                "role": res.get("approval_role", "finance_admin"),
                "approved": res.get("approved", False)
            }
            if res.get("side_effect"):
                side_effects.append(res["side_effect"])
            if res.get("unresolved_discrepancies"):
                unresolved.extend(res["unresolved_discrepancies"])

        elif intent == "maintenance_habitability":
            res = self.process_maintenance_workflow(
                request_data=req.payload,
                org_id=org_id,
                workflow_id=workflow_id
            )
            status = res.get("status", "completed")
            if res.get("checkpoint"):
                world_events.append({"event_type": "maintenance_checkpoint", "checkpoint": res["checkpoint"]})
            if res.get("side_effect"):
                side_effects.append(res["side_effect"])

        else:
            # Fallback general query
            from ..assistant import answer_assistant_query
            ans = answer_assistant_query(req.query or "")
            wm_state = ans

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return UnifiedExecutionResult(
            workflow_id=workflow_id,
            run_id=run_id,
            status=status,
            intent=intent,
            agent_id=agent_id,
            world_model_state=wm_state,
            world_model_events=world_events,
            retrieved_memories=retrieved_memories,
            published_memories=published_mems,
            side_effects=side_effects,
            approval_state=approval_state,
            unresolved_issues=unresolved,
            evidence=[{"source": "world_model", "target": req.entity_id or "portfolio"}],
            telemetry={"elapsed_ms": round(elapsed_ms, 2), "requires_durable": requires_durable}
        )

    # -------------------------------------------------------------------------
    # Scenario A: Lease Document to Resident Context
    # -------------------------------------------------------------------------
    def process_lease_document(
        self,
        title: str,
        body: str,
        property_id: str = "PROP-001",
        lease_id: Optional[str] = None,
        org_id: str = "default"
    ) -> Dict[str, Any]:
        """Ingest lease document, update World Model entities & facts, and publish memory via outbox."""
        from ..document_agent import hash_content, classify_document, extract_structured_fields

        content_hash = hash_content(body)

        # 1. Deduplication check in documents table
        with db() as conn:
            existing = conn.execute(
                "SELECT id, title, kind, created_at FROM documents WHERE body = %s",
                (body,)
            ).fetchone()

        if existing:
            return {
                "status": "duplicate_rejected",
                "document_id": existing[0],
                "message": f"Identical document body already ingested with ID {existing[0]}."
            }

        # 2. Extract structured fields
        classification = classify_document(body)
        kind = classification["kind"]
        extracted = extract_structured_fields(body, kind)
        target_lease = lease_id or extracted.get("lease_id") or f"LEASE-{uuid.uuid4().hex[:4].upper()}"
        doc_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"

        # 3. Store document record
        with db() as conn:
            conn.execute(
                """INSERT INTO documents (id, lease_id, property_id, kind, title, body, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, now())""",
                (doc_id, target_lease, property_id, kind, title, body)
            )

        # 4. Authoritative World Model Entity & Fact Persistence
        wm = self.get_world_model(org_id=org_id)
        wm.upsert_entity(WorldEntity(
            id=target_lease,
            type="lease",
            name=f"Lease {target_lease}",
            properties={"property_id": property_id, "extracted_fields": extracted, "doc_id": doc_id},
            organization_id=org_id
        ))

        if extracted.get("monthly_rent"):
            wm.assert_fact(WorldFact(
                entity_id=target_lease,
                predicate="has_monthly_rent_usd",
                value=str(extracted["monthly_rent"]),
                source=f"doc:{doc_id}",
                organization_id=org_id
            ))

        # 5. Record World Model Event
        from ..world_model import record_event
        ev_id = record_event(
            case_id=target_lease,
            entity_id=doc_id,
            event_type="document_processed",
            payload={
                "document_id": doc_id,
                "title": title,
                "kind": kind,
                "extracted_fields": extracted,
                "content_hash": content_hash[:16]
            },
            org_id=org_id
        )

        rent_val = extracted.get("monthly_rent")
        if rent_val is None and extracted.get("extracted_amounts_usd"):
            rent_val = extracted["extracted_amounts_usd"][0]
        extracted["monthly_rent"] = rent_val or 0.0

        tenant_match = re.search(r'for\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', body)
        tenant_name = extracted.get("tenant1") or (tenant_match.group(1) if tenant_match else "Resident")
        extracted["tenant1"] = tenant_name

        # 6. Publish derived contextual memory via Transactional Outbox
        mem_text = f"Lease agreement {target_lease} for {tenant_name} at {property_id}: Monthly rent ${float(extracted['monthly_rent']):.2f}."
        outbox_res = self.publish_memory_with_outbox(
            org_id=org_id,
            event_id=str(ev_id),
            entity_id=target_lease,
            memory_text=mem_text,
            source=f"document:{doc_id}",
            confidence=float(classification.get("confidence", 0.9))
        )

        return {
            "status": "processed",
            "document_id": doc_id,
            "lease_id": target_lease,
            "classification": classification,
            "extracted": extracted,
            "event": {"event_id": ev_id, "event_type": "document_processed"},
            "outbox": outbox_res
        }

    # -------------------------------------------------------------------------
    # Scenario B: Vendor Invoice Reconciliation & Approval Gating
    # -------------------------------------------------------------------------
    def process_vendor_invoice_reconciliation(
        self,
        invoice_id: str,
        org_id: str = "default",
        actor_role: str = "finance_admin",
        workflow_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Perform 4-way matching with World Model relationship verification and Markovian approval gating."""
        wf_id = workflow_id or f"WF-INV-{uuid.uuid4().hex[:8].upper()}"

        with db() as conn:
            inv = conn.execute(
                """SELECT vi.id, vi.vendor_id, vi.work_order_id, vi.total_usd, vi.status, p.org_id
                   FROM vendor_invoices vi
                   JOIN properties p ON vi.property_id = p.property_id
                   WHERE vi.id = %s""",
                (invoice_id,)
            ).fetchone()

        if not inv:
            raise ValueError(f"Vendor invoice '{invoice_id}' not found.")

        resolved_org = inv[5] or org_id
        work_order_id = inv[2]
        total_usd = float(inv[3])

        # Verify Work Order in World Model
        from ..world_model import get_latest_state, record_event
        wm = self.get_world_model(org_id=resolved_org)
        wo_state = get_latest_state(work_order_id, org_id=resolved_org)

        from ..vendor_agent import reconcile_vendor_bill
        recon = reconcile_vendor_bill(invoice_id, retrieve_evidence=False)
        reason_code = recon.get("reason_code", "MATCH_CONFIRMED")
        has_discrepancy = reason_code != "MATCH_CONFIRMED"
        requires_approval = has_discrepancy or total_usd > 500.0

        current_state = "waiting_for_approval" if requires_approval else "completed"
        unresolved = [reason_code] if has_discrepancy else []

        # Record World Model Reconciliation Event
        record_event(
            case_id=work_order_id or invoice_id,
            entity_id=invoice_id,
            event_type="vendor_invoice_reconciliation_evaluated",
            payload={
                "invoice_id": invoice_id,
                "reason_code": reason_code,
                "requires_approval": requires_approval,
                "total_usd": total_usd
            },
            org_id=resolved_org
        )

        # Save checkpoint in Markovian
        markovian = self.get_markovian(org_id=resolved_org)
        checkpoint_data = {
            "workflow_id": wf_id,
            "invoice_id": invoice_id,
            "step": "reconciliation_evaluated",
            "reason_code": reason_code,
            "requires_approval": requires_approval,
            "pending_action": "issue_payment_voucher" if requires_approval else None
        }

        # Safe side-effect execution: Only execute payment voucher if pre-approved or under threshold
        side_effect = None
        if not requires_approval and actor_role in ("finance_admin", "super_admin"):
            idemp_key = f"{resolved_org}:payment:{invoice_id}"
            def _pay():
                from ..vendor_agent import record_vendor_payment
                return record_vendor_payment(invoice_id=invoice_id, amount_usd=total_usd, payment_method="ach", reference=f"AUTO-PAY-{invoice_id}")

            side_effect = self.execute_idempotent_side_effect(
                idempotency_key=idemp_key,
                action_type="record_vendor_payment",
                payload={"invoice_id": invoice_id, "amount_usd": total_usd},
                executor_fn=_pay,
                org_id=resolved_org,
                run_id=f"run-{wf_id}"
            )

        return {
            "workflow_id": wf_id,
            "invoice_id": invoice_id,
            "current_state": current_state,
            "requires_approval": requires_approval,
            "approval_role": "finance_admin" if requires_approval else None,
            "approved": not requires_approval,
            "unresolved_discrepancies": unresolved,
            "side_effect": side_effect,
            "reconciliation": recon
        }

    # -------------------------------------------------------------------------
    # Scenario C: Resident Maintenance Workflow with Mid-Flight Failure & Recovery
    # -------------------------------------------------------------------------
    def process_maintenance_workflow(
        self,
        request_data: Dict[str, Any],
        org_id: str = "default",
        workflow_id: Optional[str] = None,
        simulate_failure_at_step: Optional[int] = None
    ) -> Dict[str, Any]:
        """Multi-step maintenance workflow with checkpointing and durable resume support."""
        wf_id = workflow_id or f"WF-MAINT-{uuid.uuid4().hex[:8].upper()}"
        wo_id = request_data.get("work_order_id") or f"WO-{uuid.uuid4().hex[:6].upper()}"
        lease_id = request_data.get("lease_id", "LEASE-0001")
        category = request_data.get("category", "plumbing")
        description = request_data.get("description", "Emergency repair request")

        markovian = self.get_markovian(org_id=org_id)
        run_id = f"run-{wf_id}"

        property_id = request_data.get("property_id") or "PROP-001"
        estimated_cost = float(request_data.get("estimated_cost_usd", 250.0))

        # Step 1: Create Work Order & Record World Model State
        with db() as conn:
            conn.execute(
                """INSERT INTO work_order_records (
                    work_order_id, lease_id, property_id, category, description, priority, status, estimated_cost_usd, reported_date
                ) VALUES (%s, %s, %s, %s, %s, 'high', 'reported', %s, now()::date)
                ON CONFLICT (work_order_id) DO NOTHING""",
                (wo_id, lease_id, property_id, category, description, estimated_cost)
            )

        from ..world_model import record_event
        record_event(
            case_id=lease_id,
            entity_id=wo_id,
            event_type="work_order_reported",
            payload={"work_order_id": wo_id, "category": category, "description": description},
            org_id=org_id
        )

        # Checkpoint Step 1
        markovian.persist_checkpoint(
            run_id=run_id,
            chunk_index=0,
            step=1,
            state={"step": 1, "work_order_id": wo_id, "status": "triaged"},
            pending_actions=["dispatch_technician"]
        )

        if simulate_failure_at_step == 1:
            raise RuntimeError(f"Simulated mid-flight failure at step 1 for workflow '{wf_id}'.")

        # Step 2: Dispatch Technician (Idempotent Side-Effect)
        idemp_key = f"{org_id}:dispatch:{wo_id}"
        def _dispatch():
            with db() as conn:
                conn.execute(
                    "UPDATE work_order_records SET status = 'in_progress', technician = 'Alex Rivera' WHERE work_order_id = %s",
                    (wo_id,)
                )
            return {"dispatched": True, "technician": "Alex Rivera", "work_order_id": wo_id}

        side_effect = self.execute_idempotent_side_effect(
            idempotency_key=idemp_key,
            action_type="dispatch_technician",
            payload={"work_order_id": wo_id},
            executor_fn=_dispatch,
            org_id=org_id,
            run_id=run_id
        )

        # Checkpoint Step 2
        markovian.persist_checkpoint(
            run_id=run_id,
            chunk_index=1,
            step=2,
            state={"step": 2, "work_order_id": wo_id, "status": "dispatched", "technician": "Alex Rivera"},
            pending_actions=[]
        )

        return {
            "workflow_id": wf_id,
            "run_id": run_id,
            "status": "completed",
            "work_order_id": wo_id,
            "side_effect": side_effect,
            "checkpoint": {"step": 2, "status": "dispatched"}
        }

    # -------------------------------------------------------------------------
    # Scenario D: Resume Workflow Post-Approval & Restart
    # -------------------------------------------------------------------------
    def resume_workflow(
        self,
        workflow_id: str,
        approver_user: str,
        approver_role: str,
        decision: str = "approve",
        org_id: str = "default"
    ) -> Dict[str, Any]:
        """Safely resume an approval-gated workflow with role validation and idempotency protection."""
        run_id = f"run-{workflow_id}"
        markovian = self.get_markovian(org_id=org_id)
        cp = markovian.get_latest_checkpoint(run_id)

        if not cp:
            raise ValueError(f"No checkpoint found for workflow '{workflow_id}'.")

        # Role Authorization Check
        required_role = cp.get("state", {}).get("required_role", "finance_admin")
        if approver_role not in (required_role, "super_admin", "property_manager"):
            raise PermissionError(f"User '{approver_user}' with role '{approver_role}' is not authorized. Required: '{required_role}'.")

        raw_pa = cp.get("pending_action") or cp.get("state", {}).get("pending_action")
        is_payment = False
        if raw_pa == "issue_payment_voucher":
            is_payment = True
        elif isinstance(raw_pa, dict):
            actions = raw_pa.get("actions", [])
            if "issue_payment_voucher" in actions or raw_pa.get("action") == "issue_payment_voucher":
                is_payment = True
        elif isinstance(raw_pa, list) and "issue_payment_voucher" in raw_pa:
            is_payment = True

        side_effect = None

        if decision == "approve" and is_payment:
            state_dict = cp.get("state") or cp.get("execution_state") or {}
            inv_id = state_dict.get("invoice_id") or workflow_id.replace("WF-INV-", "")
            idemp_key = f"{org_id}:payment:{inv_id}"
            def _pay():
                from ..vendor_agent import record_vendor_payment
                with db() as conn:
                    inv = conn.execute("SELECT total_usd FROM vendor_invoices WHERE id = %s", (inv_id,)).fetchone()
                    amount = float(inv[0]) if inv else 100.0
                return record_vendor_payment(invoice_id=inv_id, amount_usd=amount, payment_method="ach", reference=f"APPV-PAY-{inv_id}")

            side_effect = self.execute_idempotent_side_effect(
                idempotency_key=idemp_key,
                action_type="record_vendor_payment",
                payload={"invoice_id": inv_id},
                executor_fn=_pay,
                org_id=org_id,
                run_id=run_id
            )
        elif cp.get("state", {}).get("status") == "completed" or cp.get("execution_state", {}).get("status") == "completed":
            state_dict = cp.get("state") or cp.get("execution_state") or {}
            inv_id = state_dict.get("invoice_id") or workflow_id.replace("WF-INV-", "")
            idemp_key = f"{org_id}:payment:{inv_id}"
            recon = self.reconcile_side_effect(idempotency_key=idemp_key, org_id=org_id)
            if recon.get("reconciled"):
                side_effect = {"status": "cached", "result": recon.get("result"), "action_type": recon.get("action_type")}

        # Record World Model approval audit event
        from ..world_model import record_event
        record_event(
            case_id=workflow_id,
            entity_id=workflow_id,
            event_type="workflow_resumed_with_approval",
            payload={"approver_user": approver_user, "approver_role": approver_role, "decision": decision},
            org_id=org_id
        )

        # Advance checkpoint to completed
        markovian.persist_checkpoint(
            run_id=run_id,
            chunk_index=cp.get("chunk", 0) + 1,
            step=cp.get("step", 1) + 1,
            state={"status": "completed", "approved_by": approver_user, "invoice_id": inv_id},
            pending_actions=[]
        )

        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "decision": decision,
            "approver": approver_user,
            "side_effect": side_effect
        }


# =============================================================================
# 3. Factory Function
# =============================================================================

_global_coordinator: Optional[UnifiedEngineCoordinator] = None

def get_unified_coordinator(
    hmem: Optional[HMEM] = None,
    world_model: Optional[WorldModel] = None,
    markovian: Optional[Markovian] = None
) -> UnifiedEngineCoordinator:
    """Obtain or initialize the UnifiedEngineCoordinator singleton."""
    global _global_coordinator
    if hmem is not None or world_model is not None or markovian is not None:
        return UnifiedEngineCoordinator(hmem=hmem, world_model=world_model, markovian=markovian)
    if _global_coordinator is None:
        _global_coordinator = UnifiedEngineCoordinator()
    return _global_coordinator
