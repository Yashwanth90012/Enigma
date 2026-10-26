"""Vendor Maintenance Management & PDF Invoice Generation & RAG Ingestion.

Handles:
- Maintenance vendors (sinks, bathtubs, lights, HVAC, appliances, hardware)
- Authentic .PDF invoice generation using ReportLab
- PDF extraction and hybrid vector indexing via pypdf and pgvector
- Multi-format payment records (Cashier's Check, Check, Credit Card, ACH)
"""

import os
import json
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import pypdf
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from .database import db
from .rag import index_document
from .world_model import record_event, canonical_id

PDF_DIR = Path('data/invoices_pdf')
PDF_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VENDORS = [
    {
        'vendor_id': 'VEND-001',
        'name': 'Apex Plumbing & Sinks',
        'trade': 'Plumbing, Sinks & Faucets',
        'contact_email': 'billing@apexplumbingsupply.com',
        'phone': '(510) 555-0192',
        'payment_terms': 'Net 30'
    },
    {
        'vendor_id': 'VEND-002',
        'name': 'Bay Area Fixtures & Bathtubs',
        'trade': 'Bathtubs, Shower Pans & Enclosures',
        'contact_email': 'orders@bayfixtures.com',
        'phone': '(510) 555-0143',
        'payment_terms': 'Net 15'
    },
    {
        'vendor_id': 'VEND-003',
        'name': 'Lumina Electrical & Lighting',
        'trade': 'LED Fixtures, Vanity Lights & Wiring',
        'contact_email': 'service@luminalighting.com',
        'phone': '(415) 555-0188',
        'payment_terms': 'Due Upon Receipt'
    },
    {
        'vendor_id': 'VEND-004',
        'name': 'ProClimate HVAC Solutions',
        'trade': 'Heating, Air Conditioning & Ductwork',
        'contact_email': 'dispatch@proclimatehvac.com',
        'phone': '(510) 555-0177',
        'payment_terms': 'Net 30'
    },
    {
        'vendor_id': 'VEND-005',
        'name': 'AllStar Appliance Solutions',
        'trade': 'Dishwashers, Ranges & Refrigerators',
        'contact_email': 'claims@allstarappliance.com',
        'phone': '(415) 555-0122',
        'payment_terms': 'Net 30'
    },
    {
        'vendor_id': 'VEND-006',
        'name': 'Summit Building Materials',
        'trade': 'Hardware, Drywall, Paint & Fasteners',
        'contact_email': 'sales@summitmaterials.com',
        'phone': '(510) 555-0165',
        'payment_terms': 'Net 30'
    }
]

class InvoicePDFResult(tuple):
    """Result tuple that also supports dictionary-style key access and object attributes."""
    def __new__(cls, pdf_path: str, subtotal_usd: float, tax_usd: float, total_usd: float,
                issue_date: str = '', due_date: str = '', item_summary: str = ''):
        return super().__new__(cls, (pdf_path, subtotal_usd, tax_usd, total_usd))

    def __init__(self, pdf_path: str, subtotal_usd: float, tax_usd: float, total_usd: float,
                 issue_date: str = '', due_date: str = '', item_summary: str = ''):
        self.pdf_path = pdf_path
        self.subtotal_usd = subtotal_usd
        self.tax_usd = tax_usd
        self.total_usd = total_usd
        self.issue_date = issue_date
        self.due_date = due_date
        self.item_summary = item_summary

    def __getitem__(self, item):
        if isinstance(item, str):
            mapping = {
                'pdf_path': self.pdf_path,
                'subtotal_usd': self.subtotal_usd,
                'tax_usd': self.tax_usd,
                'total_usd': self.total_usd,
                'issue_date': self.issue_date,
                'due_date': self.due_date,
                'item_summary': self.item_summary
            }
            if item in mapping:
                return mapping[item]
            raise KeyError(item)
        return super().__getitem__(item)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

