import React, { useState, useEffect } from 'react';

export default function PayBillModal({
  isOpen,
  onClose,
  invoiceId,
  walkthroughData,
  onPayInvoice
}) {
  const [amount, setAmount] = useState(0);
  const [method, setMethod] = useState('check');
  const [ref, setRef] = useState('CHK-88201');
  const [extra, setExtra] = useState('First Republic Operating Account');
  const [simulateBankClearing, setSimulateBankClearing] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (walkthroughData?.bundle?.invoice) {
      setAmount(walkthroughData.bundle.invoice.total_usd);
    }
  }, [walkthroughData]);

  if (!isOpen) return null;

  const handleMethodChange = (newMethod) => {
    setMethod(newMethod);
    if (newMethod === 'cashiers_check') {
      setRef('CC-99401');
      setExtra('JPMorgan Chase Bank, N.A. (Cashier Guaranteed)');
    } else if (newMethod === 'check') {
      setRef('CHK-88201');
      setExtra('First Republic Operating Account');
    } else if (newMethod === 'credit_card') {
      setRef('AUTH-581902');
      setExtra('Corporate Commercial Visa Business 8412');
    } else if (newMethod === 'ach_wire') {
      setRef('ACH-FED-77192');
      setExtra('Wells Fargo Commercial Treasury Direct');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onPayInvoice({
        invoice_id: invoiceId,
        amount_usd: parseFloat(amount) || 0,
        payment_method: method,
        reference: ref.trim(),
        details: {
          memo: extra.trim(),
          disbursed_by: 'Property Manager'
        },
        simulate_bank_clearing: simulateBankClearing
      });
      onClose();
    } catch (err) {
      alert('Failed to disburse payment: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">Disburse Vendor Payment (Multi-Format AP)</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Vendor Invoice ID:
            <input
              type="text"
              readOnly
              value={invoiceId || ''}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4, fontFamily: 'var(--font-mono)' }}
            />
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Payment Amount ($):
              <input
                type="number"
                step="0.01"
                required
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4, fontWeight: 700 }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Payment Format:
              <select
                value={method}
                onChange={(e) => handleMethodChange(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="cashiers_check">Cashier's Check (Bank Guaranteed)</option>
                <option value="check">Normal Corporate Check (Operating Account)</option>
                <option value="credit_card">Corporate Credit Card (Visa/Mastercard)</option>
                <option value="ach_wire">ACH Direct Deposit / Wire Transfer</option>
              </select>
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Reference / Check / Auth #:
              <input
                type="text"
                required
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4, fontFamily: 'var(--font-mono)' }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Issuer Bank / Card Details:
              <input
                type="text"
                required
                value={extra}
                onChange={(e) => setExtra(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          <div style={{ background: 'rgba(8,145,178,0.06)', border: '1px solid rgba(8,145,178,0.25)', padding: 10, borderRadius: 6, marginTop: 4 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--text-heading)', fontSize: 12 }}>
              <input
                type="checkbox"
                checked={simulateBankClearing}
                onChange={(e) => setSimulateBankClearing(e.target.checked)}
                style={{ accentColor: 'var(--primary)' }}
              />
              <span>Simulate Immediate Bank Statement Presentation Feed</span>
            </label>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, paddingLeft: 22 }}>
              Uncheck this box to simulate an <strong>uncashed check / floating in-flight check</strong> (demonstrates stale check reconciliation alerts &gt;14 days).
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-emerald"
            disabled={isSubmitting}
            style={{ width: '100%', justifyContent: 'center', padding: 12, marginTop: 6 }}
          >
            {isSubmitting ? (
              <>
                <span className="spinner"></span>
                <span>Posting AP Disbursement to Ledger & World Model...</span>
              </>
            ) : (
              <span>Issue Payment Voucher & Post to Ledger</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
