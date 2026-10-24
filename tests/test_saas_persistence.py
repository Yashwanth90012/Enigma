import uuid
import pytest
from app.database import db
from app.saas import (
    list_organizations, onboard_organization,
    list_feature_requests, submit_feature_request,
    upvote_feature_request, OnboardCustomerRequest, SubmitFeatureRequest
)

def test_organization_persistence_across_fresh_connections():
    uid = uuid.uuid4().hex[:6].upper()
    org_name = f"Apex Horizon {uid}"
    req = OnboardCustomerRequest(
        name=org_name,
        portfolio_type="Residential Multifamily",
        tier="Enterprise Cloud",
        contact_email=f"ops-{uid.lower()}@apexhorizon.com",
        active_units=120
    )
    created = onboard_organization(req)
    org_id = created["id"]
    assert org_id.startswith("ORG-")

    # Verify directly from fresh database connection
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, active_units, contact_email FROM organizations WHERE id = %s",
            (org_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == org_id
        assert row[1] == org_name
        assert row[2] == 120

    # Verify through list_organizations API
    orgs = list_organizations()
    matching = [o for o in orgs if o["id"] == org_id]
    assert len(matching) == 1
    assert matching[0]["name"] == org_name

def test_feature_request_persistence_and_relationships():
    uid = uuid.uuid4().hex[:6].upper()
    org_req = OnboardCustomerRequest(
        name=f"Pacific Crest {uid}",
        contact_email=f"pm-{uid.lower()}@pacificcrest.com"
    )
    org = onboard_organization(org_req)
    org_id = org["id"]

    feat_req = SubmitFeatureRequest(
        org_id=org_id,
        title=f"Automated Utility Allocation {uid}",
        category="tenant_ar",
        priority="high",
        specification="Submeter utility bill splitting per Section 8 addendum.",
        submitted_by="Asset Manager"
    )
    created_fr = submit_feature_request(feat_req)
    req_id = created_fr["id"]
    assert req_id.startswith("REQ-")
    assert created_fr["votes"] == 1

    # Verify in DB
    with db() as conn:
        fr_row = conn.execute(
            "SELECT id, org_id, org_name, title, category, votes FROM feature_requests WHERE id = %s",
            (req_id,)
        ).fetchone()
        assert fr_row is not None
        assert fr_row[0] == req_id
        assert fr_row[1] == org_id
        assert fr_row[2] == org["name"]
        assert fr_row[5] == 1

    # Verify filtering by org_id
    org_reqs = list_feature_requests(org_id=org_id)
    assert any(r["id"] == req_id for r in org_reqs)

def test_upvote_persistence_and_duplicate_vote_protection():
    uid = uuid.uuid4().hex[:6].upper()
    org_req = OnboardCustomerRequest(
        name=f"Beacon Capital {uid}",
        contact_email=f"admin-{uid.lower()}@beacon.com"
    )
    org = onboard_organization(org_req)
    org_id = org["id"]

    feat_req = SubmitFeatureRequest(
        org_id=org_id,
        title=f"Real-Time Clearing Webhook {uid}",
        category="aws_infra",
        priority="critical_blocker",
        specification="Instantaneous AWS SQS triggers for cleared checks.",
        submitted_by="Senior Controller"
    )
    created_fr = submit_feature_request(feat_req)
    req_id = created_fr["id"]
    initial_votes = created_fr["votes"]

    # First upvote by voter A
    voter_a = f"voter-user-a-{uid}"
    res1 = upvote_feature_request(req_id, voter_id=voter_a)
    assert res1["status"] == "ok"
    assert res1["new_vote_count"] == initial_votes + 1

    # Duplicate upvote attempt by voter A
    res2 = upvote_feature_request(req_id, voter_id=voter_a)
    assert res2["status"] == "duplicate_prevented"
    assert res2["new_vote_count"] == initial_votes + 1

    # Verify count in DB did NOT increase on duplicate vote
    with db() as conn:
        db_votes = conn.execute("SELECT votes FROM feature_requests WHERE id = %s", (req_id,)).fetchone()[0]
        assert db_votes == initial_votes + 1

    # Distinct upvote by voter B should succeed
    voter_b = f"voter-user-b-{uid}"
    res3 = upvote_feature_request(req_id, voter_id=voter_b)
    assert res3["status"] == "ok"
    assert res3["new_vote_count"] == initial_votes + 2


def test_concurrent_upvotes_and_duplicate_vote_protection():
    """Verify that multiple concurrent threads attempting to vote for the same voter cannot duplicate votes."""
    import concurrent.futures
    uid = uuid.uuid4().hex[:6].upper()
    org = onboard_organization(OnboardCustomerRequest(
        name=f"Concurrent Test Org {uid}",
        contact_email=f"concurrent-{uid.lower()}@test.com"
    ))
    fr = submit_feature_request(SubmitFeatureRequest(
        org_id=org["id"],
        title=f"Concurrent Vote Test {uid}",
        specification="Stress test race-free atomic vote deduplication."
    ))
    req_id = fr["id"]
    initial_votes = fr["votes"]

    # 1. 10 concurrent threads voting with the EXACT SAME voter_id
    shared_voter = f"shared-voter-{uid}"
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(upvote_feature_request, req_id, voter_id=shared_voter) for _ in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    ok_count = sum(1 for r in results if r["status"] == "ok")
    dup_count = sum(1 for r in results if r["status"] == "duplicate_prevented")
    assert ok_count == 1, f"Expected exactly 1 successful vote, got {ok_count}"
    assert dup_count == 9, f"Expected exactly 9 duplicate-prevented responses, got {dup_count}"

    with db() as conn:
        final_votes = conn.execute("SELECT votes FROM feature_requests WHERE id = %s", (req_id,)).fetchone()[0]
        assert final_votes == initial_votes + 1

    # 2. 10 concurrent threads voting with DISTINCT voter_ids
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(upvote_feature_request, req_id, voter_id=f"distinct-voter-{i}-{uid}") for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    ok_distinct = sum(1 for r in results if r["status"] == "ok")
    assert ok_distinct == 10

    with db() as conn:
        final_votes_distinct = conn.execute("SELECT votes FROM feature_requests WHERE id = %s", (req_id,)).fetchone()[0]
        assert final_votes_distinct == initial_votes + 1 + 10


def test_foreign_key_validation_and_cascade():
    """Verify that submitting for an invalid org fails cleanly, and deleting an org cascades."""
    uid = uuid.uuid4().hex[:6].upper()
    
    # Submitting for non-existent org must raise ValueError cleanly
    with pytest.raises(ValueError, match="Organization 'ORG-NONEXISTENT' not found"):
        submit_feature_request(SubmitFeatureRequest(
            org_id="ORG-NONEXISTENT",
            title=f"Orphan FR {uid}",
            specification="This should fail foreign key validation."
        ))

    # Create real org and request, then verify cascade on delete
    org = onboard_organization(OnboardCustomerRequest(
        name=f"Cascade Test {uid}",
        contact_email=f"cascade-{uid.lower()}@test.com"
    ))
    org_id = org["id"]
    fr = submit_feature_request(SubmitFeatureRequest(
        org_id=org_id,
        title=f"Cascade FR {uid}",
        specification="Should be deleted when parent org is deleted."
    ))
    req_id = fr["id"]
    upvote_feature_request(req_id, voter_id=f"voter-cascade-{uid}")

    # Delete parent org
    with db() as conn:
        conn.execute("DELETE FROM organizations WHERE id = %s", (org_id,))

    # Verify child feature_request and votes were cascade deleted
    with db() as conn:
        fr_exists = conn.execute("SELECT COUNT(*) FROM feature_requests WHERE id = %s", (req_id,)).fetchone()[0]
        votes_exist = conn.execute("SELECT COUNT(*) FROM feature_request_votes WHERE request_id = %s", (req_id,)).fetchone()[0]
        assert fr_exists == 0
        assert votes_exist == 0


def test_database_initialization_seed_idempotency():
    """Verify calling init_database multiple times does not duplicate or reset existing data."""
    from app.database import init_database
    
    # Initial count
    orgs_before = list_organizations()
    frs_before = list_feature_requests()
    
    # Run init_database multiple times
    init_database()
    init_database()
    
    orgs_after = list_organizations()
    frs_after = list_feature_requests()
    
    assert len(orgs_after) == len(orgs_before)
    assert len(frs_after) == len(frs_before)

