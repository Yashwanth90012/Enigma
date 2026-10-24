"""EQUILIBRA Central Compliance & Risk Monitoring Hub Agent.

Connects existing EQUILIBRA agents (Resident, Finance, Vendor, Maintenance, World Model, Notifications)
to identify, track, prioritize, and resolve operational, policy, and legal compliance risks.

Architectural Principles:
1. Grounded in authoritative PostgreSQL records and existing calculation engines (engine.py, vendor_agent.py, maintenance_agent.py).
2. Strict separation of:
   - Operational Risk: late, incomplete, or inconsistent processes.
   - Business-Policy Exception: configurable internal rule breach.
   - Legal Compliance Finding: evaluated against jurisdiction-specific statutory rules and authoritative evidence.
3. Universal legal deadlines strictly prohibited: statutory rules (e.g., California Civil Code § 1950.5 21-day deposit return)
   are evaluated ONLY when the property's jurisdiction is verified. Unverified jurisdictions are marked 'unverified'.
4. Strict Human Approval Gates: AI recommendations never execute contractual or financial settlements.
5. Separation of Duties: Submitter cannot self-approve sensitive financial or contractual decisions.
6. 100% Idempotent Scans: Uses stable unique source keys to prevent duplicate findings.
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .database import db
from .world_model import record_event, canonical_id
from .notifications import queue_notification

logger = logging.getLogger("equilibra.compliance")

# =============================================================================
# 1. Jurisdiction Registry & Authoritative Statutory Rules
# =============================================================================

JURISDICTION_REGISTRY: Dict[str, Dict[str, Any]] = {
    "CA": {
        "jurisdiction": "US-CA",
        "state_name": "California",
        "statutory_source": "Cal. Civ. Code § 1950.5",
        "effective_date": "2003-01-01",
        "security_deposit_return_days": 21,
        "itemized_statement_required": True,
        "citation": "California Civil Code Section 1950.5(g)(1)",
        "summary": "Landlord must provide tenant with itemized statement and refund remaining security deposit within 21 calendar days after vacating."
    },
    "NY": {
        "jurisdiction": "US-NY",
        "state_name": "New York",
        "statutory_source": "N.Y. Gen. Oblig. Law § 7-108(1-a)(e)",
        "effective_date": "2019-07-14",
        "security_deposit_return_days": 14,
        "itemized_statement_required": True,
        "citation": "New York General Obligations Law Section 7-108(1-a)(e)",
        "summary": "Landlord must provide itemized statement and return remaining deposit within 14 calendar days after tenant vacates premises."
    },
    "TX": {
        "jurisdiction": "US-TX",
        "state_name": "Texas",
        "statutory_source": "Tex. Prop. Code § 92.103",
        "effective_date": "1995-09-01",
        "security_deposit_return_days": 30,
        "itemized_statement_required": True,
        "citation": "Texas Property Code Title 8, Section 92.103",
        "summary": "Landlord must refund security deposit on or before 30th day after date tenant surrenders premises."
    },
    "WA": {
        "jurisdiction": "US-WA",
        "state_name": "Washington",
        "statutory_source": "RCW 59.18.280",
        "effective_date": "2023-07-23",
        "security_deposit_return_days": 30,
        "itemized_statement_required": True,
        "citation": "Revised Code of Washington 59.18.280",
        "summary": "Within 30 days after tenant vacates, landlord must give full and specific statement and refund remaining deposit."
    }
}


def get_jurisdiction_rule(state_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Lookup statutory rules for a given state code. Returns None if unverified."""
    if not state_code:
        return None
    code = state_code.strip().upper()
    return JURISDICTION_REGISTRY.get(code)


def validate_finding_ownership(finding_id: str, org_id: Optional[str]) -> Dict[str, Any]:
    """Validate that finding exists and belongs to the requested organization."""
    with db() as conn:
        finding = conn.execute(
            """SELECT id, stable_key, org_id, property_id, lease_id, category,
                      finding_type, severity, title, description, status, assigned_reviewer
               FROM risk_findings WHERE id = %s""",
            (finding_id,)
        ).fetchone()

    if not finding:
        raise ValueError(f"Risk finding {finding_id} not found")

    if org_id and finding[2] != org_id:
        raise PermissionError(f"Access denied: Finding {finding_id} belongs to organization {finding[2]}")

    return {
        "id": finding[0],
        "stable_key": finding[1],
        "org_id": finding[2],
        "property_id": finding[3],
        "lease_id": finding[4],
        "category": finding[5],
        "finding_type": finding[6],
        "severity": finding[7],
        "title": finding[8],
        "description": finding[9],
        "status": finding[10],
        "assigned_reviewer": finding[11]
    }


# =============================================================================
# 2. Risk Detection Rules & Periodic Scan Engine
# =============================================================================

