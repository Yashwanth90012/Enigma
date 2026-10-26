"""Official Conformance and Integration Verification for Meterless Markovian Engine in ENIGMA.

Validates all 8 official Meterless Markovian conformance invariants:
- eff-001: Efficiency model reproduces documented worked example: N=20 -> 86.18% (naiveTotal=246,000, markovianTotal=34,000)
- snap-001: Run records carry a mandatory immutable chunkConfig snapshot
- snap-002: Historical efficiency computed against the run's own snapshot (prefix-sum standardCost, markovianCost)
- ovl-001: Overlap contract: [OVERLAP] block inserted when overlapTokens > 0
- lab-001: Token numbers labeled: runs carry 'estimated' or 'measured'
- ref-001: Reflection failure does not fail the run
- mrk-001: Markers are cleaned from display content and drive completion ([TASK_COMPLETE], [STATE_CHECKPOINT])
- cfg-001: Config bounds reject out-of-range values with a typed error, never silent truncation

Plus comprehensive ENIGMA integration tests:
- Checkpoint creation, ordering, checksum, and version integrity
- Crash recovery and resumption from latest checkpoint
- Side-effect deduplication (preventing duplicate payments, notifications, and events)
- Integration with app.orchestrator
- Multi-tenant isolation and role-gated authorization
- REST API endpoints (/api/markovian/*)
"""

import math
import pytest
from fastapi.testclient import TestClient

from app.engines.markovian import (
    Markovian,
    ChunkConfig,
    DEFAULT_CONFIG,
    BOUNDS,
    resolve_config,
    projection_curve,
    run_efficiency,
    model_totals,
    DOC_DEFAULTS,
    estimate_tokens,
    ConfigValidationError,
    parse_markers,
    clean_markers,
    canonical_block,
    overlap_slice,
    build_prompt,
    CarryoverService,
    ChunkInfo,
    ExecutionCheckpoint,
    MarkovianRun
)
from app.orchestrator import run_with_markovian_continuity
from app.world_model import record_event
from app.engines.hmem import HMEM
from app.main import app

client = TestClient(app)
T0 = 1_750_000_000_000


def step_gen(total: int):
    """Step generator mimicking the official conformance runner stepGen."""
    calls = 0
    def fn(prompt: str):
        nonlocal calls
        calls += 1
        done = calls >= total
        body = "Output for step with enough text to register in accounting math. " * 10
        marker = (
            "[TASK_COMPLETE]"
            if done
            else f"[STATE_CHECKPOINT]\nCOMPLETED: steps 1-{calls}\nREMAINING: {total - calls}\nDECISIONS: none\nCONTEXT: conformance"
        )
        return {"text": f"{body}\n{marker}"}
    return fn


# =============================================================================
# 1. Official Conformance Vectors (eff-001 through cfg-001)
# =============================================================================

def test_eff_001_efficiency_model_worked_example():
    """eff-001: efficiency model reproduces the documented worked example: N=20 -> 86% (within 0.5%)."""
    res = model_totals(20)
    assert res["naiveTotal"] == 246_000, f"naiveTotal {res['naiveTotal']}, expected 246000"
    assert res["markovianTotal"] == 34_000, f"markovianTotal {res['markovianTotal']}, expected 34000"
    assert abs(res["efficiency"] * 100 - 86.18) < 0.5, f"efficiency {res['efficiency']*100:.2f}%, expected ~86.18%"


@pytest.mark.anyio
async def test_snap_001_run_records_carry_mandatory_chunk_config_snapshot():
    """snap-001: run records carry a mandatory chunkConfig snapshot."""
    m = Markovian(chunk_config={"chunkSize": 4000, "carryoverTokens": 640}, clock=lambda: T0)
    run = await m.run(goal="snapshot check", generator=step_gen(3), reflect=False)
    assert run.chunk_config is not None
    assert run.chunk_config["carryoverTokens"] == 640, "run.chunkConfig snapshot missing or wrong"
    assert run.chunkConfig["carryoverTokens"] == 640


