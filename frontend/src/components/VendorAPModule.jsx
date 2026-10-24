import React, { useState } from 'react';

export default function VendorAPModule({
  vendorSummary,
  vendorInvoices,
  vendors,
  selectedInvoiceId,
  walkthroughData,
  isLoadingWalkthrough,
  onSelectInvoice,
  onOpenPayModal,
  onResolveVendorBill
}) {
  const [tradeFilter, setTradeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [pmNotes, setPmNotes] = useState('');
  const [resolutionMsg, setResolutionMsg] = useState('');

  const fmtMoney = (n) => '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const invoicesList = Array.isArray(vendorInvoices) ? vendorInvoices : [];
  const vendorsList = Array.isArray(vendors) ? vendors : [];
  const summary = vendorSummary || {};

  const filteredInvoices = invoicesList.filter((inv) => {
    // 1. Trade filter
    if (tradeFilter !== 'all') {
      const haystack = `${inv?.vendor_trade || ''} ${inv?.item_summary || ''}`.toLowerCase();
      if (!haystack.includes(tradeFilter.toLowerCase())) return false;
    }
    // 2. Status filter
    if (statusFilter !== 'all') {
      const cleared = Number(inv?.cleared_amount_usd || 0);
      const paid = Number(inv?.paid_amount_usd || 0);
      if (statusFilter === 'cleared' && !(cleared > 0)) return false;
      if (statusFilter === 'uncashed' && !(cleared === 0 && paid > 0)) return false;
      if (statusFilter === 'pending' && !(paid === 0)) return false;
    }
    // 3. Search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const match =
        (inv?.id && inv.id.toLowerCase().includes(q)) ||
        (inv?.invoice_number && inv.invoice_number.toLowerCase().includes(q)) ||
        (inv?.vendor_name && inv.vendor_name.toLowerCase().includes(q)) ||
        (inv?.work_order_id && inv.work_order_id.toLowerCase().includes(q)) ||
        (inv?.item_summary && inv.item_summary.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });

  const getTradeClass = (trade) => {
    const t = (trade || '').toLowerCase();
    if (t.includes('bathtub') || t.includes('fixture')) return 'trade-bathtubs';
    if (t.includes('light') || t.includes('electrical')) return 'trade-lights';
    if (t.includes('hvac') || t.includes('heat')) return 'trade-hvac';
    if (t.includes('appliance')) return 'trade-appliances';
    if (t.includes('material') || t.includes('hardware')) return 'trade-materials';
    return 'trade-sinks';
  };

  const getPaymentMethodBadge = (pm) => {
    const method = (pm || '').toLowerCase();
    if (method === 'cashiers_check') return <span className="badge-method method-cashier">Cashier Check</span>;
    if (method === 'check') return <span className="badge-method method-check">Corporate Check</span>;
    if (method === 'credit_card') return <span className="badge-method method-card">Credit Card</span>;
    if (method === 'ach_wire') return <span className="badge-method method-ach">ACH / Wire</span>;
    return <span className="badge-method" style={{ background: 'var(--pill-bg)', color: 'var(--text-dim)' }}>Unpaid</span>;
  };

  const getClearingPill = (inv) => {
    const cleared = Number(inv?.cleared_amount_usd || 0);
    const paid = Number(inv?.paid_amount_usd || 0);
    if (cleared === 0 && paid > 0) {
      return <span className="pill amber" style={{ fontSize: 9, padding: '1px 5px' }}>Uncashed Float</span>;
    } else if (paid === 0) {
      return <span className="pill rose" style={{ fontSize: 9, padding: '1px 5px' }}>Pending Pay</span>;
    }
    return <span className="pill emerald" style={{ fontSize: 9, padding: '1px 5px' }}>Cleared</span>;
  };

  const bundle = walkthroughData?.bundle || {};
  const wo = bundle.work_order || {};
  const inv = bundle.invoice || {};
  const pay = bundle.payment || null;
  const bank = bundle.bank_transaction || null;
  const firstEvidence = walkthroughData?.evidence?.[0]?.text || '';

  const handleResolution = async (action) => {
    const note = pmNotes.trim() || `Property manager decision: ${action}`;
    const res = await onResolveVendorBill(selectedInvoiceId, action, note);
    if (res) {
      setResolutionMsg(`Resolution recorded for ${res.case_id}: [${res.state.toUpperCase()}]. ${res.warning || ''}`);
      setPmNotes('');
      setTimeout(() => setResolutionMsg(''), 6000);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* AP KPI Metric Row */}
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-accent-bar accent-purple"></div>
          <div className="kpi-label">
            <span>Total Invoiced AP</span>
            <span className="pill purple" style={{ fontSize: 9 }}>Gross Billed</span>
          </div>
          <div className="kpi-value">{fmtMoney(summary.total_billed_usd)}</div>
          <div className="kpi-sub">
            <span>{summary.total_invoices || 0} Vendor Invoices Processed</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-cyan"></div>
          <div className="kpi-label">
            <span>Disbursed Payments</span>
            <span className="pill active" style={{ fontSize: 9 }}>AP Ledger</span>
          </div>
          <div className="kpi-value">{fmtMoney(summary.total_paid_usd)}</div>
          <div className="kpi-sub">Vouchers, Corporate & Cashier Checks</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-emerald"></div>
          <div className="kpi-label">
            <span>Bank Cleared Feed</span>
            <span className="pill emerald" style={{ fontSize: 9 }}>Presented</span>
          </div>
          <div className="kpi-value">{fmtMoney(summary.total_cleared_usd)}</div>
          <div className="kpi-sub">
            <span style={{ color: 'var(--emerald)' }}>✓ Verified Cash Settlement</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-amber"></div>
          <div className="kpi-label">
            <span>Uncashed Float (Float Alert)</span>
            <span className="pill amber" style={{ fontSize: 9 }}>Stale Checks</span>
          </div>
          <div className="kpi-value">
            {summary.flagged_uncashed || 0}
            <span style={{ fontSize: 13, color: 'var(--text-dim)', fontWeight: 500, marginLeft: 4 }}>
              ({fmtMoney(summary.pending_payment_usd || 0)})
            </span>
          </div>
          <div className="kpi-sub">
            <span style={{ color: 'var(--amber)' }}>⚠️ Floating in-flight checks</span>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-rose"></div>
          <div className="kpi-label">
            <span>Audit Variances</span>
            <span className="pill rose" style={{ fontSize: 9 }}>Action Gate</span>
          </div>
          <div className="kpi-value">{summary.discrepancy_total || 0}</div>
          <div className="kpi-sub">
            <span style={{ color: 'var(--rose)' }}>● Overbilling & Surcharges</span>
          </div>
        </div>
      </div>

      {/* Main Workspace Split Grid */}
      <div className="workspace-grid">
        {/* Left Directory Pane: Vendor Invoices */}
        <aside className="directory-pane">
          <div className="directory-header">
            <div className="directory-title">
              <svg className="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>
              <span>Vendor AP Invoices</span>
            </div>
            <span className="pill purple">{invoicesList.length} Bills</span>
          </div>

          {/* Modern Enterprise Directory Controls: Search & Dual Dropdowns */}
          <div className="directory-controls">
            <div className="search-box-wrapper">
              <svg className="icon search-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input
                type="text"
                className="search-input-modern"
                placeholder="Search bill #, vendor, order, scope..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button className="clear-search-btn" onClick={() => setSearchQuery('')} title="Clear search">&times;</button>
              )}
            </div>

            <div className="dual-filter-row">
              <div className="dropdown-filter-container">
                <label className="dropdown-filter-label">Trade Category:</label>
                <select
                  className="directory-select-dropdown"
                  value={tradeFilter}
                  onChange={(e) => setTradeFilter(e.target.value)}
                >
                  <option value="all">All Trades ({invoicesList.length})</option>
                  <option value="Plumbing">Sinks & Faucets</option>
                  <option value="Fixtures">Bathtubs & Fixtures</option>
                  <option value="Electrical">Lighting & Wiring</option>
                  <option value="HVAC">HVAC & Heating</option>
                  <option value="Appliance">Appliances</option>
                  <option value="Material">Building Materials</option>
                </select>
              </div>

              <div className="dropdown-filter-container">
                <label className="dropdown-filter-label">Clearing Status:</label>
                <select
                  className="directory-select-dropdown"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="all">All Statuses</option>
                  <option value="cleared">✓ Cleared & Settled</option>
                  <option value="uncashed">⚠️ Uncashed Float</option>
                  <option value="pending">● Pending Payment</option>
                </select>
              </div>
            </div>
          </div>

          {/* Invoices List */}
          <div className="lease-list" style={{ maxHeight: 420, overflowY: 'auto' }}>
            {filteredInvoices.length > 0 ? (
              filteredInvoices.map((invItem) => {
                const isSelected = invItem.id === selectedInvoiceId;
                const tradeClass = getTradeClass(invItem.vendor_trade);
                return (
                  <div
                    key={invItem.id}
                    className={`vendor-invoice-item ${isSelected ? 'active' : ''}`}
                    onClick={() => onSelectInvoice(invItem.id)}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                        <span className="lease-id-badge" style={{ fontSize: 10 }}>{invItem.invoice_number || invItem.id}</span>
                        <span className={`vendor-badge-trade ${tradeClass}`}>{(invItem.vendor_trade || 'Trade').split(',')[0]}</span>
                        {getClearingPill(invItem)}
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {invItem.vendor_name || 'Vendor'}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{invItem.item_summary || 'Maintenance Service'}</span>
                        <span>·</span>
                        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)', fontWeight: 600, flexShrink: 0 }}>{invItem.work_order_id || 'WO-Direct'}</span>
                      </div>
                    </div>
                    <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 800, color: 'var(--text-heading)' }}>
                        {fmtMoney(invItem.total_usd)}
                      </div>
                      {getPaymentMethodBadge(invItem.payment_method)}
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{ padding: 30, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
                No vendor bills match the selected trade, status, or search query.
              </div>
            )}
          </div>

          {/* Contracted Vendor Network Collapsible Drawer */}
          <details className="vendor-suppliers-drawer">
            <summary>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <svg className="icon" style={{ width: 14, height: 14, color: 'var(--primary)' }} viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                <span>Contracted Suppliers ({vendorsList.length} Network Trades)</span>
              </div>
              <span className="pill active" style={{ fontSize: 9 }}>Direct Dispatch</span>
            </summary>
            <div className="vendor-suppliers-list">
              {vendorsList.map((v) => (
                <div key={v.id} style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 6, padding: '6px 8px', fontSize: 11 }}>
                  <div style={{ fontWeight: 700, color: 'var(--text-heading)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {v.name}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 3 }}>
                    <span className={`vendor-badge-trade ${getTradeClass(v.trade)}`}>{(v.trade || 'Trade').split(',')[0]}</span>
                    <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{v.payment_terms || 'Net 30'}</span>
                  </div>
                </div>
              ))}
            </div>
          </details>
        </aside>

        {/* Right Studio Pane: Interactive 4-Way Reconciliation Walkthrough */}
        <section className="studio-pane">
          <div className="case-banner">
            <div>
              <div className="lease-id-badge" style={{ fontSize: 11, marginBottom: 4 }}>
                {inv.id ? `${inv.id} · ${inv.invoice_number}` : 'SELECT AN INVOICE'}
              </div>
              <h2 style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-heading)', marginTop: 4 }}>
                {inv.vendor?.name ? `${inv.vendor.name} — ${inv.item_summary}` : 'Autonomous 4-Way Bill Reconciliation'}
              </h2>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                Comparing authorized work order budget vs. vendor PDF extraction vs. payment voucher vs. bank statement clearing feed.
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {selectedInvoiceId && (
                <>
                  <a
                    href={`/api/vendor-invoices/${selectedInvoiceId}/pdf`}
                    target="_blank"
                    rel="noreferrer"
                    className="btn"
                    style={{ textDecoration: 'none' }}
                  >
                    <svg className="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    <span>View Authentic PDF</span>
                  </a>
                  <button className="btn btn-emerald" onClick={() => onOpenPayModal(selectedInvoiceId)}>
                    <svg className="icon" viewBox="0 0 24 24"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>
                    <span>Disburse Payment</span>
                  </button>
                </>
              )}
            </div>
          </div>

          {/* 4-Way Match Status Callout Banner */}
          {walkthroughData && (
            <div className={`discrepancy-callout ${
              walkthroughData.reason_code === 'MATCH_CONFIRMED' ? 'reconciled' :
              walkthroughData.reason_code === 'OVERBILLING_FLAGGED' ? 'review' : 'partial'
            }`}>
              <svg className="icon" style={{ width: 20, height: 20, flexShrink: 0 }} viewBox="0 0 24 24">
                {walkthroughData.reason_code === 'MATCH_CONFIRMED' ? (
                  <polyline points="20 6 9 17 4 12" />
                ) : (
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
                )}
              </svg>
              <div>
                {walkthroughData.reason_code === 'MATCH_CONFIRMED' && (
                  <><strong>100% RECONCILED MATCH:</strong> All 4 financial dimensions (Work Order quote, Vendor PDF line items, payment voucher, and bank clearing) match within allowable tolerance. Zero human exception.</>
                )}
                {walkthroughData.reason_code === 'OVERBILLING_FLAGGED' && (
                  <><strong>⚠️ OVERBILLING EXCEPTION DETECTED:</strong> Vendor billed <strong>{fmtMoney(walkthroughData.billed_cents / 100)}</strong>, exceeding authorized Work Order quote (<strong>{fmtMoney(walkthroughData.quote_cents / 100)}</strong>) by <strong>+{fmtMoney(walkthroughData.variance_cents / 100)}</strong> without an approved change order! Recommendation: {walkthroughData.action_required}</>
                )}
                {walkthroughData.reason_code === 'UNCASHED_CHECK' && (
                  <><strong>⚠️ UNCASHED / STALE CHECK DETECTED:</strong> Corporate check voucher has been issued to vendor, but bank presentation has not cleared (&gt;14 days float). Funds remain encumbered. Recommendation: {walkthroughData.action_required}</>
                )}
                {walkthroughData.reason_code === 'SURCHARGE_VARIANCE' && (
                  <><strong>⚠️ CREDIT CARD / BANK FEE SURCHARGE DETECTED:</strong> Cleared bank debit ({fmtMoney(walkthroughData.cleared_cents / 100)}) exceeds invoice total ({fmtMoney(walkthroughData.billed_cents / 100)}) due to unauthorized processing fee. Recommendation: {walkthroughData.action_required}</>
                )}
                {!['MATCH_CONFIRMED', 'OVERBILLING_FLAGGED', 'UNCASHED_CHECK', 'SURCHARGE_VARIANCE'].includes(walkthroughData.reason_code) && (
                  <><strong>NEEDS REVIEW:</strong> {walkthroughData.diagnosis?.join(' ')} Recommendation: {walkthroughData.action_required}</>
                )}
              </div>
            </div>
          )}

          {/* 5-Step Visual Walkthrough Container */}
          <div className="walkthrough-container">
            {isLoadingWalkthrough ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
                <span className="spinner" style={{ marginBottom: 8 }}></span>
                <div>Executing autonomous 4-way matching across Work Order, PDF Extraction, Payment, and Bank Feed...</div>
              </div>
            ) : walkthroughData ? (
              <>
                {/* Step 1: Work Order Quote & Scope */}
                <div className="walkthrough-card">
                  <div className="walkthrough-step-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className={`step-number-tag ${wo.work_order_id ? 'verified' : 'warning'}`}>1</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                          Dimension 1: Authorized Work Order Quote & Scope
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          Tenant maintenance ticket authorized budget
                        </div>
                      </div>
                    </div>
                    <span className={`pill ${wo.work_order_id ? 'emerald' : 'amber'}`}>
                      {wo.work_order_id ? 'WO-LINKED' : 'DIRECT ORDER'}
                    </span>
                  </div>
                  <div className="dimension-stat-grid">
                    <div>
                      <span className="stat-item-label">Work Order ID</span>
                      <div className="stat-item-value">{wo.work_order_id || 'WO-DIRECT'}</div>
                    </div>
                    <div>
                      <span className="stat-item-label">Trade Category</span>
                      <div style={{ fontWeight: 600, color: 'var(--primary)' }}>{wo.category || inv.vendor?.trade}</div>
                    </div>
                    <div>
                      <span className="stat-item-label">Authorized Quote</span>
                      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, color: 'var(--emerald)' }}>
                        {fmtMoney(wo.estimated_cost_usd || inv.total_usd)}
                      </div>
                    </div>
                    <div>
                      <span className="stat-item-label">Assigned Tech</span>
                      <div style={{ color: 'var(--text-main)', fontWeight: 500 }}>{wo.technician || 'Vendor Field Tech'}</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
                    <strong>Tenant Issue Scope:</strong> {wo.description || inv.item_summary}
                  </div>
                </div>

                {/* Step 2: Vendor PDF Invoice (Extracted via RAG) */}
                <div className="walkthrough-card">
                  <div className="walkthrough-step-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className="step-number-tag verified">2</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                          Dimension 2: Vendor PDF Invoice (Extracted via pgvector RAG)
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {inv.vendor?.name} · Invoice {inv.invoice_number}
                        </div>
                      </div>
                    </div>
                    <span className="pill active">PDF PARSED BY RAG</span>
                  </div>
                  <div className="dimension-stat-grid">
                    <div>
                      <span className="stat-item-label">Invoice Number</span>
                      <div className="stat-item-value">{inv.invoice_number}</div>
                    </div>
                    <div>
                      <span className="stat-item-label">Subtotal (Materials/Labor)</span>
                      <div className="stat-item-value">{fmtMoney(inv.subtotal_usd)}</div>
                    </div>
                    <div>
                      <span className="stat-item-label">Sales Tax (8.25%)</span>
                      <div className="stat-item-value">{fmtMoney(inv.tax_usd)}</div>
                    </div>
                    <div>
                      <span className="stat-item-label">Total Billed</span>
                      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, color: 'var(--purple)' }}>
                        {fmtMoney(inv.total_usd)}
                      </div>
                    </div>
                  </div>
                  {firstEvidence && (
                    <div className="rag-citation-box">
                      <span style={{ color: 'var(--primary)', fontWeight: 700 }}>pgvector RAG Chunk Citation:</span><br />
                      {firstEvidence.slice(0, 240)}...
                    </div>
                  )}
                </div>

                {/* Step 3: Property Manager Payment Voucher */}
                <div className="walkthrough-card">
                  <div className="walkthrough-step-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className={`step-number-tag ${pay ? 'verified' : 'warning'}`}>3</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                          Dimension 3: Property Manager Payment Voucher Disbursed
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          Accounts Payable ledger disbursement format
                        </div>
                      </div>
                    </div>
                    <span className={`pill ${pay ? 'emerald' : 'rose'}`}>
                      {pay ? String(pay.payment_method || 'Voucher').toUpperCase() : 'UNPAID'}
                    </span>
                  </div>
                  {pay ? (
                    <div className="dimension-stat-grid">
                      <div>
                        <span className="stat-item-label">Payment Format</span>
                        <div style={{ fontWeight: 700, color: 'var(--text-heading)' }}>
                          {String(pay.payment_method || 'Voucher').replace('_', ' ').toUpperCase()}
                        </div>
                      </div>
                      <div>
                        <span className="stat-item-label">Check / Auth Ref</span>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--primary)' }}>
                          {pay.reference}
                        </div>
                      </div>
                      <div>
                        <span className="stat-item-label">Disbursed Amount</span>
                        <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, color: 'var(--emerald)' }}>
                          {fmtMoney(pay.amount_usd)}
                        </div>
                      </div>
                      <div>
                        <span className="stat-item-label">Disbursement Date</span>
                        <div style={{ color: 'var(--text-main)', fontWeight: 500 }}>{pay.payment_date}</div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: 12, background: 'rgba(244,63,94,0.06)', border: '1px dashed rgba(244,63,94,0.3)', borderRadius: 8, fontSize: 12, color: 'var(--rose)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>Payment voucher has not yet been issued for this invoice.</span>
                      <button className="btn btn-emerald" style={{ padding: '4px 10px', fontSize: 11 }} onClick={() => onOpenPayModal(selectedInvoiceId)}>
                        Pay Now
                      </button>
                    </div>
                  )}
                </div>

                {/* Step 4: Bank Statement & Credit Card Feed */}
                <div className="walkthrough-card">
                  <div className="walkthrough-step-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className={`step-number-tag ${bank ? 'verified' : (pay ? 'flagged' : 'warning')}`}>4</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                          Dimension 4: Bank Statement / Card Clearing Feed
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          Independent banking ledger presentation & clearing
                        </div>
                      </div>
                    </div>
                    <span className={`pill ${bank ? 'emerald' : (pay ? 'amber' : 'rose')}`}>
                      {bank ? 'CLEARED IN FEED' : (pay ? 'UNCASHED / FLOAT' : 'AWAITING PAYMENT')}
                    </span>
                  </div>
                  {bank ? (
                    <div className="dimension-stat-grid">
                      <div>
                        <span className="stat-item-label">Bank Cleared Amount</span>
                        <div className="stat-item-value">{fmtMoney(bank.amount_usd)}</div>
                      </div>
                      <div>
                        <span className="stat-item-label">Merchant Fee / Surcharge</span>
                        <div style={{ fontFamily: 'var(--font-mono)', color: Number(bank?.merchant_fee_usd || 0) > 0 ? 'var(--rose)' : 'var(--text-muted)', fontWeight: 700 }}>
                          {fmtMoney(bank?.merchant_fee_usd || 0)}
                        </div>
                      </div>
                      <div>
                        <span className="stat-item-label">Cleared Date</span>
                        <div style={{ color: 'var(--text-main)', fontWeight: 500 }}>{bank.clearing_date}</div>
                      </div>
                      <div>
                        <span className="stat-item-label">Bank Trace Reference</span>
                        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)', fontWeight: 700 }}>{bank.reference}</div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: 12, background: 'rgba(245,158,11,0.08)', border: '1px dashed rgba(245,158,11,0.35)', borderRadius: 8, fontSize: 12, color: 'var(--amber)' }}>
                      {pay ? `⚠️ Check #${pay.reference} was disbursed but has not cleared the property manager bank account. Floating unpresented check.` : `No bank transaction present because bill is unpaid.`}
                    </div>
                  )}
                </div>

                {/* Step 5: Agent Reconciliation Diagnosis */}
                <div className="walkthrough-card" style={{ border: '1px solid rgba(8,145,178,0.3)', background: 'rgba(8,145,178,0.03)' }}>
                  <div className="walkthrough-step-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div className={`step-number-tag ${walkthroughData.status === 'reconciled' ? 'verified' : 'flagged'}`}>5</div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--primary)' }}>
                          Dimension 5: Autonomous Multi-Agent Reconciliation Diagnosis
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Deterministic financial audit synthesis</div>
                      </div>
                    </div>
                    <span className={`pill ${walkthroughData.status === 'reconciled' ? 'emerald' : 'rose'}`}>
                      {walkthroughData.reason_code}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--text-main)', marginBottom: 10 }}>
                    {walkthroughData.narrative}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-subtle)', paddingTop: 10, fontSize: 12 }}>
                    <div>
                      <strong>Action Gate Required:</strong> <span style={{ color: 'var(--amber)', fontWeight: 700 }}>{walkthroughData.action_required}</span>
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
                      Entity: {walkthroughData.canonical_id}
                    </div>
                  </div>
                </div>

                {/* Property Manager Resolution & Action Gate */}
                <div className="manager-dock" style={{ marginTop: 10 }}>
                  <div style={{ flex: 1, minWidth: 260 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                      Property Manager Review Gate & Resolution Sign-Off
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      All decisions are immutably logged into the Meterless World Model audit trail.
                    </div>
                    {resolutionMsg && (
                      <div style={{ marginTop: 6, fontSize: 12, color: 'var(--emerald)', fontWeight: 600 }}>
                        {resolutionMsg}
                      </div>
                    )}
                  </div>

                  <input
                    type="text"
                    className="decision-input"
                    placeholder="Enter resolution notes, vendor credit memo reference, or explanation..."
                    value={pmNotes}
                    onChange={(e) => setPmNotes(e.target.value)}
                  />

                  <div className="decision-actions">
                    <button className="btn btn-emerald" onClick={() => handleResolution('approved')}>
                      <svg className="icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
                      <span>Authorize & Approve Match</span>
                    </button>
                    <button className="btn btn-amber" onClick={() => handleResolution('dispute_vendor')}>
                      <svg className="icon" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                      <span>Dispute Overbilling</span>
                    </button>
                    <button className="btn btn-primary" onClick={() => handleResolution('reissue_check')}>
                      <svg className="icon" viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                      <span>Re-Issue Check</span>
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
                <svg className="icon" style={{ width: 32, height: 32, marginBottom: 8, opacity: 0.5 }} viewBox="0 0 24 24">
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <div>No invoice selected. Click an invoice on the left to walk through the 4-way reconciliation steps.</div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
