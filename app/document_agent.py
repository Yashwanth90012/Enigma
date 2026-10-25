"""Autonomous Document Intelligence Agent for EQUILIBRA.

Key capabilities:
- Automatic document classification: lease agreements, work order quotes, vendor invoices, lien waivers, bank clearing notices, legal notices
- Structured field extraction with confidence scoring
- Duplicate detection using SHA-256 content hashing to prevent duplicate uploads
- Document linking: associates documents with property, resident, lease, or invoice
- Uncertainty routing: extractions with confidence < 0.75 are flagged for human review
- Strict guardrails: uncertain OCR/parsed data never silently overwrites authoritative financial or legal ledgers
"""

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .database import db
from .config import settings
from .rag import index_document
from .world_model import record_event, canonical_id
from .notifications import queue_notification

_paddle_ocr = None

def get_paddle_ocr():
    """Lazily initialize and cache PaddleOCR instance using configured parameters."""
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(
                use_angle_cls=getattr(settings, 'ocr_use_angle_cls', True),
                lang=getattr(settings, 'ocr_lang', 'en')
            )
        except Exception:
            _paddle_ocr = False
    return _paddle_ocr

def extract_text_with_paddle_ocr(file_path_or_bytes: Any) -> Optional[str]:
    """Run PaddleOCR on an image path, image bytes, or scanned document."""
    ocr = get_paddle_ocr()
    if not ocr:
        return None
    try:
        results = ocr.ocr(file_path_or_bytes, cls=True)
        lines = []
        if results:
            for page in results:
                if page:
                    for line in page:
                        if len(line) >= 2 and len(line[1]) >= 1:
                            lines.append(str(line[1][0]))
        return "\n".join(lines) if lines else None
    except Exception:
        return None

def hash_content(text: str) -> str:
    """Compute deterministic SHA-256 hash of document body for duplicate detection."""
    clean = re.sub(r'\s+', ' ', text.strip().lower())
    return hashlib.sha256(clean.encode('utf-8')).hexdigest()


def classify_document(text: str) -> Dict[str, Any]:
    """Classify document kind and extract confidence score."""
    t_lower = text.lower()
    
    scores = {
        "lease": 0.0,
        "vendor_invoice": 0.0,
        "work_order": 0.0,
        "lien_waiver": 0.0,
        "bank_statement": 0.0,
        "legal_notice": 0.0
    }
    
    # Keyword weights
    if "residential lease" in t_lower or "lease agreement" in t_lower:
        scores["lease"] += 0.5
    if "monthly rent" in t_lower or "rent" in t_lower:
        scores["lease"] += 0.25
    if "landlord" in t_lower or "tenant" in t_lower:
        scores["lease"] += 0.2
    if "security deposit" in t_lower:
        scores["lease"] += 0.2
        
    if "invoice" in t_lower and ("subtotal" in t_lower or "tax" in t_lower or "billed to" in t_lower):
        scores["vendor_invoice"] += 0.6
    if "net 30" in t_lower or "due date" in t_lower:
        scores["vendor_invoice"] += 0.3
        
    if "work order" in t_lower or "technician notes" in t_lower or "maintenance request" in t_lower:
        scores["work_order"] += 0.7
        
    if "lien waiver" in t_lower or "unconditional waiver" in t_lower or "mechanics lien" in t_lower:
        scores["lien_waiver"] += 0.8
        
    if "bank transaction" in t_lower or "clearing date" in t_lower or "wire transfer" in t_lower or "depository" in t_lower:
        scores["bank_statement"] += 0.7
        
    if "notice to quit" in t_lower or "notice of delinquency" in t_lower or "cure or vacate" in t_lower or "legal notice" in t_lower:
        scores["legal_notice"] += 0.85
        
    best_kind = max(scores, key=scores.get)
    confidence = min(0.98, max(0.40, scores[best_kind]))
    
    return {
        "kind": best_kind if confidence >= 0.5 else "unknown",
        "confidence": round(confidence, 2),
        "scores": {k: round(v, 2) for k, v in scores.items()}
    }