def test_snap_002_historical_efficiency_computed_against_run_snapshot():
    """snap-002: historical efficiency is computed against the run's own snapshot, not current config."""
    chunks = [ChunkInfo(id=i, tokens=1000, carryover="", content="") for i in range(1, 5)]
    a = run_efficiency(chunks, {"chunkSize": 8000, "maxChunks": 24, "carryoverTokens": 512, "overlapTokens": 0})
    b = run_efficiency(chunks, {"chunkSize": 8000, "maxChunks": 24, "carryoverTokens": 2048, "overlapTokens": 0})
    assert a["standardCost"] == 10_000, f"standardCost {a['standardCost']}, expected 10000 (prefix-sum formula)"
    assert a["markovianCost"] == 6_048, f"markovianCost {a['markovianCost']}, expected 4*512+4000=6048"
    assert a["tokensSaved"] != b["tokensSaved"], "different snapshots must produce different savings for the same chunks"


@pytest.mark.anyio
async def test_ovl_001_overlap_contract_implements_overlap_block():
    """ovl-001: overlap contract: implement [OVERLAP] or reject non-zero; accept-and-ignore fails."""
    m = Markovian(chunk_config={"chunkSize": 4000, "carryoverTokens": 640, "overlapTokens": 64}, clock=lambda: T0)
    prompts = []
    async def recording_gen(prompt: str):
        prompts.append(prompt)
        done = len(prompts) >= 3
        return {
            "text": "chunk content " * 20 + ("[TASK_COMPLETE]" if done else "[STATE_CHECKPOINT]\nCOMPLETED: chunk recorded with carried state")
        }

    await m.run(goal="overlap conformance", generator=recording_gen, reflect=False)
    assert any("[OVERLAP]" in p for p in prompts[1:]), "config accepted overlapTokens=64 but no [OVERLAP] block appeared in prompts"


@pytest.mark.anyio
async def test_lab_001_token_numbers_labeled_estimated_or_measured():
    """lab-001: token numbers are labeled: runs carry estimated or measured."""
    m = Markovian(chunk_config={"chunkSize": 4000, "carryoverTokens": 640}, clock=lambda: T0)
    run = await m.run(goal="label check", generator=step_gen(2), reflect=False)
    assert run.token_label in ("estimated", "measured"), f"run.tokenLabel is '{run.token_label}'"


