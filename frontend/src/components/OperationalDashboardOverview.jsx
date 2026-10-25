import React, { useState, useEffect } from 'react';

export default function OperationalDashboardOverview({ currentOrgId = 'ORG-APEX' }) {
  const [data, setData] = useState(null);
  const [agentTelemetry, setAgentTelemetry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isExpanded, setIsExpanded] = useState(true);

  const fetchOverview = async () => {
    try {
      setLoading(true);
      setError(null);
      const [ovRes, telRes] = await Promise.all([
        fetch(`/api/dashboard/overview?organization_id=${encodeURIComponent(currentOrgId || 'all')}`),
        fetch('/api/orchestrator/telemetry').catch(() => null)
      ]);
      if (!ovRes.ok) throw new Error(`HTTP ${ovRes.status}`);
      const json = await ovRes.json();
      setData(json);

      if (telRes && telRes.ok) {
        const telJson = await telRes.json();
        setAgentTelemetry(telJson);
      }
    } catch (err) {
      console.error('Error fetching dashboard overview:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
    const interval = setInterval(fetchOverview, 30000); // 30s auto-refresh
    return () => clearInterval(interval);
  }, [currentOrgId]);

  const fmtMoney = (n) =>
    '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  if (loading && !data) {
    return (
      <div className="card" style={{ padding: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span className="indicator-dot pulse-dot" style={{ background: 'var(--primary)' }}></span>
        <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading real-time operational intelligence across multi-agent workflows...</span>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="card" style={{ padding: 16, borderLeft: '4px solid var(--rose)' }}>
        <div style={{ fontSize: 13, color: 'var(--rose)', fontWeight: 600 }}>Operational telemetry unavailable: {error}</div>
        <button className="btn btn-sm btn-subtle" style={{ marginTop: 8 }} onClick={fetchOverview}>Retry</button>
      </div>
    );
  }

  const {
    leases = {},
    rent_collection = {},
    maintenance = {},
    vendor_ap = {},
    compliance = {},
    documents = {},
    financial_data_source = {},
    notifications = {}
  } = data || {};

  return (
    <div className="card" style={{ padding: '16px 20px', border: '1px solid var(--border)', background: 'var(--surface)' }}>
      {/* Header bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: isExpanded ? 16 : 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: 'linear-gradient(135deg, rgba(8, 145, 178, 0.2), rgba(16, 185, 129, 0.2))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--primary)',
            fontWeight: 800
          }}>
            ⚡
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-heading)' }}>
                Operational Command Center & Agent Telemetry
              </span>
              <span className={`pill ${financial_data_source.status === 'operational' ? 'emerald' : 'amber'}`} style={{ fontSize: 10 }}>
                {financial_data_source.effective_source === 'zetaris' ? 'Zetaris Virtual Data Fabric' : 'PostgreSQL Live Fixture'}
              </span>
              <span className="pill" style={{ fontSize: 10 }}>
                Freshness: {new Date(financial_data_source.freshness || Date.now()).toLocaleTimeString()}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
              Autonomous monitoring across resident lifecycle, rent ledger, maintenance SLAs, vendor AP, and compliance gates.
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            className="btn btn-sm btn-subtle"
            onClick={fetchOverview}
            disabled={loading}
            title="Refresh operational telemetry"
            style={{ fontSize: 11 }}
          >
            {loading ? 'Refreshing...' : '↻ Refresh'}
          </button>
          <button
            className="btn btn-sm btn-subtle"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? 'Collapse panel' : 'Expand panel'}
            style={{ fontSize: 11 }}
          >
            {isExpanded ? 'Hide Details ▲' : 'Show Details ▼'}
          </button>
        </div>
      </div>

      {isExpanded && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 14,
          paddingTop: 12,
          borderTop: '1px solid var(--border-subtle)'
        }}>
          {/* Card 1: Lease Expirations & Renewals */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid var(--primary)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Leases & Expirations
              </span>
              <span className="pill cyan" style={{ fontSize: 9 }}>90-Day Window</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {leases.expiring_next_90_days ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                expiring of {leases.total ?? 0} active
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Renewal automation workflow active
            </div>
          </div>

          {/* Card 2: Rent Collection & Overdue Balances */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid var(--rose)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Rent AR & Overdue
              </span>
              <span className={`pill ${rent_collection.flagged_discrepancies > 0 ? 'rose' : 'emerald'}`} style={{ fontSize: 9 }}>
                {rent_collection.flagged_discrepancies > 0 ? `${rent_collection.flagged_discrepancies} Overdue` : 'Zero Overdue'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {fmtMoney(rent_collection.total_variance_usd)}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                uncollected of {fmtMoney(rent_collection.total_invoiced_usd)}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              {rent_collection.reconciled_count ?? 0} settled zero-variance accounts
            </div>
          </div>

          {/* Card 3: Maintenance & SLA Monitoring */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid var(--amber)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Maintenance & SLAs
              </span>
              <span className={`pill ${maintenance.breached_sla_count > 0 ? 'rose' : 'emerald'}`} style={{ fontSize: 9 }}>
                {maintenance.breached_sla_count ?? 0} Breached
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {maintenance.open_count ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                open ({maintenance.urgent_open ?? 0} urgent/emergency)
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Autonomous vendor dispatch & tracking
            </div>
          </div>

          {/* Card 4: Vendor AP & 4-Way Reconciliation */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid var(--purple)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Vendor AP Matching
              </span>
              <span className={`pill ${vendor_ap.disputed_count > 0 ? 'rose' : 'purple'}`} style={{ fontSize: 9 }}>
                {vendor_ap.disputed_count > 0 ? `${vendor_ap.disputed_count} Disputed` : 'In Order'}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {fmtMoney(vendor_ap.total_billed_usd)}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                ({vendor_ap.unpaid_invoices_count ?? 0} pending pay)
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              {vendor_ap.uncashed_float_count ?? 0} floating unpresented checks
            </div>
          </div>

          {/* Card 5: Compliance & Risk Register */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid #f97316'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Compliance & Risk
              </span>
              <span className={`pill ${compliance.open_risks_count > 0 ? 'amber' : 'emerald'}`} style={{ fontSize: 9 }}>
                {compliance.open_risks_count ?? 0} Active Findings
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {compliance.critical_high_risks ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                high/critical risks ({compliance.pending_approvals ?? 0} approval gates)
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Autonomous jurisdiction audit active
            </div>
          </div>

          {/* Card 6: Document Intelligence & RAG */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid #06b6d4'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Document Intelligence
              </span>
              <span className="pill cyan" style={{ fontSize: 9 }}>Hybrid RAG</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {documents.total_documents ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                vectorized documents
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              {documents.unverified_count > 0 ? `⚠️ ${documents.unverified_count} need review` : 'All documents OCR verified'}
            </div>
          </div>

          {/* Card 7: Notification Delivery & Email Pipeline */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid #10b981'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Notification Pipeline
              </span>
              <span className="pill emerald" style={{ fontSize: 9 }}>42 Templates</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {notifications.total_notifications ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                dispatches logged ({notifications.simulated ?? 0} simulated)
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              {notifications.failed > 0 ? `⚠️ ${notifications.failed} delivery failures` : 'Zero delivery failures in queue'}
            </div>
          </div>

          {/* Card 8: Agent Execution Observability & Latency */}
          <div style={{
            background: 'var(--surface-hover)',
            padding: '12px 14px',
            borderRadius: 8,
            borderLeft: '3px solid #6366f1'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Agent Observability
              </span>
              <span className="pill cyan" style={{ fontSize: 9 }}>13 Agents</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
                {agentTelemetry?.total_decisions ?? 0}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                decisions ({agentTelemetry?.average_latency_ms ?? 0}ms avg latency)
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Human review rate: {agentTelemetry?.human_review_rate_pct ?? 0}% · Abstention: {agentTelemetry?.abstention_rate_pct ?? 0}%
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
