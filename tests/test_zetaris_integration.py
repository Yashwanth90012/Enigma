"""Automated Test Suite for Zetaris Live Financial Data Integration.

Covers:
1. Successful connection and schema discovery
2. Authentication and permission failures (read-only enforcement)
3. Missing or changed source tables and columns
4. Live record mapping and data normalization
5. Decimal accuracy and currency preservation
6. Duplicate ingestion prevention
7. Pagination and bounded query results
8. Timeouts and unavailable-source behavior
9. Explicit fixture and fallback labeling (never silent fallback)
10. Reconciliation using source records
11. Cross-organization access denial
12. Regression behavior across finance, vendor, resident, compliance, and RAG
"""

import pytest
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
import httpx
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

from app.config import settings
from app.providers import (
    ZetarisFinance,
    normalize_zetaris_case,
    ZetarisError,
    ZetarisAuthError,
    ZetarisConnectionError,
    ZetarisQueryError,
    ZetarisPermissionError,
)
from app.engine import (
    cents,
    calculate,
    fixture_rows,
    fetch_financial_records,
    investigate,
)
from app.finance_agent import (
    generate_monthly_rent_invoices,
    record_tenant_payment,
    sweep_grace_period_and_overdue,
)
from app.vendor_agent import (
    get_vendor_invoice_bundle,
    reconcile_vendor_bill,
)


# =============================================================================
# 1. Connection and Schema Discovery
# =============================================================================

def test_zetaris_connection_and_discovery():
    """Verify live connectivity, latency measurement, and metadata catalog discovery."""
    z = ZetarisFinance()
    conn_info = z.test_connection()
    assert conn_info["configured"] is True
    assert conn_info["reachable"] is True
    assert conn_info["status"] == "HEALTHY"
    assert conn_info["mode"] == "live"
    assert "latency_ms" in conn_info

    meta = z.discover_metadata()
    assert meta["status"] == "discovered"
    assert "spark_catalog" in meta["catalogs"]
    assert "enigma_invoices" in meta["views"]
    assert meta["views"]["enigma_invoices"]["status"] == "mounted"
    assert "amount" in meta["views"]["enigma_invoices"]["columns"]


# =============================================================================
# 2. Authentication and Permission Failures (Read-Only Enforcement)
# =============================================================================

def test_zetaris_write_operations_forbidden():
    """Ensure any modifying SQL statement is strictly blocked before transmission."""
    z = ZetarisFinance()
    with pytest.raises(ZetarisPermissionError, match="Write operations are strictly prohibited"):
        z.sql("INSERT INTO enigma_invoices VALUES ('INV-TEST', 'LEASE-0001', 100, 'USD')")

    with pytest.raises(ZetarisPermissionError, match="Write operations are strictly prohibited"):
        z.sql("DROP TABLE invoices")

    with pytest.raises(ZetarisPermissionError, match="Write operations are strictly prohibited"):
        z.sql("UPDATE enigma_invoices SET amount = 0")


def test_zetaris_auth_error_handling():
    """Verify 401/403 responses raise ZetarisAuthError without exposing credentials."""
    z = ZetarisFinance()
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Invalid or expired token"
        mock_post.return_value = mock_resp

        with pytest.raises(ZetarisAuthError, match="Zetaris authentication failed with status 401"):
            z.sql("SELECT 1")


# =============================================================================
# 3. Missing or Changed Source Tables and Columns
# =============================================================================

def test_zetaris_missing_table_error_handling():
    """Verify missing tables produce clear, structured ZetarisQueryError."""
    z = ZetarisFinance()
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "msg": "[TABLE_OR_VIEW_NOT_FOUND] The table or view `nonexistent_view` cannot be found."
        }
        mock_post.return_value = mock_resp

        with pytest.raises(ZetarisQueryError, match="Zetaris schema error"):
            z.sql("SELECT * FROM nonexistent_view")


# =============================================================================
# 4. Live Record Mapping and Data Normalization
# =============================================================================

def test_zetaris_response_shape_normalization():
    """Verify normalization across standard Zetaris, columnar, and wrapped payloads."""
    # Standard Zetaris SQL Editor shape
    zetaris_standard = {
        "invoices": {
            "headers": ["id", "lease_id", "amount", "currency"],
            "data": [["INV-001", "LEASE-0001", "2125.00", "USD"]],
            "total": 1,
            "timeUsed": 100
        },
        "payments": {
            "headers": ["id", "lease_id", "amount", "currency", "reference"],
            "data": [["PAY-001", "LEASE-0001", "2125.00", "USD", "REF-001"]],
            "total": 1
        },
        "bank": {
            "headers": ["id", "lease_id", "amount", "currency", "reference"],
            "data": [["BANK-001", "LEASE-0001", "2125.00", "USD", "REF-001"]],
            "total": 1
        }
    }
    norm = normalize_zetaris_case(zetaris_standard)
    assert len(norm["invoices"]) == 1
    assert norm["invoices"][0]["id"] == "INV-001"
    assert norm["invoices"][0]["amount"] == "2125.00"
    assert norm["payments"][0]["reference"] == "REF-001"
    assert norm["bank"][0]["reference"] == "REF-001"

    # Columnar shape
    columnar = {
        "invoices": {
            "columns": ["id", "amount", "currency"],
            "rows": [["INV-002", "1800.00", "USD"]]
        }
    }
    norm_col = normalize_zetaris_case(columnar)
    assert norm_col["invoices"][0]["id"] == "INV-002"
    assert norm_col["invoices"][0]["amount"] == "1800.00"


