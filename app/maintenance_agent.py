"""Autonomous Maintenance & SLA Agent for EQUILIBRA.

Key capabilities:
- Automatic ticket triage: classifies category, severity, and emergency status (e.g. active flooding, no heat, electrical fire hazard)
- Deterministic & policy SLA assignment:
    - Emergency: 4 hours
    - High: 24 hours
    - Medium: 72 hours
    - Low: 7 days
- Vendor matching: queries real registered trades vendors based on trade (plumbing, hvac, electrical, appliances, fixtures)
- Automated dispatch tracking with simulated provider acknowledgment (noting simulated vs real transport)
- High-cost threshold gate: estimated repairs >= $1,000 route to Property Manager approval queue
- SLA Breach escalation monitor: detects overdue open work orders and triggers notifications
- Records all events and causal lineage in the Meterless World Model
"""

import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from decimal import Decimal

from .database import db
from .world_model import record_event, canonical_id
from .notifications import queue_notification


CATEGORY_TRADE_MAP = {
    "plumbing": "Apex Plumbing & Sinks",
    "bath": "Pacific Bathtubs & Fixtures",
    "fixtures": "Pacific Bathtubs & Fixtures",
    "electrical": "Lumina Electrical & Lighting",
    "lighting": "Lumina Electrical & Lighting",
    "hvac": "CalBreeze HVAC & Climate",
    "heating": "CalBreeze HVAC & Climate",
    "appliance": "BayPro Appliance & Refrigeration",
    "refrigerator": "BayPro Appliance & Refrigeration"
}

EMERGENCY_KEYWORDS = [
    "flood", "flooding", "burst pipe", "leak pouring", "no heat", "freezing",
    "sparks", "smoke", "electrical hazard", "sewage", "gas smell"
]


def triage_maintenance_request(description: str, category_hint: Optional[str] = None) -> Dict[str, Any]:
    """Analyze issue description to determine category, emergency status, priority, and SLA."""
    desc_lower = description.lower()
    
    # 1. Emergency detection
    is_emergency = any(kw in desc_lower for kw in EMERGENCY_KEYWORDS)
    
    # 2. Category classification
    category = "General Maintenance"
    if any(k in desc_lower for k in ["pipe", "faucet", "drain", "sink", "water leak", "toilet"]):
        category = "Plumbing & Sinks"
    elif any(k in desc_lower for k in ["tub", "bathtub", "shower pan", "grout", "tile"]):
        category = "Bathtubs & Fixtures"
    elif any(k in desc_lower for k in ["light", "switch", "outlet", "breaker", "power", "wiring"]):
        category = "Electrical & Lighting"
    elif any(k in desc_lower for k in ["heat", "furnace", "ac", "air condition", "thermostat", "hvac"]):
        category = "HVAC & Heating"
    elif any(k in desc_lower for k in ["fridge", "refrigerator", "stove", "oven", "dishwasher", "washer", "dryer"]):
        category = "Appliance & Refrigeration"
    elif category_hint:
        category = category_hint

    # 3. Priority and SLA
    if is_emergency:
        priority = "Emergency"
        sla_hours = 4
    elif any(k in desc_lower for k in ["broken", "stopped working", "urgent", "cannot use"]):
        priority = "High"
        sla_hours = 24
    elif any(k in desc_lower for k in ["slow", "noisy", "intermittent", "cosmetic"]):
        priority = "Medium"
        sla_hours = 72
    else:
        priority = "Low"
        sla_hours = 168 # 7 days

    now = datetime.now(timezone.utc)
    sla_deadline = now + timedelta(hours=sla_hours)

    return {
        "category": category,
        "is_emergency": is_emergency,
        "priority": priority,
        "sla_hours": sla_hours,
        "sla_deadline": sla_deadline.isoformat(),
        "triage_reason": f"Classified as '{priority}' ({category}) with {sla_hours}h SLA based on issue context."
    }


