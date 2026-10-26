"""Authoritative Monthly Rent Payment Lifecycle and Synchronization Service for ENIGMA.

Implements:
- Server-side payment eligibility enforcement (no premature payments, no double charges).
- Authoritative state machine: Upcoming -> Due -> Processing -> Paid / Overdue -> Action Required.
- Single atomic database synchronization across billing records, ledger payments, and bank transactions.
- Auto-cancellation of pending overdue escalations upon full payment confirmation.
- Full audit event emission and World Model event sourcing.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .database import db
from .audit import log_audit_event
from .world_model import record_event, canonical_id
from .payment_gateway import default_gateway


def get_current_billing_period() -> str:
    """Return default active billing month in YYYY-MM format."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def calculate_period_dates(billing_period: str) -> Tuple[str, str, str]:
    """Calculate due date, grace period end date, and 3-day deadline for a billing period.
    
    Default rule:
    - Due Date: 1st of the month
    - Grace Period: 3 calendar days (ends 4th at 23:59:59 UTC)
    - 3-Day Overdue Deadline: 7th at 23:59:59 UTC
    """
    try:
        parts = billing_period.split("-")
        year, month = int(parts[0]), int(parts[1])
        base_date = datetime(year, month, 1, tzinfo=timezone.utc)
    except Exception:
        now = datetime.now(timezone.utc)
        base_date = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    due_date = base_date.strftime("%Y-%m-01")
    grace_end = (base_date + timedelta(days=3)).strftime("%Y-%m-04")
    three_day_deadline = (base_date + timedelta(days=6)).strftime("%Y-%m-07 23:59:59 UTC")
    return due_date, grace_end, three_day_deadline


