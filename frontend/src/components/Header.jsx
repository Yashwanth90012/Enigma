import React from 'react';

export default function Header({
  theme,
  toggleTheme,
  organizations,
  currentOrgId,
  setCurrentOrgId,
  onOpenOnboardModal,
  onOpenLeaseModal,
  onOpenWorkOrderModal,
  onOpenVendorInvoiceModal,
  onOpenSettingsModal,
  onSeedDatabase
}) {
  return (
    <header className="enterprise-header">
      {/* Brand Identity */}
      <div className="brand-block">
        <div className="brand-logo">
          <svg className="icon" style={{ stroke: '#fff', width: 20, height: 20 }} viewBox="0 0 24 24">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
          </svg>
        </div>
        <div className="brand-titles">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="brand-name">EQUILIBRA</span>
            <span className="brand-badge">SaaS Cloud</span>
          </div>
          <div className="brand-sub">Autonomous Financial Cloud</div>
        </div>
      </div>

      {/* Customer Organization Selector */}
      <div className="org-selector-container">
        <svg className="icon" style={{ width: 14, height: 14, color: 'var(--primary)' }} viewBox="0 0 24 24">
          <path d="M3 21h18M3 7v14M21 7v14M6 7V3h12v4M9 11h2M13 11h2M9 15h2M13 15h2M9 19h2M13 19h2" />
        </svg>
        <span className="org-label">Customer:</span>
        <select
          className="org-select"
          value={currentOrgId}
          onChange={(e) => setCurrentOrgId(e.target.value)}
          title="Switch Customer Portfolio Workspace"
        >
          {organizations.map((org) => (
            <option key={org.id} value={org.id}>
              {org.name} ({org.active_units} Units · {org.tier})
            </option>
          ))}
        </select>
        <button
          className="btn-onboard-chip"
          onClick={onOpenOnboardModal}
          title="Onboard a new property manager firm into this SaaS template"
        >
          + Onboard
        </button>
      </div>

      {/* Enterprise Actions & Compact Controls */}
      <div className="header-actions">
        {/* Quick Action Button Group */}
        <div className="action-button-group">
          <button className="btn btn-primary btn-sm" onClick={onOpenLeaseModal} title="Sign & Ingest New Lease">
            <svg className="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span>+ Lease</span>
          </button>
          <button className="btn btn-amber btn-sm" onClick={onOpenWorkOrderModal} title="Dispatch Maintenance Work Order">
            <svg className="icon" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            <span>+ Order</span>
          </button>
          <button className="btn btn-purple btn-sm" onClick={onOpenVendorInvoiceModal} title="Upload Vendor PDF Bill">
            <svg className="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            <span>+ Bill</span>
          </button>
        </div>

        <div className="utility-button-group">
          <button className="btn btn-secondary btn-sm" onClick={onSeedDatabase} title="Re-Seed Demo Data">
            <svg className="icon" viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
            <span>Re-Seed</span>
          </button>

          <button className="btn-icon" onClick={onOpenSettingsModal} title="Sponsor Integrations & Cloud Configuration" aria-label="Settings">
            <svg className="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>

          {/* Compact Theme Toggle Button (Will not expand horizontally) */}
          <button
            className="theme-toggle-icon-btn"
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to Light Theme (Default)' : 'Switch to Dark Theme'}
            aria-label="Toggle Theme"
          >
            {theme === 'dark' ? (
              <svg className="icon theme-icon-moon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            ) : (
              <svg className="icon theme-icon-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
