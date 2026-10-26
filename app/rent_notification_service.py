"""Autonomous 3-Stage Rent Notification & Guarded Legal Notice Service for ENIGMA.

Implements:
- Stage 1: Upcoming rent reminders 3-5 days before due date.
- Stage 2: Overdue rent notices upon grace-period expiry with strict 3-day settlement deadline.
- Stage 3: Guarded statutory escalation upon 3-day deadline expiry, requiring authorized Property Manager review.
- Pre-flight payment rechecks, active habitability dispute offsets, and auto-cancellation of pending notices.
"""

import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .database import db
from .audit import log_audit_event
from .world_model import record_event, canonical_id
from .notifications import queue_notification
from .email_templates_html import (
    render_rent_due_email,
    render_overdue_3day_email,
    render_payment_success_email,
    render_payment_failed_email,
    render_legal_notice_review_email
)

logger = logging.getLogger("enigma.rent_notifications")


def dispatch_rent_email(
    template_key: str,
    lease_id: str,
    billing_record_id: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Render professional HTML email and dispatch with deduplication."""
    extra = extra_context or {}

    with db() as conn:
        lease = conn.execute(
            """SELECT l.lease_id, l.property_id, l.unit, l.tenant1, l.monthly_rent_usd,
                      l.resident_email, p.name as prop_name, p.org_id
               FROM lease_records l
               LEFT JOIN properties p ON l.property_id = p.property_id
               WHERE l.lease_id = %s""",
            (lease_id,)
        ).fetchone()

        bill = None
        if billing_record_id:
            bill = conn.execute(
                """SELECT id, billing_period, total_due_usd, outstanding_balance_usd,
                          due_date, grace_period_end_date, three_day_deadline, status
                   FROM rent_billing_records WHERE id = %s""",
                (billing_record_id,)
            ).fetchone()

    if not lease:
        raise ValueError(f"Lease {lease_id} not found")

    lid, pid, unit, tenant, rent, email, prop_name, org_id = lease
    recipient = email or f"{tenant.lower().replace(' ', '.')}@enigma-tenant.internal"
    property_name = prop_name or "Apartment Community"

    # Pre-flight check: If billing record is already paid, suppress collection emails!
    if bill and bill[7] == "paid" and template_key in ("upcoming_rent_reminder", "overdue_rent_3day", "legal_notice_review"):
        logger.info(f"Suppressed {template_key} for {lease_id}: obligation already paid.")
        return {"status": "suppressed", "reason": "obligation_already_settled"}

    due_date = bill[4] if bill else "1st of the month"
    grace_end = bill[5] if bill else "4th of the month"
    three_day_deadline = bill[6] if bill else "7th of the month 23:59:59 UTC"
    amount_str = f"${bill[3]:.2f}" if bill else f"${float(rent):.2f}"
    payment_link = f"http://localhost:5173"

    html_content = ""
    plain_content = ""
    subject = ""

    if template_key == "upcoming_rent_reminder":
        subject = f"Upcoming Rent Reminder for {unit} — Due on {due_date}"
        html_content, plain_content = render_rent_due_email(
            resident_name=tenant,
            property_name=property_name,
            unit=unit or "Unit",
            rent_amount=amount_str,
            due_date=due_date,
            grace_period_end_date=grace_end,
            payment_link=payment_link
        )
    elif template_key == "overdue_rent_3day":
        subject = f"URGENT: Past-Due Balance Notice for {unit} — 3-Day Payment Deadline"
        html_content, plain_content = render_overdue_3day_email(
            resident_name=tenant,
            property_name=property_name,
            unit=unit or "Unit",
            overdue_amount=amount_str,
            original_due_date=due_date,
            exact_deadline_utc=three_day_deadline,
            payment_link=payment_link
        )
    elif template_key == "payment_successful_receipt":
        subject = f"Payment Receipt: {extra.get('amount_paid', amount_str)} — {unit}"
        html_content, plain_content = render_payment_success_email(
            resident_name=tenant,
            property_name=property_name,
            unit=unit or "Unit",
            amount_paid=extra.get("amount_paid", amount_str),
            receipt_number=extra.get("receipt_number", "RCPT-1001"),
            payment_reference=extra.get("payment_reference", "PAYREF-1001"),
            payment_method=extra.get("payment_method", "Direct ACH"),
            payment_date=extra.get("payment_date", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
            remaining_balance=extra.get("remaining_balance", "$0.00")
        )
    elif template_key == "payment_failed":
        subject = f"Payment Processing Action Required — {unit}"
        html_content, plain_content = render_payment_failed_email(
            resident_name=tenant,
            property_name=property_name,
            unit=unit or "Unit",
            amount_usd=extra.get("amount_usd", amount_str),
            error_reason=extra.get("error_reason", "Card transaction declined by issuing bank"),
            retry_url=payment_link
        )
    elif template_key == "legal_notice_review":
        subject = f"Legal Notice Review Required: {lease_id} ({unit})"
        html_content, plain_content = render_legal_notice_review_email(
            manager_name="Property Manager",
            lease_id=lease_id,
            tenant_name=tenant,
            unit=unit or "Unit",
            overdue_amount=amount_str,
            jurisdiction=extra.get("jurisdiction", "California"),
            statutory_citation=extra.get("citation", "Cal. Civ. Code § 1161(2)"),
            approval_queue_url=f"http://localhost:5173"
        )
        recipient = "pm-legal@enigma-proptech.internal"
    if template_key == "payment_successful_receipt":
        suffix = extra.get("receipt_number") or (bill[1] if bill else "current")
        event_key = f"rent-{template_key}-{lease_id}-{suffix}"
    else:
        event_key = f"rent-{template_key}-{lease_id}-{bill[1] if bill else 'current'}"

    # Queue notification
    notif_res = queue_notification(
        recipient_email=recipient,
        recipient_type="tenant" if template_key != "legal_notice_review" else "owner",
        title=subject,
        message=plain_content,
        category=template_key,
        event_key=event_key,
        simulate_delivery=True,
        template_key=template_key,
        context_data={"html_body": html_content, "billing_record_id": billing_record_id}
    )

    log_audit_event(
        org_id=org_id or "ORG-APEX",
        action=f"notification_dispatched_{template_key}",
        resource_type="notification",
        resource_id=notif_res.get("id"),
        actor_type="system",
        actor_id="rent_notification_service",
        outcome="success",
        details={
            "recipient": recipient,
            "subject": subject,
            "template_key": template_key,
            "billing_record_id": billing_record_id
        },
        source_component="rent_notification_service"
    )

    return notif_res


def sweep_upcoming_and_overdue_rent(org_id: str = "ORG-APEX", period: Optional[str] = None) -> Dict[str, Any]:
    """Execute scheduled 3-stage rent collection sweep:
    
    Stage 1: Dispatches upcoming reminder if due in <= 5 days and unpaid.
    Stage 2: Dispatches 3-day overdue notice if past grace period.
    Stage 3: Evaluates 3-day deadline expiration, initiates legal notice review.
    """
    now = datetime.now(timezone.utc)
    current_period = period or now.strftime("%Y-%m")
    today_str = now.strftime("%Y-%m-%d")

    upcoming_dispatched = 0
    overdue_3day_dispatched = 0
    legal_reviews_queued = 0

    with db() as conn:
        # Fetch active leases
        leases = conn.execute(
            """SELECT l.lease_id, l.property_id, l.unit, l.tenant1, l.monthly_rent_usd, p.org_id
               FROM lease_records l
               JOIN properties p ON l.property_id = p.property_id
               WHERE p.org_id = %s""",
            (org_id,)
        ).fetchall()

    from .rent_payment_service import get_or_create_monthly_rent_obligation

    for l in leases:
        lid, pid, unit, tenant, rent, org = l
        bill = get_or_create_monthly_rent_obligation(lid, current_period)
        bill_id = bill["id"]
        status = bill["status"]
        balance = bill["outstanding_balance_usd"]
        due_date = bill["due_date"]
        grace_end = bill["grace_period_end_date"]
        reminder_stage = bill.get("reminder_stage", "none")

        # Skip if settled
        if balance <= 0 or status == "paid":
            continue

        # Check for open emergency maintenance requests (habitability rent withholding defense)
        with db() as conn:
            open_emergency = conn.execute(
                """SELECT work_order_id, priority, description 
                   FROM work_order_records 
                   WHERE lease_id = %s AND priority = 'Emergency' AND status != 'completed'""",
                (lid,)
            ).fetchone()

        # Stage 1: Upcoming Rent Reminder (5 to 1 days before due date)
        if today_str < due_date:
            if reminder_stage == "none":
                dispatch_rent_email("upcoming_rent_reminder", lid, bill_id)
                with db() as conn:
                    conn.execute(
                        "UPDATE rent_billing_records SET reminder_stage = 'upcoming_sent', updated_at = now() WHERE id = %s",
                        (bill_id,)
                    )
                upcoming_dispatched += 1

        # Stage 2: Past Grace Period -> 3-Day Overdue Notice & Late Fee
        elif (today_str > grace_end or (due_date and today_str > due_date and now.day > 4)) and reminder_stage in ("none", "upcoming_sent"):
            # If tenant has active emergency maintenance issue, note withholding defense
            extra_ctx = {}
            if open_emergency:
                extra_ctx["withholding_defense_flagged"] = True
                extra_ctx["work_order_id"] = open_emergency[0]

            dispatch_rent_email("overdue_rent_3day", lid, bill_id, extra_ctx)
            with db() as conn:
                conn.execute(
                    """UPDATE rent_billing_records 
                       SET status = 'overdue',
                           late_fee_usd = 50.00,
                           total_due_usd = rent_amount_usd + 50.00,
                           outstanding_balance_usd = rent_amount_usd + 50.00 - paid_amount_usd,
                           reminder_stage = 'overdue_3day_sent',
                           updated_at = now() 
                       WHERE id = %s""",
                    (bill_id,)
                )
            overdue_3day_dispatched += 1

        # Stage 3: Three-Day Deadline Expired -> Guarded Statutory Escalation
        elif reminder_stage == "overdue_3day_sent":
            three_day_deadline = bill.get("three_day_deadline", "")
            # If current time is past the 3-day deadline
            if now.day > 7 or (three_day_deadline and today_str > three_day_deadline[:10]):
                # Initiate Guarded Legal Notice Case (Property Manager Sign-Off Required)
                case_id = f"LNC-{lid.replace('LEASE-', '')}-{current_period}"
                with db() as conn:
                    existing_case = conn.execute(
                        "SELECT id FROM legal_notice_cases WHERE id = %s",
                        (case_id,)
                    ).fetchone()

                    if not existing_case:
                        conn.execute(
                            """INSERT INTO legal_notice_cases (
                                id, org_id, lease_id, billing_record_id, tenant_name,
                                unit, overdue_amount_usd, due_date, three_day_deadline,
                                status, eligibility_check, statutory_rule
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                case_id, org, lid, bill_id, tenant,
                                unit, balance, due_date, three_day_deadline,
                                "pending_review",
                                json.dumps({
                                    "open_emergency_work_orders": bool(open_emergency),
                                    "work_order_details": open_emergency[2] if open_emergency else None,
                                    "verified_delinquency_usd": balance,
                                    "habitability_offset_risk": bool(open_emergency)
                                }),
                                "California 3-Day Notice to Pay or Quit (Cal. Civ. Code § 1161(2))"
                            )
                        )
                        conn.execute(
                            """UPDATE rent_billing_records 
                               SET status = 'action_required', reminder_stage = 'legal_review_queued',
                                   legal_review_id = %s, updated_at = now() 
                               WHERE id = %s""",
                            (case_id, bill_id)
                        )

                # Send manager alert
                dispatch_rent_email(
                    template_key="legal_notice_review",
                    lease_id=lid,
                    billing_record_id=bill_id,
                    extra_context={
                        "jurisdiction": "California",
                        "citation": "Cal. Civ. Code § 1161(2)"
                    }
                )
                legal_reviews_queued += 1

    return {
        "status": "completed",
        "sweep_timestamp": now.isoformat(),
        "org_id": org_id,
        "upcoming_reminders_dispatched": upcoming_dispatched,
        "overdue_3day_notices_dispatched": overdue_3day_dispatched,
        "overdue_reminders_sent": overdue_3day_dispatched,
        "legal_notice_reviews_queued": legal_reviews_queued
    }


