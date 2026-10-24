"""Tests for Resident & Lease Lifecycle Workflows (Phase 2A).

Verifies:
1. Renewal eligibility and duplicate-offer prevention.
2. Lease expiration and renewal status transitions.
3. Move-in and move-out checklist lifecycle.
4. Resident-to-lease and organization ownership validation.
5. Unauthorized cross-organization access prevention (403 Forbidden).
6. Duplicate and failed notification handling with preferences.
7. Human approval requirements for contractual changes and closeout actions.
8. Regression behavior across existing lease, finance, and notification endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import db

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(autouse=True)
def cleanup_test_records():
    with db() as conn:
        conn.execute("DELETE FROM lease_renewals WHERE lease_id IN ('LEASE-0010', 'LEASE-0011', 'LEASE-0012', 'LEASE-0031')")
        conn.execute("DELETE FROM move_in_checklists WHERE lease_id IN ('LEASE-0020')")
        conn.execute("DELETE FROM move_out_records WHERE lease_id IN ('LEASE-0021', 'LEASE-0032')")
        conn.execute("UPDATE lease_records SET lease_status = 'active' WHERE lease_id IN ('LEASE-0010', 'LEASE-0011', 'LEASE-0012', 'LEASE-0020', 'LEASE-0021', 'LEASE-0031', 'LEASE-0032')")
    yield



# ---------------------------------------------------------------------------
# 1. Renewal eligibility and duplicate-offer prevention
# ---------------------------------------------------------------------------
def test_1_expiring_leases_and_renewal_eligibility(client):
    resp = client.get('/api/leases/renewals/expiring?window_days=90')
    assert resp.status_code == 200
    expiring = resp.json()
    assert isinstance(expiring, list)
    assert len(expiring) > 0

    lease_10 = next((item for item in expiring if item['lease_id'] == 'LEASE-0010'), None)
    assert lease_10 is not None
    assert lease_10['is_eligible_for_renewal'] is True
    assert lease_10['renewal_status'] in ('upcoming', 'not_started', 'offer_prepared')


def test_1b_prepare_renewal_offer_and_prevent_duplicate(client):
    # Prepare offer for LEASE-0010
    resp = client.post(
        '/api/leases/LEASE-0010/renewal/prepare',
        json={'proposed_increase_pct': 4.0, 'renewal_term_months': 12, 'prepared_by': 'Resident Agent'},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp.status_code == 200
    offer = resp.json()
    assert offer['lease_id'] == 'LEASE-0010'
    assert offer['status'] == 'offer_prepared'
    assert offer['proposed_increase_pct'] == 4.0
    assert offer['manager_approval_state'] == 'pending'
    assert offer['proposed_rent_usd'] > offer['current_rent_usd']

    # Attempt duplicate offer for the exact same renewal period
    resp_dup = client.post(
        '/api/leases/LEASE-0010/renewal/prepare',
        json={'proposed_increase_pct': 5.0, 'renewal_term_months': 12},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp_dup.status_code == 400
    assert "Duplicate offer prevented" in resp_dup.json()['detail']


# ---------------------------------------------------------------------------
# 2. Lease expiration and renewal status transitions
# ---------------------------------------------------------------------------
def test_2_renewal_status_transitions_lifecycle(client):
    # LEASE-0011: Prepare -> Resident Accept -> Manager Approve -> Finalized
    # 1. Prepare
    resp1 = client.post(
        '/api/leases/LEASE-0011/renewal/prepare',
        json={'proposed_increase_pct': 3.5, 'renewal_term_months': 12},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp1.status_code == 200
    assert resp1.json()['status'] == 'offer_prepared'

    # 2. Resident accepts offer
    resp2 = client.post(
        '/api/leases/LEASE-0011/renewal/decision',
        json={'decision': 'accepted', 'notes': 'Happy to renew!'},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp2.status_code == 200
    res_data = resp2.json()
    assert res_data['status'] == 'accepted'
    assert res_data['manager_approval_state'] == 'pending'

    # 3. Manager approves renewal
    resp3 = client.post(
        '/api/leases/LEASE-0011/renewal/approve',
        json={'manager_name': 'Sarah Connor', 'approved': True, 'notes': 'Approved 3.5% renewal'},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp3.status_code == 200
    final_data = resp3.json()
    assert final_data['status'] == 'finalized'
    assert final_data['approved_by'] == 'Sarah Connor'


def test_2b_resident_declines_renewal(client):
    # LEASE-0012: Prepare -> Resident Declines
    resp1 = client.post(
        '/api/leases/LEASE-0012/renewal/prepare',
        json={'proposed_increase_pct': 3.5, 'renewal_term_months': 12},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        '/api/leases/LEASE-0012/renewal/decision',
        json={'decision': 'declined', 'notes': 'Moving out of state.'},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp2.status_code == 200
    assert resp2.json()['status'] == 'declined'


# ---------------------------------------------------------------------------
# 3. Move-in and move-out checklist lifecycle
# ---------------------------------------------------------------------------
def test_3_move_in_checklist_lifecycle(client):
    # 1. Initiate move-in checklist for LEASE-0020
    resp = client.post(
        '/api/leases/LEASE-0020/move-in/initiate',
        json={'target_date': '2026-11-01'},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp.status_code == 200
    chk = resp.json()
    assert chk['lease_id'] == 'LEASE-0020'
    assert len(chk['tasks']) == 6
    assert chk['completed_tasks'] == 0
    assert chk['progress_percent'] == 0.0
    assert 'renters_insurance' in [t['task_key'] for t in chk['tasks']]

    # 2. Complete renter's insurance task
    resp_t1 = client.post(
        '/api/leases/LEASE-0020/move-in/tasks/renters_insurance/complete',
        json={'completed_by': 'Resident John', 'notes': 'Uploaded Lemonade policy #LEM-9921'},
        headers={'X-Organization-Id': 'ORG-APEX'}
    )
    assert resp_t1.status_code == 200
    updated = resp_t1.json()
    assert updated['completed_tasks'] == 1
    t1 = next(t for t in updated['tasks'] if t['task_key'] == 'renters_insurance')
    assert t1['is_completed'] is True
    assert t1['completed_by'] == 'Resident John'
    assert t1['completed_at'] is not None

    # 3. Complete all remaining tasks
    for key in ['government_id', 'deposit_settlement', 'pre_inspection', 'utility_transfer', 'key_handover']:
        client.post(
            f'/api/leases/LEASE-0020/move-in/tasks/{key}/complete',
            json={'completed_by': 'Staff Agent'},
            headers={'X-Organization-Id': 'ORG-APEX'}
        )
    
    final_chk = client.get('/api/leases/LEASE-0020/move-in', headers={'X-Organization-Id': 'ORG-APEX'}).json()
    assert final_chk['completed_tasks'] == 6
    assert final_chk['progress_percent'] == 100.0
    assert final_chk['status'] == 'completed'


def test_3b_move_out_checklist_lifecycle(client):
    # 1. Submit notice to vacate for LEASE-0021 (PROP-002 -> ORG-VERDANT)
    resp = client.post(
        '/api/leases/LEASE-0021/move-out/notice',
        json={
            'planned_move_out_date': '2026-11-30',
            'forwarding_address': '742 Evergreen Terrace, Springfield, OR',
            'resident_name': 'Resident Vacater'
        },
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )
    assert resp.status_code == 200
    mo = resp.json()
    assert mo['lease_id'] == 'LEASE-0021'
    assert mo['status'] == 'notice_received'
    assert mo['statutory_deadline_date'] == '2026-12-21' # 21 days after planned move-out date
    assert len(mo['tasks']) == 5

    # 2. Complete inspection and key return tasks
    resp_task = client.post(
        '/api/leases/LEASE-0021/move-out/tasks/key_return/complete',
        json={'completed_by': 'Property Manager Dave', 'notes': 'Returned 2 keys and 1 fob'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )
    assert resp_task.status_code == 200
    key_task = next(t for t in resp_task.json()['tasks'] if t['task_key'] == 'key_return')
    assert key_task['is_completed'] is True


# ---------------------------------------------------------------------------
# 4 & 5. Resident-to-lease and organization ownership validation & 403 access control
# ---------------------------------------------------------------------------
def test_4_and_5_organization_ownership_and_cross_tenant_isolation(client):
    # LEASE-0001 belongs to PROP-001 (ORG-APEX)
    # Valid org query:
    resp_valid = client.get('/api/leases/LEASE-0001/preferences', headers={'X-Organization-Id': 'ORG-APEX'})
    assert resp_valid.status_code == 200

    # Cross-tenant unauthorized access by ORG-VERDANT -> 403 Forbidden
    resp_unauthorized = client.get('/api/leases/LEASE-0001/preferences', headers={'X-Organization-Id': 'ORG-VERDANT'})
    assert resp_unauthorized.status_code == 403
    assert "Access denied" in resp_unauthorized.json()['detail']

    # Cross-tenant move-in access -> 403
    resp_mi_unauth = client.get('/api/leases/LEASE-0001/move-in', headers={'X-Organization-Id': 'ORG-VERDANT'})
    assert resp_mi_unauth.status_code == 403

    # Cross-tenant renewal access -> 403
    resp_ren_unauth = client.get('/api/leases/LEASE-0001/renewal', headers={'X-Organization-Id': 'ORG-BEACON'})
    assert resp_ren_unauth.status_code == 403


# ---------------------------------------------------------------------------
# 6. Duplicate and failed notification handling & communication preferences
# ---------------------------------------------------------------------------
def test_6_communication_preferences_and_duplicate_prevention(client):
    # Set preferences to enable email for LEASE-0030 (ORG-VERDANT)
    resp_pref = client.put(
        '/api/leases/LEASE-0030/preferences',
        json={'email': True, 'sms': False},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )
    assert resp_pref.status_code == 200

    # Send reminder -> queued
    rem1 = client.post(
        '/api/leases/LEASE-0030/notifications/remind',
        json={'reminder_type': 'renewal'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    ).json()
    assert rem1['status'] in ('queued', 'simulated') or 'notification_id' in rem1

    # Send duplicate reminder on same day -> prevented
    rem2 = client.post(
        '/api/leases/LEASE-0030/notifications/remind',
        json={'reminder_type': 'renewal'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    ).json()
    assert rem2['status'] == 'duplicate_prevented'

    # Now turn off email preferences (opt-out)
    client.put(
        '/api/leases/LEASE-0030/preferences',
        json={'email': False, 'sms': False},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )

    # Attempt sending reminder when opted out -> suppressed
    rem3 = client.post(
        '/api/leases/LEASE-0030/notifications/remind',
        json={'reminder_type': 'move_in'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    ).json()
    assert rem3['status'] == 'preference_suppressed'


# ---------------------------------------------------------------------------
# 7. Human approval requirements for contractual changes and closeout actions
# ---------------------------------------------------------------------------
def test_7_contractual_changes_require_human_approval(client):
    # 1. Fetch current rent for LEASE-0031 (ORG-VERDANT)
    with db() as conn:
        orig_rent = conn.execute("SELECT monthly_rent_usd FROM lease_records WHERE lease_id='LEASE-0031'").fetchone()[0]

    # 2. Prepare offer (+10%)
    client.post(
        '/api/leases/LEASE-0031/renewal/prepare',
        json={'proposed_increase_pct': 10.0, 'renewal_term_months': 12},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )

    # 3. Resident accepts
    client.post(
        '/api/leases/LEASE-0031/renewal/decision',
        json={'decision': 'accepted'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )

    # 4. Check that lease_records still has original rent (Contract not changed yet!)
    with db() as conn:
        mid_rent = conn.execute("SELECT monthly_rent_usd FROM lease_records WHERE lease_id='LEASE-0031'").fetchone()[0]
    assert float(mid_rent) == float(orig_rent)

    # 5. Manager formally approves
    appr_resp = client.post(
        '/api/leases/LEASE-0031/renewal/approve',
        json={'manager_name': 'Chief Portfolio Manager', 'approved': True},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )
    assert appr_resp.status_code == 200

    # 6. Now contract terms in lease_records are finalized and updated
    with db() as conn:
        final_rent = conn.execute("SELECT monthly_rent_usd FROM lease_records WHERE lease_id='LEASE-0031'").fetchone()[0]
    assert float(final_rent) > float(orig_rent)


def test_7b_move_out_deposit_closeout_requires_human_approval(client):
    # Setup move-out record for LEASE-0032 (ORG-VERDANT)
    client.post(
        '/api/leases/LEASE-0032/move-out/notice',
        json={'planned_move_out_date': '2026-11-15', 'forwarding_address': '123 New St, Austin TX'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )

    # Propose closeout with itemized deductions
    deductions = [
        {"category": "cleaning", "description": "Carpet deep steam cleaning", "amount_usd": 150.0, "evidence": "Exit photo #4"},
        {"category": "repair", "description": "Drywall patch living room", "amount_usd": 200.0, "evidence": "Inspection report"}
    ]
    prop_resp = client.post(
        '/api/leases/LEASE-0032/move-out/closeout/propose',
        json={'deductions': deductions},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )
    assert prop_resp.status_code == 200
    prop_data = prop_resp.json()
    assert prop_data['status'] == 'pending_closeout_approval'
    assert prop_data['closeout_approval_state'] == 'pending'

    # Lease must still be active/notice_received, NOT closed yet
    with db() as conn:
        status_before = conn.execute("SELECT lease_status FROM lease_records WHERE lease_id='LEASE-0032'").fetchone()[0]
    assert status_before != 'closed'

    # Formal Manager sign-off
    appr_resp = client.post(
        '/api/leases/LEASE-0032/move-out/closeout/approve',
        json={'manager_name': 'General Manager Lisa', 'notes': 'All deductions backed by contractor receipts.'},
        headers={'X-Organization-Id': 'ORG-VERDANT'}
    )
    assert appr_resp.status_code == 200
    appr_data = appr_resp.json()
    assert appr_data['status'] == 'closed'
    assert appr_data['closeout_approval_state'] == 'approved'
    assert appr_data['approved_by'] == 'General Manager Lisa'

    # Lease is now officially closed in ledger
    with db() as conn:
        status_after = conn.execute("SELECT lease_status FROM lease_records WHERE lease_id='LEASE-0032'").fetchone()[0]
    assert status_after == 'closed'


# ---------------------------------------------------------------------------
# 8. Regression tests across existing resident, lease, and finance endpoints
# ---------------------------------------------------------------------------
def test_8_existing_endpoints_regression(client):
    res1 = client.get('/api/leases')
    assert res1.status_code == 200
    assert len(res1.json()) >= 100

    res2 = client.get('/api/lease/LEASE-0001/details')
    assert res2.status_code == 200
    d = res2.json()
    assert 'lease' in d
    assert 'reconciliation' in d
    assert 'work_orders' in d

    res3 = client.get('/api/notifications')
    assert res3.status_code == 200
    assert isinstance(res3.json(), list)
