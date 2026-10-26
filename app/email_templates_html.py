"""Professional, Responsive HTML Email Templates for ENIGMA.

Provides:
- Reusable, responsive HTML email layouts with modern branding (Navy, Blue, Teal, Coral, Emerald).
- Clear typography, itemized transaction tables, and high-visibility CTA buttons.
- Plain-text alternative generation for accessible, low-bandwidth, and spam-resilient delivery.
- 8 Distinct Visual Treatments:
    1. Rent Due Reminder
    2. Overdue Rent — 3-Day Payment Deadline
    3. Payment Successful Receipt
    4. Payment Failed / Action Required
    5. Payment Processing Update
    6. Legal Notice Review & Statutory Safeguard
    7. Property Manager Collection Alert
    8. General System Notification
"""

from typing import Any, Dict, List, Optional, Tuple


def _wrap_base_html(
    title: str,
    preheader: str,
    header_gradient: str,
    badge_label: str,
    badge_bg: str,
    badge_color: str,
    headline: str,
    lead_paragraph: str,
    meta_table_rows: List[Tuple[str, str]],
    cta_text: Optional[str] = None,
    cta_url: Optional[str] = None,
    cta_color: str = "#2563eb",
    callout_box_html: Optional[str] = None,
    footer_text: Optional[str] = None
) -> str:
    """Render responsive, accessible HTML email string with inline styles."""
    rows_html = ""
    for label, val in meta_table_rows:
        rows_html += f"""
        <tr>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; color: #64748b; font-size: 13px; font-weight: 500;">
                {label}
            </td>
            <td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; color: #0f172a; font-size: 13px; font-weight: 600; text-align: right;">
                {val}
            </td>
        </tr>
        """

    cta_html = ""
    if cta_text and cta_url:
        cta_html = f"""
        <div style="text-align: center; margin: 32px 0 24px;">
            <a href="{cta_url}" style="background-color: {cta_color}; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-size: 15px; font-weight: 700; display: inline-block; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); letter-spacing: 0.3px;">
                {cta_text} &rarr;
            </a>
        </div>
        """

    callout_html = ""
    if callout_box_html:
        callout_html = f"""
        <div style="margin: 24px 0;">
            {callout_box_html}
        </div>
        """

    footer_content = footer_text or "This is an automated communication from the ENIGMA Property Management Platform. Contact your property manager for questions or arrangements."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <!--[if mso]>
    <style type="text/css">
        table {{border-collapse:collapse;border-spacing:0;margin:0;}}
        div, td {{padding:0;}}
        div {{margin:0 !important;}}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; color: #1e293b;">
    <div style="display: none; font-size: 1px; color: #f1f5f9; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden;">
        {preheader}
    </div>
    
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f1f5f9; padding: 24px 12px;">
        <tr>
            <td align="center">
                <!-- Main Container -->
                <table role="presentation" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.07), 0 4px 6px -2px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;" cellspacing="0" cellpadding="0" border="0">
                    
                    <!-- Header -->
                    <tr>
                        <td style="background: {header_gradient}; padding: 28px 32px 24px; text-align: left;">
                            <table width="100%" cellspacing="0" cellpadding="0" border="0">
                                <tr>
                                    <td>
                                        <div style="font-size: 20px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">
                                            <span style="color: #38bdf8;">ENIGMA</span> PROPTECH
                                        </div>
                                        <div style="font-size: 12px; color: #cbd5e1; margin-top: 2px;">
                                            Autonomous Financial Operations & Resident Portal
                                        </div>
                                    </td>
                                    <td align="right">
                                        <span style="background-color: {badge_bg}; color: {badge_color}; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block;">
                                            {badge_label}
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 32px 32px 28px;">
                            <h1 style="margin: 0 0 12px; font-size: 22px; font-weight: 700; color: #0f172a; line-height: 1.3;">
                                {headline}
                            </h1>
                            <p style="margin: 0 0 24px; font-size: 15px; line-height: 1.6; color: #475569;">
                                {lead_paragraph}
                            </p>

                            {callout_html}

                            <!-- Details Table -->
                            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin: 20px 0; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #f8fafc; border-collapse: separate; overflow: hidden;">
                                {rows_html}
                            </table>

                            {cta_html}

                            <p style="font-size: 13px; color: #64748b; line-height: 1.5; margin: 24px 0 0;">
                                For assistance or accounting inquiries, contact your property management office through the resident portal.
                            </p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #0f172a; padding: 24px 32px; text-align: center; color: #94a3b8; font-size: 12px; line-height: 1.6;">
                            <div style="font-weight: 600; color: #cbd5e1; margin-bottom: 4px;">
                                ENIGMA Autonomous Property Operations Cloud
                            </div>
                            <div>
                                {footer_content}
                            </div>
                            <div style="margin-top: 12px; font-size: 11px; color: #64748b;">
                                &copy; 2026 ENIGMA Platform. All rights reserved. Encrypted &amp; Audit-Logged.
                            </div>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# =============================================================================