def generate_vendor_invoice_pdf(
    invoice_number: str,
    vendor: Dict[str, Any],
    work_order_id: str = 'WO-0001',
    lease_id: str = 'LEASE-0001',
    property_id: str = 'PROP-001',
    unit: str = 'Unit 101',
    address: str = '700 Example Grove Avenue, Berkeley, CA',
    issue_date: Optional[str] = None,
    due_date: Optional[str] = None,
    line_items: Optional[List[Dict[str, Any]]] = None,
    tax_rate: float = 0.0825,
    notes: Optional[str] = None
) -> InvoicePDFResult:
    """Generate an authentic PDF vendor invoice file using ReportLab."""
    now_dt = datetime.now(timezone.utc)
    issue_date = issue_date or now_dt.strftime('%Y-%m-%d')
    due_date = due_date or (now_dt + timedelta(days=30)).strftime('%Y-%m-%d')
    line_items = line_items or [{'description': 'General Maintenance Service', 'qty': 1, 'unit_price': 150.00}]

    filename = f"{invoice_number}.pdf"
    file_path = PDF_DIR / filename

    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=colors.HexColor('#0f172a'),
        leading=24
    )
    meta_style = ParagraphStyle(
        'MetaStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        textColor=colors.HexColor('#475569'),
        leading=13
    )
    bold_style = ParagraphStyle(
        'BoldStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=colors.HexColor('#1e293b'),
        leading=14
    )

    elements = []

    # Header: Vendor Name & Invoice Label
    v_email = vendor.get('contact_email') or vendor.get('email', 'billing@vendor.com')
    v_phone = vendor.get('phone', '(555) 000-0000')
    header_data = [
        [
            Paragraph(f"<b>{vendor['name']}</b><br/>{vendor.get('trade', 'General Contractor')}<br/>Phone: {v_phone}<br/>Email: {v_email}", meta_style),
            Paragraph(f"<b>INVOICE</b><br/><font color='#06b6d4'><b>#{invoice_number}</b></font><br/>Date: {issue_date}<br/>Due Date: {due_date}", meta_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[320, 220])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 14))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cbd5e1'), spaceAfter=14))

    # Bill To & Service Property Table
    bill_data = [
        [
            Paragraph("<b>BILLED TO (PROPERTY MANAGEMENT):</b><br/>ENIGMA Property Management LLC<br/>535 Mission St, 14th Floor<br/>San Francisco, CA 94105", meta_style),
            Paragraph(f"<b>SERVICE LOCATION & WORK ORDER:</b><br/>Property: {property_id} · Unit: {unit}<br/>Address: {address}<br/><b>Associated Work Order: {work_order_id}</b><br/>Lease Scope: {lease_id}", meta_style)
        ]
    ]
    bill_table = Table(bill_data, colWidths=[270, 270])
    bill_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(bill_table)
    elements.append(Spacer(1, 18))

    # Itemized Table
    subtotal = Decimal('0.00')
    items_rows = [
        [
            Paragraph("<b>Description</b>", bold_style),
            Paragraph("<b>Qty</b>", bold_style),
            Paragraph("<b>Unit Price</b>", bold_style),
            Paragraph("<b>Line Total</b>", bold_style)
        ]
    ]

    for item in line_items:
        qty = Decimal(str(item.get('qty', 1)))
        price = Decimal(str(item.get('unit_price', 0.00)))
        line_total = (qty * price).quantize(Decimal('0.01'))
        subtotal += line_total
        desc = item.get('description') or item.get('desc') or 'Service item'
        items_rows.append([
            Paragraph(desc, meta_style),
            Paragraph(str(qty), meta_style),
            Paragraph(f"${price:.2f}", meta_style),
            Paragraph(f"${line_total:.2f}", meta_style)
        ])

    tax = (subtotal * Decimal(str(tax_rate))).quantize(Decimal('0.01'))
    total = subtotal + tax

    items_table = Table(items_rows, colWidths=[280, 50, 100, 110])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')])
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 12))

    # Summary Totals Table
    totals_data = [
        ["Subtotal:", f"${subtotal:.2f}"],
        [f"Sales Tax ({tax_rate*100:.2f}%):", f"${tax:.2f}"],
        ["TOTAL AMOUNT DUE:", f"${total:.2f}"]
    ]
    totals_table = Table(totals_data, colWidths=[430, 110])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,-1), (-1,-1), 11),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor('#0f172a')),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 20))

    # Payment Remittance Terms
    terms_text = (
        f"<b>PAYMENT INSTRUCTIONS & ACCEPTED FORMATS:</b><br/>"
        f"Terms: {vendor.get('payment_terms', 'Net 30')}. Remit payments payable to: <b>{vendor['name']}</b>.<br/>"
        f"Accepted payment methods: <b>Cashier's Check</b> (Bank Issued), <b>Normal Corporate Check</b>, or <b>Credit Card</b> (Visa/Mastercard/Amex).<br/>"
        f"For wire/ACH or card payments, please quote Invoice <b>#{invoice_number}</b> and Work Order <b>{work_order_id}</b>."
    )
    elements.append(Paragraph(terms_text, meta_style))

    if notes:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(f"<b>Special Notes:</b> {notes}", meta_style))

    doc.build(elements)

    item_summary = (line_items[0].get('description') or line_items[0].get('desc') or 'Maintenance Service')
    if len(line_items) > 1:
        item_summary += f" (+{len(line_items)-1} parts)"

    return InvoicePDFResult(
        pdf_path=str(file_path),
        subtotal_usd=float(subtotal),
        tax_usd=float(tax),
        total_usd=float(total),
        issue_date=issue_date,
        due_date=due_date,
        item_summary=item_summary
    )


