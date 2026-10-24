from decimal import Decimal
from app.engine import calculate, cents
from app.rag import chunk_document

def sample(bank_ref='ABC', amount='100'):
    return {
        'invoices': [{'id': 'I', 'amount': '100', 'currency': 'USD'}],
        'payments': [{'id': 'P', 'amount': amount, 'currency': 'USD', 'reference': 'ABC'}],
        'bank': [{'id': 'B', 'amount': amount, 'currency': 'USD', 'reference': bank_ref}]
    }

def test_exact_match():
    res = calculate(sample())
    assert res['status'] == 'reconciled'
    assert res['reason_code'] == 'MATCH_CONFIRMED'
    assert res['difference_cents'] == 0
    assert res['verified_paid_cents'] == 10000

def test_unmatched_bank():
    res = calculate(sample(bank_ref=''))
    assert res['status'] == 'needs_review'
    assert res['reason_code'] == 'MISSING_BANK_REFERENCE'
    assert res['verified_paid_cents'] == 0

def test_partial():
    res = calculate(sample(amount='80'))
    assert res['status'] == 'partial_payment'
    assert res['reason_code'] == 'PARTIAL_REMITTANCE'
    assert res['difference_cents'] == 2000

def test_duplicate_bank_transaction():
    rows = {
        'invoices': [{'id': 'I', 'amount': '100', 'currency': 'USD'}],
        'payments': [{'id': 'P', 'amount': '100', 'currency': 'USD', 'reference': 'REF-1'}],
        'bank': [
            {'id': 'B1', 'amount': '100', 'currency': 'USD', 'reference': 'REF-1'},
            {'id': 'BANK-DUP-1', 'amount': '100', 'currency': 'USD', 'reference': 'REF-1'}
        ]
    }
    res = calculate(rows)
    assert res['status'] == 'needs_review'
    assert res['reason_code'] == 'DUPLICATE_BANK_TRANSACTION'

def test_multi_currency_mismatch():
    rows = {
        'invoices': [{'id': 'I', 'amount': '100', 'currency': 'USD'}],
        'payments': [{'id': 'P', 'amount': '100', 'currency': 'EUR', 'reference': 'REF-1'}],
        'bank': [{'id': 'B', 'amount': '100', 'currency': 'EUR', 'reference': 'REF-1'}]
    }
    res = calculate(rows)
    assert res['status'] == 'needs_review'
    assert res['reason_code'] == 'CURRENCY_MISMATCH'

def test_cents_decimal_accuracy():
    assert cents('2125.00') == 212500
    assert cents('0.01') == 1
    assert cents(Decimal('1900.50')) == 190050

def test_chunker():
    chunks = chunk_document('1. Rent\nPay monthly.\n2. Maintenance\nReport issues.')
    assert len(chunks) >= 2
