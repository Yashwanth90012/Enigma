import React, { useState } from 'react';

export default function SubmitRequirementModal({
  isOpen,
  onClose,
  organizations,
  currentOrgId,
  onSubmitRequirement
}) {
  const [orgId, setOrgId] = useState(currentOrgId || 'ORG-APEX');
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('tenant_ar');
  const [priority, setPriority] = useState('standard');
  const [specification, setSpecification] = useState('');
  const [submittedBy, setSubmittedBy] = useState('Property Manager');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim() || !specification.trim()) {
      alert('Please fill out requirement title and specification.');
      return;
    }
    setIsSubmitting(true);
    try {
      await onSubmitRequirement({
        org_id: orgId,
        title: title.trim(),
        category,
        priority,
        specification: specification.trim(),
        submitted_by: submittedBy.trim() || 'Property Manager'
      });
      onClose();
    } catch (err) {
      alert('Failed to submit requirement: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">Submit Customer Requirement / New Functionality</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Submit new reconciliation rules, custom billing addendums, ERP endpoints, or AI models.
            Your request will be prioritized and published to the shared customer roadmap.
          </p>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Submitting Customer Account:
            <select
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            >
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name} ({org.id})
                </option>
              ))}
            </select>
          </label>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Requirement / Feature Title:
            <input
              type="text"
              required
              placeholder="e.g. Automated Utility Bill Proration by Square Footage"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Functional Domain:
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="tenant_ar">Tenant Rental AR Reconciliation</option>
                <option value="vendor_ap">Vendor AP & 4-Way Matching</option>
                <option value="world_model">Meterless World Model & DAG</option>
                <option value="erp_connector">Zetaris / ERP Data Federation</option>
                <option value="aws_infra">AWS Cloud EventBridge & Webhooks</option>
              </select>
            </label>

            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Priority / SLA:
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="standard">Standard (Next Feature Sprint)</option>
                <option value="high">High Priority (Urgent Portfolio Need)</option>
                <option value="critical_blocker">Critical Cloud Blocker (Audit Blocker)</option>
              </select>
            </label>
          </div>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Detailed Business Specification & Acceptance Criteria:
            <textarea
              rows="4"
              required
              placeholder="Describe what the system should do, acceptable variances, required PDF fields, or ledger formulas..."
              value={specification}
              onChange={(e) => setSpecification(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4, fontFamily: 'var(--font-sans)', fontSize: 12 }}
            />
          </label>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Submitter Name & Role:
            <input
              type="text"
              placeholder="e.g. Rachel Adams (Lead Asset Manager)"
              value={submittedBy}
              onChange={(e) => setSubmittedBy(e.target.value)}
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
                <span>Publishing to Cloud Roadmap...</span>
              </>
            ) : (
              <span>Submit Requirement to Co-Innovation Roadmap</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
