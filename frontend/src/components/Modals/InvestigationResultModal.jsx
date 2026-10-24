import React, { useEffect } from 'react';

export default function InvestigationResultModal({
  isOpen,
  onClose,
  investigationData,
  onApplyAction
}) {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !investigationData) return null;

  const res = investigationData;
  const outcome = res.result || {};
  const reasonText =
    outcome.reason ||
    outcome.reason_code ||
    (typeof outcome === 'string' ? outcome : 'Investigation complete');
  const recommendation = res.recommendation || 'No action required.';
  const narrative = res.narrative || '';
  const evidenceList = Array.isArray(res.evidence) ? res.evidence.slice(0, 3) : [];
  const status = outcome.status || 'needs_review';
  const isMatch = status === 'reconciled' || outcome.reason_code === 'EXACT_MATCH';

  const fmtMoney = (cents) => '$' + (Number(cents || 0) / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="modal-overlay active" onClick={onClose} role="dialog" aria-modal="true">
      <div
        className="modal-card"
        style={{ maxWidth: 740, width: '94%' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 8,
                background: isMatch ? 'var(--emerald-glow)' : 'rgba(244,63,94,0.12)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: isMatch ? 'var(--emerald)' : 'var(--rose)'
              }}
            >
              <svg className="icon" style={{ width: 20, height: 20 }} viewBox="0 0 24 24">
                {isMatch ? (
                  <polyline points="20 6 9 17 4 12" />
                ) : (
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
                )}
              </svg>
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <h3 style={{ fontSize: 17, fontWeight: 800, color: 'var(--text-heading)', margin: 0 }}>
                  Multi-Agent Investigation Complete
                </h3>
                <span className={`pill ${isMatch ? 'emerald' : 'rose'}`} style={{ fontSize: 10 }}>
                  {outcome.reason_code || status.toUpperCase()}
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                Case Identifier: <strong style={{ color: 'var(--primary)', fontFamily: 'var(--font-mono)' }}>{res.case_id}</strong> · Meterless World Model Event #{res.world_event_id || '3084'}
              </div>
            </div>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            &times;
          </button>
        </div>

        {/* Modal Body */}
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Key Metric Financial Strip */}
          {outcome.invoice_cents !== undefined && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 10,
                background: 'var(--bg-inset)',
                padding: '12px 14px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)'
              }}
            >
              <div>
                <span style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 700 }}>
                  Billed Due
                </span>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 800, color: 'var(--text-heading)' }}>
                  {fmtMoney(outcome.invoice_cents)}
                </div>
              </div>
              <div>
                <span style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 700 }}>
                  Bank Verified Cleared
                </span>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 800, color: 'var(--emerald)' }}>
                  {fmtMoney(outcome.verified_paid_cents)}
                </div>
              </div>
              <div>
                <span style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 700 }}>
                  Net Variance
                </span>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 16,
                    fontWeight: 800,
                    color: outcome.difference_cents > 0 ? 'var(--rose)' : 'var(--emerald)'
                  }}
                >
                  {outcome.difference_cents > 0 ? `-${fmtMoney(outcome.difference_cents)}` : '$0.00'}
                </div>
              </div>
            </div>
          )}

          {/* Diagnosis / Reason Box */}
          <div
            style={{
              padding: '12px 14px',
              borderRadius: 'var(--radius-sm)',
              background: isMatch ? 'rgba(16,185,129,0.06)' : 'rgba(244,63,94,0.06)',
              border: `1px solid ${isMatch ? 'rgba(16,185,129,0.25)' : 'rgba(244,63,94,0.25)'}`
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: isMatch ? 'var(--emerald)' : 'var(--rose)', marginBottom: 4 }}>
              Agent Diagnosis Finding
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-heading)', lineHeight: 1.5 }}>
              {reasonText}
            </div>
          </div>

          {/* Recommendation Box */}
          <div
            style={{
              padding: '12px 14px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(8,145,178,0.08)',
              border: '1px solid rgba(8,145,178,0.25)'
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--primary)', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
              <svg className="icon" style={{ width: 14, height: 14 }} viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
              <span>Autonomous Action Recommendation</span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-heading)', lineHeight: 1.5 }}>
              {recommendation}
            </div>
          </div>

          {/* Narrative Analysis */}
          {narrative && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                Multi-Agent Narrative Breakdown & Work Order Correlation
              </div>
              <div
                style={{
                  fontSize: 12,
                  lineHeight: 1.6,
                  color: 'var(--text-main)',
                  background: 'var(--bg-inset)',
                  padding: 12,
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  maxHeight: 140,
                  overflowY: 'auto'
                }}
              >
                {narrative}
              </div>
            </div>
          )}

          {/* pgvector RAG Chunk Evidence */}
          {evidenceList.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6 }}>
                pgvector RAG Citations ({evidenceList.length} Chunks Evaluated)
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 110, overflowY: 'auto' }}>
                {evidenceList.map((ev, i) => (
                  <div
                    key={i}
                    style={{
                      fontSize: 11,
                      padding: '6px 10px',
                      background: 'var(--bg-card)',
                      borderRadius: 6,
                      border: '1px solid var(--border-subtle)',
                      color: 'var(--text-muted)'
                    }}
                  >
                    <span style={{ color: 'var(--primary)', fontWeight: 700 }}>
                      Chunk #{ev.chunk_id || i + 1} (Score: {ev.rrf_score ? ev.rrf_score.toFixed(4) : '0.016'}):
                    </span>{' '}
                    {(ev.text || '').slice(0, 160)}...
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            Requires Human Approval: <strong style={{ color: res.requires_human_approval ? 'var(--amber)' : 'var(--emerald)' }}>{res.requires_human_approval ? 'Yes (Risk Gate Active)' : 'No (Automated)'}</strong>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={onClose}>
              Dismiss
            </button>
            {onApplyAction && (
              <button
                className="btn btn-primary"
                onClick={() => {
                  onApplyAction(recommendation);
                  onClose();
                }}
              >
                Apply Recommendation
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