def get_or_create_monthly_rent_obligation(
    lease_id: str,
    billing_period: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve or initialize the authoritative rent billing record for a lease and month."""
    period = billing_period or get_current_billing_period()

    with db() as conn:
        # Check existing
        existing = conn.execute(
            """SELECT id, lease_id, property_id, unit, tenant_name, billing_period,
                      rent_amount_usd, late_fee_usd, total_due_usd, paid_amount_usd,
                      outstanding_balance_usd, due_date, grace_period_end_date,
                      three_day_deadline, status, payment_method, payment_transaction_id,
                      payment_reference, receipt_number, paid_at, reminder_stage
               FROM rent_billing_records 
               WHERE lease_id = %s AND billing_period = %s""",
            (lease_id, period)
        ).fetchone()

        if existing:
            return _format_billing_record(existing)

        # Look up lease terms
        lease = conn.execute(
            """SELECT l.lease_id, l.property_id, l.unit, l.tenant1, l.monthly_rent_usd, p.org_id
               FROM lease_records l
               LEFT JOIN properties p ON l.property_id = p.property_id
               WHERE l.lease_id = %s""",
            (lease_id,)
        ).fetchone()

    if not lease:
        raise ValueError(f"Lease '{lease_id}' not found")

    lid, prop_id, unit, tenant1, rent_amount, org_id = lease
    due_date, grace_end, three_day_deadline = calculate_period_dates(period)
    bill_id = f"BILL-{lid.replace('LEASE-', '')}-{period}"
    rent_val = float(rent_amount)

    # Initial status evaluation based on current date
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    
    # Within 5 days before 1st or current month?
    if today_str < due_date:
        initial_status = "upcoming"
    elif today_str <= grace_end:
        initial_status = "due"
    elif today_str <= three_day_deadline[:10]:
        initial_status = "overdue"
    else:
        initial_status = "action_required"

    with db() as conn:
        conn.execute(
            """INSERT INTO rent_billing_records (
                id, lease_id, property_id, unit, tenant_name, billing_period,
                rent_amount_usd, late_fee_usd, total_due_usd, paid_amount_usd,
                outstanding_balance_usd, due_date, grace_period_end_date,
                three_day_deadline, status, reminder_stage
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (lease_id, billing_period) DO NOTHING""",
            (
                bill_id, lid, prop_id, unit, tenant1, period,
                rent_val, 0.0, rent_val, 0.0,
                rent_val, due_date, grace_end,
                three_day_deadline, initial_status, "none"
            )
        )

    log_audit_event(
        org_id=org_id or "ORG-APEX",
        action="rent_obligation_created",
        resource_type="billing_record",
        resource_id=bill_id,
        actor_type="system",
        actor_id="rent_payment_service",
        outcome="success",
        details={
            "lease_id": lid,
            "period": period,
            "amount_usd": rent_val,
            "due_date": due_date
        },
        source_component="rent_payment_service"
    )

    with db() as conn:
        record = conn.execute(
            """SELECT id, lease_id, property_id, unit, tenant_name, billing_period,
                      rent_amount_usd, late_fee_usd, total_due_usd, paid_amount_usd,
                      outstanding_balance_usd, due_date, grace_period_end_date,
                      three_day_deadline, status, payment_method, payment_transaction_id,
                      payment_reference, receipt_number, paid_at, reminder_stage
               FROM rent_billing_records WHERE id = %s""",
            (bill_id,)
        ).fetchone()

    return _format_billing_record(record)


def _format_billing_record(row: Any) -> Dict[str, Any]:
    """Format row tuple into clean dictionary."""
    return {
        "id": row[0],
        "lease_id": row[1],
        "property_id": row[2],
        "unit": row[3],
        "tenant_name": row[4],
        "billing_period": row[5],
        "rent_amount_usd": float(row[6]),
        "late_fee_usd": float(row[7]),
        "total_due_usd": float(row[8]),
        "paid_amount_usd": float(row[9]),
        "outstanding_balance_usd": float(row[10]),
        "due_date": row[11],
        "grace_period_end_date": row[12],
        "three_day_deadline": row[13],
        "status": row[14],
        "payment_method": row[15],
        "payment_transaction_id": row[16],
        "payment_reference": row[17],
        "receipt_number": row[18],
        "paid_at": row[19].isoformat() if hasattr(row[19], "isoformat") else (str(row[19]) if row[19] else None),
        "reminder_stage": row[20]
    }


def get_tenant_rent_dashboard(lease_id: str, period: Optional[str] = None) -> Dict[str, Any]:
    """Provide comprehensive tenant rent dashboard with strict backend eligibility gates."""
    current_period = period or get_current_billing_period()
    current_bill = get_or_create_monthly_rent_obligation(lease_id, current_period)

    with db() as conn:
        prop = conn.execute(
            """SELECT p.name, p.address, p.city, p.state, p.zip_code, l.monthly_rent_usd, l.tenant1
               FROM lease_records l
               LEFT JOIN properties p ON l.property_id = p.property_id
               WHERE l.lease_id = %s""",
            (lease_id,)
        ).fetchone()

        # All history for this lease
        history_rows = conn.execute(
            """SELECT id, billing_period, rent_amount_usd, late_fee_usd, total_due_usd,
                      paid_amount_usd, outstanding_balance_usd, status, payment_method,
                      receipt_number, paid_at, payment_reference
               FROM rent_billing_records 
               WHERE lease_id = %s 
               ORDER BY billing_period DESC""",
            (lease_id,)
        ).fetchall()

        # Pending session if any
        pending_tx = conn.execute(
            """SELECT id, amount_usd, status, created_at 
               FROM payment_gateway_transactions 
               WHERE lease_id = %s AND status = 'pending' 
               ORDER BY created_at DESC LIMIT 1""",
            (lease_id,)
        ).fetchone()

    history = []
    for h in history_rows:
        history.append({
            "billing_record_id": h[0],
            "billing_period": h[1],
            "rent_amount_usd": float(h[2]),
            "late_fee_usd": float(h[3]),
            "total_due_usd": float(h[4]),
            "paid_amount_usd": float(h[5]),
            "outstanding_balance_usd": float(h[6]),
            "status": h[7],
            "payment_method": h[8],
            "receipt_number": h[9],
            "paid_at": h[10].isoformat() if hasattr(h[10], "isoformat") else str(h[10]) if h[10] else None,
            "payment_reference": h[11]
        })

    # Eligibility rules
    status = current_bill["status"]
    is_paid = (status == "paid" or current_bill["outstanding_balance_usd"] <= 0)
    is_processing = (status == "processing")
    is_upcoming = (status == "upcoming")

    payment_eligible = (not is_paid and not is_processing and not is_upcoming)
    blocked_reason = None
    if is_paid:
        blocked_reason = "Rent for current billing period has been fully settled."
    elif is_processing:
        blocked_reason = "A payment is currently being processed by the payment network. Please check status."
    elif is_upcoming:
        blocked_reason = f"Payment opens 5 days prior to due date ({current_bill['due_date']})."

    property_info = {
        "name": prop[0] if prop else "Apartment Community",
        "address": prop[1] if prop else "On file",
        "city": prop[2] if prop else "Metropolis",
        "state": prop[3] if prop else "CA",
        "zip_code": prop[4] if prop else "90001",
        "monthly_rent_usd": float(prop[5]) if prop else current_bill["rent_amount_usd"],
        "resident_name": prop[6] if prop else current_bill["tenant_name"]
    }

    return {
        "lease_id": lease_id,
        "property": property_info,
        "current_bill": current_bill,
        "payment_eligibility": {
            "eligible": payment_eligible,
            "can_pay": payment_eligible,
            "button_text": "Pay Rent" if payment_eligible else ("Rent Paid" if is_paid else "Upcoming"),
            "blocked_reason": blocked_reason,
            "reason": blocked_reason,
            "can_retry": (status == "failed")
        },
        "pending_transaction": {
            "session_id": pending_tx[0],
            "amount_usd": float(pending_tx[1]),
            "status": pending_tx[2]
        } if pending_tx else None,
        "payment_history": history
    }


def initiate_tenant_rent_payment(
    lease_id: str,
    billing_record_id: str,
    amount_usd: float,
    customer_email: str,
    payment_method: str = "ach_transfer",
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """Initiate checkout session with server-side validation and idempotency."""
    if amount_usd <= 0:
        raise ValueError("Payment amount must be greater than $0.00")

    with db() as conn:
        bill = conn.execute(
            """SELECT id, lease_id, outstanding_balance_usd, status, billing_period, property_id 
               FROM rent_billing_records WHERE id = %s""",
            (billing_record_id,)
        ).fetchone()

        prop = conn.execute(
            "SELECT org_id FROM properties WHERE property_id = %s",
            (bill[5],) if bill else ("",)
        ).fetchone()

    if not bill or bill[1] != lease_id:
        raise ValueError("Invalid billing record for lease")

    bill_id, lid, balance, status, period, prop_id = bill
    org_id = prop[0] if prop else "ORG-APEX"

    if status == "paid" or float(balance) <= 0:
        raise ValueError("Rent for this period has already been paid in full.")

    if status == "processing":
        # Check if there is an existing pending session with this idempotency key
        if idempotency_key:
            existing_sess = default_gateway.create_checkout_session(
                lease_id=lid,
                billing_record_id=bill_id,
                amount_usd=amount_usd,
                org_id=org_id,
                customer_email=customer_email,
                idempotency_key=idempotency_key
            )
            return existing_sess

    # Mark billing record processing
    with db() as conn:
        conn.execute(
            "UPDATE rent_billing_records SET status = 'processing', updated_at = now() WHERE id = %s",
            (bill_id,)
        )

    # Create session via gateway
    session = default_gateway.create_checkout_session(
        lease_id=lid,
        billing_record_id=bill_id,
        amount_usd=amount_usd,
        org_id=org_id,
        customer_email=customer_email,
        idempotency_key=idempotency_key
    )

    log_audit_event(
        org_id=org_id,
        action="rent_payment_initiated",
        resource_type="billing_record",
        resource_id=bill_id,
        actor_type="tenant",
        actor_id=customer_email,
        outcome="success",
        details={
            "session_id": session["session_id"],
            "amount_usd": amount_usd,
            "period": period,
            "payment_method": payment_method
        },
        source_component="rent_payment_service"
    )

    return session


def synchronize_confirmed_payment(
    session_id: str,
    payment_method: str = "ach_transfer",
    reference: Optional[str] = None
) -> Dict[str, Any]:
    """Execute authoritative atomic database synchronization for a confirmed payment."""
    with db() as conn:
        tx = conn.execute(
            """SELECT id, lease_id, billing_record_id, org_id, amount_usd, status 
               FROM payment_gateway_transactions WHERE id = %s""",
            (session_id,)
        ).fetchone()

    if not tx:
        raise ValueError(f"Gateway transaction '{session_id}' not found")

    tx_id, lease_id, billing_id, org_id, amount_usd, tx_status = tx
    amount_val = float(amount_usd)

    receipt_no = f"RCPT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    pay_ref = reference or f"PAYREF-{uuid.uuid4().hex[:8].upper()}"
    pay_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    bank_id = f"BANK-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    with db() as conn:
        # 1. Update gateway transaction
        conn.execute(
            "UPDATE payment_gateway_transactions SET status = 'succeeded', updated_at = now() WHERE id = %s",
            (session_id,)
        )

        # 2. Update rent_billing_record
        bill = conn.execute(
            "SELECT total_due_usd, paid_amount_usd FROM rent_billing_records WHERE id = %s",
            (billing_id,)
        ).fetchone()

        if bill:
            total_due = float(bill[0])
            prev_paid = float(bill[1])
            new_paid = prev_paid + amount_val
            new_balance = max(0.0, round(total_due - new_paid, 2))
            new_status = "paid" if new_balance <= 0.01 else "due"

            conn.execute(
                """UPDATE rent_billing_records SET
                    paid_amount_usd = %s,
                    outstanding_balance_usd = %s,
                    status = %s,
                    payment_method = %s,
                    payment_transaction_id = %s,
                    payment_reference = %s,
                    receipt_number = %s,
                    paid_at = %s,
                    updated_at = now()
                   WHERE id = %s""",
                (
                    new_paid, new_balance, new_status,
                    payment_method, session_id, pay_ref,
                    receipt_no, now, billing_id
                )
            )

        # 3. Synchronize to historical payments & bank_transactions tables for 3-way match
        conn.execute(
            """INSERT INTO payments (id, lease_id, amount, currency, reference)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (pay_id, lease_id, amount_val, "USD", pay_ref)
        )
        conn.execute(
            """INSERT INTO bank_transactions (id, lease_id, amount, currency, reference)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (bank_id, lease_id, amount_val, "USD", pay_ref)
        )

        # 4. Auto-cancel any pending legal notice case for this billing record
        conn.execute(
            """UPDATE legal_notice_cases 
               SET status = 'cancelled_by_payment', review_notes = 'Obligation settled via verified payment', updated_at = now()
               WHERE billing_record_id = %s AND status = 'pending_review'""",
            (billing_id,)
        )

    # 5. Queue payment confirmation receipt email
    from .rent_notification_service import dispatch_rent_email
    try:
        dispatch_rent_email(
            template_key="payment_successful_receipt",
            lease_id=lease_id,
            billing_record_id=billing_id,
            extra_context={
                "amount_paid": f"${amount_val:.2f}",
                "receipt_number": receipt_no,
                "payment_reference": pay_ref,
                "payment_method": payment_method.replace("_", " ").title(),
                "payment_date": now.strftime("%B %d, %Y %H:%M UTC")
            }
        )
    except Exception as e:
        logger.warning(f"Receipt notification failed: {e}")

    # 6. Audit & World Model Event
    log_audit_event(
        org_id=org_id,
        action="rent_payment_confirmed",
        resource_type="billing_record",
        resource_id=billing_id,
        actor_type="system",
        actor_id="synchronize_confirmed_payment",
        outcome="success",
        details={
            "session_id": session_id,
            "amount_paid_usd": amount_val,
            "receipt_number": receipt_no,
            "reference": pay_ref,
            "payment_id": pay_id
        },
        source_component="rent_payment_service"
    )

    record_event(
        case_id=lease_id,
        entity_id=billing_id,
        event_type="rent_payment_settled",
        payload={
            "billing_record_id": billing_id,
            "amount_usd": amount_val,
            "receipt_number": receipt_no,
            "session_id": session_id,
            "reference": pay_ref
        }
    )

    return {
        "success": True,
        "status": "synchronized",
        "session_id": session_id,
        "billing_record_id": billing_id,
        "lease_id": lease_id,
        "amount_usd": amount_val,
        "receipt_number": receipt_no,
        "payment_reference": pay_ref,
        "new_billing_status": new_status,
        "remaining_balance_usd": new_balance
    }


def get_property_manager_collection_overview(org_id: str = "ORG-APEX") -> Dict[str, Any]:
    """Aggregate high-level accounts receivable and rent collection metrics for property managers."""
    current_period = get_current_billing_period()

    with db() as conn:
        # All billing records for current period within org
        query = """
            SELECT r.id, r.lease_id, r.tenant_name, r.unit, r.total_due_usd,
                   r.paid_amount_usd, r.outstanding_balance_usd, r.status,
                   r.due_date, r.three_day_deadline, r.receipt_number,
                   p.name as property_name
            FROM rent_billing_records r
            JOIN properties p ON r.property_id = p.property_id
            WHERE r.billing_period = %s
        """
        params: List[Any] = [current_period]
        if org_id and org_id != "all":
            query += " AND p.org_id = %s"
            params.append(org_id)

        rows = conn.execute(query, params).fetchall()

        # Recent transactions
        tx_query = """
            SELECT t.id, t.lease_id, t.amount_usd, t.status, t.created_at, t.receipt_url,
                   b.tenant_name, b.unit
            FROM payment_gateway_transactions t
            JOIN rent_billing_records b ON t.billing_record_id = b.id
        """
        if org_id and org_id != "all":
            tx_query += " WHERE t.org_id = %s ORDER BY t.created_at DESC LIMIT 20"
            tx_rows = conn.execute(tx_query, (org_id,)).fetchall()
        else:
            tx_query += " ORDER BY t.created_at DESC LIMIT 20"
            tx_rows = conn.execute(tx_query).fetchall()

        # Legal notice queue
        ln_query = """
            SELECT l.id, l.lease_id, l.tenant_name, l.unit, l.overdue_amount_usd,
                   l.three_day_deadline, l.status, l.statutory_rule, l.created_at
            FROM legal_notice_cases l
        """
        if org_id and org_id != "all":
            ln_query += " WHERE l.org_id = %s ORDER BY l.created_at DESC"
            ln_rows = conn.execute(ln_query, (org_id,)).fetchall()
        else:
            ln_query += " ORDER BY l.created_at DESC"
            ln_rows = conn.execute(ln_query).fetchall()

    total_units = len(rows)
    total_billed = sum(float(r[4]) for r in rows)
    total_paid = sum(float(r[5]) for r in rows)
    total_outstanding = sum(float(r[6]) for r in rows)

    paid_count = sum(1 for r in rows if r[7] == "paid")
    due_count = sum(1 for r in rows if r[7] == "due")
    overdue_count = sum(1 for r in rows if r[7] in ("overdue", "action_required"))
    processing_count = sum(1 for r in rows if r[7] == "processing")
    upcoming_count = sum(1 for r in rows if r[7] == "upcoming")

    overdue_cases = []
    for r in rows:
        if r[7] in ("overdue", "action_required"):
            overdue_cases.append({
                "billing_record_id": r[0],
                "lease_id": r[1],
                "tenant_name": r[2],
                "unit": r[3],
                "total_due_usd": float(r[4]),
                "outstanding_balance_usd": float(r[6]),
                "status": r[7],
                "due_date": r[8],
                "three_day_deadline": r[9],
                "property_name": r[11]
            })

    transactions = []
    for t in tx_rows:
        transactions.append({
            "session_id": t[0],
            "lease_id": t[1],
            "amount_usd": float(t[2]),
            "status": t[3],
            "created_at": t[4].isoformat() if hasattr(t[4], "isoformat") else str(t[4]),
            "receipt_url": t[5],
            "tenant_name": t[6],
            "unit": t[7]
        })

    legal_cases = []
    for l in ln_rows:
        legal_cases.append({
            "case_id": l[0],
            "lease_id": l[1],
            "tenant_name": l[2],
            "unit": l[3],
            "overdue_amount_usd": float(l[4]),
            "three_day_deadline": l[5],
            "status": l[6],
            "statutory_rule": l[7],
            "created_at": l[8].isoformat() if hasattr(l[8], "isoformat") else str(l[8])
        })

    records = []
    for r in rows:
        records.append({
            "id": r[0],
            "lease_id": r[1],
            "tenant_name": r[2],
            "unit": r[3],
            "total_due_usd": float(r[4]),
            "rent_amount_usd": float(r[4]),
            "paid_amount_usd": float(r[5]),
            "outstanding_amount_usd": float(r[6]),
            "outstanding_balance_usd": float(r[6]),
            "status": r[7],
            "due_date": r[8],
            "three_day_deadline": r[9],
            "payment_reference": r[10],
            "property_name": r[11],
            "billing_period": current_period
        })

    totals = {
        "total_billed_usd": round(total_billed, 2),
        "total_collected_usd": round(total_paid, 2),
        "paid_count": paid_count,
        "due_count": due_count,
        "overdue_count": overdue_count,
        "processing_count": processing_count,
        "upcoming_count": upcoming_count,
        "paid_sum": round(total_paid, 2),
        "due_sum": round(sum(float(r[4]) for r in rows if r[7] == "due"), 2),
        "overdue_sum": round(sum(float(r[6]) for r in rows if r[7] in ("overdue", "action_required")), 2),
        "processing_sum": round(sum(float(r[4]) for r in rows if r[7] == "processing"), 2),
        "failed_count": sum(1 for r in rows if r[7] == "failed"),
        "failed_sum": round(sum(float(r[4]) for r in rows if r[7] == "failed"), 2),
    }

    return {
        "current_billing_period": current_period,
        "total_units": total_units,
        "total_billed_usd": round(total_billed, 2),
        "total_paid_usd": round(total_paid, 2),
        "total_outstanding_usd": round(total_outstanding, 2),
        "collection_rate_pct": round((total_paid / total_billed * 100) if total_billed > 0 else 0.0, 1),
        "totals": totals,
        "counts": {
            "paid": paid_count,
            "due": due_count,
            "overdue": overdue_count,
            "processing": processing_count,
            "upcoming": upcoming_count
        },
        "records": records,
        "overdue_cases": overdue_cases,
        "recent_transactions": transactions,
        "recent_payments": transactions,
        "legal_notice_queue": legal_cases,
        "legal_cases": legal_cases
    }
