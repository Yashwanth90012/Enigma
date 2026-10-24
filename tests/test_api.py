"""Tests for FastAPI endpoints in app/main.py.

Verifies:
- Health check with pgvector & DB verification
- Portfolio financial summary aggregation
- Detailed lease list and filtering
- Single lease 360-degree bundle endpoint
- Approval / Escalation workflow
- World Model event and lineage endpoints
"""

# pyrefly: ignore[missing-import]
import pytest
# pyrefly: ignore[missing-import]
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_health_endpoint(client):
    resp = client.get('/health')
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'ok'
    assert data['database'] == 'connected'

def test_portfolio_summary_endpoint(client):
    resp = client.get('/api/portfolio/summary')
    assert resp.status_code == 200
    data = resp.json()
    assert 'total_leases' in data
    assert 'reconciled_count' in data
    assert 'total_rent_invoiced_usd' in data
    assert data['total_leases'] >= 100

def test_leases_list_endpoint(client):
    resp = client.get('/api/leases')
    assert resp.status_code == 200
    leases = resp.json()
    assert len(leases) >= 100
    first = leases[0]
    assert 'lease_id' in first
    assert 'tenant1' in first
    assert 'monthly_rent_usd' in first
    assert 'reconciliation_status' in first

def test_leases_filter_status(client):
    resp = client.get('/api/leases?status_filter=reconciled')
    assert resp.status_code == 200
    leases = resp.json()
    assert all(l['reconciliation_status'] == 'reconciled' for l in leases)

def test_lease_details_endpoint(client):
    resp = client.get('/api/lease/LEASE-0001/details')
    assert resp.status_code == 200
    data = resp.json()
    assert data['lease']['lease_id'] == 'LEASE-0001'
    assert 'work_orders' in data
    assert 'financial_records' in data
    assert 'reconciliation' in data

def test_investigate_endpoint(client):
    resp = client.post('/api/investigate', json={'lease_id': 'LEASE-0001'})
    assert resp.status_code == 200
    data = resp.json()
    assert data['case_id'] == 'LEASE-0001'
    assert 'result' in data
    assert 'recommendation' in data
    assert 'latest_state' in data

def test_world_endpoints(client):
    events_resp = client.get('/api/world/LEASE-0001')
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 1

    state_resp = client.get('/api/world/LEASE-0001/state')
    assert state_resp.status_code == 200
    state = state_resp.json()
    assert state['case_id'] == 'LEASE-0001'

    lineage_resp = client.get('/api/world/LEASE-0001/lineage')
    assert lineage_resp.status_code == 200
    lineage = lineage_resp.json()
    assert 'nodes' in lineage
    assert 'edges' in lineage

def test_approve_endpoint(client):
    resp = client.post(
        '/api/approve/LEASE-0002',
        json={
            'approved': True,
            'action': 'approved',
            'note': 'Verified against bank slip',
            'reviewer': 'Senior Auditor'
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['case_id'] == 'LEASE-0002'
    assert data['state'] == 'approved'

def test_saas_organizations(client):
    resp = client.get('/api/saas/organizations')
    assert resp.status_code == 200
    orgs = resp.json()
    assert len(orgs) >= 4
    assert any(o['id'] == 'ORG-APEX' for o in orgs)

    new_org = {
        'name': 'Cascade Mountain REIT',
        'portfolio_type': 'Mixed-Use Commercial',
        'contact_email': 'ops@cascadereit.com',
        'active_units': 150
    }
    create_resp = client.post('/api/saas/organizations', json=new_org)
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert 'id' in created
    assert created['name'] == 'Cascade Mountain REIT'

def test_saas_feature_requests(client):
    resp = client.get('/api/saas/feature-requests')
    assert resp.status_code == 200
    reqs = resp.json()
    assert len(reqs) >= 4

    new_req = {
        'org_id': 'ORG-APEX',
        'title': 'AI Cash Flow Variance Prediction Lane',
        'category': 'world_model',
        'priority': 'high',
        'specification': 'Predict 30-day ahead bank account float using historical invoice clearing DAGs.',
        'submitted_by': 'Portfolio Strategist'
    }
    create_resp = client.post('/api/saas/feature-requests', json=new_req)
    assert create_resp.status_code == 200
    created = create_resp.json()
    req_id = created['id']
    assert req_id.startswith('REQ-')

    vote_resp = client.post(f'/api/saas/feature-requests/{req_id}/upvote')
    assert vote_resp.status_code == 200
    assert vote_resp.json()['new_vote_count'] == 2

