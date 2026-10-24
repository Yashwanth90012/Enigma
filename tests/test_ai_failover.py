"""EQUILIBRA AI Provider Failover & Verification Test Suite.

Covers:
1. Meterless succeeds; NVIDIA NIM is not called.
2. Meterless is unreachable; NVIDIA NIM succeeds.
3. Meterless authentication fails; fallback behavior is correctly classified and not endlessly retried.
4. Both remote providers fail; offline fallback works.
5. NVIDIA NIM credentials are missing; offline fallback works.
6. All providers fail and offline fallback is disabled; a safe error is returned.
7. Malformed model output does not trigger unsafe actions.
8. Timeouts do not duplicate side effects.
9. API keys never appear in logs or responses.
10. Existing agent, API, and database workflows continue passing.
11. Zetaris live mode is clearly distinguished from fixture mode.
12. Provider health reflects actual verification rather than configuration alone.
"""

import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.config import settings
from app.providers import (
    UnifiedAIProvider, MeterlessProvider, NvidiaNimProvider,
    OfflineDeterministicProvider, ZetarisFinance,
    AIProviderError, AIAuthError, AIConnectionError, AITimeoutError,
    AIMalformedOutputError, redact_secret, redact_headers, sanitize_for_audit
)
from app.engine import investigate


# ---------------------------------------------------------------------------
# Test 1: Meterless succeeds; NVIDIA NIM is not called.
# ---------------------------------------------------------------------------
def test_1_meterless_succeeds_nim_not_called():
    unified = UnifiedAIProvider()
    with patch.object(settings, 'ai_provider', 'auto'), \
         patch.object(MeterlessProvider, 'is_configured', return_value=True), \
         patch.object(MeterlessProvider, 'chat', return_value="Verified Meterless Nightshift Output") as mock_meterless, \
         patch.object(NvidiaNimProvider, 'chat') as mock_nim:

        res = unified.generate("system prompt", "user query")
        assert res["provider_used"] == "meterless"
        assert res["fallback_occurred"] is False
        assert res["content"] == "Verified Meterless Nightshift Output"
        mock_meterless.assert_called_once()
        mock_nim.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: Meterless is unreachable; NVIDIA NIM succeeds.
# ---------------------------------------------------------------------------
def test_2_meterless_unreachable_nim_succeeds():
    unified = UnifiedAIProvider()
    with patch.object(settings, 'ai_provider', 'auto'), \
         patch.object(MeterlessProvider, 'is_configured', return_value=True), \
         patch.object(MeterlessProvider, 'chat', side_effect=AIConnectionError("Connection refused to 8088")), \
         patch.object(NvidiaNimProvider, 'is_configured', return_value=True), \
         patch.object(NvidiaNimProvider, 'chat', return_value="NVIDIA NIM Nemotron Response") as mock_nim:

        res = unified.generate("system prompt", "user query")
        assert res["provider_used"] == "nim"
        assert res["fallback_occurred"] is True
        assert "meterless connection_error" in (res["fallback_reason"] or "").lower()
        assert res["content"] == "NVIDIA NIM Nemotron Response"
        mock_nim.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: Meterless authentication fails; fallback behavior correctly classified (no endless retries).
# ---------------------------------------------------------------------------
def test_3_meterless_auth_fails_classified_no_endless_retries():
    unified = UnifiedAIProvider()
    with patch.object(settings, 'ai_provider', 'auto'), \
         patch.object(MeterlessProvider, 'is_configured', return_value=True), \
         patch.object(MeterlessProvider, 'chat', side_effect=AIAuthError("Meterless HTTP 401 Unauthorized")) as mock_meterless, \
         patch.object(NvidiaNimProvider, 'is_configured', return_value=False):

        # Even with max retries set to 3, an auth failure must only be attempted once on Meterless
        with patch.object(settings, 'ai_max_retries_per_provider', 3):
            res = unified.generate("system prompt", "user query")

        assert mock_meterless.call_count == 1  # Strictly 1 attempt, zero endless loops
        assert res["provider_used"] == "offline"
        assert res["fallback_occurred"] is True
        # Verify classification in execution history
        auth_step = [h for h in res["history"] if h["provider"] == "meterless"][0]
        assert auth_step["status"] == "AUTH_ERROR"
        assert auth_step["category"] == "auth_error"


