import React, { useState } from 'react';

export default function Sidebar({
  activeHub,
  setActiveHub,
  tenantCount = 0,
  vendorBillCount = 0,
  reqCount = 0,
  telemetry = {},
  organizations = [],
  currentOrgId,
  setCurrentOrgId,
  onOpenOnboardModal,
  sidebarOpen,
  setSidebarOpen
}) {
  const [collapsed, setCollapsed] = useState(false);

  const currentOrg = organizations.find((o) => o.id === currentOrgId) || organizations[0];

  const navSections = [
    {
      group: 'Overview & Analytics',
      items: [
        {
          id: 'dashboard',
          label: 'Executive Dashboard',
          sub: 'Portfolio Health & KPIs',
          badge: 'Live HUD',
          badgeColor: 'emerald',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="9" rx="1.5" />
              <rect x="14" y="3" width="7" height="5" rx="1.5" />
              <rect x="14" y="12" width="7" height="9" rx="1.5" />
              <rect x="3" y="16" width="7" height="5" rx="1.5" />
            </svg>
          )
        }
      ]
    },
    {
      group: 'Financial Operations',
      items: [
        {
          id: 'tenant',
          label: 'Tenant Rental AR',
          sub: '3-Way Match & Rent Roll',
          badge: `${tenantCount} Leases`,
          badgeColor: 'cyan',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <rect x="2" y="7" width="20" height="14" rx="2" />
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
            </svg>
          )
        },
        {
          id: 'vendor',
          label: 'Vendor AP & Maint',
          sub: '4-Way Match & Bills',
          badge: `${vendorBillCount} Bills`,
          badgeColor: 'purple',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
          )
        }
      ]
    },
    {
      group: 'Residents & Prospects',
      items: [
        {
          id: 'resident',
          label: 'Resident Portal',
          sub: 'Renewals & Move-In/Out',
          badge: 'Self-Service',
          badgeColor: 'blue',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
          )
        },
        {
          id: 'public',
          label: 'Public Listings',
          sub: 'Tours & Applications',
          badge: 'Apply',
          badgeColor: 'emerald',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
          )
        }
      ]
    },
    {
      group: 'Intelligence & Compliance',
      items: [
        {
          id: 'compliance',
          label: 'Compliance & Risk',
          sub: '16 Statutory Rules',
          badge: 'Risk Radar',
          badgeColor: 'amber',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          )
        },
        {
          id: 'docintel',
          label: 'Doc Intelligence',
          sub: 'PaddleOCR & RAG',
          badge: 'pgvector',
          badgeColor: 'cyan',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          )
        },
        {
          id: 'templates',
          label: 'Communication Library',
          sub: '42 Smart Templates',
          badge: '42 Tmpls',
          badgeColor: 'emerald',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
              <polyline points="22,6 12,13 2,6" />
            </svg>
          )
        }
      ]
    },
    {
      group: 'Platform & Diagnostics',
      items: [
        {
          id: 'saas',
          label: 'Customer Roadmap',
          sub: 'Co-Innovation & Votes',
          badge: `${reqCount} Reqs`,
          badgeColor: 'blue',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          )
        },
        {
          id: 'admin',
          label: 'Zetaris & Schedulers',
          sub: 'Lakehouse & Audit DAG',
          badge: 'Spark SQL',
          badgeColor: 'rose',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          )
        },
        {
          id: 'audit',
          label: 'Website Audit Logs',
          sub: 'Immutable Activity Logs',
          badge: 'Security',
          badgeColor: 'emerald',
          icon: (
            <svg className="nav-icon" viewBox="0 0 24 24">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="M9 12l2 2 4-4" />
            </svg>
          )
        }
      ]
    }
  ];

  return (
    <aside className={`app-sidebar ${collapsed ? 'collapsed' : ''} ${sidebarOpen ? 'mobile-open' : ''}`}>
      {/* Brand Identity */}
      <div className="sidebar-brand">
        <div className="brand-logo-container">
          <div className="brand-logo">
            <svg className="brand-svg-icon" viewBox="0 0 24 24">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
          </div>
          {!collapsed && (
            <div className="brand-text-block">
              <div className="brand-headline">
                <span className="brand-name">EQUILIBRA</span>
                <span className="brand-tag">SaaS</span>
              </div>
              <span className="brand-subline">GenAI Hackathon 2026</span>
            </div>
          )}
        </div>
        <button
          className="sidebar-collapse-toggle"
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
          aria-label="Toggle Sidebar"
        >
          <svg className="icon" viewBox="0 0 24 24">
            {collapsed ? (
              <polyline points="9 18 15 12 9 6" />
            ) : (
              <polyline points="15 18 9 12 15 6" />
            )}
          </svg>
        </button>
      </div>

      {/* Tenant Organization Switcher Widget */}
      {!collapsed && (
        <div className="sidebar-org-card">
          <div className="sidebar-org-header">
            <span className="sidebar-org-label">Current Organization</span>
            <button
              className="sidebar-onboard-btn"
              onClick={onOpenOnboardModal}
              title="Onboard new customer company"
            >
              + Onboard
            </button>
          </div>
          <div className="sidebar-org-select-wrapper">
            <select
              className="sidebar-org-select"
              value={currentOrgId}
              onChange={(e) => setCurrentOrgId(e.target.value)}
            >
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name} ({org.active_units} Units)
                </option>
              ))}
            </select>
          </div>
          {currentOrg && (
            <div className="sidebar-org-meta">
              <span className="org-tier-badge">{currentOrg.tier || 'Enterprise'}</span>
              <span className="org-units-count">{currentOrg.active_units || 100} Managed Units</span>
            </div>
          )}
        </div>
      )}

      {/* Navigation Links Grouped */}
      <nav className="sidebar-nav-container">
        {navSections.map((sec) => (
          <div key={sec.group} className="nav-group-section">
            {!collapsed && <div className="nav-group-title">{sec.group}</div>}
            <div className="nav-group-items">
              {sec.items.map((item) => {
                const isActive = activeHub === item.id;
                return (
                  <button
                    key={item.id}
                    className={`sidebar-nav-item ${isActive ? 'active' : ''}`}
                    onClick={() => {
                      setActiveHub(item.id);
                      if (setSidebarOpen) setSidebarOpen(false);
                    }}
                    title={`${item.label} — ${item.sub}`}
                  >
                    <div className="nav-item-icon-box">
                      {item.icon}
                    </div>
                    {!collapsed && (
                      <div className="nav-item-content">
                        <div className="nav-item-label-row">
                          <span className="nav-item-label">{item.label}</span>
                          {item.badge && (
                            <span className={`nav-item-badge ${item.badgeColor || 'cyan'}`}>
                              {item.badge}
                            </span>
                          )}
                        </div>
                        <span className="nav-item-sub">{item.sub}</span>
                      </div>
                    )}
                    {isActive && <div className="nav-active-indicator" />}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Sidebar Footer Telemetry Box */}
      {!collapsed && (
        <div className="sidebar-telemetry-box">
          <div className="telemetry-box-header">
            <span className="indicator-dot pulse-dot" style={{ background: 'var(--emerald)' }}></span>
            <span className="telemetry-status-text">Autonomous Engine</span>
          </div>
          <div className="telemetry-metrics-grid">
            <div className="telemetry-metric-item" title="PostgreSQL pgvector Semantic Chunks">
              <span className="telemetry-metric-val">{Number(telemetry.totalChunks || 9300).toLocaleString()}</span>
              <span className="telemetry-metric-lbl">pgvector Chunks</span>
            </div>
            <div className="telemetry-metric-item" title="Meterless World Model Event Sourcing">
              <span className="telemetry-metric-val">{telemetry.worldEvents || 0}</span>
              <span className="telemetry-metric-lbl">World Events</span>
            </div>
          </div>
          <div className="telemetry-pill-footer">
            <span className="telemetry-source-tag">Zetaris SQL</span>
            <span className="telemetry-ai-tag">Meterless</span>
          </div>
        </div>
      )}
    </aside>
  );
}
