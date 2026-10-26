import React from 'react';

export default function HubSwitcher({
  activeHub,
  setActiveHub,
  tenantCount = 0,
  vendorBillCount = 0,
  reqCount = 0,
  telemetry = {}
}) {
  return (
    <div className="hub-nav-bar">
      {/* Enterprise Workspace Menubar / Segmented Tabs */}
      <div className="hub-nav-container">
        <button
          className={`hub-nav-btn ${activeHub === 'public' ? 'active' : ''}`}
          onClick={() => setActiveHub('public')}
          title="Search verified properties and book digital tours"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          <span>Public Listings</span>
          <span className="hub-pill emerald">Tours & Apply</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'resident' ? 'active cyan-hub' : ''}`}
          onClick={() => setActiveHub('resident')}
          title="Resident self-service: pay rent, submit repairs, view notices"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          <span>Resident Portal</span>
          <span className="hub-pill cyan">Pay & Service</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'tenant' ? 'active' : ''}`}
          onClick={() => setActiveHub('tenant')}
          title="Owner/Property Manager Tenant Rental AR 3-way reconciliation"
        >
          <svg className="icon" viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
          <span>Tenant Rental AR</span>
          <span className="hub-pill cyan">{tenantCount} Leases</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'vendor' ? 'active purple-hub' : ''}`}
          onClick={() => setActiveHub('vendor')}
          title="Owner/Property Manager Vendor AP 4-way matching"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
          <span>Vendor AP & Maint</span>
          <span className="hub-pill purple">{vendorBillCount} Bills</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'docintel' ? 'active cyan-hub' : ''}`}
          onClick={() => setActiveHub('docintel')}
          title="Document Intelligence: OCR extraction, confidence validation, and hybrid RAG retrieval"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          <span>Doc Intelligence</span>
          <span className="hub-pill cyan">OCR & RAG</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'saas' ? 'active roadmap-hub' : ''}`}
          onClick={() => setActiveHub('saas')}
          title="Multi-tenant customer roadmap and feature voting"
        >
          <svg className="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <span>Customer Co-Innovation</span>
          <span className="hub-pill blue">{reqCount} Reqs</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'compliance' ? 'active amber-hub' : ''}`}
          onClick={() => setActiveHub('compliance')}
          title="Central Compliance & Risk Monitoring Hub"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span>Compliance & Risk</span>
          <span className="hub-pill amber">Risk Hub</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'templates' ? 'active' : ''}`}
          onClick={() => setActiveHub('templates')}
          title="Centralized Communication Template Library across Rent, Leases, Maintenance, Vendors, and Compliance"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
          <span>Communication Templates</span>
          <span className="hub-pill emerald">42 Templates</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'admin' ? 'active' : ''}`}
          onClick={() => setActiveHub('admin')}
          title="Scheduler health, integration status, and audit log"
        >
          <svg className="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          <span>Admin & Schedulers</span>
          <span className="hub-pill rose">Diagnostics</span>
        </button>

        <button
          className={`hub-nav-btn ${activeHub === 'audit' ? 'active emerald-hub' : ''}`}
          onClick={() => setActiveHub('audit')}
          title="Centralized website audit logs, activity tracking, and security review"
        >
          <svg className="icon" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>
          <span>Audit Logs</span>
          <span className="hub-pill emerald">Security</span>
        </button>
      </div>

      {/* Real-Time System Telemetry Rack */}
      <div className="telemetry-rack">
        <div className="telemetry-pill-engine">
          <span className="indicator-dot pulse-dot"></span>
          <span>Engine Online</span>
        </div>

        <div className="pill active" title="pgvector HNSW Indexed Hybrid Chunks">
          <svg className="icon" style={{ width: 12, height: 12 }} viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          <span>{Number(telemetry.totalChunks || 9300).toLocaleString()} Chunks</span>
        </div>

        <div className="pill purple" title="Meterless World Model Event Log Sourcing">
          <svg className="icon" style={{ width: 12, height: 12 }} viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><polygon points="12 6 12 12 14 14" /></svg>
          <span>{telemetry.worldEvents || 0} Events</span>
        </div>

        <div className="pill" title="Finance General Ledger / Source">
          <span>Ledger: <strong>{telemetry.financeSource || 'Zetaris SQL'}</strong></span>
        </div>

        <div className="pill" title="Autonomous AI Reasoning Engine">
          <span>AI: <strong>{telemetry.aiModel || 'NVIDIA Nemotron'}</strong></span>
        </div>
      </div>
    </div>
  );
}
