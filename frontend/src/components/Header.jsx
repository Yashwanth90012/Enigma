import React from 'react';

export default function Header({
  activeHub = 'dashboard',
  theme,
  toggleTheme,
  onOpenLeaseModal,
  onOpenWorkOrderModal,
  onOpenVendorInvoiceModal,
  onOpenSettingsModal,
  onSeedDatabase,
  sidebarOpen,
  setSidebarOpen
}) {
  const pageMeta = {
    dashboard: {
      category: 'Overview & Intelligence',
      title: 'Executive Dashboard',
      subtitle: 'Portfolio Health, Habitability SLAs & Multi-Agent Telemetry'
    },
    tenant: {
      category: 'Financial Operations',
      title: 'Tenant Rental Accounts Receivable (AR)',
      subtitle: '3-Way Match: Lease Schedules ↔ Tenant Remittances ↔ Bank Deposits'
    },
    vendor: {
      category: 'Financial Operations',
      title: 'Vendor Maintenance & Accounts Payable (AP)',
      subtitle: '4-Way Match: Work Orders ↔ Vendor PDF Invoices ↔ Vouchers ↔ Bank Clearing'
    },
    resident: {
      category: 'Resident Lifecycle',
      title: 'Resident Experience & Service Hub',
      subtitle: 'Onboarding Checklists, Lease Renewals & Statutory Move-Out Closures'
    },
    public: {
      category: 'Resident Lifecycle',
      title: 'Public Listings & Prospect Portal',
      subtitle: 'Verified Vacancy Showcase, Digital Tour Booking & Tenant Applications'
    },
    compliance: {
      category: 'Governance & Legal',
      title: 'Compliance & Statutory Risk Register',
      subtitle: '16 Automated Statutory Rules across CA, NY, TX, WA & Manager Approval Gates'
    },
    docintel: {
      category: 'AI & Data Infrastructure',
      title: 'Document Intelligence & RAG Vault',
      subtitle: 'PaddleOCR Text Extraction, Document Classifier & PostgreSQL pgvector HNSW'
    },
    templates: {
      category: 'Communication Automation',
      title: 'Communication Template Library',
      subtitle: '42 Production-Grade Templates across Rent, Maintenance, Vendors & Legal Notices'
    },
    saas: {
      category: 'SaaS Platform',
      title: 'Customer Requirements & Co-Innovation',
      subtitle: 'Multi-Tenant Product Roadmap, Enterprise Backlog & Feature Upvoting'
    },
    admin: {
      category: 'Infrastructure & Federation',
      title: 'Admin Diagnostics & Lakehouse Federation',
      subtitle: 'Zetaris Spark SQL Query Engine, Latency Monitors & Background Schedulers'
    }
  };

  const current = pageMeta[activeHub] || pageMeta.dashboard;

  return (
    <header className="workspace-topbar">
      {/* Left: Mobile Toggle & Page Breadcrumbs */}
      <div className="topbar-left">
        <button
          className="mobile-sidebar-toggle"
          onClick={() => setSidebarOpen && setSidebarOpen(!sidebarOpen)}
          aria-label="Toggle Navigation Menu"
        >
          <svg className="icon" viewBox="0 0 24 24">
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        <div className="topbar-breadcrumb-box">
          <div className="breadcrumb-path">
            <span className="breadcrumb-root">EQUILIBRA</span>
            <span className="breadcrumb-separator">/</span>
            <span className="breadcrumb-cat">{current.category}</span>
          </div>
          <div className="breadcrumb-headline">
            <h1 className="breadcrumb-title">{current.title}</h1>
            <span className="breadcrumb-sub">{current.subtitle}</span>
          </div>
        </div>
      </div>

      {/* Right: Quick Operational Actions & Utility Controls */}
      <div className="topbar-right">
        {/* Quick Action Button Group */}
        <div className="topbar-action-group">
          <button
            className="btn btn-primary btn-sm"
            onClick={onOpenLeaseModal}
            title="Create & Sign New Tenant Lease Agreement"
          >
            <svg className="icon" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <span>+ Lease</span>
          </button>

          <button
            className="btn btn-amber btn-sm"
            onClick={onOpenWorkOrderModal}
            title="Dispatch Maintenance Work Order"
          >
            <svg className="icon" viewBox="0 0 24 24">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
            <span>+ Order</span>
          </button>

          <button
            className="btn btn-purple btn-sm"
            onClick={onOpenVendorInvoiceModal}
            title="Upload or Generate Vendor Invoice PDF"
          >
            <svg className="icon" viewBox="0 0 24 24">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span>+ Bill</span>
          </button>
        </div>

        {/* Utilities: Seed, Settings & Theme Toggle */}
        <div className="topbar-utility-group">
          <button
            className="btn btn-secondary btn-sm"
            onClick={onSeedDatabase}
            title="Reset & Re-Seed 100 Demo Leases and Work Orders"
          >
            <svg className="icon" viewBox="0 0 24 24">
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
            <span className="btn-text-desktop">Re-Seed</span>
          </button>

          <button
            className="btn-icon"
            onClick={onOpenSettingsModal}
            title="Sponsor Integrations & Cloud Config"
            aria-label="Settings"
          >
            <svg className="icon" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>

          <button
            className="theme-toggle-icon-btn"
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to Light Theme' : 'Switch to Dark Theme'}
            aria-label="Toggle Theme"
          >
            {theme === 'dark' ? (
              <svg className="icon theme-icon-moon" viewBox="0 0 24 24">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            ) : (
              <svg className="icon theme-icon-sun" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="5" />
                <line x1="12" y1="1" x2="12" y2="3" />
                <line x1="12" y1="21" x2="12" y2="23" />
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                <line x1="1" y1="12" x2="3" y2="12" />
                <line x1="21" y1="12" x2="23" y2="12" />
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
