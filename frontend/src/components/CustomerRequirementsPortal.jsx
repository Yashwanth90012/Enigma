import React, { useState } from 'react';

export default function CustomerRequirementsPortal({
  requirements,
  organizations,
  onOpenSubmitRequirementModal,
  onOpenOnboardModal,
  onUpvoteRequirement
}) {
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredReqs = requirements.filter((req) => {
    if (categoryFilter !== 'all' && req.category !== categoryFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const match =
        req.title.toLowerCase().includes(q) ||
        req.specification.toLowerCase().includes(q) ||
        req.org_name.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });

  const getStatusBadgeClass = (status) => {
    switch (status) {
      case 'DEPLOYED_TO_CLOUD':
        return 'status-deployed';
      case 'IN_STAGING':
        return 'status-staging';
      case 'IN_ROADMAP':
        return 'status-roadmap';
      default:
        return 'status-triaged';
    }
  };

  const getCategoryLabel = (cat) => {
    switch (cat) {
      case 'tenant_ar':
        return 'Tenant AR Reconciliation';
      case 'vendor_ap':
        return 'Vendor Maintenance AP';
      case 'world_model':
        return 'Meterless World Model / AI';
      case 'erp_connector':
        return 'Zetaris / ERP Connector';
      case 'aws_infra':
        return 'AWS Cloud & Webhooks';
      default:
        return cat.toUpperCase();
    }
  };

  return (
    <div className="requirements-portal">
      {/* Banner */}
      <div className="req-header-banner">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <h1 className="req-header-title">Customer Co-Innovation & Requirements Portal</h1>
            <span className="pill active" style={{ fontSize: 11 }}>Multi-Tenant SaaS Feedback</span>
          </div>
          <p className="req-header-desc">
            All onboarded property manager customers share the unified <strong>EQUILIBRA™ OS</strong> template.
            Submit custom reconciliation rules, Yardi/Zetaris ERP requirements, or AWS cloud features directly into our continuous delivery pipeline.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-primary" onClick={onOpenSubmitRequirementModal}>
            <svg className="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            <span>+ Submit New Requirement</span>
          </button>
          <button className="btn" onClick={onOpenOnboardModal}>
            <svg className="icon" viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7.5" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>
            <span>+ Onboard Customer</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button
            className={`preset-chip ${categoryFilter === 'all' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('all')}
          >
            All Domains ({requirements.length})
          </button>
          <button
            className={`preset-chip ${categoryFilter === 'tenant_ar' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('tenant_ar')}
          >
            Tenant AR Flow
          </button>
          <button
            className={`preset-chip ${categoryFilter === 'vendor_ap' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('vendor_ap')}
          >
            Vendor AP & 4-Way Match
          </button>
          <button
            className={`preset-chip ${categoryFilter === 'world_model' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('world_model')}
          >
            Meterless World Model
          </button>
          <button
            className={`preset-chip ${categoryFilter === 'aws_infra' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('aws_infra')}
          >
            AWS Cloud Webhooks
          </button>
        </div>

        <input
          type="text"
          placeholder="Search submitted requirements, specifications, or clients..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            minWidth: 280,
            padding: '7px 12px',
            fontSize: 12,
            borderRadius: 'var(--radius-sm)'
          }}
        />
      </div>

      {/* Feature Request Cards Grid */}
      <div className="req-grid">
        {filteredReqs.map((req) => (
          <div key={req.id} className="req-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
              <div>
                <span className="lease-id-badge" style={{ fontSize: 10 }}>{req.id}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--primary)', marginLeft: 6 }}>
                  {req.org_name}
                </span>
              </div>
              <span className={`req-status-pill ${getStatusBadgeClass(req.status)}`}>
                {req.status.replace(/_/g, ' ')}
              </span>
            </div>

            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-heading)', marginTop: 2 }}>
              {req.title}
            </h3>

            <p style={{ fontSize: 12, color: 'var(--text-main)', lineHeight: 1.5, flex: 1 }}>
              {req.specification}
            </p>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-subtle)', paddingTop: 10, marginTop: 4 }}>
              <div>
                <span className="vendor-badge-trade trade-materials" style={{ fontSize: 9 }}>
                  {getCategoryLabel(req.category)}
                </span>
                <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3 }}>
                  By: {req.submitted_by} · Target: {req.target_release}
                </div>
              </div>

              <button
                className="vote-chip"
                onClick={() => onUpvoteRequirement(req.id)}
                title="Upvote this requirement to prioritize in next cloud deployment sprint"
              >
                <span>▲</span>
                <span>{req.votes} Votes</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Onboarded Customer Organizations Showcase */}
      <div style={{ marginTop: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ fontSize: 16, fontWeight: 800, color: 'var(--text-heading)' }}>
            Onboarded Customer Portfolios ({organizations.length} Property Firms)
          </h2>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Isolated tenant schemas operating on same AWS cloud template
          </span>
        </div>

        <div className="req-grid">
          {organizations.map((org) => (
            <div key={org.id} className="req-card" style={{ background: 'var(--bg-inset)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="lease-id-badge">{org.id}</span>
                <span className="pill active" style={{ fontSize: 10 }}>{org.tier}</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text-heading)' }}>
                {org.name}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {org.description}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 11, marginTop: 6, background: 'var(--bg-card)', padding: 8, borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
                <div><span style={{ color: 'var(--text-dim)' }}>Units:</span> <strong>{org.active_units} Units</strong></div>
                <div><span style={{ color: 'var(--text-dim)' }}>Region:</span> <strong>{org.aws_region}</strong></div>
                <div><span style={{ color: 'var(--text-dim)' }}>Ledger:</span> <strong style={{ color: 'var(--primary)' }}>{org.primary_ledger.split(' ')[0]}</strong></div>
                <div><span style={{ color: 'var(--text-dim)' }}>AI Reasoner:</span> <strong style={{ color: 'var(--purple)' }}>Nemotron</strong></div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