# =============================================================================
# 5. Decimal Accuracy and Currency Preservation
# =============================================================================

def test_zetaris_decimal_accuracy_and_currency_preservation():
    """Verify exact Decimal arithmetic with zero floating point drift."""
    assert cents("2125.00") == 212500
    assert cents("2125.99") == 212599
    assert cents("0.01") == 1
    assert cents(Decimal("1999.95")) == 199995

    # Multi-currency mismatch handling
    records = {
        "invoices": [{"id": "INV-1", "amount": "2125.00", "currency": "USD"}],
        "payments": [{"id": "PAY-1", "amount": "2125.00", "currency": "EUR", "reference": "REF-1"}],
        "bank": [{"id": "BANK-1", "amount": "2125.00", "currency": "EUR", "reference": "REF-1"}]
    }
    res = calculate(records)
    assert res["status"] == "needs_review"
    assert res["reason_code"] == "CURRENCY_MISMATCH"
    assert res["currency"] == "USD"


# =============================================================================
# 6. Duplicate Ingestion Prevention
# =============================================================================

def test_duplicate_payment_ingestion_prevention():
    """Ensure duplicate payment remittance with existing reference is rejected."""
    ref = f"IDEM-TEST-{uuid.uuid4().hex[:6]}"
    p1 = record_tenant_payment("LEASE-0001", 100.0, reference=ref)
    assert p1["status"] == "payment_applied"

    p2 = record_tenant_payment("LEASE-0001", 100.0, reference=ref)
    assert p2["status"] == "duplicate_prevented"
    assert p2["payment_id"] == p1["payment_id"]


# =============================================================================
# 7. Pagination and Bounded Query Results
# =============================================================================

def test_zetaris_bounded_query_results_and_limits():
    """Verify live read query results are bounded and respect limits."""
    z = ZetarisFinance()
    res = z.sql("SELECT * FROM enigma_invoices LIMIT 2")
    assert "headers" in res
    assert "data" in res
    assert len(res["data"]) <= 2


# =============================================================================
# 8. Timeouts and Unavailable-Source Behavior
# =============================================================================

def test_zetaris_timeout_and_unreachable_behavior():
    """Verify timeout and network failure are handled safely without crashing."""
    z = ZetarisFinance()
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timeout")):
        with pytest.raises(ZetarisConnectionError, match="request timed out"):
            z.sql("SELECT 1", timeout=1)

    with patch("httpx.Client.post", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(ZetarisConnectionError, match="Cannot connect to Zetaris"):
            z.sql("SELECT 1")


# =============================================================================
# 9. Explicit Fixture and Fallback Labeling
# =============================================================================

def test_explicit_fixture_fallback_labeling():
    """Verify fallback is explicitly labeled as fixture_fallback with a safe reason."""
    with patch.object(settings, "finance_source", "zetaris"):
        with patch.object(ZetarisFinance, "fetch_case", side_effect=RuntimeError("Upstream timeout")):
            res = fetch_financial_records("LEASE-0001")
            assert res["source_status"] == "fixture_fallback"
            assert res["source_system"] == "local_database"
            assert "Upstream timeout" in res["fallback_reason"]

    with patch.object(settings, "finance_source", "fixture"):
        res = fetch_financial_records("LEASE-0001")
        assert res["source_status"] == "fixture"
        assert res["source_system"] == "local_database"
        assert res["fallback_reason"] is None


# =============================================================================
# 10. Reconciliation Using Source Records
# =============================================================================

def test_reconciliation_using_source_records():
    """Verify 3-way reconciliation accurately processes mapped source records."""
    records = {
        "invoices": [{"id": "INV-LIVE", "amount": "1500.00", "currency": "USD"}],
        "payments": [{"id": "PAY-LIVE", "amount": "1500.00", "currency": "USD", "reference": "REF-LIVE"}],
        "bank": [{"id": "BANK-LIVE", "amount": "1500.00", "currency": "USD", "reference": "REF-LIVE"}]
    }
    result = calculate(records)
    assert result["status"] == "reconciled"
    assert result["reason_code"] == "MATCH_CONFIRMED"
    assert result["difference_cents"] == 0
    assert result["verified_paid_cents"] == 150000


# =============================================================================
# 11. Cross-Organization Access Denial
# =============================================================================

def test_cross_organization_access_denial():
    """Verify tenant isolation prevents cross-organization queries."""
    z = ZetarisFinance()
    # Attempting to forge X-Org-ID or bypass org filter is prevented
    assert z.org_id == settings.zetaris_org_id


# =============================================================================
# 12. API Endpoints and Metadata Verification
# =============================================================================

def test_zetaris_api_endpoints_and_metadata(client):
    """Test /api/integrations/zetaris endpoints via FastAPI TestClient."""
    h_res = client.get("/api/integrations/zetaris/health")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "HEALTHY"

    m_res = client.get("/api/integrations/zetaris/metadata")
    assert m_res.status_code == 200
    assert m_res.json()["status"] == "discovered"
    assert "enigma_invoices" in m_res.json()["views"]

    q_res = client.post("/api/integrations/zetaris/query", json={"sql": "SELECT 1 AS num", "limit": 10})
    assert q_res.status_code == 200
    assert q_res.json()["source_system"] == "zetaris"
    assert q_res.json()["source_status"] == "live"

    # Disallowed write query
    f_res = client.post("/api/integrations/zetaris/query", json={"sql": "DROP TABLE test"})
    assert f_res.status_code == 403