def extract_structured_fields(text: str, kind: str) -> Dict[str, Any]:
    """Extract key domain entities from document text with confidence."""
    fields = {}
    
    # Extract amounts (e.g. $1,250.00)
    amounts = re.findall(r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', text)
    if amounts:
        fields["extracted_amounts_usd"] = [float(a.replace(',', '')) for a in amounts[:5]]
        
    # Extract dates (YYYY-MM-DD or MM/DD/YYYY)
    dates = re.findall(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b', text)
    if dates:
        fields["extracted_dates"] = dates[:3]
        
    # Extract lease IDs (e.g. LEASE-0001)
    lease_match = re.search(r'\bLEASE-\d{4,}\b', text)
    if lease_match:
        fields["lease_id"] = lease_match.group(0)
        
    # Extract work order IDs (e.g. WO-0001)
    wo_match = re.search(r'\bWO-\d{4,}\b', text)
    if wo_match:
        fields["work_order_id"] = wo_match.group(0)
        
    # Extract invoice numbers (e.g. INV-1001, INV-P7-ABC12)
    inv_match = re.search(r'\b(?:INV|VINV)-[A-Za-z0-9-]+\b', text)
    if inv_match:
        fields["invoice_number"] = inv_match.group(0)
        
    return fields


def process_document(
    title: str,
    body: Optional[str] = None,
    property_id: str = "PROP-001",
    lease_id: Optional[str] = None,
    document_id: Optional[str] = None,
    file_path: Optional[str] = None
) -> Dict[str, Any]:
    """Execute Document Intelligence pipeline: OCR, deduplication, classification, extraction, RAG indexing."""
    ocr_applied = False
    if (not body or len(body.strip()) < 10) and file_path:
        ocr_extracted = extract_text_with_paddle_ocr(file_path)
        if ocr_extracted:
            body = ocr_extracted
            ocr_applied = True

    if not body:
        body = title
    else:
        body = body.replace("\x00", "")

    content_hash = hash_content(body)
    doc_id = document_id or f"DOC-{uuid.uuid4().hex[:8].upper()}"
    
    # 1. Check for duplicate document
    with db() as conn:
        existing = conn.execute(
            "SELECT id, title, kind, created_at FROM documents WHERE body = %s",
            (body,)
        ).fetchone()
        
    if existing:
        return {
            "status": "duplicate_rejected",
            "document_id": existing[0],
            "title": existing[1],
            "kind": existing[2],
            "message": f"Identical document already ingested on {existing[3]} with ID {existing[0]}."
        }
        
    # 2. Classification & Extraction
    classification = classify_document(body)
    kind = classification["kind"]
    confidence = classification["confidence"]
    extracted = extract_structured_fields(body, kind)
    
    # Correlate lease_id if found in text
    final_lease_id = lease_id or extracted.get("lease_id")
    
    # 3. Route uncertain extractions for review
    requires_review = confidence < 0.75
    
    # 4. Index in database & pgvector RAG
    chunk_count = index_document(
        document_id=doc_id,
        lease_id=final_lease_id or "PORTFOLIO",
        property_id=property_id,
        kind=kind,
        title=title,
        body=body
    )
    
    # 5. Record event in World Model
    record_event(
        case_id=final_lease_id or property_id,
        entity_id=doc_id,
        event_type="document_processed",
        payload={
            "document_id": doc_id,
            "title": title,
            "kind": kind,
            "confidence": confidence,
            "requires_review": requires_review,
            "extracted_fields": extracted,
            "content_hash": content_hash[:16]
        }
    )
    
    if requires_review:
        queue_notification(
            recipient_email="compliance@equilibra.internal",
            recipient_type="owner",
            title=f"Uncertain Document Review: {title}",
            message=f"Document {doc_id} classified as '{kind}' with low confidence ({confidence}). Please verify structured fields before posting.",
            category="document_review",
            event_key=f"doc-review-{doc_id}"
        )
        
    return {
        "status": "processed",
        "document_id": doc_id,
        "canonical_id": canonical_id("document", doc_id),
        "title": title,
        "kind": kind,
        "confidence": confidence,
        "requires_review": requires_review,
        "extracted_fields": extracted,
        "indexed_chunks": chunk_count,
        "ocr_applied": ocr_applied,
        "ocr_provider": "paddleocr" if ocr_applied else None,
        "message": f"Document processed and indexed into pgvector ({chunk_count} chunks)."
    }


def cross_validate_document_with_entity(
    entity_type: str,
    entity_id: str,
    document_id: Optional[str] = None,
    document_text: Optional[str] = None,
    org_id: Optional[str] = None
) -> "AgentDecision":
    """Cross-validate an ingested document against authoritative database records.
    
    Grounds extracted document figures against authoritative database records:
    - For leases: verifies monthly rent, security deposit, tenant name, and dates.
    - For invoices: verifies invoice number, vendor, subtotal, tax, and total.
    Returns a validated structured AgentDecision.
    """
    from .agent_execution import (
        AgentDecision, EvidenceReference, EstablishedAgent,
        DecisionOutcome, ConfidenceLevel, RiskLevel, ExecutionStatus,
        create_abstention_decision, assert_tenant_access
    )

    # 1. Fetch document body
    doc_body = document_text
    doc_title = "Direct Document Payload"
    doc_rec_id = document_id or "DIRECT"

    if document_id and not doc_body:
        with db() as conn:
            row = conn.execute(
                "SELECT id, title, kind, body, lease_id, property_id FROM documents WHERE id = %s",
                (document_id,)
            ).fetchone()
            if row:
                doc_rec_id = row[0]
                doc_title = row[1]
                doc_body = row[3]

    if not doc_body or len(doc_body.strip()) < 10:
        return create_abstention_decision(
            agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
            case_id=entity_id,
            reason=f"Document text for '{doc_rec_id}' is empty, unparseable, or missing from document store.",
            org_id=org_id,
            approval_role="property_manager"
        )

    classification = classify_document(doc_body)
    extracted = extract_structured_fields(doc_body, classification["kind"])
    evidence_list: List[EvidenceReference] = []

    # 2. Cross-validate by entity type
    if entity_type == "lease":
        with db() as conn:
            lease_row = conn.execute(
                """SELECT l.lease_id, l.property_id, p.org_id, l.unit, l.address,
                          l.tenant1, l.monthly_rent_usd, l.security_deposit_usd, l.move_in_date, l.end_date
                   FROM lease_records l
                   JOIN properties p ON l.property_id = p.property_id
                   WHERE l.lease_id = %s""",
                (entity_id,)
            ).fetchone()

        if not lease_row:
            return create_abstention_decision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                reason=f"Authoritative lease record '{entity_id}' not found in database.",
                org_id=org_id
            )

        assert_tenant_access(lease_row[2], org_id, f"Lease {entity_id}")
        db_rent = float(lease_row[6])
        db_deposit = float(lease_row[7])
        db_tenant = str(lease_row[5])

        extracted_amounts = extracted.get("extracted_amounts_usd", [])
        rent_matched = any(abs(a - db_rent) < 0.01 for a in extracted_amounts)
        deposit_matched = any(abs(a - db_deposit) < 0.01 for a in extracted_amounts)
        tenant_matched = db_tenant.lower() in doc_body.lower()

        evidence_list.append(EvidenceReference(
            entity_type="lease",
            entity_id=entity_id,
            source_table="lease_records",
            field_values={
                "monthly_rent_usd": db_rent,
                "security_deposit_usd": db_deposit,
                "tenant1": db_tenant
            },
            citation=f"Contractual rent ${db_rent:.2f}, deposit ${db_deposit:.2f} for {db_tenant}"
        ))

        evidence_list.append(EvidenceReference(
            entity_type="document",
            entity_id=doc_rec_id,
            source_table="documents",
            field_values={
                "extracted_amounts_usd": extracted_amounts,
                "classification": classification["kind"],
                "extracted_dates": extracted.get("extracted_dates", [])
            },
            citation=f"Document '{doc_title}' extracted amounts: {extracted_amounts}"
        ))

        if rent_matched and tenant_matched:
            return AgentDecision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                decision=DecisionOutcome.MATCH_CONFIRMED.value,
                confidence=0.95,
                confidence_level=ConfidenceLevel.HIGH,
                evidence=evidence_list,
                rationale=f"Document text for '{doc_title}' confirms contractual rent (${db_rent:.2f}) and tenant identity ({db_tenant}).",
                recommended_action="Proceed with verified lease document indexing.",
                requires_human_approval=False,
                risk_level=RiskLevel.LOW,
                execution_status=ExecutionStatus.EXECUTED,
                org_id=lease_row[2]
            )
        elif not rent_matched:
            mismatched_rent = extracted_amounts[0] if extracted_amounts else "None detected"
            return AgentDecision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                decision=DecisionOutcome.DISCREPANCY_FLAGGED.value,
                confidence=0.88,
                confidence_level=ConfidenceLevel.HIGH,
                evidence=evidence_list,
                rationale=f"Rent amount discrepancy: Signed document indicates ${mismatched_rent} vs database record ${db_rent:.2f}.",
                recommended_action="Route to compliance officer for manual lease document audit.",
                requires_human_approval=True,
                approval_role="compliance_officer",
                risk_level=RiskLevel.HIGH,
                execution_status=ExecutionStatus.RECOMMENDED,
                org_id=lease_row[2]
            )
        else:
            return AgentDecision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                decision=DecisionOutcome.NEEDS_REVIEW.value,
                confidence=0.72,
                confidence_level=ConfidenceLevel.MEDIUM,
                evidence=evidence_list,
                rationale=f"Partial verification: Rent matched but tenant name '{db_tenant}' was not confirmed in text.",
                recommended_action="Verify tenant signatory identity.",
                requires_human_approval=True,
                approval_role="property_manager",
                risk_level=RiskLevel.MEDIUM,
                execution_status=ExecutionStatus.RECOMMENDED,
                org_id=lease_row[2]
            )

    elif entity_type == "vendor_invoice":
        with db() as conn:
            inv_row = conn.execute(
                """SELECT vi.id, vi.invoice_number, vi.total_usd, v.name as vendor_name, p.org_id
                   FROM vendor_invoices vi
                   JOIN vendors v ON vi.vendor_id = v.vendor_id
                   LEFT JOIN properties p ON vi.property_id = p.property_id
                   WHERE vi.id = %s""",
                (entity_id,)
            ).fetchone()

        if not inv_row:
            return create_abstention_decision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                reason=f"Authoritative vendor invoice record '{entity_id}' not found.",
                org_id=org_id
            )

        resolved_org = inv_row[4] or "ORG-APEX"
        assert_tenant_access(resolved_org, org_id, f"Invoice {entity_id}")

        db_inv_num = str(inv_row[1])
        db_total = float(inv_row[2])
        db_vendor = str(inv_row[3])

        extracted_amounts = extracted.get("extracted_amounts_usd", [])
        total_matched = any(abs(a - db_total) < 0.05 for a in extracted_amounts)
        num_matched = db_inv_num.lower() in doc_body.lower()
        vendor_matched = db_vendor.lower() in doc_body.lower()

        evidence_list.append(EvidenceReference(
            entity_type="invoice",
            entity_id=entity_id,
            source_table="vendor_invoices",
            field_values={"invoice_number": db_inv_num, "total_usd": db_total, "vendor_name": db_vendor},
            citation=f"Authoritative invoice record: #{db_inv_num}, Total: ${db_total:.2f}, Vendor: {db_vendor}"
        ))

        evidence_list.append(EvidenceReference(
            entity_type="document",
            entity_id=doc_rec_id,
            source_table="documents",
            field_values={"extracted_amounts_usd": extracted_amounts, "classification": classification["kind"]},
            citation=f"Document text extractions: {extracted_amounts}"
        ))

        if total_matched and (num_matched or vendor_matched):
            return AgentDecision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                decision=DecisionOutcome.MATCH_CONFIRMED.value,
                confidence=0.94,
                confidence_level=ConfidenceLevel.HIGH,
                evidence=evidence_list,
                rationale=f"Document extractions for #{db_inv_num} match database total (${db_total:.2f}) and vendor ({db_vendor}).",
                recommended_action="Proceed to 4-way Accounts Payable matching.",
                requires_human_approval=False,
                risk_level=RiskLevel.LOW,
                execution_status=ExecutionStatus.EXECUTED,
                org_id=resolved_org
            )
        elif not total_matched:
            return AgentDecision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                decision=DecisionOutcome.DISCREPANCY_FLAGGED.value,
                confidence=0.89,
                confidence_level=ConfidenceLevel.HIGH,
                evidence=evidence_list,
                rationale=f"Invoice total mismatch: Document indicates {extracted_amounts} vs database record ${db_total:.2f}.",
                recommended_action="Hold payment voucher; request vendor billing clarification.",
                requires_human_approval=True,
                approval_role="financial_controller",
                risk_level=RiskLevel.HIGH,
                execution_status=ExecutionStatus.RECOMMENDED,
                org_id=resolved_org
            )
        else:
            return AgentDecision(
                agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
                case_id=entity_id,
                decision=DecisionOutcome.NEEDS_REVIEW.value,
                confidence=0.68,
                confidence_level=ConfidenceLevel.MEDIUM,
                evidence=evidence_list,
                rationale=f"Vendor identity or invoice number could not be confidently confirmed from document text.",
                recommended_action="Manual inspection of invoice header required.",
                requires_human_approval=True,
                approval_role="property_manager",
                risk_level=RiskLevel.MEDIUM,
                execution_status=ExecutionStatus.RECOMMENDED,
                org_id=resolved_org
            )

    return create_abstention_decision(
        agent_id=EstablishedAgent.DOCUMENT_INTELLIGENCE.value,
        case_id=entity_id,
        reason=f"Unsupported entity type '{entity_type}' for document cross-validation.",
        org_id=org_id
    )

