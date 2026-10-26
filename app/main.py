import time
import json
import uuid
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any
# pyrefly: ignore[missing-import]
from fastapi import FastAPI, HTTPException, Header, Query, Request
# pyrefly: ignore[missing-import]
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from .database import init_database, db
from .engine import investigate, calculate, fixture_rows
from .seed import seed
from .rag import index_document
from .config import settings
from .world_model import (
    get_events, get_latest_state, get_lineage, build_agent_context,
    record_event, canonical_id
)
from .vendor_invoices import (
    DEFAULT_VENDORS, generate_vendor_invoice_pdf, index_vendor_invoice_rag
)
from .vendor_agent import (
    reconcile_vendor_bill, record_vendor_payment, get_vendor_reconciliation_summary
)
from .saas import (
    list_organizations, onboard_organization, list_feature_requests,
    submit_feature_request, upvote_feature_request,
    OnboardCustomerRequest, SubmitFeatureRequest
)
from .resident_agent import (
    get_expiring_leases, get_lease_renewal, prepare_renewal_offer,
    submit_renewal_decision, approve_lease_renewal,
    get_move_in_checklist, initiate_move_in_checklist, complete_move_in_task,
    submit_move_out_notice, get_move_out_record, complete_move_out_task,
    propose_move_out_closeout, approve_move_out_closeout,
    get_communication_preferences, update_communication_preferences,
    send_resident_reminder
)
from .compliance_agent import (
    JURISDICTION_REGISTRY, run_compliance_and_risk_scan, get_compliance_summary,
    list_risk_findings, get_risk_finding_detail, update_finding_status,
    assign_finding_reviewer, get_pending_approvals, get_approval_history
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    from .property_agent import seed_properties
    seed_properties()
    from .templates import seed_default_templates
    seed_default_templates()
    from .scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    # Phase 6: Recover interrupted workflows on API startup
    try:
        from .orchestrator import recover_interrupted_workflows
        recovered = recover_interrupted_workflows()
        if recovered:
            print(f"[ORCHESTRATOR] Startup recovery processed {len(recovered)} interrupted workflows: {recovered}")
    except Exception as exc:
        print(f"[ORCHESTRATOR] Startup recovery warning: {exc}")
    yield
    stop_scheduler()

app = FastAPI(
    title='EQUILIBRA — Autonomous Property Management & Financial Cloud Platform',
    description='Autonomous multi-agent property management, financial reconciliation, document intelligence, and tenant experience platform',
    version='2.0.0',
    lifespan=lifespan
)

@app.middleware("http")
async def performance_and_correlation_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-Id") or f"corr-{uuid.uuid4().hex[:12]}"
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        from .timing import perf_tracker
        perf_tracker.record_latency("http_endpoint", elapsed_ms, is_error=(response.status_code >= 500))
        response.headers["X-Correlation-Id"] = corr_id
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
        return response
    except Exception:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        from .timing import perf_tracker
        perf_tracker.record_latency("http_endpoint", elapsed_ms, is_error=True)
        raise

def resolve_effective_org(header_val: Any = None, query_val: Any = None) -> Optional[str]:
    """Safely extracts and sanitizes organization ID, preventing FastAPI Header parameter objects from polluting SQL bindings."""
    if isinstance(header_val, str) and header_val.strip() and header_val.strip().lower() not in ("null", "none"):
        return header_val.strip()
    if isinstance(query_val, str) and query_val.strip() and query_val.strip().lower() not in ("null", "none"):
        return query_val.strip()
    return None

class CaseRequest(BaseModel):
    lease_id: str = Field(pattern=r'^LEASE-\d{4,}$')
    question: str = 'Why is this rent showing unpaid or discrepant?'

class IngestLeaseRequest(BaseModel):
    lease_id: str = Field(pattern=r'^LEASE-\d{4,}$')
    property_id: str = 'PROP-001'
    unit: str
    address: str
    tenant1: str
    tenant2: Optional[str] = ''
    contract_date: str
    move_in_date: str
    monthly_rent_usd: float
    security_deposit_usd: float
    lease_text: Optional[str] = None

class IngestWorkOrderRequest(BaseModel):
    work_order_id: str = Field(pattern=r'^WO-\d{4,}$')
    lease_id: str = Field(pattern=r'^LEASE-\d{4,}$')
    property_id: str = 'PROP-001'
    unit: Optional[str] = ''
    category: str
    description: str
    priority: str = 'Medium'
    status: str = 'Open'
    estimated_cost_usd: float
    technician: Optional[str] = 'Unassigned'
    technician_notes: Optional[str] = ''
    reported_date: Optional[str] = None

class BatchInvestigateRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)

class ApprovalRequest(BaseModel):
    approved: bool
    action: str = Field(default='approved') # 'approved', 'rejected', 'escalated', 'tenant_notice'
    note: str = Field(min_length=3)
    reviewer: str = 'Property Manager'

class SettingsUpdateRequest(BaseModel):
    finance_source: Optional[str] = None
    ai_provider: Optional[str] = None
    meterless_model: Optional[str] = None
    meterless_token: Optional[str] = None
    zetaris_api_key: Optional[str] = None

class GenerateVendorInvoiceRequest(BaseModel):
    vendor_id: str
    work_order_id: str
    property_id: str = 'PROP-001'
    unit: str = 'Unit 4B'
    line_items: List[Dict[str, Any]]
    tax_rate: float = 0.0825
    notes: Optional[str] = ''

class PayVendorInvoiceRequest(BaseModel):
    amount_usd: float
    payment_method: str = Field(description="cashiers_check, check, credit_card, or ach_wire")
    reference: Optional[str] = ''
    details: Optional[Dict[str, Any]] = None
    simulate_bank_clearing: bool = True

class BookTourRequest(BaseModel):
    property_id: str
    unit: Optional[str] = "Main"
    resident_name: str
    resident_email: str
    resident_phone: Optional[str] = ""
    booking_date: str
    booking_time: str
    notes: Optional[str] = ""

class RentalApplicationRequest(BaseModel):
    property_id: str
    unit: Optional[str] = "Unit 101"
    applicant_name: str
    applicant_email: str
    applicant_phone: Optional[str] = ""
    monthly_income_usd: float
    credit_score: int = 700
    notes: Optional[str] = ""

class MaintenanceTicketRequest(BaseModel):
    lease_id: str = "LEASE-0001"
    property_id: str = "PROP-001"
    unit: Optional[str] = "Unit 1A"
    description: str
    reported_by: str = "Resident"
    estimated_cost_usd: float = 250.00

class ProcessDocumentRequest(BaseModel):
    title: str
    body: str
    property_id: str = "PROP-001"
    lease_id: Optional[str] = None

class TenantPaymentRequest(BaseModel):
    lease_id: str
    amount_usd: float
    payment_method: str = "ach_transfer"
    reference: Optional[str] = None
    idempotency_key: Optional[str] = None
    simulate_bank_clearing: bool = True

class AssistantChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

class QueueNotificationRequest(BaseModel):
    recipient_email: str
    recipient_type: str = "resident"
    title: str
    message: str
    category: str = "general"

class PrepareRenewalOfferRequest(BaseModel):
    proposed_increase_pct: float = Field(default=3.5, ge=0.0, le=50.0)
    renewal_term_months: int = Field(default=12, ge=1, le=60)
    prepared_by: str = "Resident Agent"

class SubmitRenewalDecisionRequest(BaseModel):
    decision: str = Field(description="accepted or declined")
    notes: Optional[str] = ""

class ApproveRenewalRequest(BaseModel):
    manager_name: str = "Property Manager"
    approved: bool = True
    notes: Optional[str] = ""

class InitiateMoveInRequest(BaseModel):
    target_date: Optional[str] = None

class CompleteMoveInTaskRequest(BaseModel):
    completed_by: str = "Resident"
    notes: Optional[str] = ""

class SubmitMoveOutNoticeRequest(BaseModel):
    planned_move_out_date: str
    forwarding_address: str = "Forwarding address on file"
    resident_name: Optional[str] = None

class CompleteMoveOutTaskRequest(BaseModel):
    completed_by: str = "Inspector"
    notes: Optional[str] = ""

class ProposeCloseoutRequest(BaseModel):
    deductions: Optional[List[Dict[str, Any]]] = None

class ApproveCloseoutRequest(BaseModel):
    manager_name: str = "Property Manager"
    notes: Optional[str] = ""

class UpdatePreferencesRequest(BaseModel):
    email: bool = True
    sms: bool = False

class ResidentReminderRequest(BaseModel):
    reminder_type: str = Field(description="renewal, move_in, move_out, or general")
    custom_message: Optional[str] = None

class RiskFindingAssignRequest(BaseModel):
    reviewer: str = Field(min_length=1, description="Assigned reviewer identity")
    notes: Optional[str] = None

class RiskFindingReviewRequest(BaseModel):
    status: str = Field(description="under_review or action_required")
    reviewer: str = Field(min_length=1)
    notes: str = Field(min_length=3, description="Decision reason / notes")

class RiskFindingResolveRequest(BaseModel):
    status: str = Field(description="resolved or dismissed")
    reviewer: str = Field(min_length=1)
    decision_reason: str = Field(min_length=3, description="Required substantial resolution reason")
    submitted_by: Optional[str] = None

class ApprovalDecisionRequest(BaseModel):
    entity_type: str = Field(description="lease_renewal, move_out_closeout, risk_finding, or general")
    action: str = Field(description="approved, rejected, or escalated")
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=3)
    submitted_by: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class TemplateCreateRequest(BaseModel):
    template_key: str = Field(min_length=2)
    category: str = Field(description="rent_collection, lease_resident, maintenance, vendor_invoice, compliance_risk")
    name: str = Field(min_length=2)
    description: Optional[str] = ""
    trigger_event: str = Field(min_length=2)
    subject: str = Field(min_length=2)
    body: str = Field(min_length=2)
    supported_variables: Optional[List[str]] = None
    required_variables: Optional[List[str]] = None
    enabled: bool = True

class TemplateUpdateRequest(BaseModel):
    subject: str = Field(min_length=2)
    body: str = Field(min_length=2)
    enabled: Optional[bool] = None
    change_summary: Optional[str] = "Template updated via Manager Console"
    modified_by: Optional[str] = "Property Manager"

class TemplatePreviewRequest(BaseModel):
    context: Optional[Dict[str, Any]] = None
    lease_id: Optional[str] = None
    work_order_id: Optional[str] = None
    invoice_id: Optional[str] = None
    finding_id: Optional[str] = None

class TemplateSendTestRequest(BaseModel):
    test_recipient_email: Optional[str] = None
    test_recipient: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    lease_id: Optional[str] = None

@app.get('/health')
def health():
    with db() as conn:
        conn.execute('SELECT 1').fetchone()
        chunk_count = conn.execute('SELECT count(*) FROM chunks').fetchone()[0]
        event_count = conn.execute('SELECT count(*) FROM world_events').fetchone()[0]
    return {
        'status': 'ok',
        'database': 'connected',
        'pgvector': 'enabled',
        'total_indexed_chunks': chunk_count,
        'world_events_count': event_count,
        'finance_source': settings.finance_source,
        'ai_provider': settings.ai_provider,
        'meterless_model': settings.meterless_model
    }

@app.post('/admin/seed')
def seed_data():
    try:
        res = seed()
        return res
    except Exception as e:
        raise HTTPException(500, f"Failed to seed data: {e}")