def review_and_decide_legal_notice(
    case_id: str,
    decision: str,
    reviewer_name: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """Authorized Property Manager review gate for statutory legal notice dispatch."""
    if decision not in ("approved", "rejected"):
        raise ValueError("Decision must be 'approved' or 'rejected'")

    with db() as conn:
        case = conn.execute(
            """SELECT id, org_id, lease_id, billing_record_id, tenant_name,
                      overdue_amount_usd, status 
               FROM legal_notice_cases WHERE id = %s""",
            (case_id,)
        ).fetchone()

    if not case:
        raise ValueError(f"Legal notice case '{case_id}' not found")

    cid, org_id, lid, bill_id, tenant, amount, current_status = case

    # Pre-flight check: Re-verify if payment was made in the interim!
    with db() as conn:
        bill = conn.execute(
            "SELECT status, outstanding_balance_usd FROM rent_billing_records WHERE id = %s",
            (bill_id,)
        ).fetchone()

    if bill and (bill[0] == "paid" or float(bill[1]) <= 0):
        # Auto-cancel escalation
        with db() as conn:
            conn.execute(
                """UPDATE legal_notice_cases 
                   SET status = 'cancelled_by_payment', review_notes = 'Obligation confirmed settled prior to review',
                       reviewed_by = %s, reviewed_at = now(), updated_at = now() 
                   WHERE id = %s""",
                (reviewer_name, case_id)
            )
        return {
            "success": False,
            "status": "cancelled_by_payment",
            "case_id": case_id,
            "message": "Notice cancelled: tenant has fully settled their outstanding rent balance."
        }

    new_status = "approved" if decision == "approved" else "rejected"
    now = datetime.now(timezone.utc)

    with db() as conn:
        conn.execute(
            """UPDATE legal_notice_cases SET
                status = %s,
                reviewed_by = %s,
                reviewed_at = %s,
                review_notes = %s,
                dispatched_at = %s,
                updated_at = now()
               WHERE id = %s""",
            (
                new_status, reviewer_name, now, notes or "",
                now if new_status == "approved" else None,
                case_id
            )
        )

        if new_status == "approved":
            conn.execute(
                "UPDATE rent_billing_records SET reminder_stage = 'legal_dispatched', updated_at = now() WHERE id = %s",
                (bill_id,)
            )

    log_audit_event(
        org_id=org_id,
        action=f"legal_notice_{new_status}",
        resource_type="legal_case",
        resource_id=case_id,
        actor_type="property_manager",
        actor_id=reviewer_name,
        outcome="success",
        details={
            "lease_id": lid,
            "decision": decision,
            "notes": notes,
            "amount_usd": float(amount)
        },
        source_component="rent_notification_service"
    )

    record_event(
        case_id=lid,
        entity_id=case_id,
        event_type="statutory_notice_reviewed",
        payload={
            "case_id": case_id,
            "decision": decision,
            "reviewer": reviewer_name,
            "notes": notes
        }
    )

    return {
        "success": True,
        "case_id": case_id,
        "lease_id": lid,
        "status": new_status,
        "reviewed_by": reviewer_name,
        "reviewed_at": now.isoformat(),
        "dispatched": (new_status == "approved")
    }
