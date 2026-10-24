"""Conformance and behavior tests for Meterless World Model integration.

Verifies:
- Canonical stable entity identifier conventions
- Append-only event store integrity
- Monotonic versioning per case
- Deterministic event replay & derived latest state projection
- Causal lineage graph construction
- Context builder structure for autonomous agents
"""

from app.world_model import (
    canonical_id, parse_canonical_id, record_event, get_events,
    get_latest_state, get_lineage, build_agent_context, replay_events_for_state
)
from app.database import db

def test_canonical_id_generation():
    assert canonical_id('lease', 'LEASE-0001') == 'lease:LEASE-0001'
    assert canonical_id('property', 'PROP-001') == 'property:PROP-001'
    assert canonical_id('tenant', 'Skyler Price') == 'tenant:skyler-price'
    assert canonical_id('invoice', 'INV-0001') == 'invoice:INV-0001'
    assert canonical_id('payment', 'PAY-0001') == 'payment:PAY-0001'
    assert canonical_id('bank', 'BANK-0001') == 'bank:BANK-0001'
    assert canonical_id('work_order', 'WO-0001') == 'work_order:WO-0001'
    assert canonical_id('case', 'LEASE-0001') == 'case:LEASE-0001'

def test_parse_canonical_id():
    etype, raw = parse_canonical_id('lease:LEASE-0042')
    assert etype == 'lease'
    assert raw == 'LEASE-0042'

def test_event_sourcing_and_versioning():
    test_case = 'LEASE-9999'
    e1 = record_event(test_case, test_case, 'case_opened', {'question': 'Test conformance'})
    assert e1 is not None

    e2 = record_event(test_case, test_case, 'finance_calculated', {
        'status': 'reconciled',
        'currency': 'USD',
        'invoice_cents': 200000,
        'verified_paid_cents': 200000,
        'difference_cents': 0
    }, caused_by=[e1])
    assert e2 is not None

    events = get_events(test_case)
    assert len(events) >= 2
    assert events[-1]['version'] > events[-2]['version']
    assert events[-1]['caused_by'] == [e1]

def test_derived_state_replay():
    test_case = 'LEASE-9999'
    state = get_latest_state(test_case)
    assert state['case_id'] == test_case
    assert state['canonical_id'] == f'case:{test_case}'
    assert state['status'] == 'reconciled'
    assert state['invoice_cents'] == 200000
    assert state['difference_cents'] == 0

def test_causal_lineage_dag():
    test_case = 'LEASE-9999'
    lineage = get_lineage(test_case)
    assert lineage['case_id'] == test_case
    assert len(lineage['nodes']) >= 2
    assert len(lineage['edges']) >= 1
    # Check that caused_by edge exists
    assert any(edge['type'] == 'caused_by' for edge in lineage['edges'])

def test_context_builder_structure():
    ctx = build_agent_context('LEASE-0001', 'Why is this rent unpaid?')
    assert ctx['case_id'] == 'LEASE-0001'
    assert 'lease' in ctx
    assert 'latest_state' in ctx
    assert 'work_orders' in ctx
    assert ctx['lease']['lease_id'] == 'LEASE-0001'