# 8 Specific Email Template Implementations
# =============================================================================

def render_rent_due_email(
    resident_name: str,
    property_name: str,
    unit: str,
    rent_amount: str,
    due_date: str,
    grace_period_end_date: str,
    payment_link: str
) -> Tuple[str, str]:
    """1. Rent Due Reminder (Deep Navy + Blue Palette)."""
    preheader = f"Your rent payment of {rent_amount} for {unit} is due on {due_date}."
    headline = f"Monthly Rent Due: {unit} at {property_name}"
    lead = f"Dear {resident_name}, your regular monthly rent remittance for {unit} at {property_name} is scheduled for {due_date}. You can review your statement and submit payment securely through your resident portal below."
    
    meta = [
        ("Property & Unit", f"{property_name} — {unit}"),
        ("Monthly Rent Due", rent_amount),
        ("Contractual Due Date", due_date),
        ("Grace Period Window", f"Through {grace_period_end_date} (No late fees applied)")
    ]

    html = _wrap_base_html(
        title=f"Rent Due Reminder — {unit}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%)",
        badge_label="Payment Due",
        badge_bg="rgba(56, 189, 248, 0.2)",
        badge_color="#38bdf8",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="Pay Rent Online",
        cta_url=payment_link,
        cta_color="#2563eb"
    )

    plain_text = f"""ENIGMA PROPTECH — RENT DUE REMINDER
Property: {property_name} ({unit})
Tenant: {resident_name}
Amount Due: {rent_amount}
Due Date: {due_date}
Grace Period Ends: {grace_period_end_date}

Please submit your payment online before the grace period ends:
{payment_link}
"""
    return html, plain_text


def render_overdue_3day_email(
    resident_name: str,
    property_name: str,
    unit: str,
    overdue_amount: str,
    original_due_date: str,
    exact_deadline_utc: str,
    payment_link: str,
    manager_contact: str = "leasing@enigma-proptech.internal"
) -> Tuple[str, str]:
    """2. Overdue Rent — 3-Day Payment Deadline (Amber & Crimson Warning Palette)."""
    preheader = f"URGENT: Past-due rent of {overdue_amount} for {unit}. 3 calendar days to remit payment before formal legal review."
    headline = f"Notice of Past-Due Rent: {unit}"
    lead = f"Dear {resident_name}, our accounting records indicate that the rent remittance for {unit} at {property_name} remains unpaid past the contractual due date."

    callout = f"""
    <div style="background-color: #fef2f2; border: 2px solid #ef4444; border-radius: 8px; padding: 18px 20px; color: #991b1b;">
        <div style="display: flex; align-items: center; font-size: 15px; font-weight: 800; margin-bottom: 6px; color: #b91c1c;">
            &#9888; THREE-CALENDAR-DAY PAYMENT DEADLINE
        </div>
        <div style="font-size: 13px; line-height: 1.5; color: #7f1d1d;">
            Under property management policy, you have <strong>three calendar days</strong> from notice delivery to remit the outstanding balance. Failure to remit by the deadline will escalate this account to Property Manager statutory review.
        </div>
        <div style="margin-top: 10px; font-size: 14px; font-weight: 700; color: #991b1b;">
            Exact Settlement Deadline: {exact_deadline_utc}
        </div>
    </div>
    """

    meta = [
        ("Property & Unit", f"{property_name} — {unit}"),
        ("Past-Due Balance", overdue_amount),
        ("Original Due Date", original_due_date),
        ("Mandatory Payment Deadline", exact_deadline_utc),
        ("Manager Office Contact", manager_contact)
    ]

    html = _wrap_base_html(
        title=f"URGENT: Past-Due Balance Notice — {unit}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #1e1b4b 0%, #b91c1c 100%)",
        badge_label="3-Day Deadline Active",
        badge_bg="rgba(239, 68, 68, 0.2)",
        badge_color="#fca5a5",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="Settle Past-Due Rent Now",
        cta_url=payment_link,
        cta_color="#dc2626",
        callout_box_html=callout
    )

    plain_text = f"""ENIGMA PROPTECH — URGENT OVERDUE RENT NOTICE
Property: {property_name} ({unit})
Tenant: {resident_name}
Past-Due Amount: {overdue_amount}
Original Due Date: {original_due_date}
Payment Deadline: {exact_deadline_utc}

THREE-DAY NOTICE:
You have three calendar days to remit the outstanding balance.
Please remit immediately via your resident portal to avoid formal escalation:
{payment_link}

Contact your management office at {manager_contact} if you have already submitted payment.
"""
    return html, plain_text


