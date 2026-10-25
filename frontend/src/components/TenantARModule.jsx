import React, { useState } from 'react';

export default function TenantARModule({
  summary,
  leases,
  selectedLease,
  activeCaseData,
  isInvestigating,
  onSelectLease,
  onInvestigateCase,
  onSubmitDecision,
  onRefreshWorldModel,
  onOpenInvestigationModal,
  hasInvestigationResult
}) {
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState('lease');
  const [managerNote, setManagerNote] = useState('');
  const [decisionFeedback, setDecisionFeedback] = useState('');

  // Multi-Agent Orchestrator Workflows
  const [isCrossValidating, setIsCrossValidating] = useState(false);
  const [crossValidationResult, setCrossValidationResult] = useState(null);
  const [crossValidationErr, setCrossValidationErr] = useState(null);

  const [isAssessingHabitability, setIsAssessingHabitability] = useState(false);
  const [habitabilityRiskResult, setHabitabilityRiskResult] = useState(null);
  const [habitabilityErr, setHabitabilityErr] = useState(null);

  const fmtMoney = (n) => '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const filteredLeases = leases.filter((l) => {
    if (filter !== 'all' && l.reconciliation_status !== filter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const match =
        l.lease_id.toLowerCase().includes(q) ||
        (l.tenant1 && l.tenant1.toLowerCase().includes(q)) ||
        (l.unit && l.unit.toLowerCase().includes(q)) ||
        (l.address && l.address.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  const lease = activeCaseData?.lease || selectedLease || {};
  const recon = activeCaseData?.reconciliation || {};
  const financialRecords = activeCaseData?.financial_records || [];
  const workOrders = activeCaseData?.work_orders || [];
  const events = activeCaseData?.events || [];
  const latestState = activeCaseData?.latest_state || {};

  const handleDecision = async (approved, action) => {
    const note = managerNote.trim() || (approved ? 'Reconciled with zero variance.' : 'Flagged for manager investigation.');
    const res = await onSubmitDecision(approved, action, note);
    if (res) {
      setDecisionFeedback(`Decision recorded: [${res.state.toUpperCase()}]. ${res.warning || ''}`);
      setManagerNote('');
      setTimeout(() => setDecisionFeedback(''), 6000);
    }
  };

  const handleRunCrossValidation = async () => {
    if (!lease.lease_id) return;
    setIsCrossValidating(true);
    setCrossValidationErr(null);
    try {
      const res = await fetch('/api/orchestrator/workflows/lease-cross-validation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Organization-Id': 'ORG-APEX'
        },
        body: JSON.stringify({ lease_id: lease.lease_id })
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setCrossValidationResult(data);
    } catch (err) {
      setCrossValidationErr(err.message);
    } finally {
      setIsCrossValidating(false);
    }
  };

  const handleRunHabitabilityAssessment = async () => {
    if (!lease.lease_id) return;
    setIsAssessingHabitability(true);
    setHabitabilityErr(null);
    try {
      const res = await fetch('/api/orchestrator/workflows/habitability-risk', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Organization-Id': 'ORG-APEX'
        },
        body: JSON.stringify({
          lease_id: lease.lease_id,
          jurisdiction: 'California'
        })
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setHabitabilityRiskResult(data);
    } catch (err) {
      setHabitabilityErr(err.message);
    } finally {
      setIsAssessingHabitability(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* KPI Dashboard Row */}
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-accent-bar accent-cyan"></div>
          <div className="kpi-label">
            <span>Portfolio Leases</span>
            <span className="pill" style={{ fontSize: 9 }}>Active REIT</span>
          </div>
          <div className="kpi-value">{summary.total_leases || 100}</div>
          <div className="kpi-sub">Units Under Autonomous Audit</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-emerald"></div>
          <div className="kpi-label">
            <span>Reconciled Match</span>
            <span className="pill emerald" style={{ fontSize: 9 }}>100% Match</span>
          </div>
          <div className="kpi-value">
            {summary.reconciled_count || 0}
            <span style={{ fontSize: 13, color: 'var(--text-dim)', fontWeight: 500, marginLeft: 4 }}>
              ({summary.reconciled_percentage || 0}%)
            </span>
          </div>
          <div className="kpi-sub">
            <span style={{ color: 'var(--emerald)' }}>▲ Clean zero-variance book</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-purple"></div>
          <div className="kpi-label">
            <span>Total Rent Invoiced</span>
            <span className="pill purple" style={{ fontSize: 9 }}>Gross AR</span>
          </div>
          <div className="kpi-value">{fmtMoney(summary.total_rent_invoiced_usd)}</div>
          <div className="kpi-sub">Current Monthly Accrual</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-rose"></div>
          <div className="kpi-label">
            <span>Audit Discrepancies</span>
            <span className="pill rose" style={{ fontSize: 9 }}>Action Gate</span>
          </div>
          <div className="kpi-value">
            {summary.flagged_discrepancies || 0}
            <span style={{ fontSize: 13, color: 'var(--text-dim)', fontWeight: 500, marginLeft: 4 }}>
              ({fmtMoney(summary.total_variance_usd)})
            </span>
          </div>
          <div className="kpi-sub">
            <span style={{ color: 'var(--rose)' }}>● Under Agent Investigation</span>
          </div>
        </div>
      </div>

      {/* Main Workspace Grid */}
      <div className="workspace-grid">
        {/* Left Directory Pane */}
        <aside className="directory-pane">
          <div className="directory-header">
            <div className="directory-title">
              <svg className="icon" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
              <span>Tenant Accounts Directory</span>
            </div>
            <span className="pill" style={{ fontSize: 10 }}>{filteredLeases.length} Accounts</span>
          </div>

          <div className="directory-controls">
            <div className="search-box-wrapper">
              <svg className="icon search-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input
                type="text"
                className="search-input-modern"
                placeholder="Search lease ID, tenant, unit, address..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button className="clear-search-btn" onClick={() => setSearch('')} title="Clear search">&times;</button>
              )}
            </div>

            <div className="dropdown-filter-container">
              <label className="dropdown-filter-label">Reconciliation Status:</label>
              <select
                className="directory-select-dropdown"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">All Accounts ({leases.length})</option>
                <option value="reconciled">✓ Matched (Clean Zero-Variance) ({leases.filter(l => l.reconciliation_status === 'reconciled').length})</option>
                <option value="partial_payment">⚠️ Partial Payment (Variance) ({leases.filter(l => l.reconciliation_status === 'partial_payment').length})</option>
                <option value="unmatched_bank">● Under Review (Action Gate) ({leases.filter(l => l.reconciliation_status !== 'reconciled' && l.reconciliation_status !== 'partial_payment').length})</option>
              </select>
            </div>
          </div>

          <div className="lease-list">
            {filteredLeases.map((l) => {
              const isSelected = l.lease_id === lease.lease_id;
              const isReconciled = l.reconciliation_status === 'reconciled';
              const isPartial = l.reconciliation_status === 'partial_payment';
              return (
                <div
                  key={l.lease_id}
                  className={`lease-card ${isSelected ? 'selected' : ''}`}
                  onClick={() => onSelectLease(l.lease_id)}
                >
                  <div className="card-row-top">
                    <span className="lease-id-badge">{l.lease_id}</span>
                    <span className={`pill ${isReconciled ? 'emerald' : isPartial ? 'amber' : 'rose'}`} style={{ fontSize: 9, padding: '1px 6px' }}>
                      {l.reconciliation_status ? l.reconciliation_status.replace('_', ' ').toUpperCase() : 'PENDING'}
                    </span>
                  </div>
                  <div className="card-tenant">{l.tenant1} {l.tenant2 ? `& ${l.tenant2}` : ''}</div>
                  <div className="card-address">Unit {l.unit} · {l.address}</div>
                  <div className="card-footer">
                    <span className="card-rent">{fmtMoney(l.monthly_rent_usd)}/mo</span>
                    <span className={`card-variance ${isReconciled ? 'zero' : 'neg'}`}>
                      {isReconciled ? '✓ Matched' : '⚠️ Variance Detected'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        {/* Right Studio Pane */}
        <section className="studio-pane">
          {/* Active Case Banner */}
          <div className="case-banner">
            <div className="case-info">
              <div className="case-title">
                <span>{lease.lease_id || 'SELECT ACCOUNT'}</span>
                <span className={`pill ${recon.status === 'reconciled' ? 'emerald' : 'rose'}`}>
                  {recon.status ? recon.status.toUpperCase() : 'NEEDS INVESTIGATION'}
                </span>
              </div>
              <div className="case-meta">
                <span>Tenant: <strong>{lease.tenant1 || 'N/A'}</strong></span>
                <span>Unit: <strong>{lease.unit || 'N/A'}</strong></span>
                <span>Rent Due: <strong>{fmtMoney(lease.monthly_rent_usd)}</strong></span>
                <span>Deposit: <strong>{fmtMoney(lease.security_deposit_usd)}</strong></span>
              </div>
            </div>

            <div className="case-actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button
                className="btn"
                style={{ background: 'rgba(99, 102, 241, 0.15)', borderColor: 'rgba(99, 102, 241, 0.4)', color: 'var(--text-heading)' }}
                onClick={handleRunCrossValidation}
                disabled={isCrossValidating || !lease.lease_id}
                title="Execute 4-agent collaborative lease cross-validation DAG"
              >
                {isCrossValidating ? (
                  <>
                    <span className="spinner"></span>
                    <span>Validating 4 Agents...</span>
                  </>
                ) : (
                  <>
                    <svg className="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><polyline points="9 15 12 18 16 14"/></svg>
                    <span>Cross-Validate Lease DAG</span>
                  </>
                )}
              </button>

              <button
                className="btn btn-primary"
                onClick={onInvestigateCase}
                disabled={isInvestigating}
              >
                {isInvestigating ? (
                  <>
                    <span className="spinner"></span>
                    <span>Running Multi-Agent Flow...</span>
                  </>
                ) : (
                  <>
                    <svg className="icon" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    <span>Run Multi-Agent Investigation</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Cross-Validation Orchestration Result Panel */}
          {crossValidationErr && (
            <div className="discrepancy-callout review" style={{ margin: '4px 0' }}>
              <strong>Cross-Validation Error:</strong> {crossValidationErr}
            </div>
          )}

          {crossValidationResult && (
            <div style={{
              background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(6, 182, 212, 0.06))',
              border: '1px solid rgba(99, 102, 241, 0.3)',
              borderRadius: 'var(--radius-md)',
              padding: 16,
              display: 'flex',
              flexDirection: 'column',
              gap: 12
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                    ⚡ 4-Agent Lease Cross-Validation Pipeline
                  </span>
                  <span className={`pill ${crossValidationResult.status === 'cross_validated' ? 'emerald' : 'amber'}`}>
                    {crossValidationResult.status}
                  </span>
                  <span className="pill cyan">
                    Composite Confidence: {Math.round((crossValidationResult.composite_confidence || 0.95) * 100)}%
                  </span>
                </div>
                <button
                  className="btn btn-subtle btn-sm"
                  onClick={() => setCrossValidationResult(null)}
                  style={{ fontSize: 11, padding: '2px 8px' }}
                >
                  ✕ Close
                </button>
              </div>

              {/* Steps Progress */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
                {(crossValidationResult.steps || []).map((st, sIdx) => (
                  <div key={sIdx} style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 6,
                    padding: '8px 10px',
                    fontSize: 11
                  }}>
                    <div style={{ fontWeight: 700, color: 'var(--text-heading)', display: 'flex', justifyContent: 'space-between' }}>
                      <span>Step {sIdx + 1}: {st.agent}</span>
                      <span style={{ color: 'var(--emerald)' }}>✓</span>
                    </div>
                    <div style={{ color: 'var(--text-dim)', marginTop: 2, fontSize: 10 }}>
                      Outcome: {st.outcome || 'Passed'}
                    </div>
                  </div>
                ))}
              </div>

              {/* Discrepancies Callout */}
              {(crossValidationResult.discrepancies || []).length > 0 ? (
                <div style={{ background: 'rgba(244, 63, 94, 0.1)', border: '1px solid rgba(244, 63, 94, 0.25)', borderRadius: 6, padding: '8px 12px', fontSize: 11 }}>
                  <strong style={{ color: 'var(--rose)' }}>Discrepancies Detected:</strong>
                  <ul style={{ paddingLeft: 18, marginTop: 4, color: 'var(--text-main)' }}>
                    {crossValidationResult.discrepancies.map((d, dIdx) => (
                      <li key={dIdx}>{typeof d === 'string' ? d : JSON.stringify(d)}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div style={{ color: 'var(--emerald)', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>✓</span>
                  <span>Zero contract discrepancies found between OCR lease extraction, tenant AR ledger, and financial records.</span>
                </div>
              )}
            </div>
          )}

          {/* 3-Way Match Matrix Cards */}
          <div className="ledger-grid">
            <div className="ledger-card">
              <div className="ledger-header">
                <span className="ledger-tag cyan">1. Lease Due AR</span>
                <span className="pill" style={{ fontSize: 10 }}>Contract Ledger</span>
              </div>
              <div className="ledger-amount">{fmtMoney(recon.invoice_cents ? recon.invoice_cents / 100 : lease.monthly_rent_usd)}</div>
              <div className="ledger-meta-row">
                <span>Contract Due Date:</span>
                <span className="ledger-meta-val">1st of Month</span>
              </div>
              <div className="ledger-meta-row">
                <span>Unit Reference:</span>
                <span className="ledger-meta-val">Unit {lease.unit}</span>
              </div>
            </div>

            <div className="ledger-card">
              <div className="ledger-header">
                <span className="ledger-tag purple">2. Tenant Payment Receipt</span>
                <span className="pill purple" style={{ fontSize: 10 }}>Internal Ledger</span>
              </div>
              <div className="ledger-amount" style={{ color: 'var(--purple)' }}>
                {fmtMoney(recon.verified_paid_cents ? recon.verified_paid_cents / 100 : (recon.status === 'reconciled' ? lease.monthly_rent_usd : 0))}
              </div>
              <div className="ledger-meta-row">
                <span>Receipt Number:</span>
                <span className="ledger-meta-val">REC-{lease.lease_id ? lease.lease_id.replace('LEASE-', '') : '0000'}</span>
              </div>
              <div className="ledger-meta-row">
                <span>Method / Gateway:</span>
                <span className="ledger-meta-val">ACH Direct Debit</span>
              </div>
            </div>

            <div className="ledger-card">
              <div className="ledger-header">
                <span className="ledger-tag emerald">3. Bank Statement Feed</span>
                <span className="pill emerald" style={{ fontSize: 10 }}>Zetaris / Banking</span>
              </div>
              <div className="ledger-amount" style={{ color: 'var(--emerald)' }}>
                {fmtMoney(recon.bank_cleared_cents ? recon.bank_cleared_cents / 100 : (recon.status === 'reconciled' ? lease.monthly_rent_usd : 0))}
              </div>
              <div className="ledger-meta-row">
                <span>Clearing Presentation:</span>
                <span className="ledger-meta-val">{recon.status === 'reconciled' ? 'Cleared & Posted' : 'Flagged Discrepancy'}</span>
              </div>
              <div className="ledger-meta-row">
                <span>Trace Reference:</span>
                <span className="ledger-meta-val">TRX-{lease.lease_id ? lease.lease_id.replace('LEASE-', '') : '0000'}</span>
              </div>
            </div>
          </div>

          {/* Discrepancy Callout Banner */}
          <div className={`discrepancy-callout ${recon.status === 'reconciled' ? 'reconciled' : recon.status === 'partial_payment' ? 'partial' : 'review'}`}>
            <svg className="icon" style={{ width: 20, height: 20, flexShrink: 0 }} viewBox="0 0 24 24">
              {recon.status === 'reconciled' ? (
                <polyline points="20 6 9 17 4 12" />
              ) : (
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
              )}
            </svg>
            <div>
              {recon.status === 'reconciled' ? (
                <><strong>Zero Discrepancy:</strong> 100% matched across billed lease invoice, tenant payment receipt, and cleared bank statement.</>
              ) : recon.status === 'partial_payment' ? (
                <><strong>Partial Payment Variance:</strong> Cleared {fmtMoney(recon.verified_paid_cents / 100)} of {fmtMoney(recon.invoice_cents / 100)} due (Variance: -{fmtMoney(recon.difference_cents / 100)}).</>
              ) : (
                <><strong>Ledger Discrepancy:</strong> {typeof recon.reason === 'string' ? recon.reason : (recon.reason?.reason || 'Unmatched transactions present on account requiring manager review.')}</>
              )}
            </div>
          </div>

          {/* Autonomous Multi-Agent Investigation Finding & Recommendation */}
          {(latestState?.recommendation || activeCaseData?.recommendation) && (
            <div
              style={{
                background: 'rgba(8,145,178,0.06)',
                border: '1px solid rgba(8,145,178,0.25)',
                borderRadius: 'var(--radius-sm)',
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                boxShadow: 'var(--card-shadow)'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <svg className="icon" style={{ color: 'var(--primary)', width: 16, height: 16 }} viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 14 14" />
                  </svg>
                  <span style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', color: 'var(--primary)', letterSpacing: '0.04em' }}>
                    Agent Investigation Finding & Recommendation
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {onOpenInvestigationModal && hasInvestigationResult && (
                    <button
                      className="btn"
                      style={{ padding: '3px 8px', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                      onClick={onOpenInvestigationModal}
                      title="Open Full Multi-Agent Investigation Popup Dialog"
                    >
                      <svg className="icon" style={{ width: 12, height: 12 }} viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
                      <span>Open Popup Dialog</span>
                    </button>
                  )}
                  <span className="pill purple" style={{ fontSize: 9, padding: '1px 6px' }}>
                    World Model Event #{latestState?.version || 'Latest'}
                  </span>
                </div>
              </div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)', lineHeight: 1.5 }}>
                {latestState?.recommendation || activeCaseData?.recommendation}
              </div>
              {(latestState?.narrative || activeCaseData?.narrative) && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6, borderTop: '1px solid var(--border-subtle)', paddingTop: 8 }}>
                  {latestState?.narrative || activeCaseData?.narrative}
                </div>
              )}
            </div>
          )}

          {/* Interactive Evidence Tabs Card */}
          <div className="tabs-card">
            <div className="tab-nav">
              <button className={`tab-btn ${activeTab === 'lease' ? 'active' : ''}`} onClick={() => setActiveTab('lease')}>
                <span>Lease Agreement</span>
              </button>
              <button className={`tab-btn ${activeTab === 'ledger' ? 'active' : ''}`} onClick={() => setActiveTab('ledger')}>
                <span>Payment Evidence</span>
              </button>
              <button className={`tab-btn ${activeTab === 'workorders' ? 'active' : ''}`} onClick={() => setActiveTab('workorders')}>
                <span>Work Orders ({workOrders.length})</span>
              </button>
              <button className={`tab-btn ${activeTab === 'world' ? 'active' : ''}`} onClick={() => setActiveTab('world')}>
                <span>World Model & DAG</span>
              </button>
              <button className={`tab-btn ${activeTab === 'audit' ? 'active' : ''}`} onClick={() => setActiveTab('audit')}>
                <span>Audit JSONL</span>
              </button>
            </div>

            <div className="tab-content">
              {activeTab === 'lease' && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div>
                      <strong style={{ fontSize: 14, color: 'var(--text-heading)' }}>Residential Lease Agreement</strong>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Signed: {lease.contract_date} · Move-in: {lease.move_in_date}</div>
                    </div>
                    <span className="pill emerald">Legally Executed</span>
                  </div>
                  <div className="briefing-box" style={{ background: 'var(--bg-inset)', border: '1px solid var(--border-subtle)' }}>
                    <div style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>
                      {lease.lease_text || 'Standard California Association of Realtors Residential Lease Agreement. Monthly rent payable on the 1st. Tenant shall not deduct repair costs from rent without written landlord authorization.'}
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'ledger' && (
                <div className="evidence-list">
                  {financialRecords.length > 0 ? (
                    financialRecords.map((r, i) => (
                      <div key={i} className="evidence-card">
                        <div className="evidence-header">
                          <span className="evidence-id">{r.source ? r.source.toUpperCase() : 'LEDGER ENTRY'}</span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--primary)' }}>{fmtMoney(r.amount_usd)}</span>
                        </div>
                        <div className="evidence-body">
                          <strong>Date:</strong> {r.date} · <strong>Memo:</strong> {r.description || 'Rental disbursement transaction'}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: 20 }}>
                      No direct ledger records indexed for this account.
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'workorders' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {/* Habitability Assessment Action Bar */}
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    background: 'var(--surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 6,
                    padding: '8px 12px'
                  }}>
                    <div>
                      <strong style={{ fontSize: 13, color: 'var(--text-heading)' }}>Maintenance & SLA Tracking</strong>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                        Jurisdiction: California Civil Code § 1941.1 (Warranty of Habitability)
                      </div>
                    </div>
                    <button
                      className="btn"
                      style={{ background: 'rgba(245, 158, 11, 0.15)', borderColor: 'rgba(245, 158, 11, 0.4)', color: 'var(--text-heading)', fontSize: 12 }}
                      onClick={handleRunHabitabilityAssessment}
                      disabled={isAssessingHabitability || !lease.lease_id}
                      title="Run cross-agent habitability and rent withholding risk assessment"
                    >
                      {isAssessingHabitability ? (
                        <>
                          <span className="spinner"></span>
                          <span>Assessing Risk...</span>
                        </>
                      ) : (
                        <>
                          <svg className="icon" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                          <span>Assess Habitability & Withholding Risk</span>
                        </>
                      )}
                    </button>
                  </div>

                  {habitabilityErr && (
                    <div className="discrepancy-callout review">
                      <strong>Risk Assessment Error:</strong> {habitabilityErr}
                    </div>
                  )}

                  {/* Habitability Risk Assessment Result Card */}
                  {habitabilityRiskResult && (
                    <div style={{
                      background: habitabilityRiskResult.severity === 'critical' ? 'rgba(244, 63, 94, 0.08)' : 'rgba(245, 158, 11, 0.08)',
                      border: `1px solid ${habitabilityRiskResult.severity === 'critical' ? 'rgba(244, 63, 94, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`,
                      borderRadius: 8,
                      padding: 14,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                            🛡️ Habitability Risk Assessment
                          </span>
                          <span className={`pill ${habitabilityRiskResult.severity === 'critical' ? 'rose' : habitabilityRiskResult.severity === 'elevated' ? 'amber' : 'emerald'}`}>
                            {habitabilityRiskResult.severity?.toUpperCase()} SEVERITY
                          </span>
                          <span className="pill cyan">
                            Risk Score: {habitabilityRiskResult.habitability_risk_score} / 100
                          </span>
                        </div>
                        <button
                          className="btn btn-subtle btn-sm"
                          onClick={() => setHabitabilityRiskResult(null)}
                          style={{ fontSize: 11, padding: '2px 8px' }}
                        >
                          ✕ Close
                        </button>
                      </div>

                      <div style={{ fontSize: 12, color: 'var(--text-main)', lineHeight: 1.5 }}>
                        <strong>Rent Withholding Exposure:</strong> {habitabilityRiskResult.rent_withholding_risk ? '⚠️ YES — Tenant may legally withhold rent under statutory habitability remedies' : '✓ NO — Routine maintenance; rent withholding not legally justified'}
                      </div>

                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        <strong>Immediate Required Action:</strong> {habitabilityRiskResult.immediate_action_required || 'Monitor repair to completion within SLA'}
                      </div>

                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                        <strong>Legal Basis & Statutory Timeline:</strong> {habitabilityRiskResult.legal_basis || 'California Civil Code § 1941.1 / § 1942'} · Max statutory window: {habitabilityRiskResult.statutory_timeline_days || 30} days
                      </div>

                      {habitabilityRiskResult.communication_draft && (
                        <div style={{ marginTop: 6, padding: 8, background: 'var(--surface)', borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--primary)', marginBottom: 2 }}>
                            ✉️ AUTOMATED NOTICE DRAFT (TEMPLATE-BACKED)
                          </div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-heading)' }}>
                            Subject: {habitabilityRiskResult.communication_draft.rendered_subject}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                            Recipient: {habitabilityRiskResult.communication_draft.recipient}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  <div className="evidence-list">
                    {workOrders.length > 0 ? (
                      workOrders.map((w) => (
                        <div key={w.work_order_id} className="evidence-card">
                          <div className="evidence-header">
                            <div>
                              <span className="evidence-id">{w.work_order_id}</span>
                              <span className={`pill ${w.priority === 'High' ? 'rose' : 'amber'}`} style={{ marginLeft: 6, fontSize: 10 }}>
                                {w.priority} Priority
                              </span>
                              <span className="pill" style={{ fontSize: 10 }}>Status: {w.status}</span>
                            </div>
                            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-heading)' }}>
                              Est: {fmtMoney(w.estimated_cost_usd)}
                            </span>
                          </div>
                          <div className="evidence-body">
                            <strong>{w.category}:</strong> {w.description}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
                            <span>Reported: {w.reported_date}</span> · <span>Tech: {w.technician || 'Assigned'}</span> · <span>Notes: {w.technician_notes || 'None'}</span>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: 20 }}>
                        No maintenance work orders reported for this unit.
                      </div>
                    )}
                  </div>
                </div>
              )}

              {activeTab === 'world' && (
                <div>
                  <div style={{ marginBottom: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                      Event-Sourced Case Progression & Lineage DAG
                    </span>
                    <button className="btn" onClick={onRefreshWorldModel}>Refresh Event Log</button>
                  </div>
                  <div className="event-stream">
                    {events.length > 0 ? (
                      events.slice(-10).reverse().map((ev, i) => (
                        <div key={i} className="event-row">
                          <div className="event-meta">
                            <span className="event-tag">{ev.canonical_id}</span>
                            <strong style={{ color: 'var(--text-heading)' }}>{ev.event_type}</strong>
                            <span className="pill" style={{ fontSize: 10, padding: '2px 6px' }}>v{ev.version}</span>
                          </div>
                          <div className="event-time">{new Date(ev.created_at).toLocaleTimeString()}</div>
                        </div>
                      ))
                    ) : (
                      <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: 20 }}>
                        No events recorded in World Model stream.
                      </div>
                    )}
                  </div>
                  <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
                      Derived Latest State JSON (Materialized Projection):
                    </div>
                    <pre className="code-view">{JSON.stringify(latestState, null, 2)}</pre>
                  </div>
                </div>
              )}

              {activeTab === 'audit' && (
                <div>
                  <div style={{ marginBottom: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                    Continuous tamper-evident JSONL audit event logs:
                  </div>
                  <pre className="code-view">
                    {events.map((e) => JSON.stringify(e)).join('\n') || '{"status": "Audit stream active", "engine": "Meterless World Model"}'}
                  </pre>
                </div>
              )}
            </div>
          </div>

          {/* Property Manager Decision & Sign-off Dock */}
          <div className="manager-dock">
            <div style={{ flex: 1, minWidth: 260 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                Property Manager Action Gate & Audit Sign-Off
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                Deterministic audit trail required under SOC2/GAAP. Immutably logged into Meterless World Model DAG.
              </div>
              {decisionFeedback && (
                <div style={{ marginTop: 6, fontSize: 12, color: 'var(--emerald)', fontWeight: 600 }}>
                  {decisionFeedback}
                </div>
              )}
            </div>

            <input
              type="text"
              className="decision-input"
              placeholder="Enter resolution notes, bank statement slip trace #, or tenant dispute reason..."
              value={managerNote}
              onChange={(e) => setManagerNote(e.target.value)}
            />

            <div className="decision-actions">
              <button className="btn btn-emerald" onClick={() => handleDecision(true, 'approved')}>
                <svg className="icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
                <span>Approve Match</span>
              </button>
              <button className="btn btn-rose" onClick={() => handleDecision(false, 'escalate_tenant_dispute')}>
                <svg className="icon" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                <span>Escalate Review</span>
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
