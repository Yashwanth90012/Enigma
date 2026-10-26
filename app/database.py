import hashlib
import re
import queue
import threading
from typing import Optional
from contextlib import contextmanager
# pyrefly: ignore[missing-import]
import psycopg
# pyrefly: ignore[missing-import]
from pgvector.psycopg import register_vector
from .config import settings
from .timing import perf_tracker


class SimpleConnectionPool:
    """Thread-safe PostgreSQL connection pool avoiding raw TCP re-connection overhead."""

    def __init__(self, dsn: str, max_connections: int = 15):
        self.dsn = dsn
        self.max_connections = max_connections
        self._pool = queue.Queue(maxsize=max_connections)
        self._created = 0
        self._lock = threading.Lock()

    def get_conn(self) -> psycopg.Connection:
        try:
            conn = self._pool.get_nowait()
            if conn.closed:
                conn = self._create_conn()
            return conn
        except queue.Empty:
            with self._lock:
                if self._created < self.max_connections:
                    self._created += 1
                    return self._create_conn()
            # Wait up to 10 seconds for an active connection to return
            return self._pool.get(timeout=10.0)

    def return_conn(self, conn: psycopg.Connection):
        if conn and not conn.closed:
            try:
                conn.rollback()  # reset clean transaction state
                self._pool.put_nowait(conn)
            except (queue.Full, Exception):
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    self._created = max(0, self._created - 1)
        else:
            with self._lock:
                self._created = max(0, self._created - 1)

    def _create_conn(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn, autocommit=False)
        try:
            register_vector(conn)
        except Exception:
            pass
        return conn


_pool_instance: Optional[SimpleConnectionPool] = None
_pool_lock = threading.Lock()

def get_pool() -> SimpleConnectionPool:
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = SimpleConnectionPool(settings.database_url, max_connections=15)
    return _pool_instance

@contextmanager
def db():
    pool = get_pool()
    with perf_tracker.time_stage("db_query"):
        conn = pool.get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.return_conn(conn)

