import csv
from pathlib import Path
# pyrefly: ignore[missing-import]
from docx import Document
from .database import db, init_database
from .rag import index_document
from .config import settings
from .vendor_invoices import seed_vendors_and_sample_invoices

def seed():
    init_database()
    root = Path(settings.data_dir)
    if not (root / 'leases.csv').exists():
        # Fallback if running outside docker
        root = Path(__file__).resolve().parent.parent / 'data'
        
    leases = list(csv.DictReader((root / 'leases.csv').open()))
    work = list(csv.DictReader((root / 'work_orders.csv').open()))
    
    with db() as conn:
        for stmt in [
            'CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY, lease_id TEXT, amount NUMERIC(12,2), currency TEXT)',
            'CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY, lease_id TEXT, amount NUMERIC(12,2), currency TEXT, reference TEXT)',
            'CREATE TABLE IF NOT EXISTS bank_transactions(id TEXT PRIMARY KEY, lease_id TEXT, amount NUMERIC(12,2), currency TEXT, reference TEXT)'
        ]:
            conn.execute(stmt)

        # Populate lease_records table
        for l in leases:
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
                    l['lease_id'], l['property_id'], l.get('unit', ''), l['address'],
                    l['tenant1'], l.get('tenant2', ''), l.get('contract_date'),
                    l.get('move_in_date'), float(l['monthly_rent_usd']), float(l['security_deposit_usd'])
                )
            )

        # Populate work_order_records table
        for w in work:
            conn.execute(
                """INSERT INTO work_order_records (
                    work_order_id, lease_id, property_id, unit, address, tenant1,
                    reported_date, scheduled_date, completion_date, category,
                    description, priority, status, technician, estimated_cost_usd, technician_notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (work_order_id) DO UPDATE SET
                    lease_id = excluded.lease_id,
                    property_id = excluded.property_id,
                    unit = excluded.unit,
                    address = excluded.address,
                    tenant1 = excluded.tenant1,
                    reported_date = excluded.reported_date,
                    scheduled_date = excluded.scheduled_date,
                    completion_date = excluded.completion_date,
                    category = excluded.category,
                    description = excluded.description,
                    priority = excluded.priority,
                    status = excluded.status,
                    technician = excluded.technician,
                    estimated_cost_usd = excluded.estimated_cost_usd,
                    technician_notes = excluded.technician_notes""",
                (
                    w['work_order_id'], w['lease_id'], w['property_id'], w.get('unit', ''),
                    w.get('address', ''), w.get('tenant1', ''), w.get('reported_date'),
                    w.get('scheduled_date'), w.get('completion_date'), w['category'],
                    w['description'], w['priority'], w['status'], w.get('technician', ''),
                    float(w.get('estimated_cost_usd') or 0), w.get('technician_notes', '')
                )
            )

        # Financial ledgers
        for i, l in enumerate(leases, 1):
            lease = l['lease_id']
            rent = int(float(l['monthly_rent_usd']))
            conn.execute('INSERT INTO invoices VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (f'INV-{i:04d}', lease, rent, 'USD'))
            # Sample scenarios:
            # 0: exact match
            # 1: partial payment (difference 225)
            # 2: missing bank reference
            # 3: bank deposit only / unrecorded payment
            # 4: duplicate bank transactions
            scenario = i % 5
            amount = rent if scenario != 1 else rent - 225
            ref = f'PAYREF-{i:04d}'
            if scenario != 3:
                conn.execute('INSERT INTO payments VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                             (f'PAY-{i:04d}', lease, amount, 'USD', ref))
            bank_ref = ref if scenario not in (2, 3) else ''
            conn.execute('INSERT INTO bank_transactions VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                         (f'BANK-{i:04d}', lease, amount, 'USD', bank_ref))
            if scenario == 4:
                conn.execute('INSERT INTO bank_transactions VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                             (f'BANK-DUP-{i:04d}', lease, amount, 'USD', ref))

    # Documents and chunks RAG indexing
    for l in leases:
        fp = root / 'leases' / f"{l['lease_id']}.docx"
        if fp.exists():
            doc = Document(fp)
            text = '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            text = (f"Residential Lease Agreement {l['lease_id']}; Tenant {l['tenant1']}; "
                    f"Address {l['address']}; Monthly Rent ${l['monthly_rent_usd']}. "
                    "Section 3: Rent is due on the 1st of each month. Late fee of 5% applies after grace period. "
                    "Section 11: Tenant shall not deduct repair expenses or withhold rent without landlord consent. "
                    "Section 28: Notice of default required before termination.")
        index_document(l['lease_id'], l['lease_id'], l['property_id'], 'lease', l['address'], text)

    for w in work:
        text = (f"Work Order {w['work_order_id']}. Property {w['property_id']} Unit {w.get('unit','')}. "
                f"Category: {w['category']}. Priority: {w['priority']}. Status: {w['status']}. "
                f"Issue: {w['description']}. Estimated Cost: ${w.get('estimated_cost_usd',0)}. "
                f"Technician Notes: {w.get('technician_notes','')}")
        index_document(w['work_order_id'], w['lease_id'], w['property_id'], 'work_order', w['category'], text)

    # Seed maintenance vendors, generate .pdf invoices, and index into RAG
    vendor_seed_res = seed_vendors_and_sample_invoices()

    # Seed verified properties and public listings
    from .property_agent import seed_properties
    seed_properties()

    return {
        'leases': len(leases),
        'work_orders': len(work),
        'vendors': vendor_seed_res['seeded_vendors'],
        'vendor_invoices_pdf': vendor_seed_res['sample_invoices'],
        'properties': 4,
        'status': 'seeded_successfully'
    }

if __name__ == '__main__':
    print(seed())