def render_payment_success_email(
    resident_name: str,
    property_name: str,
    unit: str,
    amount_paid: str,
    receipt_number: str,
    payment_reference: str,
    payment_method: str,
    payment_date: str,
    remaining_balance: str = "$0.00"
) -> Tuple[str, str]:
    """3. Payment Successful Receipt (Emerald Teal & Dark Navy Palette)."""
    preheader = f"Official Receipt: Payment of {amount_paid} confirmed for {unit} (Ref: {payment_reference})."
    headline = f"Payment Confirmed & Official Receipt"
    lead = f"Thank you, {resident_name}. Your payment of {amount_paid} has been confirmed and credited to your tenant ledger. Your account is in good standing."

    callout = f"""
    <div style="background-color: #ecfdf5; border: 1px solid #10b981; border-radius: 8px; padding: 14px 18px; color: #065f46; font-size: 13px;">
        <span style="font-weight: 700; color: #047857;">&#10003; 100% RECONCILED:</span> This payment has been verified across our financial ledger and bank clearing feeds. Any pending overdue reminders have been cancelled.
    </div>
    """

    meta = [
        ("Receipt Number", receipt_number),
        ("Property & Unit", f"{property_name} — {unit}"),
        ("Amount Paid", amount_paid),
        ("Payment Method", payment_method),
        ("Payment Reference", payment_reference),
        ("Settlement Timestamp", payment_date),
        ("Remaining Balance", remaining_balance)
    ]

    html = _wrap_base_html(
        title=f"Payment Receipt: {amount_paid} — {unit}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #0f172a 0%, #065f46 100%)",
        badge_label="Payment Settled",
        badge_bg="rgba(16, 185, 129, 0.2)",
        badge_color="#6ee7b7",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="View Statement in Resident Portal",
        cta_url="http://localhost:5173",
        cta_color="#059669",
        callout_box_html=callout
    )

    plain_text = f"""ENIGMA PROPTECH — OFFICIAL PAYMENT RECEIPT
Receipt Number: {receipt_number}
Property: {property_name} ({unit})
Tenant: {resident_name}
Amount Paid: {amount_paid}
Method: {payment_method}
Reference: {payment_reference}
Timestamp: {payment_date}
Remaining Balance: {remaining_balance}

Thank you for your payment. Your ledger balance is updated and clean.
"""
    return html, plain_text


