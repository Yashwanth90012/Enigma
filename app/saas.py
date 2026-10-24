"""SaaS Multi-Tenant Management & Customer Requirements Portal.

Provides:
- Pre-configured SaaS customer organizations (Apex, Beacon, Verdant, Skyline)
- Onboarding API for new customer property management firms
- Customer Requirements & Feature Requests submission, triaging, and roadmap voting
- Organization-scoped tenant configuration & templates
"""

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# Pre-populated enterprise customer organizations
DEFAULT_ORGANIZATIONS: List[Dict[str, Any]] = [
    {
        "id": "ORG-APEX",
        "name": "Apex Horizon Living",
        "portfolio_type": "Residential Multifamily",
        "tier": "Enterprise Cloud",
        "aws_region": "us-east-1",
        "active_units": 100,
        "contact_email": "operations@apexhorizon.com",
        "primary_ledger": "Zetaris SQL REST Federation",
        "ai_engine": "NVIDIA Nemotron-4-340B (Meterless Nightshift)",
        "created_at": "2026-01-15T08:00:00Z",
        "description": "Urban multifamily portfolio across Berkeley, Oakland, and San Francisco."
    },
    {
        "id": "ORG-BEACON",
        "name": "Beacon Bay Commercial REIT",
        "portfolio_type": "Mixed-Use Commercial",
        "tier": "Institutional Tier",
        "aws_region": "us-west-2",
        "active_units": 240,
        "contact_email": "ap-controller@beaconreit.com",
        "primary_ledger": "PostgreSQL Fixture / Yardi Voyager",
        "ai_engine": "Deterministic Audit Reasoner",
        "created_at": "2026-02-01T10:30:00Z",
        "description": "High-volume retail and commercial office suites in Downtown SF Financial District."
    },
    {
        "id": "ORG-VERDANT",
        "name": "Verdant Valley Estates",
        "portfolio_type": "Luxury Single-Family Portfolios",
        "tier": "Growth SaaS",
        "aws_region": "us-west-1",
        "active_units": 65,
        "contact_email": "pm@verdantestates.com",
        "primary_ledger": "Zetaris SQL REST Federation",
        "ai_engine": "NVIDIA Nemotron-4-340B (Meterless Nightshift)",
        "created_at": "2026-02-20T14:15:00Z",
        "description": "Premium luxury residential homes and townhomes in Silicon Valley."
    },
    {
        "id": "ORG-SKYLINE",
        "name": "Skyline Urban Holdings",
        "portfolio_type": "Metro High-Rise Communities",
        "tier": "Enterprise Cloud",
        "aws_region": "us-east-2",
        "active_units": 320,
        "contact_email": "tech@skylineurban.com",
        "primary_ledger": "RealPage Cloud API Adapter",
        "ai_engine": "NVIDIA Nemotron-4-340B (Meterless Nightshift)",
        "created_at": "2026-03-05T09:00:00Z",
        "description": "Midwest high-density residential towers with on-site commercial vendor amenities."
    }
]

# Pre-populated customer-submitted feature requirements & co-innovation roadmap
DEFAULT_FEATURE_REQUESTS: List[Dict[str, Any]] = [
    {
        "id": "REQ-1001",
        "org_id": "ORG-APEX",
        "org_name": "Apex Horizon Living",
        "title": "Automated CAM (Common Area Maintenance) Utility Reconciliation",
        "category": "tenant_ar",
        "priority": "high",
        "specification": "Support multi-submeter water and electric bills split automatically across fractional tenants per lease Section 8 utility addendum.",
        "status": "IN_ROADMAP",
        "target_release": "v2.2-Cloud",
        "votes": 14,
        "submitted_by": "Marcus Vance (Senior Asset Manager)",
        "submitted_at": "2026-10-18T11:20:00Z"
    },
    {
        "id": "REQ-1002",
        "org_id": "ORG-BEACON",
        "org_name": "Beacon Bay Commercial REIT",
        "title": "OCR Hand-Signed Lien Waiver Extraction from Vendor PDFs",
        "category": "vendor_ap",
        "priority": "critical_blocker",
        "specification": "When a plumbing contractor invoices over $500, require pgvector RAG extraction of the unconditional final lien waiver signature block before payment voucher issuance.",
        "status": "IN_STAGING",
        "target_release": "v2.1-Cloud",
        "votes": 28,
        "submitted_by": "Elena Rostova (VP of Accounts Payable)",
        "submitted_at": "2026-10-19T14:45:00Z"
    },
    {
        "id": "REQ-1003",
        "org_id": "ORG-VERDANT",
        "org_name": "Verdant Valley Estates",
        "title": "Direct Plaid / Yodlee Live Bank Feed Webhook Ingestion",
        "category": "aws_infra",
        "priority": "standard",
        "specification": "Replace CSV bank imports with instantaneous AWS SNS/SQS event triggers for cleared bank presentation check debits.",
        "status": "DEPLOYED_TO_CLOUD",
        "target_release": "v2.0-Production",
        "votes": 19,
        "submitted_by": "Priya Sharma (Portfolio Controller)",
        "submitted_at": "2026-10-20T09:10:00Z"
    },
    {
        "id": "REQ-1004",
        "org_id": "ORG-SKYLINE",
        "org_name": "Skyline Urban Holdings",
        "title": "Automated Stale Check Re-issuance & Escheatment Warning Timer",
        "category": "vendor_ap",
        "priority": "high",
        "specification": "If a corporate vendor check remains uncashed float beyond 90 days, auto-generate a California 180-day escheatment notice draft in World Model.",
        "status": "UNDER_REVIEW",
        "target_release": "v2.3-Cloud",
        "votes": 9,
        "submitted_by": "David Kim (Operations Director)",
        "submitted_at": "2026-10-22T16:30:00Z"
    }
]

