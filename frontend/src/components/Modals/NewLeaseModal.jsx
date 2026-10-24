import React, { useState } from 'react';

export default function NewLeaseModal({ isOpen, onClose, onIngestLease }) {
  const [leaseId, setLeaseId] = useState('LEASE-0105');
  const [unit, setUnit] = useState('301');
  const [tenant, setTenant] = useState('Aria Montgomery');
  const [address, setAddress] = useState('700 Example Grove Avenue, Unit 301, Berkeley, CA 94704');
  const [rent, setRent] = useState(2400);
  const [deposit, setDeposit] = useState(2500);
  const [leaseText, setLeaseText] = useState('Residential Lease Agreement. Section 3: Monthly rent due on 1st. Section 11: Tenant shall not deduct repair expenses or withhold rent under any circumstances without landlord authorization.');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onIngestLease({
        lease_id: leaseId.trim(),
        unit: unit.trim(),
        address: address.trim(),
        tenant1: tenant.trim(),
        contract_date: new Date().toISOString().split('T')[0],
        move_in_date: new Date().toISOString().split('T')[0],
        monthly_rent_usd: parseFloat(rent) || 0,
        security_deposit_usd: parseFloat(deposit) || 0,
        lease_text: leaseText.trim()
      });
      onClose();
    } catch (err) {
      alert('Failed to sign lease: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">Sign & Ingest New Residential Lease Agreement</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Lease ID:
              <input
                type="text"
                required
                value={leaseId}
                onChange={(e) => setLeaseId(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Unit #:
              <input
                type="text"
                required
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Primary Tenant Full Name:
            <input
              type="text"
              required
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Property Address:
            <input
              type="text"
              required
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Monthly Rent ($):
              <input
                type="number"
                required
                value={rent}
                onChange={(e) => setRent(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Security Deposit ($):
              <input
                type="number"
                required
                value={deposit}
                onChange={(e) => setDeposit(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Lease Agreement Legal Text:
            <textarea
              rows="4"
              value={leaseText}
              onChange={(e) => setLeaseText(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4, fontFamily: 'var(--font-sans)', fontSize: 12 }}
            />
          </label>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting}
            style={{ width: '100%', justifyContent: 'center', padding: 12, marginTop: 6 }}
          >
            {isSubmitting ? (
              <>
                <span className="spinner"></span>
                <span>Executing Lease & Indexing pgvector Embeddings...</span>
              </>
            ) : (
              <span>Execute Lease & Ingest to Database</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
