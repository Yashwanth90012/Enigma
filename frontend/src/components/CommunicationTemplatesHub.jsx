import React, { useState, useEffect, useCallback } from 'react';

export default function CommunicationTemplatesHub({ currentOrgId = 'ORG-APEX' }) {
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState('editor'); // 'editor', 'history', 'logs'
  const [isLoading, setIsLoading] = useState(false);
  const [notification, setNotification] = useState(null);

  // Editor State
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editEnabled, setEditEnabled] = useState(true);
  const [changeSummary, setChangeSummary] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // Live Preview State
  const [previewData, setPreviewData] = useState(null);
  const [versionHistory, setVersionHistory] = useState([]);
  const [deliveryLogs, setDeliveryLogs] = useState([]);

  // Test Send Modal State
  const [isTestSendModalOpen, setIsTestSendModalOpen] = useState(false);
  const [testRecipient, setTestRecipient] = useState('puligillayashwanth776@gmail.com');
  const [isSendingTest, setIsSendingTest] = useState(false);
  const [testSendResult, setTestSendResult] = useState(null);

  // Variable Catalog
  const [catalog, setCatalog] = useState({});

  const showNotification = (msg, type = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 5000);
  };

  // 1. Load Templates List
  const loadTemplates = useCallback(async () => {
    setIsLoading(true);
    try {
      const url = `/api/templates?category=${selectedCategory}&search=${encodeURIComponent(searchQuery)}&org_id=${currentOrgId}`;
      const res = await fetch(url, { credentials: 'omit' });
      if (res.ok) {
        const data = await res.json();
        setTemplates(data);
        if (data.length > 0 && (!selectedTemplate || !data.some(t => t.id === selectedTemplate.id))) {
          loadTemplateDetail(data[0].id);
        }
      }
    } catch (e) {
      console.error("Error loading templates:", e);
      showNotification("Failed to fetch templates from backend: " + e.message, "error");
    } finally {
      setIsLoading(false);
    }
  }, [selectedCategory, searchQuery, currentOrgId]);

  // 2. Load Variable Catalog
  useEffect(() => {
    fetch('/api/templates/variables/catalog', { credentials: 'omit' })
      .then(res => res.json())
      .then(d => setCatalog(d.catalog || {}))
      .catch(e => console.error(e));
  }, []);

  // 3. Load Template Detail & Live Preview
  const loadTemplateDetail = async (templateId) => {
    try {
      const res = await fetch(`/api/templates/${templateId}?org_id=${currentOrgId}`, { credentials: 'omit' });
      if (res.ok) {
        const data = await res.json();
        const tmpl = data.template;
        setSelectedTemplate(tmpl);
        setEditSubject(tmpl.subject);
        setEditBody(tmpl.body);
        setEditEnabled(tmpl.enabled);
        setVersionHistory(data.version_history || []);

        // Load preview
        fetchPreview(tmpl.id, tmpl.subject, tmpl.body);

        // Load delivery logs
        loadDeliveryLogs(tmpl.template_key);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchPreview = async (templateId, subj = editSubject, body = editBody) => {
    try {
      const res = await fetch(`/api/templates/${templateId}/preview?org_id=${currentOrgId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context: {} }),
        credentials: 'omit'
      });
      if (res.ok) {
        const p = await res.json();
        setPreviewData(p);
      }
    } catch (e) {
      console.error("Preview error:", e);
    }
  };

  const loadDeliveryLogs = async (templateKey) => {
    try {
      const res = await fetch(`/api/notifications?limit=30`, { credentials: 'omit' });
      if (res.ok) {
        const allNotifs = await res.json();
        const filtered = allNotifs.filter(n => n.template_key === templateKey || (n.category && selectedTemplate && n.category === selectedTemplate.category));
        setDeliveryLogs(filtered);
      }
    } catch (e) {
      console.error("Logs error:", e);
    }
  };

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  // 4. Save Template Changes
  const handleSaveTemplate = async () => {
    if (!selectedTemplate) return;
    setIsSaving(true);
    try {
      const res = await fetch(`/api/templates/${selectedTemplate.id}?org_id=${currentOrgId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: editSubject,
          body: editBody,
          enabled: editEnabled,
          change_summary: changeSummary.trim() || 'Updated template content in manager console',
          modified_by: 'Property Manager'
        }),
        credentials: 'omit'
      });
      if (res.ok) {
        const data = await res.json();
        showNotification(`Template '${data.template.name}' saved successfully (Version ${data.template.version}).`);
        setChangeSummary('');
        loadTemplateDetail(data.template.id);
        loadTemplates();
      } else {
        const err = await res.json();
        showNotification(`Save failed: ${err.detail || 'Unknown error'}`, 'error');
      }
    } catch (e) {
      showNotification(`Save failed: ${e.message}`, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  // 5. Send Test Message (Strictly Safe)
  const handleSendTestMessage = async () => {
    if (!selectedTemplate || !testRecipient.includes('@')) {
      alert("Please provide a valid test recipient address.");
      return;
    }
    setIsSendingTest(true);
    try {
      const res = await fetch(`/api/templates/${selectedTemplate.id}/send-test?org_id=${currentOrgId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          test_recipient_email: testRecipient.trim()
        }),
        credentials: 'omit'
      });
      if (res.ok) {
        const result = await res.json();
        setTestSendResult(result);
        showNotification(`Test message dispatched to '${testRecipient}' (${result.status}).`);
        loadDeliveryLogs(selectedTemplate.template_key);
      } else {
        const err = await res.json();
        alert(`Test send failed: ${err.detail || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`Test send error: ${e.message}`);
    } finally {
      setIsSendingTest(false);
    }
  };

  // Insert Variable at cursor or append
  const insertVariable = (varName) => {
    const token = `{{${varName}}}`;
    setEditBody(prev => prev + ' ' + token);
  };

  const getCategoryBadgeClass = (cat) => {
    switch (cat) {
      case 'rent_collection': return 'cyan';
      case 'lease_resident': return 'emerald';
      case 'maintenance': return 'purple';
      case 'vendor_invoice': return 'blue';
      case 'compliance_risk': return 'amber';
      default: return '';
    }
  };

  const formatCategoryLabel = (cat) => {
    switch (cat) {
      case 'rent_collection': return 'Rent & Payments';
      case 'lease_resident': return 'Lease & Resident';
      case 'maintenance': return 'Maintenance & SLA';
      case 'vendor_invoice': return 'Vendor AP';
      case 'compliance_risk': return 'Compliance & Risk';
      default: return cat;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Toast Alert */}
      {notification && (
        <div style={{
          padding: '12px 18px',
          borderRadius: 8,
          backgroundColor: notification.type === 'error' ? 'rgba(225, 29, 72, 0.15)' : 'rgba(5, 150, 105, 0.15)',
          border: `1px solid ${notification.type === 'error' ? 'var(--rose)' : 'var(--emerald)'}`,
          color: notification.type === 'error' ? 'var(--rose)' : 'var(--emerald)',
          fontWeight: 600,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{notification.msg}</span>
          <button onClick={() => setNotification(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}>✕</button>
        </div>
      )}

      {/* Top Operations Header Banner */}
      <div className="card" style={{ padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 24 }}>📬</span>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-heading)' }}>
              Centralized Communication Template Library
            </h2>
            <span className="pill cyan">42 Predefined Templates</span>
            <span className="pill purple">Versioned & Audited</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>
            Predefined email & notice templates across Resident Lifecycle, Rent Collection, Maintenance SLAs, Vendor AP, and Statutory Compliance.
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Active Tenant Scope</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-heading)' }}>{currentOrgId}</div>
          </div>
          <button
            className="btn btn-primary"
            onClick={() => setIsTestSendModalOpen(true)}
            disabled={!selectedTemplate}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <span>✉️</span>
            <span>Send Test Preview</span>
          </button>
        </div>
      </div>

      {/* Filter Toolbar & Category Segmented Control */}
      <div className="card" style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 14 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {[
            { id: 'all', label: 'All Templates' },
            { id: 'rent_collection', label: 'Rent & Payments' },
            { id: 'lease_resident', label: 'Lease & Resident' },
            { id: 'maintenance', label: 'Maintenance' },
            { id: 'vendor_invoice', label: 'Vendor AP' },
            { id: 'compliance_risk', label: 'Compliance & Risk' }
          ].map(c => (
            <button
              key={c.id}
              className={`btn btn-sm ${selectedCategory === c.id ? 'btn-primary' : 'btn-default'}`}
              onClick={() => setSelectedCategory(c.id)}
              style={{ fontWeight: selectedCategory === c.id ? 700 : 500 }}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div style={{ minWidth: 260, position: 'relative' }}>
          <input
            type="text"
            className="input"
            placeholder="Search templates or triggers..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ width: '100%', paddingLeft: 32, fontSize: 13 }}
          />
          <span style={{ position: 'absolute', left: 10, top: 9, color: 'var(--text-dim)' }}>🔍</span>
        </div>
      </div>

      {/* Main 2-Column Template Console */}
      <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 20, alignItems: 'start' }}>
        
        {/* Left Column: Template List */}
        <div className="card" style={{ padding: 14, maxHeight: '820px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px', borderBottom: '1px solid var(--border-subtle)', marginBottom: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase' }}>
              Templates Catalog ({templates.length})
            </span>
            {isLoading && <span style={{ fontSize: 11, color: 'var(--primary)' }}>Refreshing...</span>}
          </div>

          {templates.length === 0 && !isLoading && (
            <div style={{ padding: 30, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
              No templates found matching your search.
            </div>
          )}

          {templates.map(t => {
            const isSelected = selectedTemplate?.id === t.id;
            return (
              <div
                key={t.id}
                onClick={() => loadTemplateDetail(t.id)}
                style={{
                  padding: '12px 14px',
                  borderRadius: 8,
                  backgroundColor: isSelected ? 'var(--bg-card-hover)' : 'var(--bg-inset)',
                  border: isSelected ? '1px solid var(--primary)' : '1px solid var(--border-subtle)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  boxShadow: isSelected ? '0 0 0 1px var(--primary-glow)' : 'none'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                  <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                    {t.id}
                  </span>
                  <span className={`pill ${getCategoryBadgeClass(t.category)}`} style={{ fontSize: 9, padding: '2px 6px' }}>
                    {formatCategoryLabel(t.category)}
                  </span>
                </div>

                <div style={{ fontSize: 14, fontWeight: isSelected ? 700 : 600, color: 'var(--text-heading)', marginBottom: 4 }}>
                  {t.name}
                </div>

                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.3, marginBottom: 8, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                  {t.description || t.trigger_event}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: 'var(--text-dim)' }}>
                  <span>v{t.version} {t.org_id !== 'system' ? `· (${t.org_id})` : '· System'}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', backgroundColor: t.enabled ? 'var(--emerald)' : 'var(--rose)' }}></span>
                    <span>{t.enabled ? 'Active' : 'Disabled'}</span>
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Right Column: Template Editor, Preview, and Audit Tabs */}
        {selectedTemplate ? (
          <div className="card" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 18 }}>
            
            {/* Template Header & Controls */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 16 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span className={`pill ${getCategoryBadgeClass(selectedTemplate.category)}`} style={{ fontSize: 11 }}>
                    {formatCategoryLabel(selectedTemplate.category)}
                  </span>
                  <span className="pill" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                    {selectedTemplate.template_key}
                  </span>
                  <span className="pill purple" style={{ fontSize: 11 }}>
                    v{selectedTemplate.version}
                  </span>
                </div>
                <h3 style={{ margin: '4px 0 0 0', fontSize: 19, fontWeight: 700, color: 'var(--text-heading)' }}>
                  {selectedTemplate.name}
                </h3>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer', fontWeight: 600 }}>
                  <input
                    type="checkbox"
                    checked={editEnabled}
                    onChange={(e) => setEditEnabled(e.target.checked)}
                  />
                  <span>Enabled in Workflows</span>
                </label>
              </div>
            </div>

            {/* Trigger Event Banner */}
            <div style={{
              padding: '12px 16px',
              backgroundColor: 'var(--briefing-box-bg)',
              border: '1px solid var(--briefing-box-border)',
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              gap: 10
            }}>
              <span style={{ fontSize: 18 }}>⚡</span>
              <div style={{ fontSize: 13, color: 'var(--text-main)' }}>
                <strong>Automated Trigger Event:</strong> {selectedTemplate.trigger_event}
              </div>
            </div>

            {/* Sub-Tabs Switcher */}
            <div style={{ display: 'flex', gap: 10, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 8 }}>
              <button
                className={`btn btn-sm ${activeTab === 'editor' ? 'btn-primary' : 'btn-default'}`}
                onClick={() => setActiveTab('editor')}
              >
                ✏️ Editor & Live Preview
              </button>
              <button
                className={`btn btn-sm ${activeTab === 'history' ? 'btn-primary' : 'btn-default'}`}
                onClick={() => setActiveTab('history')}
              >
                📜 Version History ({versionHistory.length})
              </button>
              <button
                className={`btn btn-sm ${activeTab === 'logs' ? 'btn-primary' : 'btn-default'}`}
                onClick={() => setActiveTab('logs')}
              >
                📊 Delivery Logs ({deliveryLogs.length})
              </button>
            </div>

            {/* TAB 1: Editor & Live Preview */}
            {activeTab === 'editor' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                
                {/* Variable Insertion Quick-Bar */}
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 6 }}>
                    Supported Variables (Click to insert into message):
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {(selectedTemplate.supported_variables || []).map(v => (
                      <button
                        key={v}
                        onClick={() => insertVariable(v)}
                        className="pill"
                        title={catalog[v]?.description || v}
                        style={{
                          cursor: 'pointer',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 11,
                          backgroundColor: 'var(--bg-card-hover)',
                          border: '1px solid var(--border-strong)',
                          padding: '3px 8px'
                        }}
                      >
                        + &#123;&#123;{v}&#125;&#125;
                      </button>
                    ))}
                  </div>
                </div>

                {/* Email Subject Input */}
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 700, color: 'var(--text-dim)', marginBottom: 6 }}>
                    EMAIL SUBJECT TEMPLATE:
                  </label>
                  <input
                    type="text"
                    className="input"
                    value={editSubject}
                    onChange={(e) => {
                      setEditSubject(e.target.value);
                      fetchPreview(selectedTemplate.id, e.target.value, editBody);
                    }}
                    style={{ width: '100%', fontSize: 14, fontFamily: 'var(--font-sans)', fontWeight: 600 }}
                  />
                </div>

                {/* Email Body Input */}
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 700, color: 'var(--text-dim)', marginBottom: 6 }}>
                    EMAIL BODY TEMPLATE:
                  </label>
                  <textarea
                    className="input"
                    rows={12}
                    value={editBody}
                    onChange={(e) => {
                      setEditBody(e.target.value);
                      fetchPreview(selectedTemplate.id, editSubject, e.target.value);
                    }}
                    style={{
                      width: '100%',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 13,
                      lineHeight: 1.5,
                      resize: 'vertical'
                    }}
                  />
                </div>

                {/* Change Summary & Save Bar */}
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', backgroundColor: 'var(--bg-inset)', padding: '12px 16px', borderRadius: 8 }}>
                  <input
                    type="text"
                    className="input"
                    placeholder="Audit reason for changes (e.g., Updated contact phone and late notice clause)..."
                    value={changeSummary}
                    onChange={(e) => setChangeSummary(e.target.value)}
                    style={{ flex: 1, fontSize: 13 }}
                  />
                  <button
                    className="btn btn-primary"
                    onClick={handleSaveTemplate}
                    disabled={isSaving}
                  >
                    {isSaving ? 'Saving...' : 'Save & Publish Version'}
                  </button>
                </div>

                {/* LIVE SAFE PREVIEW PANEL */}
                <div style={{ marginTop: 10, borderTop: '1px solid var(--border-subtle)', paddingTop: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 18 }}>👁️</span>
                      <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-heading)' }}>
                        Live Safe Preview (Rendered with representative portfolio data)
                      </h4>
                    </div>
                    {previewData && (
                      <span className={`pill ${previewData.is_valid ? 'emerald' : 'rose'}`} style={{ fontSize: 11 }}>
                        {previewData.is_valid ? '✓ Variables Validated' : '⚠️ Missing Required Variables'}
                      </span>
                    )}
                  </div>

                  {previewData && (
                    <div style={{
                      backgroundColor: 'var(--bg-card)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 8,
                      overflow: 'hidden',
                      boxShadow: 'var(--card-shadow)'
                    }}>
                      {/* Email Header Simulation */}
                      <div style={{ backgroundColor: 'var(--bg-inset)', padding: '12px 18px', borderBottom: '1px solid var(--border-subtle)', fontSize: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <div><strong>From:</strong> EQUILIBRA Property Operations &lt;puligillayashwanth776@gmail.com&gt;</div>
                        <div><strong>To:</strong> Yashwanth Puligilla &lt;puligillayashwanth776@gmail.com&gt;</div>
                        <div><strong>Subject:</strong> <span style={{ color: 'var(--primary)', fontWeight: 700 }}>{previewData.rendered_subject}</span></div>
                      </div>

                      {/* Email Body Simulation */}
                      <div style={{ padding: '20px 24px', fontSize: 13.5, lineHeight: 1.6, color: 'var(--text-main)', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-sans)' }}>
                        {previewData.rendered_body}
                      </div>

                      {/* Variable Resolution Map Table */}
                      <div style={{ padding: '14px 18px', backgroundColor: 'var(--bg-inset)', borderTop: '1px solid var(--border-subtle)' }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: 8 }}>
                          Resolved Variables Mapping:
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8, fontSize: 11 }}>
                          {Object.entries(previewData.resolved_variables || {}).map(([k, v]) => (
                            <div key={k} style={{ padding: '4px 8px', borderRadius: 4, backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
                              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>&#123;&#123;{k}&#125;&#125;: </span>
                              <strong style={{ color: 'var(--text-heading)' }}>{v.value}</strong>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

              </div>
            )}

            {/* TAB 2: Version History */}
            {activeTab === 'history' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--border-subtle)', textAlign: 'left', color: 'var(--text-dim)', fontSize: 11 }}>
                      <th style={{ padding: '8px 12px' }}>VERSION</th>
                      <th style={{ padding: '8px 12px' }}>MODIFIED BY</th>
                      <th style={{ padding: '8px 12px' }}>CHANGE SUMMARY</th>
                      <th style={{ padding: '8px 12px' }}>TIMESTAMP</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versionHistory.map(v => (
                      <tr key={v.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '10px 12px', fontWeight: 700 }}>
                          <span className="pill purple" style={{ fontSize: 11 }}>v{v.version}</span>
                        </td>
                        <td style={{ padding: '10px 12px', color: 'var(--text-main)', fontWeight: 600 }}>{v.modified_by}</td>
                        <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{v.change_summary || 'No change notes recorded'}</td>
                        <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 12 }}>{v.created_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* TAB 3: Delivery Logs */}
            {activeTab === 'logs' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {deliveryLogs.length === 0 ? (
                  <div style={{ padding: 30, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                    No recent notification delivery records found for this template category.
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: '2px solid var(--border-subtle)', textAlign: 'left', color: 'var(--text-dim)', fontSize: 11 }}>
                        <th style={{ padding: '8px 12px' }}>STATUS</th>
                        <th style={{ padding: '8px 12px' }}>RECIPIENT</th>
                        <th style={{ padding: '8px 12px' }}>RENDERED TITLE</th>
                        <th style={{ padding: '8px 12px' }}>EVENT KEY</th>
                        <th style={{ padding: '8px 12px' }}>DISPATCHED</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deliveryLogs.map(n => (
                        <tr key={n.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                          <td style={{ padding: '10px 12px' }}>
                            <span className={`pill ${n.status === 'sent' ? 'emerald' : (n.status === 'simulated' ? 'cyan' : 'rose')}`} style={{ fontSize: 10 }}>
                              {n.status.toUpperCase()}
                            </span>
                          </td>
                          <td style={{ padding: '10px 12px', fontWeight: 600, color: 'var(--text-main)' }}>{n.recipient_email}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{n.title}</td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>{n.event_key}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-dim)', fontSize: 11 }}>{n.created_at}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

          </div>
        ) : (
          <div className="card" style={{ padding: 50, textAlign: 'center', color: 'var(--text-muted)' }}>
            Select a template from the catalog on the left to inspect, edit, or test.
          </div>
        )}

      </div>

      {/* TEST SEND MODAL */}
      {isTestSendModalOpen && selectedTemplate && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.6)',
          backdropFilter: 'blur(3px)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 1000
        }}>
          <div className="card" style={{ width: 500, padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: 'var(--text-heading)' }}>
                Safe Test Send — {selectedTemplate.name}
              </h3>
              <button
                onClick={() => { setIsTestSendModalOpen(false); setTestSendResult(null); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-dim)' }}
              >✕</button>
            </div>

            <div style={{
              padding: '10px 14px',
              backgroundColor: 'rgba(8, 145, 178, 0.08)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 6,
              fontSize: 12,
              color: 'var(--text-main)',
              lineHeight: 1.4
            }}>
              🔒 <strong>Safe Delivery Policy:</strong> Test messages are dispatched strictly to your verified administrative testing address. They are marked simulated or sent via internal queue to avoid sending emails to actual residents or vendors.
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 700, color: 'var(--text-dim)', marginBottom: 6 }}>
                AUTHORIZED TEST RECIPIENT:
              </label>
              <input
                type="email"
                className="input"
                value={testRecipient}
                onChange={(e) => setTestRecipient(e.target.value)}
                style={{ width: '100%', fontSize: 14 }}
              />
            </div>

            {testSendResult && (
              <div style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(5, 150, 105, 0.1)',
                border: '1px solid var(--emerald)',
                borderRadius: 6,
                fontSize: 12,
                color: 'var(--emerald)'
              }}>
                ✓ Test message queued successfully with Notification ID: <strong>{testSendResult.id}</strong> (Status: {testSendResult.status}).
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
              <button
                className="btn btn-default"
                onClick={() => { setIsTestSendModalOpen(false); setTestSendResult(null); }}
              >
                Close
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSendTestMessage}
                disabled={isSendingTest}
              >
                {isSendingTest ? 'Dispatching...' : 'Confirm Test Send'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