from .database import db

class OnboardCustomerRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    portfolio_type: str = Field(default="Residential Multifamily")
    tier: str = Field(default="Enterprise Cloud")
    aws_region: str = Field(default="us-east-1")
    active_units: int = Field(default=100, ge=1)
    contact_email: str = Field(..., min_length=5)
    primary_ledger: str = Field(default="Zetaris SQL REST Federation")
    ai_engine: str = Field(default="NVIDIA Nemotron-4-340B (Meterless Nightshift)")
    description: Optional[str] = "Multi-property real estate portfolio onboarded to SaaS Cloud template."


class SubmitFeatureRequest(BaseModel):
    org_id: str = Field(..., min_length=2)
    title: str = Field(..., min_length=5, max_length=150)
    category: str = Field(default="tenant_ar") # tenant_ar, vendor_ap, world_model, erp_connector, aws_infra
    priority: str = Field(default="standard") # standard, high, critical_blocker
    specification: str = Field(..., min_length=10, max_length=2000)
    submitted_by: Optional[str] = "Property Manager"


def list_organizations() -> List[Dict[str, Any]]:
    """Return all onboarded customer organizations from PostgreSQL."""
    with db() as conn:
        rows = conn.execute(
            """SELECT id, name, portfolio_type, tier, aws_region, active_units,
                      contact_email, primary_ledger, ai_engine, description, created_at
               FROM organizations ORDER BY created_at ASC"""
        ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "portfolio_type": r[2],
            "tier": r[3],
            "aws_region": r[4],
            "active_units": r[5],
            "contact_email": r[6],
            "primary_ledger": r[7],
            "ai_engine": r[8],
            "description": r[9] or "",
            "created_at": r[10].isoformat() if hasattr(r[10], "isoformat") else str(r[10])
        }
        for r in rows
    ]


