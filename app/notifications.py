"""Durable Notification Infrastructure for EQUILIBRA.

Tracks:
- Inbound and outbound notifications for Residents, Property Managers, and Trades Vendors
- Delivery lifecycle states: queued, sent, simulated, failed
- Deduplication via stable event_keys to prevent spam on repeated scheduler runs
"""

import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .database import db
from .config import settings
from .world_model import record_event, canonical_id

def send_smtp_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email using configured SMTP credentials."""
    if not settings.smtp_host or not settings.smtp_user:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.request_timeout_seconds)
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception:
        return False

def init_notifications_table():
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            recipient_email TEXT NOT NULL,
            recipient_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            event_key TEXT UNIQUE,
            created_at TIMESTAMPTZ DEFAULT now(),
            delivered_at TIMESTAMPTZ
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS notif_recipient ON notifications(recipient_email)')
        conn.execute('CREATE INDEX IF NOT EXISTS notif_key ON notifications(event_key)')

def queue_notification(
    recipient_email: str,
    recipient_type: str,
    title: str,
    message: str,
    category: str,
    event_key: Optional[str] = None,
    simulate_delivery: bool = True
) -> Dict[str, Any]:
    """Queue a notification with deduplication. Dispatches via live SMTP if configured, else marks simulated."""
    init_notifications_table()

    # Check if notification with this event_key already exists
    if event_key:
        with db() as conn:
            existing = conn.execute(
                "SELECT id, status, created_at FROM notifications WHERE event_key = %s",
                (event_key,)
            ).fetchone()
            if existing:
                return {
                    "id": existing[0],
                    "status": existing[1],
                    "duplicate": True,
                    "message": "Notification already queued/sent previously"
                }

    notif_id = f"NOTIF-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(timezone.utc)
    delivered_at = None

    if getattr(settings, 'smtp_enabled', False) and settings.smtp_host and settings.smtp_user:
        sent_ok = send_smtp_email(recipient_email, title, message)
        if sent_ok:
            status = "sent"
            delivered_at = now
        else:
            status = "failed"
    else:
        status = "simulated" if simulate_delivery else "queued"
        if status == "simulated":
            delivered_at = now

    with db() as conn:
        conn.execute(
            """INSERT INTO notifications (
                id, recipient_email, recipient_type, title, message, category, status, event_key, delivered_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_key) DO NOTHING""",
            (
                notif_id, recipient_email, recipient_type, title, message,
                category, status, event_key or notif_id, delivered_at
            )
        )

    return {
        "id": notif_id,
        "canonical_id": canonical_id("notification", notif_id),
        "recipient_email": recipient_email,
        "recipient_type": recipient_type,
        "title": title,
        "status": status,
        "event_key": event_key or notif_id,
        "duplicate": False
    }

def list_notifications(
    recipient_email: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieve recent notifications."""
    init_notifications_table()
    sql = """SELECT id, recipient_email, recipient_type, title, message, category, status, event_key, created_at, delivered_at
             FROM notifications"""
    conditions = []
    params = []
    if recipient_email:
        conditions.append("recipient_email = %s")
        params.append(recipient_email)
    if category:
        conditions.append("category = %s")
        params.append(category)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    with db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": r[0],
            "canonical_id": canonical_id("notification", r[0]),
            "recipient_email": r[1],
            "recipient_type": r[2],
            "title": r[3],
            "message": r[4],
            "category": r[5],
            "status": r[6],
            "event_key": r[7],
            "created_at": r[8].isoformat() if hasattr(r[8], "isoformat") else str(r[8]),
            "delivered_at": r[9].isoformat() if r[9] and hasattr(r[9], "isoformat") else (str(r[9]) if r[9] else None)
        }
        for r in rows
    ]