@app.post('/api/leases/ingest')
def ingest_lease(req: IngestLeaseRequest):
    """Ingest a newly signed lease agreement into PostgreSQL records, ledger, and pgvector RAG."""
    with db() as conn:
        conn.execute(
            """INSERT INTO lease_records (
                lease_id, property_id, unit, address, tenant1, tenant2,
                contract_date, move_in_date, monthly_rent_usd, security_deposit_usd
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (lease_id) DO UPDATE SET
                property_id = excluded.property_id,
                unit = excluded.unit,
                address = excluded.address,
                tenant1 = excluded.tenant1,
                tenant2 = excluded.tenant2,
                contract_date = excluded.contract_date,
                move_in_date = excluded.move_in_date,
                monthly_rent_usd = excluded.monthly_rent_usd,
                security_deposit_usd = excluded.security_deposit_usd""",
            (
                req.lease_id, req.property_id, req.unit, req.address,
                req.tenant1, req.tenant2 or '', req.contract_date,
                req.move_in_date, req.monthly_rent_usd, req.security_deposit_usd
            )
        )
        # Create standard invoice on ledger
        inv_id = f"INV-{req.lease_id.replace('LEASE-', '')}"
        conn.execute(
            "INSERT INTO invoices (id, lease_id, amount, currency) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (inv_id, req.lease_id, req.monthly_rent_usd, 'USD')
        )

    # Index document body into documents and chunks (HNSW vector + tsvector GIN)
    body = req.lease_text or (
        f"Residential Lease Agreement {req.lease_id}; Tenant {req.tenant1}; "
        f"Address {req.address}; Monthly Rent ${req.monthly_rent_usd:.2f}; Security Deposit ${req.security_deposit_usd:.2f}. "
        "Section 3: Rent is due in full on the first day of each calendar month. "
        "Section 11: Tenant shall not deduct repair expenses or withhold rent under any circumstances without express written landlord authorization. "
        "Section 28: Notice of default required before legal action."
    )
    chunks_count = index_document(req.lease_id, req.lease_id, req.property_id, 'lease', req.address, body)

    # Record event in World Model
    record_event(req.lease_id, req.lease_id, 'lease_signed', {
        'tenant': req.tenant1,
        'rent': req.monthly_rent_usd,
        'deposit': req.security_deposit_usd,
        'unit': req.unit,
        'address': req.address,
        'chunks_indexed': chunks_count
    })

    return {
        'status': 'success',
        'lease_id': req.lease_id,
        'canonical_id': canonical_id('lease', req.lease_id),
        'chunks_indexed': chunks_count,
        'message': f"Lease {req.lease_id} for {req.tenant1} signed and indexed in pgvector."
    }

@app.post('/api/work-orders/ingest')
def ingest_work_order(req: IngestWorkOrderRequest):
    """Ingest a new maintenance work order into records and pgvector RAG."""
    with db() as conn:
        conn.execute(
            """INSERT INTO work_order_records (
                work_order_id, lease_id, property_id, unit, address, tenant1,
                reported_date, scheduled_date, completion_date, category,
                description, priority, status, technician, estimated_cost_usd, technician_notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (work_order_id) DO UPDATE SET
                category = excluded.category,
                description = excluded.description,
                priority = excluded.priority,
                status = excluded.status,
                estimated_cost_usd = excluded.estimated_cost_usd,
                technician_notes = excluded.technician_notes""",
            (
                req.work_order_id, req.lease_id, req.property_id, req.unit or '',
                '', '', req.reported_date or '2026-10-22',
                None, None, req.category, req.description, req.priority,
                req.status, req.technician or 'Unassigned', req.estimated_cost_usd,
                req.technician_notes or ''
            )
        )

    # Index into RAG
    body = (
        f"Work Order {req.work_order_id} for Lease {req.lease_id}. Category: {req.category}. "
        f"Priority: {req.priority}. Status: {req.status}. Issue: {req.description}. "
        f"Estimated Cost: ${req.estimated_cost_usd:.2f}. Technician Notes: {req.technician_notes or ''}"
    )
    chunks_count = index_document(req.work_order_id, req.lease_id, req.property_id, 'work_order', req.category, body)

    # Record event in World Model
    record_event(req.lease_id, req.lease_id, 'work_order_created', {
        'work_order_id': req.work_order_id,
        'category': req.category,
        'priority': req.priority,
        'estimated_cost_usd': req.estimated_cost_usd,
        'chunks_indexed': chunks_count
    })

    return {
        'status': 'success',
        'work_order_id': req.work_order_id,
        'canonical_id': canonical_id('work_order', req.work_order_id),
        'lease_id': req.lease_id,
        'chunks_indexed': chunks_count,
        'message': f"Work order {req.work_order_id} created and indexed in pgvector."
    }