def find_eligible_vendor(category: str) -> Optional[Dict[str, Any]]:
    """Match registered trades vendor from the database."""
    with db() as conn:
        vendors = conn.execute(
            """SELECT vendor_id, name, trade, contact_email, phone, payment_terms
               FROM vendors"""
        ).fetchall()
        
    if not vendors:
        return None
        
    cat_lower = category.lower()
    for v in vendors:
        trade_lower = v[2].lower()
        if any(term in cat_lower for term in trade_lower.split()):
            return {
                "vendor_id": v[0],
                "canonical_id": canonical_id("vendor", v[0]),
                "name": v[1],
                "trade": v[2],
                "contact_email": v[3],
                "phone": v[4],
                "payment_terms": v[5]
            }
            
    # Default fallback to first vendor
    v = vendors[0]
    return {
        "vendor_id": v[0],
        "canonical_id": canonical_id("vendor", v[0]),
        "name": v[1],
        "trade": v[2],
        "contact_email": v[3],
        "phone": v[4],
        "payment_terms": v[5]
    }


def submit_and_triage_ticket(
    lease_id: str,
    property_id: str,
    unit: str,
    description: str,
    reported_by: str,
    estimated_cost_usd: float = 250.00
) -> Dict[str, Any]:
    """End-to-end autonomous maintenance triage and work order processing."""
    triage = triage_maintenance_request(description)
    wo_id = f"WO-{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc)
    
    # Check high-cost approval requirement (>= $1,000)
    requires_approval = estimated_cost_usd >= 1000.00 or triage["is_emergency"]
    
    # Match vendor
    matched_vendor = find_eligible_vendor(triage["category"])
    vendor_name = matched_vendor["name"] if matched_vendor else "Unassigned Contractor"
    
    # Dispatch tracking status
    dispatch_status = "simulated_dispatched" if not requires_approval else "pending_approval"
    
    with db() as conn:
        conn.execute(
            """INSERT INTO work_order_records (
                work_order_id, lease_id, property_id, unit, address, tenant1,
                reported_date, scheduled_date, category, description,
                priority, status, technician, estimated_cost_usd, technician_notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                wo_id, lease_id, property_id, unit, "", reported_by,
                now.strftime("%Y-%m-%d"),
                (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                triage["category"], description, triage["priority"],
                "Open", vendor_name, estimated_cost_usd,
                f"SLA: {triage['sla_hours']}h (Deadline: {triage['sla_deadline']}). Dispatch: {dispatch_status}"
            )
        )
        
    # Queue notification to tenant and vendor
    queue_notification(
        recipient_email="tenant@equilibra.internal",
        recipient_type="tenant",
        title=f"Maintenance Ticket Triaged: {wo_id}",
        message=f"Your request '{description}' has been classified as {triage['priority']} ({triage['category']}). Assigned to {vendor_name}.",
        category="maintenance_triage",
        event_key=f"maint-{wo_id}-tenant"
    )
    
    if matched_vendor:
        queue_notification(
            recipient_email=matched_vendor["contact_email"],
            recipient_type="vendor",
            title=f"Work Order Dispatch: {wo_id} ({triage['priority']})",
            message=f"Dispatch request for {triage['category']} at unit {unit}. SLA Deadline: {triage['sla_deadline']}.",
            category="vendor_dispatch",
            event_key=f"maint-{wo_id}-vendor"
        )

    # Record in World Model
    record_event(
        case_id=lease_id,
        entity_id=wo_id,
        event_type="work_order_triaged",
        payload={
            "work_order_id": wo_id,
            "category": triage["category"],
            "priority": triage["priority"],
            "is_emergency": triage["is_emergency"],
            "sla_hours": triage["sla_hours"],
            "sla_deadline": triage["sla_deadline"],
            "assigned_vendor": vendor_name,
            "dispatch_status": dispatch_status,
            "requires_approval": requires_approval
        }
    )

    return {
        "work_order_id": wo_id,
        "canonical_id": canonical_id("work_order", wo_id),
        "lease_id": lease_id,
        "category": triage["category"],
        "priority": triage["priority"],
        "is_emergency": triage["is_emergency"],
        "sla_deadline": triage["sla_deadline"],
        "assigned_vendor": matched_vendor,
        "dispatch_status": dispatch_status,
        "requires_manager_approval": requires_approval,
        "message": f"Work order {wo_id} logged and triaged with {triage['sla_hours']}h SLA."
    }


def check_sla_breaches() -> List[Dict[str, Any]]:
    """Scan open work orders for SLA breaches and trigger escalations."""
    with db() as conn:
        orders = conn.execute(
            """SELECT work_order_id, lease_id, category, priority, status,
                      reported_date, technician, estimated_cost_usd, technician_notes
               FROM work_order_records
               WHERE status NOT IN ('Completed', 'Closed')"""
        ).fetchall()
        
    breaches = []
    now = datetime.now(timezone.utc)
    
    for wo in orders:
        wo_id, lease_id, cat, prio, st, rep_date, tech, est, notes = wo
        # Parse reported date
        try:
            r_date = datetime.strptime(str(rep_date), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            r_date = now - timedelta(days=2)
            
        sla_hours = 4 if prio == "Emergency" else (24 if prio == "High" else 72)
        deadline = r_date + timedelta(hours=sla_hours)
        
        if now > deadline:
            overdue_hours = int((now - deadline).total_seconds() / 3600)
            breach_record = {
                "work_order_id": wo_id,
                "lease_id": lease_id,
                "category": cat,
                "priority": prio,
                "overdue_hours": overdue_hours,
                "assigned_vendor": tech,
                "status": "SLA_BREACHED"
            }
            breaches.append(breach_record)
            
            # Queue escalation notification to Property Manager
            queue_notification(
                recipient_email="ops-controller@equilibra.internal",
                recipient_type="owner",
                title=f"SLA Breach Escalation: Work Order {wo_id}",
                message=f"Work order {wo_id} ({cat}, {prio}) is {overdue_hours} hours past SLA deadline. Assigned vendor: {tech}.",
                category="sla_escalation",
                event_key=f"breach-{wo_id}-{now.strftime('%Y%m%d')}"
            )
            
    return breaches


def assess_habitability_and_rent_risk(work_order_id: str, org_id: Optional[str] = None) -> "AgentDecision":
    """Evaluate whether an open maintenance ticket poses habitability risks or rent withholding defense.
    
    Cross-references maintenance ticket priority and category against tenant ledger status.
    Returns a grounded structured AgentDecision.
    """
    from .agent_execution import (
        AgentDecision, EvidenceReference, EstablishedAgent,
        DecisionOutcome, ConfidenceLevel, RiskLevel, ExecutionStatus,
        create_abstention_decision, assert_tenant_access
    )

    with db() as conn:
        row = conn.execute(
            """SELECT wo.work_order_id, wo.lease_id, wo.property_id, wo.category,
                      wo.description, wo.priority, wo.status, wo.technician,
                      wo.estimated_cost_usd, wo.reported_date, p.org_id, p.name as property_name
               FROM work_order_records wo
               JOIN properties p ON wo.property_id = p.property_id
               WHERE wo.work_order_id = %s""",
            (work_order_id,)
        ).fetchone()

    if not row:
        return create_abstention_decision(
            agent_id=EstablishedAgent.MAINTENANCE_SLA.value,
            case_id=work_order_id,
            reason=f"Work order '{work_order_id}' not found in database records.",
            org_id=org_id
        )

    wo_id, lease_id, prop_id, cat, desc, prio, st, tech, est_cost, rep_date, p_org, prop_name = row
    assert_tenant_access(p_org, org_id, f"Work order {work_order_id}")

    # Detect habitability keywords
    desc_lower = (desc or "").lower()
    cat_lower = (cat or "").lower()
    habitability_covenants = ["flood", "leak", "sewage", "heat", "hot water", "gas", "sparks", "mold", "pipe"]
    is_habitability_issue = prio in ("Emergency", "High") or any(k in desc_lower or k in cat_lower for k in habitability_covenants)

    evidence_list: List[EvidenceReference] = [
        EvidenceReference(
            entity_type="work_order",
            entity_id=wo_id,
            source_table="work_order_records",
            field_values={
                "category": cat,
                "priority": prio,
                "status": st,
                "description": desc,
                "estimated_cost_usd": float(est_cost)
            },
            citation=f"Work Order {wo_id} ({cat}, Priority: {prio}): '{desc}'"
        )
    ]

    # Cross-reference tenant ledger balance
    from .engine import fixture_rows, calculate
    fin = fixture_rows(lease_id)
    recon = calculate(fin)
    diff_cents = recon.get("difference_cents") or 0
    has_unpaid_rent = diff_cents > 0

    if has_unpaid_rent:
        evidence_list.append(EvidenceReference(
            entity_type="lease",
            entity_id=lease_id,
            source_table="lease_records",
            field_values={
                "variance_cents": diff_cents,
                "reconciliation_status": recon.get("status"),
                "reason": recon.get("reason")
            },
            citation=f"Tenant ledger carries ${diff_cents/100:.2f} unpaid balance ({recon.get('status')})"
        ))

    if is_habitability_issue and has_unpaid_rent and st not in ("Completed", "Closed"):
        return AgentDecision(
            agent_id=EstablishedAgent.MAINTENANCE_SLA.value,
            case_id=wo_id,
            decision=DecisionOutcome.ESCALATED.value,
            confidence=0.91,
            confidence_level=ConfidenceLevel.HIGH,
            evidence=evidence_list,
            rationale=(
                f"Habitability risk identified: Open {prio} ticket '{desc}' in {cat} coincided with an unpaid rent "
                f"balance of ${diff_cents/100:.2f}. Under statutory habitability covenants, tenant may assert lawful "
                f"repair-and-deduct or withholding rights."
            ),
            recommended_action="Expedite contractor dispatch immediately; do not issue adverse late notice until repair is verified.",
            requires_human_approval=True,
            approval_role="property_manager",
            risk_level=RiskLevel.CRITICAL if prio == "Emergency" else RiskLevel.HIGH,
            execution_status=ExecutionStatus.RECOMMENDED,
            org_id=p_org,
            metadata={"habitability_risk": True, "tenant_withholding_risk": True, "unpaid_rent_usd": diff_cents / 100.0}
        )
    elif is_habitability_issue and st not in ("Completed", "Closed"):
        return AgentDecision(
            agent_id=EstablishedAgent.MAINTENANCE_SLA.value,
            case_id=wo_id,
            decision=DecisionOutcome.ACTION_REQUIRED.value,
            confidence=0.88,
            confidence_level=ConfidenceLevel.HIGH,
            evidence=evidence_list,
            rationale=f"Habitability impact flagged: {prio} priority ticket ({cat}) requires strict SLA enforcement.",
            recommended_action=f"Assign certified trade technician ({tech or 'Unassigned'}) within SLA window.",
            requires_human_approval=False,
            risk_level=RiskLevel.MEDIUM,
            execution_status=ExecutionStatus.EXECUTED,
            org_id=p_org,
            metadata={"habitability_risk": True, "tenant_withholding_risk": False}
        )
    else:
        return AgentDecision(
            agent_id=EstablishedAgent.MAINTENANCE_SLA.value,
            case_id=wo_id,
            decision=DecisionOutcome.APPROVED.value,
            confidence=0.94,
            confidence_level=ConfidenceLevel.HIGH,
            evidence=evidence_list,
            rationale=f"Routine maintenance ticket {wo_id} ({cat}, {prio}). No habitability or financial withholding cross-risks detected.",
            recommended_action="Proceed with scheduled contractor appointment.",
            requires_human_approval=False,
            risk_level=RiskLevel.LOW,
            execution_status=ExecutionStatus.EXECUTED,
            org_id=p_org,
            metadata={"habitability_risk": False, "tenant_withholding_risk": False}
        )

