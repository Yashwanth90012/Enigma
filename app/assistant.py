"""EQUILIBRA Autonomous Property Management AI Assistant.

Provides:
- Natural-language reasoning over authoritative properties, leases, work orders, vendor bills, and financial ledger data
- Tool calling against backend functions:
    - query_lease(lease_id)
    - query_reconciliation(lease_id)
    - query_work_orders(lease_id or property_id)
    - query_properties(published_only)
    - query_vendor_bills(invoice_id or status)
    - explain_variance(lease_id)
- Respects security & audit boundaries: zero arbitrary SQL execution, zero unverified bank balance alterations
- Uses MeterlessProvider when configured or high-grade deterministic synthesis when offline
"""

import json
from typing import Any, Dict, List, Optional

from .database import db
from .config import settings
from .engine import fixture_rows, calculate
from .providers import MeterlessProvider, UnifiedAIProvider
from .world_model import get_latest_state, canonical_id


def answer_assistant_query(query: str, session_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Process user prompt, consult authoritative backend records via tools, and synthesize response."""
    q_lower = query.lower()
    tool_calls = []
    retrieved_data = {}
    
    # 1. Intent routing & tool dispatch
    if "lease" in q_lower or "rent" in q_lower or "tenant" in q_lower:
        # Check if a specific lease ID is mentioned
        import re
        lease_match = re.search(r'\bLEASE-\d{4}\b', query.upper())
        target_lease = lease_match.group(0) if lease_match else "LEASE-0001"
        
        tool_calls.append({"tool": "query_lease_details", "param": target_lease})
        with db() as conn:
            lease_row = conn.execute(
                "SELECT lease_id, property_id, unit, address, tenant1, monthly_rent_usd FROM lease_records WHERE lease_id = %s",
                (target_lease,)
            ).fetchone()
            
        if lease_row:
            fin = fixture_rows(target_lease)
            calc = calculate(fin)
            retrieved_data["lease"] = {
                "lease_id": lease_row[0],
                "property_id": lease_row[1],
                "unit": lease_row[2],
                "address": lease_row[3],
                "tenant1": lease_row[4],
                "rent_usd": float(lease_row[5]),
                "reconciliation_status": calc["status"],
                "variance_cents": calc["difference_cents"],
                "reason": calc["reason"]
            }
            
    if "maintenance" in q_lower or "work order" in q_lower or "repair" in q_lower:
        tool_calls.append({"tool": "query_active_work_orders"})
        with db() as conn:
            orders = conn.execute(
                """SELECT work_order_id, lease_id, category, description, priority, status, technician, estimated_cost_usd
                   FROM work_order_records ORDER BY reported_date DESC LIMIT 5"""
            ).fetchall()
        retrieved_data["recent_work_orders"] = [
            {
                "id": o[0], "lease_id": o[1], "category": o[2],
                "description": o[3], "priority": o[4], "status": o[5],
                "technician": o[6], "cost_usd": float(o[7])
            }
            for o in orders
        ]
        
    if "property" in q_lower or "listing" in q_lower or "tour" in q_lower:
        tool_calls.append({"tool": "query_verified_properties"})
        with db() as conn:
            props = conn.execute(
                """SELECT property_id, name, address, city, monthly_rent_usd, verification_status, is_published
                   FROM properties ORDER BY property_id ASC LIMIT 4"""
            ).fetchall()
        retrieved_data["properties"] = [
            {
                "id": p[0], "name": p[1], "address": p[2],
                "city": p[3], "rent_usd": float(p[4]),
                "status": p[5], "published": bool(p[6])
            }
            for p in props
        ]
        
    if "vendor" in q_lower or "invoice" in q_lower or "bill" in q_lower:
        tool_calls.append({"tool": "query_vendor_invoices"})
        with db() as conn:
            bills = conn.execute(
                """SELECT id, vendor_id, invoice_number, total_usd, status
                   FROM vendor_invoices ORDER BY issue_date DESC LIMIT 4"""
            ).fetchall()
        retrieved_data["vendor_bills"] = [
            {"id": b[0], "vendor_id": b[1], "number": b[2], "total_usd": float(b[3]), "status": b[4]}
            for b in bills
        ]

    if any(k in q_lower for k in ("risk", "compliance", "finding", "statutory", "violation", "audit", "approval")):
        tool_calls.append({"tool": "query_compliance_risk_register"})
        import re
        finding_match = re.search(r'\bRISK-[0-9A-F]{8}\b', query.upper())
        with db() as conn:
            if finding_match:
                f_id = finding_match.group(0)
                f_rows = conn.execute(
                    """SELECT id, title, description, category, finding_type, severity,
                              source_record_type, source_record_id, detection_rule,
                              jurisdiction, statutory_source, compliance_status, status, evidence
                       FROM risk_findings WHERE id = %s""",
                    (f_id,)
                ).fetchall()
            else:
                f_rows = conn.execute(
                    """SELECT id, title, description, category, finding_type, severity,
                              source_record_type, source_record_id, detection_rule,
                              jurisdiction, statutory_source, compliance_status, status, evidence
                       FROM risk_findings
                       WHERE status NOT IN ('resolved', 'dismissed')
                       ORDER BY
                           CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END ASC,
                           created_at DESC
                       LIMIT 5"""
                ).fetchall()

        retrieved_data["risk_findings"] = [
            {
                "id": r[0],
                "title": r[1],
                "description": r[2],
                "category": r[3],
                "finding_type": r[4],
                "severity": r[5],
                "source_record": f"{r[6]}:{r[7]}",
                "rule": r[8],
                "jurisdiction": r[9],
                "statutory_source": r[10],
                "compliance_status": r[11],
                "status": r[12],
                "evidence": r[13] if isinstance(r[13], dict) else json.loads(r[13] or "{}")
            }
            for r in f_rows
        ]

    # 2. Synthesize response narrative using unified failover (Meterless -> NIM -> Offline)
    system = (
        "You are EQUILIBRA AI Assistant, an autonomous property management intelligence companion. "
        "Base answers only on the verified backend facts retrieved. Clearly distinguish recorded facts, "
        "configured business rules, and AI recommendations. Do not bypass manager approval gates."
    )
    prompt = f"User asked: '{query}'. Authoritative backend context: {json.dumps(retrieved_data, default=str)}. Formulate a helpful property management response (<150 words)."

    unified_ai = UnifiedAIProvider()
    ai_result = unified_ai.generate(system, prompt, side_effects_executed=False)

    if ai_result['provider_used'] == 'offline':
        narrative = _synthesize_offline_response(query, retrieved_data)
    else:
        narrative = ai_result['content']

    return {
        "query": query,
        "tool_calls": tool_calls,
        "retrieved_context": retrieved_data,
        "response": narrative,
        "ai_engine": settings.ai_provider,
        "provider_used": ai_result['provider_used'],
        "fallback_occurred": ai_result['fallback_occurred'],
        "fallback_reason": ai_result['fallback_reason'],
        "latency_ms": ai_result['total_latency_ms']
    }


def _synthesize_offline_response(query: str, data: Dict[str, Any]) -> str:
    """Deterministic, factual response generator based on authoritative retrieved data."""
    parts = []
    
    if "risk_findings" in data:
        findings = data["risk_findings"]
        if not findings:
            parts.append("Compliance Register reports zero active high-severity risk findings.")
        else:
            parts.append(f"Compliance Register identified {len(findings)} active finding(s):")
            for f in findings:
                stat_info = f" [Statutory Rule: {f['statutory_source']}]" if f.get('statutory_source') else ""
                parts.append(
                    f"• [{f['severity'].upper()} - {f['finding_type'].replace('_', ' ').title()}] {f['id']}: {f['title']}{stat_info}. "
                    f"Source: {f['source_record']}. Detected Issue: {f['description']} "
                    f"Recommended Action: Review underlying record and execute authorized manager sign-off."
                )

    if "lease" in data:
        l = data["lease"]
        parts.append(
            f"Regarding {l['lease_id']} ({l['address']}, {l['unit']}) for {l['tenant1']}: "
            f"Monthly rent is ${l['rent_usd']:.2f}. Reconciliation status is [{l['reconciliation_status'].upper()}]. "
            f"{l['reason']}."
        )
        
    if "recent_work_orders" in data:
        wo_count = len(data["recent_work_orders"])
        sample = data["recent_work_orders"][0] if wo_count > 0 else None
        if sample:
            parts.append(
                f"There are {wo_count} active maintenance work orders. Most recent is {sample['id']} "
                f"({sample['category']}, {sample['priority']} priority: '{sample['description']}'), assigned to {sample['technician']}."
            )
            
    if "properties" in data:
        p_count = len(data["properties"])
        parts.append(f"Portfolio currently features {p_count} properties. Publicly published and verified units are actively taking tour bookings.")
        
    if "vendor_bills" in data:
        v_count = len(data["vendor_bills"])
        parts.append(f"Found {v_count} vendor invoices undergoing 4-way matching across trades vendors.")
        
    if not parts:
        parts.append(
            f"EQUILIBRA AI Assistant is active. You can ask about lease reconciliations (e.g. 'Status of LEASE-0001'), "
            "compliance risk findings, open maintenance work orders, public property listings, or vendor AP bills."
        )
        
    return " ".join(parts)
