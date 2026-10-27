"""Payment Gateway Provider Abstraction and Sandbox Engine for ENIGMA.

Provides:
- Pluggable payment provider abstraction.
- Built-in high-integrity Sandbox Gateway supporting realistic checkout initiation, signed HMAC webhooks, and idempotent processing.
- Zero raw card credential storage (only tokenized references).
- Authoritative event-driven reconciliation with replay protection.
"""

import hmac
import hashlib
import time
import json
import uuid
import os
import logging
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

from .database import db
from .audit import log_audit_event
from .config import settings

logger = logging.getLogger(__name__)


def get_webhook_secret() -> str:
    """Retrieve webhook signing secret from configuration or environment.

    In production mode, raises ValueError if no secure secret is configured.
    In development/test mode, provides an explicitly scoped fallback secret.
    """
    secret = (
        getattr(settings, "stripe_webhook_secret", "")
        or getattr(settings, "sandbox_webhook_secret", "")
        or os.getenv("STRIPE_WEBHOOK_SECRET", "")
        or os.getenv("SANDBOX_WEBHOOK_SECRET", "")
    )
    if secret:
        return secret
    env = getattr(settings, "environment", "development").lower()
    if env == "production":
        raise ValueError(
            "Production security failure: A valid STRIPE_WEBHOOK_SECRET or SANDBOX_WEBHOOK_SECRET "
            "must be configured via environment variable in production mode."
        )
    return "whsec_test_mode_ephemeral_sandbox_secret"


WEBHOOK_SECRET = get_webhook_secret()


