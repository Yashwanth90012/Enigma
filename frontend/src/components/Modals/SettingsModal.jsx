import React, { useState } from 'react';

export default function SettingsModal({
  isOpen,
  onClose,
  config,
  onSaveConfig
}) {
  const [financeSource, setFinanceSource] = useState(config.finance_source || 'fixture');
  const [zetarisKey, setZetarisKey] = useState(config.zetaris_key || '');
  const [aiProvider, setAiProvider] = useState(config.ai_provider || 'offline');
  const [meterlessModel, setMeterlessModel] = useState(config.meterless_model || 'nvidia/nemotron-4-340b-instruct');
  const [meterlessToken, setMeterlessToken] = useState(config.meterless_token || '');
  const [isSaving, setIsSaving] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      await onSaveConfig({
        finance_source: financeSource,
        zetaris_key: zetarisKey,
        ai_provider: aiProvider,
        meterless_model: meterlessModel,
        meterless_token: meterlessToken
      });
      onClose();
    } catch (err) {
      alert('Failed to save settings: ' + err.message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">Sponsor Integrations & Cloud Infrastructure</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: 13 }}>
          {/* Zetaris Integration */}
          <div className="kpi-card" style={{ padding: 14 }}>
            <div className="kpi-label">
              <span>Zetaris SQL Data Federation</span>
              <span className="pill active" style={{ fontSize: 9 }}>Lakehouse REST</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
              <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                Financial Ledger Source:
                <select
                  value={financeSource}
                  onChange={(e) => setFinanceSource(e.target.value)}
                  style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
                >
                  <option value="fixture">PostgreSQL Fixture Ledgers (Offline Demo)</option>
                  <option value="zetaris">Zetaris Live SQL REST Query (/sql-editor/sqls/run)</option>
                </select>
              </label>
              <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                Zetaris API Bearer Token:
                <input
                  type="password"
                  placeholder="Enter Zetaris Bearer Token"
                  value={zetarisKey}
                  onChange={(e) => setZetarisKey(e.target.value)}
                  style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
                />
              </label>
            </div>
          </div>

          {/* Meterless / NVIDIA Nemotron AI Reasoner */}
          <div className="kpi-card" style={{ padding: 14 }}>
            <div className="kpi-label">
              <span>Meterless Nightshift / NVIDIA Nemotron Reasoner</span>
              <span className="pill purple" style={{ fontSize: 9 }}>Nemotron-4-340B</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
              <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                AI Provider Mode:
                <select
                  value={aiProvider}
                  onChange={(e) => setAiProvider(e.target.value)}
                  style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
                >
                  <option value="offline">Offline Deterministic Synthesis (Safe Demo)</option>
                  <option value="meterless">Meterless Nightshift (Live NVIDIA Nemotron lane)</option>
                </select>
              </label>
              <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                NVIDIA Nemotron Lane Model ID:
                <input
                  type="text"
                  value={meterlessModel}
                  onChange={(e) => setMeterlessModel(e.target.value)}
                  style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
                />
              </label>
              <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                Meterless Runtime Token:
                <input
                  type="password"
                  placeholder="Bearer Token for Nightshift"
                  value={meterlessToken}
                  onChange={(e) => setMeterlessToken(e.target.value)}
                  style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
                />
              </label>
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSaving}
            style={{ width: '100%', justifyContent: 'center', padding: 12, marginTop: 4 }}
          >
            {isSaving ? (
              <>
                <span className="spinner"></span>
                <span>Applying Cloud Configurations...</span>
              </>
            ) : (
              <span>Apply Configuration & Test Endpoints</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