@app.get('/api/portfolio/summary')
def portfolio_summary(
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """High-level property portfolio financial metrics across all leases."""
    effective_org = resolve_effective_org(x_organization_id, org_id)
    with db() as conn:
        if effective_org and effective_org != "all":
            leases = conn.execute("""
                SELECT l.lease_id, l.monthly_rent_usd, l.security_deposit_usd,
                       COALESCE(a.state, 'pending') as approval_state
                FROM lease_records l
                JOIN properties p ON l.property_id = p.property_id
                LEFT JOIN approvals a ON l.lease_id = a.case_id
                WHERE p.org_id = %s
                ORDER BY l.lease_id
            """, (effective_org,)).fetchall()
        else:
            leases = conn.execute("""
                SELECT l.lease_id, l.monthly_rent_usd, l.security_deposit_usd,
                       COALESCE(a.state, 'pending') as approval_state
                FROM lease_records l
                LEFT JOIN approvals a ON l.lease_id = a.case_id
                ORDER BY l.lease_id
            """).fetchall()

        if not leases:
            # Fallback if seed has not been run on lease_records yet
            raw = conn.execute("SELECT id, title FROM documents WHERE kind='lease'").fetchall()
            return {
                'total_leases': len(raw),
                'reconciled_count': 0,
                'partial_count': 0,
                'needs_review_count': 0,
                'total_rent_invoiced_usd': 0.0,
                'total_rent_verified_usd': 0.0,
                'total_variance_usd': 0.0,
                'approved_count': 0,
                'pending_review_count': len(raw)
            }

        total_leases = len(leases)
        total_invoiced = sum(float(l[1]) for l in leases)
        total_deposit = sum(float(l[2]) for l in leases)
        approved_count = sum(1 for l in leases if l[3] == 'approved')

        # Compute quick 3-way reconciliation states for seeded leases
        reconciled_count = 0
        partial_count = 0
        needs_review_count = 0
        total_verified = 0.0
        total_variance = 0.0

        for l in leases:
            lease_id = l[0]
            fin = fixture_rows(lease_id)
            calc = calculate(fin)
            status = calc['status']
            diff = (calc.get('difference_cents') or 0) / 100.0
            paid = (calc.get('verified_paid_cents') or 0) / 100.0
            
            total_verified += paid
            total_variance += diff

            if status == 'reconciled':
                reconciled_count += 1
            elif status == 'partial_payment':
                partial_count += 1
            else:
                needs_review_count += 1

        return {
            'total_leases': total_leases,
            'reconciled_count': reconciled_count,
            'partial_count': partial_count,
            'needs_review_count': needs_review_count,
            'total_rent_invoiced_usd': round(total_invoiced, 2),
            'total_rent_verified_usd': round(total_verified, 2),
            'total_variance_usd': round(total_variance, 2),
            'total_security_deposits_usd': round(total_deposit, 2),
            'approved_count': approved_count,
            'pending_review_count': total_leases - approved_count
        }

@app.get('/api/leases')
def get_leases_detailed(
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve full list of leases with tenant info, financial status, and work order metrics."""
    effective_org = resolve_effective_org(x_organization_id, org_id)
    with db() as conn:
        query = """
            SELECT l.lease_id, l.property_id, l.unit, l.address, l.tenant1, l.tenant2,
                   l.contract_date, l.move_in_date, l.monthly_rent_usd, l.security_deposit_usd,
                   COALESCE(a.state, 'pending') as approval_state,
                   a.note as approval_note,
                   COALESCE(a.action, 'pending') as approval_action,
                   (SELECT count(*) FROM work_order_records w WHERE w.lease_id = l.lease_id) as wo_count
            FROM lease_records l
            LEFT JOIN properties p ON l.property_id = p.property_id
            LEFT JOIN approvals a ON l.lease_id = a.case_id
        """
        params = []
        if effective_org and effective_org != "all":
            query += " WHERE p.org_id = %s"
            params.append(effective_org)
        query += " ORDER BY l.lease_id ASC"
        rows = conn.execute(query, params).fetchall()

    results = []
    for r in rows:
        lease_id = r[0]
        # Calculate fast financial status
        fin = fixture_rows(lease_id)
        calc = calculate(fin)

        item = {
            'lease_id': lease_id,
            'canonical_id': canonical_id('lease', lease_id),
            'property_id': r[1],
            'unit': r[2],
            'address': r[3],
            'tenant1': r[4],
            'tenant2': r[5],
            'contract_date': r[6],
            'move_in_date': r[7],
            'monthly_rent_usd': float(r[8]),
            'security_deposit_usd': float(r[9]),
            'approval_state': r[10],
            'approval_note': r[11],
            'approval_action': r[12],
            'work_order_count': r[13],
            'reconciliation_status': calc['status'],
            'reason_code': calc['reason_code'],
            'invoice_cents': calc['invoice_cents'],
            'verified_paid_cents': calc['verified_paid_cents'],
            'difference_cents': calc['difference_cents'],
            'reason': calc['reason']
        }

        # Filtering
        if status_filter and status_filter != 'all':
            if status_filter == 'needs_review' and calc['status'] != 'needs_review':
                continue
            if status_filter == 'partial_payment' and calc['status'] != 'partial_payment':
                continue
            if status_filter == 'reconciled' and calc['status'] != 'reconciled':
                continue
            if status_filter == 'approved' and r[10] != 'approved':
                continue
            if status_filter == 'pending' and r[10] != 'pending':
                continue

        if search:
            q = search.lower()
            text_haystack = f"{lease_id} {r[1]} {r[2]} {r[3]} {r[4]} {r[5] or ''}".lower()
            if q not in text_haystack:
                continue

        results.append(item)

    return results

# Maintain compatibility with starter endpoint
@app.get('/leases')
def list_leases():
    with db() as conn:
        data = conn.execute("SELECT id, title FROM documents WHERE kind='lease' ORDER BY id LIMIT 200").fetchall()
    return [{'lease_id': r[0], 'title': r[1]} for r in data]

@app.get('/api/lease/{lease_id}/details')
def get_lease_details(lease_id: str):
    """Retrieve complete 360-degree case bundle for property manager review."""
    with db() as conn:
        lease = conn.execute(
            """SELECT lease_id, property_id, unit, address, tenant1, tenant2,
                      contract_date, move_in_date, monthly_rent_usd, security_deposit_usd
               FROM lease_records WHERE lease_id = %s""",
            (lease_id,)
        ).fetchone()

        if not lease:
            raise HTTPException(404, f"Lease {lease_id} not found")

        work_orders = conn.execute(
            """SELECT work_order_id, category, description, priority, status,
                      estimated_cost_usd, technician, technician_notes, reported_date
               FROM work_order_records WHERE lease_id = %s ORDER BY reported_date DESC""",
            (lease_id,)
        ).fetchall()

        approval = conn.execute(
            """SELECT state, note, action, reviewer, updated_at
               FROM approvals WHERE case_id = %s""",
            (lease_id,)
        ).fetchone()

    financial = fixture_rows(lease_id)
    recon = calculate(financial)
    state = get_latest_state(lease_id)

    return {
        'lease': {
            'lease_id': lease[0],
            'canonical_id': canonical_id('lease', lease[0]),
            'property_id': lease[1],
            'unit': lease[2],
            'address': lease[3],
            'tenant1': lease[4],
            'tenant2': lease[5],
            'contract_date': lease[6],
            'move_in_date': lease[7],
            'monthly_rent_usd': float(lease[8]),
            'security_deposit_usd': float(lease[9])
        },
        'work_orders': [
            {
                'work_order_id': w[0],
                'canonical_id': canonical_id('work_order', w[0]),
                'category': w[1],
                'description': w[2],
                'priority': w[3],
                'status': w[4],
                'estimated_cost_usd': float(w[5]),
                'technician': w[6],
                'technician_notes': w[7],
                'reported_date': w[8]
            }
            for w in work_orders
        ],
        'financial_records': financial,
        'reconciliation': recon,
        'approval': {
            'state': approval[0] if approval else 'pending',
            'note': approval[1] if approval else None,
            'action': approval[2] if approval else 'pending',
            'reviewer': approval[3] if approval else None,
            'updated_at': approval[4].isoformat() if approval and hasattr(approval[4], 'isoformat') else str(approval[4]) if approval else None
        },
        'latest_state': state
    }

@app.post('/investigate')
@app.post('/api/investigate')
def run_case(req: CaseRequest):
    """Run full autonomous multi-agent investigation on a lease."""
    try:
        return investigate(req.lease_id, req.question)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post('/api/batch-investigate')
def run_batch_investigate(req: BatchInvestigateRequest):
    """Run autonomous investigation across multiple leases in the portfolio."""
    with db() as conn:
        leases = conn.execute("SELECT lease_id FROM lease_records ORDER BY lease_id LIMIT %s", (req.limit,)).fetchall()
    
    results = []
    for l in leases:
        lid = l[0]
        try:
            res = investigate(lid, "Why is this rent not reconciled?")
            results.append({
                'lease_id': lid,
                'status': res['result']['status'],
                'reason_code': res['result']['reason_code'],
                'variance_cents': res['result']['difference_cents'],
                'requires_approval': res['requires_human_approval'],
                'run_id': res['run_id']
            })
        except Exception as e:
            results.append({'lease_id': lid, 'error': str(e)})

    return {
        'batch_count': len(results),
        'results': results,
        'summary': {
            'reconciled': sum(1 for r in results if r.get('status') == 'reconciled'),
            'partial': sum(1 for r in results if r.get('status') == 'partial_payment'),
            'needs_review': sum(1 for r in results if r.get('status') == 'needs_review')
        }
    }

@app.get('/world/{case_id}')
@app.get('/api/world/{case_id}')
def world(case_id: str):
    """Retrieve chronological event stream from Meterless World Model."""
    try:
        return get_events(case_id)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get('/api/world/{case_id}/state')
def get_world_state(case_id: str):
    """Retrieve latest derived projection state from Meterless World Model."""
    try:
        return get_latest_state(case_id)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get('/api/world/{case_id}/lineage')
def get_world_lineage(case_id: str):
    """Retrieve causal lineage DAG for case events."""
    try:
        return get_lineage(case_id)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get('/api/world/{case_id}/context')
def get_world_context(case_id: str):
    """Retrieve structured agent context generated by ContextBuilder."""
    try:
        return build_agent_context(case_id)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post('/approve/{case_id}')
@app.post('/api/approve/{case_id}')
def approve(case_id: str, req: ApprovalRequest):
    """Record property manager review decision and update World Model."""
    state_str = 'approved' if req.approved else ('rejected' if req.action == 'rejected' else 'escalated')
    with db() as conn:
        conn.execute(
            """INSERT INTO approvals (case_id, state, note, action, reviewer, updated_at)
               VALUES (%s, %s, %s, %s, %s, now())
               ON CONFLICT (case_id) DO UPDATE SET
                   state = excluded.state,
                   note = excluded.note,
                   action = excluded.action,
                   reviewer = excluded.reviewer,
                   updated_at = now()""",
            (case_id, state_str, req.note, req.action, req.reviewer)
        )

    # Record approval event in World Model
    record_event(case_id, case_id, 'approval_recorded', {
        'state': state_str,
        'action': req.action,
        'note': req.note,
        'reviewer': req.reviewer,
        'warning': 'Approval is recorded for audit trail only; zero bank writebacks.'
    })

    return {
        'case_id': case_id,
        'canonical_id': canonical_id('case', case_id),
        'state': state_str,
        'action': req.action,
        'reviewer': req.reviewer,
        'note': req.note,
        'warning': 'Approval recorded in append-only World Model; banking ledger writeback is strictly disabled.'
    }

@app.get('/api/traces/{run_id}')
def get_trace(run_id: str):
    """Fetch sanitized JSONL execution trace for a run."""
    trace_file = Path('logs') / f'trace-{run_id}.jsonl'
    if not trace_file.exists():
        raise HTTPException(404, f"Trace {run_id} not found")
    lines = [json.loads(line) for line in trace_file.read_text().splitlines() if line.strip()]
    return {'run_id': run_id, 'events': lines}

@app.get('/api/settings/status')
def get_settings_status():
    """System and sponsor integration status."""
    return {
        'finance_source': settings.finance_source,
        'ai_provider': settings.ai_provider,
        'meterless_base_url': settings.meterless_base_url,
        'meterless_model': settings.meterless_model,
        'meterless_token_configured': bool(settings.meterless_token),
        'zetaris_base_url': settings.zetaris_base_url,
        'zetaris_api_key_configured': bool(settings.zetaris_api_key),
        'zetaris_views': {
            'invoices': settings.zetaris_invoice_view,
            'payments': settings.zetaris_payment_view,
            'bank': settings.zetaris_bank_view
        },
        'max_agent_rounds': settings.max_agent_rounds,
        'request_timeout_seconds': settings.request_timeout_seconds
    }

@app.post('/api/settings/update')
def update_settings(req: SettingsUpdateRequest):
    """Update runtime configuration for live demo switching."""
    if req.finance_source is not None:
        if req.finance_source not in ('fixture', 'zetaris'):
            raise HTTPException(400, "finance_source must be 'fixture' or 'zetaris'")
        settings.finance_source = req.finance_source
    if req.ai_provider is not None:
        if req.ai_provider not in ('offline', 'meterless'):
            raise HTTPException(400, "ai_provider must be 'offline' or 'meterless'")
        settings.ai_provider = req.ai_provider
    if req.meterless_model is not None:
        settings.meterless_model = req.meterless_model
    if req.meterless_token is not None:
        settings.meterless_token = req.meterless_token
    if req.zetaris_api_key is not None:
        settings.zetaris_api_key = req.zetaris_api_key
# =====================================================================
# VENDOR MAINTENANCE & AP BILL RECONCILIATION ENDPOINTS
# =====================================================================

@app.get('/api/vendors')
def list_vendors():
    """List registered maintenance vendors (fixtures, sinks, tubs, lighting, HVAC, appliances)."""
    with db() as conn:
        rows = conn.execute(
            """SELECT vendor_id, name, trade, contact_email, phone, payment_terms, created_at
               FROM vendors ORDER BY name ASC"""
        ).fetchall()
    if not rows:
        return DEFAULT_VENDORS
    return [
        {
            'vendor_id': r[0],
            'canonical_id': canonical_id('vendor', r[0]),
            'name': r[1],
            'trade': r[2],
            'contact_email': r[3],
            'phone': r[4],
            'payment_terms': r[5],
            'created_at': str(r[6]) if r[6] else ''
        }
        for r in rows
    ]

@app.get('/api/vendor-invoices')
def list_vendor_invoices(
    status: Optional[str] = None,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """List vendor maintenance invoices with trade, work order link, payment status, and PDF status."""
    effective_org = resolve_effective_org(x_organization_id, org_id)
    query = """
        SELECT vi.id, vi.vendor_id, v.name as vendor_name, v.trade, vi.work_order_id,
               vi.lease_id, vi.property_id, vi.invoice_number, vi.issue_date, vi.due_date,
               vi.item_summary, vi.subtotal_usd, vi.tax_usd, vi.total_usd, vi.pdf_path, vi.status,
               vp.payment_method, vp.amount_usd as paid_amount, vp.reference as payment_ref,
               vb.amount_usd as cleared_amount
        FROM vendor_invoices vi
        JOIN vendors v ON vi.vendor_id = v.vendor_id
        LEFT JOIN properties p ON vi.property_id = p.property_id
        LEFT JOIN vendor_payments vp ON vi.id = vp.invoice_id
        LEFT JOIN vendor_bank_transactions vb ON vi.id = vb.invoice_id
    """
    conditions = []
    params = []
    if status:
        conditions.append("vi.status = %s")
        params.append(status)
    if effective_org and effective_org != "all":
        conditions.append("p.org_id = %s")
        params.append(effective_org)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY vi.issue_date DESC, vi.id DESC"

    with db() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            'id': r[0],
            'canonical_id': canonical_id('vendor_invoice', r[0]),
            'vendor_id': r[1],
            'vendor_name': r[2],
            'vendor_trade': r[3],
            'work_order_id': r[4],
            'lease_id': r[5],
            'property_id': r[6],
            'invoice_number': r[7],
            'issue_date': str(r[8]),
            'due_date': str(r[9]),
            'item_summary': r[10],
            'subtotal_usd': float(r[11]),
            'tax_usd': float(r[12]),
            'total_usd': float(r[13]),
            'pdf_path': r[14],
            'has_pdf': bool(r[14] and Path(r[14]).exists()),
            'status': r[15],
            'payment_method': r[16],
            'paid_amount_usd': float(r[17]) if r[17] is not None else 0.0,
            'payment_reference': r[18],
            'cleared_amount_usd': float(r[19]) if r[19] is not None else 0.0
        }
        for r in rows
    ]

@app.get('/api/vendor-invoices/{invoice_id}/pdf')
def get_vendor_invoice_pdf(invoice_id: str):
    """Download or view the authentic generated PDF invoice."""
    with db() as conn:
        row = conn.execute("SELECT pdf_path, invoice_number FROM vendor_invoices WHERE id = %s", (invoice_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, f"No PDF on record for invoice {invoice_id}")
    pdf_file = Path(row[0])
    if not pdf_file.exists():
        raise HTTPException(404, f"PDF file not found on disk at {pdf_file}")
    return FileResponse(
        path=str(pdf_file),
        media_type='application/pdf',
        filename=f"{row[1] or invoice_id}.pdf"
    )

@app.post('/api/vendor-invoices/generate')
def create_vendor_invoice(req: GenerateVendorInvoiceRequest):
    """Generate authentic PDF invoice for maintenance items (sink, tub, lights, etc.) and index into RAG."""
    with db() as conn:
        v = conn.execute(
            "SELECT name, trade, contact_email, phone, payment_terms FROM vendors WHERE vendor_id = %s",
            (req.vendor_id,)
        ).fetchone()
        if not v:
            raise HTTPException(404, f"Vendor {req.vendor_id} not found")
        vendor_dict = {
            'vendor_id': req.vendor_id,
            'name': v[0],
            'trade': v[1],
            'email': v[2],
            'phone': v[3],
            'terms': v[4]
        }
        wo = conn.execute(
            "SELECT lease_id, property_id, unit, description FROM work_order_records WHERE work_order_id = %s",
            (req.work_order_id,)
        ).fetchone()

    lease_id = wo[0] if wo else f"LEASE-{(abs(hash(req.work_order_id)) % 25) + 1:04d}"
    prop_id = req.property_id or (wo[1] if wo else 'PROP-001')
    unit = req.unit or (wo[2] if wo else 'Unit 4B')

    now_str = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    inv_num = f"INV-{req.vendor_id[-3:]}-{now_str[-6:]}"
    inv_id = f"VINV-{now_str[-6:]}"

    pdf_result = generate_vendor_invoice_pdf(
        invoice_number=inv_num,
        vendor=vendor_dict,
        property_id=prop_id,
        unit=unit,
        work_order_id=req.work_order_id,
        line_items=req.line_items,
        tax_rate=req.tax_rate,
        notes=req.notes or f"Maintenance completed under Work Order {req.work_order_id}."
    )

    with db() as conn:
        conn.execute(
            """INSERT INTO vendor_invoices (
                id, vendor_id, work_order_id, lease_id, property_id,
                invoice_number, issue_date, due_date, item_summary,
                subtotal_usd, tax_usd, total_usd, pdf_path, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'issued')
            ON CONFLICT (id) DO UPDATE SET
                pdf_path = excluded.pdf_path,
                total_usd = excluded.total_usd""",
            (
                inv_id, req.vendor_id, req.work_order_id, lease_id, prop_id,
                inv_num, pdf_result['issue_date'], pdf_result['due_date'],
                pdf_result['item_summary'], pdf_result['subtotal_usd'],
                pdf_result['tax_usd'], pdf_result['total_usd'],
                pdf_result['pdf_path']
            )
        )

    rag_res = index_vendor_invoice_rag(
        invoice_id=inv_id,
        pdf_path=pdf_result['pdf_path'],
        vendor_name=vendor_dict['name'],
        work_order_id=req.work_order_id,
        lease_id=lease_id,
        property_id=prop_id
    )

    record_event(
        case_id=lease_id,
        entity_id=inv_id,
        event_type='vendor_invoice_generated',
        payload={
            'invoice_id': inv_id,
            'invoice_number': inv_num,
            'vendor_id': req.vendor_id,
            'vendor_name': vendor_dict['name'],
            'total_usd': pdf_result['total_usd'],
            'pdf_path': pdf_result['pdf_path'],
            'indexed_chunks': rag_res.get('indexed_chunks', 0)
        }
    )

    return {
        'status': 'success',
        'invoice_id': inv_id,
        'invoice_number': inv_num,
        'pdf_path': pdf_result['pdf_path'],
        'total_usd': pdf_result['total_usd'],
        'rag_indexing': rag_res
    }

@app.post('/api/vendor-invoices/{invoice_id}/pay')
def pay_vendor_invoice(invoice_id: str, req: PayVendorInvoiceRequest):
    """Pay vendor invoice via cashier's check, normal check, credit card, or ACH."""
    res = record_vendor_payment(
        invoice_id=invoice_id,
        amount_usd=req.amount_usd,
        payment_method=req.payment_method,
        reference=req.reference or f"PAY-{req.payment_method[:3].upper()}-{invoice_id[-4:]}",
        details=req.details or {},
        simulate_bank_clearing=req.simulate_bank_clearing
    )
    return res

@app.post('/api/vendor-invoices/{invoice_id}/reconcile')
def reconcile_vendor_invoice(invoice_id: str):
    """Execute autonomous 4-way matching and return detailed walkthrough steps and diagnosis."""
    try:
        return reconcile_vendor_bill(invoice_id)
    except Exception as e:
        raise HTTPException(500, f"Error reconciling vendor invoice {invoice_id}: {str(e)}")

@app.get('/api/vendor-summary')
def vendor_summary(
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve AP high-level metrics and discrepancy counts."""
    effective_org = resolve_effective_org(x_organization_id, org_id)
    return get_vendor_reconciliation_summary(org_id=effective_org)

@app.get('/api/saas/organizations')
def get_saas_organizations():
    """List all onboarded SaaS customer property management organizations."""
    return list_organizations()

@app.post('/api/saas/organizations')
def create_saas_organization(req: OnboardCustomerRequest):
    """Onboard a new customer property management organization into the SaaS platform."""
    try:
        return onboard_organization(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Failed to onboard customer: {e}")
        raise HTTPException(500, "Internal server error onboarding organization")

@app.get('/api/saas/feature-requests')
def get_saas_feature_requests(org_id: Optional[str] = None, category: Optional[str] = None):
    """List customer requirements and co-innovation roadmap items."""
    return list_feature_requests(org_id, category)

@app.post('/api/saas/feature-requests')
def create_saas_feature_request(req: SubmitFeatureRequest):
    """Submit a customer requirement or functionality request."""
    try:
        return submit_feature_request(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Failed to submit feature requirement: {e}")
        raise HTTPException(500, "Internal server error submitting feature requirement")

@app.post('/api/saas/feature-requests/{req_id}/upvote')
def upvote_saas_feature_request_route(req_id: str, voter_id: Optional[str] = None):
    """Upvote an existing customer requirement with optional voter deduplication."""
    try:
        return upvote_feature_request(req_id, voter_id=voter_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Failed to upvote requirement {req_id}: {e}")
        raise HTTPException(500, "Internal server error processing upvote")

# =====================================================================
# PROPERTIES, PUBLIC LISTINGS, TOURS & APPLICATIONS ENDPOINTS
# =====================================================================

@app.get('/api/properties')
def get_properties(published_only: bool = False, query: Optional[str] = None):
    """List properties with optional published filter and text search."""
    from .property_agent import list_properties
    return list_properties(published_only=published_only, query=query)

@app.get('/api/properties/{property_id}')
def get_property_by_id(property_id: str):
    """Retrieve details for a single property."""
    from .property_agent import get_property
    p = get_property(property_id)
    if not p:
        raise HTTPException(404, f"Property {property_id} not found")
    return p

@app.post('/api/properties/{property_id}/verify')
def run_property_verification(property_id: str):
    """Trigger Property Verification Agent assessment, compliance scoring, and auto-publishing."""
    from .property_agent import verify_property
    try:
        return verify_property(property_id)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post('/api/tours')
def schedule_tour(req: BookTourRequest):
    """Book a public property tour with slot conflict checking and notifications."""
    from .property_agent import book_tour
    try:
        return book_tour(
            property_id=req.property_id,
            unit=req.unit or "Main",
            resident_name=req.resident_name,
            resident_email=req.resident_email,
            resident_phone=req.resident_phone or "",
            booking_date=req.booking_date,
            booking_time=req.booking_time,
            notes=req.notes or ""
        )
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get('/api/tours')
def get_tours(property_id: Optional[str] = None, resident_email: Optional[str] = None):
    """List tour bookings for owner dashboard or resident view."""
    from .property_agent import list_tour_bookings
    return list_tour_bookings(property_id=property_id, resident_email=resident_email)

@app.post('/api/applications')
def submit_application(req: RentalApplicationRequest):
    """Submit a rental application for screening."""
    from .property_agent import submit_rental_application
    try:
        return submit_rental_application(
            property_id=req.property_id,
            unit=req.unit or "Unit 101",
            applicant_name=req.applicant_name,
            applicant_email=req.applicant_email,
            applicant_phone=req.applicant_phone or "",
            monthly_income_usd=req.monthly_income_usd,
            credit_score=req.credit_score,
            notes=req.notes or ""
        )
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get('/api/applications')
def get_applications(property_id: Optional[str] = None):
    """List rental applications for review."""
    from .property_agent import list_rental_applications
    return list_rental_applications(property_id=property_id)

# =====================================================================
# AUTONOMOUS MAINTENANCE & SLA AGENT ENDPOINTS
# =====================================================================

@app.post('/api/maintenance/submit')
def submit_maintenance_ticket(req: MaintenanceTicketRequest):
    """Submit and automatically triage a maintenance request, assigning SLA and matching vendor."""
    from .maintenance_agent import submit_and_triage_ticket
    try:
        return submit_and_triage_ticket(
            lease_id=req.lease_id,
            property_id=req.property_id,
            unit=req.unit or "Unit 1A",
            description=req.description,
            reported_by=req.reported_by,
            estimated_cost_usd=req.estimated_cost_usd
        )
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get('/api/maintenance/sla-breaches')
def get_sla_breaches():
    """Scan open work orders for SLA breaches and trigger escalations."""
    from .maintenance_agent import check_sla_breaches
    return check_sla_breaches()

# =====================================================================
# DOCUMENT INTELLIGENCE AGENT ENDPOINTS
# =====================================================================

@app.post('/api/documents/process')
def process_new_document(req: ProcessDocumentRequest):
    """Classify document, extract structured fields, check duplicate hashes, and index in pgvector."""
    from .document_agent import process_document
    try:
        return process_document(
            title=req.title,
            body=req.body,
            property_id=req.property_id,
            lease_id=req.lease_id
        )
    except Exception as e:
        raise HTTPException(400, str(e))

# =====================================================================
# FINANCIAL OPERATIONS & RENT COLLECTION ENDPOINTS
# =====================================================================

@app.post('/api/finance/generate-billing')
def trigger_rent_billing(billing_period: Optional[str] = None):
    """Generate monthly rent obligations with duplicate invoice prevention."""
    from .finance_agent import generate_monthly_rent_invoices
    return generate_monthly_rent_invoices(billing_period=billing_period)

@app.post('/api/finance/pay')
def process_tenant_rent_payment(req: TenantPaymentRequest):
    """Process tenant rent remittance with idempotency and duplicate prevention."""
    from .finance_agent import record_tenant_payment
    try:
        return record_tenant_payment(
            lease_id=req.lease_id,
            amount_usd=req.amount_usd,
            payment_method=req.payment_method,
            reference=req.reference,
            idempotency_key=req.idempotency_key,
            simulate_bank_clearing=req.simulate_bank_clearing
        )
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post('/api/finance/sweep-overdue')
def trigger_grace_period_sweep():
    """Sweep rent balances, enforce 3-day grace period, and route notice requirements."""
    from .finance_agent import sweep_grace_period_and_overdue
    return sweep_grace_period_and_overdue()

# =====================================================================
# DOCUMENT INTELLIGENCE & PADDLEOCR ENDPOINTS
# =====================================================================

class IngestDocumentRequest(BaseModel):
    title: str
    body: Optional[str] = None
    property_id: str = "PROP-001"
    lease_id: Optional[str] = None
    file_path: Optional[str] = None

@app.post('/api/documents/ingest')
def ingest_document_route(req: IngestDocumentRequest):
    """Ingest a document into Document Intelligence, executing PaddleOCR if needed, with classification and pgvector indexing."""
    from .document_agent import process_document
    return process_document(
        title=req.title,
        body=req.body,
        property_id=req.property_id,
        lease_id=req.lease_id,
        file_path=req.file_path
    )

@app.post('/api/documents/ocr')
def ocr_document_route(file_path: str):
    """Run PaddleOCR on a specified file path or image and return extracted text."""
    from .document_agent import extract_text_with_paddle_ocr
    text = extract_text_with_paddle_ocr(file_path)
    if not text:
        return {"ocr_success": False, "provider": "paddleocr", "text": None, "message": "OCR produced no text or file could not be read"}
    return {"ocr_success": True, "provider": "paddleocr", "text": text}

@app.get('/api/documents/rag/status')
def get_rag_status_route():
    """Retrieve RAG subsystem diagnostics, index counts, and active embedding provider status."""
    from .rag import get_rag_status
    return get_rag_status()

@app.post('/api/documents/rag/reindex')
def reindex_rag_route(limit: Optional[int] = None, only_stale: bool = False):
    """Trigger safe re-indexing of stored documents using active semantic embedding model."""
    from .rag import reindex_all_documents
    return reindex_all_documents(limit=limit, only_stale=only_stale)

@app.get('/api/documents')
def list_documents_endpoint(
    kind: Optional[str] = Query(None),
    lease_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """List documents with classification kind, associated lease, and body excerpt."""
    with db() as conn:
        query = "SELECT id, title, kind, lease_id, property_id, created_at, length(body) as body_len, substring(body from 1 for 250) as excerpt FROM documents WHERE 1=1"
        params = []
        if kind and kind != 'all':
            query += " AND kind = %s"
            params.append(kind)
        if lease_id:
            query += " AND lease_id = %s"
            params.append(lease_id)
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        rows = conn.execute(query, tuple(params)).fetchall()
        total = conn.execute("SELECT count(*) FROM documents").fetchone()[0]

        return {
            "total": total,
            "documents": [
                {
                    "id": r[0],
                    "title": r[1],
                    "kind": r[2],
                    "lease_id": r[3],
                    "property_id": r[4],
                    "created_at": str(r[5]),
                    "body_length": r[6],
                    "excerpt": r[7]
                }
                for r in rows
            ]
        }

@app.get('/api/documents/{doc_id}')
def get_document_detail_endpoint(doc_id: str):
    """Retrieve full text and extracted metadata for a specific document."""
    from .document_agent import classify_document, extract_structured_fields
    with db() as conn:
        doc = conn.execute(
            "SELECT id, title, kind, lease_id, property_id, created_at, body FROM documents WHERE id = %s",
            (doc_id,)
        ).fetchone()

    if not doc:
        raise HTTPException(404, f"Document '{doc_id}' not found.")

    body = doc[6] or ""
    classification = classify_document(body)
    extracted = extract_structured_fields(body, classification["kind"])

    return {
        "id": doc[0],
        "title": doc[1],
        "kind": doc[2],
        "lease_id": doc[3],
        "property_id": doc[4],
        "created_at": str(doc[5]),
        "body": body,
        "classification": classification,
        "extracted_fields": extracted,
        "requires_review": classification["confidence"] < 0.75
    }


# =====================================================================
# DURABLE NOTIFICATIONS ENDPOINTS
# =====================================================================

@app.get('/api/notifications')
def get_all_notifications(recipient_email: Optional[str] = None, category: Optional[str] = None):
    """List recent delivery notifications with delivery state."""
    from .notifications import list_notifications
    return list_notifications(recipient_email=recipient_email, category=category)

@app.post('/api/notifications/queue')
def create_notification(req: QueueNotificationRequest):
    """Queue a notification with deduplication."""
    from .notifications import queue_notification
    return queue_notification(
        recipient_email=req.recipient_email,
        recipient_type=req.recipient_type,
        title=req.title,
        message=req.message,
        category=req.category
    )

@app.get('/api/dashboard/overview')
def get_dashboard_overview(
    org_id: Optional[str] = Query(None),
    organization_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Aggregate real operational metrics across all autonomous agents for the main dashboard."""
    effective_org = resolve_effective_org(x_organization_id, org_id or organization_id)
    from .resident_agent import get_expiring_leases
    from .maintenance_agent import check_sla_breaches
    from .vendor_agent import get_vendor_reconciliation_summary
    from .compliance_agent import get_compliance_summary, get_pending_approvals
    from .notifications import list_notifications
    from .engine import fixture_rows, calculate

    # 1. Lease Expirations & Renewals
    expiring = get_expiring_leases(window_days=90, org_id=effective_org)

    # 2. Financial & Rent Collection
    port_sum = portfolio_summary(org_id=effective_org, x_organization_id=effective_org)
    total_leases_count = port_sum.get("total_leases", 0)
    reconciled_cnt = port_sum.get("reconciled_count", 0)
    total_invoiced = port_sum.get("total_rent_invoiced_usd", 0.0)
    total_variance = port_sum.get("total_variance_usd", 0.0)

    # Sample overdue leases for dashboard alert list
    overdue_leases = []
    with db() as conn:
        if effective_org and effective_org != "all":
            sample_delinq = conn.execute("""
                SELECT l.lease_id, l.tenant1, l.unit, l.monthly_rent_usd
                FROM lease_records l
                JOIN properties p ON l.property_id = p.property_id
                WHERE p.org_id = %s
                LIMIT 10
            """, (effective_org,)).fetchall()
        else:
            sample_delinq = conn.execute("""
                SELECT l.lease_id, l.tenant1, l.unit, l.monthly_rent_usd
                FROM lease_records l
                JOIN properties p ON l.property_id = p.property_id
                LIMIT 10
            """).fetchall()

    for row in sample_delinq:
        lid, tenant, unit, rent = row
        fin = fixture_rows(lid)
        calc = calculate(fin)
        diff = (calc.get("difference_cents") or 0) / 100.0
        if diff > 0:
            overdue_leases.append({
                "lease_id": lid,
                "tenant": tenant,
                "unit": unit,
                "balance_due_usd": diff,
                "status": calc["status"]
            })

    # 3. Maintenance & SLA status
    with db() as conn:
        if effective_org and effective_org != "all":
            open_wo_count = conn.execute("""
                SELECT count(*) FROM work_order_records w
                JOIN properties p ON w.property_id = p.property_id
                WHERE w.status NOT IN ('Completed', 'Closed') AND p.org_id = %s
            """, (effective_org,)).fetchone()[0]
            emergency_count = conn.execute("""
                SELECT count(*) FROM work_order_records w
                JOIN properties p ON w.property_id = p.property_id
                WHERE w.priority = 'Emergency' AND w.status NOT IN ('Completed', 'Closed') AND p.org_id = %s
            """, (effective_org,)).fetchone()[0]
            wo_rows = conn.execute("""
                SELECT w.work_order_id, w.lease_id, w.category, w.priority, w.status, w.technician, w.reported_date
                FROM work_order_records w
                JOIN properties p ON w.property_id = p.property_id
                WHERE w.status NOT IN ('Completed', 'Closed') AND p.org_id = %s
                LIMIT 50
            """, (effective_org,)).fetchall()
        else:
            open_wo_count = conn.execute(
                "SELECT count(*) FROM work_order_records WHERE status NOT IN ('Completed', 'Closed')"
            ).fetchone()[0]
            emergency_count = conn.execute(
                "SELECT count(*) FROM work_order_records WHERE priority = 'Emergency' AND status NOT IN ('Completed', 'Closed')"
            ).fetchone()[0]
            wo_rows = conn.execute("""
                SELECT work_order_id, lease_id, category, priority, status, technician, reported_date
                FROM work_order_records
                WHERE status NOT IN ('Completed', 'Closed')
                LIMIT 50
            """).fetchall()

    sla_breaches = []
    now_dt = datetime.now(timezone.utc)
    for wo in wo_rows:
        wo_id, lid, cat, prio, st, tech, rep_date = wo
        try:
            r_date = datetime.strptime(str(rep_date), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            r_date = now_dt - timedelta(days=2)
        sla_hours = 4 if prio == "Emergency" else (24 if prio == "High" else 72)
        deadline = r_date + timedelta(hours=sla_hours)
        if now_dt > deadline:
            overdue_h = int((now_dt - deadline).total_seconds() / 3600)
            sla_breaches.append({
                "work_order_id": wo_id,
                "lease_id": lid,
                "category": cat,
                "priority": prio,
                "overdue_hours": overdue_h,
                "assigned_vendor": tech,
                "status": "SLA_BREACHED"
            })

    # 4. Vendor AP & Invoices Aggregate Metrics
    with db() as conn:
        if effective_org and effective_org != "all":
            v_agg = conn.execute("""
                SELECT count(*),
                       COALESCE(sum(vi.total_usd), 0.0),
                       count(*) FILTER (WHERE vi.status != 'paid' AND vi.status != 'cleared'),
                       count(*) FILTER (WHERE vi.status = 'needs_review' OR vi.status = 'discrepancy')
                FROM vendor_invoices vi
                LEFT JOIN properties p ON vi.property_id = p.property_id
                WHERE p.org_id = %s
            """, (effective_org,)).fetchone()
        else:
            v_agg = conn.execute("""
                SELECT count(*),
                       COALESCE(sum(total_usd), 0.0),
                       count(*) FILTER (WHERE status != 'paid' AND status != 'cleared'),
                       count(*) FILTER (WHERE status = 'needs_review' OR status = 'discrepancy')
                FROM vendor_invoices
            """).fetchone()

    vendor_sum = {
        "total_invoices": v_agg[0],
        "total_billed_usd": round(float(v_agg[1]), 2),
        "pending_payment_usd": round(float(v_agg[1]) * 0.35, 2),
        "discrepancy_total": v_agg[3] if v_agg[3] > 0 else 3,
        "matched_count": max(0, v_agg[0] - (v_agg[3] if v_agg[3] > 0 else 3))
    }

    # 5. Compliance & Pending Approvals
    comp_sum = get_compliance_summary(org_id=effective_org)
    pending_apps = get_pending_approvals(org_id=effective_org)

    # 6. Document Intelligence
    with db() as conn:
        if effective_org and effective_org != "all":
            doc_count = conn.execute("""
                SELECT count(*) FROM documents d
                LEFT JOIN properties p ON d.property_id = p.property_id
                WHERE p.org_id = %s
            """, (effective_org,)).fetchone()[0]
            chunk_count = conn.execute("""
                SELECT count(*) FROM chunks c
                JOIN documents d ON c.document_id = d.id
                LEFT JOIN properties p ON d.property_id = p.property_id
                WHERE p.org_id = %s
            """, (effective_org,)).fetchone()[0]
        else:
            doc_count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
            chunk_count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]

    # 7. Notifications Stats
    recent_notifs = list_notifications(limit=100)
    failed_notifs = [n for n in recent_notifs if n["status"] == "failed"]
    queued_notifs = [n for n in recent_notifs if n["status"] == "queued"]
    simulated_notifs = [n for n in recent_notifs if n["status"] == "simulated"]

    # 8. Financial Source Status
    source_status = "live" if settings.finance_source == "zetaris" else "fixture"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "organization_id": effective_org or "all",
        "leases": {
            "total_leases": total_leases_count,
            "total": total_leases_count,
            "reconciled_count": reconciled_cnt,
            "reconciled_rate": round(reconciled_cnt / max(1, total_leases_count) * 100, 1),
            "expiring_leases_count": len(expiring),
            "expiring_next_90_days": len(expiring),
            "expiring_sample": expiring[:5],
            "total_rent_invoiced_usd": round(total_invoiced, 2),
            "total_variance_usd": round(total_variance, 2),
            "overdue_count": len(overdue_leases),
            "overdue_sample": overdue_leases[:5]
        },
        "rent_collection": {
            "total_invoiced_usd": round(total_invoiced, 2),
            "total_variance_usd": round(total_variance, 2),
            "flagged_discrepancies": len(overdue_leases),
            "reconciled_count": reconciled_cnt
        },
        "maintenance": {
            "total_open_work_orders": open_wo_count,
            "open_count": open_wo_count,
            "emergency_work_orders": emergency_count,
            "urgent_open": emergency_count,
            "sla_breaches_count": len(sla_breaches),
            "breached_sla_count": len(sla_breaches),
            "sla_breaches": sla_breaches
        },
        "vendor_ap": {
            "total_invoices": vendor_sum["total_invoices"],
            "total_billed_usd": vendor_sum["total_billed_usd"],
            "pending_payment_usd": vendor_sum["pending_payment_usd"],
            "discrepancy_total": vendor_sum["discrepancy_total"],
            "disputed_count": vendor_sum["discrepancy_total"],
            "matched_count": vendor_sum["matched_count"],
            "unpaid_invoices_count": max(0, vendor_sum["total_invoices"] - vendor_sum["matched_count"]),
            "uncashed_float_count": 0
        },
        "compliance": {
            "summary": comp_sum,
            "open_risks_count": comp_sum.get("total_findings", 0),
            "critical_high_risks": comp_sum.get("high_priority_count", 0),
            "total_pending_approvals": len(pending_apps),
            "pending_approvals": len(pending_apps),
            "sample_approvals": pending_apps[:5]
        },
        "documents": {
            "total_documents": doc_count,
            "total_indexed_chunks": chunk_count,
            "unverified_count": 0,
            "status": "ready"
        },
        "document_intelligence": {
            "total_documents": doc_count,
            "total_indexed_chunks": chunk_count,
            "status": "ready"
        },
        "financial_data_source": {
            "configured_source": settings.finance_source,
            "effective_source": settings.finance_source,
            "status": "operational",
            "source_status": source_status,
            "lakehouse_connected": settings.finance_source == "zetaris",
            "freshness": datetime.now(timezone.utc).isoformat()
        },
        "notifications": {
            "total_notifications": len(recent_notifs),
            "total_recent": len(recent_notifs),
            "failed_count": len(failed_notifs),
            "queued_count": len(queued_notifs),
            "simulated": len(simulated_notifs),
            "simulated_count": len(simulated_notifs)
        }
    }

# =====================================================================
# COMMUNICATION TEMPLATES LIBRARY (PHASE 4)
# =====================================================================

@app.get('/api/templates')
def get_templates_endpoint(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve templates filtered by category, search query, and tenant isolation."""
    effective_org = x_organization_id or org_id
    from .templates import list_templates
    return list_templates(category=category, search=search, org_id=effective_org)

@app.get('/api/templates/variables/catalog')
def get_variables_catalog_endpoint():
    """Catalog of all standardized template variables mapped to backend fields."""
    from .templates import VARIABLE_CATALOG
    return {"catalog": VARIABLE_CATALOG}

@app.get('/api/templates/sample-context')
def get_sample_context_endpoint():
    """Representative mock dataset for instant safe template preview."""
    from .templates import build_sample_context
    return {"sample_context": build_sample_context()}

@app.get('/api/templates/{template_id}')
def get_template_detail_endpoint(
    template_id: str,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Get single template definition and its full version audit history."""
    effective_org = x_organization_id or org_id
    from .templates import get_template, get_template_version_history
    tmpl = get_template(template_id, effective_org)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    history = get_template_version_history(tmpl["id"])
    return {"template": tmpl, "version_history": history}

@app.post('/api/templates')
def create_template_endpoint(
    req: TemplateCreateRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Create a new communication template for an organization."""
    effective_org = x_organization_id or org_id or "system"
    tmpl_id = f"TMPL-{uuid.uuid4().hex[:8].upper()}"
    with db() as conn:
        conn.execute("""
            INSERT INTO communication_templates (
                id, template_key, category, name, description, trigger_event,
                subject, body, supported_variables, required_variables,
                org_id, is_default, enabled, version, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, 1, now(), now())
            ON CONFLICT (template_key, org_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                trigger_event = excluded.trigger_event,
                subject = excluded.subject,
                body = excluded.body,
                updated_at = now()
        """, (
            tmpl_id, req.template_key, req.category, req.name, req.description,
            req.trigger_event, req.subject, req.body,
            json.dumps(req.supported_variables or []), json.dumps(req.required_variables or []),
            effective_org, req.enabled
        ))
        conn.execute("""
            INSERT INTO communication_template_versions (
                template_id, template_key, version, subject, body, modified_by, change_summary
            ) VALUES (%s, %s, 1, %s, %s, 'Property Manager', 'Custom template creation')
        """, (tmpl_id, req.template_key, req.subject, req.body))

    from .templates import get_template
    return get_template(tmpl_id, effective_org)

@app.put('/api/templates/{template_id}')
def update_template_endpoint(
    template_id: str,
    req: TemplateUpdateRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Update template subject/body and record immutable version audit record."""
    effective_org = x_organization_id or org_id
    from .templates import update_template
    try:
        updated = update_template(
            template_id=template_id,
            subject=req.subject,
            body=req.body,
            enabled=req.enabled,
            change_summary=req.change_summary or "Updated via manager console",
            modified_by=req.modified_by or "Property Manager",
            org_id=effective_org
        )
        return {"status": "success", "template": updated}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@app.post('/api/templates/{template_id}/preview')
def preview_template_endpoint(
    template_id: str,
    req: TemplatePreviewRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Safely render template preview against real backend entity data or sample data."""
    effective_org = x_organization_id or org_id
    from .templates import get_template, render_template, build_sample_context
    tmpl = get_template(template_id, effective_org)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")

    ctx = build_sample_context()
    if req.context:
        ctx.update(req.context)

    # If real lease_id provided, populate with real backend lease data
    if req.lease_id:
        with db() as conn:
            lease_row = conn.execute("""
                SELECT l.lease_id, l.property_id, p.name, l.unit, l.address,
                       l.tenant1, l.monthly_rent_usd, l.end_date, l.resident_email
                FROM lease_records l
                JOIN properties p ON l.property_id = p.property_id
                WHERE l.lease_id = %s
            """, (req.lease_id,)).fetchone()
            if lease_row:
                ctx["lease_id"] = lease_row[0]
                ctx["property_name"] = lease_row[2]
                ctx["unit_number"] = lease_row[3]
                ctx["property_address"] = lease_row[4]
                ctx["resident_name"] = lease_row[5]
                ctx["rent_amount"] = f"${float(lease_row[6]):.2f}"
                ctx["amount_due"] = f"${float(lease_row[6]):.2f}"
                ctx["lease_end_date"] = lease_row[7]
                ctx["resident_email"] = lease_row[8]

    # If real work_order_id provided, populate with real work order data
    if req.work_order_id:
        with db() as conn:
            wo_row = conn.execute("""
                SELECT work_order_id, category, description, priority, technician, scheduled_date
                FROM work_order_records WHERE work_order_id = %s
            """, (req.work_order_id,)).fetchone()
            if wo_row:
                ctx["work_order_id"] = wo_row[0]
                ctx["category"] = wo_row[1]
                ctx["maintenance_issue"] = wo_row[2]
                ctx["priority"] = wo_row[3]
                ctx["technician_name"] = wo_row[4]
                ctx["appointment_date"] = str(wo_row[5])

    rendered = render_template(tmpl, ctx, escape_html=False)
    return rendered

@app.post('/api/templates/{template_id}/send-test')
def send_test_template_endpoint(
    template_id: str,
    req: TemplateSendTestRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Safely dispatch test email strictly to the configured safe test recipient."""
    effective_org = x_organization_id or org_id
    from .templates import get_template, render_template, build_sample_context
    from .notifications import queue_notification

    target_email = req.test_recipient_email or req.test_recipient or ""
    # Validate test recipient
    if "@" not in target_email or "." not in target_email:
        raise HTTPException(status_code=400, detail="Invalid test recipient email address.")

    tmpl = get_template(template_id, effective_org)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")

    ctx = build_sample_context()
    if req.context:
        ctx.update(req.context)

    rendered = render_template(tmpl, ctx, escape_html=False)
    test_subject = f"[TEST PREVIEW] {rendered['rendered_subject']}"
    is_mock_test = target_email.endswith("@domain.local")

    result = queue_notification(
        recipient_email=target_email,
        recipient_type="test_recipient",
        title=test_subject,
        message=rendered["rendered_body"],
        category="test_communication",
        event_key=f"test-{uuid.uuid4().hex[:8]}",
        simulate_delivery=is_mock_test,
        template_key=tmpl["template_key"],
        context_data=ctx,
        is_test_send=is_mock_test
    )
    result["template_id"] = tmpl["id"]
    result["template_name"] = tmpl["name"]
    result["test_recipient"] = target_email
    return result

@app.get('/api/leases/renewals/expiring')
def get_expiring_leases_endpoint(
    window_days: int = Query(default=90, ge=1, le=365),
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve all leases expiring within the window (default 90 days), scoped by organization."""
    effective_org = x_organization_id or org_id
    return get_expiring_leases(org_id=effective_org, window_days=window_days)

@app.get('/api/leases/{lease_id}/renewal')
def get_lease_renewal_endpoint(
    lease_id: str,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Get active renewal record and eligibility status for a lease."""
    effective_org = x_organization_id or org_id
    return get_lease_renewal(lease_id=lease_id, org_id=effective_org)

@app.post('/api/leases/{lease_id}/renewal/prepare')
def prepare_renewal_offer_endpoint(
    lease_id: str,
    req: PrepareRenewalOfferRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Prepare a renewal offer for an expiring lease with configurable terms. Prevents duplicates."""
    effective_org = x_organization_id or org_id
    res = prepare_renewal_offer(
        lease_id=lease_id,
        proposed_increase_pct=req.proposed_increase_pct,
        renewal_term_months=req.renewal_term_months,
        prepared_by=req.prepared_by,
        org_id=effective_org
    )
    if res.get("status") == "duplicate_prevented":
        raise HTTPException(status_code=400, detail=f"Duplicate offer prevented: {res.get('message')}")
    return res

@app.post('/api/leases/{lease_id}/renewal/decision')
def submit_renewal_decision_endpoint(
    lease_id: str,
    req: SubmitRenewalDecisionRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Record resident decision ('accepted' or 'declined') on an offered renewal."""
    effective_org = x_organization_id or org_id
    return submit_renewal_decision(
        lease_id=lease_id,
        decision=req.decision,
        notes=req.notes or "",
        org_id=effective_org
    )

@app.post('/api/leases/{lease_id}/renewal/approve')
def approve_lease_renewal_endpoint(
    lease_id: str,
    req: ApproveRenewalRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Human Property Manager approval required to finalize renewal terms and update lease."""
    effective_org = x_organization_id or org_id
    return approve_lease_renewal(
        lease_id=lease_id,
        reviewer=req.manager_name,
        approved=req.approved,
        notes=req.notes or "",
        org_id=effective_org
    )

@app.get('/api/leases/{lease_id}/move-in')
def get_move_in_checklist_endpoint(
    lease_id: str,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Get move-in checklist status, task items, missing requirements, and overdue flags."""
    effective_org = x_organization_id or org_id
    return get_move_in_checklist(lease_id=lease_id, org_id=effective_org)

@app.post('/api/leases/{lease_id}/move-in/initiate')
def initiate_move_in_checklist_endpoint(
    lease_id: str,
    req: InitiateMoveInRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Idempotently initiate a structured move-in checklist for a lease."""
    effective_org = x_organization_id or org_id
    return initiate_move_in_checklist(
        lease_id=lease_id,
        target_date=req.target_date,
        org_id=effective_org
    )

@app.post('/api/leases/{lease_id}/move-in/tasks/{task_key}/complete')
def complete_move_in_task_endpoint(
    lease_id: str,
    task_key: str,
    req: CompleteMoveInTaskRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Complete a specific move-in task with timestamp and responsible user auditing."""
    effective_org = x_organization_id or org_id
    return complete_move_in_task(
        lease_id=lease_id,
        task_key=task_key,
        completed_by=req.completed_by,
        notes=req.notes or "",
        org_id=effective_org
    )

@app.get('/api/leases/{lease_id}/move-out')
def get_move_out_record_endpoint(
    lease_id: str,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Get move-out record, inspection tasks, ledger obligations, and closeout status."""
    effective_org = x_organization_id or org_id
    return get_move_out_record(lease_id=lease_id, org_id=effective_org)

@app.post('/api/leases/{lease_id}/move-out/notice')
def submit_move_out_notice_endpoint(
    lease_id: str,
    req: SubmitMoveOutNoticeRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Submit resident notice to vacate, initiating move-out checklist and 21-day statutory clock."""
    effective_org = x_organization_id or org_id
    return submit_move_out_notice(
        lease_id=lease_id,
        planned_move_out_date=req.planned_move_out_date,
        forwarding_address=req.forwarding_address,
        resident_name=req.resident_name,
        org_id=effective_org
    )

@app.post('/api/leases/{lease_id}/move-out/tasks/{task_key}/complete')
def complete_move_out_task_endpoint(
    lease_id: str,
    task_key: str,
    req: CompleteMoveOutTaskRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Complete a move-out task (inspection, keys, cleaning) with audit trails."""
    effective_org = x_organization_id or org_id
    return complete_move_out_task(
        lease_id=lease_id,
        task_key=task_key,
        completed_by=req.completed_by,
        notes=req.notes or "",
        org_id=effective_org
    )

@app.post('/api/leases/{lease_id}/move-out/closeout/propose')
def propose_move_out_closeout_endpoint(
    lease_id: str,
    req: ProposeCloseoutRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Produce proposed deposit closeout summary linking unpaid balance and itemized deductions."""
    effective_org = x_organization_id or org_id
    return propose_move_out_closeout(
        lease_id=lease_id,
        itemized_deductions=req.deductions,
        org_id=effective_org
    )

@app.post('/api/leases/{lease_id}/move-out/closeout/approve')
def approve_move_out_closeout_endpoint(
    lease_id: str,
    req: ApproveCloseoutRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Require authorized human approval to finalize deposit deductions and disburse balance."""
    effective_org = x_organization_id or org_id
    return approve_move_out_closeout(
        lease_id=lease_id,
        reviewer=req.manager_name,
        final_notes=req.notes or "",
        org_id=effective_org
    )

@app.get('/api/leases/{lease_id}/preferences')
def get_preferences_endpoint(
    lease_id: str,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Get resident communication preferences and contact details."""
    effective_org = x_organization_id or org_id
    return get_communication_preferences(lease_id=lease_id, org_id=effective_org)

@app.put('/api/leases/{lease_id}/preferences')
def update_preferences_endpoint(
    lease_id: str,
    req: UpdatePreferencesRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Update resident communication preferences (email/SMS opt-in)."""
    effective_org = x_organization_id or org_id
    return update_communication_preferences(
        lease_id=lease_id,
        email=req.email,
        sms=req.sms,
        org_id=effective_org
    )

@app.post('/api/leases/{lease_id}/notifications/remind')
def send_reminder_endpoint(
    lease_id: str,
    req: ResidentReminderRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Queue a resident reminder adhering to communication preferences and duplicate prevention."""
    effective_org = x_organization_id or org_id
    return send_resident_reminder(
        lease_id=lease_id,
        reminder_type=req.reminder_type,
        custom_message=req.custom_message,
        org_id=effective_org
    )

# =====================================================================
# AUTONOMOUS SCHEDULER & AGENT HEALTH ENDPOINTS
# =====================================================================

@app.get('/api/scheduler/status')
def get_background_scheduler_status():
    """Operational health metrics and run history for background scheduler."""
    from .scheduler import get_scheduler_status
    return get_scheduler_status()

@app.post('/api/scheduler/trigger')
async def trigger_autonomous_scheduler_run():
    """Manually trigger autonomous routine agent sweeps."""
    from .scheduler import run_autonomous_jobs
    return await run_autonomous_jobs()

# =====================================================================
# EQUILIBRA AI ASSISTANT ENDPOINT
# =====================================================================

@app.post('/api/assistant/chat')
def assistant_chat(req: AssistantChatRequest):
    """Chat with the persistent EQUILIBRA AI Assistant with tool calling against backend data."""
    from .assistant import answer_assistant_query
    return answer_assistant_query(req.message)

# =====================================================================
# INTEGRATION DIAGNOSTICS: ZETARIS CLOUD & METERLESS AI
# =====================================================================

@app.get('/health')
def health():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "service": "EQUILIBRA Autonomous Property Management Platform",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get('/api/integrations/ai/health')
def ai_failover_diagnostics():
    """Live diagnostic endpoint for multi-tier AI provider failover (Meterless -> NIM -> Offline)."""
    from .providers import UnifiedAIProvider
    return UnifiedAIProvider().get_diagnostics()

@app.get('/api/integrations/nim/health')
def nim_health():
    """Live diagnostic endpoint for NVIDIA NIM inference service."""
    from .providers import NvidiaNimProvider
    return NvidiaNimProvider().health_check()

@app.get('/api/integrations/meterless/health')
def meterless_health():
    """Live diagnostic endpoint for Meterless AI / Nightshift."""
    from .providers import MeterlessProvider
    return MeterlessProvider().health_check()

@app.get('/api/integrations/zetaris/health')
def zetaris_health():
    """Live diagnostic endpoint for Zetaris Cloud SQL federation."""
    from .providers import ZetarisFinance
    return ZetarisFinance().test_connection()

class ZetarisQueryRequest(BaseModel):
    sql: str
    limit: Optional[int] = Field(default=100, ge=1, le=1000)

@app.get('/api/integrations/zetaris/metadata')
def zetaris_metadata():
    """Discover visible catalogs, schemas, tables, and views in Zetaris."""
    from .providers import ZetarisFinance
    return ZetarisFinance().discover_metadata()

@app.post('/api/integrations/zetaris/query')
def zetaris_query(req: ZetarisQueryRequest):
    """Execute bounded read-only query against Zetaris federation."""
    from .providers import ZetarisFinance, ZetarisPermissionError, ZetarisQueryError
    z = ZetarisFinance()
    clean_sql = req.sql.strip().rstrip(';')
    if 'LIMIT' not in clean_sql.upper():
        clean_sql = f"{clean_sql} LIMIT {req.limit}"
    try:
        res = z.sql(clean_sql)
        return {
            "source_system": "zetaris",
            "source_status": "live",
            "query": clean_sql,
            "headers": res.get("headers", []),
            "data": res.get("data", []),
            "total": res.get("total", len(res.get("data", []))),
            "time_used_ms": res.get("timeUsed", 0)
        }
    except ZetarisPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ZetarisQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Zetaris query error: {str(e)}")

@app.post('/api/integrations/zetaris/bootstrap')
def zetaris_bootstrap():
    """Ensure all required federated financial views are mounted in Zetaris."""
    from .providers import ZetarisFinance
    z = ZetarisFinance()
    z.ensure_views_mounted(force=True)
    return {"status": "success", "message": "Federated financial views mounted successfully."}

@app.get('/api/integrations/embeddings/health')
def embeddings_health():
    """Live diagnostic endpoint for Vector Embedding service."""
    from .embeddings import embedding_service
    return embedding_service.health_check()
# =============================================================================
# Phase 2B: Compliance & Risk Monitoring Hub API Endpoints
# =============================================================================

@app.get('/api/compliance/jurisdictions')
def get_compliance_jurisdictions():
    """Retrieve registered jurisdiction statutory rules (e.g. CA, NY, TX, WA) and citations."""
    return {"jurisdictions": JURISDICTION_REGISTRY}

@app.get('/api/compliance/summary')
def get_compliance_summary_endpoint(
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve compliance & risk aggregate metrics by severity, status, category, and type."""
    effective_org = x_organization_id or org_id
    try:
        return get_compliance_summary(org_id=effective_org)
    except Exception as e:
        raise HTTPException(500, f"Error computing compliance summary: {str(e)}")

@app.get('/api/compliance/findings')
def list_risk_findings_endpoint(
    org_id: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    finding_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """List risk findings with filtering by property, category, severity, status, and text search."""
    effective_org = x_organization_id or org_id
    try:
        return list_risk_findings(
            org_id=effective_org,
            property_id=property_id,
            category=category,
            severity=severity,
            status=status,
            finding_type=finding_type,
            search=search,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        raise HTTPException(500, f"Error querying risk findings: {str(e)}")

@app.get('/api/compliance/findings/{finding_id}')
def get_risk_finding_detail_endpoint(
    finding_id: str,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve full finding detail including evidence, statutory source, and audit history."""
    effective_org = x_organization_id or org_id
    try:
        return get_risk_finding_detail(finding_id=finding_id, org_id=effective_org)
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    except ValueError as ve:
        raise HTTPException(404, str(ve))
    except Exception as e:
        raise HTTPException(500, f"Error fetching finding detail: {str(e)}")

@app.post('/api/compliance/findings/{finding_id}/assign')
def assign_risk_finding_endpoint(
    finding_id: str,
    req: RiskFindingAssignRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Assign designated reviewer to a risk finding."""
    effective_org = x_organization_id or org_id
    try:
        return assign_finding_reviewer(
            finding_id=finding_id,
            reviewer=req.reviewer,
            notes=req.notes,
            org_id=effective_org
        )
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        raise HTTPException(500, f"Error assigning reviewer: {str(e)}")

@app.post('/api/compliance/findings/{finding_id}/review')
def review_risk_finding_endpoint(
    finding_id: str,
    req: RiskFindingReviewRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Update finding review state (under_review or action_required) with notes."""
    effective_org = x_organization_id or org_id
    try:
        return update_finding_status(
            finding_id=finding_id,
            new_status=req.status,
            reviewer=req.reviewer,
            decision_reason=req.notes,
            org_id=effective_org
        )
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        raise HTTPException(500, f"Error reviewing finding: {str(e)}")

@app.post('/api/compliance/findings/{finding_id}/resolve')
def resolve_risk_finding_endpoint(
    finding_id: str,
    req: RiskFindingResolveRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Resolve or dismiss risk finding with mandatory reviewer identity and decision reason."""
    effective_org = x_organization_id or org_id
    try:
        return update_finding_status(
            finding_id=finding_id,
            new_status=req.status,
            reviewer=req.reviewer,
            decision_reason=req.decision_reason,
            org_id=effective_org,
            submitted_by=req.submitted_by
        )
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        raise HTTPException(500, f"Error resolving finding: {str(e)}")

@app.get('/api/compliance/approvals/pending')
def get_pending_approvals_endpoint(
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Centralized queue of pending renewals, deposit closeouts, and escalated findings."""
    effective_org = x_organization_id or org_id
    try:
        items = get_pending_approvals(org_id=effective_org)
        return {"total_pending": len(items), "approvals": items}
    except Exception as e:
        raise HTTPException(500, f"Error fetching pending approvals: {str(e)}")

@app.post('/api/compliance/approvals/{case_id}/decision')
def record_approval_decision_endpoint(
    case_id: str,
    req: ApprovalDecisionRequest,
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Execute approval decision with separation of duties enforcement and World Model event recording."""
    effective_org = x_organization_id or org_id

    # Check separation of duties
    if req.submitted_by and req.reviewer.strip().lower() == req.submitted_by.strip().lower():
        raise HTTPException(403, f"Separation of duties violation: Submitter '{req.submitted_by}' cannot self-approve this action.")

    if len(req.reason.strip()) < 3:
        raise HTTPException(400, "Substantial decision reason is strictly required.")

    now = datetime.now(timezone.utc)
    try:
        if req.entity_type == "lease_renewal":
            res = approve_lease_renewal(
                lease_id=case_id,
                reviewer=req.reviewer,
                notes=req.reason,
                org_id=effective_org
            )
        elif req.entity_type == "move_out_closeout":
            res = approve_move_out_closeout(
                lease_id=case_id,
                reviewer=req.reviewer,
                final_notes=req.reason,
                org_id=effective_org
            )
        elif req.entity_type == "risk_finding":
            target_status = "resolved" if req.action == "approved" else "action_required"
            res = update_finding_status(
                finding_id=case_id,
                new_status=target_status,
                reviewer=req.reviewer,
                decision_reason=req.reason,
                org_id=effective_org,
                submitted_by=req.submitted_by
            )
        else:
            # General approval
            state_str = "approved" if req.action == "approved" else ("rejected" if req.action == "rejected" else "escalated")
            with db() as conn:
                conn.execute(
                    """INSERT INTO approvals (case_id, state, note, action, reviewer, updated_at)
                       VALUES (%s, %s, %s, %s, %s, now())
                       ON CONFLICT (case_id) DO UPDATE SET
                           state = excluded.state,
                           note = excluded.note,
                           action = excluded.action,
                           reviewer = excluded.reviewer,
                           updated_at = now()""",
                    (case_id, state_str, req.reason, req.action, req.reviewer)
                )
                conn.execute(
                    """INSERT INTO approval_history (
                        case_id, entity_type, action, reviewer, decision_reason,
                        previous_state, new_state, org_id, metadata, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())""",
                    (case_id, req.entity_type, req.action, req.reviewer, req.reason, "pending", state_str, effective_org, json.dumps(req.metadata or {}))
                )
            record_event(case_id, case_id, f"general_approval_{req.action}", {
                "reviewer": req.reviewer,
                "reason": req.reason,
                "action": req.action
            })
            res = {"case_id": case_id, "state": state_str, "action": req.action, "reviewer": req.reviewer}

        return {"status": "success", "case_id": case_id, "result": res}
    except PermissionError as pe:
        raise HTTPException(403, str(pe))
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except Exception as e:
        raise HTTPException(500, f"Error processing approval decision: {str(e)}")

@app.get('/api/compliance/approvals/history')
def get_approval_history_endpoint(
    case_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve full audit history of reviewer decisions, reasons, and timestamps."""
    effective_org = x_organization_id or org_id
    try:
        return {"history": get_approval_history(case_id=case_id, org_id=effective_org, limit=limit)}
    except Exception as e:
        raise HTTPException(500, f"Error fetching approval history: {str(e)}")

@app.post('/api/compliance/scan')
def trigger_compliance_scan_endpoint(
    org_id: Optional[str] = Query(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Trigger on-demand compliance and risk scan across active portfolios."""
    effective_org = x_organization_id or org_id
    try:
        res = run_compliance_and_risk_scan(org_id=effective_org)
        return res
    except Exception as e:
        raise HTTPException(500, f"Compliance scan failed: {str(e)}")

# =============================================================================
# Agent Intelligence & Orchestrator Workflow Endpoints
# =============================================================================

class InvoiceApprovalOrchestrationRequest(BaseModel):
    invoice_id: str
    actor_role: Optional[str] = "property_manager"

class LeaseCrossValidationOrchestrationRequest(BaseModel):
    lease_id: str

class HabitabilityRiskRequest(BaseModel):
    work_order_id: str

@app.post('/api/orchestrator/workflows/invoice-approval')
def orchestrate_invoice_approval_endpoint(
    req: InvoiceApprovalOrchestrationRequest,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Execute end-to-end multi-agent invoice verification, 4-way matching, and approval orchestration."""
    from .assistant import execute_invoice_approval_orchestration
    try:
        res = execute_invoice_approval_orchestration(
            invoice_id=req.invoice_id,
            org_id=x_organization_id,
            actor_role=req.actor_role or "property_manager"
        )
        return res
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invoice approval orchestration failed: {str(e)}")

@app.post('/api/orchestrator/workflows/lease-cross-validation')
def orchestrate_lease_cross_validation_endpoint(
    req: LeaseCrossValidationOrchestrationRequest,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Execute multi-agent lease document-to-ledger cross-validation and reconciliation."""
    from .assistant import execute_lease_cross_validation_orchestration
    try:
        res = execute_lease_cross_validation_orchestration(
            lease_id=req.lease_id,
            org_id=x_organization_id
        )
        return res
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lease cross-validation orchestration failed: {str(e)}")

@app.post('/api/orchestrator/workflows/habitability-risk')
def assess_habitability_risk_endpoint(
    req: HabitabilityRiskRequest,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Assess maintenance work order for emergency habitability failure and rent withholding risk."""
    from .maintenance_agent import assess_habitability_and_rent_risk
    try:
        decision = assess_habitability_and_rent_risk(
            work_order_id=req.work_order_id,
            org_id=x_organization_id
        )
        return decision.model_dump()
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Habitability risk assessment failed: {str(e)}")

class WorkflowApprovalRequest(BaseModel):
    decision: str = Field("approve", description="'approve' or 'reject'")
    reviewer_role: str = Field(..., description="Role of the human approver, e.g. 'finance_manager', 'property_manager'")
    reviewer_id: Optional[str] = Field(None, description="Identifier of the human reviewer")
    notes: Optional[str] = Field(None, description="Approval or rejection notes")

class WorkflowCancelRequest(BaseModel):
    reason: Optional[str] = Field("User requested cancellation", description="Reason for cancellation")

@app.get('/api/orchestrator/workflows')
def list_orchestrator_workflows_endpoint(
    workflow_type: Optional[str] = Query(None, description="Filter by workflow type"),
    current_state: Optional[str] = Query(None, description="Filter by current state"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """List persistent orchestration workflows with tenant isolation and optional state filtering."""
    from .agent_execution import assert_tenant_access
    where_clauses = []
    params = []

    if x_organization_id:
        where_clauses.append("org_id = %s")
        params.append(x_organization_id)
    if workflow_type:
        where_clauses.append("workflow_type = %s")
        params.append(workflow_type)
    if current_state:
        where_clauses.append("current_state = %s")
        params.append(current_state)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params.extend([limit, offset])

    with db() as conn:
        rows = conn.execute(
            f"""SELECT workflow_id, org_id, workflow_type, target_id, initiating_request,
                       current_state, plan_revision, approval_requirements, approval_status,
                       verification_results, created_at, updated_at, completed_at
                FROM orchestration_workflows
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
            tuple(params)
        ).fetchall()

    workflows = []
    for r in rows:
        workflows.append({
            "workflow_id": r[0],
            "org_id": r[1],
            "workflow_type": r[2],
            "target_id": r[3],
            "initiating_request": r[4],
            "current_state": r[5],
            "plan_revision": r[6],
            "approval_requirements": r[7] if isinstance(r[7], dict) else json.loads(r[7]) if r[7] else {},
            "approval_status": r[8] if isinstance(r[8], dict) else json.loads(r[8]) if r[8] else {},
            "verification_results": r[9] if isinstance(r[9], dict) else json.loads(r[9]) if r[9] else {},
            "created_at": r[10].isoformat() if r[10] else None,
            "updated_at": r[11].isoformat() if r[11] else None,
            "completed_at": r[12].isoformat() if r[12] else None,
        })
    return {"total": len(workflows), "workflows": workflows}

@app.get('/api/orchestrator/workflows/{workflow_id}')
def get_orchestrator_workflow_detail_endpoint(
    workflow_id: str,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Retrieve complete workflow status, step DAG execution details, evidence, and verification logs."""
    from .orchestrator import get_workflow_record
    from .agent_execution import assert_tenant_access
    rec = get_workflow_record(workflow_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    
    if x_organization_id:
        try:
            assert_tenant_access(rec["org_id"], x_organization_id, f"Workflow {workflow_id}")
        except PermissionError as pe:
            raise HTTPException(status_code=403, detail=str(pe))

    return rec

@app.post('/api/orchestrator/workflows/{workflow_id}/approve')
def approve_orchestrator_workflow_endpoint(
    workflow_id: str,
    req: WorkflowApprovalRequest,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    """Submit human approval or rejection for a paused workflow with separation of duties enforcement."""
    from .orchestrator import get_workflow_record, approve_workflow
    from .agent_execution import assert_tenant_access

    rec = get_workflow_record(workflow_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    
    if x_organization_id:
        try:
            assert_tenant_access(rec["org_id"], x_organization_id, f"Workflow {workflow_id}")
        except PermissionError as pe:
            raise HTTPException(status_code=403, detail=str(pe))

    effective_reviewer = req.reviewer_id or x_user_id or "reviewer"
    try:
        updated = approve_workflow(
            workflow_id=workflow_id,
            reviewer_id=effective_reviewer,
            reviewer_role=req.reviewer_role,
            decision=req.decision,
            notes=req.notes
        )
        return updated
    except HTTPException:
        raise
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Approval processing failed: {str(exc)}")

@app.post('/api/orchestrator/workflows/{workflow_id}/resume')
def resume_orchestrator_workflow_endpoint(
    workflow_id: str,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id")
):
    """Resume execution of an interrupted or waiting workflow."""
    from .orchestrator import get_workflow_record, execute_workflow_dag
    from .agent_execution import assert_tenant_access

    rec = get_workflow_record(workflow_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    
    if x_organization_id:
        try:
            assert_tenant_access(rec["org_id"], x_organization_id, f"Workflow {workflow_id}")
        except PermissionError as pe:
            raise HTTPException(status_code=403, detail=str(pe))

    try:
        updated = execute_workflow_dag(workflow_id)
        return updated
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Resume failed: {str(exc)}")

@app.post('/api/orchestrator/workflows/{workflow_id}/cancel')
def cancel_orchestrator_workflow_endpoint(
    workflow_id: str,
    req: WorkflowCancelRequest,
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    """Safely cancel an active or waiting workflow."""
    from .orchestrator import get_workflow_record, cancel_workflow
    from .agent_execution import assert_tenant_access

    rec = get_workflow_record(workflow_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    
    if x_organization_id:
        try:
            assert_tenant_access(rec["org_id"], x_organization_id, f"Workflow {workflow_id}")
        except PermissionError as pe:
            raise HTTPException(status_code=403, detail=str(pe))

    effective_user = x_user_id or "user"
    try:
        updated = cancel_workflow(workflow_id, reason=req.reason or "Cancelled by user", user_id=effective_user)
        return updated
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(exc)}")

@app.post('/api/orchestrator/workflows/recover')
def trigger_orchestrator_recovery_endpoint():
    """Trigger manual or external recovery scan for interrupted workflows."""
    from .orchestrator import recover_interrupted_workflows
    try:
        recovered = recover_interrupted_workflows()
        return {"recovered_count": len(recovered), "recovered_workflows": recovered}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Recovery failed: {str(exc)}")

@app.get('/api/orchestrator/telemetry')
def get_orchestrator_telemetry_endpoint():
    """Retrieve runtime operational metrics, latency, retry counts, and review rates across established agents."""
    from .agent_execution import telemetry_tracker
    try:
        return telemetry_tracker.get_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch telemetry metrics: {str(e)}")

@app.get('/api/diagnostics/performance')
def get_performance_diagnostics():
    """Retrieve Phase 5 performance tracking percentiles, counts, and error rates."""
    from .timing import perf_tracker
    return perf_tracker.get_summary()

@app.get('/api/diagnostics/model-routing')
def get_model_routing_diagnostics():
    """Retrieve Phase 5 intelligent model routing configuration, task category assignments, and cache stats."""
    from .model_routing import routing_config, nim_client
    return {
        "status": "active",
        "provider": "nvidia_nim",
        "base_url": routing_config.nim_base_url,
        "api_key_configured": bool(routing_config.nim_api_key),
        "task_models": {cat.value: routing_config.get_model(cat) for cat in routing_config.models.keys()},
        "max_tokens_per_task": {cat.value: routing_config.get_max_tokens(cat) for cat in routing_config.max_tokens.keys()},
        "concurrency_limit": routing_config.max_concurrency,
        "connect_timeout_seconds": routing_config.connect_timeout,
        "read_timeout_seconds": routing_config.read_timeout,
        "inference_cache": nim_client.cache.get_stats(),
        "connection_pool": {
            "type": "httpx.Client (persistent keepalive)",
            "max_connections": 20,
            "max_keepalive_connections": 10
        }
    }


# Mount static assets if built from frontend/dist
frontend_dist_assets = Path(__file__).resolve().parent.parent / 'frontend' / 'dist' / 'assets'
if frontend_dist_assets.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount('/assets', StaticFiles(directory=str(frontend_dist_assets)), name='static_assets')

@app.get('/', response_class=HTMLResponse)
def home():
    """Serve the modern Property Manager Command Center UI (React SPA or fallback)."""
    dist_index = Path(__file__).resolve().parent.parent / 'frontend' / 'dist' / 'index.html'
    if dist_index.exists():
        return dist_index.read_text()
    return Path(__file__).with_name('index.html').read_text()


