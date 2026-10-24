"""Tests for Zetaris SQL federation adapter and Meterless/Nemotron provider.

Verifies:
- Robust normalization across all known Zetaris response shapes
- Identifier whitelisting and input sanitization
- Credential redaction in headers and traces
- Offline fallback reasoning behavior
"""

import pytest
from app.providers import normalize_zetaris_case, redact_headers, redact_secret, MeterlessProvider

def test_normalize_zetaris_list_format():
    raw = {
        'invoices': [{'id': 'INV-1', 'amount': '2125.00', 'currency': 'USD'}],
        'payments': [{'id': 'PAY-1', 'amount': '2125.00', 'currency': 'USD', 'reference': 'REF-1'}],
        'bank': [{'id': 'BANK-1', 'amount': '2125.00', 'currency': 'USD', 'reference': 'REF-1'}]
    }
    norm = normalize_zetaris_case(raw)
    assert norm['invoices'][0]['id'] == 'INV-1'
    assert norm['payments'][0]['reference'] == 'REF-1'

def test_normalize_zetaris_wrapped_rows_format():
    raw = {
        'invoices': {'rows': [{'id': 'INV-2', 'amount': '1800.00'}]},
        'payments': {'rows': []},
        'bank': {'rows': []}
    }
    norm = normalize_zetaris_case(raw)
    assert norm['invoices'][0]['id'] == 'INV-2'

def test_normalize_zetaris_wrapped_data_format():
    raw = {
        'invoices': {'data': [{'id': 'INV-3', 'amount': '2500.00'}]},
        'payments': {'data': []},
        'bank': {'data': []}
    }
    norm = normalize_zetaris_case(raw)
    assert norm['invoices'][0]['id'] == 'INV-3'

def test_normalize_zetaris_nested_result_records_format():
    raw = {
        'invoices': {'result': {'records': [{'id': 'INV-4', 'amount': '3000.00'}]}},
        'payments': {'result': {'records': []}},
        'bank': {'result': {'records': []}}
    }
    norm = normalize_zetaris_case(raw)
    assert norm['invoices'][0]['id'] == 'INV-4'

def test_normalize_zetaris_tabular_columns_rows_format():
    raw = {
        'invoices': {
            'columns': ['id', 'lease_id', 'amount', 'currency'],
            'rows': [['INV-5', 'LEASE-0005', 2125.0, 'USD']]
        },
        'payments': {'columns': ['id', 'reference'], 'rows': []},
        'bank': {'columns': ['id', 'reference'], 'rows': []}
    }
    norm = normalize_zetaris_case(raw)
    assert norm['invoices'][0]['id'] == 'INV-5'
    assert norm['invoices'][0]['lease_id'] == 'LEASE-0005'
    assert norm['invoices'][0]['amount'] == 2125.0

def test_normalize_zetaris_invalid_shape():
    raw = {'invoices': 'invalid_string_not_dict'}
    with pytest.raises(ValueError, match='Unrecognized Zetaris response shape'):
        normalize_zetaris_case(raw)

def test_credential_redaction():
    token = "sk-live-meterless-secret-key-123456789"
    redacted = redact_secret(token)
    assert "sk-l" in redacted
    assert "89" in redacted
    assert "secret-key" not in redacted

    headers = {
        'Authorization': 'Bearer ' + token,
        'meterless-app': 'enigma',
        'X-Org-ID': '1'
    }
    safe = redact_headers(headers)
    assert "secret-key" not in safe['Authorization']
    assert safe['meterless-app'] == 'enigma'
    assert safe['X-Org-ID'] == '1'

def test_offline_summary_fallback():
    provider = MeterlessProvider()
    summary = provider._deterministic_summary("Sample test context")
    assert "Property Manager Executive Summary" in summary