def init_database():
    with db() as conn:
        conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
        conn.execute('''CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, lease_id TEXT, property_id TEXT, kind TEXT NOT NULL,
            title TEXT NOT NULL, body TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now())''')
        conn.execute('''CREATE TABLE IF NOT EXISTS chunks (
            id BIGSERIAL PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
            lease_id TEXT, property_id TEXT, heading TEXT, body TEXT NOT NULL,
            embedding vector(384),
            search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english',body)) STORED)''')
        conn.execute('CREATE INDEX IF NOT EXISTS chunks_lease ON chunks(lease_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS chunks_prop ON chunks(property_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS chunks_fts ON chunks USING gin(search_tsv)')
        conn.execute('CREATE INDEX IF NOT EXISTS chunks_hnsw ON chunks USING hnsw(embedding vector_cosine_ops)')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS lease_records (
            lease_id TEXT PRIMARY KEY,
            property_id TEXT NOT NULL,
            unit TEXT,
            address TEXT NOT NULL,
            tenant1 TEXT NOT NULL,
            tenant2 TEXT,
            contract_date TEXT,
            move_in_date TEXT,
            monthly_rent_usd NUMERIC(12,2) NOT NULL,
            security_deposit_usd NUMERIC(12,2) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS leases_prop ON lease_records(property_id)')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS work_order_records (
            work_order_id TEXT PRIMARY KEY,
            lease_id TEXT NOT NULL,
            property_id TEXT NOT NULL,
            unit TEXT,
            address TEXT,
            tenant1 TEXT,
            reported_date TEXT,
            scheduled_date TEXT,
            completion_date TEXT,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            technician TEXT,
            estimated_cost_usd NUMERIC(12,2) NOT NULL,
            technician_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS wo_lease ON work_order_records(lease_id)')

        conn.execute('''CREATE TABLE IF NOT EXISTS world_events (
            id BIGSERIAL PRIMARY KEY, case_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT now())''')
        # Migrate world_events with canonical_id, version, and caused_by if not present
        conn.execute('ALTER TABLE world_events ADD COLUMN IF NOT EXISTS canonical_id TEXT')
        conn.execute('ALTER TABLE world_events ADD COLUMN IF NOT EXISTS version INT DEFAULT 1')
        conn.execute('ALTER TABLE world_events ADD COLUMN IF NOT EXISTS caused_by JSONB DEFAULT \'[]\'::jsonb')
        conn.execute('CREATE INDEX IF NOT EXISTS events_case ON world_events(case_id,id)')
        conn.execute('CREATE INDEX IF NOT EXISTS events_canonical ON world_events(canonical_id)')

        conn.execute('''CREATE TABLE IF NOT EXISTS derived_states (
            case_id TEXT PRIMARY KEY,
            canonical_id TEXT NOT NULL,
            version INT NOT NULL,
            state JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT now())''')

        conn.execute('''CREATE TABLE IF NOT EXISTS approvals (
            case_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            note TEXT,
            action TEXT DEFAULT 'approved',
            reviewer TEXT DEFAULT 'Property Manager',
            updated_at TIMESTAMPTZ DEFAULT now())''')
        conn.execute("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS action TEXT DEFAULT 'approved'")
        conn.execute("ALTER TABLE approvals ADD COLUMN IF NOT EXISTS reviewer TEXT DEFAULT 'Property Manager'")

        # Vendor Maintenance & AP Tables
        conn.execute('''CREATE TABLE IF NOT EXISTS vendors (
            vendor_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            trade TEXT NOT NULL,
            contact_email TEXT,
            phone TEXT,
            payment_terms TEXT DEFAULT 'Net 30',
            created_at TIMESTAMPTZ DEFAULT now()
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS vendor_invoices (
            id TEXT PRIMARY KEY,
            vendor_id TEXT REFERENCES vendors(vendor_id) ON DELETE CASCADE,
            work_order_id TEXT,
            lease_id TEXT,
            property_id TEXT,
            invoice_number TEXT NOT NULL,
            issue_date TEXT,
            due_date TEXT,
            item_summary TEXT,
            subtotal_usd NUMERIC(12,2) NOT NULL,
            tax_usd NUMERIC(12,2) NOT NULL,
            total_usd NUMERIC(12,2) NOT NULL,
            pdf_path TEXT,
            status TEXT DEFAULT 'unpaid',
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS vi_wo ON vendor_invoices(work_order_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS vi_lease ON vendor_invoices(lease_id)')

        conn.execute('''CREATE TABLE IF NOT EXISTS vendor_payments (
            id TEXT PRIMARY KEY,
            invoice_id TEXT REFERENCES vendor_invoices(id) ON DELETE CASCADE,
            amount_usd NUMERIC(12,2) NOT NULL,
            payment_method TEXT NOT NULL,
            reference TEXT NOT NULL,
            payment_date TEXT,
            status TEXT DEFAULT 'issued',
            details JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS vp_inv ON vendor_payments(invoice_id)')

        conn.execute('''CREATE TABLE IF NOT EXISTS vendor_bank_transactions (
            id TEXT PRIMARY KEY,
            invoice_id TEXT,
            amount_usd NUMERIC(12,2) NOT NULL,
            payment_method TEXT NOT NULL,
            reference TEXT,
            clearing_date TEXT,
            merchant_fee_usd NUMERIC(12,2) DEFAULT 0.00,
            status TEXT DEFAULT 'cleared'
        )''')

        # Properties & Units Table
        conn.execute('''CREATE TABLE IF NOT EXISTS properties (
            property_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            zip_code TEXT NOT NULL,
            property_type TEXT DEFAULT 'Residential Multifamily',
            total_units INT DEFAULT 1,
            monthly_rent_usd NUMERIC(12,2) NOT NULL,
            security_deposit_usd NUMERIC(12,2) NOT NULL,
            amenities JSONB DEFAULT '[]'::jsonb,
            images JSONB DEFAULT '[]'::jsonb,
            verification_status TEXT DEFAULT 'pending',
            verification_score NUMERIC(5,2) DEFAULT 0.0,
            verification_findings JSONB DEFAULT '{}'::jsonb,
            is_published BOOLEAN DEFAULT FALSE,
            org_id TEXT DEFAULT 'ORG-APEX',
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS prop_published ON properties(is_published)')
        conn.execute('CREATE INDEX IF NOT EXISTS prop_org ON properties(org_id)')

        # Public Tour Bookings Table
        conn.execute('''CREATE TABLE IF NOT EXISTS tour_bookings (
            id TEXT PRIMARY KEY,
            property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
            unit TEXT,
            resident_name TEXT NOT NULL,
            resident_email TEXT NOT NULL,
            resident_phone TEXT,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            status TEXT DEFAULT 'confirmed',
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS tb_prop ON tour_bookings(property_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS tb_email ON tour_bookings(resident_email)')

        # Rental Applications Table
        conn.execute('''CREATE TABLE IF NOT EXISTS rental_applications (
            id TEXT PRIMARY KEY,
            property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
            unit TEXT,
            applicant_name TEXT NOT NULL,
            applicant_email TEXT NOT NULL,
            applicant_phone TEXT,
            monthly_income_usd NUMERIC(12,2) NOT NULL,
            credit_score INT DEFAULT 700,
            status TEXT DEFAULT 'under_review',
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS ra_prop ON rental_applications(property_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS ra_email ON rental_applications(applicant_email)')

        # Notifications Table
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
            delivered_at TIMESTAMPTZ
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS notif_recipient ON notifications(recipient_email)')
        conn.execute('CREATE INDEX IF NOT EXISTS notif_key ON notifications(event_key)')

        # Migrate chunks with model_name and is_semantic if not present
        conn.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS model_name TEXT DEFAULT 'deterministic-hash-v1'")
        conn.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_semantic BOOLEAN DEFAULT FALSE")

        # SaaS Organizations Table
        conn.execute('''CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            portfolio_type TEXT DEFAULT 'Residential Multifamily',
            tier TEXT DEFAULT 'Enterprise Cloud',
            aws_region TEXT DEFAULT 'us-east-1',
            active_units INT DEFAULT 100,
            contact_email TEXT NOT NULL,
            primary_ledger TEXT DEFAULT 'Zetaris SQL REST Federation',
            ai_engine TEXT DEFAULT 'NVIDIA Nemotron-4-340B (Meterless Nightshift)',
            description TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT now()
        )''')

        # SaaS Feature Requests Table
        conn.execute('''CREATE TABLE IF NOT EXISTS feature_requests (
            id TEXT PRIMARY KEY,
            org_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
            org_name TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            specification TEXT NOT NULL,
            status TEXT DEFAULT 'TRIAGED',
            target_release TEXT DEFAULT 'Upcoming Cloud Sprint',
            votes INT DEFAULT 1,
            submitted_by TEXT DEFAULT 'Property Manager',
            submitted_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS fr_org ON feature_requests(org_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS fr_cat ON feature_requests(category)')
        conn.execute('CREATE INDEX IF NOT EXISTS fr_status ON feature_requests(status)')

        # SaaS Feature Request Upvotes Table (deduplicated by voter)
        conn.execute('''CREATE TABLE IF NOT EXISTS feature_request_votes (
            request_id TEXT REFERENCES feature_requests(id) ON DELETE CASCADE,
            voter_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (request_id, voter_id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS frv_voter ON feature_request_votes(voter_id)')

        # Seed initial SaaS organizations and feature requests safely
        from .saas import DEFAULT_ORGANIZATIONS, DEFAULT_FEATURE_REQUESTS
        for org in DEFAULT_ORGANIZATIONS:
            conn.execute(
                """INSERT INTO organizations (
                    id, name, portfolio_type, tier, aws_region, active_units,
                    contact_email, primary_ledger, ai_engine, description, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (
                    org["id"], org["name"], org.get("portfolio_type", "Residential Multifamily"),
                    org.get("tier", "Enterprise Cloud"), org.get("aws_region", "us-east-1"),
                    org.get("active_units", 100), org["contact_email"], org.get("primary_ledger", ""),
                    org.get("ai_engine", ""), org.get("description", ""), org.get("created_at")
                )
            )

        for req in DEFAULT_FEATURE_REQUESTS:
            conn.execute(
                """INSERT INTO feature_requests (
                    id, org_id, org_name, title, category, priority, specification,
                    status, target_release, votes, submitted_by, submitted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (
                    req["id"], req["org_id"], req["org_name"], req["title"], req["category"],
                    req["priority"], req["specification"], req.get("status", "TRIAGED"),
                    req.get("target_release", "Upcoming Cloud Sprint"), req.get("votes", 1),
                    req.get("submitted_by", "Property Manager"), req.get("submitted_at")
                )
            )

        # =====================================================================
        # Phase 2A: Resident & Lease Lifecycle Workflow Tables & Migrations
        # =====================================================================

        # Migrate lease_records with lifecycle columns
        conn.execute("ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS end_date TEXT")
        conn.execute("ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS lease_status TEXT DEFAULT 'active'")
        conn.execute("ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS resident_email TEXT")
        conn.execute("ALTER TABLE lease_records ADD COLUMN IF NOT EXISTS communication_preferences JSONB DEFAULT '{\"email\": true, \"sms\": false}'::jsonb")
        conn.execute("CREATE INDEX IF NOT EXISTS leases_status ON lease_records(lease_status)")

        # Safe backfill for legacy leases where end_date or resident_email is null
        conn.execute("""
            UPDATE lease_records
            SET end_date = TO_CHAR((move_in_date::date + INTERVAL '1 year'), 'YYYY-MM-DD')
            WHERE end_date IS NULL AND move_in_date IS NOT NULL
        """)
        conn.execute("""
            UPDATE lease_records
            SET resident_email = LOWER(REPLACE(tenant1, ' ', '.')) || '@equilibra-tenant.internal'
            WHERE resident_email IS NULL AND tenant1 IS NOT NULL
        """)

        # 1. Lease Renewals Table
        conn.execute('''CREATE TABLE IF NOT EXISTS lease_renewals (
            id TEXT PRIMARY KEY,
            lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE CASCADE,
            property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
            renewal_period TEXT NOT NULL,
            current_rent_usd NUMERIC(12,2) NOT NULL,
            proposed_rent_usd NUMERIC(12,2) NOT NULL,
            term_months INT DEFAULT 12,
            eligibility_status TEXT DEFAULT 'eligible',
            status TEXT DEFAULT 'offer_prepared',
            offer_terms TEXT,
            resident_decision TEXT,
            decision_date TIMESTAMPTZ,
            manager_approval_state TEXT DEFAULT 'pending',
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (lease_id, renewal_period)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS lr_lease ON lease_renewals(lease_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS lr_status ON lease_renewals(status)')

        # 2. Move-In Checklists Table
        conn.execute('''CREATE TABLE IF NOT EXISTS move_in_checklists (
            id TEXT PRIMARY KEY,
            lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE CASCADE,
            property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
            resident_name TEXT NOT NULL,
            resident_email TEXT NOT NULL,
            target_move_in_date TEXT NOT NULL,
            status TEXT DEFAULT 'in_progress',
            tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ,
            UNIQUE (lease_id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS mic_lease ON move_in_checklists(lease_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS mic_status ON move_in_checklists(status)')

        # 3. Move-Out Records & Closeouts Table
        conn.execute('''CREATE TABLE IF NOT EXISTS move_out_records (
            id TEXT PRIMARY KEY,
            lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE CASCADE,
            property_id TEXT REFERENCES properties(property_id) ON DELETE CASCADE,
            resident_name TEXT NOT NULL,
            resident_email TEXT NOT NULL,
            notice_date TEXT NOT NULL,
            planned_move_out_date TEXT NOT NULL,
            actual_move_out_date TEXT,
            forwarding_address TEXT,
            status TEXT DEFAULT 'notice_received',
            tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
            security_deposit_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
            outstanding_balance_usd NUMERIC(12,2) NOT NULL DEFAULT 0.00,
            proposed_deductions JSONB DEFAULT '[]'::jsonb,
            proposed_refund_usd NUMERIC(12,2) DEFAULT 0.00,
            statutory_deadline_date TEXT,
            closeout_approval_state TEXT DEFAULT 'pending',
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            approval_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (lease_id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS mor_lease ON move_out_records(lease_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS mor_status ON move_out_records(status)')

        # =====================================================================
        # Phase 2B: Central Risk Register & Compliance Tables
        # =====================================================================

        # 1. Central Risk Register
        conn.execute('''CREATE TABLE IF NOT EXISTS risk_findings (
            id TEXT PRIMARY KEY,
            stable_key TEXT UNIQUE NOT NULL,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            property_id TEXT REFERENCES properties(property_id) ON DELETE SET NULL,
            lease_id TEXT REFERENCES lease_records(lease_id) ON DELETE SET NULL,
            invoice_id TEXT,
            vendor_id TEXT,
            work_order_id TEXT,
            resident_id TEXT,
            category TEXT NOT NULL,
            finding_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            source_record_type TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            detection_rule TEXT NOT NULL,
            originating_event TEXT,
            evidence JSONB DEFAULT '{}'::jsonb,
            jurisdiction TEXT,
            statutory_source TEXT,
            effective_date TEXT,
            compliance_status TEXT DEFAULT 'not_applicable',
            status TEXT NOT NULL DEFAULT 'open',
            assigned_reviewer TEXT,
            due_date TIMESTAMPTZ,
            last_reviewed_at TIMESTAMPTZ,
            reviewed_by TEXT,
            resolution_notes TEXT,
            resolved_by TEXT,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_org ON risk_findings(org_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_status ON risk_findings(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_severity ON risk_findings(severity)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_category ON risk_findings(category)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_finding_type ON risk_findings(finding_type)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_prop ON risk_findings(property_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_lease ON risk_findings(lease_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_key ON risk_findings(stable_key)')

        # 2. Centralized Approval & Review History
        conn.execute('''CREATE TABLE IF NOT EXISTS approval_history (
            id BIGSERIAL PRIMARY KEY,
            case_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            decision_reason TEXT NOT NULL,
            previous_state TEXT,
            new_state TEXT,
            org_id TEXT,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS ah_case ON approval_history(case_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS ah_reviewer ON approval_history(reviewer)')
        conn.execute('CREATE INDEX IF NOT EXISTS ah_org ON approval_history(org_id)')

        # 3. Agent Execution & Idempotency Logs
        conn.execute('''CREATE TABLE IF NOT EXISTS agent_execution_logs (
            id BIGSERIAL PRIMARY KEY,
            idempotency_key TEXT UNIQUE NOT NULL,
            agent_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            action_name TEXT NOT NULL,
            org_id TEXT,
            decision JSONB NOT NULL,
            status TEXT NOT NULL,
            latency_ms NUMERIC(10,2),
            executed_at TIMESTAMPTZ DEFAULT now()
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS ael_key ON agent_execution_logs(idempotency_key)')
        conn.execute('CREATE INDEX IF NOT EXISTS ael_agent ON agent_execution_logs(agent_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS ael_case ON agent_execution_logs(case_id)')
        # Communication Templates & Versions
        conn.execute('''CREATE TABLE IF NOT EXISTS communication_templates (
            id TEXT PRIMARY KEY,
            template_key TEXT NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            trigger_event TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            supported_variables JSONB DEFAULT '[]'::jsonb,
            required_variables JSONB DEFAULT '[]'::jsonb,
            org_id TEXT DEFAULT 'system',
            is_default BOOLEAN DEFAULT TRUE,
            enabled BOOLEAN DEFAULT TRUE,
            version INT DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (template_key, org_id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS ct_key ON communication_templates(template_key)')
        conn.execute('CREATE INDEX IF NOT EXISTS ct_cat ON communication_templates(category)')
        conn.execute('CREATE INDEX IF NOT EXISTS ct_org ON communication_templates(org_id)')

        conn.execute('''CREATE TABLE IF NOT EXISTS communication_template_versions (
            id BIGSERIAL PRIMARY KEY,
            template_id TEXT NOT NULL REFERENCES communication_templates(id) ON DELETE CASCADE,
            template_key TEXT NOT NULL,
            version INT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            modified_by TEXT NOT NULL,
            change_summary TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )''')

        # Phase 5 High-Impact Targeted Query Optimization Indexes
        conn.execute('CREATE INDEX IF NOT EXISTS doc_prop ON documents(property_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS doc_lease ON documents(lease_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS doc_kind ON documents(kind)')
        conn.execute('CREATE INDEX IF NOT EXISTS doc_created ON documents(created_at DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS vi_status ON vendor_invoices(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS wo_status ON work_order_records(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS wo_priority ON work_order_records(priority)')
        conn.execute('CREATE INDEX IF NOT EXISTS rf_status_sev ON risk_findings(status, severity)')
        conn.execute('CREATE INDEX IF NOT EXISTS tmpl_category ON communication_templates(category)')
        conn.execute('CREATE INDEX IF NOT EXISTS lr_prop ON lease_records(property_id)')

        # Phase 6 Dynamic Orchestration & Recoverable Execution Tables
        conn.execute('''CREATE TABLE IF NOT EXISTS orchestration_workflows (
            workflow_id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            workflow_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            initiating_request JSONB NOT NULL DEFAULT '{}',
            current_state TEXT NOT NULL DEFAULT 'created',
            plan_revision INT NOT NULL DEFAULT 1,
            plan_dag JSONB NOT NULL DEFAULT '[]',
            context_data JSONB NOT NULL DEFAULT '{}',
            approval_requirements JSONB,
            approval_status JSONB,
            verification_results JSONB,
            error_details JSONB,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS ow_org_state ON orchestration_workflows(org_id, current_state)')
        conn.execute('CREATE INDEX IF NOT EXISTS ow_type_target ON orchestration_workflows(workflow_type, target_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS ow_created ON orchestration_workflows(created_at DESC)')

        conn.execute('''CREATE TABLE IF NOT EXISTS orchestration_steps (
            step_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES orchestration_workflows(workflow_id) ON DELETE CASCADE,
            plan_revision INT NOT NULL DEFAULT 1,
            agent_id TEXT NOT NULL,
            operation_name TEXT NOT NULL,
            execution_order INT NOT NULL DEFAULT 1,
            dependencies JSONB NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'planned',
            inputs JSONB NOT NULL DEFAULT '{}',
            outputs JSONB,
            evidence JSONB DEFAULT '[]',
            attempt_count INT NOT NULL DEFAULT 0,
            max_retries INT NOT NULL DEFAULT 2,
            duration_ms NUMERIC(10,2),
            error_message TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            completed_at TIMESTAMPTZ
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS os_wf_state ON orchestration_steps(workflow_id, state)')
        conn.execute('CREATE INDEX IF NOT EXISTS os_agent ON orchestration_steps(agent_id)')

def simple_embedding(text: str):
    """Deterministic hashed lexical vector; OFFLINE DEMO ONLY, not a semantic model."""
    vec = [0.0] * 384
    tokens = re.findall(r'[a-z0-9]+',text.lower())
    for term in tokens:
        digest = hashlib.sha256(term.encode()).digest()
        pos = int.from_bytes(digest[:4],'little') % 384
        vec[pos] += 1 if digest[4] % 2 else -1
    norm = sum(x*x for x in vec)**0.5 or 1
    return [x/norm for x in vec]
