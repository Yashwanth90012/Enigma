import React, { useState } from 'react';

export default function RentalApplicationModal({ isOpen, onClose, property, onApplicationSubmitted }) {
  const [applicantName, setApplicantName] = useState('');
  const [applicantEmail, setApplicantEmail] = useState('');
  const [applicantPhone, setApplicantPhone] = useState('');
  const [unit, setUnit] = useState('Unit 101');
  const [income, setIncome] = useState('8500');
  const [creditScore, setCreditScore] = useState(720);
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen || !property) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      const res = await fetch('/api/applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          property_id: property.property_id,
          unit: unit,
          applicant_name: applicantName,
          applicant_email: applicantEmail,
          applicant_phone: applicantPhone,
          monthly_income_usd: parseFloat(income),
          credit_score: parseInt(creditScore, 10),
          notes: notes
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.message || 'Failed to submit application');
      if (onApplicationSubmitted) onApplicationSubmitted(data);
      onClose();
      alert(`Application received! Status: [${data.status.toUpperCase()}]. Ratio: ${data.income_ratio}x`);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540 }}>
        <div className="modal-header">
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Rental Application</h2>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              Applying for: {property.name} (${property.monthly_rent_usd}/mo)
            </div>
          </div>
          <button className="btn-icon btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        {error && (
          <div style={{ padding: 10, background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--rose)', borderRadius: 6, color: 'var(--rose)', fontSize: 13, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Applicant Full Name</label>
            <input
              type="text"
              required
              className="input-field"
              placeholder="e.g. Taylor Morgan"
              value={applicantName}
              onChange={(e) => setApplicantName(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Email</label>
              <input
                type="email"
                required
                className="input-field"
                placeholder="taylor@example.com"
                value={applicantEmail}
                onChange={(e) => setApplicantEmail(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Phone</label>
              <input
                type="tel"
                className="input-field"
                placeholder="(555) 012-9843"
                value={applicantPhone}
                onChange={(e) => setApplicantPhone(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Target Unit</label>
              <input
                type="text"
                className="input-field"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Monthly Income ($)</label>
              <input
                type="number"
                required
                className="input-field"
                value={income}
                onChange={(e) => setIncome(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Est. Credit Score</label>
              <input
                type="number"
                min="400"
                max="850"
                className="input-field"
                value={creditScore}
                onChange={(e) => setCreditScore(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
          </div>

          <div style={{ background: 'var(--surface-hover)', padding: 10, borderRadius: 6, fontSize: 12 }}>
            ℹ Automated Pre-Qualification: Income must meet or exceed 2.5x monthly rent (${(property.monthly_rent_usd * 2.5).toFixed(2)}) with credit score ≥ 650.
          </div>

          <div className="modal-footer" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 10 }}>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </button>
            <button type="submit" className="btn btn-emerald btn-sm" disabled={isSubmitting}>
              {isSubmitting ? 'Evaluating...' : 'Submit Rental Application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