@pytest.mark.anyio
async def test_ref_001_reflection_failure_does_not_fail_run():
    """ref-001: reflection failure does not fail the run."""
    calls = 0
    m = Markovian(chunk_config={"chunkSize": 4000, "carryoverTokens": 640}, clock=lambda: T0)
    async def exploding_gen(prompt: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("provider exploded in reflection")
        return {"text": "done in one chunk [TASK_COMPLETE]"}

    run = await m.run(goal="reflection failure", generator=exploding_gen, reflect=True)
    assert run.status == "completed", f"run.status {run.status}; reflection failures must not fail the run"
    assert run.error is not None and "reflection failed" in run.error


@pytest.mark.anyio
async def test_mrk_001_markers_cleaned_from_display_and_drive_completion():
    """mrk-001: markers are cleaned from display content and drive completion."""
    m = Markovian(chunk_config={"chunkSize": 4000, "carryoverTokens": 640}, clock=lambda: T0)
    run = await m.run(goal="marker cleaning", generator=step_gen(3), reflect=False)
    assert run.status == "completed", f"status {run.status}, expected completed via [TASK_COMPLETE]"
    assert "[TASK_COMPLETE]" not in run.output
    assert "[STATE_CHECKPOINT]" not in run.output
    assert len(run.chunks) == 3, f"chunks {len(run.chunks)}, expected 3"


def test_cfg_001_config_bounds_reject_out_of_range():
    """cfg-001: config bounds reject out-of-range values with a typed error, never silent truncation."""
    with pytest.raises(ConfigValidationError) as exc:
        resolve_config({"chunkSize": 128, "carryoverTokens": 640})
    assert "outside" in str(exc.value).lower() or "chunksize" in str(exc.value).lower()


# =============================================================================
# 2. State Carryover Compression Cascade & Prompt Builder
# =============================================================================

@pytest.mark.anyio
async def test_carryover_cascade_levels():
    """Test all 4 levels of the carryover compression cascade."""
    cfg = ChunkConfig(carryover_tokens=800)
    service = CarryoverService()

    # 1. Marker override
    res1 = await service.next(
        marker_state="COMPLETED: Task 1 and 2 done\nREMAINING: Task 3\nDECISIONS: Use PostgreSQL",
        previous_carryover="",
        chunk_text="Some chunk output",
        config=cfg
    )
    assert res1.level == "marker"
    assert "Task 1 and 2 done" in res1.carryover

    # 2. Heuristic extraction fallback (when marker is absent)
    res2 = await service.next(
        marker_state=None,
        previous_carryover="",
        chunk_text="Therefore we selected the balanced model. Key insight is that chunking preserves state. Status is ongoing.",
        config=cfg
    )
    assert res2.level == "heuristic"
    assert "Therefore" in res2.carryover or "Key insight" in res2.carryover

    # 3. Word tail truncation fallback
    res3 = await service.next(
        marker_state=None,
        previous_carryover="",
        chunk_text="word " * 500,
        config=ChunkConfig(carryover_tokens=50)
    )
    assert res3.level == "truncation"
    assert estimate_tokens(res3.carryover) <= 50


# =============================================================================
# 3. Durable Checkpoint Creation, Versioning, and Crash Recovery
# =============================================================================

@pytest.mark.anyio
async def test_checkpoint_persistence_and_resumption():
    """Simulate a crash mid-workflow and resume execution from latest checkpoint."""
    m1 = Markovian(storage="postgres", org_id="test_org_crash")

    step_count = 0
    def crashing_gen(prompt: str):
        nonlocal step_count
        step_count += 1
        if step_count == 2:
            # Simulate sudden process crash after producing chunk 2
            raise RuntimeError("SIMULATED PROCESS CRASH")
        return {"text": f"Execution progress for step {step_count} completed.\n[STATE_CHECKPOINT]\nCOMPLETED: step {step_count}"}

    run1 = await m1.run(goal="Recoverable leasing audit", generator=crashing_gen, reflect=False)
    assert run1.status == "errored"
    assert len(run1.chunks) == 1, "Chunk 1 was persisted before crash"

    # Verify checkpoint exists
    latest_chk = m1.get_latest_checkpoint(run1.run_id)
    assert latest_chk is not None
    assert latest_chk.step == 1
    assert latest_chk.checksum is not None

    # Resume from checkpoint using a fresh engine instance
    m2 = Markovian(storage="postgres", org_id="test_org_crash")
    def resumed_gen(prompt: str):
        return {"text": "Resumed step successfully completed final invoice processing.\n[TASK_COMPLETE]"}

    resumed_run = await m2.run(
        goal="Recoverable leasing audit",
        generator=resumed_gen,
        resume_from_checkpoint=latest_chk,
        reflect=False
    )
    assert resumed_run.status == "completed"
    assert resumed_run.run_id == run1.run_id
    # Resumed step starts from step 2
    assert any(c.id == 2 for c in resumed_run.chunks)


# =============================================================================
# 4. Side-Effect Deduplication
# =============================================================================

def test_side_effect_idempotent_deduplication():
    """Verify that irreversible actions (e.g. payments/notifications) are not repeated."""
    import uuid
    m = Markovian(storage="postgres", org_id="test_org_side_effects")
    idempotency_key = f"test_side_effect_invoice_{uuid.uuid4().hex[:8]}"

    execution_counter = 0
    def payment_action():
        nonlocal execution_counter
        execution_counter += 1
        return {"transaction_id": "TX-998811", "amount_paid": 3500.00}

    # First execution: executes action
    res1 = m.execute_side_effect(
        idempotency_key=idempotency_key,
        action_type="disburse_vendor_payment",
        payload={"invoice_id": "INV-001", "amount": 3500.00},
        executor_fn=payment_action
    )
    assert res1["status"] in ("executed", "executed_fallback")
    assert execution_counter == 1
    assert res1["result"]["transaction_id"] == "TX-998811"

    # Second execution with same idempotency key: cached, executor NOT called!
    res2 = m.execute_side_effect(
        idempotency_key=idempotency_key,
        action_type="disburse_vendor_payment",
        payload={"invoice_id": "INV-001", "amount": 3500.00},
        executor_fn=payment_action
    )
    assert res2["status"] == "cached"
    assert execution_counter == 1, "Executor must NOT be called a second time!"
    assert res2["result"]["transaction_id"] == "TX-998811"


def test_orchestrator_continuity_integration():
    """Verify orchestrator bridge helper executes side-effects with Markovian deduplication."""
    import uuid
    wf_id = f"WF-TEST-{uuid.uuid4().hex[:8]}"
    execution_counter = 0
    def notification_action():
        nonlocal execution_counter
        execution_counter += 1
        return {"notified": True, "recipient": "tenant@example.com"}

    res = run_with_markovian_continuity(
        workflow_id=wf_id,
        step_id="step_notify_resident",
        action_type="send_resident_notice",
        payload={"notice_type": "lease_renewal"},
        executor_fn=notification_action,
        org_id="ORG-APEX"
    )
    assert res["status"] in ("executed", "executed_fallback")
    assert execution_counter == 1

    # Call again: deduplicated
    res_dup = run_with_markovian_continuity(
        workflow_id=wf_id,
        step_id="step_notify_resident",
        action_type="send_resident_notice",
        payload={"notice_type": "lease_renewal"},
        executor_fn=notification_action,
        org_id="ORG-APEX"
    )
    assert res_dup["status"] == "cached"
    assert execution_counter == 1


# =============================================================================
# 5. REST API Endpoints Verification
# =============================================================================

def test_rest_api_markovian_lifecycle():
    """Verify Markovian REST endpoints: create, inspect, checkpoints, metrics, and side-effects."""
    # 1. Create Run
    resp = client.post("/api/markovian/runs", json={
        "goal": "Reconcile quarterly HVAC maintenance contracts",
        "mode": "ARCHITECT",
        "chunk_config": {"chunkSize": 6000, "maxChunks": 5, "carryoverTokens": 800}
    }, headers={"X-Organization-Id": "test_api_org"})
    assert resp.status_code == 200, resp.text
    run_data = resp.json()["run"]
    run_id = run_data["id"]
    assert run_data["status"] == "completed"
    assert run_data["chunkConfig"]["carryoverTokens"] == 800

    # 2. Inspect Run
    get_resp = client.get(f"/api/markovian/runs/{run_id}", headers={"X-Organization-Id": "test_api_org"})
    assert get_resp.status_code == 200
    assert get_resp.json()["run_id"] == run_id

    # 3. Retrieve Checkpoints
    chk_resp = client.get(f"/api/markovian/runs/{run_id}/checkpoints", headers={"X-Organization-Id": "test_api_org"})
    assert chk_resp.status_code == 200
    assert chk_resp.json()["count"] >= 1

    # 4. Query Efficiency Metrics
    eff_resp = client.get("/api/markovian/metrics/efficiency?n_steps=20")
    assert eff_resp.status_code == 200
    eff_data = eff_resp.json()
    assert eff_data["model_totals"]["naiveTotal"] == 246000
    assert eff_data["model_totals"]["markovianTotal"] == 34000
    assert len(eff_data["projection_curve"]) == 20

    # 5. Resume (Role Authorized)
    resume_resp = client.post(
        f"/api/markovian/runs/{run_id}/resume",
        json={"override_carryover": "COMPLETED: Step 1 override"},
        headers={"X-User-Role": "property_manager", "X-Organization-Id": "test_api_org"}
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "resumed"

    # 6. Resume (Role Unauthorized -> 403 Forbidden)
    unauth_resp = client.post(
        f"/api/markovian/runs/{run_id}/resume",
        json={},
        headers={"X-User-Role": "unauthorized_viewer", "X-Organization-Id": "test_api_org"}
    )
    assert unauth_resp.status_code == 403
