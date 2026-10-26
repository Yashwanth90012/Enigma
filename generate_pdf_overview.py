#!/usr/bin/env python3
"""Generate a comprehensive, beautifully styled PDF explaining EQUILIBRA in simple terms."""

import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Header (pages 2+)
        if self._pageNumber > 1:
            self.drawString(54, letter[1] - 36, "EQUILIBRA — Autonomous Property Management & Financial Cloud")
            self.drawRightString(letter[0] - 54, letter[1] - 36, "Executive Plain-English Guide")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, letter[1] - 42, letter[0] - 54, letter[1] - 42)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 45, letter[0] - 54, 45)
        self.drawString(54, 32, "Confidential & Proprietary — EQUILIBRA GenAI Platform")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(letter[0] - 54, 32, page_str)
        self.restoreState()


def build_pdf(filename="EQUILIBRA_Project_Overview.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#2563EB'),
        spaceAfter=14
    )

    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0284C7'),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6
    )

    body_bold = ParagraphStyle(
        'BodyBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )

    callout_style = ParagraphStyle(
        'Callout',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1E293B')
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.white
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#1E293B')
    )

    table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=table_cell_style,
        fontName='Helvetica-Bold'
    )

    story = []

    # Title & Subtitle Banner
    story.append(Paragraph("EQUILIBRA Platform Overview", title_style))
    story.append(Paragraph("What is EQUILIBRA and How Does It Work? — An Executive Plain-English Guide", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceAfter=12))

    # 1. Executive Summary in 30 Seconds
    story.append(Paragraph("1. The 30-Second Summary: What is EQUILIBRA?", h1_style))
    story.append(Paragraph(
        "<b>EQUILIBRA</b> (formerly known as <i>ENIGMA</i>) is an intelligent, automated operating system for <b>property management companies</b> "
        "(landlords, commercial REITs, apartment building operators, and real estate asset managers).", body_style
    ))
    story.append(Paragraph(
        "Think of it as an <b>autonomous financial controller and digital property manager</b> working 24/7. "
        "It handles the messy, error-prone tasks that real estate companies usually do by hand: reconciling monthly rent payments, "
        "checking contractor bills against actual repairs, screening rental applicants, enforcing state tenancy laws, and answering tenant inquiries. "
        "Unlike generic AI that can hallucinate numbers, EQUILIBRA uses <b>exact mathematical accounting</b> combined with <b>strict human approval gates</b>.", body_style
    ))

    # Callout Box: The 3 Core Promises
    core_callout_data = [[
        Paragraph(
            "<b>The Three Golden Rules of EQUILIBRA:</b><br/>"
            "• <b>Zero Hallucinated Numbers:</b> All money calculations are done with exact cents precision in Python Decimal—never by an AI guessing numbers.<br/>"
            "• <b>Complete Paper Trail (Lineage DAG):</b> Every single payment, approval, or fee adjustment is recorded in an immutable ledger with cause-and-effect tracking.<br/>"
            "• <b>Human-in-the-Loop Safeguards:</b> Large contractor invoices (> $500), security deposit withholdings, and legal notices cannot be finalized without a real human manager's digital sign-off.",
            callout_style
        )
    ]]
    t_callout = Table(core_callout_data, colWidths=[504])
    t_callout.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F0F9FF')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#BAE6FD')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(t_callout)
    story.append(Spacer(1, 10))

    # 2. What Real-World Problems Does It Solve?
    story.append(Paragraph("2. The Real-World Headaches Property Managers Face", h1_style))
    story.append(Paragraph(
        "Managing hundreds or thousands of apartment units involves massive volumes of fragmented paperwork and disconnected software systems:", body_style
    ))

    problems_data = [
        [Paragraph("Problem in Property Management", table_header_style), Paragraph("How EQUILIBRA Solves It", table_header_style)],
        [
            Paragraph("<b>Missing or Discrepant Rent:</b><br/>Tenants pay random amounts via bank transfers, checks, or ACH. Matching hundreds of deposits to 100+ lease contracts by hand takes days and leads to missed late fees or wrongful eviction threats.", table_cell_style),
            Paragraph("<b>Automated 3-Way Match:</b><br/>Instantly connects Lease Invoices ↔ Tenant Payments ↔ Bank Deposits. It even recognizes when a tenant legitimately withheld rent because of an unresolved emergency leak!", table_cell_style)
        ],
        [
            Paragraph("<b>Contractor Overbilling & Fraud:</b><br/>Plumbers and HVAC contractors send paper or PDF invoices charging $1,200 for a job quoted at $800, adding unauthorized materials or sneaky card surcharge fees.", table_cell_style),
            Paragraph("<b>Automated 4-Way Match:</b><br/>Scans PDF invoices using local Optical Character Recognition (OCR), extracts line items, and compares Work Order Scope ↔ PDF Invoice ↔ Payment Voucher ↔ Bank Clearance to catch overcharges.", table_cell_style)
        ],
        [
            Paragraph("<b>Strict Statutory Law Deadlines:</b><br/>States impose fierce legal deadlines (e.g. California requires returning deposits within 21 days; New York within 14 days). Missing these deadlines exposes landlords to double-damage lawsuits.", table_cell_style),
            Paragraph("<b>Automated Statutory Clocks:</b><br/>Monitors legal jurisdictions (CA, NY, TX, WA) automatically, ticking countdown clocks the minute a tenant gives notice to vacate and flagging overdue action items.", table_cell_style)
        ],
        [
            Paragraph("<b>Scattered Resident Communication:</b><br/>Renewal letters get sent twice, move-in checklists are forgotten, and tenant maintenance emergencies get lost in email inboxes.", table_cell_style),
            Paragraph("<b>Resident Lifecycle Hub:</b><br/>Tracks lease expirations 90 days out, generates renewal agreements with rent-cap calculations, and organizes step-by-step move-in and move-out workflows.", table_cell_style)
        ]
    ]

    t_problems = Table(problems_data, colWidths=[240, 264])
    t_problems.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E293B')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')])
    ]))
    story.append(t_problems)
    story.append(Spacer(1, 14))

    # Page Break for clean reading
    story.append(PageBreak())

    # 3. Deep Dive into the Core Hubs & Agents
    story.append(Paragraph("3. Tour of the System: The 6 Key Operational Hubs", h1_style))
    story.append(Paragraph(
        "EQUILIBRA organizes property management operations into dedicated, interconnected modules accessible via a modern web interface:", body_style
    ))

    # Module 1
    story.append(Paragraph("A. Tenant Rental Accounts Receivable (AR) Hub", h2_style))
    story.append(Paragraph(
        "Evaluates the entire rent roll across 100 residential leases. It groups leases into clear status buckets: <b>Clean</b>, "
        "<b>Underpaid</b>, <b>Discrepant</b>, <b>Overpaid</b>, and <b>Withholding</b>. "
        "When an issue is flagged, managers can click <i>'Investigate'</i> to see exact timestamps, bank reference codes, "
        "and mathematical variance breakdowns without ever calculating by hand.", body_style
    ))

    # Module 2
    story.append(Paragraph("B. Vendor Maintenance & Accounts Payable (AP) Hub", h2_style))
    story.append(Paragraph(
        "Oversees contracted trade vendors (plumbing, electrical, HVAC, appliances, roofing). "
        "When a vendor submits a bill, the platform runs an authentic PDF generation and OCR extraction process. "
        "It then executes a <b>4-Way Reconciliation</b> comparing the original approved repair quote, the contractor's PDF invoice, "
        "the payment check/ACH voucher, and the bank clearance statement. Bills over $500 are automatically paused until a human manager approves.", body_style
    ))

    # Module 3
    story.append(Paragraph("C. Resident Experience & Lease Lifecycle Hub", h2_style))
    story.append(Paragraph(
        "Manages the complete tenant journey from tour booking to move-out:<br/>"
        "• <b>Rental Applications:</b> Collects applicant data, screens monthly income vs rent, and scores applicant risk.<br/>"
        "• <b>Move-In Checklist:</b> 6-step verified onboarding (lease signing, security deposit, renters insurance, keys handover).<br/>"
        "• <b>Lease Renewals:</b> Identifies leases expiring in 90 days, calculates statutory rent caps, and generates single renewal offers.<br/>"
        "• <b>Move-Out & Deposit Settlement:</b> Starts countdown clocks upon notice to vacate, tallies itemized deductions (e.g. wall patching, cleaning), and generates compliant settlement proposals.", body_style
    ))

    # Module 4
    story.append(Paragraph("D. Centralized Compliance & Risk Register", h2_style))
    story.append(Paragraph(
        "A portfolio-wide compliance radar that continuously audits 16 operational risk categories. "
        "It flags unresolved habitability risks (like an active water leak open past 24 hours), overdue move-in tasks, "
        "unreconciled payments, and statutory legal deadlines across <b>California</b> (21 days), <b>New York</b> (14 days), "
        "<b>Texas</b> (30 days), and <b>Washington</b> (30 days).", body_style
    ))

    # Module 5
    story.append(Paragraph("E. AI Document Intelligence & Search (Hybrid RAG)", h2_style))
    story.append(Paragraph(
        "EQUILIBRA can read uploaded PDFs, Word documents, and scanned images. It uses <b>PaddleOCR</b> (running 100% locally on the server "
        "without sending confidential tenant data to third parties) and indexes text into <b>PostgreSQL pgvector</b>. "
        "When a property manager asks a question like <i>'What is the late fee policy on Unit 4B?'</i>, the AI Assistant retrieves the exact lease clauses "
        "and answers strictly from the document text.", body_style
    ))

    # Module 6
    story.append(Paragraph("F. Zetaris Live Lakehouse Federation & Diagnostics", h2_style))
    story.append(Paragraph(
        "Allows EQUILIBRA to query distributed external corporate accounting databases via Zetaris Networked SQL. "
        "Strict security rules prevent unauthorized writes (blocking INSERT/UPDATE/DELETE), and the platform always discloses "
        "whether data came from a live external connection, local database, or verified fallback fixture.", body_style
    ))

    story.append(Spacer(1, 10))

    # Page Break for clean reading
    story.append(PageBreak())

    # 4. Under the Hood: Technical Architecture in Simple Terms
    story.append(Paragraph("4. Under the Hood: How the Tech Works Together", h1_style))
    story.append(Paragraph(
        "EQUILIBRA is built on modern, industrial-grade open-source and enterprise technologies, packaged cleanly in Docker containers:", body_style
    ))

    tech_stack_data = [
        [Paragraph("Component", table_header_style), Paragraph("Technology Used", table_header_style), Paragraph("Plain-English Role", table_header_style)],
        [
            Paragraph("<b>Frontend UI</b>", table_cell_bold),
            Paragraph("React 19, Vite, Vanilla CSS", table_cell_style),
            Paragraph("Interactive web app with dark/light themes, instant multi-tenant property switching, and live operational cards.", table_cell_style)
        ],
        [
            Paragraph("<b>Backend API</b>", table_cell_bold),
            Paragraph("FastAPI (Python 3.11)", table_cell_style),
            Paragraph("High-speed web server managing all business logic, agent workflows, security checks, and REST endpoints.", table_cell_style)
        ],
        [
            Paragraph("<b>Database</b>", table_cell_bold),
            Paragraph("PostgreSQL 16 + pgvector", table_cell_style),
            Paragraph("Relational storage for leases, payments, and work orders, plus AI vector indexing for instant document clause search.", table_cell_style)
        ],
        [
            Paragraph("<b>Document OCR</b>", table_cell_bold),
            Paragraph("PaddleOCR v3.7 (Local)", table_cell_style),
            Paragraph("Reads text from scanned contractor receipts and invoices directly on the machine without needing external internet APIs.", table_cell_style)
        ],
        [
            Paragraph("<b>AI Engine & Failover</b>", table_cell_bold),
            Paragraph("Meterless, NVIDIA NIM, Offline", table_cell_style),
            Paragraph("3-tier failover: uses smart cloud models when available, but automatically switches to offline logic if internet drops.", table_cell_style)
        ],
        [
            Paragraph("<b>Audit Ledger (DAG)</b>", table_cell_bold),
            Paragraph("Meterless World Model", table_cell_style),
            Paragraph("Immutable, append-only event trail connecting every action to its cause. Enables instant audits and undo/replay.", table_cell_style)
        ],
        [
            Paragraph("<b>Data Federation</b>", table_cell_bold),
            Paragraph("Zetaris Live Spark SQL", table_cell_style),
            Paragraph("Connects into legacy enterprise accounting databases safely with read-only guards.", table_cell_style)
        ]
    ]

    t_tech = Table(tech_stack_data, colWidths=[100, 150, 254])
    t_tech.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')])
    ]))
    story.append(t_tech)
    story.append(Spacer(1, 14))

    # 5. Safety & Trust: Why Landlords Can Trust It
    story.append(Paragraph("5. Safety, Governance & Separation of Duties", h1_style))
    story.append(Paragraph(
        "Many companies hesitate to adopt AI because they fear erratic decisions or hallucinated numbers. "
        "EQUILIBRA was specifically architected to eliminate these risks:", body_style
    ))
    story.append(Paragraph(
        "• <b>Separation of Duties:</b> AI agents are programmatically forbidden from approving their own financial transactions. "
        "Any action requiring authorization must be approved by an authenticated user with the proper role.<br/>"
        "• <b>Hard Multi-Tenant Isolation:</b> Each property management client (e.g., Apex Horizon vs. Beacon Bay Commercial) "
        "has strict organization boundaries. One client can never see, modify, or query another client's leases or financials.<br/>"
        "• <b>Idempotency Guarantees:</b> Automated billing runs or recurring rent sweeps use cryptographic deduplication keys. "
        "Even if a server restarts mid-transaction, a tenant will never be billed twice.<br/>"
        "• <b>Automatic Crash Recovery:</b> If the server loses power during a complex multi-step workflow, the system automatically detects "
        "interrupted jobs on boot-up and seamlessly resumes from the exact last successful step.", body_style
    ))

    story.append(Spacer(1, 10))

    # 6. How to Run It Locally
    story.append(Paragraph("6. Quick Start: How to Run the App Locally", h1_style))
    story.append(Paragraph(
        "The application is completely self-contained and already running on this machine:", body_style
    ))

    quickstart_data = [
        [Paragraph("Step", table_header_style), Paragraph("Command / URL", table_header_style), Paragraph("Description", table_header_style)],
        [
            Paragraph("<b>1. Web App</b>", table_cell_bold),
            Paragraph("<b>http://localhost:5173/</b>", table_cell_style),
            Paragraph("Open in any web browser to explore the full React interface, switch organizations, and view reconciliations.", table_cell_style)
        ],
        [
            Paragraph("<b>2. API Docs</b>", table_cell_bold),
            Paragraph("<b>http://localhost:8000/docs</b>", table_cell_style),
            Paragraph("Interactive Swagger documentation for all 57+ REST endpoints.", table_cell_style)
        ],
        [
            Paragraph("<b>3. System Health</b>", table_cell_bold),
            Paragraph("<b>http://localhost:8000/health</b>", table_cell_style),
            Paragraph("Live telemetry displaying database status, pgvector indexing, and AI routing mode.", table_cell_style)
        ],
        [
            Paragraph("<b>4. Test Suite</b>", table_cell_bold),
            Paragraph("<code>docker compose exec -T api pytest -v</code>", table_cell_style),
            Paragraph("Runs the comprehensive automated test suite (150+ tests passing 100%).", table_cell_style)
        ]
    ]

    t_quick = Table(quickstart_data, colWidths=[80, 190, 234])
    t_quick.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2563EB')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')])
    ]))
    story.append(t_quick)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated PDF: {filename}")

if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "EQUILIBRA_Project_Overview.pdf"
    build_pdf(out_file)
