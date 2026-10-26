import React, { useState, useEffect } from 'react';

export default function AuditLogsPortal({ currentOrgId = 'ORG-APEX' }) {
  const [logs, setLogs] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [search, setSearch] = useState('');
  const [actorType, setActorType] = useState('all');
  const [action, setAction] = useState('all');
  const [outcome, setOutcome] = useState('all');
  const [page, setPage] = useState(0);
  const limit = 25;

  // Selected event for detail drawer
  const [selectedLog, setSelectedLog] = useState(null);

  const fetchLogs = async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({
        org_id: currentOrgId || 'ORG-APEX',
        limit: String(limit),
        offset: String(page * limit)
      });

      if (search.trim()) params.append('search', search.trim());
      if (actorType !== 'all') params.append('actor_type', actorType);
      if (action !== 'all') params.append('action', action);
      if (outcome !== 'all') params.append('outcome', outcome);

      const res = await fetch(`/api/audit-logs?${params.toString()}`, {
        headers: {
          'X-Organization-Id': currentOrgId || 'ORG-APEX'
        }
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: Failed to fetch audit records`);
      const data = await res.json();
      setLogs(data.logs || []);
      setTotalCount(data.total_count || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [currentOrgId, page, actorType, action, outcome]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setPage(0);
    fetchLogs();
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(logs, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `enigma_audit_logs_${currentOrgId}_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const getOutcomeBadge = (out) => {
    switch (out?.toLowerCase()) {
      case 'success':
        return <span className="pill badge-emerald">✓ SUCCESS</span>;
      case 'failure':
      case 'failed':
        return <span className="pill badge-rose">✕ FAILURE</span>;
      case 'blocked':
        return <span className="pill badge-purple">🛡 BLOCKED</span>;
      case 'pending':
        return <span className="pill badge-amber">⏳ PENDING</span>;
      default:
        return <span className="pill badge-cyan">{out?.toUpperCase() || 'INFO'}</span>;
    }
  };

  const getActorBadge = (type) => {
    switch (type?.toLowerCase()) {
      case 'tenant':
        return <span style={{ color: 'var(--cyan)', fontWeight: 600 }}>👤 Tenant</span>;
      case 'property_manager':
        return <span style={{ color: 'var(--purple)', fontWeight: 600 }}>👔 Property Mgr</span>;
      case 'system':
        return <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>⚙️ System</span>;
      case 'webhook':
        return <span style={{ color: 'var(--emerald)', fontWeight: 600 }}>🔗 Webhook</span>;
      case 'agent':
        return <span style={{ color: 'var(--primary)', fontWeight: 600 }}>🤖 AI Agent</span>;
      default:
        return <span>{type}</span>;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header HUD */}
      <div className="card" style={{ padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 14 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 24 }}>🛡️</span>
              <h2 style={{ fontSize: 20, fontWeight: 800, margin: 0, letterSpacing: '-0.3px' }}>
                Centralized Website Audit Logs
              </h2>
              <span className="pill badge-emerald">Immutable Ledger</span>
            </div>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Comprehensive, tamper-evident audit trail capturing authentication, rent payments, webhooks, statutory escalations, and system operations.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button onClick={fetchLogs} className="btn btn-secondary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>🔄</span> Refresh
            </button>
            <button onClick={handleExportJson} className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span>📥</span> Export JSON
            </button>
          </div>
        </div>

        {/* Filters Toolbar */}
        <div style={{ display: 'flex', gap: 12, marginTop: 20, flexWrap: 'wrap', alignItems: 'center' }}>
          <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: 8, flex: '1 1 280px' }}>
            <input
              type="text"
              placeholder="Search action, resource, actor, or details..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="input-field"
              style={{ width: '100%', padding: '8px 12px', fontSize: 13 }}
            />
            <button type="submit" className="btn btn-secondary" style={{ padding: '8px 14px' }}>
              Search
            </button>
          </form>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <select
              value={actorType}
              onChange={(e) => { setActorType(e.target.value); setPage(0); }}
              className="input-field"
              style={{ padding: '8px 12px', fontSize: 13 }}
            >
              <option value="all">All Actor Types</option>
              <option value="tenant">Tenants</option>
              <option value="property_manager">Property Managers</option>
              <option value="system">System Jobs</option>
              <option value="webhook">Payment Webhooks</option>
              <option value="agent">AI Agents</option>
            </select>

            <select
              value={action}
              onChange={(e) => { setAction(e.target.value); setPage(0); }}
              className="input-field"
              style={{ padding: '8px 12px', fontSize: 13 }}
            >
              <option value="all">All Actions</option>
              <option value="rent_obligation_created">rent_obligation_created</option>
              <option value="checkout_session_created">checkout_session_created</option>
              <option value="rent_payment_initiated">rent_payment_initiated</option>
              <option value="rent_payment_confirmed">rent_payment_confirmed</option>
              <option value="webhook_payment_intent_succeeded">webhook_payment_intent_succeeded</option>
              <option value="notification_dispatched_upcoming_rent_reminder">notification_dispatched_upcoming</option>
              <option value="notification_dispatched_overdue_rent_3day">notification_dispatched_3day</option>
              <option value="legal_notice_approved">legal_notice_approved</option>
              <option value="legal_notice_rejected">legal_notice_rejected</option>
            </select>

            <select
              value={outcome}
              onChange={(e) => { setOutcome(e.target.value); setPage(0); }}
              className="input-field"
              style={{ padding: '8px 12px', fontSize: 13 }}
            >
              <option value="all">All Outcomes</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
              <option value="blocked">Blocked</option>
            </select>
          </div>
        </div>
      </div>

      {/* Main Table Card */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {error && (
          <div style={{ padding: 14, background: 'rgba(239, 68, 68, 0.1)', color: 'var(--rose)', fontSize: 13 }}>
            ⚠️ {error}
          </div>
        )}

        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--surface-hover)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700 }}>Timestamp (UTC)</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700 }}>Action</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700 }}>Actor</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700 }}>Resource</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700 }}>Outcome</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700 }}>Source</th>
                <th style={{ padding: '12px 16px', textAlign: 'right', fontSize: 12, fontWeight: 700 }}>Inspect</th>
              </tr>
            </thead>
            <tbody>
              {loading && logs.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                    Loading audit records...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                    No audit records matching criteria.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr
                    key={log.id}
                    onClick={() => setSelectedLog(log)}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      cursor: 'pointer',
                      background: selectedLog?.id === log.id ? 'var(--surface-hover)' : 'transparent',
                      transition: 'background 0.15s'
                    }}
                  >
                    <td style={{ padding: '10px 16px', fontSize: 12, fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                      {log.timestamp.replace('T', ' ').slice(0, 19)}
                    </td>
                    <td style={{ padding: '10px 16px', fontSize: 13, fontWeight: 600 }}>
                      <code style={{ background: 'var(--surface-hover)', padding: '2px 6px', borderRadius: 4, color: 'var(--primary)' }}>
                        {log.action}
                      </code>
                    </td>
                    <td style={{ padding: '10px 16px', fontSize: 12 }}>
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        {getActorBadge(log.actor_type)}
                        <span style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 140 }}>
                          {log.actor_id}
                        </span>
                      </div>
                    </td>
                    <td style={{ padding: '10px 16px', fontSize: 12 }}>
                      <div>
                        <span style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                          {log.resource_type}:
                        </span>{' '}
                        <strong>{log.resource_id || 'N/A'}</strong>
                      </div>
                    </td>
                    <td style={{ padding: '10px 16px' }}>
                      {getOutcomeBadge(log.outcome)}
                    </td>
                    <td style={{ padding: '10px 16px', fontSize: 11, color: 'var(--text-muted)' }}>
                      {log.source_component}
                    </td>
                    <td style={{ padding: '10px 16px', textAlign: 'right' }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); setSelectedLog(log); }}
                        className="btn btn-sm btn-secondary"
                        style={{ fontSize: 11, padding: '4px 8px' }}
                      >
                        Inspect &rarr;
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', background: 'var(--surface-hover)', fontSize: 13 }}>
          <span style={{ color: 'var(--text-muted)' }}>
            Showing {logs.length} of {totalCount} total audit events
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setPage(Math.max(0, page - 1))}
              disabled={page === 0 || loading}
              className="btn btn-sm btn-secondary"
            >
              &larr; Previous
            </button>
            <span style={{ padding: '4px 10px', fontWeight: 600 }}>
              Page {page + 1} of {Math.max(1, Math.ceil(totalCount / limit))}
            </span>
            <button
              onClick={() => setPage(page + 1)}
              disabled={(page + 1) * limit >= totalCount || loading}
              className="btn btn-sm btn-secondary"
            >
              Next &rarr;
            </button>
          </div>
        </div>
      </div>

      {/* Inspect Event Modal / Drawer */}
      {selectedLog && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.6)',
            zIndex: 1000,
            display: 'flex',
            justifyContent: 'flex-end'
          }}
          onClick={() => setSelectedLog(null)}
        >
          <div
            style={{
              width: '100%',
              maxWidth: 580,
              background: 'var(--surface)',
              height: '100%',
              overflowY: 'auto',
              padding: '24px 28px',
              boxShadow: '-4px 0 20px rgba(0,0,0,0.3)',
              display: 'flex',
              flexDirection: 'column',
              gap: 20
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: 14 }}>
              <div>
                <span className="pill badge-cyan" style={{ fontSize: 10 }}>AUDIT EVENT INSPECTOR</span>
                <h3 style={{ fontSize: 18, fontWeight: 800, margin: '4px 0 0' }}>{selectedLog.action}</h3>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>ID: {selectedLog.id}</span>
              </div>
              <button onClick={() => setSelectedLog(null)} className="btn btn-secondary" style={{ padding: '4px 10px' }}>
                ✕ Close
              </button>
            </div>

            {/* Quick Details Table */}
            <div style={{ background: 'var(--surface-hover)', borderRadius: 8, padding: 14, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 12 }}>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Timestamp (UTC):</span>
                <strong>{selectedLog.timestamp}</strong>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Outcome:</span>
                {getOutcomeBadge(selectedLog.outcome)}
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Actor:</span>
                <strong>{selectedLog.actor_id}</strong> ({selectedLog.actor_type})
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Resource:</span>
                <strong>{selectedLog.resource_type}</strong> ({selectedLog.resource_id})
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Source Component:</span>
                <code>{selectedLog.source_component}</code>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)', display: 'block' }}>Correlation ID:</span>
                <code style={{ fontSize: 10 }}>{selectedLog.correlation_id}</code>
              </div>
            </div>

            {/* Event Details JSON */}
            <div>
              <h4 style={{ fontSize: 13, fontWeight: 700, margin: '0 0 8px', color: 'var(--text-secondary)' }}>Event Details & Payload</h4>
              <pre style={{
                background: '#0f172a',
                color: '#38bdf8',
                padding: 14,
                borderRadius: 8,
                fontSize: 12,
                overflowX: 'auto',
                lineHeight: 1.5
              }}>
                {JSON.stringify(selectedLog.details, null, 2)}
              </pre>
            </div>

            {/* State Diffs */}
            {(selectedLog.before_state || selectedLog.after_state) && (
              <div>
                <h4 style={{ fontSize: 13, fontWeight: 700, margin: '0 0 8px', color: 'var(--text-secondary)' }}>State Transition Diff</h4>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)' }}>Before State:</span>
                    <pre style={{ background: '#0f172a', color: '#cbd5e1', padding: 10, borderRadius: 6, fontSize: 11, overflowX: 'auto' }}>
                      {JSON.stringify(selectedLog.before_state || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--emerald)' }}>After State:</span>
                    <pre style={{ background: '#0f172a', color: '#6ee7b7', padding: 10, borderRadius: 6, fontSize: 11, overflowX: 'auto' }}>
                      {JSON.stringify(selectedLog.after_state || {}, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
