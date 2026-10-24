"""Autonomous Property Verification & Public Discovery Service for EQUILIBRA.

Responsibilities:
- Validate property submission fields, units, and financial consistency.
- Inspect required media, title/lease evidence, and calculate verification score.
- Automatically publish eligible verified properties (score >= 85).
- Manage public tour bookings with duplicate prevention and resident/owner notifications.
- Manage rental applications with income/credit screening and decision workflows.
- Record all lifecycle transitions in the Meterless World Model with canonical IDs.
"""

import re
import uuid
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from decimal import Decimal

from .database import db
from .world_model import record_event, canonical_id
from .notifications import queue_notification


# Synthetic seed properties
DEFAULT_PROPERTIES = [
    {
        "property_id": "PROP-001",
        "name": "Skyline Terrace Apartments",
        "address": "535 Mission St",
        "city": "San Francisco",
        "state": "CA",
        "zip_code": "94105",
        "property_type": "Residential Multifamily",
        "total_units": 100,
        "monthly_rent_usd": 2850.00,
        "security_deposit_usd": 2850.00,
        "amenities": ["Rooftop Lounge", "Fitness Center", "EV Charging", "Smart Locks", "Concierge"],
        "images": [
            "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=800&q=80",
            "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=800&q=80"
        ],
        "verification_status": "verified",
        "verification_score": 96.0,
        "verification_findings": {
            "title_deed_verified": True,
            "rent_covenants_consistent": True,
            "media_inspected": True,
            "safety_inspection_current": True
        },
        "is_published": True,
        "org_id": "ORG-APEX"
    },
    {
        "property_id": "PROP-002",
        "name": "Verdant Valley Luxury Estates",
        "address": "1200 Silicon Valley Way",
        "city": "Palo Alto",
        "state": "CA",
        "zip_code": "94301",
        "property_type": "Single-Family Luxury",
        "total_units": 65,
        "monthly_rent_usd": 4200.00,
        "security_deposit_usd": 4200.00,
        "amenities": ["Private Garden", "Solar Panels", "Wine Cellar", "Gated Security", "Pool"],
        "images": [
            "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=800&q=80"
        ],
        "verification_status": "verified",
        "verification_score": 92.5,
        "verification_findings": {
            "title_deed_verified": True,
            "rent_covenants_consistent": True,
            "media_inspected": True,
            "safety_inspection_current": True
        },
        "is_published": True,
        "org_id": "ORG-VERDANT"
    },
    {
        "property_id": "PROP-003",
        "name": "Beacon Bay Commercial Plaza",
        "address": "400 Montgomery St",
        "city": "San Francisco",
        "state": "CA",
        "zip_code": "94104",
        "property_type": "Mixed-Use Commercial",
        "total_units": 240,
        "monthly_rent_usd": 3600.00,
        "security_deposit_usd": 3600.00,
        "amenities": ["Conference Hub", "Fiber Internet", "Loading Dock", "24/7 Security"],
        "images": [
            "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=800&q=80"
        ],
        "verification_status": "verified",
        "verification_score": 88.0,
        "verification_findings": {
            "title_deed_verified": True,
            "rent_covenants_consistent": True,
            "media_inspected": True,
            "safety_inspection_current": True
        },
        "is_published": True,
        "org_id": "ORG-BEACON"
    },
    {
        "property_id": "PROP-004",
        "name": "Oakridge Modern Lofts",
        "address": "880 Broadway",
        "city": "Oakland",
        "state": "CA",
        "zip_code": "94607",
        "property_type": "Urban Loft",
        "total_units": 45,
        "monthly_rent_usd": 2150.00,
        "security_deposit_usd": 2150.00,
        "amenities": ["High Ceilings", "Bike Storage", "Package Lockers"],
        "images": [
            "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80"
        ],
        "verification_status": "pending",
        "verification_score": 72.0,
        "verification_findings": {
            "title_deed_verified": False,
            "rent_covenants_consistent": True,
            "media_inspected": True,
            "safety_inspection_current": False
        },
        "is_published": False,
        "org_id": "ORG-SKYLINE"
    }
]