class PaymentProvider:
    """Abstract interface for payment gateway providers (Stripe, Plaid, Sandbox)."""

    def create_checkout_session(
        self,
        lease_id: str,
        billing_record_id: str,
        amount_usd: float,
        org_id: str,
        customer_email: str,
        idempotency_key: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def verify_webhook_signature(
        self,
        payload_bytes: bytes,
        signature_header: str,
        secret: Optional[str] = None
    ) -> bool:
        raise NotImplementedError

    def handle_webhook_event(
        self,
        event_data: Dict[str, Any],
        signature_valid: bool
    ) -> Dict[str, Any]:
        raise NotImplementedError


class SandboxPaymentProvider(PaymentProvider):
    """Production-grade Sandbox Gateway with HMAC-SHA256 signed webhooks and idempotency."""

    def __init__(self, secret: Optional[str] = None):
        self._secret = secret

    @property
    def secret(self) -> str:
        return self._secret or get_webhook_secret()

    def create_checkout_session(
        self,
        lease_id: str,
        billing_record_id: str,
        amount_usd: float,
        org_id: str,
        customer_email: str,
        idempotency_key: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None
    ) -> Dict[str, Any]:
        if amount_usd <= 0:
            raise ValueError("Payment amount must be greater than $0.00")

        # Check existing transaction for this idempotency key
        if idempotency_key:
            with db() as conn:
                existing = conn.execute(
                    """SELECT id, status, client_secret, amount_usd 
                       FROM payment_gateway_transactions 
                       WHERE idempotency_key = %s""",
                    (idempotency_key,)
                ).fetchone()
                if existing:
                    return {
                        "session_id": existing[0],
                        "status": existing[1],
                        "client_secret": existing[2],
                        "amount_usd": float(existing[3]),
                        "idempotency_key": idempotency_key,
                        "checkout_url": f"/checkout/sandbox?session_id={existing[0]}",
                        "message": "Existing checkout session retrieved (idempotent)."
                    }

        session_id = f"cs_test_{uuid.uuid4().hex[:16]}"
        client_secret = f"seti_secret_{uuid.uuid4().hex[:24]}"
        checkout_url = f"/checkout/sandbox?session_id={session_id}"

        with db() as conn:
            conn.execute(
                """INSERT INTO payment_gateway_transactions (
                    id, lease_id, billing_record_id, org_id, amount_usd,
                    currency, provider, status, client_secret, idempotency_key,
                    receipt_url
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    session_id,
                    lease_id,
                    billing_record_id,
                    org_id,
                    amount_usd,
                    "USD",
                    "sandbox",
                    "pending",
                    client_secret,
                    idempotency_key or str(uuid.uuid4()),
                    f"/api/payments/receipts/{session_id}"
                )
            )

        log_audit_event(
            org_id=org_id,
            action="checkout_session_created",
            resource_type="payment_session",
            resource_id=session_id,
            actor_type="tenant",
            actor_id=customer_email,
            outcome="success",
            details={
                "billing_record_id": billing_record_id,
                "lease_id": lease_id,
                "amount_usd": amount_usd,
                "provider": "sandbox"
            },
            source_component="payment_gateway"
        )

        return {
            "session_id": session_id,
            "status": "pending",
            "client_secret": client_secret,
            "amount_usd": amount_usd,
            "currency": "USD",
            "idempotency_key": idempotency_key,
            "checkout_url": checkout_url,
            "customer_email": customer_email
        }

    def generate_webhook_signature(self, payload: str, timestamp: Optional[int] = None) -> str:
        """Create signature header for test or simulation dispatch: t=timestamp,v1=signature."""
        ts = timestamp if timestamp is not None else int(time.time())
        signed_payload = f"{ts}.{payload}".encode("utf-8")
        computed = hmac.new(self.secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return f"t={ts},v1={computed}"

    def verify_webhook_signature(
        self,
        payload_bytes: bytes,
        signature_header: str,
        secret: Optional[str] = None
    ) -> bool:
        """Verify HMAC-SHA256 signature in t=...,v1=... format with 300s replay window."""
        sec = secret or self.secret
        if not signature_header:
            return False

        parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
        timestamp_str = parts.get("t")
        sig = parts.get("v1")

        if not timestamp_str or not sig:
            return False

        try:
            timestamp = int(timestamp_str)
            # 5 minute tolerance
            if abs(int(time.time()) - timestamp) > 300:
                logger.warning("Webhook rejected: signature timestamp expired.")
                return False

            signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
            expected_sig = hmac.new(sec.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(sig, expected_sig)
        except Exception:
            return False

    def handle_webhook_event(
        self,
        event_data: Dict[str, Any],
        signature_valid: bool
    ) -> Dict[str, Any]:
        """Process verified provider webhook event with idempotency and state transitions."""
        if not signature_valid:
            log_audit_event(
                org_id="system",
                action="webhook_verification_failed",
                resource_type="webhook",
                resource_id=event_data.get("id"),
                outcome="blocked",
                details={"event_type": event_data.get("type")},
                source_component="payment_gateway"
            )
            raise ValueError("Invalid webhook signature")

        event_id = event_data.get("id", f"evt_{uuid.uuid4().hex[:12]}")
        event_type = event_data.get("type")
        data_obj = event_data.get("data", {}).get("object", {})
        session_id = data_obj.get("id") or data_obj.get("session_id")

        if not session_id:
            raise ValueError("Webhook missing session identifier")

        with db() as conn:
            tx = conn.execute(
                """SELECT id, lease_id, billing_record_id, org_id, amount_usd, status, webhook_events 
                   FROM payment_gateway_transactions WHERE id = %s""",
                (session_id,)
            ).fetchone()

        if not tx:
            raise ValueError(f"Gateway transaction '{session_id}' not found")

        tx_id, lease_id, billing_id, org_id, amount_usd, current_status, webhook_events = tx
        events_list = webhook_events if isinstance(webhook_events, list) else []

        # Duplicate webhook check
        if any(e.get("event_id") == event_id for e in events_list):
            return {
                "status": "duplicate_event_ignored",
                "session_id": session_id,
                "event_id": event_id,
                "current_status": current_status
            }

        new_status = current_status
        if event_type == "payment_intent.succeeded":
            new_status = "succeeded"
        elif event_type == "payment_intent.payment_failed":
            new_status = "failed"
        elif event_type == "charge.refunded":
            new_status = "refunded"

        events_list.append({
            "event_id": event_id,
            "type": event_type,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "new_status": new_status
        })

        with db() as conn:
            conn.execute(
                """UPDATE payment_gateway_transactions 
                   SET status = %s, webhook_events = %s, updated_at = now() 
                   WHERE id = %s""",
                (new_status, json.dumps(events_list), session_id)
            )

        log_audit_event(
            org_id=org_id,
            action=f"webhook_{event_type.replace('.', '_')}",
            resource_type="payment_session",
            resource_id=session_id,
            actor_type="webhook",
            actor_id="sandbox_gateway",
            outcome="success",
            before_state={"status": current_status},
            after_state={"status": new_status},
            details={"event_id": event_id, "amount_usd": float(amount_usd)},
            source_component="payment_gateway"
        )

        return {
            "status": "processed",
            "session_id": session_id,
            "previous_status": current_status,
            "new_status": new_status,
            "event_type": event_type,
            "lease_id": lease_id,
            "billing_record_id": billing_id,
            "amount_usd": float(amount_usd),
            "org_id": org_id
        }

    def simulate_checkout_completion(
        self,
        session_id: str,
        should_succeed: bool = True,
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Simulate customer completing checkout on hosted page, firing webhook."""
        with db() as conn:
            tx = conn.execute(
                "SELECT id, amount_usd, lease_id, billing_record_id, org_id FROM payment_gateway_transactions WHERE id = %s",
                (session_id,)
            ).fetchone()

        if not tx:
            raise ValueError(f"Session {session_id} not found")

        tx_id, amount_usd, lease_id, billing_id, org_id = tx
        event_type = "payment_intent.succeeded" if should_succeed else "payment_intent.payment_failed"
        event_payload = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type,
            "data": {
                "object": {
                    "id": session_id,
                    "amount": int(round(float(amount_usd) * 100)),
                    "currency": "usd",
                    "status": "succeeded" if should_succeed else "failed",
                    "error": error_message if not should_succeed else None
                }
            }
        }

        now_ts = int(time.time())
        raw_json = json.dumps(event_payload)
        sig = self.generate_webhook_signature(raw_json, now_ts)
        is_valid = self.verify_webhook_signature(raw_json.encode("utf-8"), sig)

        webhook_result = self.handle_webhook_event(event_payload, signature_valid=is_valid)
        return {
            "simulation_success": True,
            "session_id": session_id,
            "webhook_result": webhook_result,
            "simulated_outcome": "succeeded" if should_succeed else "failed"
        }


# Singleton instance
default_gateway = SandboxPaymentProvider()


def get_payment_provider() -> SandboxPaymentProvider:
    return default_gateway