def render_payment_failed_email(
    resident_name: str,
    property_name: str,
    unit: str,
    amount_usd: str,
    error_reason: str,
    retry_url: str
) -> Tuple[str, str]:
    """4. Payment Failed or Action Required (Rose & Amber Palette)."""
    preheader = f"Payment Unsuccessful: Your payment of {amount_usd} for {unit} could not be completed."
    headline = f"Payment Processing Action Required"
    lead = f"Dear {resident_name}, your recent attempt to remit {amount_usd} for {unit} at {property_name} was declined or could not be completed by your financial institution."

    callout = f"""
    <div style="background-color: #fff7ed; border: 1px solid #f97316; border-radius: 8px; padding: 14px 18px; color: #9a3412; font-size: 13px;">
        <strong>Reason Reported:</strong> {error_reason}.<br/>
        No duplicate charges were posted. You can retry with an alternative payment method without penalty.
    </div>
    """

    meta = [
        ("Unit / Property", f"{property_name} {unit}"),
        ("Attempted Amount", amount_usd),
        ("Transaction Outcome", "Declined / Failed"),
        ("Recommended Action", "Retry via Direct ACH or Alternative Card")
    ]

    html = _wrap_base_html(
        title=f"Payment Failed — Action Required for {unit}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #0f172a 0%, #991b1b 100%)",
        badge_label="Action Required",
        badge_bg="rgba(244, 63, 94, 0.2)",
        badge_color="#fda4af",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="Retry Payment Online",
        cta_url=retry_url,
        cta_color="#e11d48",
        callout_box_html=callout
    )

    plain_text = f"""ENIGMA PROPTECH — PAYMENT FAILED
Unit: {property_name} {unit}
Tenant: {resident_name}
Attempted Amount: {amount_usd}
Reason: {error_reason}

Your payment could not be processed. Please retry with an alternative method:
{retry_url}
"""
    return html, plain_text


def render_payment_processing_email(
    resident_name: str,
    property_name: str,
    unit: str,
    amount_usd: str,
    session_id: str
) -> Tuple[str, str]:
    """5. Payment Processing Update (Sky Blue & Navy Palette)."""
    preheader = f"Payment Processing: Remittance of {amount_usd} for {unit} is being verified."
    headline = f"Payment Processing Initiated"
    lead = f"Dear {resident_name}, your payment of {amount_usd} for {unit} has been received and is currently clearing through the banking network."

    meta = [
        ("Unit", f"{property_name} {unit}"),
        ("Amount Processing", amount_usd),
        ("Gateway Session", session_id),
        ("Estimated Settlement", "1-2 business days (ACH)")
    ]

    html = _wrap_base_html(
        title=f"Payment Processing — {unit}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #0f172a 0%, #0369a1 100%)",
        badge_label="Processing",
        badge_bg="rgba(2, 132, 199, 0.2)",
        badge_color="#38bdf8",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="Check Payment Status",
        cta_url="http://localhost:5173",
        cta_color="#0284c7"
    )

    plain_text = f"""ENIGMA PROPTECH — PAYMENT PROCESSING
Unit: {property_name} {unit}
Tenant: {resident_name}
Amount: {amount_usd}
Session ID: {session_id}

Your payment is currently clearing. You will receive an official receipt once settlement confirms.
"""
    return html, plain_text