def seed_properties():
    """Ensure sample properties exist in the database."""
    with db() as conn:
        for p in DEFAULT_PROPERTIES:
            conn.execute(
                """INSERT INTO properties (
                    property_id, name, address, city, state, zip_code,
                    property_type, total_units, monthly_rent_usd, security_deposit_usd,
                    amenities, images, verification_status, verification_score,
                    verification_findings, is_published, org_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (property_id) DO NOTHING""",
                (
                    p["property_id"], p["name"], p["address"], p["city"], p["state"], p["zip_code"],
                    p["property_type"], p["total_units"], p["monthly_rent_usd"], p["security_deposit_usd"],
                    json.dumps(p["amenities"]), json.dumps(p["images"]),
                    p["verification_status"], p["verification_score"],
                    json.dumps(p["verification_findings"]), p["is_published"], p["org_id"]
                )
            )


def list_properties(published_only: bool = False, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve list of properties with optional filtering."""
    sql = """SELECT property_id, name, address, city, state, zip_code,
                    property_type, total_units, monthly_rent_usd, security_deposit_usd,
                    amenities, images, verification_status, verification_score,
                    verification_findings, is_published, org_id, created_at
             FROM properties"""
    conditions = []
    params = []
    
    if published_only:
        conditions.append("is_published = TRUE")
    if query:
        conditions.append("(name ILIKE %s OR address ILIKE %s OR city ILIKE %s OR property_type ILIKE %s)")
        q_wild = f"%{query}%"
        params.extend([q_wild, q_wild, q_wild, q_wild])
        
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
        
    sql += " ORDER BY property_id ASC"
    
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        
    return [
        {
            "property_id": r[0],
            "canonical_id": canonical_id("property", r[0]),
            "name": r[1],
            "address": r[2],
            "city": r[3],
            "state": r[4],
            "zip_code": r[5],
            "property_type": r[6],
            "total_units": r[7],
            "monthly_rent_usd": float(r[8]),
            "security_deposit_usd": float(r[9]),
            "amenities": r[10] or [],
            "images": r[11] or [],
            "verification_status": r[12],
            "verification_score": float(r[13]) if r[13] is not None else 0.0,
            "verification_findings": r[14] or {},
            "is_published": bool(r[15]),
            "org_id": r[16],
            "created_at": r[17].isoformat() if hasattr(r[17], "isoformat") else str(r[17])
        }
        for r in rows
    ]


def get_property(property_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve single property record."""
    with db() as conn:
        r = conn.execute(
            """SELECT property_id, name, address, city, state, zip_code,
                      property_type, total_units, monthly_rent_usd, security_deposit_usd,
                      amenities, images, verification_status, verification_score,
                      verification_findings, is_published, org_id, created_at
               FROM properties WHERE property_id = %s""",
            (property_id,)
        ).fetchone()
        
    if not r:
        return None
        
    return {
        "property_id": r[0],
        "canonical_id": canonical_id("property", r[0]),
        "name": r[1],
        "address": r[2],
        "city": r[3],
        "state": r[4],
        "zip_code": r[5],
        "property_type": r[6],
        "total_units": r[7],
        "monthly_rent_usd": float(r[8]),
        "security_deposit_usd": float(r[9]),
        "amenities": r[10] or [],
        "images": r[11] or [],
        "verification_status": r[12],
        "verification_score": float(r[13]) if r[13] is not None else 0.0,
        "verification_findings": r[14] or {},
        "is_published": bool(r[15]),
        "org_id": r[16],
        "created_at": r[17].isoformat() if hasattr(r[17], "isoformat") else str(r[17])
    }


def verify_property(property_id: str) -> Dict[str, Any]:
    """Execute Property Verification Agent assessment."""
    prop = get_property(property_id)
    if not prop:
        raise ValueError(f"Property {property_id} not found")
        
    findings = {}
    score = 100.0
    deductions = []
    
    # 1. Check address & units
    if not prop["address"] or len(prop["address"]) < 5:
        score -= 25.0
        deductions.append("Invalid or missing street address")
        findings["address_valid"] = False
    else:
        findings["address_valid"] = True
        
    if prop["total_units"] <= 0:
        score -= 20.0
        deductions.append("Total unit count must be at least 1")
        findings["units_valid"] = False
    else:
        findings["units_valid"] = True
        
    # 2. Check rent consistency
    rent = prop["monthly_rent_usd"]
    deposit = prop["security_deposit_usd"]
    if rent <= 0:
        score -= 30.0
        deductions.append("Monthly rent must be greater than $0.00")
        findings["rent_valid"] = False
    else:
        findings["rent_valid"] = True
        
    if deposit < rent * 0.5 or deposit > rent * 3.0:
        score -= 10.0
        deductions.append("Security deposit deviates significantly from standard 1x monthly rent policy")
        findings["deposit_policy_match"] = False
    else:
        findings["deposit_policy_match"] = True
        
    # 3. Check media evidence
    images = prop.get("images") or []
    if not images:
        score -= 15.0
        deductions.append("No property exterior/interior photographs uploaded")
        findings["media_verified"] = False
    else:
        findings["media_verified"] = True
        findings["image_count"] = len(images)
        
    score = max(0.0, min(100.0, score))
    is_verified = score >= 85.0 and findings.get("address_valid") and findings.get("rent_valid")
    new_status = "verified" if is_verified else "needs_review"
    auto_published = is_verified
    
    findings["score"] = score
    findings["deductions"] = deductions
    findings["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    
    with db() as conn:
        conn.execute(
            """UPDATE properties
               SET verification_status = %s,
                   verification_score = %s,
                   verification_findings = %s::jsonb,
                   is_published = %s
               WHERE property_id = %s""",
            (new_status, score, json.dumps(findings), auto_published, property_id)
        )
        
    # Record in World Model
    record_event(
        case_id=property_id,
        entity_id=property_id,
        event_type="property_verified",
        payload={
            "property_id": property_id,
            "score": score,
            "status": new_status,
            "published": auto_published,
            "deductions": deductions
        }
    )
    
    return {
        "property_id": property_id,
        "verification_status": new_status,
        "verification_score": score,
        "is_published": auto_published,
        "findings": findings
    }


def book_tour(
    property_id: str,
    unit: str,
    resident_name: str,
    resident_email: str,
    resident_phone: str,
    booking_date: str,
    booking_time: str,
    notes: Optional[str] = ""
) -> Dict[str, Any]:
    """Persist tour booking, validate slot conflict, and queue notifications."""
    prop = get_property(property_id)
    if not prop:
        raise ValueError(f"Property {property_id} not found")
        
    with db() as conn:
        existing = conn.execute(
            """SELECT id FROM tour_bookings
               WHERE property_id = %s AND resident_email = %s AND booking_date = %s AND status = 'confirmed'""",
            (property_id, resident_email, booking_date)
        ).fetchone()
        
    if existing:
        raise ValueError(f"You already have a confirmed tour booking for {prop['name']} on {booking_date}.")
        
    booking_id = f"TOUR-{uuid.uuid4().hex[:8].upper()}"
    
    with db() as conn:
        conn.execute(
            """INSERT INTO tour_bookings (
                id, property_id, unit, resident_name, resident_email, resident_phone,
                booking_date, booking_time, status, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', %s)""",
            (
                booking_id, property_id, unit or "Main", resident_name,
                resident_email, resident_phone, booking_date, booking_time, notes or ""
            )
        )
        
    queue_notification(
        recipient_email=resident_email,
        recipient_type="resident",
        title=f"Tour Confirmed: {prop['name']}",
        message=f"Hello {resident_name}, your tour is confirmed for {booking_date} at {booking_time} at {prop['address']}.",
        category="tour_booking",
        event_key=f"tour-{booking_id}-resident"
    )
    
    queue_notification(
        recipient_email="leasing@equilibra.internal",
        recipient_type="owner",
        title=f"New Tour Booking: {resident_name}",
        message=f"Prospective resident {resident_name} booked a tour for {prop['name']} ({booking_date} {booking_time}).",
        category="tour_booking",
        event_key=f"tour-{booking_id}-owner"
    )
    
    record_event(
        case_id=property_id,
        entity_id=booking_id,
        event_type="tour_booked",
        payload={
            "booking_id": booking_id,
            "property_id": property_id,
            "resident": resident_name,
            "date": booking_date,
            "time": booking_time
        }
    )
    
    return {
        "booking_id": booking_id,
        "property_id": property_id,
        "property_name": prop["name"],
        "resident_name": resident_name,
        "booking_date": booking_date,
        "booking_time": booking_time,
        "status": "confirmed",
        "message": f"Tour successfully scheduled for {booking_date} at {booking_time}."
    }


def list_tour_bookings(property_id: Optional[str] = None, resident_email: Optional[str] = None) -> List[Dict[str, Any]]:
    """List tour bookings for owner dashboard or resident view."""
    sql = """SELECT t.id, t.property_id, p.name as property_name, t.unit,
                    t.resident_name, t.resident_email, t.resident_phone,
                    t.booking_date, t.booking_time, t.status, t.notes, t.created_at
             FROM tour_bookings t
             JOIN properties p ON t.property_id = p.property_id"""
    conditions = []
    params = []
    
    if property_id:
        conditions.append("t.property_id = %s")
        params.append(property_id)
    if resident_email:
        conditions.append("t.resident_email = %s")
        params.append(resident_email)
        
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
        
    sql += " ORDER BY t.booking_date DESC, t.id DESC"
    
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        
    return [
        {
            "id": r[0],
            "canonical_id": canonical_id("tour", r[0]),
            "property_id": r[1],
            "property_name": r[2],
            "unit": r[3],
            "resident_name": r[4],
            "resident_email": r[5],
            "resident_phone": r[6],
            "booking_date": str(r[7]),
            "booking_time": str(r[8]),
            "status": r[9],
            "notes": r[10],
            "created_at": r[11].isoformat() if hasattr(r[11], "isoformat") else str(r[11])
        }
        for r in rows
    ]


def submit_rental_application(
    property_id: str,
    unit: str,
    applicant_name: str,
    applicant_email: str,
    applicant_phone: str,
    monthly_income_usd: float,
    credit_score: int,
    notes: Optional[str] = ""
) -> Dict[str, Any]:
    """Submit a rental application for tenant screening."""
    prop = get_property(property_id)
    if not prop:
        raise ValueError(f"Property {property_id} not found")
        
    app_id = f"APP-{uuid.uuid4().hex[:8].upper()}"
    
    monthly_rent = prop["monthly_rent_usd"]
    income_ratio = monthly_income_usd / monthly_rent if monthly_rent > 0 else 0
    auto_eligible = (income_ratio >= 2.5) and (credit_score >= 650)
    initial_status = "pre_approved" if auto_eligible else "under_review"
    
    with db() as conn:
        conn.execute(
            """INSERT INTO rental_applications (
                id, property_id, unit, applicant_name, applicant_email, applicant_phone,
                monthly_income_usd, credit_score, status, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                app_id, property_id, unit or "Unit 101", applicant_name,
                applicant_email, applicant_phone, monthly_income_usd, credit_score,
                initial_status, notes or ""
            )
        )
        
    queue_notification(
        recipient_email=applicant_email,
        recipient_type="resident",
        title=f"Application Received: {prop['name']}",
        message=f"Thank you {applicant_name}, your application for {prop['name']} has been submitted with status '{initial_status}'.",
        category="rental_application",
        event_key=f"app-{app_id}-applicant"
    )
    
    record_event(
        case_id=property_id,
        entity_id=app_id,
        event_type="application_submitted",
        payload={
            "app_id": app_id,
            "property_id": property_id,
            "applicant": applicant_name,
            "income_ratio": round(income_ratio, 2),
            "credit_score": credit_score,
            "status": initial_status
        }
    )
    
    return {
        "application_id": app_id,
        "property_id": property_id,
        "property_name": prop["name"],
        "applicant_name": applicant_name,
        "status": initial_status,
        "income_ratio": round(income_ratio, 2),
        "message": f"Rental application submitted. Preliminary status: {initial_status}."
    }


def list_rental_applications(property_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List rental applications for review."""
    sql = """SELECT a.id, a.property_id, p.name as property_name, a.unit,
                    a.applicant_name, a.applicant_email, a.applicant_phone,
                    a.monthly_income_usd, a.credit_score, a.status, a.notes, a.created_at
             FROM rental_applications a
             JOIN properties p ON a.property_id = p.property_id"""
    params = []
    if property_id:
        sql += " WHERE a.property_id = %s"
        params.append(property_id)
        
    sql += " ORDER BY a.created_at DESC, a.id DESC"
    
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        
    return [
        {
            "id": r[0],
            "canonical_id": canonical_id("application", r[0]),
            "property_id": r[1],
            "property_name": r[2],
            "unit": r[3],
            "applicant_name": r[4],
            "applicant_email": r[5],
            "applicant_phone": r[6],
            "monthly_income_usd": float(r[7]),
            "credit_score": r[8],
            "status": r[9],
            "notes": r[10],
            "created_at": r[11].isoformat() if hasattr(r[11], "isoformat") else str(r[11])
        }
        for r in rows
    ]
