import React, { useState, useEffect } from 'react';

const ORG_DEFAULT_LEASES = {
  'ORG-APEX': 'LEASE-0001',
  'ORG-VERDANT': 'LEASE-0021',
  'ORG-BEACON': 'LEASE-0041',
  'ORG-SKYLINE': 'LEASE-0061',
};

const ORG_PROPERTY_FALLBACK = {
  'ORG-APEX': 'PROP-001',
  'ORG-VERDANT': 'PROP-002',
  'ORG-BEACON': 'PROP-003',
  'ORG-SKYLINE': 'PROP-004'
};

export default function ResidentPortal({ onOpenPayModal, currentOrgId = 'ORG-APEX' }) {
  const [activeTab, setActiveTab] = useState('overview'); // overview, move_in, renewal, move_out, preferences
  const [activeLeaseId, setActiveLeaseId] = useState(ORG_DEFAULT_LEASES[currentOrgId] || 'LEASE-0001');
  const [leaseData, setLeaseData] = useState(null);
  const [loading, setLoading] = useState(true);

  // Auto-switch to a representative lease whenever the organization changes
  useEffect(() => {
    if (currentOrgId && ORG_DEFAULT_LEASES[currentOrgId]) {
      setActiveLeaseId(ORG_DEFAULT_LEASES[currentOrgId]);
    }
  }, [currentOrgId]);

  // Workflow states
  const [moveInData, setMoveInData] = useState(null);
  const [renewalData, setRenewalData] = useState(null);
  const [moveOutData, setMoveOutData] = useState(null);
  const [preferencesData, setPreferencesData] = useState(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [feedback, setFeedback] = useState(null);

  // Maintenance form
  const [maintDesc, setMaintDesc] = useState('');
  const [maintCost, setMaintCost] = useState(150);
  const [submittingMaint, setSubmittingMaint] = useState(false);
  const [maintResult, setMaintResult] = useState(null);

  // Pay rent form
  const [payAmount, setPayAmount] = useState('');
  const [payMethod, setPayMethod] = useState('ach_transfer');
  const [isPaying, setIsPaying] = useState(false);
  const [payFeedback, setPayFeedback] = useState(null);
  const [rentDashboard, setRentDashboard] = useState(null);
  const [activeReceipt, setActiveReceipt] = useState(null);
  const [showReceiptModal, setShowReceiptModal] = useState(false);
  const [showPayModal, setShowPayModal] = useState(false);

  // Document upload form
  const [docTitle, setDocTitle] = useState('');
  const [docBody, setDocBody] = useState('');
  const [docFeedback, setDocFeedback] = useState(null);
  const [isUploadingDoc, setIsUploadingDoc] = useState(false);

  // Move-out notice form
  const [moveOutDate, setMoveOutDate] = useState('2026-11-30');
  const [forwardingAddress, setForwardingAddress] = useState('');
  const [noticeReason, setNoticeReason] = useState('Job relocation');
  const [submittingNotice, setSubmittingNotice] = useState(false);

  // Renewal decision form
  const [decisionNotes, setDecisionNotes] = useState('');
  const [submittingDecision, setSubmittingDecision] = useState(false);

  // Prepare renewal offer form (manager / test mode)
  const [proposedIncreasePct, setProposedIncreasePct] = useState(3.5);
  const [proposedTermMonths, setProposedTermMonths] = useState(12);
  const [preparingOffer, setPreparingOffer] = useState(false);

  // Closeout deduction form
  const [deductionCategory, setDeductionCategory] = useState('repair');
  const [deductionDesc, setDeductionDesc] = useState('Drywall repair & paint touch-up');
  const [deductionAmount, setDeductionAmount] = useState(150.0);
  const [proposingCloseout, setProposingCloseout] = useState(false);

  // Notifications
  const [notifications, setNotifications] = useState([]);

  const fmtMoney = (n) => {
    const num = Number(n || 0);
    if (num < 0) {
      return '-$' + Math.abs(num).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return '$' + num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const getHeaders = () => ({
    'Content-Type': 'application/json',
    'X-Organization-Id': currentOrgId || 'ORG-APEX'
  });

  // Load basic lease & reconciliation details
  const loadLeaseDetails = async (lid) => {
    try {
      setLoading(true);
      const res = await fetch(`/api/lease/${lid}/details`);
      if (res.ok) {
        const data = await res.json();
        setLeaseData(data);
        if (data.reconciliation) {
          const diff = (data.reconciliation.difference_cents || 0) / 100.0;
          setPayAmount(diff > 0 ? diff.toFixed(2) : (data.lease?.monthly_rent_usd || 0).toFixed(2));
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Load active workflows for the current lease
  const loadWorkflows = async (lid) => {
    try {
      setWorkflowLoading(true);
      const headers = getHeaders();

      // 1. Move-in checklist
      const miRes = await fetch(`/api/leases/${lid}/move-in`, { headers });
      if (miRes.ok) setMoveInData(await miRes.json());
      else setMoveInData(null);

      // 2. Renewal record
      const renRes = await fetch(`/api/leases/${lid}/renewal`, { headers });
      if (renRes.ok) setRenewalData(await renRes.json());
      else setRenewalData(null);

      // 3. Move-out record
      const moRes = await fetch(`/api/leases/${lid}/move-out`, { headers });
      if (moRes.ok) setMoveOutData(await moRes.json());
      else setMoveOutData(null);

      // 4. Preferences
      const prefRes = await fetch(`/api/leases/${lid}/preferences`, { headers });
      if (prefRes.ok) setPreferencesData(await prefRes.json());
      else setPreferencesData(null);
    } catch (e) {
      console.error('Failed to load resident workflows:', e);
    } finally {
      setWorkflowLoading(false);
    }
  };

  const loadRentDashboard = async (lid) => {
    try {
      const res = await fetch(`/api/tenant/rent-dashboard?lease_id=${lid}`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setRentDashboard(data);
        if (data.current_bill) {
          const bal = data.current_bill.outstanding_balance_usd;
          setPayAmount(bal > 0 ? bal.toFixed(2) : data.current_bill.rent_amount_usd.toFixed(2));
        }
      }
    } catch (e) {
      console.error('Failed to load rent dashboard:', e);
    }
  };

  const loadNotifications = async () => {
    try {
      const res = await fetch('/api/notifications');
      if (res.ok) {
        const data = await res.json();
        setNotifications(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadLeaseDetails(activeLeaseId);
    loadWorkflows(activeLeaseId);
    loadRentDashboard(activeLeaseId);
    loadNotifications();
  }, [activeLeaseId, currentOrgId]);

  // Handle Maintenance Submit
  const handleMaintenanceSubmit = async (e) => {
    e.preventDefault();
    if (!maintDesc.trim()) return;
    setSubmittingMaint(true);
    setMaintResult(null);

    try {
      const res = await fetch('/api/maintenance/submit', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          lease_id: activeLeaseId,
          property_id: leaseData?.lease?.property_id || ORG_PROPERTY_FALLBACK[currentOrgId] || 'PROP-001',
          unit: leaseData?.lease?.unit || 'Unit 1A',
          description: maintDesc,
          reported_by: leaseData?.lease?.tenant1 || 'Resident',
          estimated_cost_usd: Number(maintCost)
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to submit ticket');
      setMaintResult(data);
      setMaintDesc('');
      loadLeaseDetails(activeLeaseId);
      loadNotifications();
    } catch (err) {
      alert(err.message);
    } finally {
      setSubmittingMaint(false);
    }
  };

  // Handle Pay Rent via Phase 7 Authoritative Gateway & Synchronization
  const handlePayRent = async (e) => {
    e.preventDefault();
    const amt = parseFloat(payAmount);
    if (!amt || amt <= 0) {
      alert('Please enter a valid amount greater than $0.00.');
      return;
    }
    setIsPaying(true);
    setPayFeedback(null);

    try {
      const billingRecordId = rentDashboard?.current_bill?.id || `BILL-${activeLeaseId.replace('LEASE-', '')}-2026-10`;
      const idempotencyKey = `pay-tx-${activeLeaseId}-${Date.now()}`;
      const customerEmail = leaseData?.lease?.resident_email || `${(leaseData?.lease?.tenant1 || 'tenant').toLowerCase().replace(' ', '.')}@enigma-tenant.internal`;

      // 1. Initiate checkout session
      const payRes = await fetch('/api/tenant/pay-rent', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          lease_id: activeLeaseId,
          billing_record_id: billingRecordId,
          amount_usd: amt,
          customer_email: customerEmail,
          payment_method: payMethod,
          idempotency_key: idempotencyKey
        })
      });
      const payData = await payRes.json();
      if (!payRes.ok) throw new Error(payData.detail || 'Payment initiation failed');

      // 2. Simulate sandbox completion
      const simRes = await fetch('/api/tenant/checkout-session/simulate', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          session_id: payData.session_id,
          should_succeed: true
        })
      });
      const simData = await simRes.json();
      if (!simRes.ok) throw new Error(simData.detail || 'Payment simulation failed');

      const sync = simData.synchronization;
      const receiptNo = sync?.receipt_number || 'RCPT-CONFIRMED';
      const reference = sync?.payment_reference || payData.session_id;

      setPayFeedback({
        message: `Payment of ${fmtMoney(amt)} confirmed and reconciled via ${payMethod.replace('_', ' ').toUpperCase()}`,
        reference: reference,
        receipt_number: receiptNo,
        reconciliation_status: sync?.new_billing_status || 'paid'
      });

      setActiveReceipt({
        receipt_number: receiptNo,
        amount: amt,
        reference: reference,
        method: payMethod,
        date: new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC',
        tenant: leaseData?.lease?.tenant1 || 'Resident',
        property: leaseData?.lease?.address || 'Community',
        unit: leaseData?.lease?.unit || 'Unit',
        billing_period: rentDashboard?.current_bill?.billing_period || 'Current Month'
      });
      setShowReceiptModal(true);

      loadLeaseDetails(activeLeaseId);
      loadRentDashboard(activeLeaseId);
      loadNotifications();
    } catch (err) {
      alert(err.message);
    } finally {
      setIsPaying(false);
    }
  };

  // Handle Document Upload
  const handleDocUpload = async (e) => {
    e.preventDefault();
    if (!docTitle.trim() || !docBody.trim()) return;
    setIsUploadingDoc(true);
    setDocFeedback(null);

    try {
      const res = await fetch('/api/documents/process', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          title: docTitle,
          body: docBody,
          property_id: leaseData?.lease?.property_id || ORG_PROPERTY_FALLBACK[currentOrgId] || 'PROP-001',
          lease_id: activeLeaseId
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      setDocFeedback(data);
      setDocTitle('');
      setDocBody('');
    } catch (err) {
      alert(err.message);
    } finally {
      setIsUploadingDoc(false);
    }
  };

  // Complete Move-In Task
  const handleCompleteMoveInTask = async (taskKey) => {
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/move-in/tasks/${taskKey}/complete`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          completed_by: leaseData?.lease?.tenant1 || 'Resident',
          notes: 'Completed verified via Resident Portal'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to update task');
      setMoveInData(data);
      setFeedback({ type: 'success', message: `Task '${taskKey}' marked complete!` });
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  // Prepare Renewal Offer
  const handlePrepareRenewalOffer = async (e) => {
    e.preventDefault();
    setPreparingOffer(true);
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/renewal/prepare`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          proposed_increase_pct: Number(proposedIncreasePct),
          renewal_term_months: Number(proposedTermMonths),
          prepared_by: 'Resident Portal AI'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to prepare renewal offer');
      setRenewalData(data);
      setFeedback({ type: 'success', message: 'Renewal offer prepared successfully!' });
      loadWorkflows(activeLeaseId);
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    } finally {
      setPreparingOffer(false);
    }
  };

  // Submit Renewal Decision
  const handleRenewalDecision = async (decision) => {
    setSubmittingDecision(true);
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/renewal/decision`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          decision,
          notes: decisionNotes || (decision === 'accepted' ? 'Accepted by resident' : 'Declined by resident')
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to record decision');
      setFeedback({
        type: 'success',
        message: decision === 'accepted'
          ? 'Renewal decision accepted! Manager sign-off is required before finalization.'
          : 'Renewal offer declined.'
      });
      loadWorkflows(activeLeaseId);
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    } finally {
      setSubmittingDecision(false);
    }
  };

  // Approve Renewal (Manager Gate)
  const handleApproveRenewal = async () => {
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/renewal/approve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          manager_name: 'Property Manager',
          approved: true,
          notes: 'Executed authorized lease renewal'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Approval failed');
      setFeedback({ type: 'success', message: 'Lease renewal finalized and contract terms updated!' });
      loadLeaseDetails(activeLeaseId);
      loadWorkflows(activeLeaseId);
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  // Submit Move-Out Notice
  const handleSubmitMoveOutNotice = async (e) => {
    e.preventDefault();
    if (!forwardingAddress.trim()) {
      alert('Please enter a forwarding address for security deposit accounting.');
      return;
    }
    setSubmittingNotice(true);
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/move-out/notice`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          planned_move_out_date: moveOutDate,
          forwarding_address: forwardingAddress,
          resident_name: leaseData?.lease?.tenant1 || 'Resident'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to submit move-out notice');
      setMoveOutData(data);
      setFeedback({
        type: 'success',
        message: `Notice to vacate submitted. Statutory return deadline set to ${data.statutory_deadline_date}.`
      });
      loadWorkflows(activeLeaseId);
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    } finally {
      setSubmittingNotice(false);
    }
  };

  // Complete Move-Out Task
  const handleCompleteMoveOutTask = async (taskKey) => {
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/move-out/tasks/${taskKey}/complete`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          completed_by: 'Inspector / Resident',
          notes: 'Verified inspection item'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to complete move-out task');
      setMoveOutData(data);
      setFeedback({ type: 'success', message: `Move-out task '${taskKey}' recorded.` });
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  // Propose Closeout Deductions
  const handleProposeCloseout = async (e) => {
    e.preventDefault();
    setProposingCloseout(true);
    try {
      const deductions = [
        {
          category: deductionCategory,
          description: deductionDesc,
          amount_usd: Number(deductionAmount),
          evidence: 'Inspection report and turnover invoice'
        }
      ];
      const res = await fetch(`/api/leases/${activeLeaseId}/move-out/closeout/propose`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ deductions })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to propose closeout');
      setMoveOutData(data);
      setFeedback({ type: 'success', message: 'Proposed deposit reconciliation generated. Awaiting manager approval.' });
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    } finally {
      setProposingCloseout(false);
    }
  };

  // Approve Closeout (Manager Gate)
  const handleApproveCloseout = async () => {
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/move-out/closeout/approve`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({
          manager_name: 'Senior Property Manager',
          notes: 'Approved itemized deposit accounting and release.'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to approve closeout');
      setMoveOutData(data);
      setFeedback({ type: 'success', message: 'Closeout approved! Security deposit settlement letter queued for delivery.' });
      loadLeaseDetails(activeLeaseId);
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  // Update Communication Preferences
  const handleTogglePreference = async (key, val) => {
    const cur = preferencesData?.preferences || { email: true, sms: false };
    const updated = { ...cur, [key]: val };
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/preferences`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify(updated)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to update preferences');
      setPreferencesData(data);
      setFeedback({ type: 'success', message: `Communication preference for ${key.toUpperCase()} updated.` });
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  // Send Test Reminder
  const handleSendReminder = async (type) => {
    try {
      const res = await fetch(`/api/leases/${activeLeaseId}/notifications/remind`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ reminder_type: type })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to send reminder');
      setFeedback({
        type: data.status === 'preference_suppressed' ? 'error' : 'success',
        message: data.message || `Reminder queued (${data.status}).`
      });
      loadNotifications();
    } catch (err) {
      setFeedback({ type: 'error', message: err.message });
    }
  };

  const lease = leaseData?.lease || {};
  const recon = leaseData?.reconciliation || {};
  const workOrders = leaseData?.work_orders || [];
  const varianceUsd = (recon.difference_cents || 0) / 100.0;
  const currentOutstandingUsd = rentDashboard?.current_bill
    ? Number(rentDashboard.current_bill.outstanding_balance_usd || 0)
    : (varianceUsd > 0 ? varianceUsd : 0.0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Resident Header Banner */}
      <div className="card" style={{ padding: 24, background: 'var(--surface)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span className="pill emerald">Resident Portal</span>
              <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>Authenticated Resident Experience</span>
              <span className="pill cyan" style={{ fontSize: 11 }}>Org: {currentOrgId}</span>
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 700 }}>
              Welcome Home, {lease.tenant1 || 'Resident'}
            </h2>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 4 }}>
              📍 {lease.address || '535 Mission St'} · {lease.unit || 'Unit 1A'} · Lease Ref: <strong>{activeLeaseId}</strong> · Status: <span className="pill">{lease.lease_status || 'active'}</span>
            </div>
          </div>

          {/* Quick Lease Switcher for Multi-Tenant / Lease Testing */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>Select Tenancy:</span>
            <select
              className="org-select"
              value={activeLeaseId}
              onChange={(e) => setActiveLeaseId(e.target.value)}
              style={{ width: 170 }}
            >
              <option value="LEASE-0001">LEASE-0001 (ORG-APEX · Active)</option>
              <option value="LEASE-0010">LEASE-0010 (ORG-APEX · Expiring)</option>
              <option value="LEASE-0020">LEASE-0020 (ORG-APEX · Move-In)</option>
              <option value="LEASE-0021">LEASE-0021 (ORG-VERDANT · Notice)</option>
              <option value="LEASE-0030">LEASE-0030 (ORG-VERDANT · Preferences)</option>
              <option value="LEASE-0031">LEASE-0031 (ORG-VERDANT · Renewal Hub)</option>
              <option value="LEASE-0032">LEASE-0032 (ORG-VERDANT · Move-Out)</option>
              <option value="LEASE-0041">LEASE-0041 (ORG-BEACON · Commercial Active)</option>
              <option value="LEASE-0050">LEASE-0050 (ORG-BEACON · Expiring)</option>
              <option value="LEASE-0061">LEASE-0061 (ORG-SKYLINE · Urban Active)</option>
              <option value="LEASE-0070">LEASE-0070 (ORG-SKYLINE · Move-In Pending)</option>
            </select>
          </div>
        </div>

        {/* Workflow Tabs Navigation */}
        <div style={{ display: 'flex', gap: 8, marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 16, overflowX: 'auto' }}>
          {[
            { id: 'overview', label: '💳 Overview & Rent Settlement', icon: '🏠' },
            { id: 'move_in', label: '📦 Move-In Checklist', icon: '🔑', badge: moveInData ? `${moveInData.completed_tasks}/${moveInData.total_tasks}` : null },
            { id: 'renewal', label: '📄 Lease Renewal Hub', icon: '🔄', badge: renewalData?.renewal_record ? renewalData.renewal_record.status : 'Check' },
            { id: 'move_out', label: '🚪 Move-Out & Closeout', icon: '📋', badge: moveOutData ? moveOutData.status : null },
            { id: 'preferences', label: '⚙️ Communication Preferences', icon: '🔔' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => { setActiveTab(tab.id); setFeedback(null); }}
              className={`btn btn-sm ${activeTab === tab.id ? 'btn-primary' : 'btn-secondary'}`}
              style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}
            >
              <span>{tab.label}</span>
              {tab.badge && (
                <span className="pill" style={{ fontSize: 10, padding: '2px 6px', background: activeTab === tab.id ? 'rgba(255,255,255,0.2)' : 'var(--surface-hover)' }}>
                  {tab.badge}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Global Feedback Banner */}
      {feedback && (
        <div style={{
          padding: 12,
          borderRadius: 8,
          background: feedback.type === 'error' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)',
          border: `1px solid ${feedback.type === 'error' ? 'var(--rose)' : 'var(--emerald)'}`,
          color: feedback.type === 'error' ? 'var(--rose)' : 'var(--emerald)',
          fontWeight: 600,
          fontSize: 13,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{feedback.type === 'error' ? '⚠️' : '✓'} {feedback.message}</span>
          <button onClick={() => setFeedback(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}>✕</button>
        </div>
      )}

      {/* KPI Summary Cards */}
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-accent-bar accent-cyan"></div>
          <div className="kpi-label">Monthly Rent Obligation</div>
          <div className="kpi-value">{fmtMoney(lease.monthly_rent_usd)}</div>
          <div className="kpi-sub">Lease End Date: <strong>{lease.end_date || 'N/A'}</strong></div>
        </div>

        <div className="kpi-card">
          <div className={`kpi-accent-bar ${currentOutstandingUsd > 0 ? 'accent-rose' : 'accent-emerald'}`}></div>
          <div className="kpi-label">Current Outstanding Balance</div>
          <div className="kpi-value" style={{ color: currentOutstandingUsd > 0 ? 'var(--rose)' : 'var(--emerald)' }}>
            {fmtMoney(currentOutstandingUsd)}
          </div>
          <div className="kpi-sub">
            {currentOutstandingUsd > 0 ? '⚠️ Unsettled balance due' : '✓ 100% Paid & Reconciled'}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-purple"></div>
          <div className="kpi-label">Security Deposit Escrow</div>
          <div className="kpi-value">{fmtMoney(lease.security_deposit_usd)}</div>
          <div className="kpi-sub">Held in compliant trust account</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-accent-bar accent-amber"></div>
          <div className="kpi-label">Active Work Orders</div>
          <div className="kpi-value">{workOrders.length}</div>
          <div className="kpi-sub">Logged work orders on record</div>
        </div>
      </div>

      {/* TAB 1: OVERVIEW & RENT REMITTANCE */}
      {/* TAB 1: OVERVIEW & RENT REMITTANCE */}
      {activeTab === 'overview' && (
        <>
          {/* Overdue 3-Day Deadline Alert Banner */}
          {(rentDashboard?.current_bill?.status === 'overdue' || rentDashboard?.current_bill?.status === 'action_required') && (
            <div style={{
              marginBottom: 20,
              padding: 16,
              borderRadius: 8,
              background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(245, 158, 11, 0.15))',
              border: '2px solid var(--rose)',
              display: 'flex',
              flexDirection: 'column',
              gap: 8
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--rose)', display: 'flex', alignItems: 'center', gap: 8 }}>
                  ⚠️ STATUTORY NOTICE OF OVERDUE RENT — 3-DAY PAYMENT DEADLINE
                </span>
                <span className="pill rose" style={{ fontWeight: 700, letterSpacing: 0.5 }}>
                  ACTION REQUIRED
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.5 }}>
                Your rent payment for <strong>{rentDashboard.current_bill.billing_period}</strong> was due on <strong>{rentDashboard.current_bill.due_date}</strong>. The contractual grace period expired on <strong>{rentDashboard.current_bill.grace_period_end}</strong>.
                To prevent statutory legal notice escalation, the outstanding balance of <strong>{fmtMoney(rentDashboard.current_bill.outstanding_amount_usd)}</strong> must be settled by:
              </div>
              <div style={{
                fontSize: 14,
                fontWeight: 700,
                color: 'var(--rose)',
                background: 'rgba(239, 68, 68, 0.1)',
                padding: '8px 12px',
                borderRadius: 6,
                display: 'inline-block',
                width: 'fit-content'
              }}>
                ⏰ Strict Payment Deadline: {rentDashboard.current_bill.three_day_deadline || 'Within 3 Calendar Days (23:59:59 UTC)'}
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            {/* Left Column: Authoritative Monthly Rent Obligation & Settlement */}
            <div className="card" style={{ padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>💳 Monthly Rent Obligation</h3>
                <span className={`pill ${
                  rentDashboard?.current_bill?.status === 'paid' ? 'emerald' :
                  rentDashboard?.current_bill?.status === 'overdue' ? 'rose' :
                  rentDashboard?.current_bill?.status === 'due' ? 'cyan' :
                  rentDashboard?.current_bill?.status === 'processing' ? 'amber' : 'purple'
                }`} style={{ textTransform: 'uppercase', fontWeight: 700, fontSize: 11 }}>
                  {rentDashboard?.current_bill?.status === 'paid' ? '✓ Paid & Reconciled' :
                   rentDashboard?.current_bill?.status === 'overdue' ? 'Overdue' :
                   rentDashboard?.current_bill?.status === 'due' ? 'Due' :
                   rentDashboard?.current_bill?.status || 'Upcoming'}
                </span>
              </div>

              {/* Obligation Details Summary */}
              <div style={{ background: 'var(--surface-hover)', padding: 14, borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Billing Period:</span>
                  <strong>{rentDashboard?.current_bill?.billing_period || 'Current Billing Cycle'}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Property & Unit:</span>
                  <span>{leaseData?.lease?.address || 'Skyline Terrace'} · {leaseData?.lease?.unit || 'Unit'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Contractual Due Date:</span>
                  <span>{rentDashboard?.current_bill?.due_date || '1st of month'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Grace Period End:</span>
                  <span>{rentDashboard?.current_bill?.grace_period_end || '4th of month'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ color: 'var(--text-dim)' }}>Base Rent:</span>
                  <span>{fmtMoney(rentDashboard?.current_bill?.rent_amount_usd || lease.monthly_rent_usd)}</span>
                </div>
                {(rentDashboard?.current_bill?.late_fee_usd > 0) && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, color: 'var(--rose)' }}>
                    <span>Applicable Late Fee:</span>
                    <span>+{fmtMoney(rentDashboard.current_bill.late_fee_usd)}</span>
                  </div>
                )}
                <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 8, display: 'flex', justifyContent: 'space-between', fontSize: 15, fontWeight: 700 }}>
                  <span>Outstanding Balance:</span>
                  <span style={{ color: (rentDashboard?.current_bill?.outstanding_amount_usd || 0) > 0 ? 'var(--rose)' : 'var(--emerald)' }}>
                    {fmtMoney(rentDashboard?.current_bill?.outstanding_amount_usd ?? 0)}
                  </span>
                </div>
              </div>

              {payFeedback && (
                <div style={{
                  padding: 12,
                  borderRadius: 6,
                  background: (payFeedback.reconciliation_status === 'settled' || payFeedback.reconciliation_status === 'reconciled' || payFeedback.reconciliation_status === 'paid')
                    ? 'rgba(16, 185, 129, 0.1)'
                    : 'rgba(245, 158, 11, 0.1)',
                  border: `1px solid ${(payFeedback.reconciliation_status === 'settled' || payFeedback.reconciliation_status === 'reconciled' || payFeedback.reconciliation_status === 'paid') ? 'var(--emerald)' : 'var(--amber)'}`,
                  marginBottom: 16
                }}>
                  <div style={{
                    fontWeight: 600,
                    color: (payFeedback.reconciliation_status === 'settled' || payFeedback.reconciliation_status === 'reconciled' || payFeedback.reconciliation_status === 'paid') ? 'var(--emerald)' : 'var(--amber)'
                  }}>
                    {(payFeedback.reconciliation_status === 'settled' || payFeedback.reconciliation_status === 'reconciled' || payFeedback.reconciliation_status === 'paid')
                      ? `✓ Verified Settlement: ${payFeedback.message}`
                      : `⏳ Payment Submitted: ${payFeedback.message}`}
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>Ref: <code>{payFeedback.reference}</code></span>
                    {payFeedback.receipt_number && (
                      <button
                        onClick={() => setShowReceiptModal(true)}
                        className="btn btn-sm btn-secondary"
                        style={{ padding: '2px 8px', fontSize: 11 }}
                      >
                        View Receipt
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* State 1: Paid In Full */}
              {rentDashboard?.current_bill?.status === 'paid' ? (
                <div style={{
                  background: 'rgba(16, 185, 129, 0.08)',
                  border: '1px solid var(--emerald)',
                  borderRadius: 8,
                  padding: 16,
                  textAlign: 'center'
                }}>
                  <div style={{ fontSize: 18, color: 'var(--emerald)', fontWeight: 700, marginBottom: 6 }}>
                    ✓ Rent Paid In Full
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 14 }}>
                    The rent obligation for {rentDashboard.current_bill.billing_period} has been settled and reconciled.
                    Next payment window will open according to your lease schedule.
                  </div>
                  <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
                    <button
                      type="button"
                      className="btn btn-emerald"
                      onClick={() => {
                        setActiveReceipt({
                          receipt_number: rentDashboard.current_bill.receipt_reference || `RCPT-${activeLeaseId}-${rentDashboard.current_bill.billing_period}`,
                          amount: rentDashboard.current_bill.rent_amount_usd,
                          reference: rentDashboard.current_bill.payment_reference || 'CONFIRMED',
                          method: 'Direct Bank ACH Wire',
                          date: rentDashboard.current_bill.payment_confirmed_at ? new Date(rentDashboard.current_bill.payment_confirmed_at).toLocaleString() : 'Confirmed',
                          tenant: leaseData?.lease?.tenant1 || 'Resident',
                          property: leaseData?.lease?.address || 'Community',
                          unit: leaseData?.lease?.unit || 'Unit',
                          billing_period: rentDashboard.current_bill.billing_period
                        });
                        setShowReceiptModal(true);
                      }}
                    >
                      📄 View Official Receipt
                    </button>
                  </div>
                </div>
              ) : rentDashboard?.payment_eligibility?.can_pay ? (
                /* State 2: Eligible To Pay */
                <form onSubmit={handlePayRent} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                      Payment Amount (USD)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      className="input-field"
                      value={payAmount}
                      onChange={(e) => setPayAmount(e.target.value)}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                      Payment Method
                    </label>
                    <select
                      className="input-field"
                      value={payMethod}
                      onChange={(e) => setPayMethod(e.target.value)}
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                    >
                      <option value="ach_transfer">Direct Bank ACH Wire (Zero Surcharge · Reconciled)</option>
                      <option value="credit_card">Credit / Debit Card (Secure Tokenized Gateway)</option>
                      <option value="cashiers_check">Cashier's Check / Electronic Voucher</option>
                    </select>
                  </div>

                  <div style={{ background: 'var(--surface-hover)', padding: 12, borderRadius: 6, fontSize: 12 }}>
                    🛡 <strong>Financial Protection:</strong> Zero raw card storage. Server-side idempotency prevents duplicate debit on retries.
                  </div>

                  <button
                    type="submit"
                    className="btn btn-emerald"
                    disabled={isPaying}
                    style={{ padding: '12px 18px', fontSize: 14, fontWeight: 700 }}
                  >
                    {isPaying ? 'Processing Remittance...' : `💳 Pay Rent Now (${fmtMoney(payAmount || 0)})`}
                  </button>
                </form>
              ) : (
                /* State 3: Upcoming / Ineligible */
                <div style={{
                  background: 'var(--surface-hover)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: 16,
                  textAlign: 'center'
                }}>
                  <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                    🔒 Payment Window Not Yet Active
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                    {rentDashboard?.payment_eligibility?.reason || 'Payment window opens according to lease terms.'}
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: Submit Maintenance Request */}
            <div className="card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>🛠 Submit Maintenance Request</h3>
              {maintResult && (
                <div style={{ padding: 12, borderRadius: 6, background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--primary)', marginBottom: 16 }}>
                  <div style={{ fontWeight: 600, color: 'var(--primary)' }}>
                    ✓ {maintResult.work_order_id} Triaged as {maintResult.priority}
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    Category: <strong>{maintResult.category}</strong> · SLA Deadline: <strong>{new Date(maintResult.sla_deadline).toLocaleString()}</strong>
                  </div>
                </div>
              )}

              <form onSubmit={handleMaintenanceSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Issue Description (e.g. leaking faucet, flickering kitchen lights, broken AC)
                  </label>
                  <textarea
                    className="input-field"
                    rows={3}
                    placeholder="Describe what is broken or leaking..."
                    value={maintDesc}
                    onChange={(e) => setMaintDesc(e.target.value)}
                    required
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Estimated Repair Scope / Cost (USD)
                  </label>
                  <input
                    type="number"
                    step="25"
                    className="input-field"
                    value={maintCost}
                    onChange={(e) => setMaintCost(e.target.value)}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  />
                </div>

                <button type="submit" className="btn btn-primary" disabled={submittingMaint}>
                  {submittingMaint ? 'Triaging with AI...' : 'Submit Maintenance Ticket'}
                </button>
              </form>
            </div>
          </div>

          {/* Previous Rent Payments & Receipts */}
          <div className="card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>📜 Previous Rent Payments & Reconciled Receipts</h3>
              <span className="pill cyan" style={{ fontSize: 11 }}>
                {rentDashboard?.payment_history?.length || 0} Recorded
              </span>
            </div>
            {(!rentDashboard?.payment_history || rentDashboard.payment_history.length === 0) ? (
              <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>No previous payment receipts on record for this lease.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Billing Period</th>
                    <th>Payment Date</th>
                    <th>Amount Paid</th>
                    <th>Method</th>
                    <th>Status</th>
                    <th>Reference</th>
                    <th>Receipt</th>
                  </tr>
                </thead>
                <tbody>
                  {rentDashboard.payment_history.map((tx) => (
                    <tr key={tx.id || tx.reference}>
                      <td><strong>{tx.billing_period || 'N/A'}</strong></td>
                      <td>{tx.confirmed_at ? new Date(tx.confirmed_at).toLocaleString() : 'Confirmed'}</td>
                      <td><strong>{fmtMoney(tx.amount_usd)}</strong></td>
                      <td><span className="pill">{tx.payment_method || 'ACH'}</span></td>
                      <td>
                        <span className="pill emerald">✓ Reconciled</span>
                      </td>
                      <td><code style={{ fontSize: 11 }}>{tx.reference}</code></td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-sm btn-secondary"
                          onClick={() => {
                            setActiveReceipt({
                              receipt_number: tx.receipt_reference || `RCPT-${activeLeaseId}-${tx.billing_period || 'TX'}`,
                              amount: tx.amount_usd,
                              reference: tx.reference,
                              method: tx.payment_method || 'ACH Transfer',
                              date: tx.confirmed_at ? new Date(tx.confirmed_at).toLocaleString() : 'Confirmed',
                              tenant: leaseData?.lease?.tenant1 || 'Resident',
                              property: leaseData?.lease?.address || 'Community',
                              unit: leaseData?.lease?.unit || 'Unit',
                              billing_period: tx.billing_period || 'Current'
                            });
                            setShowReceiptModal(true);
                          }}
                        >
                          📄 View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Active Work Orders */}
          <div className="card" style={{ padding: 20 }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>📋 Active Work Orders & SLA Status</h3>
            {workOrders.length === 0 ? (
              <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>No active maintenance requests for this lease.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Order ID</th>
                    <th>Category</th>
                    <th>Issue</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Assigned Contractor</th>
                    <th>Estimated Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {workOrders.map((wo) => (
                    <tr key={wo.work_order_id}>
                      <td><strong>{wo.work_order_id}</strong></td>
                      <td>{wo.category}</td>
                      <td style={{ maxWidth: 220, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {wo.description}
                      </td>
                      <td>
                        <span className={`pill ${wo.priority === 'Emergency' ? 'rose' : wo.priority === 'High' ? 'amber' : 'cyan'}`}>
                          {wo.priority}
                        </span>
                      </td>
                      <td>{wo.status}</td>
                      <td>{wo.technician || 'Assigned'}</td>
                      <td>{fmtMoney(wo.estimated_cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Document Upload & Notifications Feed */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div className="card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>📄 Upload Resident Document</h3>
              {docFeedback && (
                <div style={{ padding: 12, borderRadius: 6, background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--primary)', marginBottom: 16 }}>
                  <div style={{ fontWeight: 600 }}>✓ {docFeedback.message}</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    Detected Kind: <strong>{docFeedback.kind}</strong> (Confidence: {docFeedback.confidence})
                  </div>
                </div>
              )}

              <form onSubmit={handleDocUpload} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <input
                  type="text"
                  placeholder="Document Title (e.g. Renter's Insurance Policy 2026)"
                  className="input-field"
                  value={docTitle}
                  onChange={(e) => setDocTitle(e.target.value)}
                  required
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                />
                <textarea
                  rows={3}
                  placeholder="Paste document text or covenants..."
                  className="input-field"
                  value={docBody}
                  onChange={(e) => setDocBody(e.target.value)}
                  required
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                />
                <button type="submit" className="btn btn-secondary btn-sm" disabled={isUploadingDoc}>
                  {isUploadingDoc ? 'Scanning...' : 'Upload & Process with AI'}
                </button>
              </form>
            </div>

            <div className="card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>🔔 Official Notifications Feed</h3>
              <div style={{ maxHeight: 240, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {notifications.slice(0, 6).map((n) => (
                  <div key={n.id} style={{ flexShrink: 0, padding: 10, background: 'var(--surface-hover)', borderRadius: 6, fontSize: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                      <span>{n.title}</span>
                      <span className="pill" style={{ fontSize: 9 }}>{n.status}</span>
                    </div>
                    <div style={{ color: 'var(--text-dim)', marginTop: 4 }}>{n.message}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {/* TAB 2: MOVE-IN CHECKLIST */}
      {activeTab === 'move_in' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="card" style={{ padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 700 }}>📦 Resident Move-In Onboarding Checklist</h3>
                <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 2 }}>
                  Target Move-In Date: <strong>{moveInData?.target_move_in_date || lease.move_in_date || 'Pending'}</strong>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span className={`pill ${moveInData?.status === 'completed' ? 'emerald' : moveInData?.status === 'overdue' ? 'rose' : 'amber'}`}>
                  Status: {moveInData?.status || 'in_progress'}
                </span>
                <span className="pill cyan" style={{ fontWeight: 700 }}>
                  {moveInData?.progress_percent || 0}% Complete ({moveInData?.completed_tasks || 0}/{moveInData?.total_tasks || 6})
                </span>
              </div>
            </div>

            {/* Progress Bar */}
            <div style={{ width: '100%', height: 8, background: 'var(--surface-hover)', borderRadius: 4, overflow: 'hidden', marginBottom: 20 }}>
              <div
                style={{
                  width: `${moveInData?.progress_percent || 0}%`,
                  height: '100%',
                  background: moveInData?.status === 'completed' ? 'var(--emerald)' : 'var(--primary)',
                  transition: 'width 0.4s ease'
                }}
              />
            </div>

            {/* Missing Requirements Alert */}
            {moveInData?.missing_requirements?.length > 0 && (
              <div style={{ padding: 12, borderRadius: 6, background: 'rgba(245, 158, 11, 0.1)', border: '1px solid var(--amber)', marginBottom: 20, fontSize: 13 }}>
                ⚠️ <strong>Missing Requirements ({moveInData.missing_requirements.length}):</strong> {moveInData.missing_requirements.join(', ')}
              </div>
            )}

            {/* Task Item Cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(moveInData?.tasks || []).map((t) => (
                <div
                  key={t.task_key}
                  style={{
                    padding: 16,
                    borderRadius: 8,
                    background: t.is_completed ? 'rgba(16, 185, 129, 0.05)' : 'var(--surface-hover)',
                    border: `1px solid ${t.is_completed ? 'var(--emerald)' : 'var(--border)'}`,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: 12
                  }}
                >
                  <div style={{ flex: 1, minWidth: 260 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span className="pill" style={{ fontSize: 10 }}>{t.category}</span>
                      <strong style={{ fontSize: 14 }}>{t.title}</strong>
                      {t.is_completed && <span className="pill emerald" style={{ fontSize: 10 }}>✓ Completed</span>}
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>{t.description}</div>
                    {t.is_completed && (
                      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
                        Completed by <strong>{t.completed_by}</strong> on {new Date(t.completed_at).toLocaleString()} {t.notes && `· Note: "${t.notes}"`}
                      </div>
                    )}
                  </div>

                  {!t.is_completed && (
                    <button
                      onClick={() => handleCompleteMoveInTask(t.task_key)}
                      className="btn btn-sm btn-primary"
                    >
                      Verify & Complete Task
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: LEASE RENEWAL HUB */}
      {activeTab === 'renewal' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Active Renewal Status Card */}
          <div className="card" style={{ padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16, marginBottom: 20 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span className="pill cyan">Lease Lifecycle Agent</span>
                  <span className={`pill ${renewalData?.renewal_record?.status === 'finalized' ? 'emerald' : 'amber'}`}>
                    Status: {renewalData?.renewal_record?.status || 'upcoming'}
                  </span>
                </div>
                <h3 style={{ fontSize: 20, fontWeight: 700 }}>
                  Lease Expiration & Renewal Decision Hub
                </h3>
                <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 4 }}>
                  Current Lease Expiration: <strong>{renewalData?.lease?.end_date || lease.end_date || 'N/A'}</strong> · Countdown: <strong>{renewalData?.days_until_expiration || 0} days remaining</strong>
                </div>
              </div>

              <div style={{ textAlign: 'right' }}>
                <span className={`pill ${renewalData?.renewal_eligibility === 'eligible' ? 'emerald' : 'amber'}`} style={{ fontSize: 12, padding: '4px 10px' }}>
                  Renewal Standing: {renewalData?.renewal_eligibility?.toUpperCase() || 'ELIGIBLE'}
                </span>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                  {renewalData?.eligibility_reason}
                </div>
              </div>
            </div>

            {/* Active Offer Details */}
            {renewalData?.renewal_record ? (
              <div style={{ padding: 20, borderRadius: 8, background: 'var(--surface-hover)', border: '1px solid var(--border)', marginBottom: 20 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Current Contract Rent</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>{fmtMoney(renewalData.renewal_record.current_rent_usd)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Proposed Renewal Rent</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--emerald)' }}>{fmtMoney(renewalData.renewal_record.proposed_rent_usd)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Renewal Term & Period</div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{renewalData.renewal_record.term_months} Months ({renewalData.renewal_record.renewal_period})</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Manager Approval Gate</div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>
                      <span className={`pill ${renewalData.renewal_record.manager_approval_state === 'approved' ? 'emerald' : 'amber'}`}>
                        {renewalData.renewal_record.manager_approval_state?.toUpperCase()}
                      </span>
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 16 }}>
                  📜 <strong>Covenants & Terms:</strong> {renewalData.renewal_record.offer_terms}
                </div>

                {/* Resident Action Controls */}
                {renewalData.renewal_record.status === 'offer_prepared' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                    <input
                      type="text"
                      className="input-field"
                      placeholder="Optional notes or questions for property manager..."
                      value={decisionNotes}
                      onChange={(e) => setDecisionNotes(e.target.value)}
                      style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                    />
                    <div style={{ display: 'flex', gap: 12 }}>
                      <button
                        onClick={() => handleRenewalDecision('accepted')}
                        className="btn btn-emerald"
                        disabled={submittingDecision}
                      >
                        ✓ Accept Renewal Offer (+{renewalData.renewal_record.proposed_rent_usd ? (((renewalData.renewal_record.proposed_rent_usd / renewalData.renewal_record.current_rent_usd) - 1) * 100).toFixed(1) : '3.5'}%)
                      </button>
                      <button
                        onClick={() => handleRenewalDecision('declined')}
                        className="btn btn-secondary"
                        disabled={submittingDecision}
                      >
                        ✕ Decline & Plan Move-Out
                      </button>
                    </div>
                  </div>
                )}

                {/* Manager Finalize Gate */}
                {renewalData.renewal_record.status === 'pending_approval' && (
                  <div style={{ padding: 14, borderRadius: 6, background: 'rgba(245, 158, 11, 0.1)', border: '1px solid var(--amber)', marginTop: 12 }}>
                    <div style={{ fontWeight: 600, color: 'var(--amber)' }}>
                      🛡 Human Manager Gate Required: Resident has accepted the offer. Contract terms cannot be modified until an authorized manager executes approval.
                    </div>
                    <button
                      onClick={handleApproveRenewal}
                      className="btn btn-sm btn-primary"
                      style={{ marginTop: 10 }}
                    >
                      Authorize & Finalize Renewal Contract
                    </button>
                  </div>
                )}

                {renewalData.renewal_record.status === 'finalized' && (
                  <div style={{ padding: 12, borderRadius: 6, background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--emerald)', marginTop: 12, color: 'var(--emerald)', fontWeight: 600 }}>
                    ✓ Renewal Contract Finalized! Approved by {renewalData.renewal_record.approved_by || 'Property Manager'} on {new Date(renewalData.renewal_record.approved_at).toLocaleDateString()}.
                  </div>
                )}
              </div>
            ) : (
              <div style={{ padding: 24, borderRadius: 8, background: 'var(--surface-hover)', textAlign: 'center', marginBottom: 20 }}>
                <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>No renewal offer has been formulated yet for this renewal period.</p>
              </div>
            )}

            {/* Prepare New Offer Panel (Manager / AI Agent Formulation) */}
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 20 }}>
              <h4 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>⚙️ Prepare / Revise Renewal Offer</h4>
              <form onSubmit={handlePrepareRenewalOffer} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 16, alignItems: 'flex-end' }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Rent Escalation Rate (% increase)
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="30"
                    className="input-field"
                    value={proposedIncreasePct}
                    onChange={(e) => setProposedIncreasePct(e.target.value)}
                    required
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Renewal Term (Months)
                  </label>
                  <select
                    className="input-field"
                    value={proposedTermMonths}
                    onChange={(e) => setProposedTermMonths(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  >
                    <option value="6">6 Months</option>
                    <option value="12">12 Months (Standard)</option>
                    <option value="24">24 Months</option>
                  </select>
                </div>
                <button type="submit" className="btn btn-primary" disabled={preparingOffer}>
                  {preparingOffer ? 'Formulating...' : 'Generate Renewal Offer'}
                </button>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* TAB 4: MOVE-OUT & SECURITY DEPOSIT CLOSEOUT */}
      {activeTab === 'move_out' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Notice to Vacate & Statutory Clock */}
          <div className="card" style={{ padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 700 }}>🚪 Resident Move-Out & Deposit Closeout</h3>
                <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 2 }}>
                  Cal. Civ. Code § 1950.5 21-Day Statutory Return Compliance Engine
                </div>
              </div>
              {moveOutData && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <span className="pill amber">Status: {moveOutData.status}</span>
                  <span className="pill cyan">Deadline: {moveOutData.statutory_deadline_date}</span>
                </div>
              )}
            </div>

            {moveOutData ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ padding: 16, borderRadius: 8, background: 'var(--surface-hover)', border: '1px solid var(--border)' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Planned Move-Out Date</div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{moveOutData.planned_move_out_date}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Forwarding Address</div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{moveOutData.forwarding_address}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>Statutory Escrow Clock</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--primary)' }}>21-Day Clock Active ({moveOutData.statutory_deadline_date})</div>
                    </div>
                  </div>
                </div>

                {/* Move-Out Checklist Tasks */}
                <h4 style={{ fontSize: 15, fontWeight: 700 }}>Inspection & Turnover Checklist</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {(moveOutData.tasks || []).map((t) => (
                    <div
                      key={t.task_key}
                      style={{
                        padding: 12,
                        borderRadius: 6,
                        background: t.is_completed ? 'rgba(16, 185, 129, 0.05)' : 'var(--surface-hover)',
                        border: `1px solid ${t.is_completed ? 'var(--emerald)' : 'var(--border)'}`,
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div>
                        <strong>{t.title}</strong>
                        <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{t.description}</div>
                        {t.is_completed && (
                          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                            Completed by {t.completed_by} on {new Date(t.completed_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                      {!t.is_completed && (
                        <button
                          onClick={() => handleCompleteMoveOutTask(t.task_key)}
                          className="btn btn-sm btn-secondary"
                        >
                          Mark Completed
                        </button>
                      )}
                    </div>
                  ))}
                </div>

                {/* Security Deposit Accounting Proposal */}
                <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                  <h4 style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>💰 Security Deposit Accounting & Disbursement</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 16 }}>
                    <div className="kpi-card" style={{ padding: 14 }}>
                      <div className="kpi-label">Held Escrow Deposit</div>
                      <div className="kpi-value">{fmtMoney(moveOutData.security_deposit_usd)}</div>
                    </div>
                    <div className="kpi-card" style={{ padding: 14 }}>
                      <div className="kpi-label">Unpaid Rent Balance</div>
                      <div className="kpi-value" style={{ color: moveOutData.outstanding_rent_balance_usd > 0 ? 'var(--rose)' : 'inherit' }}>
                        {fmtMoney(moveOutData.outstanding_rent_balance_usd)}
                      </div>
                    </div>
                    <div className="kpi-card" style={{ padding: 14 }}>
                      <div className="kpi-label">Itemized Deductions</div>
                      <div className="kpi-value">
                        {fmtMoney((moveOutData.proposed_deductions || []).reduce((acc, d) => acc + (d.amount_usd || 0), 0))}
                      </div>
                    </div>
                    <div className="kpi-card" style={{ padding: 14 }}>
                      <div className="kpi-label">Proposed Net Refund</div>
                      <div className="kpi-value" style={{ color: 'var(--emerald)' }}>{fmtMoney(moveOutData.proposed_refund_usd)}</div>
                    </div>
                  </div>

                  {/* Propose Closeout Panel */}
                  <form onSubmit={handleProposeCloseout} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 120px auto', gap: 12, alignItems: 'flex-end', marginBottom: 16 }}>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Deduction Category</label>
                      <select
                        className="input-field"
                        value={deductionCategory}
                        onChange={(e) => setDeductionCategory(e.target.value)}
                        style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}
                      >
                        <option value="repair">Unit Damage Repair</option>
                        <option value="cleaning">Turnover Deep Clean</option>
                        <option value="utility">Final Utility Settlement</option>
                      </select>
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description & Evidence</label>
                      <input
                        type="text"
                        className="input-field"
                        value={deductionDesc}
                        onChange={(e) => setDeductionDesc(e.target.value)}
                        required
                        style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Amount (USD)</label>
                      <input
                        type="number"
                        step="10"
                        className="input-field"
                        value={deductionAmount}
                        onChange={(e) => setDeductionAmount(e.target.value)}
                        required
                        style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}
                      />
                    </div>
                    <button type="submit" className="btn btn-secondary btn-sm" disabled={proposingCloseout}>
                      {proposingCloseout ? 'Calculating...' : 'Propose Closeout'}
                    </button>
                  </form>

                  {/* Manager Approval Requirement Alert */}
                  {moveOutData.status === 'pending_closeout_approval' && (
                    <div style={{ padding: 14, borderRadius: 6, background: 'rgba(245, 158, 11, 0.1)', border: '1px solid var(--amber)' }}>
                      <div style={{ fontWeight: 600, color: 'var(--amber)' }}>
                        🛡 Human Manager Sign-Off Required: Security deposit funds are held in compliant escrow and cannot be disbursed automatically without Property Manager authorization.
                      </div>
                      <button onClick={handleApproveCloseout} className="btn btn-sm btn-primary" style={{ marginTop: 10 }}>
                        Authorize Deposit Refund & Close Tenancy
                      </button>
                    </div>
                  )}

                  {moveOutData.status === 'closed' && (
                    <div style={{ padding: 12, borderRadius: 6, background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--emerald)', color: 'var(--emerald)', fontWeight: 600 }}>
                      ✓ Tenancy Closed & Escrow Disbursed! Approved by {moveOutData.approved_by || 'Property Manager'} on {new Date(moveOutData.approved_at).toLocaleDateString()}.
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <form onSubmit={handleSubmitMoveOutNotice} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <p style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  Submit a formal 30-day notice to vacate. Initiates inspection tasks, key return tracking, and the 21-day statutory deposit return countdown.
                </p>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Planned Move-Out Date
                  </label>
                  <input
                    type="date"
                    className="input-field"
                    value={moveOutDate}
                    onChange={(e) => setMoveOutDate(e.target.value)}
                    required
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Forwarding Postal Address (Required for Security Deposit Refund)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. 742 Evergreen Terrace, Springfield, OR 97477"
                    className="input-field"
                    value={forwardingAddress}
                    onChange={(e) => setForwardingAddress(e.target.value)}
                    required
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Reason for Vacating
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={noticeReason}
                    onChange={(e) => setNoticeReason(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
                  />
                </div>
                <button type="submit" className="btn btn-primary" disabled={submittingNotice}>
                  {submittingNotice ? 'Submitting Notice...' : 'Submit Official Notice to Vacate'}
                </button>
              </form>
            )}
          </div>
        </div>
      )}

      {/* TAB 5: COMMUNICATION PREFERENCES */}
      {activeTab === 'preferences' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="card" style={{ padding: 24 }}>
            <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>⚙️ Resident Communication Preferences</h3>
            <p style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 20 }}>
              Control multi-channel delivery preferences. The system respects opt-outs and deduplicates alerts via stable event keys.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ padding: 16, borderRadius: 8, background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong>Email Delivery Channel</strong>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                    Receive official notices, renewal reminders, and move-in/move-out task checklists at <code>{preferencesData?.resident_email || lease.resident_email}</code>.
                  </div>
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={preferencesData?.preferences?.email ?? true}
                    onChange={(e) => handleTogglePreference('email', e.target.checked)}
                  />
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    {preferencesData?.preferences?.email ? 'Enabled' : 'Opted-Out'}
                  </span>
                </label>
              </div>

              <div style={{ padding: 16, borderRadius: 8, background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong>SMS / Text Message Alerts</strong>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                    Instant emergency maintenance dispatch and inspection reminders.
                  </div>
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={preferencesData?.preferences?.sms ?? false}
                    onChange={(e) => handleTogglePreference('sms', e.target.checked)}
                  />
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    {preferencesData?.preferences?.sms ? 'Enabled' : 'Disabled'}
                  </span>
                </label>
              </div>

              {/* Delivery Gateway Status */}
              <div style={{ padding: 14, borderRadius: 6, background: 'rgba(59, 130, 246, 0.08)', border: '1px solid var(--primary)', fontSize: 13 }}>
                📡 <strong>Delivery Queue Transparency:</strong> External SMTP / Twilio integrations operate in simulated queue mode when external gateway credentials are omitted, preventing false delivery claims.
              </div>

              {/* Test Reminder Triggers */}
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                <h4 style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>🧪 Test Idempotent Notification Triggers</h4>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  <button onClick={() => handleSendReminder('renewal')} className="btn btn-sm btn-secondary">
                    Trigger Renewal Alert
                  </button>
                  <button onClick={() => handleSendReminder('move_in')} className="btn btn-sm btn-secondary">
                    Trigger Move-In Task Reminder
                  </button>
                  <button onClick={() => handleSendReminder('move_out')} className="btn btn-sm btn-secondary">
                    Trigger Move-Out Checklist Notice
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* View / Download Official Receipt Modal */}
      {showReceiptModal && activeReceipt && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          backdropFilter: 'blur(4px)'
        }}>
          <div className="card" style={{
            maxWidth: 520,
            width: '90%',
            background: 'var(--surface)',
            border: '2px solid var(--emerald)',
            borderRadius: 12,
            boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
            padding: 28
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--border)', paddingBottom: 16, marginBottom: 20 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--emerald)', letterSpacing: 1.2, textTransform: 'uppercase' }}>
                  ENIGMA Official Payment Confirmation
                </div>
                <h2 style={{ fontSize: 20, fontWeight: 800, margin: '4px 0 0 0' }}>
                  Rent Remittance Receipt
                </h2>
              </div>
              <button
                onClick={() => setShowReceiptModal(false)}
                style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-dim)' }}
              >
                ✕
              </button>
            </div>

            {/* Receipt Body */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Receipt Number:</span>
                <strong style={{ fontFamily: 'monospace' }}>{activeReceipt.receipt_number}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Payment Reference:</span>
                <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{activeReceipt.reference}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Resident:</span>
                <strong>{activeReceipt.tenant}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Property & Unit:</span>
                <span>{activeReceipt.property} · {activeReceipt.unit}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Billing Period:</span>
                <span>{activeReceipt.billing_period}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Payment Method:</span>
                <span>{activeReceipt.method}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-dim)' }}>Timestamp (UTC):</span>
                <span>{activeReceipt.date}</span>
              </div>
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '12px 14px',
                background: 'rgba(16, 185, 129, 0.12)',
                borderRadius: 8,
                marginTop: 8
              }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--emerald)' }}>Amount Paid:</span>
                <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--emerald)' }}>{fmtMoney(activeReceipt.amount)}</span>
              </div>
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: 10, marginTop: 24, justifyContent: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => window.print()}
              >
                🖨 Print / Save PDF
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setShowReceiptModal(false)}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
