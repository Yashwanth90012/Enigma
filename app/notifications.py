"""Durable Notification Infrastructure for EQUILIBRA.

Tracks:
- Inbound and outbound notifications for Residents, Property Managers, and Trades Vendors
- Delivery lifecycle states: queued, sent, simulated, failed
- Deduplication via stable event_keys to prevent spam on repeated scheduler runs
"""

import uuid
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .database import db
from .config import settings
from .world_model import record_event, canonical_id

import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

DEMO_TARGET_EMAIL = "puligillayashwanth776@gmail.com"

def get_smtp_config() -> Dict[str, Any]:
    """Retrieve SMTP configuration with fallback to environment variables and .env file."""
    host = settings.smtp_host or os.getenv("SMTP_HOST") or "smtp.gmail.com"
    port = int(settings.smtp_port or os.getenv("SMTP_PORT") or 587)
    user = settings.smtp_user or os.getenv("SMTP_USER") or ""
    pwd = settings.smtp_password or os.getenv("SMTP_PASSWORD") or os.getenv("SMTP_PASS") or ""
    enabled = getattr(settings, 'smtp_enabled', False) or (os.getenv("SMTP_ENABLED", "").lower() == "true")
    from_email = settings.smtp_from_email or os.getenv("SMTP_FROM_EMAIL") or user or "notifications@equilibra.ai"
    from_name = settings.smtp_from_name or os.getenv("SMTP_FROM_NAME") or "EQUILIBRA Property Operations"
    use_tls = settings.smtp_use_tls if hasattr(settings, 'smtp_use_tls') else (os.getenv("SMTP_USE_TLS", "true").lower() == "true")

    # If user or password is missing in environment, inspect .env file directly
    if (not user or not pwd) and os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SMTP_USER="):
                        user = user or line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("SMTP_PASS=") or line.startswith("SMTP_PASSWORD="):
                        pwd = pwd or line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("SMTP_ENABLED="):
                        enabled = line.split("=", 1)[1].strip().lower() == "true"
                    elif line.startswith("SMTP_HOST="):
                        host = host or line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("SMTP_FROM_EMAIL="):
                        from_email = from_email or line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": pwd,
        "enabled": enabled,
        "from_email": from_email,
        "from_name": from_name,
        "use_tls": use_tls
    }

def send_smtp_email(to_email: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
    """Send an email using configured SMTP credentials, redirecting to demo recipient with full HTML rendering."""
    cfg = get_smtp_config()
    if not cfg["host"] or not cfg["user"] or not cfg["password"]:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg['From'] = f"{cfg['from_name']} <{cfg['from_email']}>"
        target = DEMO_TARGET_EMAIL or to_email
        msg['To'] = target

        # If original intended recipient is different, include banner note
        if to_email and to_email.lower() != target.lower():
            msg['Subject'] = f"{subject} [Intended: {to_email}]"
            full_plain = (
                f"====================================================\n"
                f"EQUILIBRA DEMO NOTIFICATION ROUTING\n"
                f"Intended Recipient: {to_email}\n"
                f"Delivered To: {target}\n"
                f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"====================================================\n\n"
                f"{body}"
            )
        else:
            msg['Subject'] = subject
            full_plain = body

        msg.attach(MIMEText(full_plain, 'plain'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=settings.request_timeout_seconds)
        if cfg["use_tls"]:
            server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)
        server.quit()
        print(f"[SMTP SUCCESS] Dispatched email to {target} (intended: {to_email})")
        return True
    except Exception as e:
        print(f"[SMTP ERROR] Failed to send email to {target}: {e}")
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
            delivered_at TIMESTAMPTZ,
            template_key TEXT,
            context_data JSONB DEFAULT '{}'::jsonb
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS notif_recipient ON notifications(recipient_email)')
        conn.execute('CREATE INDEX IF NOT EXISTS notif_key ON notifications(event_key)')
        conn.execute('ALTER TABLE notifications ADD COLUMN IF NOT EXISTS template_key TEXT')
        conn.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS context_data JSONB DEFAULT '{}'::jsonb")

def queue_notification(
    recipient_email: str,
    recipient_type: str,
    title: str,
    message: str,
    category: str,
    event_key: Optional[str] = None,
    simulate_delivery: bool = True,
    template_key: Optional[str] = None,
    context_data: Optional[Dict[str, Any]] = None,
    is_test_send: bool = False
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

    cfg = get_smtp_config()
    html_body = context_data.get("html_body") if isinstance(context_data, dict) else None
    is_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))

    if not is_pytest and cfg["enabled"] and cfg["user"] and cfg["password"]:
        sent_ok = send_smtp_email(recipient_email, title, message, html_body=html_body)
        if sent_ok:
            status = "sent"
            delivered_at = now
        else:
            status = "simulated" if simulate_delivery else "failed"
            if status == "simulated":
                delivered_at = now
    else:
        status = "simulated" if simulate_delivery else "queued"
        if status == "simulated":
            delivered_at = now

    with db() as conn:
        conn.execute(
            """INSERT INTO notifications (
                id, recipient_email, recipient_type, title, message, category, status, event_key, delivered_at, template_key, context_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_key) DO NOTHING""",
            (
                notif_id, recipient_email, recipient_type, title, message,
                category, status, event_key or notif_id, delivered_at,
                template_key, json.dumps(context_data or {})
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
        "duplicate": False,
        "template_key": template_key
    }

def list_notifications(
    recipient_email: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Retrieve recent notifications."""
    init_notifications_table()
    sql = """SELECT id, recipient_email, recipient_type, title, message, category, status, event_key, created_at, delivered_at, template_key, context_data
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
            "delivered_at": r[9].isoformat() if r[9] and hasattr(r[9], "isoformat") else (str(r[9]) if r[9] else None),
            "template_key": r[10] if len(r) > 10 else None,
            "context_data": r[11] if len(r) > 11 else {}
        }
        for r in rows
    ]
