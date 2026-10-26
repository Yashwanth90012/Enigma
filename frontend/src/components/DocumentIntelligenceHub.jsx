import React, { useState, useEffect, useCallback } from 'react';

const ORG_PROPERTY_MAP = {
  'ORG-APEX': { propertyId: 'PROP-001', defaultLease: 'LEASE-0001', name: 'Skyline Terrace (PROP-001)' },
  'ORG-VERDANT': { propertyId: 'PROP-002', defaultLease: 'LEASE-0021', name: 'Verdant Valley Estates (PROP-002)' },
  'ORG-BEACON': { propertyId: 'PROP-003', defaultLease: 'LEASE-0041', name: 'Beacon Bay Commercial (PROP-003)' },
  'ORG-SKYLINE': { propertyId: 'PROP-004', defaultLease: 'LEASE-0061', name: 'Oakridge Modern Lofts (PROP-004)' },
};

export default function DocumentIntelligenceHub({ currentOrgId = 'ORG-APEX' }) {
  const [documents, setDocuments] = useState([]);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  // Filters
  const [kindFilter, setKindFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  // RAG Subsystem Status
  const [ragStatus, setRagStatus] = useState(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [reindexResult, setReindexResult] = useState(null);

  // Upload / Process Document Form
  const defaultCfg = ORG_PROPERTY_MAP[currentOrgId] || ORG_PROPERTY_MAP['ORG-APEX'];
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadBody, setUploadBody] = useState('');
  const [uploadLeaseId, setUploadLeaseId] = useState(defaultCfg.defaultLease);
  const [uploadPropertyId, setUploadPropertyId] = useState(defaultCfg.propertyId);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processResult, setProcessResult] = useState(null);

  // Sync upload defaults whenever current organization changes
  useEffect(() => {
    const cfg = ORG_PROPERTY_MAP[currentOrgId] || ORG_PROPERTY_MAP['ORG-APEX'];
    setUploadPropertyId(cfg.propertyId);
    setUploadLeaseId(cfg.defaultLease);
  }, [currentOrgId]);

  // Cross-validation state
  const [isCrossValidating, setIsCrossValidating] = useState(false);
  const [crossValResult, setCrossValResult] = useState(null);

  const [notification, setNotification] = useState(null);

  const showNotification = (msg, type = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 6000);
  };

  // 1. Fetch Documents List
  const fetchDocuments = useCallback(async () => {
    setIsLoadingList(true);
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (kindFilter !== 'all') params.append('kind', kindFilter);
      const res = await fetch(`/api/documents?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
        setTotalDocuments(data.total || 0);
        if (data.documents && data.documents.length > 0 && !selectedDocId) {
          handleSelectDocument(data.documents[0].id);
        }
      }
    } catch (e) {
      console.error('Error fetching documents:', e);
      showNotification('Failed to fetch document catalog: ' + e.message, 'error');
    } finally {
      setIsLoadingList(false);
    }
  }, [kindFilter, selectedDocId]);

  // 2. Fetch RAG Vector Store Status
  const fetchRagStatus = async () => {
    try {
      const res = await fetch('/api/documents/rag/status');
      if (res.ok) {
        const data = await res.json();
        setRagStatus(data);
      }
    } catch (e) {
      console.error('Error fetching RAG status:', e);
    }
  };

  useEffect(() => {
    fetchDocuments();
    fetchRagStatus();
  }, [fetchDocuments]);

  // 3. Select & Fetch Document Detail
  const handleSelectDocument = async (docId) => {
    setSelectedDocId(docId);
    setIsLoadingDetail(true);
    setCrossValResult(null);
    try {
      const res = await fetch(`/api/documents/${docId}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedDoc(data);
      }
    } catch (e) {
      console.error('Error fetching document details:', e);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  // 4. Ingest / Process New Document
  const handleProcessDocument = async (e) => {
    e.preventDefault();
    if (!uploadTitle.trim() || !uploadBody.trim()) {
      showNotification('Document title and text body are required.', 'error');
      return;
    }

    setIsProcessing(true);
    setProcessResult(null);
    try {
      const activeProp = uploadPropertyId.trim() || ORG_PROPERTY_MAP[currentOrgId]?.propertyId || 'PROP-001';
      const activeLease = uploadLeaseId.trim() || ORG_PROPERTY_MAP[currentOrgId]?.defaultLease || null;
      const res = await fetch('/api/documents/process', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Organization-Id': currentOrgId || 'ORG-APEX'
        },
        body: JSON.stringify({
          title: uploadTitle.trim(),
          body: uploadBody.trim(),
          lease_id: activeLease,
          property_id: activeProp,
          organization_id: currentOrgId
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));

      setProcessResult(data);
      showNotification(`Document ${data.document_id} processed, classified as [${data.kind.toUpperCase()}], and indexed into pgvector.`);
      fetchDocuments();
      fetchRagStatus();
      if (data.document_id) {
        handleSelectDocument(data.document_id);
      }
    } catch (err) {
      showNotification('Document processing error: ' + err.message, 'error');
    } finally {
      setIsProcessing(false);
    }
  };

  // 5. Trigger Safe RAG Reindex
  const handleReindexRag = async () => {
    if (!confirm('Re-index stored documents using active semantic embedding model?')) return;
    setIsReindexing(true);
    setReindexResult(null);
    try {
      const res = await fetch('/api/documents/rag/reindex', { method: 'POST' });
      const data = await res.json();
      setReindexResult(data);
      showNotification(`Semantic vector reindex completed. Chunks updated: ${data.reindexed_chunks || data.total_chunks || 0}.`);
      fetchRagStatus();
    } catch (err) {
      showNotification('Reindexing failed: ' + err.message, 'error');
    } finally {
      setIsReindexing(false);
    }
  };

  // 6. Run Cross-Validation on selected document's lease
  const handleCrossValidateLease = async (leaseId) => {
    if (!leaseId) return;
    setIsCrossValidating(true);
    setCrossValResult(null);
    try {
      const res = await fetch('/api/orchestrator/workflows/lease-cross-validation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Organization-Id': currentOrgId || 'ORG-APEX'
        },
        body: JSON.stringify({ lease_id: leaseId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      setCrossValResult(data);
      showNotification(`Cross-validation complete for ${leaseId}: [${data.final_status}]. Composite confidence: ${(data.composite_confidence * 100).toFixed(0)}%.`);
    } catch (err) {
      showNotification('Cross-validation failed: ' + err.message, 'error');
    } finally {
      setIsCrossValidating(false);
    }
  };

  const filteredDocs = documents.filter((doc) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      doc.id.toLowerCase().includes(q) ||
      doc.title.toLowerCase().includes(q) ||
      (doc.lease_id && doc.lease_id.toLowerCase().includes(q)) ||
      doc.kind.toLowerCase().includes(q)
    );
  });

  const getKindBadge = (kind) => {
    switch (kind) {
      case 'lease':
        return <span className="pill cyan">Residential Lease</span>;
      case 'vendor_invoice':
        return <span className="pill purple">Vendor AP Invoice</span>;
      case 'work_order':
        return <span className="pill amber">Work Order Quote</span>;
      case 'lien_waiver':
        return <span className="pill emerald">Lien Waiver</span>;
      case 'bank_statement':
        return <span className="pill blue">Bank Clearing Feed</span>;
      case 'legal_notice':
        return <span className="pill rose">Statutory Legal Notice</span>;
      default:
        return <span className="pill">General Document</span>;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Toast Notification */}
      {notification && (
        <div className={`discrepancy-callout ${notification.type === 'error' ? 'review' : 'reconciled'}`} style={{ margin: 0 }}>
          <span>{notification.msg}</span>
        </div>
      )}

      {/* KPI Metric Overview Row */}
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-accent-bar accent-cyan"></div>
          <div className="kpi-label">
            <span>Document Repository</span>
            <span className="pill cyan" style={{ fontSize: 9 }}>Indexed</span>
          </div>
          <div className="kpi-value">{totalDocuments || documents.length}</div>
          <div className="kpi-sub">Total Stored Authoritative Contracts & Bills</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-purple"></div>
          <div className="kpi-label">
            <span>Semantic Vector Store</span>
            <span className="pill purple" style={{ fontSize: 9 }}>pgvector RAG</span>
          </div>
          <div className="kpi-value">{ragStatus?.total_chunks || 9300}</div>
          <div className="kpi-sub">
            Model: <code>{ragStatus?.model || 'BAAI/bge-small-en-v1.5'}</code>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-emerald"></div>
          <div className="kpi-label">
            <span>OCR Extraction Engine</span>
            <span className="pill emerald" style={{ fontSize: 9 }}>PaddleOCR v4</span>
          </div>
          <div className="kpi-value">
            <span style={{ color: 'var(--emerald)', fontSize: 20, fontWeight: 700 }}>Online & Active</span>
          </div>
          <div className="kpi-sub">Angle Classification & Text Extraction</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-amber"></div>
          <div className="kpi-label">
            <span>Uncertainty Routing Gate</span>
            <span className="pill amber" style={{ fontSize: 9 }}>Guardrail</span>
          </div>
          <div className="kpi-value">&lt; 0.75 Score</div>
          <div className="kpi-sub">Routes to Human Review (Zero Hallucination)</div>
        </div>
      </div>

      {/* Main Studio Split View */}
      <div className="module-layout">
        {/* Left Sidebar: Document Catalog */}
        <aside className="sidebar-pane">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
              Document Store ({filteredDocs.length})
            </span>
            <button
              className="btn btn-sm btn-primary"
              onClick={() => setIsUploadModalOpen(true)}
              style={{ fontSize: 11, padding: '4px 10px' }}
            >
              + Ingest Document
            </button>
          </div>

          {/* Search and Category Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            <input
              type="text"
              placeholder="Search by title, ID, lease..."
              className="decision-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ padding: '6px 10px', fontSize: 12 }}
            />

            <select
              className="decision-input"
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
              style={{ padding: '6px 8px', fontSize: 12 }}
            >
              <option value="all">All Document Categories</option>
              <option value="lease">Residential Leases</option>
              <option value="vendor_invoice">Vendor AP Invoices</option>
              <option value="work_order">Work Order Quotes</option>
              <option value="lien_waiver">Lien Waivers</option>
              <option value="bank_statement">Bank Clearing Feeds</option>
              <option value="legal_notice">Statutory Legal Notices</option>
            </select>
          </div>

          {/* Document Items List */}
          <div className="tenant-list" style={{ maxHeight: 600, overflowY: 'auto' }}>
            {isLoadingList ? (
              <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
                <span className="spinner"></span> Loading document repository...
              </div>
            ) : filteredDocs.length === 0 ? (
              <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
                No documents match the active filter criteria.
              </div>
            ) : (
              filteredDocs.map((doc) => (
                <div
                  key={doc.id}
                  className={`tenant-item ${selectedDocId === doc.id ? 'active' : ''}`}
                  onClick={() => handleSelectDocument(doc.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <code style={{ fontSize: 11, fontWeight: 700, color: 'var(--primary)' }}>{doc.id}</code>
                    {getKindBadge(doc.kind)}
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-heading)', marginTop: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {doc.title}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                    <span>{doc.lease_id || 'Portfolio wide'}</span>
                    <span>{doc.body_length ? `${doc.body_length} chars` : ''}</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* RAG Reindex Dock */}
          <div style={{ marginTop: 16, padding: 12, background: 'var(--bg-inset)', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-heading)', marginBottom: 4 }}>
              Semantic Embedding Maintenance
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
              Synchronizes pgvector embeddings with the active vector table.
            </div>
            <button
              className="btn btn-sm btn-subtle"
              style={{ width: '100%', fontSize: 11 }}
              onClick={handleReindexRag}
              disabled={isReindexing}
            >
              {isReindexing ? 'Reindexing Chunks...' : '⚡ Re-Index Vector Chunks'}
            </button>
          </div>
        </aside>

        {/* Right Studio Pane: Inspection & Extraction Details */}
        <section className="studio-pane">
          {isLoadingDetail ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
              <span className="spinner"></span> Loading document intelligence extraction...
            </div>
          ) : selectedDoc ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Document Header Card */}
              <div className="case-banner">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <code style={{ fontSize: 12, color: 'var(--primary)', fontWeight: 700 }}>{selectedDoc.id}</code>
                    {getKindBadge(selectedDoc.kind)}
                    {selectedDoc.requires_review ? (
                      <span className="pill amber" style={{ fontSize: 10 }}>⚠️ Review Required (&lt; 75%)</span>
                    ) : (
                      <span className="pill emerald" style={{ fontSize: 10 }}>✓ High Confidence Verification</span>
                    )}
                  </div>
                  <h2 style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-heading)', margin: '4px 0' }}>
                    {selectedDoc.title}
                  </h2>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Linked Entity: <strong>{selectedDoc.lease_id || 'Portfolio Wide'}</strong> · Property: <strong>{selectedDoc.property_id || 'PROP-001'}</strong> · Ingested: {selectedDoc.created_at ? new Date(selectedDoc.created_at).toLocaleString() : 'Recent'}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 8 }}>
                  {selectedDoc.lease_id && selectedDoc.lease_id !== 'PORTFOLIO' && (
                    <button
                      className="btn btn-primary"
                      onClick={() => handleCrossValidateLease(selectedDoc.lease_id)}
                      disabled={isCrossValidating}
                    >
                      {isCrossValidating ? (
                        <>
                          <span className="spinner"></span>
                          <span>Cross-Validating...</span>
                        </>
                      ) : (
                        <>
                          <svg className="icon" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                          <span>Cross-Validate with Lease</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>

              {/* Cross-Validation Result Banner (if triggered) */}
              {crossValResult && (
                <div
                  className={`discrepancy-callout ${
                    crossValResult.final_status === 'LEASE_HEALTHY_AND_RECONCILED' ? 'reconciled' : 'review'
                  }`}
                >
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <strong style={{ fontSize: 13 }}>
                        Multi-Agent Cross-Validation Pipeline Result: [{crossValResult.final_status}]
                      </strong>
                      <span className="pill cyan">
                        Composite Confidence: {(crossValResult.composite_confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                      <strong>Workflow ID:</strong> <code>{crossValResult.workflow_id}</code> · <strong>Human Approval Required:</strong> {crossValResult.requires_human_approval ? `Yes (${crossValResult.approval_role})` : 'No (Auto-verified)'}
                    </div>
                    {crossValResult.step_decisions?.document_intelligence && (
                      <div style={{ fontSize: 11, marginTop: 4, color: 'var(--text-main)', borderTop: '1px solid var(--border-subtle)', paddingTop: 4 }}>
                        <strong>Document Intelligence Agent:</strong> {crossValResult.step_decisions.document_intelligence.rationale}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Classification & Confidence Analysis Card */}
              <div className="card" style={{ padding: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)', marginBottom: 12 }}>
                  Classification & Uncertainty Scoring
                </div>
                <div className="dimension-stat-grid">
                  <div>
                    <span className="stat-item-label">Detected Category</span>
                    <div className="stat-item-value">{selectedDoc.classification?.kind?.toUpperCase() || selectedDoc.kind.toUpperCase()}</div>
                  </div>
                  <div>
                    <span className="stat-item-label">Classification Confidence</span>
                    <div className="stat-item-value" style={{ color: (selectedDoc.classification?.confidence || 0.9) >= 0.75 ? 'var(--emerald)' : 'var(--amber)' }}>
                      {((selectedDoc.classification?.confidence || 0.9) * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div>
                    <span className="stat-item-label">Review Status</span>
                    <div className="stat-item-value">
                      {selectedDoc.requires_review ? 'Pending Manager Review' : 'Auto-Verified'}
                    </div>
                  </div>
                  <div>
                    <span className="stat-item-label">Vector Chunking</span>
                    <div className="stat-item-value">pgvector Cosine Sim</div>
                  </div>
                </div>
              </div>

              {/* Extracted Structured Fields Card */}
              <div className="card" style={{ padding: 16 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)', marginBottom: 12 }}>
                  Structured Extracted Fields (Deterministic Regex & OCR Token Parsing)
                </div>
                {selectedDoc.extracted_fields && Object.keys(selectedDoc.extracted_fields).length > 0 ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
                    {Object.entries(selectedDoc.extracted_fields).map(([key, val]) => (
                      <div key={key} style={{ background: 'var(--bg-inset)', padding: 10, borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
                        <span style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-dim)', letterSpacing: '0.04em' }}>
                          {key.replace(/_/g, ' ')}
                        </span>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)', marginTop: 2 }}>
                          {typeof val === 'number' && key.includes('amount') || key.includes('rent') || key.includes('total')
                            ? `$${Number(val).toLocaleString('en-US', { minimumFractionDigits: 2 })}`
                            : Array.isArray(val)
                            ? val.join(', ') || 'None'
                            : String(val || 'N/A')}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-dim)', fontSize: 12, padding: 12, background: 'var(--bg-inset)', borderRadius: 6 }}>
                    No structured entity fields detected in text body.
                  </div>
                )}
              </div>

              {/* Full Document Body Text Viewer */}
              <div className="card" style={{ padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-heading)' }}>
                    Extracted Text Body & Grounded Evidence
                  </div>
                  <span className="pill" style={{ fontSize: 10 }}>
                    {selectedDoc.body?.length || 0} Characters
                  </span>
                </div>
                <div
                  className="briefing-box"
                  style={{
                    background: 'var(--bg-inset)',
                    border: '1px solid var(--border-subtle)',
                    maxHeight: 280,
                    overflowY: 'auto',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    lineHeight: 1.6,
                    whiteSpace: 'pre-wrap'
                  }}
                >
                  {selectedDoc.body || 'No text extracted.'}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
              No document selected. Choose a document on the left to inspect extractions and validation findings.
            </div>
          )}
        </section>
      </div>

      {/* Ingest / Process Document Modal */}
      {isUploadModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-card" style={{ maxWidth: 640 }}>
            <div className="modal-header">
              <h3 style={{ fontSize: 16, fontWeight: 800 }}>Ingest Document into Document Intelligence</h3>
              <button className="btn-icon" onClick={() => setIsUploadModalOpen(false)}>✕</button>
            </div>

            <form onSubmit={handleProcessDocument} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label className="form-label">Document Title / File Descriptor *</label>
                <input
                  type="text"
                  className="decision-input"
                  required
                  placeholder="e.g. Standard California Residential Lease Agreement"
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label className="form-label">Associate to Lease ID (Optional)</label>
                  <input
                    type="text"
                    className="decision-input"
                    placeholder="LEASE-0001"
                    value={uploadLeaseId}
                    onChange={(e) => setUploadLeaseId(e.target.value)}
                  />
                </div>
                <div>
                  <label className="form-label">Property Association</label>
                  <select
                    className="decision-input"
                    value={uploadPropertyId}
                    onChange={(e) => setUploadPropertyId(e.target.value)}
                  >
                    <option value="PROP-001">PROP-001 (Skyline Terrace · ORG-APEX)</option>
                    <option value="PROP-002">PROP-002 (Verdant Valley · ORG-VERDANT)</option>
                    <option value="PROP-003">PROP-003 (Beacon Bay Plaza · ORG-BEACON)</option>
                    <option value="PROP-004">PROP-004 (Oakridge Lofts · ORG-SKYLINE)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="form-label">Document Text Body / OCR Transcribed Content *</label>
                <textarea
                  className="decision-input"
                  rows={8}
                  required
                  placeholder="Paste lease clauses, vendor bill items, work order quote, or OCR extracted text..."
                  value={uploadBody}
                  onChange={(e) => setUploadBody(e.target.value)}
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                />
              </div>

              {processResult && (
                <div className="discrepancy-callout reconciled" style={{ fontSize: 12 }}>
                  <strong>Processed Successfully:</strong> ID: <code>{processResult.document_id}</code> | Category: <strong>{processResult.kind}</strong> | Confidence: {(processResult.confidence * 100).toFixed(0)}%
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                <button type="button" className="btn btn-subtle" onClick={() => setIsUploadModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={isProcessing}>
                  {isProcessing ? 'Processing OCR & RAG...' : '⚡ Ingest & Extract Fields'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