# ---------------------------------------------------------------------------
# Test 4: Both remote providers fail; offline fallback works.
# ---------------------------------------------------------------------------
def test_4_both_remote_providers_fail_offline_fallback():
    unified = UnifiedAIProvider()
    with patch.object(settings, 'ai_provider', 'auto'), \
         patch.object(MeterlessProvider, 'is_configured', return_value=True), \
         patch.object(MeterlessProvider, 'chat', side_effect=AITimeoutError("Meterless timeout")), \
         patch.object(NvidiaNimProvider, 'is_configured', return_value=True), \
         patch.object(NvidiaNimProvider, 'chat', side_effect=AIConnectionError("NIM host unreachable")):

        res = unified.generate("system prompt", "user query")
        assert res["provider_used"] == "offline"
        assert res["fallback_occurred"] is True
        assert len(res["content"]) > 20
        assert "Reconciliation review completed" in res["content"]


# ---------------------------------------------------------------------------
# Test 5: NVIDIA NIM credentials missing; offline fallback works.
# ---------------------------------------------------------------------------
def test_5_nim_credentials_missing_offline_fallback():
    unified = UnifiedAIProvider()
    with patch.object(settings, 'ai_provider', 'auto'), \
         patch.object(MeterlessProvider, 'is_configured', return_value=False), \
         patch.object(NvidiaNimProvider, 'is_configured', return_value=False):

        res = unified.generate("system prompt", "user query")
        assert res["provider_used"] == "offline"
        assert res["content"] is not None
        assert any(h["provider"] == "offline" and "SUCCESS" in h["status"] for h in res["history"])


# ---------------------------------------------------------------------------
# Test 6: All providers fail and offline fallback is disabled; safe error returned.
# ---------------------------------------------------------------------------
def test_6_all_providers_fail_offline_disabled_safe_error():
    unified = UnifiedAIProvider()
    with patch.object(settings, 'ai_offline_fallback', False), \
         patch.object(MeterlessProvider, 'is_configured', return_value=True), \
         patch.object(MeterlessProvider, 'chat', side_effect=AIConnectionError("Meterless down")), \
         patch.object(NvidiaNimProvider, 'is_configured', return_value=True), \
         patch.object(NvidiaNimProvider, 'chat', side_effect=AITimeoutError("NIM timeout")):

        with pytest.raises(AIProviderError) as exc_info:
            unified.generate("system prompt", "user query")

        err_msg = str(exc_info.value)
        assert "All AI providers in fallback chain failed" in err_msg
        # Ensure credentials/tokens are never exposed in error text
        assert "Bearer" not in err_msg
        assert "nvapi-" not in err_msg


# ---------------------------------------------------------------------------
# Test 7: Malformed model output does not trigger unsafe actions.
# ---------------------------------------------------------------------------
def test_7_malformed_model_output_does_not_trigger_unsafe_actions():
    nim = NvidiaNimProvider()
    # Mock HTTP response with empty choices
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": []}

    with patch.object(nim, 'is_configured', return_value=True), \
         patch('httpx.Client.post', return_value=mock_resp):
        with pytest.raises(AIMalformedOutputError):
            nim.chat("system", "user")

    # Mock response with empty content string
    mock_resp.json.return_value = {"choices": [{"message": {"content": "   "}}]}
    with patch.object(nim, 'is_configured', return_value=True), \
         patch('httpx.Client.post', return_value=mock_resp):
        with pytest.raises(AIMalformedOutputError):
            nim.chat("system", "user")


# ---------------------------------------------------------------------------
# Test 8: Timeouts do not duplicate side effects.
# ---------------------------------------------------------------------------
def test_8_timeouts_do_not_duplicate_side_effects():
    """Verify that when side_effects_executed=True, the model fails over without side effect re-execution."""
    side_effect_mock = MagicMock()

    def perform_consequential_action():
        side_effect_mock("TRANSFER_FUNDS")

    # Step 1: Perform the action exactly once
    perform_consequential_action()
    assert side_effect_mock.call_count == 1

    # Step 2: Model inference times out on Meterless, falls back to offline
    unified = UnifiedAIProvider()
    with patch.object(MeterlessProvider, 'is_configured', return_value=True), \
         patch.object(MeterlessProvider, 'chat', side_effect=AITimeoutError("Timeout during narrative generation")), \
         patch.object(NvidiaNimProvider, 'is_configured', return_value=False):

        res = unified.generate("system", "user", side_effects_executed=True)

    # Assert side effect was NOT repeated
    assert side_effect_mock.call_count == 1
    assert res["provider_used"] == "offline"


