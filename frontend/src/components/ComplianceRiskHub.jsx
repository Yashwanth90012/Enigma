import React, { useState, useEffect, useCallback } from 'react';

export default function ComplianceRiskHub({ currentOrgId = 'ORG-APEX' }) {
  // State
  const [activeTab, setActiveTab] = useState('register'); // 'register' | 'approvals' | 'jurisdictions' | 'history'
  const [summary, setSummary] = useState(null);
  const [findings, setFindings] = useState([]);
  const [totalFindings, setTotalFindings] = useState(0);
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [jurisdictions, setJurisdictions] = useState({});
  const [approvalHistory, setApprovalHistory] = useState([]);
  
  // Filters
  const [categoryFilter, setCategoryFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 15;

  // Selected finding for modal inspection
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);

  // Action dialog states
  const [actionModal, setActionModal] = useState({ open: false, type: '', finding: null });
  const [actionReviewer, setActionReviewer] = useState('Compliance Officer');
  const [actionReason, setActionReason] = useState('');
  const [actionSubmittedBy, setActionSubmittedBy] = useState('');
  const [isSubmittingAction, setIsSubmittingAction] = useState(false);

  // Approval queue action
  const [approvalModal, setApprovalModal] = useState({ open: false, item: null, action: 'approved' });
  const [approvalReason, setApprovalReason] = useState('');
  const [approvalReviewer, setApprovalReviewer] = useState('Property Manager');

  // UI state
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const showFeedback = (type, msg) => {
    setFeedback({ type, msg });
    setTimeout(() => setFeedback(null), 5000);
  };

  // 1. Fetch Summary
  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch(`/api/compliance/summary?org_id=${currentOrgId}`, {
        headers: { 'X-Organization-Id': currentOrgId }
      });
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
      }
    } catch (e) {
      console.error('Error fetching compliance summary:', e);
    }
  }, [currentOrgId]);

  // 2. Fetch Findings
  const fetchFindings = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        org_id: currentOrgId,
        limit: pageSize.toString(),
        offset: (page * pageSize).toString()
      });
      if (categoryFilter) params.append('category', categoryFilter);
      if (severityFilter) params.append('severity', severityFilter);
      if (statusFilter) params.append('status', statusFilter);
      if (typeFilter) params.append('finding_type', typeFilter);
      if (searchQuery.trim()) params.append('search', searchQuery.trim());

      const res = await fetch(`/api/compliance/findings?${params.toString()}`, {
        headers: { 'X-Organization-Id': currentOrgId }
      });
      if (res.ok) {
        const data = await res.json();
        setFindings(data.findings || []);
        setTotalFindings(data.total || 0);
      }
    } catch (e) {
      console.error('Error fetching findings:', e);
    }
  }, [currentOrgId, page, categoryFilter, severityFilter, statusFilter, typeFilter, searchQuery]);

  // 3. Fetch Pending Approvals
  const fetchPendingApprovals = useCallback(async () => {
    try {
      const res = await fetch(`/api/compliance/approvals/pending?org_id=${currentOrgId}`, {
        headers: { 'X-Organization-Id': currentOrgId }
      });
      if (res.ok) {
        const data = await res.json();
        setPendingApprovals(data.approvals || []);
      }
    } catch (e) {
      console.error('Error fetching pending approvals:', e);
    }
  }, [currentOrgId]);

  // 4. Fetch Jurisdictions
  const fetchJurisdictions = useCallback(async () => {
    try {
      const res = await fetch('/api/compliance/jurisdictions');
      if (res.ok) {
        const data = await res.json();
        setJurisdictions(data.jurisdictions || {});
      }
    } catch (e) {
      console.error('Error fetching jurisdictions:', e);
    }
  }, []);

  // 5. Fetch History
  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`/api/compliance/approvals/history?org_id=${currentOrgId}&limit=50`, {
        headers: { 'X-Organization-Id': currentOrgId }
      });
      if (res.ok) {
        const data = await res.json();
        setApprovalHistory(data.history || []);
      }
    } catch (e) {
      console.error('Error fetching approval history:', e);
    }
  }, [currentOrgId]);

  // Initial Load
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchSummary(), fetchFindings(), fetchPendingApprovals(), fetchJurisdictions(), fetchHistory()])
      .finally(() => setLoading(false));
  }, [fetchSummary, fetchFindings, fetchPendingApprovals, fetchJurisdictions, fetchHistory]);

  // On tab change
  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (tab === 'approvals') fetchPendingApprovals();
    if (tab === 'history') fetchHistory();
    if (tab === 'jurisdictions') fetchJurisdictions();
  };

  // Run On-Demand Scan
  const handleTriggerScan = async () => {
    setScanning(true);
    try {
      const res = await fetch(`/api/compliance/scan?org_id=${currentOrgId}`, {
        method: 'POST',
        headers: { 'X-Organization-Id': currentOrgId }
      });
      if (res.ok) {
        const data = await res.json();
        showFeedback('success', `Compliance scan completed: ${data.findings_detected} issues identified, ${data.findings_persisted} persisted.`);
        fetchSummary();
        fetchFindings();
        fetchPendingApprovals();
      } else {
        const err = await res.json();
        showFeedback('error', `Scan failed: ${err.detail || 'Server error'}`);
      }
    } catch (e) {
      showFeedback('error', `Scan error: ${e.message}`);
    } finally {
      setScanning(false);
    }
  };

  // Open Finding Detail
  const handleInspectFinding = async (findingId) => {
    setIsLoadingDetail(true);
    try {
      const res = await fetch(`/api/compliance/findings/${findingId}?org_id=${currentOrgId}`, {
        headers: { 'X-Organization-Id': currentOrgId }
      });
      if (res.ok) {
        const detail = await res.json();
        setSelectedFinding(detail);
      } else {
        showFeedback('error', 'Failed to load finding detail');
      }
    } catch (e) {
      showFeedback('error', e.message);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  // Submit Finding Action (assign, review, resolve, dismiss)
  const handleSubmitFindingAction = async () => {
    if (!actionReviewer.trim()) {
      showFeedback('error', 'Reviewer name is required');
      return;
    }
    if (actionModal.type !== 'assign' && (!actionReason || actionReason.trim().length < 3)) {
      showFeedback('error', 'A decision reason (minimum 3 characters) is required');
      return;
    }

    setIsSubmittingAction(true);
    const { type, finding } = actionModal;

    try {
      let url = '';
      let body = {};

      if (type === 'assign') {
        url = `/api/compliance/findings/${finding.id}/assign?org_id=${currentOrgId}`;
        body = { reviewer: actionReviewer, notes: actionReason || `Assigned to ${actionReviewer}` };
      } else if (type === 'under_review' || type === 'action_required') {
        url = `/api/compliance/findings/${finding.id}/review?org_id=${currentOrgId}`;
        body = { status: type, reviewer: actionReviewer, notes: actionReason };
      } else if (type === 'resolved' || type === 'dismissed') {
        url = `/api/compliance/findings/${finding.id}/resolve?org_id=${currentOrgId}`;
        body = {
          status: type,
          reviewer: actionReviewer,
          decision_reason: actionReason,
          submitted_by: actionSubmittedBy || undefined
        };
      }

      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Organization-Id': currentOrgId },
        body: JSON.stringify(body)
      });

      if (res.ok) {
        showFeedback('success', `Finding ${finding.id} marked as ${type.replace('_', ' ')}.`);
        setActionModal({ open: false, type: '', finding: null });
        setActionReason('');
        setActionSubmittedBy('');
        fetchSummary();
        fetchFindings();
        if (selectedFinding && selectedFinding.id === finding.id) {
          handleInspectFinding(finding.id);
        }
      } else {
        const err = await res.json();
        showFeedback('error', err.detail || 'Action failed');
      }
    } catch (e) {
      showFeedback('error', e.message);
    } finally {
      setIsSubmittingAction(false);
    }
  };

  // Submit Pending Approval Decision
  const handleExecuteApproval = async () => {
    if (!approvalReviewer.trim()) {
      showFeedback('error', 'Reviewer identity is required');
      return;
    }
    if (!approvalReason || approvalReason.trim().length < 3) {
      showFeedback('error', 'Decision rationale is required');
      return;
    }

    setIsSubmittingAction(true);
    const { item, action } = approvalModal;

    try {
      const res = await fetch(`/api/compliance/approvals/${item.case_id}/decision?org_id=${currentOrgId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Organization-Id': currentOrgId },
        body: JSON.stringify({
          entity_type: item.entity_type,
          action,
          reviewer: approvalReviewer,
          reason: approvalReason
        })
      });

      if (res.ok) {
        showFeedback('success', `Approval decision [${action.toUpperCase()}] executed for ${item.title}.`);
        setApprovalModal({ open: false, item: null, action: 'approved' });
        setApprovalReason('');
        fetchPendingApprovals();
        fetchSummary();
        fetchHistory();
      } else {
        const err = await res.json();
        showFeedback('error', err.detail || 'Approval execution failed');
      }
    } catch (e) {
      showFeedback('error', e.message);
    } finally {
      setIsSubmittingAction(false);
    }
  };

  return (
    <div className="portal-container" style={{ padding: '24px 32px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-heading)' }}>Compliance & Risk Monitoring Hub</span>
            <span className="hub-pill amber" style={{ fontSize: 11, padding: '3px 8px' }}>Phase 2B Active</span>
          </div>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
            Continuous multi-agent risk identification, statutory jurisdiction deadlines, 4-way financial reconciliation audits, and central approval governance.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            onClick={handleTriggerScan}
            disabled={scanning}
            className="hub-nav-btn active"
            style={{ padding: '8px 16px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}
          >
            <svg className={`icon ${scanning ? 'spin' : ''}`} style={{ width: 14, height: 14 }} viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
            <span>{scanning ? 'Scanning Portfolio...' : 'Run Compliance Scan'}</span>
          </button>
        </div>
      </div>

      {/* Notification Toast */}
      {feedback && (
        <div style={{
          padding: '12px 18px',
          borderRadius: 8,
          marginBottom: 16,
          fontSize: 13,
          fontWeight: 500,
          background: feedback.type === 'error' ? 'rgba(225, 29, 72, 0.1)' : 'rgba(5, 150, 105, 0.1)',
          color: feedback.type === 'error' ? 'var(--rose)' : 'var(--emerald)',
          border: `1px solid ${feedback.type === 'error' ? 'var(--rose)' : 'var(--emerald)'}`
        }}>
          {feedback.msg}
        </div>
      )}

      {/* Metrics Banner */}
      {summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginBottom: 24 }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: '16px 20px', boxShadow: 'var(--card-shadow)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 600, textTransform: 'uppercase' }}>High Priority Risks</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: summary.high_priority_count > 0 ? 'var(--rose)' : 'var(--emerald)', marginTop: 4 }}>
              {summary.high_priority_count}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Critical & High severity open findings
            </div>
          </div>

          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: '16px 20px', boxShadow: 'var(--card-shadow)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 600, textTransform: 'uppercase' }}>Pending Approvals</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: pendingApprovals.length > 0 ? 'var(--amber)' : 'var(--text-main)', marginTop: 4 }}>
              {pendingApprovals.length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Renewals, deposit closeouts & escalations
            </div>
          </div>

          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: '16px 20px', boxShadow: 'var(--card-shadow)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 600, textTransform: 'uppercase' }}>Total Active Findings</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--text-heading)', marginTop: 4 }}>
              {(summary.by_status?.open || 0) + (summary.by_status?.under_review || 0) + (summary.by_status?.action_required || 0)}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Open: {summary.by_status?.open || 0} · Review: {summary.by_status?.under_review || 0}
            </div>
          </div>

          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: '16px 20px', boxShadow: 'var(--card-shadow)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 600, textTransform: 'uppercase' }}>Resolved / Dismissed</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--emerald)', marginTop: 4 }}>
              {(summary.by_status?.resolved || 0) + (summary.by_status?.dismissed || 0)}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              Resolved: {summary.by_status?.resolved || 0} · Dismissed: {summary.by_status?.dismissed || 0}
            </div>
          </div>
        </div>
      )}

      {/* Workflow Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border-subtle)', marginBottom: 20, gap: 10 }}>
        <button
          onClick={() => handleTabChange('register')}
          style={{
            padding: '10px 16px',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontSize: 14,
            fontWeight: 600,
            borderBottom: activeTab === 'register' ? '2px solid var(--primary)' : '2px solid transparent',
            color: activeTab === 'register' ? 'var(--primary)' : 'var(--text-muted)'
          }}
        >
          Central Risk Register ({totalFindings})
        </button>

        <button
          onClick={() => handleTabChange('approvals')}
          style={{
            padding: '10px 16px',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontSize: 14,
            fontWeight: 600,
            borderBottom: activeTab === 'approvals' ? '2px solid var(--amber)' : '2px solid transparent',
            color: activeTab === 'approvals' ? 'var(--amber)' : 'var(--text-muted)',
            display: 'flex',
            alignItems: 'center',
            gap: 6
          }}
        >
          <span>Pending Approvals</span>
          {pendingApprovals.length > 0 && (
            <span style={{ background: 'var(--amber)', color: '#fff', borderRadius: 10, padding: '1px 6px', fontSize: 11 }}>
              {pendingApprovals.length}
            </span>
          )}
        </button>

        <button
          onClick={() => handleTabChange('jurisdictions')}
          style={{
            padding: '10px 16px',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontSize: 14,
            fontWeight: 600,
            borderBottom: activeTab === 'jurisdictions' ? '2px solid var(--purple)' : '2px solid transparent',
            color: activeTab === 'jurisdictions' ? 'var(--purple)' : 'var(--text-muted)'
          }}
        >
          Statutory Jurisdictions & Deadlines
        </button>

        <button
          onClick={() => handleTabChange('history')}
          style={{
            padding: '10px 16px',
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            fontSize: 14,
            fontWeight: 600,
            borderBottom: activeTab === 'history' ? '2px solid var(--emerald)' : '2px solid transparent',
            color: activeTab === 'history' ? 'var(--emerald)' : 'var(--text-muted)'
          }}
        >
          Audit History ({approvalHistory.length})
        </button>
      </div>

      {/* TAB 1: Central Risk Register */}
      {activeTab === 'register' && (
        <div>
          {/* Filters Bar */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 16, alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Search by title, record ID, or description..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setPage(0); }}
              style={{
                flex: 1,
                minWidth: 240,
                padding: '8px 12px',
                borderRadius: 8,
                border: '1px solid var(--border-subtle)',
                background: 'var(--input-bg)',
                color: 'var(--input-color)',
                fontSize: 13
              }}
            />

            <select
              value={categoryFilter}
              onChange={(e) => { setCategoryFilter(e.target.value); setPage(0); }}
              style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)', fontSize: 13 }}
            >
              <option value="">All Categories</option>
              <option value="lease_resident">Lease & Resident</option>
              <option value="financial">Financial & AP</option>
              <option value="maintenance">Maintenance</option>
              <option value="operational_integration">Operational</option>
              <option value="legal_compliance">Legal Compliance</option>
            </select>

            <select
              value={severityFilter}
              onChange={(e) => { setSeverityFilter(e.target.value); setPage(0); }}
              style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)', fontSize: 13 }}
            >
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>

            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
              style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)', fontSize: 13 }}
            >
              <option value="">All Statuses</option>
              <option value="open">Open</option>
              <option value="under_review">Under Review</option>
              <option value="action_required">Action Required</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>

            <select
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value); setPage(0); }}
              style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)', fontSize: 13 }}
            >
              <option value="">All Finding Types</option>
              <option value="operational_risk">Operational Risk</option>
              <option value="policy_exception">Policy Exception</option>
              <option value="legal_compliance_finding">Legal Compliance</option>
            </select>
          </div>

          {/* Findings Table */}
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, overflow: 'hidden', boxShadow: 'var(--card-shadow)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--bg-inset)', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '12px 16px' }}>Severity</th>
                  <th style={{ padding: '12px 16px' }}>Finding / Title</th>
                  <th style={{ padding: '12px 16px' }}>Category & Type</th>
                  <th style={{ padding: '12px 16px' }}>Source Record</th>
                  <th style={{ padding: '12px 16px' }}>Jurisdiction / Statute</th>
                  <th style={{ padding: '12px 16px' }}>Status</th>
                  <th style={{ padding: '12px 16px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                      Loading risk findings...
                    </td>
                  </tr>
                ) : findings.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                      No risk findings matching criteria. Run a compliance scan to evaluate active operations.
                    </td>
                  </tr>
                ) : (
                  findings.map((f) => {
                    const sevColor = f.severity === 'critical' ? 'var(--rose)' : (f.severity === 'high' ? 'var(--amber)' : (f.severity === 'medium' ? 'var(--primary)' : 'var(--text-muted)'));
                    const statusBg = f.status === 'resolved' ? 'rgba(5, 150, 105, 0.1)' : (f.status === 'action_required' ? 'rgba(225, 29, 72, 0.1)' : (f.status === 'under_review' ? 'rgba(217, 119, 6, 0.1)' : 'rgba(8, 145, 178, 0.1)'));
                    const statusColor = f.status === 'resolved' ? 'var(--emerald)' : (f.status === 'action_required' ? 'var(--rose)' : (f.status === 'under_review' ? 'var(--amber)' : 'var(--primary)'));

                    return (
                      <tr key={f.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '12px 16px' }}>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: 6,
                            fontSize: 11,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            background: f.severity === 'critical' ? 'rgba(225, 29, 72, 0.15)' : (f.severity === 'high' ? 'rgba(217, 119, 6, 0.15)' : 'rgba(8, 145, 178, 0.1)'),
                            color: sevColor
                          }}>
                            {f.severity}
                          </span>
                        </td>
                        <td style={{ padding: '12px 16px', maxWidth: 300 }}>
                          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{f.title}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {f.description}
                          </div>
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <div style={{ textTransform: 'capitalize' }}>{f.category.replace('_', ' ')}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{f.finding_type.replace(/_/g, ' ')}</div>
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <code>{f.source_record_type}:{f.source_record_id}</code>
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          {f.statutory_source ? (
                            <div>
                              <span style={{ fontWeight: 600, color: 'var(--purple)', fontSize: 11 }}>{f.statutory_source}</span>
                              <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{f.jurisdiction}</div>
                            </div>
                          ) : (
                            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                              {f.jurisdiction === 'unverified' ? 'Jurisdiction Unverified' : 'N/A (Operational/Policy)'}
                            </span>
                          )}
                        </td>
                        <td style={{ padding: '12px 16px' }}>
                          <span style={{
                            padding: '3px 8px',
                            borderRadius: 6,
                            fontSize: 11,
                            fontWeight: 600,
                            background: statusBg,
                            color: statusColor,
                            textTransform: 'capitalize'
                          }}>
                            {f.status.replace('_', ' ')}
                          </span>
                        </td>
                        <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                            <button
                              onClick={() => handleInspectFinding(f.id)}
                              style={{ padding: '4px 10px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', color: 'var(--btn-default-color)', cursor: 'pointer' }}
                            >
                              Inspect
                            </button>
                            {f.status !== 'resolved' && f.status !== 'dismissed' && (
                              <button
                                onClick={() => setActionModal({ open: true, type: 'resolved', finding: f })}
                                style={{ padding: '4px 10px', fontSize: 12, borderRadius: 6, border: '1px solid var(--emerald)', background: 'rgba(5, 150, 105, 0.1)', color: 'var(--emerald)', cursor: 'pointer', fontWeight: 600 }}
                              >
                                Resolve
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>

            {/* Pagination footer */}
            <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-inset)' }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Showing {findings.length} of {totalFindings} findings
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button
                  disabled={page === 0}
                  onClick={() => setPage(page - 1)}
                  style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: page === 0 ? 'not-allowed' : 'pointer' }}
                >
                  Prev
                </button>
                <button
                  disabled={(page + 1) * pageSize >= totalFindings}
                  onClick={() => setPage(page + 1)}
                  style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: (page + 1) * pageSize >= totalFindings ? 'not-allowed' : 'pointer' }}
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: Pending Approvals Queue */}
      {activeTab === 'approvals' && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, overflow: 'hidden', padding: 24, boxShadow: 'var(--card-shadow)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, color: 'var(--text-heading)' }}>Centralized Pending Approvals Queue</h3>
              <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
                Authoritative human approval gates for lease renewal term updates, security deposit closeouts, and escalated risk findings.
              </p>
            </div>
            <button
              onClick={fetchPendingApprovals}
              style={{ padding: '6px 12px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: 'pointer' }}
            >
              Refresh Queue
            </button>
          </div>

          {pendingApprovals.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
              Zero pending approvals. All contractual adjustments and deposit dispositions are finalized.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {pendingApprovals.map((item) => (
                <div
                  key={item.approval_id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '16px 20px',
                    borderRadius: 10,
                    border: '1px solid var(--border-subtle)',
                    background: 'var(--bg-inset)'
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        padding: '2px 6px',
                        borderRadius: 4,
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        background: item.severity === 'critical' ? 'rgba(225, 29, 72, 0.2)' : 'rgba(217, 119, 6, 0.2)',
                        color: item.severity === 'critical' ? 'var(--rose)' : 'var(--amber)'
                      }}>
                        {item.entity_type.replace('_', ' ')}
                      </span>
                      <span style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: 14 }}>{item.title}</span>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                      {item.description}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                      Case: <code>{item.case_id}</code> · Property: {item.property_name || item.property_id} · Created: {item.created_at ? new Date(item.created_at).toLocaleString() : 'N/A'}
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={() => setApprovalModal({ open: true, item, action: 'approved' })}
                      style={{ padding: '6px 14px', borderRadius: 6, border: 'none', background: 'var(--emerald)', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
                    >
                      Authorize Sign-Off
                    </button>
                    <button
                      onClick={() => setApprovalModal({ open: true, item, action: 'rejected' })}
                      style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid var(--rose)', background: 'rgba(225, 29, 72, 0.1)', color: 'var(--rose)', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: Statutory Jurisdictions & Legal Deadlines */}
      {activeTab === 'jurisdictions' && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, overflow: 'hidden', padding: 24, boxShadow: 'var(--card-shadow)' }}>
          <div style={{ marginBottom: 20 }}>
            <h3 style={{ margin: 0, fontSize: 16, color: 'var(--text-heading)' }}>Authoritative Statutory Compliance Registry</h3>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Jurisdiction-specific legal rules, statutory return countdowns, and citations. Evaluated only against properties with verified jurisdiction evidence.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            {Object.entries(jurisdictions).map(([code, rule]) => (
              <div
                key={code}
                style={{
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 10,
                  padding: '16px 20px',
                  background: 'var(--bg-inset)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-heading)' }}>
                    {rule.state_name} ({code})
                  </div>
                  <span className="hub-pill purple" style={{ fontSize: 11 }}>{rule.jurisdiction}</span>
                </div>

                <div style={{ marginTop: 10, fontSize: 13, color: 'var(--purple)', fontWeight: 600 }}>
                  {rule.citation}
                </div>

                <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {rule.summary}
                </div>

                <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <div>
                    <span style={{ color: 'var(--text-dim)' }}>Deposit Return Limit: </span>
                    <strong style={{ color: 'var(--text-heading)' }}>{rule.security_deposit_return_days} Calendar Days</strong>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-dim)' }}>Effective Date: </span>
                    <code>{rule.effective_date}</code>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 4: Audit History */}
      {activeTab === 'history' && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, overflow: 'hidden', padding: 24, boxShadow: 'var(--card-shadow)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, color: 'var(--text-heading)' }}>Central Approval & Resolution Audit Trail</h3>
              <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
                Immutable event journal recording actor identities, decision rationales, prior/post states, and timestamps.
              </p>
            </div>
            <button
              onClick={fetchHistory}
              style={{ padding: '6px 12px', fontSize: 12, borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: 'pointer' }}
            >
              Refresh
            </button>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg-inset)', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '10px 14px' }}>Timestamp</th>
                <th style={{ padding: '10px 14px' }}>Case / Entity</th>
                <th style={{ padding: '10px 14px' }}>Action</th>
                <th style={{ padding: '10px 14px' }}>Reviewer / Actor</th>
                <th style={{ padding: '10px 14px' }}>State Transition</th>
                <th style={{ padding: '10px 14px' }}>Decision Rationale</th>
              </tr>
            </thead>
            <tbody>
              {approvalHistory.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: 30, textAlign: 'center', color: 'var(--text-muted)' }}>
                    No audit records recorded yet.
                  </td>
                </tr>
              ) : (
                approvalHistory.map((h) => (
                  <tr key={h.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '10px 14px', fontSize: 11, color: 'var(--text-dim)' }}>
                      {h.created_at ? new Date(h.created_at).toLocaleString() : 'N/A'}
                    </td>
                    <td style={{ padding: '10px 14px' }}>
                      <code>{h.case_id}</code>
                    </td>
                    <td style={{ padding: '10px 14px' }}>
                      <span style={{
                        padding: '2px 6px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        background: h.action === 'approved' || h.action === 'resolved' ? 'rgba(5, 150, 105, 0.15)' : 'rgba(217, 119, 6, 0.15)',
                        color: h.action === 'approved' || h.action === 'resolved' ? 'var(--emerald)' : 'var(--amber)'
                      }}>
                        {h.action}
                      </span>
                    </td>
                    <td style={{ padding: '10px 14px', fontWeight: 500 }}>
                      {h.reviewer}
                    </td>
                    <td style={{ padding: '10px 14px', fontSize: 11 }}>
                      <span style={{ color: 'var(--text-dim)' }}>{h.previous_state || 'none'}</span>
                      <span style={{ margin: '0 4px' }}>→</span>
                      <strong>{h.new_state}</strong>
                    </td>
                    <td style={{ padding: '10px 14px', maxWidth: 300, fontSize: 12 }}>
                      {h.decision_reason}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* INSPECTION MODAL */}
      {selectedFinding && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.6)',
          backdropFilter: 'blur(3px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            background: 'var(--modal-bg)',
            borderRadius: 14,
            padding: 24,
            width: '90%',
            maxWidth: 700,
            maxHeight: '90vh',
            overflowY: 'auto',
            boxShadow: '0 20px 40px rgba(0,0,0,0.3)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <span style={{
                  padding: '3px 8px',
                  borderRadius: 6,
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  background: selectedFinding.severity === 'critical' ? 'rgba(225, 29, 72, 0.15)' : 'rgba(217, 119, 6, 0.15)',
                  color: selectedFinding.severity === 'critical' ? 'var(--rose)' : 'var(--amber)'
                }}>
                  {selectedFinding.severity} · {selectedFinding.finding_type.replace(/_/g, ' ')}
                </span>
                <h3 style={{ margin: '8px 0 4px', fontSize: 18, color: 'var(--text-heading)' }}>{selectedFinding.title}</h3>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  Finding ID: <code>{selectedFinding.id}</code> · Canonical: <code>{selectedFinding.canonical_id}</code>
                </div>
              </div>
              <button
                onClick={() => setSelectedFinding(null)}
                style={{ border: 'none', background: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-muted)' }}
              >
                ✕
              </button>
            </div>

            <div style={{ marginTop: 16, padding: '12px 16px', background: 'var(--bg-inset)', borderRadius: 8, fontSize: 13, lineHeight: 1.5 }}>
              {selectedFinding.description}
            </div>

            {/* Jurisdiction & Statutory Evidence */}
            {selectedFinding.statutory_source && (
              <div style={{ marginTop: 14, padding: '12px 16px', background: 'rgba(124, 58, 237, 0.08)', border: '1px solid var(--purple)', borderRadius: 8 }}>
                <div style={{ fontWeight: 600, color: 'var(--purple)', fontSize: 13 }}>Statutory Legal Basis</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>
                  <strong>Source:</strong> {selectedFinding.statutory_source} ({selectedFinding.jurisdiction})
                </div>
                <div style={{ fontSize: 12, marginTop: 2 }}>
                  <strong>Effective Date:</strong> {selectedFinding.effective_date}
                </div>
                <div style={{ fontSize: 12, marginTop: 2 }}>
                  <strong>Compliance Standing:</strong> <span style={{ textTransform: 'uppercase', fontWeight: 600, color: 'var(--rose)' }}>{selectedFinding.compliance_status}</span>
                </div>
              </div>
            )}

            {/* Evidence Payload */}
            <div style={{ marginTop: 14 }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-heading)', marginBottom: 6 }}>Source Evidence Payload</div>
              <pre style={{
                background: 'var(--code-bg)',
                color: 'var(--code-color)',
                padding: '12px 16px',
                borderRadius: 8,
                fontSize: 12,
                overflowX: 'auto',
                maxHeight: 180
              }}>
                {JSON.stringify(selectedFinding.evidence, null, 2)}
              </pre>
            </div>

            {/* Finding History */}
            {selectedFinding.audit_history && selectedFinding.audit_history.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-heading)', marginBottom: 6 }}>Decision History</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {selectedFinding.audit_history.map((ah) => (
                    <div key={ah.id} style={{ fontSize: 12, padding: '6px 10px', background: 'var(--bg-inset)', borderRadius: 6 }}>
                      <strong>{ah.reviewer}</strong> marked as <em>{ah.action}</em>: "{ah.reason}" ({new Date(ah.timestamp).toLocaleDateString()})
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Modal Actions */}
            <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <button
                onClick={() => {
                  setActionModal({ open: true, type: 'assign', finding: selectedFinding });
                }}
                style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: 'pointer' }}
              >
                Assign Reviewer
              </button>

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => {
                    setActionModal({ open: true, type: 'action_required', finding: selectedFinding });
                  }}
                  style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid var(--rose)', background: 'rgba(225, 29, 72, 0.1)', color: 'var(--rose)', cursor: 'pointer', fontWeight: 600 }}
                >
                  Escalate
                </button>
                <button
                  onClick={() => {
                    setActionModal({ open: true, type: 'resolved', finding: selectedFinding });
                  }}
                  style={{ padding: '8px 14px', borderRadius: 6, border: 'none', background: 'var(--emerald)', color: '#fff', cursor: 'pointer', fontWeight: 600 }}
                >
                  Resolve Finding
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ACTION DIALOG MODAL (Assign / Review / Resolve / Dismiss) */}
      {actionModal.open && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.6)',
          backdropFilter: 'blur(3px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1100
        }}>
          <div style={{
            background: 'var(--modal-bg)',
            borderRadius: 14,
            padding: 24,
            width: '90%',
            maxWidth: 480,
            boxShadow: '0 20px 40px rgba(0,0,0,0.3)'
          }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16, color: 'var(--text-heading)' }}>
              Action: Mark Finding as {actionModal.type.replace('_', ' ').toUpperCase()}
            </h3>

            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
              Case: <strong>{actionModal.finding?.title}</strong> ({actionModal.finding?.id})
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-heading)', marginBottom: 4 }}>
                Reviewer / Responsible Actor:
              </label>
              <input
                type="text"
                value={actionReviewer}
                onChange={(e) => setActionReviewer(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)' }}
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-heading)', marginBottom: 4 }}>
                Decision Rationale / Notes (Required):
              </label>
              <textarea
                rows={3}
                placeholder="Explain the verified resolution or why this finding is dismissed/escalated..."
                value={actionReason}
                onChange={(e) => setActionReason(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)', fontSize: 13 }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
              <button
                onClick={() => setActionModal({ open: false, type: '', finding: null })}
                style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitFindingAction}
                disabled={isSubmittingAction}
                style={{ padding: '8px 16px', borderRadius: 6, border: 'none', background: 'var(--primary)', color: '#fff', cursor: 'pointer', fontWeight: 600 }}
              >
                {isSubmittingAction ? 'Submitting...' : 'Confirm Decision'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* APPROVAL DIALOG MODAL */}
      {approvalModal.open && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.6)',
          backdropFilter: 'blur(3px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1100
        }}>
          <div style={{
            background: 'var(--modal-bg)',
            borderRadius: 14,
            padding: 24,
            width: '90%',
            maxWidth: 480,
            boxShadow: '0 20px 40px rgba(0,0,0,0.3)'
          }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 16, color: 'var(--text-heading)' }}>
              Execute {approvalModal.action.toUpperCase()}: {approvalModal.item?.title}
            </h3>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
              {approvalModal.item?.description}
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-heading)', marginBottom: 4 }}>
                Authorizing Manager:
              </label>
              <input
                type="text"
                value={approvalReviewer}
                onChange={(e) => setApprovalReviewer(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)' }}
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-heading)', marginBottom: 4 }}>
                Decision Reason / Audit Note:
              </label>
              <textarea
                rows={3}
                placeholder="Document contractual, inspection walkthrough, or ledger audit rationale..."
                value={approvalReason}
                onChange={(e) => setApprovalReason(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--input-bg)', color: 'var(--input-color)', fontSize: 13 }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
              <button
                onClick={() => setApprovalModal({ open: false, item: null, action: 'approved' })}
                style={{ padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border-subtle)', background: 'var(--btn-default-bg)', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteApproval}
                disabled={isSubmittingAction}
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  border: 'none',
                  background: approvalModal.action === 'approved' ? 'var(--emerald)' : 'var(--rose)',
                  color: '#fff',
                  cursor: 'pointer',
                  fontWeight: 600
                }}
              >
                {isSubmittingAction ? 'Executing...' : `Confirm ${approvalModal.action.toUpperCase()}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
