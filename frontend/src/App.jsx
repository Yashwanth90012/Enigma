import React, { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import TenantARModule from './components/TenantARModule';
import VendorAPModule from './components/VendorAPModule';
import OperationalDashboardOverview from './components/OperationalDashboardOverview';
import EquilibraAssistant from './components/EquilibraAssistant';
import { cachedFetch } from './apiCache';

// Lazy-loaded secondary hubs & portals
const CustomerRequirementsPortal = lazy(() => import('./components/CustomerRequirementsPortal'));
const PublicListingsPortal = lazy(() => import('./components/PublicListingsPortal'));
const ResidentPortal = lazy(() => import('./components/ResidentPortal'));
const AdminDiagnosticsPortal = lazy(() => import('./components/AdminDiagnosticsPortal'));
const ComplianceRiskHub = lazy(() => import('./components/ComplianceRiskHub'));
const CommunicationTemplatesHub = lazy(() => import('./components/CommunicationTemplatesHub'));
const DocumentIntelligenceHub = lazy(() => import('./components/DocumentIntelligenceHub'));

// Lazy-loaded modals
const OnboardCustomerModal = lazy(() => import('./components/Modals/OnboardCustomerModal'));
const SubmitRequirementModal = lazy(() => import('./components/Modals/SubmitRequirementModal'));
const NewLeaseModal = lazy(() => import('./components/Modals/NewLeaseModal'));
const NewWorkOrderModal = lazy(() => import('./components/Modals/NewWorkOrderModal'));
const NewVendorInvoiceModal = lazy(() => import('./components/Modals/NewVendorInvoiceModal'));
const PayBillModal = lazy(() => import('./components/Modals/PayBillModal'));
const SettingsModal = lazy(() => import('./components/Modals/SettingsModal'));
const InvestigationResultModal = lazy(() => import('./components/Modals/InvestigationResultModal'));
const BookTourModal = lazy(() => import('./components/Modals/BookTourModal'));
const RentalApplicationModal = lazy(() => import('./components/Modals/RentalApplicationModal'));

export default function App() {
  // Theme System (Default is Light)
  const [theme, setTheme] = useState(() => {
    try {
      const saved = localStorage.getItem('equilibra_theme') || localStorage.getItem('enigma_theme');
      return saved === 'dark' ? 'dark' : 'light';
    } catch {
      return 'light';
    }
  });

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.setAttribute('data-theme', next);
    try {
      localStorage.setItem('equilibra_theme', next);
      localStorage.setItem('enigma_theme', next);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Telemetry & Active Hub
  const [activeHub, setActiveHub] = useState('dashboard');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [telemetry, setTelemetry] = useState({
    totalChunks: 9300,
    worldEvents: 0,
    financeSource: 'Zetaris SQL',
    aiModel: 'NVIDIA Nemotron'
  });

  // SaaS Multi-Tenant State
  const [organizations, setOrganizations] = useState([]);
  const [currentOrgId, setCurrentOrgId] = useState('ORG-APEX');
  const [requirements, setRequirements] = useState([]);

  // Tenant AR Hub State
  const [summary, setSummary] = useState({});
  const [leases, setLeases] = useState([]);
  const [selectedLeaseId, setSelectedLeaseId] = useState('LEASE-0001');
  const [activeCaseData, setActiveCaseData] = useState(null);
  const [isInvestigating, setIsInvestigating] = useState(false);

  // Vendor AP Hub State
  const [vendorSummary, setVendorSummary] = useState({});
  const [vendorInvoices, setVendorInvoices] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState(null);
  const [walkthroughData, setWalkthroughData] = useState(null);
  const [isLoadingWalkthrough, setIsLoadingWalkthrough] = useState(false);

  // Modals Visibility
  const [isOnboardModalOpen, setIsOnboardModalOpen] = useState(false);
  const [isSubmitReqModalOpen, setIsSubmitReqModalOpen] = useState(false);
  const [isLeaseModalOpen, setIsLeaseModalOpen] = useState(false);
  const [isWorkOrderModalOpen, setIsWorkOrderModalOpen] = useState(false);
  const [isVendorInvoiceModalOpen, setIsVendorInvoiceModalOpen] = useState(false);
  const [isPayModalOpen, setIsPayModalOpen] = useState(false);
  const [payTargetInvoiceId, setPayTargetInvoiceId] = useState(null);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [isInvestigationModalOpen, setIsInvestigationModalOpen] = useState(false);
  const [investigationResult, setInvestigationResult] = useState(null);
  const [isTourModalOpen, setIsTourModalOpen] = useState(false);
  const [tourTargetProperty, setTourTargetProperty] = useState(null);
  const [isApplyModalOpen, setIsApplyModalOpen] = useState(false);
  const [applyTargetProperty, setApplyTargetProperty] = useState(null);
  const [systemConfig, setSystemConfig] = useState({
    finance_source: 'fixture',
    zetaris_key: '',
    ai_provider: 'offline',
    meterless_model: 'nvidia/nemotron-4-340b-instruct',
    meterless_token: ''
  });

  // Helper fetcher with deduplication and caching
  const api = async (url, opts = {}) => {
    const res = await cachedFetch(url, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
    return data;
  };

  // Load SaaS Organizations & Requirements
  const loadSaaSData = useCallback(async () => {
    try {
      const [orgs, reqs] = await Promise.all([
        api('/api/saas/organizations'),
        api('/api/saas/feature-requests')
      ]);
      setOrganizations(orgs);
      setRequirements(reqs);
      if (orgs.length > 0 && !currentOrgId) {
        setCurrentOrgId(orgs[0].id);
      }
    } catch (e) {
      console.error('Failed to load SaaS data', e);
    }
  }, [currentOrgId]);

  // Load Telemetry & Health
  const loadTelemetry = async () => {
    try {
      const h = await api('/health');
      setTelemetry({
        totalChunks: h.total_indexed_chunks || 9300,
        worldEvents: h.world_events_count || 0,
        financeSource: h.finance_source === 'zetaris' ? 'Zetaris SQL' : 'PostgreSQL Fixture',
        aiModel: h.ai_provider === 'meterless' ? 'NVIDIA Nemotron' : 'Deterministic Reasoner'
      });
    } catch (e) {
      console.error('Health check failed', e);
    }
  };

  // Load Tenant AR Data
  const loadTenantARData = useCallback(async (orgId = currentOrgId) => {
    try {
      const q = orgId && orgId !== 'all' ? `?org_id=${encodeURIComponent(orgId)}` : '';
      const [s, l] = await Promise.all([
        api(`/api/portfolio/summary${q}`),
        api(`/api/leases${q}`)
      ]);
      setSummary(s);
      setLeases(l);
      if (l.length > 0) {
        setSelectedLeaseId(l[0].lease_id);
        loadLeaseDetails(l[0].lease_id);
      }
    } catch (e) {
      console.error('Tenant summary load error', e);
    }
  }, [currentOrgId]);

  // Load Lease Details
  const loadLeaseDetails = async (leaseId) => {
    if (!leaseId) return;
    try {
      const data = await api(`/api/lease/${leaseId}/details`);
      const events = await api(`/api/world/${leaseId}`).catch(() => []);
      setActiveCaseData({ ...data, events });
    } catch (e) {
      console.error('Lease details fetch error', e);
    }
  };

  // Load Vendor AP Data
  const loadVendorAPData = useCallback(async (orgId = currentOrgId) => {
    try {
      const q = orgId && orgId !== 'all' ? `?org_id=${encodeURIComponent(orgId)}` : '';
      const [vs, vi, v] = await Promise.all([
        api(`/api/vendor-summary${q}`),
        api(`/api/vendor-invoices${q}`),
        api('/api/vendors')
      ]);
      setVendorSummary(vs);
      setVendorInvoices(vi);
      setVendors(v);

      if (vi.length > 0) {
        setSelectedInvoiceId(vi[0].id);
        reconcileInvoice(vi[0].id);
      }
    } catch (e) {
      console.error('Vendor AP load error', e);
    }
  }, [currentOrgId]);

  // Reconcile Invoice (4-Way Match)
  const reconcileInvoice = async (invoiceId) => {
    if (!invoiceId) return;
    setIsLoadingWalkthrough(true);
    try {
      const data = await api(`/api/vendor-invoices/${invoiceId}/reconcile`, { method: 'POST' });
      setWalkthroughData(data);
    } catch (e) {
      console.error('Reconciliation error', e);
    } finally {
      setIsLoadingWalkthrough(false);
    }
  };

  // Bootstrap Application
  useEffect(() => {
    loadTelemetry();
    loadSaaSData();
  }, []);

  // Reload data whenever current organization changes
  useEffect(() => {
    if (currentOrgId) {
      loadTenantARData(currentOrgId);
      loadVendorAPData(currentOrgId);
    }
  }, [currentOrgId, loadTenantARData, loadVendorAPData]);

  // Handle Hub Tab Switching (Dismiss modals across tabs)
  const handleSwitchHub = (hub) => {
    setIsInvestigationModalOpen(false);
    setActiveHub(hub);
  };

  // Handle Lease Selection
  const handleSelectLease = (leaseId) => {
    setIsInvestigationModalOpen(false);
    setSelectedLeaseId(leaseId);
    loadLeaseDetails(leaseId);
  };

  // Handle Vendor Invoice Selection
  const handleSelectInvoice = (invoiceId) => {
    setSelectedInvoiceId(invoiceId);
    reconcileInvoice(invoiceId);
  };

  // Investigate Active Case
  const handleInvestigateCase = async () => {
    if (!selectedLeaseId) return;
    setIsInvestigating(true);
    try {
      const res = await api('/api/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lease_id: selectedLeaseId,
          question: 'Analyze payment status and verify ledger accuracy.'
        })
      });
      // Refresh lease details, tenant list, & telemetry
      await loadLeaseDetails(selectedLeaseId);
      await loadTenantARData();
      await loadTelemetry();

      // Open professional investigation report modal
      setInvestigationResult(res);
      setIsInvestigationModalOpen(true);
    } catch (e) {
      alert('Investigation failed: ' + (e.message || String(e)));
    } finally {
      setIsInvestigating(false);
    }
  };

  // Submit Property Manager Decision
  const handleSubmitDecision = async (approved, action, note) => {
    try {
      const res = await api(`/api/approve/${selectedLeaseId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved, action, note, reviewer: 'Property Manager' })
      });
      await loadTenantARData();
      await loadLeaseDetails(selectedLeaseId);
      return res;
    } catch (e) {
      alert('Failed to record decision: ' + e.message);
      return null;
    }
  };

  // Refresh World Model
  const handleRefreshWorldModel = async () => {
    if (!selectedLeaseId) return;
    try {
      const events = await api(`/api/world/${selectedLeaseId}`);
      const latestState = await api(`/api/world/${selectedLeaseId}/state`);
      setActiveCaseData((prev) => ({
        ...prev,
        events,
        latest_state: latestState
      }));
    } catch (e) {
      console.error(e);
    }
  };

  // Resolve Vendor Bill
  const handleResolveVendorBill = async (invoiceId, action, note) => {
    try {
      const res = await api(`/api/approve/${invoiceId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approved: action === 'approved',
          action,
          note,
          reviewer: 'Property Manager'
        })
      });
      await loadVendorAPData();
      await reconcileInvoice(invoiceId);
      return res;
    } catch (e) {
      alert('Failed to resolve bill: ' + e.message);
      return null;
    }
  };

  // Pay Vendor Invoice
  const handlePayInvoice = async (payload) => {
    const res = await api(`/api/vendor-invoices/${payload.invoice_id}/pay`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    alert(res.message);
    await loadVendorAPData();
    await reconcileInvoice(payload.invoice_id);
  };

  // Ingest New Lease
  const handleIngestLease = async (leasePayload) => {
    const res = await api('/api/leases/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(leasePayload)
    });
    alert(`Lease ${res.lease_id} executed and indexed successfully.`);
    await loadTenantARData();
    handleSelectLease(res.lease_id);
  };

  // Ingest Work Order
  const handleIngestWorkOrder = async (woPayload) => {
    const res = await api('/api/workorders/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(woPayload)
    });
    alert(`Work order ${res.work_order_id} recorded and linked to ${res.lease_id}.`);
    await loadLeaseDetails(selectedLeaseId);
  };

  // Generate Vendor Invoice
  const handleGenerateVendorInvoice = async (invoicePayload) => {
    const res = await api('/api/vendor-invoices/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(invoicePayload)
    });
    alert(`Vendor PDF Invoice ${res.invoice_number} generated & vectorized with RAG.`);
    await loadVendorAPData();
    handleSelectInvoice(res.id);
  };

  // Onboard SaaS Customer
  const handleOnboardCustomer = async (orgPayload) => {
    const newOrg = await api('/api/saas/organizations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(orgPayload)
    });
    alert(`Customer Organization ${newOrg.name} (${newOrg.id}) onboarded to SaaS Cloud template.`);
    await loadSaaSData();
    setCurrentOrgId(newOrg.id);
  };

  // Submit SaaS Feature Requirement
  const handleSubmitRequirement = async (reqPayload) => {
    const newReq = await api('/api/saas/feature-requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqPayload)
    });
    alert(`Requirement ${newReq.id} recorded. Published to Co-Innovation Roadmap.`);
    await loadSaaSData();
    setActiveHub('saas');
  };

  // Upvote Requirement
  const handleUpvoteRequirement = async (reqId) => {
    try {
      const res = await api(`/api/saas/feature-requests/${reqId}/upvote`, { method: 'POST' });
      setRequirements((prev) =>
        prev.map((r) => (r.id === reqId ? { ...r, votes: res.new_vote_count } : r))
      );
    } catch (e) {
      console.error(e);
    }
  };

  // Seed Database
  const handleSeedDatabase = async () => {
    if (!confirm('Re-seed initial demo dataset?')) return;
    try {
      await api('/seed');
      alert('Database re-seeded successfully.');
      await loadTelemetry();
      await loadTenantARData();
      await loadLeaseDetails(selectedLeaseId);
      await loadVendorAPData();
    } catch (e) {
      alert('Seed failed: ' + e.message);
    }
  };

  // Save Settings Config
  const handleSaveConfig = async (cfg) => {
    setSystemConfig(cfg);
    alert('Cloud configuration updated.');
  };

  return (
    <div className="app-layout-root">
      <div className="app-shell">
        <Sidebar
        activeHub={activeHub}
        setActiveHub={handleSwitchHub}
        tenantCount={leases.length}
        vendorBillCount={vendorInvoices.length}
        reqCount={requirements.length}
        telemetry={telemetry}
        organizations={organizations}
        currentOrgId={currentOrgId}
        setCurrentOrgId={setCurrentOrgId}
        onOpenOnboardModal={() => setIsOnboardModalOpen(true)}
        sidebarOpen={sidebarOpen}
        setSidebarOpen={setSidebarOpen}
      />

      <div className="app-main-viewport">
        <Header
          activeHub={activeHub}
          theme={theme}
          toggleTheme={toggleTheme}
          onOpenLeaseModal={() => setIsLeaseModalOpen(true)}
          onOpenWorkOrderModal={() => setIsWorkOrderModalOpen(true)}
          onOpenVendorInvoiceModal={() => setIsVendorInvoiceModalOpen(true)}
          onOpenSettingsModal={() => setIsSettingsModalOpen(true)}
          onSeedDatabase={handleSeedDatabase}
          sidebarOpen={sidebarOpen}
          setSidebarOpen={setSidebarOpen}
        />

        <main className="app-content">
          {/* Dedicated Page Views wrapped in Suspense */}
          <Suspense fallback={<div className="page-loading-skeleton"><span className="indicator-dot pulse-dot" style={{ background: 'var(--primary)' }}></span><span>Loading operational workspace...</span></div>}>
            {activeHub === 'dashboard' && (
              <div className="page-view-container">
                <OperationalDashboardOverview currentOrgId={currentOrgId} />
              </div>
            )}

            {activeHub === 'tenant' && (
              <div className="page-view-container">
                <TenantARModule
                  summary={summary}
                  leases={leases}
                  selectedLease={leases.find((l) => l.lease_id === selectedLeaseId)}
                  activeCaseData={activeCaseData}
                  isInvestigating={isInvestigating}
                  onSelectLease={handleSelectLease}
                  onInvestigateCase={handleInvestigateCase}
                  onSubmitDecision={handleSubmitDecision}
                  onRefreshWorldModel={handleRefreshWorldModel}
                  onOpenInvestigationModal={() => setIsInvestigationModalOpen(true)}
                  hasInvestigationResult={Boolean(investigationResult)}
                />
              </div>
            )}

            {activeHub === 'vendor' && (
              <div className="page-view-container">
                <VendorAPModule
                  vendorSummary={vendorSummary}
                  vendorInvoices={vendorInvoices}
                  vendors={vendors}
                  selectedInvoiceId={selectedInvoiceId}
                  walkthroughData={walkthroughData}
                  isLoadingWalkthrough={isLoadingWalkthrough}
                  onSelectInvoice={handleSelectInvoice}
                  onOpenPayModal={(invId) => {
                    setPayTargetInvoiceId(invId);
                    setIsPayModalOpen(true);
                  }}
                  onResolveVendorBill={handleResolveVendorBill}
                />
              </div>
            )}

            {activeHub === 'resident' && (
              <div className="page-view-container">
                <ResidentPortal
                  onOpenPayModal={() => setIsPayModalOpen(true)}
                  currentOrgId={currentOrgId}
                />
              </div>
            )}

            {activeHub === 'public' && (
              <div className="page-view-container">
                <PublicListingsPortal
                  onOpenTourModal={(p) => {
                    setTourTargetProperty(p);
                    setIsTourModalOpen(true);
                  }}
                  onOpenApplyModal={(p) => {
                    setApplyTargetProperty(p);
                    setIsApplyModalOpen(true);
                  }}
                />
              </div>
            )}

            {activeHub === 'compliance' && (
              <div className="page-view-container">
                <ComplianceRiskHub currentOrgId={currentOrgId} />
              </div>
            )}

            {activeHub === 'docintel' && (
              <div className="page-view-container">
                <DocumentIntelligenceHub
                  currentOrgId={currentOrgId}
                  onSelectLease={(leaseId) => {
                    setActiveHub('tenant');
                    handleSelectLease(leaseId);
                  }}
                />
              </div>
            )}

            {activeHub === 'templates' && (
              <div className="page-view-container">
                <CommunicationTemplatesHub currentOrgId={currentOrgId} />
              </div>
            )}

            {activeHub === 'saas' && (
              <div className="page-view-container">
                <CustomerRequirementsPortal
                  requirements={requirements}
                  organizations={organizations}
                  onOpenSubmitRequirementModal={() => setIsSubmitReqModalOpen(true)}
                  onOpenOnboardModal={() => setIsOnboardModalOpen(true)}
                  onUpvoteRequirement={handleUpvoteRequirement}
                />
              </div>
            )}

            {activeHub === 'admin' && (
              <div className="page-view-container">
                <AdminDiagnosticsPortal />
              </div>
            )}
          </Suspense>
        </main>
      </div>
    </div>

      {/* Global SaaS Modals wrapped in Suspense */}
      <Suspense fallback={null}>
        {isOnboardModalOpen && (
          <OnboardCustomerModal
            isOpen={isOnboardModalOpen}
            onClose={() => setIsOnboardModalOpen(false)}
            onOnboardCustomer={handleOnboardCustomer}
          />
        )}

        {isSubmitReqModalOpen && (
          <SubmitRequirementModal
            isOpen={isSubmitReqModalOpen}
            onClose={() => setIsSubmitReqModalOpen(false)}
            organizations={organizations}
            currentOrgId={currentOrgId}
            onSubmitRequirement={handleSubmitRequirement}
          />
        )}

        {isLeaseModalOpen && (
          <NewLeaseModal
            isOpen={isLeaseModalOpen}
            onClose={() => setIsLeaseModalOpen(false)}
            onIngestLease={handleIngestLease}
          />
        )}

        {isWorkOrderModalOpen && (
          <NewWorkOrderModal
            isOpen={isWorkOrderModalOpen}
            onClose={() => setIsWorkOrderModalOpen(false)}
            currentLeaseId={selectedLeaseId}
            onIngestWorkOrder={handleIngestWorkOrder}
          />
        )}

        {isVendorInvoiceModalOpen && (
          <NewVendorInvoiceModal
            isOpen={isVendorInvoiceModalOpen}
            onClose={() => setIsVendorInvoiceModalOpen(false)}
            vendors={vendors}
            onGenerateVendorInvoice={handleGenerateVendorInvoice}
          />
        )}

        {isPayModalOpen && (
          <PayBillModal
            isOpen={isPayModalOpen}
            onClose={() => setIsPayModalOpen(false)}
            invoiceId={payTargetInvoiceId}
            walkthroughData={walkthroughData}
            onPayInvoice={handlePayInvoice}
          />
        )}

        {isSettingsModalOpen && (
          <SettingsModal
            isOpen={isSettingsModalOpen}
            onClose={() => setIsSettingsModalOpen(false)}
            config={systemConfig}
            onSaveConfig={handleSaveConfig}
          />
        )}

        {isInvestigationModalOpen && (
          <InvestigationResultModal
            isOpen={isInvestigationModalOpen}
            onClose={() => setIsInvestigationModalOpen(false)}
            investigationData={investigationResult}
            onApplyAction={(rec) => {
              handleSubmitDecision(true, 'approved', `Approved per agent recommendation: ${rec}`);
            }}
          />
        )}

        {isTourModalOpen && (
          <BookTourModal
            isOpen={isTourModalOpen}
            onClose={() => setIsTourModalOpen(false)}
            property={tourTargetProperty}
            onTourBooked={() => fetchPortfolioData()}
          />
        )}

        {isApplyModalOpen && (
          <RentalApplicationModal
            isOpen={isApplyModalOpen}
            onClose={() => setIsApplyModalOpen(false)}
            property={applyTargetProperty}
            onApplicationSubmitted={() => fetchPortfolioData()}
          />
        )}
      </Suspense>

      {/* Persistent EQUILIBRA AI Assistant in lower-right corner */}
      <EquilibraAssistant />
    </div>
  );
}