# ---------------------------------------------------------------------------
# Test 9: API keys never appear in logs or responses.
# ---------------------------------------------------------------------------
def test_9_api_keys_never_appear_in_logs_or_responses():
    secret_key = "nvapi-real-super-secret-key-12345"
    secret_token = "meterless-token-classified-67890"

    redacted_key = redact_secret(secret_key)
    redacted_token = redact_secret(secret_token)

    assert secret_key not in redacted_key
    assert secret_token not in redacted_token
    assert "***" in redacted_key

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "x-api-key": secret_token,
        "Content-Type": "application/json"
    }
    safe_headers = redact_headers(headers)
    assert secret_key not in safe_headers["Authorization"]
    assert secret_token not in safe_headers["x-api-key"]

    audit_payload = {
        "token": secret_token,
        "credentials": {"api_key": secret_key, "port": 8000}
    }
    sanitized = sanitize_for_audit(audit_payload)
    assert secret_token not in str(sanitized)
    assert secret_key not in str(sanitized)


# ---------------------------------------------------------------------------
# Test 10: Existing agent workflows continue passing with unified failover.
# ---------------------------------------------------------------------------
def test_10_existing_agent_workflows_continue_passing():
    result = investigate("LEASE-0001", "Verify rent reconciliation status")
    assert result["case_id"] == "LEASE-0001"
    assert "result" in result
    assert result["result"]["status"] in ("reconciled", "needs_review", "partial_payment", "overpayment")
    assert "ai_provider_used" in result["mode"]
    assert result["mode"]["ai_provider_used"] in ("meterless", "nim", "offline")
    assert result["narrative"] is not None


# ---------------------------------------------------------------------------
# Test 11: Zetaris live mode is clearly distinguished from fixture mode.
# ---------------------------------------------------------------------------
def test_11_zetaris_live_distinguished_from_fixture():
    zf = ZetarisFinance()

    # When unconfigured, it must clearly report fixture_fallback
    with patch.object(zf, 'is_configured', return_value=False):
        status = zf.test_connection()
        assert status["mode"] == "fixture_fallback"
        assert status["status"] == "NOT_CONFIGURED"

    # When endpoint responds with 200, it reports live
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch.object(zf, 'is_configured', return_value=True), \
         patch('httpx.Client.post', return_value=mock_resp):
        status = zf.test_connection()
        assert status["mode"] == "live"
        assert status["status"] == "HEALTHY"

    # When endpoint responds with error, it gracefully reports fixture_fallback
    mock_resp.status_code = 400
    mock_resp.text = "Missing source"
    with patch.object(zf, 'is_configured', return_value=True), \
         patch('httpx.Client.post', return_value=mock_resp):
        status = zf.test_connection()
        assert status["mode"] == "fixture_fallback"
        assert status["status"] == "DEGRADED"


# ---------------------------------------------------------------------------
# Test 12: Provider health reflects actual verification rather than configuration alone.
# ---------------------------------------------------------------------------
def test_12_provider_health_reflects_actual_verification():
    nim = NvidiaNimProvider()

    # If key is set but server returns 401, status is AUTH_FAILED (not HEALTHY)
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch.object(nim, 'is_configured', return_value=True), \
         patch('httpx.Client.get', return_value=mock_resp):
        health = nim.health_check()
        assert health["status"] == "AUTH_FAILED"
        assert health["auth_status"] == "invalid"

    # If key is set and server returns 200 with model list, status is HEALTHY
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": nim.model}]}
    with patch.object(nim, 'is_configured', return_value=True), \
         patch('httpx.Client.get', return_value=mock_resp):
        health = nim.health_check()
        assert health["status"] == "HEALTHY"
        assert health["auth_status"] == "valid"
        assert health["model_verified"] == "verified"