def onboard_organization(data: OnboardCustomerRequest) -> Dict[str, Any]:
    """Onboard a new customer property management organization into PostgreSQL."""
    slug = "".join(c for c in data.name if c.isalnum()).upper()[:8]
    org_id = f"ORG-{slug}"
    now_dt = datetime.now(timezone.utc)
    
    with db() as conn:
        existing = conn.execute("SELECT id FROM organizations WHERE id = %s", (org_id,)).fetchone()
        if existing:
            org_id = f"{org_id}-{str(uuid.uuid4())[:4].upper()}"
            
        conn.execute(
            """INSERT INTO organizations (
                id, name, portfolio_type, tier, aws_region, active_units,
                contact_email, primary_ledger, ai_engine, description, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                org_id, data.name, data.portfolio_type, data.tier, data.aws_region,
                data.active_units, data.contact_email, data.primary_ledger,
                data.ai_engine, data.description or "", now_dt
            )
        )
    return {
        "id": org_id,
        "name": data.name,
        "portfolio_type": data.portfolio_type,
        "tier": data.tier,
        "aws_region": data.aws_region,
        "active_units": data.active_units,
        "contact_email": data.contact_email,
        "primary_ledger": data.primary_ledger,
        "ai_engine": data.ai_engine,
        "created_at": now_dt.isoformat(),
        "description": data.description or ""
    }


def list_feature_requests(org_id: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return customer requirements and feature roadmap items from PostgreSQL."""
    sql = """SELECT id, org_id, org_name, title, category, priority, specification,
                    status, target_release, votes, submitted_by, submitted_at
             FROM feature_requests"""
    conditions = []
    params = []
    if org_id and org_id != "all":
        conditions.append("org_id = %s")
        params.append(org_id)
    if category and category != "all":
        conditions.append("category = %s")
        params.append(category)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY (priority = 'critical_blocker') DESC, votes DESC, submitted_at DESC"
    
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        
    return [
        {
            "id": r[0],
            "org_id": r[1],
            "org_name": r[2],
            "title": r[3],
            "category": r[4],
            "priority": r[5],
            "specification": r[6],
            "status": r[7],
            "target_release": r[8],
            "votes": r[9],
            "submitted_by": r[10],
            "submitted_at": r[11].isoformat() if hasattr(r[11], "isoformat") else str(r[11])
        }
        for r in rows
    ]


def submit_feature_request(data: SubmitFeatureRequest) -> Dict[str, Any]:
    """Submit a new feature requirement or custom template rule into PostgreSQL."""
    now_dt = datetime.now(timezone.utc)
    with db() as conn:
        org_row = conn.execute("SELECT name FROM organizations WHERE id = %s", (data.org_id,)).fetchone()
        if not org_row:
            raise ValueError(f"Organization '{data.org_id}' not found.")
        org_name = org_row[0]
        
        count = conn.execute("SELECT COUNT(*) FROM feature_requests").fetchone()[0]
        req_id = f"REQ-{count + 1001}"
        existing = conn.execute("SELECT id FROM feature_requests WHERE id = %s", (req_id,)).fetchone()
        if existing:
            req_id = f"REQ-{count + 1001}-{str(uuid.uuid4())[:4].upper()}"

        conn.execute(
            """INSERT INTO feature_requests (
                id, org_id, org_name, title, category, priority, specification,
                status, target_release, votes, submitted_by, submitted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'TRIAGED', 'Upcoming Cloud Sprint', 1, %s, %s)""",
            (
                req_id, data.org_id, org_name, data.title, data.category,
                data.priority, data.specification, data.submitted_by or "Property Manager", now_dt
            )
        )
        voter_id = data.submitted_by or data.org_id
        conn.execute(
            "INSERT INTO feature_request_votes (request_id, voter_id) VALUES (%s, %s) ON CONFLICT (request_id, voter_id) DO NOTHING",
            (req_id, voter_id)
        )
        
    return {
        "id": req_id,
        "org_id": data.org_id,
        "org_name": org_name,
        "title": data.title,
        "category": data.category,
        "priority": data.priority,
        "specification": data.specification,
        "status": "TRIAGED",
        "target_release": "Upcoming Cloud Sprint",
        "votes": 1,
        "submitted_by": data.submitted_by or "Property Manager",
        "submitted_at": now_dt.isoformat()
    }


def upvote_feature_request(req_id: str, voter_id: Optional[str] = None) -> Dict[str, Any]:
    """Upvote an existing customer requirement with atomic voter deduplication in PostgreSQL."""
    effective_voter = voter_id or f"voter-session-{req_id}"
    with db() as conn:
        row = conn.execute("SELECT id, votes FROM feature_requests WHERE id = %s", (req_id,)).fetchone()
        if not row:
            raise ValueError(f"Requirement {req_id} not found.")
        current_votes = row[1]
        
        # Concurrency-safe atomic insert: only 1 concurrent execution will insert successfully
        inserted = conn.execute(
            """INSERT INTO feature_request_votes (request_id, voter_id)
               VALUES (%s, %s)
               ON CONFLICT (request_id, voter_id) DO NOTHING
               RETURNING 1""",
            (req_id, effective_voter)
        ).fetchone()
        
        if not inserted:
            return {
                "status": "duplicate_prevented",
                "request_id": req_id,
                "new_vote_count": current_votes,
                "message": f"Vote already recorded for voter '{effective_voter}'."
            }
            
        updated_votes = conn.execute(
            "UPDATE feature_requests SET votes = votes + 1 WHERE id = %s RETURNING votes",
            (req_id,)
        ).fetchone()[0]
        
    return {"status": "ok", "request_id": req_id, "new_vote_count": updated_votes}