def extract_pdf_text(pdf_path: str) -> str:
    """Extract plain text from a generated PDF invoice using pypdf."""
    reader = pypdf.PdfReader(pdf_path)
    text_parts = []
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            text_parts.append(txt)
    return "\n\n".join(text_parts)

def index_vendor_invoice_rag(
    invoice_id: str,
    pdf_path: str,
    vendor_id: str = '',
    vendor_name: str = '',
    work_order_id: str = '',
    lease_id: str = 'LEASE-0001',
    property_id: str = 'PROP-001'
) -> Dict[str, Any]:
    """Extract text from vendor invoice PDF and index into pgvector HNSW and GIN FTS."""
    extracted = extract_pdf_text(pdf_path)
    title = f"Vendor Invoice {invoice_id} - {vendor_name or vendor_id} ({work_order_id})"
    chunks_count = index_document(
        document_id=invoice_id,
        lease_id=lease_id,
        property_id=property_id,
        kind='vendor_invoice',
        title=title,
        body=extracted
    )
    return {
        'status': 'indexed',
        'invoice_id': invoice_id,
        'pdf_path': pdf_path,
        'indexed_chunks': chunks_count
    }

def seed_vendors_and_sample_invoices():
    """Seed initial maintenance vendors, generate authentic PDF invoices, and index into RAG."""
    with db() as conn:
        for v in DEFAULT_VENDORS:
            conn.execute(
                """INSERT INTO vendors (vendor_id, name, trade, contact_email, phone, payment_terms)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (vendor_id) DO UPDATE SET
                       name = excluded.name,
                       trade = excluded.trade,
                       contact_email = excluded.contact_email,
                       phone = excluded.phone,
                       payment_terms = excluded.payment_terms""",
                (v['vendor_id'], v['name'], v['trade'], v['contact_email'], v['phone'], v['payment_terms'])
            )

    # Initial sample invoices connecting sinks, bathtubs, lighting, HVAC, and appliances
    sample_bills = [
        {
            'invoice_id': 'VINV-0001',
            'vendor_id': 'VEND-001', # Apex Plumbing & Sinks
            'work_order_id': 'WO-0001',
            'lease_id': 'LEASE-0001',
            'property_id': 'PROP-001',
            'unit': '101',
            'address': '700 Example Grove Avenue, Unit 101, Berkeley, CA',
            'issue_date': '2025-04-24',
            'due_date': '2025-05-24',
            'item_summary': 'Kitchen Sink Faucet & Valve Replacement',
            'items': [
                {'description': 'Stainless Pull-Out Kitchen Sink Faucet Assembly', 'qty': 1, 'unit_price': 135.00},
                {'description': 'Brass Angle Stop Valves & Supply Lines (pair)', 'qty': 1, 'unit_price': 34.00},
                {'description': 'Licensed Plumber Labor (2.0 hrs @ $80/hr)', 'qty': 2.0, 'unit_price': 80.00}
            ],
            'payment': {
                'method': 'credit_card',
                'ref': 'CC-AUTH-99214',
                'amount': 356.10, # exact total with tax
                'details': {'card_brand': 'Visa Business', 'last4': '4912', 'auth_code': '99214'}
            },
            'bank_tx': {
                'amount': 356.10,
                'method': 'credit_card',
                'ref': 'CC-AUTH-99214',
                'fee': 0.00
            }
        },
        {
            'invoice_id': 'VINV-0002',
            'vendor_id': 'VEND-002', # Bay Area Fixtures & Bathtubs
            'work_order_id': 'WO-0002',
            'lease_id': 'LEASE-0002',
            'property_id': 'PROP-001',
            'unit': '102',
            'address': '700 Example Grove Avenue, Unit 102, Berkeley, CA',
            'issue_date': '2026-01-14',
            'due_date': '2026-02-14',
            'item_summary': 'Bathroom Bathtub Drain Clearing & Surround Re-caulk',
            'items': [
                {'description': 'Bathtub Heavy-Duty Snake Auger Clearing Service', 'qty': 1, 'unit_price': 120.00},
                {'description': 'Anti-Microbial Silicone Sealant & Tub Gasket Kit', 'qty': 1, 'unit_price': 38.00},
                {'description': 'Specialized Bathtub Technician Labor (1.5 hrs)', 'qty': 1.5, 'unit_price': 75.00}
            ],
            'payment': {
                'method': 'cashiers_check',
                'ref': 'CASH-CHK-88102',
                'amount': 292.82,
                'details': {'issuing_bank': 'First Republic / Chase', 'check_number': '88102'}
            },
            'bank_tx': {
                'amount': 292.82,
                'method': 'cashiers_check',
                'ref': 'CASH-CHK-88102',
                'fee': 0.00
            }
        },
        {
            'invoice_id': 'VINV-0003',
            'vendor_id': 'VEND-003', # Lumina Electrical & Lighting
            'work_order_id': 'WO-0003',
            'lease_id': 'LEASE-0003',
            'property_id': 'PROP-001',
            'unit': '103',
            'address': '700 Example Grove Avenue, Unit 103, Berkeley, CA',
            'issue_date': '2025-05-09',
            'due_date': '2025-06-09',
            'item_summary': 'Kitchen Under-Sink Pipe Seal & GFCI Outlet Installation',
            'items': [
                {'description': 'Water-Resistant GFCI 20A Dual Outlet Receptacle', 'qty': 2, 'unit_price': 28.00},
                {'description': 'PVC Drain Trap & Moisture Sensor Box', 'qty': 1, 'unit_price': 45.00},
                {'description': 'Electrician & Pipe Specialist Labor (3 hrs)', 'qty': 3.0, 'unit_price': 85.00}
            ],
            'payment': {
                'method': 'check', # Normal corporate check
                'ref': 'CHK-77401',
                'amount': 385.37,
                'details': {'check_number': '77401', 'bank_account': 'Operating Checking *7802'}
            },
            # Notice: Uncashed check! Bank tx is missing to demonstrate uncashed check reconciliation detection!
            'bank_tx': None
        },
        {
            'invoice_id': 'VINV-0004',
            'vendor_id': 'VEND-004', # ProClimate HVAC
            'work_order_id': 'WO-0004',
            'lease_id': 'LEASE-0004',
            'property_id': 'PROP-001',
            'unit': '104',
            'address': '700 Example Grove Avenue, Unit 104, Berkeley, CA',
            'issue_date': '2026-05-11',
            'due_date': '2026-06-11',
            'item_summary': 'AC Condenser Fan Motor & Capacitor Replacement',
            'items': [
                {'description': '1/4 HP Outdoor Condenser Fan Motor Replacement', 'qty': 1, 'unit_price': 185.00},
                {'description': 'Dual Run Capacitor 45/5 MFD 440V', 'qty': 1, 'unit_price': 42.00},
                {'description': 'HVAC Certified Refrigerant System Check & Labor', 'qty': 2.0, 'unit_price': 95.00}
            ],
            'payment': {
                'method': 'credit_card',
                'ref': 'CC-AUTH-44109',
                'amount': 451.41,
                'details': {'card_brand': 'Mastercard Fleet', 'last4': '1109', 'auth_code': '44109'}
            },
            'bank_tx': {
                # Surcharge variance scenario: Bank statement charged $467.21 (with 3.5% card surcharge)!
                'amount': 467.21,
                'method': 'credit_card',
                'ref': 'CC-AUTH-44109',
                'fee': 15.80
            }
        },
        {
            'invoice_id': 'VINV-0005',
            'vendor_id': 'VEND-005', # AllStar Appliance
            'work_order_id': 'WO-0005',
            'lease_id': 'LEASE-0005',
            'property_id': 'PROP-001',
            'unit': '105',
            'address': '700 Example Grove Avenue, Unit 105, Berkeley, CA',
            'issue_date': '2026-03-20',
            'due_date': '2026-04-20',
            'item_summary': 'Dishwasher Drain Solenoid & Float Switch',
            'items': [
                {'description': 'Appliance Grade Float Switch & Wire Harness', 'qty': 1, 'unit_price': 65.00},
                {'description': 'Appliance Diagnostic & Repair Service Call', 'qty': 1, 'unit_price': 125.00}
            ],
            'payment': None, # Unpaid / Pending property manager review!
            'bank_tx': None
        },
        # ORG-VERDANT / PROP-002 Invoices
        {
            'invoice_id': 'VINV-0021',
            'vendor_id': 'VEND-001',
            'work_order_id': 'WO-0021',
            'lease_id': 'LEASE-0021',
            'property_id': 'PROP-002',
            'unit': '121',
            'address': '710 Example Grove Avenue, Unit 121, Berkeley, CA 94704',
            'issue_date': '2026-03-12',
            'due_date': '2026-04-12',
            'item_summary': 'Commercial Water Heater Pressure Relief Valve Replacement',
            'items': [
                {'description': 'Watts Temperature & Pressure Relief Valve 3/4"', 'qty': 1, 'unit_price': 85.00},
                {'description': 'Plumber Dispatch & Diagnostic Labor (1.5 hrs)', 'qty': 1.5, 'unit_price': 90.00}
            ],
            'payment': {
                'method': 'ach',
                'ref': 'ACH-TR-88129',
                'amount': 238.15,
                'details': {'bank_name': 'First Republic', 'account_last4': '9012', 'trace': '88129'}
            },
            'bank_tx': {
                'amount': 238.15,
                'method': 'ach',
                'ref': 'ACH-TR-88129',
                'fee': 0.00
            }
        },
        {
            'invoice_id': 'VINV-0022',
            'vendor_id': 'VEND-004',
            'work_order_id': 'WO-0024',
            'lease_id': 'LEASE-0024',
            'property_id': 'PROP-002',
            'unit': '124',
            'address': '710 Example Grove Avenue, Unit 124, Berkeley, CA 94704',
            'issue_date': '2026-04-01',
            'due_date': '2026-05-01',
            'item_summary': 'HVAC Rooftop Chiller Coil De-icing & Blower Inspection',
            'items': [
                {'description': 'Commercial High-MERV Chiller Filter Pack (x4)', 'qty': 4, 'unit_price': 42.00},
                {'description': 'EPA Certified HVAC Diagnostic Labor (2.0 hrs)', 'qty': 2.0, 'unit_price': 110.00}
            ],
            'payment': None,
            'bank_tx': None
        },
        # ORG-BEACON / PROP-003 Invoices
        {
            'invoice_id': 'VINV-0041',
            'vendor_id': 'VEND-003',
            'work_order_id': 'WO-0041',
            'lease_id': 'LEASE-0041',
            'property_id': 'PROP-003',
            'unit': '141',
            'address': '720 Example Grove Avenue, Unit 141, Berkeley, CA 94704',
            'issue_date': '2026-02-18',
            'due_date': '2026-03-18',
            'item_summary': 'Plaza Common Corridor Emergency Exit Lighting & Ballasts',
            'items': [
                {'description': 'Dual-Lite Emergency LED Exit Light Fixture', 'qty': 2, 'unit_price': 120.00},
                {'description': 'Commercial Electrician Service Call (2.0 hrs)', 'qty': 2.0, 'unit_price': 95.00}
            ],
            'payment': {
                'method': 'check',
                'ref': 'CHK-77401',
                'amount': 466.56,
                'details': {'check_number': '77401'}
            },
            'bank_tx': {
                'amount': 466.56,
                'method': 'check',
                'ref': 'CHK-77401',
                'fee': 0.00
            }
        },
        # ORG-SKYLINE / PROP-004 Invoices
        {
            'invoice_id': 'VINV-0061',
            'vendor_id': 'VEND-002',
            'work_order_id': 'WO-0061',
            'lease_id': 'LEASE-0061',
            'property_id': 'PROP-004',
            'unit': '161',
            'address': '730 Example Grove Avenue, Unit 161, Berkeley, CA 94704',
            'issue_date': '2026-03-25',
            'due_date': '2026-04-25',
            'item_summary': 'Modern Loft Shower Pan Regrouting & Silicone Sealing',
            'items': [
                {'description': 'Mold-Resistant Epoxy Tile Grout & Primer Kit', 'qty': 1, 'unit_price': 75.00},
                {'description': 'Tile & Glaze Technician Labor (2.5 hrs)', 'qty': 2.5, 'unit_price': 70.00}
            ],
            'payment': None,
            'bank_tx': None
        }
    ]

    vendor_lookup = {v['vendor_id']: v for v in DEFAULT_VENDORS}

    for b in sample_bills:
        v = vendor_lookup[b['vendor_id']]
        pdf_path, subtotal, tax, total = generate_vendor_invoice_pdf(
            invoice_number=b['invoice_id'],
            vendor=v,
            work_order_id=b['work_order_id'],
            lease_id=b['lease_id'],
            property_id=b['property_id'],
            unit=b['unit'],
            address=b['address'],
            issue_date=b['issue_date'],
            due_date=b['due_date'],
            line_items=b['items']
        )

        with db() as conn:
            conn.execute(
                """INSERT INTO vendor_invoices (
                    id, vendor_id, work_order_id, lease_id, property_id,
                    invoice_number, issue_date, due_date, item_summary,
                    subtotal_usd, tax_usd, total_usd, pdf_path, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    subtotal_usd = excluded.subtotal_usd,
                    tax_usd = excluded.tax_usd,
                    total_usd = excluded.total_usd,
                    pdf_path = excluded.pdf_path,
                    status = excluded.status""",
                (
                    b['invoice_id'], b['vendor_id'], b['work_order_id'], b['lease_id'], b['property_id'],
                    b['invoice_id'], b['issue_date'], b['due_date'], b['item_summary'],
                    subtotal, tax, total, pdf_path, 'paid' if b.get('payment') else 'unpaid'
                )
            )

            if b.get('payment'):
                p = b['payment']
                conn.execute(
                    """INSERT INTO vendor_payments (
                        id, invoice_id, amount_usd, payment_method, reference, payment_date, status, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO NOTHING""",
                    (
                        f"VPAY-{b['invoice_id']}", b['invoice_id'], p['amount'],
                        p['method'], p['ref'], b['issue_date'], 'issued',
                        json.dumps(p.get('details', {}))
                    )
                )

            if b.get('bank_tx'):
                bt = b['bank_tx']
                conn.execute(
                    """INSERT INTO vendor_bank_transactions (
                        id, invoice_id, amount_usd, payment_method, reference, clearing_date, merchant_fee_usd, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING""",
                    (
                        f"VBANK-{b['invoice_id']}", b['invoice_id'], bt['amount'],
                        bt['method'], bt['ref'], b['issue_date'], bt.get('fee', 0.0), 'cleared'
                    )
                )

        # Index the PDF contents into RAG!
        index_vendor_invoice_rag(
            invoice_id=b['invoice_id'],
            vendor_id=b['vendor_id'],
            work_order_id=b['work_order_id'],
            lease_id=b['lease_id'],
            property_id=b['property_id'],
            pdf_path=pdf_path
        )

        record_event(b['lease_id'], b['invoice_id'], 'vendor_invoice_generated', {
            'vendor': v['name'],
            'invoice_id': b['invoice_id'],
            'total_usd': total,
            'work_order_id': b['work_order_id'],
            'pdf_path': pdf_path
        })

    return {'seeded_vendors': len(DEFAULT_VENDORS), 'sample_invoices': len(sample_bills)}
