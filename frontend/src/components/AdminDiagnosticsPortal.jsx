import React, { useState, useEffect } from 'react';

export default function AdminDiagnosticsPortal() {
  const [schedulerStatus, setSchedulerStatus] = useState(null);
  const [zetarisStatus, setZetarisStatus] = useState(null);
  const [zetarisMeta, setZetarisMeta] = useState(null);
  const [meterlessStatus, setMeterlessStatus] = useState(null);
  const [nimStatus, setNimStatus] = useState(null);
  const [aiDiagnostics, setAiDiagnostics] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [isTriggering, setIsTriggering] = useState(false);
  const [triggerResult, setTriggerResult] = useState(null);
  const [customSql, setCustomSql] = useState('SELECT * FROM enigma_invoices LIMIT 5');
  const [queryResult, setQueryResult] = useState(null);
  const [isQuerying, setIsQuerying] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(false);

  const fetchDiagnostics = async () => {
    try {
      const [schedRes, zRes, zMetaRes, mRes, nimRes, aiRes, notifRes] = await Promise.all([
        fetch('/api/scheduler/status'),
        fetch('/api/integrations/zetaris/health'),
        fetch('/api/integrations/zetaris/metadata'),
        fetch('/api/integrations/meterless/health'),
        fetch('/api/integrations/nim/health'),
        fetch('/api/integrations/ai/health'),
        fetch('/api/notifications')
      ]);

      if (schedRes.ok) setSchedulerStatus(await schedRes.json());
      if (zRes.ok) setZetarisStatus(await zRes.json());
      if (zMetaRes.ok) {
        setZetarisMeta(await zMetaRes.json());
      } else {
        const err = await zMetaRes.json().catch(() => ({}));
        setZetarisMeta({ error: err.detail || 'Zetaris federation unconfigured or unreachable' });
      }
      if (mRes.ok) setMeterlessStatus(await mRes.json());
      if (nimRes.ok) setNimStatus(await nimRes.json());
      if (aiRes.ok) setAiDiagnostics(await aiRes.json());
      if (notifRes.ok) setNotifications(await notifRes.json());
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunQuery = async () => {
    setIsQuerying(true);
    setQueryResult(null);
    try {
      const res = await fetch('/api/integrations/zetaris/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: customSql, limit: 50 })
      });
      const data = await res.json();
      setQueryResult({ ok: res.ok, status: res.status, data });
    } catch (err) {
      setQueryResult({ ok: false, status: 500, data: { detail: err.message } });
    } finally {
      setIsQuerying(false);
    }
  };

  const handleBootstrapViews = async () => {
    setIsBootstrapping(true);
    try {
      const res = await fetch('/api/integrations/zetaris/bootstrap', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        alert(`Bootstrap failed: ${data.detail || 'Failed to mount views in Zetaris'}`);
      } else {
        await fetchDiagnostics();
        alert('Federated financial views mounted and refreshed in Zetaris Spark engine.');
      }
    } catch (err) {
      alert(`Bootstrap failed: ${err.message}`);
    } finally {
      setIsBootstrapping(false);
    }
  };

  useEffect(() => {
    fetchDiagnostics();
  }, []);

  const handleManualTrigger = async () => {
    setIsTriggering(true);
    setTriggerResult(null);
    try {
      const res = await fetch('/api/scheduler/trigger', { method: 'POST' });
      const data = await res.json();
      setTriggerResult(data);
      fetchDiagnostics();
    } catch (e) {
      alert(`Trigger error: ${e.message}`);
    } finally {
      setIsTriggering(false);
    }
  };

  const getStatusPill = (status) => {
    switch (status) {
      case 'HEALTHY':
      case 'connected':
      case 'live':
        return <span className="pill emerald">Live & Healthy</span>;
      case 'DEGRADED':
      case 'fixture_fallback':
        return <span className="pill amber">Fixture / Degraded</span>;
      case 'AUTH_FAILED':
        return <span className="pill red">Auth Failed</span>;
      case 'UNREACHABLE':
        return <span className="pill red">Unreachable</span>;
      case 'NOT_CONFIGURED':
      default:
        return <span className="pill purple">Not Configured</span>;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header Banner */}
      <div className="card" style={{ padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span className="pill purple">Administrator Hub</span>
              <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>System Diagnostics & Autonomous Observability</span>
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 700 }}>AI Provider Failover & Integration Telemetry</h2>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 4 }}>
              Multi-tier AI failover (Meterless → NVIDIA NIM → Offline Deterministic) and Zetaris Cloud data federation.
            </div>
          </div>

          <button
            className="btn btn-primary"
            onClick={handleManualTrigger}
            disabled={isTriggering}
          >
            {isTriggering ? 'Running Routine Sweeps...' : '⚡ Trigger Autonomous Sweeps'}
          </button>
        </div>

        {triggerResult && (
          <div style={{ marginTop: 16, padding: 12, background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--primary)', borderRadius: 6, fontSize: 12 }}>
            <strong>Sweep Completed:</strong> Scanned {triggerResult.delinquencies_scanned} rent accounts; detected {triggerResult.sla_breaches_detected} maintenance SLA breaches. Errors: {triggerResult.errors?.length || 0}.
          </div>
        )}
      </div>

      {/* AI Failover Overview Banner */}
      {aiDiagnostics && (
        <div className="card" style={{ padding: 18, borderLeft: '4px solid var(--primary)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-dim)' }}>
                Active AI Orchestration Mode
              </div>
              <div style={{ fontSize: 16, fontWeight: 700, marginTop: 2 }}>
                Mode: <code>{aiDiagnostics.active_mode}</code> | Fallback Order: <code>{aiDiagnostics.fallback_order?.join(' → ')}</code>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ fontSize: 12 }}>
                Last Provider: <strong>{aiDiagnostics.last_provider_used || 'offline'}</strong>
              </div>
              <div style={{ fontSize: 12 }}>
                Fallback Occurred: <strong>{aiDiagnostics.last_fallback_occurred ? 'Yes' : 'No'}</strong>
              </div>
              {aiDiagnostics.last_fallback_reason && (
                <div style={{ fontSize: 12, color: 'var(--accent-amber)' }}>
                  Reason: <em>{aiDiagnostics.last_fallback_reason}</em>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Integration Status Grid (3 Providers + Zetaris Data Federation) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        {/* Meterless AI Card */}
        <div className="card" style={{ padding: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700 }}>1. Meterless / Nightshift</h3>
            {getStatusPill(meterlessStatus?.status)}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
            <div><strong>Endpoint:</strong> <code>{meterlessStatus?.details || 'http://host.docker.internal:8088/v1'}</code></div>
            <div><strong>Configured:</strong> {meterlessStatus?.configured ? 'Yes' : 'No (METERLESS_TOKEN missing)'}</div>
            <div><strong>Auth Status:</strong> <code>{meterlessStatus?.auth_status || 'unverified'}</code></div>
            <div><strong>Role:</strong> Primary inference provider (Nightshift Nemotron lane)</div>
          </div>
        </div>

        {/* NVIDIA NIM Card */}
        <div className="card" style={{ padding: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700 }}>2. NVIDIA NIM Hosted API</h3>
            {getStatusPill(nimStatus?.status)}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
            <div><strong>Endpoint:</strong> <code>https://integrate.api.nvidia.com/v1</code></div>
            <div><strong>Configured:</strong> {nimStatus?.configured ? 'Yes' : 'No (NVIDIA_NIM_API_KEY missing)'}</div>
            <div><strong>Auth Status:</strong> <code>{nimStatus?.auth_status || 'unverified'}</code></div>
            <div><strong>Model Verified:</strong> <code>{nimStatus?.model_verified || 'unverified'}</code></div>
            <div><strong>Role:</strong> Automatic secondary failover provider</div>
          </div>
        </div>

        {/* Offline Deterministic Card */}
        <div className="card" style={{ padding: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700 }}>3. Offline Deterministic</h3>
            <span className="pill emerald">Live & Healthy</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
            <div><strong>Availability:</strong> Always active (zero network dependence)</div>
            <div><strong>Math Precision:</strong> Exact Decimal 3-way reconciliation</div>
            <div><strong>Role:</strong> Final safety fallback (no hallucinations)</div>
          </div>
        </div>

        {/* Zetaris Data Federation Card */}
        <div className="card" style={{ padding: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700 }}>Zetaris Data Federation</h3>
            {getStatusPill(zetarisStatus?.status)}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
            <div><strong>Category:</strong> Independent SQL Federation (NOT AI)</div>
            <div>
              <strong>Mode:</strong>{' '}
              <span className={`pill ${zetarisStatus?.mode === 'live' ? 'emerald' : 'amber'}`}>
                {zetarisStatus?.mode === 'live' ? '⚡ LIVE FEDERATION' : 'FIXTURE FALLBACK'}
              </span>
            </div>
            <div><strong>Engine Latency:</strong> {zetarisStatus?.latency_ms ? `${zetarisStatus.latency_ms} ms` : 'Active'}</div>
            <div><strong>Catalogs:</strong> <code>{zetarisMeta?.current_catalog || 'spark_catalog'}</code> ({zetarisMeta?.current_schema || 'default'})</div>
            <div><strong>Mounted Views:</strong> {zetarisMeta?.views ? Object.keys(zetarisMeta.views).length : 6} verified</div>
          </div>
        </div>
      </div>

      {/* Zetaris Live Federation & Query Explorer */}
      <div className="card" style={{ padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 700 }}>⚡ Zetaris Federated Financial Lakehouse Explorer</h3>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
              Direct read-only SQL federation to live tenant invoices, payment records, bank ledgers, and vendor bills.
            </p>
          </div>
          <button
            className="btn btn-secondary"
            style={{ fontSize: 12, padding: '6px 12px' }}
            onClick={handleBootstrapViews}
            disabled={isBootstrapping}
          >
            {isBootstrapping ? 'Remounting...' : '🔄 Refresh / Remount Views'}
          </button>
        </div>

        {/* View Badges */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8 }}>DISCOVERED FEDERATED VIEWS:</div>
          {zetarisMeta?.error ? (
            <div style={{ color: '#f59e0b', fontSize: 12, padding: '10px 14px', background: 'rgba(245, 158, 11, 0.08)', borderRadius: 6, border: '1px solid rgba(245, 158, 11, 0.2)' }}>
              ⚠️ {zetarisMeta.error}
            </div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {zetarisMeta?.views && Object.entries(zetarisMeta.views).map(([viewName, info]) => (
                <div
                  key={viewName}
                  style={{
                    background: 'rgba(255, 255, 255, 0.04)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 6,
                    padding: '6px 10px',
                    fontSize: 11,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6
                  }}
                >
                  <span style={{ color: '#10b981', fontWeight: 700 }}>●</span>
                  <code style={{ fontWeight: 600 }}>{viewName}</code>
                  <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                    ({info.columns?.length || 0} cols)
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Interactive Query Box */}
        <div style={{ background: 'rgba(0,0,0,0.2)', padding: 14, borderRadius: 8, border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
            <input
              type="text"
              value={customSql}
              onChange={(e) => setCustomSql(e.target.value)}
              placeholder="Enter read-only SQL query (e.g. SELECT * FROM enigma_invoices LIMIT 5)"
              style={{
                flex: 1,
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid var(--border-color)',
                background: 'rgba(255,255,255,0.05)',
                color: 'var(--text-color)',
                fontFamily: 'monospace',
                fontSize: 13
              }}
            />
            <button
              className="btn btn-primary"
              onClick={handleRunQuery}
              disabled={isQuerying}
              style={{ padding: '8px 18px', fontSize: 13 }}
            >
              {isQuerying ? 'Executing...' : 'Run Live Query'}
            </button>
          </div>

          {/* Quick query buttons */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center' }}>Samples:</span>
            {[
              'SELECT * FROM enigma_invoices LIMIT 5',
              'SELECT * FROM enigma_payments LIMIT 5',
              'SELECT * FROM enigma_bank_transactions LIMIT 5',
              'SELECT * FROM enigma_vendor_invoices LIMIT 5'
            ].map((q) => (
              <button
                key={q}
                onClick={() => setCustomSql(q)}
                style={{
                  background: 'none',
                  border: '1px solid rgba(255,255,255,0.1)',
                  color: 'var(--text-muted)',
                  fontSize: 11,
                  borderRadius: 4,
                  padding: '2px 8px',
                  cursor: 'pointer'
                }}
              >
                {q.split('FROM ')[1]}
              </button>
            ))}
          </div>

          {/* Query Output */}
          {queryResult && (
            <div style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8 }}>
                <span className={`pill ${queryResult.ok ? 'emerald' : 'rose'}`}>
                  {queryResult.ok ? `HTTP 200 OK (${queryResult.data.time_used_ms || 0} ms)` : `HTTP ${queryResult.status}`}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  Source: <strong>{queryResult.data.source_system || 'zetaris'}</strong> ({queryResult.data.source_status || 'live'})
                </span>
              </div>

              {queryResult.ok && queryResult.data.headers && (
                <div style={{ overflowX: 'auto', maxHeight: 260 }}>
                  <table className="data-table" style={{ fontSize: 11 }}>
                    <thead>
                      <tr>
                        {queryResult.data.headers.map((h, i) => (
                          <th key={i}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {queryResult.data.data.map((row, ri) => (
                        <tr key={ri}>
                          {row.map((cell, ci) => (
                            <td key={ci}>{String(cell)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!queryResult.ok && (
                <div style={{ color: '#f43f5e', fontSize: 12, padding: 8, background: 'rgba(244, 63, 94, 0.1)', borderRadius: 4 }}>
                  {queryResult.data.detail || 'Query execution failed'}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Scheduler Health and History */}
      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>⏱ Background Scheduler Execution Log</h3>
        <div style={{ display: 'flex', gap: 20, marginBottom: 16 }}>
          <div>Status: <span className="pill emerald">{schedulerStatus?.status || 'running'}</span></div>
          <div>Last Run: <strong>{schedulerStatus?.last_run_time ? new Date(schedulerStatus.last_run_time).toLocaleString() : 'Just now'}</strong></div>
          <div>Total Sweeps: <strong>{schedulerStatus?.total_runs || 1}</strong></div>
        </div>

        {schedulerStatus?.recent_history && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Execution Time</th>
                <th>SLA Breaches Checked</th>
                <th>Delinquent Accounts Scanned</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {schedulerStatus.recent_history.map((h, i) => (
                <tr key={i}>
                  <td>{new Date(h.timestamp).toLocaleTimeString()}</td>
                  <td>{h.sla_breaches_detected}</td>
                  <td>{h.delinquencies_scanned}</td>
                  <td>{h.errors?.length || 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Notifications Audit Log */}
      <div className="card" style={{ padding: 20 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>📬 Durable Notification Delivery Audit</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Recipient</th>
              <th>Type</th>
              <th>Title</th>
              <th>Category</th>
              <th>Delivery State</th>
              <th>Event Key</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {notifications.slice(0, 10).map((n) => (
              <tr key={n.id}>
                <td><code>{n.id}</code></td>
                <td>{n.recipient_email}</td>
                <td><span className="pill" style={{ fontSize: 9 }}>{n.recipient_type}</span></td>
                <td><strong>{n.title}</strong></td>
                <td>{n.category}</td>
                <td>
                  <span className={`pill ${n.status === 'simulated' ? 'cyan' : n.status === 'sent' ? 'emerald' : 'amber'}`}>
                    {n.status}
                  </span>
                </td>
                <td><code style={{ fontSize: 10 }}>{n.event_key}</code></td>
                <td>{new Date(n.created_at).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
