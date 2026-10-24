import React, { useState } from 'react';

export default function OnboardCustomerModal({ isOpen, onClose, onOnboardCustomer }) {
  const [name, setName] = useState('');
  const [portfolioType, setPortfolioType] = useState('Residential Multifamily');
  const [tier, setTier] = useState('Enterprise Cloud');
  const [awsRegion, setAwsRegion] = useState('us-east-1');
  const [activeUnits, setActiveUnits] = useState(120);
  const [contactEmail, setContactEmail] = useState('');
  const [primaryLedger, setPrimaryLedger] = useState('Zetaris SQL REST Federation');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !contactEmail.trim()) {
      alert('Please provide company name and contact email.');
      return;
    }
    setIsSubmitting(true);
    try {
      await onOnboardCustomer({
        name: name.trim(),
        portfolio_type: portfolioType,
        tier,
        aws_region: awsRegion,
        active_units: parseInt(activeUnits) || 100,
        contact_email: contactEmail.trim(),
        primary_ledger: primaryLedger,
        description: description.trim() || `${name} onboarded into EQUILIBRA™ OS SaaS cloud template.`
      });
      onClose();
    } catch (err) {
      alert('Failed to onboard customer: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">Onboard New Customer (SaaS Cloud Tenant)</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Onboard an independent property management company or REIT. The customer will immediately receive an isolated tenant workspace on the same high-performance reconciliation template.
          </p>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Company / Portfolio Name:
            <input
              type="text"
              required
              placeholder="e.g. Pacific Coast Asset Management"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Portfolio Asset Class:
              <select
                value={portfolioType}
                onChange={(e) => setPortfolioType(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="Residential Multifamily">Residential Multifamily</option>
                <option value="Mixed-Use Commercial">Mixed-Use Commercial</option>
                <option value="Luxury Single-Family Portfolios">Luxury Single-Family Portfolios</option>
                <option value="Metro High-Rise Communities">Metro High-Rise Communities</option>
                <option value="Student Housing & Co-Living">Student Housing & Co-Living</option>
              </select>
            </label>

            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              SaaS Subscription Tier:
              <select
                value={tier}
                onChange={(e) => setTier(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="Growth SaaS">Growth SaaS ($499/mo)</option>
                <option value="Enterprise Cloud">Enterprise Cloud ($1,499/mo)</option>
                <option value="Institutional Tier">Institutional REIT Custom SLA</option>
              </select>
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Active Units / Leases:
              <input
                type="number"
                min="1"
                value={activeUnits}
                onChange={(e) => setActiveUnits(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>

            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Target AWS Cloud Region:
              <select
                value={awsRegion}
                onChange={(e) => setAwsRegion(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="us-east-1">AWS US East (N. Virginia)</option>
                <option value="us-west-2">AWS US West (Oregon)</option>
                <option value="eu-central-1">AWS EU (Frankfurt)</option>
                <option value="ap-southeast-1">AWS AP (Singapore)</option>
              </select>
            </label>
          </div>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Admin / Controller Contact Email:
            <input
              type="email"
              required
              placeholder="controller@company.com"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Primary Accounting Integration:
            <select
              value={primaryLedger}
              onChange={(e) => setPrimaryLedger(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            >
              <option value="Zetaris SQL REST Federation">Zetaris SQL REST Federation (Direct Lakehouse Query)</option>
              <option value="PostgreSQL Fixture / Yardi Voyager">PostgreSQL Fixture / Yardi Voyager API</option>
              <option value="RealPage Cloud API Adapter">RealPage Cloud API Adapter</option>
              <option value="QuickBooks Enterprise REST">QuickBooks Enterprise REST Connector</option>
            </select>
          </label>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Portfolio Memo / Description:
            <textarea
              rows="2"
              placeholder="Describe portfolio locations, special billing terms, or tenant mix..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting}
            style={{ width: '100%', justifyContent: 'center', padding: 12, marginTop: 8 }}
          >
            {isSubmitting ? (
              <>
                <span className="spinner"></span>
                <span>Provisioning SaaS Tenant Workspace...</span>
              </>
            ) : (
              <span>Deploy Customer Workspace to Cloud</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