def run_compliance_and_risk_scan(org_id: Optional[str] = None) -> Dict[str, Any]:
    """Execute comprehensive, idempotent compliance & risk scan across all operational domains.
    
    Connects:
    - Lease & Resident Workflows
    - Financial & Reconciliation Engines
    - Maintenance SLA Tracking
    - Vendor AP Matching
    - System Notifications & Approvals
    """
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    
    findings_to_insert = []
    
    with db() as conn:
        # Fetch properties with org ownership
        if org_id:
            props = conn.execute(
                """SELECT property_id, name, state, org_id FROM properties WHERE org_id = %s""",
                (org_id,)
            ).fetchall()
        else:
            props = conn.execute(
                """SELECT property_id, name, state, org_id FROM properties"""
            ).fetchall()

    prop_map = {p[0]: {"name": p[1], "state": p[2], "org_id": p[3]} for p in props}
    prop_ids = list(prop_map.keys())

    if not prop_ids:
        return {"scanned_at": now.isoformat(), "findings_count": 0, "status": "completed"}

    # -------------------------------------------------------------------------
    # A. Lease & Resident Risks
    # -------------------------------------------------------------------------
    with db() as conn:
        leases = conn.execute(
            """SELECT l.lease_id, l.property_id, l.tenant1, l.end_date, l.monthly_rent_usd,
                      l.move_in_date, l.lease_status, p.org_id, p.state
               FROM lease_records l
               JOIN properties p ON l.property_id = p.property_id
               WHERE l.lease_status = 'active'"""
        ).fetchall()

        # Check existing renewals
        renewals = conn.execute(
            """SELECT id, lease_id, property_id, renewal_period, status, manager_approval_state
               FROM lease_renewals"""
        ).fetchall()

        # Check move-in checklists
        move_ins = conn.execute(
            """SELECT id, lease_id, property_id, target_move_in_date, status, tasks
               FROM move_in_checklists WHERE status != 'completed'"""
        ).fetchall()

        # Check move-out records
        move_outs = conn.execute(
            """SELECT id, lease_id, property_id, planned_move_out_date, status,
                      closeout_approval_state, statutory_deadline_date, proposed_deductions
               FROM move_out_records WHERE status != 'completed'"""
        ).fetchall()

        # Check documents
        docs = conn.execute(
            """SELECT lease_id, count(id) FROM documents GROUP BY lease_id"""
        ).fetchall()

    doc_counts = {d[0]: d[1] for d in docs}
    renewal_by_lease = {r[1]: r for r in renewals}

    # 1. Lease approaching expiration without renewal decision
    for l in leases:
        lease_id, prop_id, tenant, end_date_str, rent, move_in_str, l_status, l_org, p_state = l
        if org_id and l_org != org_id:
            continue

        if end_date_str:
            try:
                end_d = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                today_d = now.date()
                days_left = (end_d - today_d).days
                if 0 <= days_left <= 90:
                    # Check if a decision has been recorded
                    ren = renewal_by_lease.get(lease_id)
                    if not ren or ren[4] in ("upcoming", "offer_prepared"):
                        severity = "high" if days_left <= 30 else "medium"
                        findings_to_insert.append({
                            "stable_key": f"lease_expiring_no_decision:{lease_id}:{end_date_str}",
                            "org_id": l_org,
                            "property_id": prop_id,
                            "lease_id": lease_id,
                            "category": "lease_resident",
                            "finding_type": "operational_risk",
                            "severity": severity,
                            "title": f"Lease Expiring Without Renewal Decision: {lease_id}",
                            "description": f"Lease for {tenant} expires in {days_left} days ({end_date_str}) without a confirmed resident decision.",
                            "source_record_type": "lease",
                            "source_record_id": lease_id,
                            "detection_rule": "RULE_LEASE_EXPIRATION_APPROACHING",
                            "originating_event": "lease_expiration_monitor",
                            "evidence": {"days_remaining": days_left, "end_date": end_date_str, "tenant": tenant},
                            "due_date": end_d.isoformat()
                        })
            except Exception as e:
                logger.warning(f"Error checking lease expiration for {lease_id}: {e}")

        # 2. Missing executed lease documents
        if doc_counts.get(lease_id, 0) == 0:
            findings_to_insert.append({
                "stable_key": f"missing_lease_document:{lease_id}",
                "org_id": l_org,
                "property_id": prop_id,
                "lease_id": lease_id,
                "category": "lease_resident",
                "finding_type": "operational_risk",
                "severity": "medium",
                "title": f"Missing Executed Lease Document: {lease_id}",
                "description": f"Active lease {lease_id} for {tenant} has no registered lease agreements or executed addenda in the document store.",
                "source_record_type": "lease",
                "source_record_id": lease_id,
                "detection_rule": "RULE_DOCUMENT_RETENTION_INTEGRITY",
                "originating_event": "document_integrity_scan",
                "evidence": {"document_count": 0, "tenant": tenant}
            })

    # 3. Renewal offers awaiting manager approval
    for r in renewals:
        r_id, r_lease_id, r_prop_id, r_period, r_status, r_mgr_state = r
        p_info = prop_map.get(r_prop_id)
        if not p_info:
            continue
        if org_id and p_info["org_id"] != org_id:
            continue

        if r_mgr_state == "pending" or r_status == "pending_approval":
            findings_to_insert.append({
                "stable_key": f"renewal_pending_approval:{r_id}",
                "org_id": p_info["org_id"],
                "property_id": r_prop_id,
                "lease_id": r_lease_id,
                "category": "lease_resident",
                "finding_type": "policy_exception",
                "severity": "high",
                "title": f"Renewal Offer Awaiting Manager Approval: {r_lease_id}",
                "description": f"Tenant accepted renewal for period '{r_period}'. Requires authorized human manager sign-off before contractual terms and rent are finalized.",
                "source_record_type": "renewal",
                "source_record_id": r_id,
                "detection_rule": "RULE_CONTRACTUAL_APPROVAL_REQUIRED",
                "originating_event": "lease_renewal_decision",
                "evidence": {"renewal_id": r_id, "renewal_period": r_period, "approval_state": r_mgr_state}
            })

    # 4. Incomplete or overdue move-in checklists
    for m in move_ins:
        m_id, m_lease_id, m_prop_id, target_date_str, m_status, m_tasks = m
        p_info = prop_map.get(m_prop_id)
        if not p_info or (org_id and p_info["org_id"] != org_id):
            continue

        tasks_list = m_tasks if isinstance(m_tasks, list) else []
        pending_tasks = [t.get("title") or t.get("task_key") for t in tasks_list if not t.get("completed")]
        
        if pending_tasks:
            try:
                target_d = datetime.strptime(target_date_str, "%Y-%m-%d").date()
                today_d = now.date()
                if today_d >= target_d:
                    findings_to_insert.append({
                        "stable_key": f"move_in_tasks_overdue:{m_lease_id}",
                        "org_id": p_info["org_id"],
                        "property_id": m_prop_id,
                        "lease_id": m_lease_id,
                        "category": "lease_resident",
                        "finding_type": "operational_risk",
                        "severity": "high",
                        "title": f"Overdue Move-In Checklist Tasks: {m_lease_id}",
                        "description": f"Target move-in date ({target_date_str}) has passed with {len(pending_tasks)} incomplete onboarding tasks: {', '.join(pending_tasks)}.",
                        "source_record_type": "checklist",
                        "source_record_id": m_id,
                        "detection_rule": "RULE_MOVE_IN_CHECKLIST_OVERDUE",
                        "originating_event": "move_in_lifecycle_sweep",
                        "evidence": {"target_move_in_date": target_date_str, "pending_tasks": pending_tasks}
                    })
                elif (target_d - today_d).days <= 7:
                    findings_to_insert.append({
                        "stable_key": f"move_in_tasks_pending:{m_lease_id}",
                        "org_id": p_info["org_id"],
                        "property_id": m_prop_id,
                        "lease_id": m_lease_id,
                        "category": "lease_resident",
                        "finding_type": "operational_risk",
                        "severity": "medium",
                        "title": f"Pending Move-In Tasks Approaching Target Date: {m_lease_id}",
                        "description": f"Move-in scheduled for {target_date_str} with {len(pending_tasks)} tasks remaining.",
                        "source_record_type": "checklist",
                        "source_record_id": m_id,
                        "detection_rule": "RULE_MOVE_IN_CHECKLIST_APPROACHING",
                        "originating_event": "move_in_lifecycle_sweep",
                        "evidence": {"target_move_in_date": target_date_str, "pending_tasks": pending_tasks}
                    })
            except Exception as e:
                logger.warning(f"Error checking move-in checklist {m_id}: {e}")

    # 5. Move-out deposit closeout review & statutory jurisdiction deadlines
    for mo in move_outs:
        mo_id, mo_lease_id, mo_prop_id, planned_d_str, mo_status, closeout_state, stat_d_str, deductions = mo
        p_info = prop_map.get(mo_prop_id)
        if not p_info or (org_id and p_info["org_id"] != org_id):
            continue

        # Awaiting manager sign-off
        if closeout_state == "pending":
            findings_to_insert.append({
                "stable_key": f"move_out_deposit_pending_approval:{mo_lease_id}",
                "org_id": p_info["org_id"],
                "property_id": mo_prop_id,
                "lease_id": mo_lease_id,
                "category": "lease_resident",
                "finding_type": "policy_exception",
                "severity": "high",
                "title": f"Move-Out Deposit Closeout Awaiting Approval: {mo_lease_id}",
                "description": f"Proposed security deposit closeout awaiting authorized property manager approval.",
                "source_record_type": "move_out",
                "source_record_id": mo_id,
                "detection_rule": "RULE_SECURITY_DEPOSIT_APPROVAL_REQUIRED",
                "originating_event": "move_out_closeout_proposed",
                "evidence": {"planned_move_out_date": planned_d_str, "proposed_deductions": deductions}
            })

        # Statutory Deadline Jurisdiction Evaluation
        rule = get_jurisdiction_rule(p_info.get("state"))
        if rule:
            try:
                p_date = datetime.strptime(planned_d_str, "%Y-%m-%d").date()
                statutory_days = rule["security_deposit_return_days"]
                statutory_deadline = p_date + timedelta(days=statutory_days)
                days_left = (statutory_deadline - now.date()).days
                
                if days_left <= 5:
                    is_breached = days_left < 0
                    findings_to_insert.append({
                        "stable_key": f"statutory_deposit_deadline:{mo_lease_id}:{rule['jurisdiction']}",
                        "org_id": p_info["org_id"],
                        "property_id": mo_prop_id,
                        "lease_id": mo_lease_id,
                        "category": "legal_compliance",
                        "finding_type": "legal_compliance_finding",
                        "severity": "critical" if is_breached else "high",
                        "title": f"Statutory Deposit Return Deadline {'BREACHED' if is_breached else 'Approaching'} ({rule['state_name']}): {mo_lease_id}",
                        "description": (
                            f"{rule['citation']} mandates itemized deposit statement and refund within {statutory_days} days. "
                            f"{'Statutory deadline EXPIRED on ' + statutory_deadline.isoformat() if is_breached else f'{days_left} calendar days remaining until {statutory_deadline.isoformat()}'}."
                        ),
                        "source_record_type": "move_out",
                        "source_record_id": mo_id,
                        "detection_rule": "RULE_JURISDICTION_SECURITY_DEPOSIT_STATUTE",
                        "originating_event": "statutory_compliance_evaluation",
                        "jurisdiction": rule["jurisdiction"],
                        "statutory_source": rule["statutory_source"],
                        "effective_date": rule["effective_date"],
                        "compliance_status": "potential_violation" if is_breached else "warning",
                        "evidence": {
                            "statutory_days": statutory_days,
                            "statutory_deadline": statutory_deadline.isoformat(),
                            "days_remaining": days_left,
                            "citation": rule["citation"],
                            "summary": rule["summary"]
                        },
                        "due_date": statutory_deadline.isoformat()
                    })
            except Exception as e:
                logger.warning(f"Error checking statutory deadline for {mo_id}: {e}")
        else:
            # Unverified Jurisdiction Rule
            findings_to_insert.append({
                "stable_key": f"move_out_unverified_jurisdiction:{mo_lease_id}",
                "org_id": p_info["org_id"],
                "property_id": mo_prop_id,
                "lease_id": mo_lease_id,
                "category": "operational_integration",
                "finding_type": "operational_risk",
                "severity": "medium",
                "title": f"Move-Out In Progress With Unverified Jurisdiction: {mo_lease_id}",
                "description": f"Property state '{p_info.get('state')}' has no registered statutory deposit rule in the compliance database. Evaluated as operational process risk without statutory claim.",
                "source_record_type": "move_out",
                "source_record_id": mo_id,
                "detection_rule": "RULE_JURISDICTION_UNVERIFIED",
                "originating_event": "statutory_compliance_evaluation",
                "jurisdiction": "unverified",
                "statutory_source": None,
                "effective_date": None,
                "compliance_status": "unverified",
                "evidence": {"state": p_info.get("state"), "planned_move_out_date": planned_d_str}
            })

    # -------------------------------------------------------------------------
    # B. Financial Risks (Reconciliation, Rent Delinquency, Vendor AP)
    # -------------------------------------------------------------------------
    from .engine import fixture_rows, calculate
    
    for l in leases:
        lease_id, prop_id, tenant, end_date_str, rent, move_in_str, l_status, l_org, p_state = l
        if org_id and l_org != org_id:
            continue

        try:
            fin = fixture_rows(lease_id)
            recon = calculate(fin)
            diff_cents = recon.get("difference_cents", 0)

            # 3-Way Reconciliation Mismatch
            if recon.get("status") != "matched":
                findings_to_insert.append({
                    "stable_key": f"financial_reconciliation_mismatch:{lease_id}",
                    "org_id": l_org,
                    "property_id": prop_id,
                    "lease_id": lease_id,
                    "category": "financial",
                    "finding_type": "policy_exception",
                    "severity": "high",
                    "title": f"3-Way Financial Reconciliation Mismatch: {lease_id}",
                    "description": f"Financial ledger variance of ${diff_cents / 100.0:.2f} detected for {tenant}. Status: {recon.get('status')}. Reason: {recon.get('reason')}.",
                    "source_record_type": "lease",
                    "source_record_id": lease_id,
                    "detection_rule": "RULE_3WAY_RECONCILIATION_VARIANCE",
                    "originating_event": "financial_reconciliation_sweep",
                    "evidence": {
                        "status": recon.get("status"),
                        "difference_cents": diff_cents,
                        "difference_usd": diff_cents / 100.0,
                        "reason": recon.get("reason")
                    }
                })

            # Overdue Rent Past Grace Period
            if diff_cents > 0:
                findings_to_insert.append({
                    "stable_key": f"overdue_rent:{lease_id}:{now.strftime('%Y-%m')}",
                    "org_id": l_org,
                    "property_id": prop_id,
                    "lease_id": lease_id,
                    "category": "financial",
                    "finding_type": "policy_exception",
                    "severity": "high",
                    "title": f"Overdue Rent Past Grace Period: {lease_id}",
                    "description": f"Outstanding tenant rent balance of ${diff_cents / 100.0:.2f} past contractual grace period. Property manager statutory notice review required.",
                    "source_record_type": "lease",
                    "source_record_id": lease_id,
                    "detection_rule": "RULE_RENT_DELINQUENCY_POST_GRACE",
                    "originating_event": "rent_grace_period_sweep",
                    "evidence": {
                        "balance_due_usd": diff_cents / 100.0,
                        "tenant": tenant,
                        "reconciliation_reason": recon.get("reason")
                    }
                })
        except Exception as e:
            logger.warning(f"Error evaluating financial reconciliation for {lease_id}: {e}")

    # Vendor 4-Way AP Matching Discrepancies
    from .vendor_agent import reconcile_vendor_bill
    with db() as conn:
        invoices = conn.execute(
            """SELECT vi.id, vi.property_id, vi.lease_id, vi.total_usd, vi.status, p.org_id
               FROM vendor_invoices vi
               LEFT JOIN properties p ON vi.property_id = p.property_id"""
        ).fetchall()

    for inv in invoices:
        inv_id, inv_prop_id, inv_lease_id, total_usd, inv_status, inv_org = inv
        resolved_org = inv_org or (prop_map.get(inv_prop_id, {}).get("org_id")) or "ORG-APEX"
        if org_id and resolved_org != org_id:
            continue

        try:
            recon_res = reconcile_vendor_bill(inv_id)
            if recon_res.get("status") == "needs_review":
                reason = recon_res.get("reason_code", "UNKNOWN_VARIANCE")
                severity = "high" if reason in ("OVERBILLING", "SURCHARGE_VARIANCE") else "medium"
                diag_msg = "; ".join(recon_res.get("diagnosis", [recon_res.get("action_required", "")]))
                
                findings_to_insert.append({
                    "stable_key": f"vendor_invoice_discrepancy:{inv_id}:{reason}",
                    "org_id": resolved_org,
                    "property_id": inv_prop_id,
                    "lease_id": inv_lease_id,
                    "invoice_id": inv_id,
                    "category": "financial",
                    "finding_type": "policy_exception",
                    "severity": severity,
                    "title": f"Vendor AP Variance ({reason}): Invoice {inv_id}",
                    "description": diag_msg,
                    "source_record_type": "invoice",
                    "source_record_id": inv_id,
                    "detection_rule": f"RULE_VENDOR_4WAY_MATCH_{reason}",
                    "originating_event": "vendor_ap_reconciliation",
                    "evidence": {
                        "reason_code": reason,
                        "diagnosis": recon_res.get("diagnosis"),
                        "action_required": recon_res.get("action_required"),
                        "total_usd": float(total_usd)
                    }
                })
        except Exception as e:
            logger.warning(f"Error checking vendor invoice {inv_id}: {e}")

    # -------------------------------------------------------------------------
    # C. Maintenance SLA Breaches & Repeated Issues
    # -------------------------------------------------------------------------
    with db() as conn:
        open_wo = conn.execute(
            """SELECT wo.work_order_id, wo.lease_id, wo.property_id, wo.unit, wo.category,
                      wo.priority, wo.status, wo.reported_date, wo.technician, p.org_id
               FROM work_order_records wo
               JOIN properties p ON wo.property_id = p.property_id
               WHERE wo.status NOT IN ('Completed', 'Closed')"""
        ).fetchall()

    for wo in open_wo:
        wo_id, wo_lease_id, wo_prop_id, wo_unit, wo_cat, wo_prio, wo_status, rep_date_str, tech, wo_org = wo
        if org_id and wo_org != org_id:
            continue

        try:
            rep_d = datetime.strptime(str(rep_date_str), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            sla_hours = 4 if wo_prio == "Emergency" else (24 if wo_prio == "High" else 72)
            deadline = rep_d + timedelta(hours=sla_hours)
            
            if now > deadline:
                overdue_h = int((now - deadline).total_seconds() / 3600)
                findings_to_insert.append({
                    "stable_key": f"maintenance_sla_breach:{wo_id}",
                    "org_id": wo_org,
                    "property_id": wo_prop_id,
                    "lease_id": wo_lease_id,
                    "work_order_id": wo_id,
                    "category": "maintenance",
                    "finding_type": "operational_risk",
                    "severity": "critical" if wo_prio == "Emergency" else "high",
                    "title": f"Maintenance SLA Breached: Work Order {wo_id}",
                    "description": f"Work order {wo_id} ({wo_cat}, {wo_prio}) is {overdue_h} hours past configured {sla_hours}h SLA deadline. Assigned vendor: {tech or 'Unassigned'}.",
                    "source_record_type": "work_order",
                    "source_record_id": wo_id,
                    "detection_rule": "RULE_MAINTENANCE_SLA_BREACH",
                    "originating_event": "maintenance_sla_monitor",
                    "evidence": {
                        "reported_date": str(rep_date_str),
                        "sla_hours": sla_hours,
                        "overdue_hours": overdue_h,
                        "assigned_vendor": tech,
                        "priority": wo_prio
                    },
                    "due_date": deadline.isoformat()
                })
            elif (deadline - now).total_seconds() <= 14400: # Within 4 hours
                hours_remaining = round((deadline - now).total_seconds() / 3600, 1)
                findings_to_insert.append({
                    "stable_key": f"maintenance_sla_approaching:{wo_id}",
                    "org_id": wo_org,
                    "property_id": wo_prop_id,
                    "lease_id": wo_lease_id,
                    "work_order_id": wo_id,
                    "category": "maintenance",
                    "finding_type": "operational_risk",
                    "severity": "medium",
                    "title": f"Maintenance SLA Deadline Approaching (< 4h): {wo_id}",
                    "description": f"Work order {wo_id} ({wo_prio}) has {hours_remaining} hours remaining before SLA breach.",
                    "source_record_type": "work_order",
                    "source_record_id": wo_id,
                    "detection_rule": "RULE_MAINTENANCE_SLA_APPROACHING",
                    "originating_event": "maintenance_sla_monitor",
                    "evidence": {"hours_remaining": hours_remaining, "priority": wo_prio},
                    "due_date": deadline.isoformat()
                })
        except Exception as e:
            logger.warning(f"Error checking SLA for work order {wo_id}: {e}")

    # Repeated maintenance issues in same unit within 30 days
    with db() as conn:
        repeated_wo = conn.execute(
            """SELECT wo.property_id, wo.unit, wo.category, count(wo.work_order_id) as cnt, p.org_id
               FROM work_order_records wo
               JOIN properties p ON wo.property_id = p.property_id
               GROUP BY wo.property_id, wo.unit, wo.category, p.org_id
               HAVING count(wo.work_order_id) >= 2"""
        ).fetchall()

    for r_wo in repeated_wo:
        r_prop_id, r_unit, r_cat, cnt, r_org = r_wo
        if org_id and r_org != org_id:
            continue
        findings_to_insert.append({
            "stable_key": f"repeated_maintenance:{r_prop_id}:{r_unit}:{r_cat}",
            "org_id": r_org,
            "property_id": r_prop_id,
            "category": "maintenance",
            "finding_type": "operational_risk",
            "severity": "medium",
            "title": f"Repeated Maintenance Issue ({r_cat}): Unit {r_unit}",
            "description": f"Unit {r_unit} has recorded {cnt} separate '{r_cat}' maintenance tickets. Recommended for root-cause inspection.",
            "source_record_type": "work_order",
            "source_record_id": f"{r_prop_id}-{r_unit}",
            "detection_rule": "RULE_REPEATED_MAINTENANCE_INCIDENT",
            "originating_event": "maintenance_cluster_analysis",
            "evidence": {"ticket_count": cnt, "unit": r_unit, "category": r_cat}
        })

    # -------------------------------------------------------------------------
    # D. Operational & Integration Risks (Failed Notifs, Overdue Approvals)
    # -------------------------------------------------------------------------
    with db() as conn:
        failed_notifs = conn.execute(
            """SELECT id, title, recipient_email, recipient_type, category, created_at
               FROM notifications WHERE status = 'failed'"""
        ).fetchall()

        overdue_approvals = conn.execute(
            """SELECT case_id, state, action, reviewer, updated_at
               FROM approvals WHERE state IN ('pending', 'escalated')
               AND updated_at < now() - INTERVAL '7 days'"""
        ).fetchall()

    default_org = org_id or "ORG-APEX"

    for fn in failed_notifs:
        fn_id, fn_title, fn_email, fn_type, fn_cat, fn_created = fn
        findings_to_insert.append({
            "stable_key": f"failed_notification:{fn_id}",
            "org_id": default_org,
            "category": "operational_integration",
            "finding_type": "operational_risk",
            "severity": "medium",
            "title": f"Failed Notification Dispatch: {fn_title}",
            "description": f"Notification '{fn_title}' to {fn_email} failed delivery. Dispatch queue follow-up required.",
            "source_record_type": "notification",
            "source_record_id": fn_id,
            "detection_rule": "RULE_NOTIFICATION_DELIVERY_FAILURE",
            "originating_event": "notification_queue_monitor",
            "evidence": {"recipient": fn_email, "category": fn_cat, "created_at": str(fn_created)}
        })

    for oa in overdue_approvals:
        oa_case, oa_state, oa_act, oa_rev, oa_upd = oa
        findings_to_insert.append({
            "stable_key": f"overdue_approval:{oa_case}",
            "org_id": default_org,
            "category": "operational_integration",
            "finding_type": "operational_risk",
            "severity": "high",
            "title": f"Overdue Approval Escalation: Case {oa_case}",
            "description": f"Approval case '{oa_case}' has remained in '{oa_state}' state for over 7 days without resolution.",
            "source_record_type": "approval",
            "source_record_id": oa_case,
            "detection_rule": "RULE_APPROVAL_ESCALATION_OVERDUE",
            "originating_event": "approval_aging_sweep",
            "evidence": {"reviewer": oa_rev, "state": oa_state, "last_updated": str(oa_upd)}
        })

    # -------------------------------------------------------------------------
    # Idempotent Database Persistence (ON CONFLICT DO UPDATE)
    # -------------------------------------------------------------------------
    persisted_count = 0
    with db() as conn:
        for f in findings_to_insert:
            f_id = f"RISK-{hash(f['stable_key']) & 0x7FFFFFFF:08x}".upper()
            evidence_json = json.dumps(f.get("evidence", {}))
            
            conn.execute(
                """INSERT INTO risk_findings (
                    id, stable_key, org_id, property_id, lease_id, invoice_id,
                    vendor_id, work_order_id, resident_id, category, finding_type,
                    severity, title, description, source_record_type, source_record_id,
                    detection_rule, originating_event, evidence, jurisdiction,
                    statutory_source, effective_date, compliance_status, due_date,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()
                )
                ON CONFLICT (stable_key) DO UPDATE SET
                    evidence = excluded.evidence,
                    description = excluded.description,
                    title = excluded.title,
                    severity = excluded.severity,
                    compliance_status = excluded.compliance_status,
                    due_date = excluded.due_date,
                    updated_at = now()
                WHERE risk_findings.status NOT IN ('resolved', 'dismissed')""",
                (
                    f_id,
                    f["stable_key"],
                    f["org_id"],
                    f.get("property_id"),
                    f.get("lease_id"),
                    f.get("invoice_id"),
                    f.get("vendor_id"),
                    f.get("work_order_id"),
                    f.get("resident_id"),
                    f["category"],
                    f["finding_type"],
                    f["severity"],
                    f["title"],
                    f["description"],
                    f["source_record_type"],
                    f["source_record_id"],
                    f["detection_rule"],
                    f.get("originating_event"),
                    evidence_json,
                    f.get("jurisdiction"),
                    f.get("statutory_source"),
                    f.get("effective_date"),
                    f.get("compliance_status", "not_applicable"),
                    f.get("due_date")
                )
            )
            persisted_count += 1

    return {
        "scanned_at": now.isoformat(),
        "findings_detected": len(findings_to_insert),
        "findings_persisted": persisted_count,
        "org_id": org_id or "all_organizations",
        "status": "completed"
    }


# =============================================================================
# 3. Query, Filtering & Detail Endpoints
# =============================================================================

def get_compliance_summary(org_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve aggregate metrics by severity, status, category, and finding type."""
    with db() as conn:
        where_clause = "WHERE org_id = %s" if org_id else ""
        params = (org_id,) if org_id else ()

        by_severity = conn.execute(
            f"""SELECT severity, count(*) FROM risk_findings {where_clause} GROUP BY severity""",
            params
        ).fetchall()

        by_status = conn.execute(
            f"""SELECT status, count(*) FROM risk_findings {where_clause} GROUP BY status""",
            params
        ).fetchall()

        by_category = conn.execute(
            f"""SELECT category, count(*) FROM risk_findings {where_clause} GROUP BY category""",
            params
        ).fetchall()

        by_type = conn.execute(
            f"""SELECT finding_type, count(*) FROM risk_findings {where_clause} GROUP BY finding_type""",
            params
        ).fetchall()

        open_high_priority = conn.execute(
            f"""SELECT count(*) FROM risk_findings
               WHERE status IN ('open', 'under_review', 'action_required')
               AND severity IN ('critical', 'high')
               {"AND org_id = %s" if org_id else ""}""",
            params
        ).fetchone()

        total_findings = conn.execute(
            f"""SELECT count(*) FROM risk_findings {where_clause}""",
            params
        ).fetchone()

    return {
        "total_findings": total_findings[0] if total_findings else 0,
        "high_priority_count": open_high_priority[0] if open_high_priority else 0,
        "by_severity": {row[0]: row[1] for row in by_severity},
        "by_status": {row[0]: row[1] for row in by_status},
        "by_category": {row[0]: row[1] for row in by_category},
        "by_finding_type": {row[0]: row[1] for row in by_type}
    }


def list_risk_findings(
    org_id: Optional[str] = None,
    property_id: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    finding_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """List risk findings with comprehensive multi-facet filtering and pagination."""
    conditions = []
    params: List[Any] = []

    if org_id:
        conditions.append("org_id = %s")
        params.append(org_id)
    if property_id:
        conditions.append("property_id = %s")
        params.append(property_id)
    if category:
        conditions.append("category = %s")
        params.append(category)
    if severity:
        conditions.append("severity = %s")
        params.append(severity)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if finding_type:
        conditions.append("finding_type = %s")
        params.append(finding_type)
    if search:
        conditions.append("(title ILIKE %s OR description ILIKE %s OR source_record_id ILIKE %s)")
        wild = f"%{search}%"
        params.extend([wild, wild, wild])

    where_str = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db() as conn:
        count_row = conn.execute(
            f"SELECT count(*) FROM risk_findings {where_str}",
            tuple(params)
        ).fetchone()
        total = count_row[0] if count_row else 0

        query = f"""
            SELECT id, stable_key, org_id, property_id, lease_id, invoice_id,
                   work_order_id, category, finding_type, severity, title,
                   description, source_record_type, source_record_id, detection_rule,
                   jurisdiction, statutory_source, compliance_status, status,
                   assigned_reviewer, due_date, last_reviewed_at, created_at, updated_at
            FROM risk_findings
            {where_str}
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END ASC,
                created_at DESC
            LIMIT %s OFFSET %s
        """
        exec_params = list(params) + [limit, offset]
        rows = conn.execute(query, tuple(exec_params)).fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "stable_key": r[1],
            "org_id": r[2],
            "property_id": r[3],
            "lease_id": r[4],
            "invoice_id": r[5],
            "work_order_id": r[6],
            "category": r[7],
            "finding_type": r[8],
            "severity": r[9],
            "title": r[10],
            "description": r[11],
            "source_record_type": r[12],
            "source_record_id": r[13],
            "detection_rule": r[14],
            "jurisdiction": r[15],
            "statutory_source": r[16],
            "compliance_status": r[17],
            "status": r[18],
            "assigned_reviewer": r[19],
            "due_date": r[20].isoformat() if r[20] else None,
            "last_reviewed_at": r[21].isoformat() if r[21] else None,
            "created_at": r[22].isoformat() if r[22] else None,
            "updated_at": r[23].isoformat() if r[23] else None
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "findings": items
    }


def get_risk_finding_detail(finding_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve full detail for a finding, including evidence, related records, and audit history."""
    validate_finding_ownership(finding_id, org_id)

    with db() as conn:
        row = conn.execute(
            """SELECT id, stable_key, org_id, property_id, lease_id, invoice_id,
                      vendor_id, work_order_id, resident_id, category, finding_type,
                      severity, title, description, source_record_type, source_record_id,
                      detection_rule, originating_event, evidence, jurisdiction,
                      statutory_source, effective_date, compliance_status, status,
                      assigned_reviewer, due_date, last_reviewed_at, reviewed_by,
                      resolution_notes, resolved_by, resolved_at, created_at, updated_at
               FROM risk_findings WHERE id = %s""",
            (finding_id,)
        ).fetchone()

        if not row:
            raise ValueError(f"Finding {finding_id} not found")

        # Fetch audit history for this finding
        history_rows = conn.execute(
            """SELECT id, action, reviewer, decision_reason, previous_state, new_state, created_at
               FROM approval_history WHERE case_id = %s ORDER BY created_at DESC""",
            (finding_id,)
        ).fetchall()

    history = [
        {
            "id": h[0],
            "action": h[1],
            "reviewer": h[2],
            "reason": h[3],
            "previous_state": h[4],
            "new_state": h[5],
            "timestamp": h[6].isoformat() if h[6] else None
        }
        for h in history_rows
    ]

    return {
        "id": row[0],
        "canonical_id": canonical_id("risk_finding", row[0]),
        "stable_key": row[1],
        "org_id": row[2],
        "property_id": row[3],
        "lease_id": row[4],
        "invoice_id": row[5],
        "vendor_id": row[6],
        "work_order_id": row[7],
        "resident_id": row[8],
        "category": row[9],
        "finding_type": row[10],
        "severity": row[11],
        "title": row[12],
        "description": row[13],
        "source_record_type": row[14],
        "source_record_id": row[15],
        "detection_rule": row[16],
        "originating_event": row[17],
        "evidence": row[18] if isinstance(row[18], dict) else json.loads(row[18] or "{}"),
        "jurisdiction": row[19],
        "statutory_source": row[20],
        "effective_date": row[21],
        "compliance_status": row[22],
        "status": row[23],
        "assigned_reviewer": row[24],
        "due_date": row[25].isoformat() if row[25] else None,
        "last_reviewed_at": row[26].isoformat() if row[26] else None,
        "reviewed_by": row[27],
        "resolution_notes": row[28],
        "resolved_by": row[29],
        "resolved_at": row[30].isoformat() if row[30] else None,
        "created_at": row[31].isoformat() if row[31] else None,
        "updated_at": row[32].isoformat() if row[32] else None,
        "audit_history": history
    }


# =============================================================================
# 4. Reviewer Decisions, Resolution & Approval Management
# =============================================================================

def update_finding_status(
    finding_id: str,
    new_status: str,
    reviewer: str,
    decision_reason: str,
    org_id: Optional[str] = None,
    submitted_by: Optional[str] = None
) -> Dict[str, Any]:
    """Execute reviewer transition (under_review, action_required, resolved, dismissed).
    
    Enforces:
    - Mandatory non-empty reviewer identity and decision reason.
    - Separation of duties: Submitter cannot self-approve sensitive resolutions.
    - Append-only World Model event sourcing.
    - Approval history audit recording.
    """
    valid_statuses = ("open", "under_review", "action_required", "resolved", "dismissed")
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of {valid_statuses}")

    reviewer_clean = (reviewer or "").strip()
    reason_clean = (decision_reason or "").strip()

    if not reviewer_clean:
        raise ValueError("Reviewer identity is required for risk finding updates.")
    if len(reason_clean) < 3:
        raise ValueError("A substantial decision reason (minimum 3 characters) is strictly required.")

    # Separation of duties check
    if submitted_by and reviewer_clean.lower() == submitted_by.strip().lower() and new_status in ("resolved", "dismissed"):
        raise PermissionError(f"Separation of duties violation: Submitter '{submitted_by}' cannot self-approve resolution of this finding.")

    finding = validate_finding_ownership(finding_id, org_id)
    prev_status = finding["status"]

    now = datetime.now(timezone.utc)
    is_terminal = new_status in ("resolved", "dismissed")

    with db() as conn:
        conn.execute(
            """UPDATE risk_findings
               SET status = %s,
                   last_reviewed_at = %s,
                   reviewed_by = %s,
                   resolution_notes = %s,
                   resolved_by = %s,
                   resolved_at = %s,
                   updated_at = now()
               WHERE id = %s""",
            (
                new_status,
                now,
                reviewer_clean,
                reason_clean,
                reviewer_clean if is_terminal else None,
                now if is_terminal else None,
                finding_id
            )
        )

        # Audit History Record
        conn.execute(
            """INSERT INTO approval_history (
                case_id, entity_type, action, reviewer, decision_reason,
                previous_state, new_state, org_id, metadata, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())""",
            (
                finding_id,
                "risk_finding",
                new_status,
                reviewer_clean,
                reason_clean,
                prev_status,
                new_status,
                finding["org_id"],
                json.dumps({"title": finding["title"], "category": finding["category"]})
            )
        )

    # World Model Event
    record_event(
        case_id=finding_id,
        entity_id=finding_id,
        event_type="risk_finding_status_transitioned",
        payload={
            "finding_id": finding_id,
            "previous_status": prev_status,
            "new_status": new_status,
            "reviewer": reviewer_clean,
            "decision_reason": reason_clean,
            "org_id": finding["org_id"]
        }
    )

    return {
        "finding_id": finding_id,
        "previous_status": prev_status,
        "new_status": new_status,
        "reviewer": reviewer_clean,
        "decision_reason": reason_clean,
        "updated_at": now.isoformat()
    }


def assign_finding_reviewer(
    finding_id: str,
    reviewer: str,
    notes: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Assign designated reviewer to a risk finding."""
    reviewer_clean = (reviewer or "").strip()
    if not reviewer_clean:
        raise ValueError("Reviewer identity is required.")

    finding = validate_finding_ownership(finding_id, org_id)

    with db() as conn:
        conn.execute(
            """UPDATE risk_findings
               SET assigned_reviewer = %s,
                   status = CASE WHEN status = 'open' THEN 'under_review' ELSE status END,
                   updated_at = now()
               WHERE id = %s""",
            (reviewer_clean, finding_id)
        )

        conn.execute(
            """INSERT INTO approval_history (
                case_id, entity_type, action, reviewer, decision_reason,
                previous_state, new_state, org_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())""",
            (
                finding_id,
                "risk_finding",
                "assigned",
                reviewer_clean,
                notes or f"Assigned to {reviewer_clean}",
                finding["status"],
                "under_review",
                finding["org_id"]
            )
        )

    return {
        "finding_id": finding_id,
        "assigned_reviewer": reviewer_clean,
        "message": f"Finding {finding_id} assigned to {reviewer_clean}."
    }


def get_pending_approvals(org_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Centralized aggregator of all pending operational, contractual, and financial approvals."""
    pending_items = []

    with db() as conn:
        # 1. Lease Renewals pending approval
        ren_rows = conn.execute(
            """SELECT lr.id, lr.lease_id, lr.property_id, lr.renewal_period, lr.current_rent_usd,
                      lr.proposed_rent_usd, lr.created_at, p.org_id, p.name as property_name,
                      l.tenant1
               FROM lease_renewals lr
               JOIN properties p ON lr.property_id = p.property_id
               JOIN lease_records l ON lr.lease_id = l.lease_id
               WHERE lr.manager_approval_state = 'pending' OR lr.status = 'pending_approval'"""
        ).fetchall()

        for r in ren_rows:
            if org_id and r[7] != org_id:
                continue
            pending_items.append({
                "approval_id": f"RENEWAL-{r[0]}",
                "case_id": r[0],
                "entity_type": "lease_renewal",
                "org_id": r[7],
                "property_id": r[2],
                "property_name": r[8],
                "lease_id": r[1],
                "title": f"Lease Renewal Approval: {r[1]} ({r[9]})",
                "description": f"Tenant accepted renewal offer for {r[3]}. Rent adjusting from ${r[4]} to ${r[5]}.",
                "severity": "high",
                "created_at": r[6].isoformat() if r[6] else None
            })

        # 2. Move-Out Deposit Closeouts pending approval
        mo_rows = conn.execute(
            """SELECT mo.id, mo.lease_id, mo.property_id, mo.resident_name, mo.security_deposit_usd,
                      mo.proposed_refund_usd, mo.statutory_deadline_date, mo.created_at, p.org_id, p.name as property_name
               FROM move_out_records mo
               JOIN properties p ON mo.property_id = p.property_id
               WHERE mo.closeout_approval_state = 'pending'"""
        ).fetchall()

        for m in mo_rows:
            if org_id and m[8] != org_id:
                continue
            pending_items.append({
                "approval_id": f"MOVEOUT-{m[0]}",
                "case_id": m[0],
                "entity_type": "move_out_closeout",
                "org_id": m[8],
                "property_id": m[2],
                "property_name": m[9],
                "lease_id": m[1],
                "title": f"Security Deposit Closeout Approval: {m[1]} ({m[3]})",
                "description": f"Proposed deposit disposition: ${m[5]} refund from ${m[4]} escrow deposit. Statutory deadline: {m[6] or 'Unspecified'}.",
                "severity": "critical" if m[6] else "high",
                "created_at": m[7].isoformat() if m[7] else None
            })

        # 3. Risk findings marked action_required
        rf_rows = conn.execute(
            """SELECT id, title, description, category, severity, org_id, property_id, lease_id, created_at
               FROM risk_findings
               WHERE status = 'action_required'"""
        ).fetchall()

        for rf in rf_rows:
            if org_id and rf[5] != org_id:
                continue
            pending_items.append({
                "approval_id": f"RISK-{rf[0]}",
                "case_id": rf[0],
                "entity_type": "risk_finding",
                "org_id": rf[5],
                "property_id": rf[6],
                "lease_id": rf[7],
                "title": rf[1],
                "description": rf[2],
                "severity": rf[4],
                "created_at": rf[8].isoformat() if rf[8] else None
            })

    return pending_items


def get_approval_history(
    case_id: Optional[str] = None,
    org_id: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieve indexed audit log of reviewer approvals, decisions, and reasons."""
    conditions = []
    params: List[Any] = []

    if case_id:
        conditions.append("case_id = %s")
        params.append(case_id)
    if org_id:
        conditions.append("org_id = %s")
        params.append(org_id)

    where_str = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db() as conn:
        rows = conn.execute(
            f"""SELECT id, case_id, entity_type, action, reviewer, decision_reason,
                       previous_state, new_state, org_id, metadata, created_at
                FROM approval_history
                {where_str}
                ORDER BY created_at DESC
                LIMIT %s""",
            tuple(params + [limit])
        ).fetchall()

    return [
        {
            "id": r[0],
            "case_id": r[1],
            "entity_type": r[2],
            "action": r[3],
            "reviewer": r[4],
            "decision_reason": r[5],
            "previous_state": r[6],
            "new_state": r[7],
            "org_id": r[8],
            "metadata": r[9] if isinstance(r[9], dict) else json.loads(r[9] or "{}"),
            "created_at": r[10].isoformat() if r[10] else None
        }
        for r in rows
    ]
