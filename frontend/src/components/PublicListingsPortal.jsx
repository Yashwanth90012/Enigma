import React, { useState, useEffect } from 'react';

export default function PublicListingsPortal({ onOpenTourModal, onOpenApplyModal }) {
  const [properties, setProperties] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedProp, setSelectedProp] = useState(null);
  const [selectedType, setSelectedType] = useState('all');

  const fetchProperties = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/properties');
      const data = await res.json();
      setProperties(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProperties();
  }, []);

  const filteredProps = properties.filter((p) => {
    if (selectedType !== 'all' && p.property_type !== selectedType) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const match =
        p.name.toLowerCase().includes(q) ||
        p.address.toLowerCase().includes(q) ||
        p.city.toLowerCase().includes(q) ||
        p.property_type.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });

  const propertyTypes = ['all', ...Array.from(new Set(properties.map((p) => p.property_type).filter(Boolean)))];

  const fmtMoney = (n) =>
    '$' + Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="public-portal-container" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Hero Banner */}
      <div className="card public-hero-card">
        <div className="public-hero-badge">
          <span className="indicator-dot pulse-dot"></span>
          <span>Verified Real Estate Portfolio · Synthetic Sandbox Data</span>
        </div>
        <h1 className="public-hero-title">EQUILIBRA Property Discovery & Resident Portal</h1>
        <p className="public-hero-subtitle">
          Explore autonomous, AI-verified residential and mixed-use rental homes. Real-time availability, instant digital tour scheduling, and automated pre-qualification.
        </p>

        {/* Search Bar */}
        <div className="public-search-bar">
          <input
            type="text"
            placeholder="Search by city, address, community name, or building type..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="type-filter-group">
            {propertyTypes.map((t) => (
              <button
                key={t}
                className={`btn btn-sm ${selectedType === t ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setSelectedType(t)}
              >
                {t === 'all' ? 'All Portfolios' : t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Property Grid */}
      {loading ? (
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <div className="typing-indicator" style={{ display: 'inline-flex' }}>
            <span></span>
            <span></span>
            <span></span>
          </div>
          <p style={{ marginTop: 12, color: 'var(--text-dim)' }}>Loading verified portfolio listings...</p>
        </div>
      ) : filteredProps.length === 0 ? (
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <p style={{ color: 'var(--text-dim)' }}>No properties matched your criteria.</p>
        </div>
      ) : (
        <div className="property-grid">
          {filteredProps.map((p) => (
            <div key={p.property_id} className="card property-card">
              <div className="property-image-wrapper">
                <img
                  src={
                    p.images && p.images[0]
                      ? p.images[0]
                      : 'https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=800&q=80'
                  }
                  alt={p.name}
                  className="property-card-img"
                  loading="lazy"
                />
                <div className="property-img-badges">
                  {p.is_published ? (
                    <span className="pill emerald">✓ Verified & Published ({p.verification_score}%)</span>
                  ) : (
                    <span className="pill amber">⏳ Review Pending ({p.verification_score}%)</span>
                  )}
                  <span className="pill">{p.property_type}</span>
                </div>
              </div>

              <div className="property-card-content">
                <div className="property-price-row">
                  <div className="property-rent-val">
                    {fmtMoney(p.monthly_rent_usd)}
                    <span className="property-rent-unit"> / month</span>
                  </div>
                  <div className="property-unit-count">{p.total_units} Units</div>
                </div>

                <h3 className="property-title">{p.name}</h3>
                <div className="property-address">
                  📍 {p.address}, {p.city}, {p.state} {p.zip_code}
                </div>

                {/* Amenities */}
                <div className="property-amenities-row">
                  {(p.amenities || []).slice(0, 4).map((a, i) => (
                    <span key={i} className="amenity-chip">
                      {a}
                    </span>
                  ))}
                  {(p.amenities || []).length > 4 && (
                    <span className="amenity-chip">+{p.amenities.length - 4} more</span>
                  )}
                </div>

                {/* Card Actions */}
                <div className="property-card-actions">
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setSelectedProp(p)}
                    style={{ flex: 1 }}
                  >
                    View Details
                  </button>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => onOpenTourModal(p)}
                    style={{ flex: 1 }}
                  >
                    📅 Book Tour
                  </button>
                  <button
                    className="btn btn-emerald btn-sm"
                    onClick={() => onOpenApplyModal(p)}
                    style={{ flex: 1 }}
                  >
                    📝 Apply
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Property Detail Modal */}
      {selectedProp && (
        <div className="modal-overlay" onClick={() => setSelectedProp(null)}>
          <div className="modal-card card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 650 }}>
            <div className="modal-header">
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 700 }}>{selectedProp.name}</h2>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {selectedProp.address}, {selectedProp.city}, {selectedProp.state} {selectedProp.zip_code}
                </div>
              </div>
              <button className="btn-icon btn-sm" onClick={() => setSelectedProp(null)}>
                ✕
              </button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <img
                src={selectedProp.images?.[0] || 'https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?auto=format&fit=crop&w=800&q=80'}
                alt={selectedProp.name}
                style={{ width: '100%', height: 220, objectFit: 'cover', borderRadius: 8 }}
              />

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                <div className="kpi-card" style={{ padding: 12 }}>
                  <div className="kpi-label">Monthly Rent</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--primary)' }}>
                    {fmtMoney(selectedProp.monthly_rent_usd)}
                  </div>
                </div>
                <div className="kpi-card" style={{ padding: 12 }}>
                  <div className="kpi-label">Deposit</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>
                    {fmtMoney(selectedProp.security_deposit_usd)}
                  </div>
                </div>
                <div className="kpi-card" style={{ padding: 12 }}>
                  <div className="kpi-label">Audit Score</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--emerald)' }}>
                    {selectedProp.verification_score}%
                  </div>
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Included Amenities</h4>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(selectedProp.amenities || []).map((a, i) => (
                    <span key={i} className="amenity-chip" style={{ fontSize: 11, padding: '4px 10px' }}>
                      ✓ {a}
                    </span>
                  ))}
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Verification Findings</h4>
                <div style={{ background: 'var(--surface-hover)', padding: 10, borderRadius: 6, fontSize: 12 }}>
                  <div>• Title deed verification: <strong>{selectedProp.verification_findings?.title_deed_verified ? 'Passed' : 'Pending review'}</strong></div>
                  <div>• Rent covenant consistency: <strong>{selectedProp.verification_findings?.rent_covenants_consistent ? 'Compliant' : 'Review'}</strong></div>
                  <div>• Physical & safety inspection: <strong>{selectedProp.verification_findings?.safety_inspection_current ? 'Current & Verified' : 'Scheduled'}</strong></div>
                </div>
              </div>
            </div>

            <div className="modal-footer" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                className="btn btn-primary"
                onClick={() => {
                  const p = selectedProp;
                  setSelectedProp(null);
                  onOpenTourModal(p);
                }}
              >
                📅 Book Tour
              </button>
              <button
                className="btn btn-emerald"
                onClick={() => {
                  const p = selectedProp;
                  setSelectedProp(null);
                  onOpenApplyModal(p);
                }}
              >
                📝 Submit Application
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
