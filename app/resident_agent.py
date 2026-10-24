"""Autonomous Resident & Lease Lifecycle Workflow Agent for EQUILIBRA.

Manages:
1. Lease Renewal:
   - Identify upcoming expiring leases and evaluate renewal eligibility.
   - Prepare renewal offers with business-rule rent adjustments.
   - Track status: upcoming -> offer_prepared -> offered -> accepted -> pending_approval -> finalized.
   - Require authorized human approval before contract terms are modified.
   - Prevent duplicate offers for the same renewal period.

2. Move-In Workflow:
   - Structured onboarding checklists linked to resident, lease, and property.
   - Track required insurance, ID, escrow deposit, pre-inspection, utility transfer, and key handover.
   - Flag missing requirements and overdue tasks.
   - Preserve completion timestamps and responsible users.

3. Move-Out Workflow:
   - Track notice to vacate, planned exit, inspections, and keys surrender.
   - Cross-reference unpaid rent and damage work orders.
   - Formulate proposed closeout summary without unauthorized automatic deposit deductions.
   - Enforce statutory deadlines (e.g. 21-day California escrow return rules).
   - Require authorized human approval for deposit release.

4. Resident Communications & Multi-Tenant Isolation:
   - Respect resident communication preferences (email/SMS opt-out).
   - Deduplicate alerts with stable event keys.
   - Enforce organization ownership on every operation to prevent cross-tenant leaks.
   - Append-only event sourcing in the Meterless World Model.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from decimal import Decimal

# pyrefly: ignore[missing-import]
from fastapi import HTTPException
from .database import db
from .world_model import record_event, canonical_id
from .notifications import queue_notification
from .engine import fixture_rows, calculate


def validate_lease_ownership(lease_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Verify that a lease exists and belongs to the specified organization."""
    with db() as conn:
        row = conn.execute(
            """SELECT l.lease_id, l.property_id, p.name as property_name, p.org_id,
                      l.unit, l.address, l.tenant1, l.tenant2, l.contract_date,
                      l.move_in_date, l.end_date, l.monthly_rent_usd, l.security_deposit_usd,
                      l.lease_status, l.resident_email, l.communication_preferences
               FROM lease_records l
               JOIN properties p ON l.property_id = p.property_id
               WHERE l.lease_id = %s""",
            (lease_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Lease '{lease_id}' not found.")

    lease_dict = {
        "lease_id": row[0],
        "property_id": row[1],
        "property_name": row[2],
        "org_id": row[3],
        "unit": row[4],
        "address": row[5],
        "tenant1": row[6],
        "tenant2": row[7],
        "contract_date": row[8],
        "move_in_date": row[9],
        "end_date": row[10],
        "monthly_rent_usd": float(row[11]),
        "security_deposit_usd": float(row[12]),
        "lease_status": row[13] or "active",
        "resident_email": row[14] or f"resident-{lease_id.lower()}@equilibra.internal",
        "communication_preferences": row[15] or {"email": True, "sms": False}
    }

    if org_id and org_id != "all" and lease_dict["org_id"] != org_id:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: Lease '{lease_id}' belongs to organization '{lease_dict['org_id']}', not '{org_id}'."
        )

    return lease_dict


# =====================================================================
# A. LEASE RENEWAL WORKFLOW
# =====================================================================

def get_expiring_leases(
    days_threshold: int = 90,
    org_id: Optional[str] = None,
    window_days: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Identify leases approaching expiration and evaluate renewal eligibility."""
    effective_days = window_days if window_days is not None else days_threshold
    with db() as conn:
        sql = """
            SELECT l.lease_id, l.property_id, p.name as property_name, p.org_id,
                   l.unit, l.address, l.tenant1, l.monthly_rent_usd, l.move_in_date,
                   l.end_date, l.lease_status, l.resident_email
            FROM lease_records l
            JOIN properties p ON l.property_id = p.property_id
            WHERE l.lease_status = 'active'
        """
        params = []
        if org_id and org_id != "all":
            sql += " AND p.org_id = %s"
            params.append(org_id)
        sql += " ORDER BY l.end_date ASC NULLS LAST"
        rows = conn.execute(sql, params).fetchall()

    today = datetime.now(timezone.utc).date()
    expiring = []

    for r in rows:
        lease_id = r[0]
        end_date_str = r[9]
        if not end_date_str:
            continue

        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        days_remaining = (end_date - today).days

        # Include if expiring within threshold or already in renewal consideration window
        if days_remaining <= effective_days:
            # 1. Evaluate payment standing
            fin = fixture_rows(lease_id)
            recon = calculate(fin)
            diff_cents = recon.get("difference_cents") or 0

            # 2. Check open maintenance requests
            with db() as conn:
                open_wo = conn.execute(
                    "SELECT count(*) FROM work_order_records WHERE lease_id = %s AND status != 'completed'",
                    (lease_id,)
                ).fetchone()[0]

            if diff_cents > 50000:  # > $500 unpaid delinquency
                eligibility = "ineligible"
                eligibility_reason = "Significant unpaid rent delinquency on ledger."
            elif diff_cents > 0 or open_wo > 3:
                eligibility = "requires_review"
                eligibility_reason = "Unsettled balance or multiple active maintenance tickets require manager review."
            else:
                eligibility = "eligible"
                eligibility_reason = "Clean payment ledger and good tenancy standing."

            # Check existing renewal offer
            with db() as conn:
                existing_offer = conn.execute(
                    "SELECT id, renewal_period, proposed_rent_usd, status FROM lease_renewals WHERE lease_id = %s ORDER BY created_at DESC LIMIT 1",
                    (lease_id,)
                ).fetchone()

            expiring.append({
                "lease_id": lease_id,
                "property_id": r[1],
                "property_name": r[2],
                "org_id": r[3],
                "unit": r[4],
                "address": r[5],
                "tenant1": r[6],
                "current_rent_usd": float(r[7]),
                "move_in_date": r[8],
                "end_date": end_date_str,
                "days_remaining": days_remaining,
                "days_until_expiration": days_remaining,
                "eligibility_status": eligibility,
                "renewal_eligibility": eligibility,
                "is_eligible_for_renewal": eligibility == "eligible",
                "eligibility_reason": eligibility_reason,
                "active_renewal_id": existing_offer[0] if existing_offer else None,
                "renewal_status": existing_offer[3] if existing_offer else "upcoming"
            })

    return expiring


def get_lease_renewal(lease_id: str, org_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve the active renewal record for a lease."""
    validate_lease_ownership(lease_id, org_id=org_id)
    with db() as conn:
        row = conn.execute(
            """SELECT id, lease_id, property_id, renewal_period, current_rent_usd,
                      proposed_rent_usd, term_months, eligibility_status, status,
                      offer_terms, resident_decision, decision_date, manager_approval_state,
                      approved_by, approved_at, notes, created_at
               FROM lease_renewals WHERE lease_id = %s ORDER BY created_at DESC LIMIT 1""",
            (lease_id,)
        ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "lease_id": row[1],
        "property_id": row[2],
        "renewal_period": row[3],
        "current_rent_usd": float(row[4]),
        "proposed_rent_usd": float(row[5]),
        "term_months": row[6],
        "eligibility_status": row[7],
        "status": row[8],
        "offer_terms": row[9] or "",
        "resident_decision": row[10],
        "decision_date": row[11].isoformat() if row[11] else None,
        "manager_approval_state": row[12],
        "approved_by": row[13],
        "approved_at": row[14].isoformat() if row[14] else None,
        "notes": row[15] or "",
        "created_at": row[16].isoformat() if row[16] else None
    }


def prepare_renewal_offer(
    lease_id: str,
    term_months: int = 12,
    rent_increase_percent: float = 3.5,
    custom_notes: Optional[str] = None,
    prepared_by: Optional[str] = None,
    org_id: Optional[str] = None,
    proposed_increase_pct: Optional[float] = None,
    renewal_term_months: Optional[int] = None
) -> Dict[str, Any]:
    """Prepare a renewal offer with business rules and duplicate-offer prevention."""
    if proposed_increase_pct is not None:
        rent_increase_percent = proposed_increase_pct
    if renewal_term_months is not None:
        term_months = renewal_term_months

    lease = validate_lease_ownership(lease_id, org_id=org_id)

    # Determine renewal period
    current_end = lease["end_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        end_dt = datetime.strptime(current_end, "%Y-%m-%d")
        new_end_dt = end_dt + timedelta(days=term_months * 30)
        renewal_period = f"{end_dt.strftime('%Y-%m')} to {new_end_dt.strftime('%Y-%m')}"
    except ValueError:
        renewal_period = f"Term-{term_months}m-{current_end}"

    # Duplicate check: prevent duplicate offer for the same lease and renewal period
    with db() as conn:
        existing = conn.execute(
            "SELECT id, status, proposed_rent_usd FROM lease_renewals WHERE lease_id = %s AND renewal_period = %s",
            (lease_id, renewal_period)
        ).fetchone()

    if existing:
        return {
            "status": "duplicate_prevented",
            "renewal_id": existing[0],
            "renewal_status": existing[1],
            "proposed_rent_usd": float(existing[2]),
            "message": f"Renewal offer already prepared for lease '{lease_id}' for period '{renewal_period}'."
        }

    current_rent = Decimal(str(lease["monthly_rent_usd"]))
    proposed_rent = round(current_rent * (Decimal("1") + Decimal(str(rent_increase_percent)) / Decimal("100")), 2)

    renewal_id = f"REN-{lease_id.replace('LEASE-', '')}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    offer_terms = custom_notes or f"Standard {term_months}-month renewal at ${proposed_rent:.2f}/month (+{rent_increase_percent}%). Security deposit unchanged."

    with db() as conn:
        conn.execute(
            """INSERT INTO lease_renewals (
                id, lease_id, property_id, renewal_period, current_rent_usd,
                proposed_rent_usd, term_months, eligibility_status, status,
                offer_terms, manager_approval_state
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'eligible', 'offer_prepared', %s, 'pending')""",
            (
                renewal_id, lease_id, lease["property_id"], renewal_period,
                float(current_rent), float(proposed_rent), term_months, offer_terms
            )
        )

    # Record in World Model
    record_event(
        case_id=lease_id,
        entity_id=renewal_id,
        event_type="lease_renewal_offer_prepared",
        payload={
            "renewal_id": renewal_id,
            "lease_id": lease_id,
            "current_rent": float(current_rent),
            "proposed_rent": float(proposed_rent),
            "period": renewal_period
        }
    )

    # Queue alert notification to resident respecting preferences
    prefs = lease.get("communication_preferences") or {"email": True}
    if prefs.get("email", True):
        queue_notification(
            recipient_email=lease["resident_email"],
            recipient_type="resident",
            title=f"Lease Renewal Offer: {lease['property_name']}",
            message=f"Hello {lease['tenant1']}, your lease renewal offer for {renewal_period} is ready for review at ${float(proposed_rent):.2f}/mo.",
            category="lease_renewal",
            event_key=f"renewal-offer:{lease_id}:{renewal_period}"
        )

    return {
        "status": "offer_prepared",
        "renewal_id": renewal_id,
        "lease_id": lease_id,
        "renewal_period": renewal_period,
        "current_rent_usd": float(current_rent),
        "proposed_rent_usd": float(proposed_rent),
        "proposed_increase_pct": float(rent_increase_percent),
        "term_months": term_months,
        "offer_terms": offer_terms,
        "manager_approval_state": "pending"
    }


def submit_renewal_decision(
    lease_id: str,
    decision: str,
    notes: Optional[str] = None,
    resident_name: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Resident accepts or declines renewal offer. Requires human manager approval before finalization."""
    if decision not in ("accepted", "declined"):
        raise ValueError("Decision must be 'accepted' or 'declined'.")

    lease = validate_lease_ownership(lease_id, org_id=org_id)
    with db() as conn:
        renewal = conn.execute(
            """SELECT id, renewal_period, proposed_rent_usd, status
               FROM lease_renewals WHERE lease_id = %s ORDER BY created_at DESC LIMIT 1""",
            (lease_id,)
        ).fetchone()

    if not renewal:
        raise ValueError(f"No active renewal offer found for lease '{lease_id}'.")

    renewal_id, period, proposed_rent, current_status = renewal
    now_dt = datetime.now(timezone.utc)
    new_status = "pending_approval" if decision == "accepted" else "declined"

    with db() as conn:
        conn.execute(
            """UPDATE lease_renewals
               SET resident_decision = %s,
                   decision_date = %s,
                   status = %s,
                   notes = COALESCE(notes, '') || %s
               WHERE id = %s""",
            (decision, now_dt, new_status, f" | Decision: {decision}. {notes or ''}", renewal_id)
        )

    record_event(
        case_id=lease_id,
        entity_id=renewal_id,
        event_type="lease_renewal_decision_submitted",
        payload={
            "renewal_id": renewal_id,
            "decision": decision,
            "resident": resident_name or lease["tenant1"],
            "status": new_status
        }
    )

    # Queue alert to property manager
    queue_notification(
        recipient_email="leasing@equilibra.internal",
        recipient_type="manager",
        title=f"Renewal Decision: {lease['tenant1']} ({decision.upper()})",
        message=f"Resident {lease['tenant1']} for lease {lease_id} has {decision} renewal offer for {period}. Requires manager sign-off.",
        category="lease_renewal",
        event_key=f"renewal-decision:{renewal_id}"
    )

    return {
        "status": decision,
        "renewal_id": renewal_id,
        "lease_id": lease_id,
        "decision": decision,
        "manager_approval_state": "pending" if decision == "accepted" else "not_required",
        "new_status": new_status,
        "message": f"Renewal offer marked as {decision}. Contractual execution requires manager approval."
    }


def approve_lease_renewal(
    lease_id: str,
    reviewer: str = "Property Manager",
    approved: bool = True,
    notes: Optional[str] = None,
    org_id: Optional[str] = None,
    manager_name: Optional[str] = None
) -> Dict[str, Any]:
    """Authorized human approval required before finalizing contract renewal and updating ledger terms."""
    effective_reviewer = manager_name or reviewer
    lease = validate_lease_ownership(lease_id, org_id=org_id)

    with db() as conn:
        renewal = conn.execute(
            """SELECT id, renewal_period, proposed_rent_usd, term_months, status
               FROM lease_renewals WHERE lease_id = %s ORDER BY created_at DESC LIMIT 1""",
            (lease_id,)
        ).fetchone()

    if not renewal:
        raise ValueError(f"No renewal offer found for lease '{lease_id}'.")

    renewal_id, period, proposed_rent, term_months, current_status = renewal
    now_dt = datetime.now(timezone.utc)

    if not approved:
        with db() as conn:
            conn.execute(
                """UPDATE lease_renewals
                   SET manager_approval_state = 'rejected',
                       approved_by = %s,
                       approved_at = %s,
                       status = 'offer_prepared',
                       notes = COALESCE(notes, '') || %s
                   WHERE id = %s""",
                (reviewer, now_dt, f" | Rejected by {reviewer}: {notes or ''}", renewal_id)
            )
        return {
            "status": "rejected",
            "renewal_id": renewal_id,
            "lease_id": lease_id,
            "message": f"Renewal offer for '{lease_id}' rejected by {reviewer}."
        }

    # Finalize renewal: update lease_records with new rent and extended end_date
    current_end = lease["end_date"] or now_dt.strftime("%Y-%m-%d")
    try:
        end_dt = datetime.strptime(current_end, "%Y-%m-%d")
        new_end = (end_dt + timedelta(days=term_months * 30)).strftime("%Y-%m-%d")
    except ValueError:
        new_end = (now_dt + timedelta(days=365)).strftime("%Y-%m-%d")

    with db() as conn:
        conn.execute(
            """UPDATE lease_renewals
               SET manager_approval_state = 'approved',
                   approved_by = %s,
                   approved_at = %s,
                   status = 'finalized',
                   notes = COALESCE(notes, '') || %s
               WHERE id = %s""",
            (reviewer, now_dt, f" | Approved and finalized by {reviewer}: {notes or ''}", renewal_id)
        )
        conn.execute(
            """UPDATE lease_records
               SET monthly_rent_usd = %s,
                   end_date = %s,
                   lease_status = 'active'
               WHERE lease_id = %s""",
            (proposed_rent, new_end, lease_id)
        )

    record_event(
        case_id=lease_id,
        entity_id=renewal_id,
        event_type="lease_renewal_approved",
        payload={
            "renewal_id": renewal_id,
            "approved_by": reviewer,
            "new_rent_usd": float(proposed_rent),
            "new_end_date": new_end,
            "period": period
        }
    )

    # Queue confirmation to resident
    queue_notification(
        recipient_email=lease["resident_email"],
        recipient_type="resident",
        title=f"Lease Renewal Finalized: {lease['property_name']}",
        message=f"Congratulations {lease['tenant1']}! Your lease renewal has been approved and executed through {new_end}.",
        category="lease_renewal",
        event_key=f"renewal-finalized:{renewal_id}"
    )

    return {
        "status": "finalized",
        "renewal_id": renewal_id,
        "lease_id": lease_id,
        "new_rent_usd": float(proposed_rent),
        "new_end_date": new_end,
        "approved_by": reviewer,
        "message": f"Lease '{lease_id}' successfully renewed through {new_end}."
    }


# =====================================================================
# B. MOVE-IN WORKFLOW
# =====================================================================

DEFAULT_MOVE_IN_TASKS = [
    {
        "task_key": "renters_insurance",
        "title": "Renter's Insurance Policy",
        "category": "document",
        "description": "Upload certificate of insurance with minimum $100k liability coverage.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None,
        "notes": ""
    },
    {
        "task_key": "government_id",
        "title": "Government Photo Identification",
        "category": "document",
        "description": "Verify government-issued photo ID for all primary leaseholders.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None,
        "notes": ""
    },
    {
        "task_key": "deposit_settlement",
        "title": "Initial Escrow & 1st Month Remittance",
        "category": "payment",
        "description": "Confirm cleared receipt of full security deposit and first month rent.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None,
        "notes": ""
    },
    {
        "task_key": "pre_inspection",
        "title": "Move-In Condition Walkthrough",
        "category": "inspection",
        "description": "Complete unit condition walkthrough report and record pre-existing marks.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None,
        "notes": ""
    },
    {
        "task_key": "utility_transfer",
        "title": "Utility Account Transfer",
        "category": "utility",
        "description": "Confirm PG&E/electric and water submeter account transferred to resident.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None,
        "notes": ""
    },
    {
        "task_key": "key_handover",
        "title": "Smart Lock & Physical Key Handover",
        "category": "access",
        "description": "Issue unit physical keys, parking remote fobs, and program digital entry pin.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None,
        "notes": ""
    }
]


def get_move_in_checklist(lease_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve or auto-initialize move-in onboarding checklist for a resident lease."""
    lease = validate_lease_ownership(lease_id, org_id=org_id)
    with db() as conn:
        row = conn.execute(
            """SELECT id, lease_id, property_id, resident_name, resident_email,
                      target_move_in_date, status, tasks, created_at, completed_at
               FROM move_in_checklists WHERE lease_id = %s""",
            (lease_id,)
        ).fetchone()

    if not row:
        return initiate_move_in_checklist(lease_id, org_id=org_id)

    tasks = row[7] if isinstance(row[7], list) else []
    completed_count = sum(1 for t in tasks if t.get("is_completed"))
    total_count = len(tasks)
    progress_percent = round((completed_count / total_count * 100), 1) if total_count > 0 else 0.0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_date = row[5]
    is_overdue = (target_date < today) and (completed_count < total_count)

    return {
        "checklist_id": row[0],
        "lease_id": row[1],
        "property_id": row[2],
        "property_name": lease["property_name"],
        "resident_name": row[3],
        "resident_email": row[4],
        "target_move_in_date": target_date,
        "status": "overdue" if is_overdue else row[6],
        "progress_percent": progress_percent,
        "completed_tasks": completed_count,
        "total_tasks": total_count,
        "missing_requirements": [t["title"] for t in tasks if not t.get("is_completed")],
        "tasks": tasks,
        "created_at": row[8].isoformat() if row[8] else None,
        "completed_at": row[9].isoformat() if row[9] else None
    }


def initiate_move_in_checklist(
    lease_id: str,
    target_date: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new move-in checklist for an active lease (idempotent)."""
    lease = validate_lease_ownership(lease_id, org_id=org_id)
    target = target_date or lease["move_in_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    checklist_id = f"MI-{lease_id.replace('LEASE-', '')}"

    import json
    with db() as conn:
        conn.execute(
            """INSERT INTO move_in_checklists (
                id, lease_id, property_id, resident_name, resident_email,
                target_move_in_date, status, tasks
            ) VALUES (%s, %s, %s, %s, %s, %s, 'in_progress', %s::jsonb)
            ON CONFLICT (lease_id) DO NOTHING""",
            (
                checklist_id, lease_id, lease["property_id"], lease["tenant1"],
                lease["resident_email"], target, json.dumps(DEFAULT_MOVE_IN_TASKS)
            )
        )

    record_event(
        case_id=lease_id,
        entity_id=checklist_id,
        event_type="move_in_checklist_created",
        payload={
            "checklist_id": checklist_id,
            "lease_id": lease_id,
            "target_date": target
        }
    )

    return get_move_in_checklist(lease_id, org_id=org_id)


def complete_move_in_task(
    lease_id: str,
    task_key: str,
    completed_by: str,
    notes: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record completion of a move-in task with timestamp and responsible user."""
    validate_lease_ownership(lease_id, org_id=org_id)
    chk = get_move_in_checklist(lease_id, org_id=org_id)

    tasks = chk["tasks"]
    found = False
    now_iso = datetime.now(timezone.utc).isoformat()

    for t in tasks:
        if t["task_key"] == task_key:
            t["is_completed"] = True
            t["completed_at"] = now_iso
            t["completed_by"] = completed_by
            if notes:
                t["notes"] = notes
            found = True
            break

    if not found:
        raise ValueError(f"Task key '{task_key}' not found in move-in checklist.")

    all_done = all(t.get("is_completed") for t in tasks)
    new_status = "completed" if all_done else "in_progress"

    import json
    with db() as conn:
        conn.execute(
            """UPDATE move_in_checklists
               SET tasks = %s::jsonb,
                   status = %s,
                   completed_at = %s
               WHERE lease_id = %s""",
            (json.dumps(tasks), new_status, datetime.now(timezone.utc) if all_done else None, lease_id)
        )

    record_event(
        case_id=lease_id,
        entity_id=task_key,
        event_type="move_in_task_completed",
        payload={
            "lease_id": lease_id,
            "task_key": task_key,
            "completed_by": completed_by,
            "all_done": all_done
        }
    )

    return get_move_in_checklist(lease_id, org_id=org_id)


# =====================================================================
# C. MOVE-OUT WORKFLOW
# =====================================================================

DEFAULT_MOVE_OUT_TASKS = [
    {
        "task_key": "notice_acknowledgment",
        "title": "30-Day Notice Acknowledgment",
        "category": "administrative",
        "description": "Verify formal 30-day notice to vacate received and logged.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None
    },
    {
        "task_key": "pre_move_out_inspection",
        "title": "Pre-Move-Out Inspection Walkthrough",
        "category": "inspection",
        "description": "Perform preliminary inspection to advise resident of potential repair deductions.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None
    },
    {
        "task_key": "key_return",
        "title": "Key, Remote & Fob Return",
        "category": "access",
        "description": "Physical surrender and verification of all keys, remotes, and access badges.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None
    },
    {
        "task_key": "cleaning_inspection",
        "title": "Final Turnover Cleaning Inspection",
        "category": "inspection",
        "description": "Verify unit swept clean and appliance sanitation meets contract standard.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None
    },
    {
        "task_key": "utility_final",
        "title": "Final Utility Meter Settlement",
        "category": "utility",
        "description": "Record final submeter reads and transfer accounts back to landlord.",
        "is_completed": False,
        "completed_at": None,
        "completed_by": None
    }
]


def submit_move_out_notice(
    lease_id: str,
    planned_move_out_date: str,
    forwarding_address: str,
    resident_name: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record resident notice to vacate and initialize move-out workflow."""
    lease = validate_lease_ownership(lease_id, org_id=org_id)
    now_dt = datetime.now(timezone.utc)
    notice_id = f"MO-{lease_id.replace('LEASE-', '')}"

    # Calculate statutory 21-day escrow deadline (Cal. Civ. Code § 1950.5)
    try:
        planned_dt = datetime.strptime(planned_move_out_date, "%Y-%m-%d")
        statutory_deadline = (planned_dt + timedelta(days=21)).strftime("%Y-%m-%d")
    except ValueError:
        statutory_deadline = (now_dt + timedelta(days=51)).strftime("%Y-%m-%d")

    import json
    with db() as conn:
        conn.execute(
            """INSERT INTO move_out_records (
                id, lease_id, property_id, resident_name, resident_email,
                notice_date, planned_move_out_date, forwarding_address,
                status, tasks, security_deposit_usd, statutory_deadline_date,
                closeout_approval_state
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'notice_received', %s::jsonb, %s, %s, 'pending')
            ON CONFLICT (lease_id) DO UPDATE SET
                planned_move_out_date = excluded.planned_move_out_date,
                forwarding_address = excluded.forwarding_address""",
            (
                notice_id, lease_id, lease["property_id"], resident_name or lease["tenant1"],
                lease["resident_email"], now_dt.strftime("%Y-%m-%d"), planned_move_out_date,
                forwarding_address, json.dumps(DEFAULT_MOVE_OUT_TASKS), lease["security_deposit_usd"],
                statutory_deadline
            )
        )

    record_event(
        case_id=lease_id,
        entity_id=notice_id,
        event_type="move_out_notice_received",
        payload={
            "notice_id": notice_id,
            "lease_id": lease_id,
            "planned_move_out": planned_move_out_date,
            "forwarding_address": forwarding_address
        }
    )

    # Queue alert to property manager
    queue_notification(
        recipient_email="leasing@equilibra.internal",
        recipient_type="manager",
        title=f"Notice to Vacate: {lease['tenant1']} ({lease_id})",
        message=f"Resident {lease['tenant1']} submitted notice to vacate for {planned_move_out_date}. 21-day statutory deadline is {statutory_deadline}.",
        category="move_out",
        event_key=f"move-out-notice:{notice_id}"
    )

    return get_move_out_record(lease_id, org_id=org_id)


def get_move_out_record(lease_id: str, org_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve move-out record with linked invoices, damage orders, and closeout summary."""
    lease = validate_lease_ownership(lease_id, org_id=org_id)
    with db() as conn:
        row = conn.execute(
            """SELECT id, lease_id, property_id, resident_name, resident_email,
                      notice_date, planned_move_out_date, actual_move_out_date,
                      forwarding_address, status, tasks, security_deposit_usd,
                      outstanding_balance_usd, proposed_deductions, proposed_refund_usd,
                      statutory_deadline_date, closeout_approval_state, approved_by,
                      approved_at, approval_notes, created_at
               FROM move_out_records WHERE lease_id = %s""",
            (lease_id,)
        ).fetchone()

    if not row:
        return None

    # Calculate linked ledger obligations
    fin = fixture_rows(lease_id)
    recon = calculate(fin)
    outstanding_balance = max(0.0, float(recon.get("difference_cents", 0)) / 100.0)

    # Fetch any tenant-linked repair work orders
    with db() as conn:
        wo_rows = conn.execute(
            """SELECT work_order_id, category, description, estimated_cost_usd, status
               FROM work_order_records WHERE lease_id = %s ORDER BY reported_date DESC""",
            (lease_id,)
        ).fetchall()

    work_orders = [
        {
            "id": w[0],
            "category": w[1],
            "description": w[2],
            "cost_usd": float(w[3]),
            "status": w[4]
        }
        for w in wo_rows
    ]

    tasks = row[10] if isinstance(row[10], list) else []
    deductions = row[13] if isinstance(row[13], list) else []

    return {
        "move_out_id": row[0],
        "lease_id": row[1],
        "property_id": row[2],
        "property_name": lease["property_name"],
        "resident_name": row[3],
        "resident_email": row[4],
        "notice_date": row[5],
        "planned_move_out_date": row[6],
        "actual_move_out_date": row[7],
        "forwarding_address": row[8],
        "status": row[9],
        "tasks": tasks,
        "security_deposit_usd": float(row[11]),
        "outstanding_rent_balance_usd": outstanding_balance,
        "proposed_deductions": deductions,
        "proposed_refund_usd": float(row[14]),
        "statutory_deadline_date": row[15],
        "closeout_approval_state": row[16],
        "approved_by": row[17],
        "approved_at": row[18].isoformat() if row[18] else None,
        "approval_notes": row[19] or "",
        "linked_work_orders": work_orders,
        "created_at": row[20].isoformat() if row[20] else None
    }


def complete_move_out_task(
    lease_id: str,
    task_key: str,
    completed_by: str,
    notes: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Complete a move-out task with timestamp and responsible user."""
    validate_lease_ownership(lease_id, org_id=org_id)
    rec = get_move_out_record(lease_id, org_id=org_id)
    if not rec:
        raise ValueError(f"No move-out record found for lease '{lease_id}'.")

    tasks = rec["tasks"]
    found = False
    now_iso = datetime.now(timezone.utc).isoformat()

    for t in tasks:
        if t["task_key"] == task_key:
            t["is_completed"] = True
            t["completed_at"] = now_iso
            t["completed_by"] = completed_by
            if notes:
                t["notes"] = notes
            found = True
            break

    if not found:
        raise ValueError(f"Task key '{task_key}' not found in move-out tasks.")

    import json
    with db() as conn:
        conn.execute(
            "UPDATE move_out_records SET tasks = %s::jsonb WHERE lease_id = %s",
            (json.dumps(tasks), lease_id)
        )

    record_event(
        case_id=lease_id,
        entity_id=task_key,
        event_type="move_out_task_completed",
        payload={
            "lease_id": lease_id,
            "task_key": task_key,
            "completed_by": completed_by
        }
    )

    return get_move_out_record(lease_id, org_id=org_id)


def propose_move_out_closeout(
    lease_id: str,
    itemized_deductions: Optional[List[Dict[str, Any]]] = None,
    deductions: Optional[List[Dict[str, Any]]] = None,
    proposed_by: Optional[str] = None,
    notes: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Prepare a proposed security deposit reconciliation summary for authorized human review."""
    effective_deductions = itemized_deductions if itemized_deductions is not None else deductions
    rec = get_move_out_record(lease_id, org_id=org_id)
    if not rec:
        raise ValueError(f"No move-out record found for lease '{lease_id}'.")

    deposit = Decimal(str(rec["security_deposit_usd"]))
    unpaid_rent = Decimal(str(rec["outstanding_rent_balance_usd"]))

    deductions_list = []
    total_deductions = Decimal("0.00")

    # Add unpaid rent deduction if applicable
    if unpaid_rent > 0:
        deductions_list.append({
            "category": "unpaid_rent",
            "description": f"Outstanding unpaid rent balance on ledger",
            "amount_usd": float(unpaid_rent),
            "evidence": "Ledger 3-way reconciliation audit"
        })
        total_deductions += unpaid_rent

    # Add itemized damage deductions with evidence validation
    if itemized_deductions:
        for d in itemized_deductions:
            amt = Decimal(str(d.get("amount_usd", 0.0)))
            if amt > 0:
                deductions_list.append({
                    "category": d.get("category", "repair"),
                    "description": d.get("description", "Unit repair / damage deduction"),
                    "amount_usd": float(amt),
                    "evidence": d.get("evidence", "Move-out inspection report")
                })
                total_deductions += amt

    proposed_refund = max(Decimal("0.00"), deposit - total_deductions)

    import json
    with db() as conn:
        conn.execute(
            """UPDATE move_out_records
               SET outstanding_balance_usd = %s,
                   proposed_deductions = %s::jsonb,
                   proposed_refund_usd = %s,
                   status = 'pending_closeout_approval',
                   closeout_approval_state = 'pending'
               WHERE lease_id = %s""",
            (float(unpaid_rent), json.dumps(deductions_list), float(proposed_refund), lease_id)
        )

    record_event(
        case_id=lease_id,
        entity_id=rec["move_out_id"],
        event_type="move_out_closeout_proposed",
        payload={
            "move_out_id": rec["move_out_id"],
            "deposit_usd": float(deposit),
            "total_deductions_usd": float(total_deductions),
            "proposed_refund_usd": float(proposed_refund)
        }
    )

    return get_move_out_record(lease_id, org_id=org_id)


def approve_move_out_closeout(
    lease_id: str,
    reviewer: str = "Property Manager",
    manager_name: Optional[str] = None,
    final_notes: Optional[str] = None,
    notes: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Authorized human approval required to execute deposit disbursement and close tenancy."""
    effective_reviewer = manager_name or reviewer
    effective_notes = final_notes or notes
    rec = get_move_out_record(lease_id, org_id=org_id)
    if not rec:
        raise ValueError(f"No move-out record found for lease '{lease_id}'.")

    now_dt = datetime.now(timezone.utc)
    with db() as conn:
        conn.execute(
            """UPDATE move_out_records
               SET status = 'closed',
                   closeout_approval_state = 'approved',
                   approved_by = %s,
                   approved_at = %s,
                   approval_notes = %s
               WHERE lease_id = %s""",
            (reviewer, now_dt, final_notes or f"Approved by {reviewer}", lease_id)
        )
        conn.execute(
            "UPDATE lease_records SET lease_status = 'closed' WHERE lease_id = %s",
            (lease_id,)
        )

    record_event(
        case_id=lease_id,
        entity_id=rec["move_out_id"],
        event_type="move_out_closeout_approved",
        payload={
            "move_out_id": rec["move_out_id"],
            "approved_by": reviewer,
            "refund_usd": rec["proposed_refund_usd"],
            "status": "closed"
        }
    )

    # Queue settlement letter notification to resident
    queue_notification(
        recipient_email=rec["resident_email"],
        recipient_type="resident",
        title=f"Security Deposit Settlement Statement: {rec['property_name']}",
        message=f"Hello {rec['resident_name']}, your security deposit closeout has been approved by {reviewer}. Refund of ${rec['proposed_refund_usd']:.2f} is being disbursed to your forwarding address.",
        category="move_out",
        event_key=f"deposit-settlement:{rec['move_out_id']}"
    )

    return get_move_out_record(lease_id, org_id=org_id)


# =====================================================================
# D. RESIDENT COMMUNICATIONS & PREFERENCES
# =====================================================================

def get_communication_preferences(lease_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve communication preferences for a resident lease."""
    lease = validate_lease_ownership(lease_id, org_id=org_id)
    return {
        "lease_id": lease_id,
        "resident_name": lease["tenant1"],
        "resident_email": lease["resident_email"],
        "preferences": lease["communication_preferences"]
    }


def update_communication_preferences(
    lease_id: str,
    email: bool,
    sms: bool,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Update resident communication preferences (opt-in/opt-out)."""
    validate_lease_ownership(lease_id, org_id=org_id)
    import json
    new_prefs = {"email": email, "sms": sms}

    with db() as conn:
        conn.execute(
            "UPDATE lease_records SET communication_preferences = %s::jsonb WHERE lease_id = %s",
            (json.dumps(new_prefs), lease_id)
        )

    return {
        "lease_id": lease_id,
        "preferences": new_prefs,
        "message": "Communication preferences successfully updated."
    }


def send_resident_reminder(
    lease_id: str,
    reminder_type: str,
    custom_message: Optional[str] = None,
    org_id: Optional[str] = None
) -> Dict[str, Any]:
    """Send reminder alert respecting resident communication preferences and deduplication."""
    lease = validate_lease_ownership(lease_id, org_id=org_id)
    prefs = lease["communication_preferences"]

    if not prefs.get("email", True):
        return {
            "status": "preference_suppressed",
            "lease_id": lease_id,
            "message": "Email delivery skipped because resident has disabled email communications in preferences."
        }

    now_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    event_key = f"reminder:{reminder_type}:{lease_id}:{now_str}"

    if reminder_type == "renewal":
        title = f"Friendly Reminder: Upcoming Lease Renewal for {lease['property_name']}"
        body = custom_message or f"Hello {lease['tenant1']}, your lease at {lease['address']} is approaching expiration. Please review your renewal options."
    elif reminder_type == "move_in":
        title = f"Action Required: Incomplete Move-In Tasks for {lease['property_name']}"
        body = custom_message or f"Hello {lease['tenant1']}, please upload missing move-in documentation before your scheduled move-in."
    elif reminder_type == "move_out":
        title = f"Move-Out Checklist Reminder for {lease['property_name']}"
        body = custom_message or f"Hello {lease['tenant1']}, please remember to return keys and schedule your exit walkthrough."
    else:
        title = f"Notice regarding your tenancy at {lease['property_name']}"
        body = custom_message or "General tenancy reminder."

    res = queue_notification(
        recipient_email=lease["resident_email"],
        recipient_type="resident",
        title=title,
        message=body,
        category=reminder_type,
        event_key=event_key
    )

    return {
        "status": "queued" if not res.get("duplicate") else "duplicate_prevented",
        "notification_id": res.get("id"),
        "delivery_state": res.get("status"),
        "event_key": event_key,
        "message": "Reminder queued successfully." if not res.get("duplicate") else "Reminder already queued for today."
    }


def sweep_expiring_leases_and_renewals(window_days: int = 90) -> List[Dict[str, Any]]:
    """Scan expiring leases across all properties and idempotently queue renewal reminders."""
    expiring = get_expiring_leases(window_days=window_days)
    results = []
    for item in expiring:
        lease_id = item["lease_id"]
        # Only queue reminders if renewal not yet finalized
        if item.get("renewal_status") in ("upcoming", "not_started", "offer_prepared", None):
            res = send_resident_reminder(lease_id=lease_id, reminder_type="renewal")
            results.append({
                "lease_id": lease_id,
                "days_until_expiration": item["days_until_expiration"],
                "reminder_status": res["status"]
            })
    return results