def render_legal_notice_review_email(
    manager_name: str,
    lease_id: str,
    tenant_name: str,
    unit: str,
    overdue_amount: str,
    jurisdiction: str,
    statutory_citation: str,
    approval_queue_url: str
) -> Tuple[str, str]:
    """6. Legal-Notice Review & Manager Safeguard (Executive Indigo & Purple Palette)."""
    preheader = f"Manager Approval Required: Overdue balance for {tenant_name} ({unit}) exceeds 3-day deadline. Review statutory notice."
    headline = f"Statutory Notice Approval Gate: {unit}"
    lead = f"Attention {manager_name}, Lease {lease_id} ({tenant_name}, {unit}) remains delinquent past the 3-day grace period with an outstanding balance of {overdue_amount}. A statutory legal notice draft has been generated and awaits your authorized review."

    callout = f"""
    <div style="background-color: #faf5ff; border: 1px solid #9333ea; border-radius: 8px; padding: 14px 18px; color: #581c87; font-size: 13px;">
        <strong>Statutory Compliance Guard:</strong> Jurisdiction: {jurisdiction} ({statutory_citation}). Automated dispatch is strictly blocked until authorized Property Manager review.
    </div>
    """

    meta = [
        ("Lease & Unit", f"{lease_id} — {unit}"),
        ("Tenant Name", tenant_name),
        ("Overdue Amount", overdue_amount),
        ("Statutory Rule", statutory_citation),
        ("Required Sign-Off", "Property Manager or Legal Counsel")
    ]

    html = _wrap_base_html(
        title=f"Legal Notice Review Required: {unit}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #1e1b4b 0%, #4c1d95 100%)",
        badge_label="Manager Gate Active",
        badge_bg="rgba(147, 51, 234, 0.2)",
        badge_color="#c084fc",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="Review & Approve in Compliance Hub",
        cta_url=approval_queue_url,
        cta_color="#7e22ce",
        callout_box_html=callout
    )

    plain_text = f"""ENIGMA PROPTECH — STATUTORY LEGAL NOTICE REVIEW
Manager: {manager_name}
Lease ID: {lease_id} ({unit})
Tenant: {tenant_name}
Overdue: {overdue_amount}
Rule: {statutory_citation}

Action Required:
Review the case in the Compliance Hub before notice dispatch:
{approval_queue_url}
"""
    return html, plain_text


def render_pm_collection_alert_email(
    manager_name: str,
    org_name: str,
    billing_period: str,
    collection_rate_pct: str,
    total_overdue: str,
    overdue_units_count: int,
    dashboard_url: str
) -> Tuple[str, str]:
    """7. Property Manager Daily Collection Briefing (Navy & Slate Palette)."""
    preheader = f"Daily Rent Collection HUD for {org_name} ({billing_period}): {collection_rate_pct}% settled."
    headline = f"Portfolio Rent Collection Briefing: {billing_period}"
    lead = f"Good morning {manager_name}, here is the verified collection summary for {org_name} for the {billing_period} billing cycle."

    meta = [
        ("Organization", org_name),
        ("Billing Month", billing_period),
        ("Collection Rate", f"{collection_rate_pct}%"),
        ("Overdue Units", f"{overdue_units_count} Units"),
        ("Total Delinquency", total_overdue)
    ]

    html = _wrap_base_html(
        title=f"Rent Collection Briefing: {billing_period}",
        preheader=preheader,
        header_gradient="linear-gradient(135deg, #0f172a 0%, #334155 100%)",
        badge_label="Portfolio HUD",
        badge_bg="rgba(148, 163, 184, 0.2)",
        badge_color="#cbd5e1",
        headline=headline,
        lead_paragraph=lead,
        meta_table_rows=meta,
        cta_text="Open Property Manager HUD",
        cta_url=dashboard_url,
        cta_color="#0f172a"
    )

    plain_text = f"""ENIGMA PROPTECH — COLLECTION BRIEFING
Organization: {org_name}
Cycle: {billing_period}
Settled: {collection_rate_pct}%
Overdue Units: {overdue_units_count} ({total_overdue})

View live HUD:
{dashboard_url}
"""
    return html, plain_text


def render_system_notification_email(
    title: str,
    message: str,
    action_label: Optional[str] = None,
    action_url: Optional[str] = None
) -> Tuple[str, str]:
    """8. General ENIGMA System Notification (Clean Slate / Teal Palette)."""
    meta = [
        ("System Component", "ENIGMA Autonomous Orchestrator"),
        ("Status", "Operational")
    ]

    html = _wrap_base_html(
        title=title,
        preheader=title,
        header_gradient="linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
        badge_label="System Alert",
        badge_bg="rgba(56, 189, 248, 0.2)",
        badge_color="#38bdf8",
        headline=title,
        lead_paragraph=message,
        meta_table_rows=meta,
        cta_text=action_label,
        cta_url=action_url,
        cta_color="#2563eb"
    )

    plain_text = f"""ENIGMA PROPTECH NOTIFICATION
{title}

{message}
"""
    return html, plain_text
