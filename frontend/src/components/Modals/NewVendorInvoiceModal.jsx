import React, { useState, useEffect } from 'react';

const ORG_PRESETS = {
  'ORG-APEX': {
    propertyId: 'PROP-001',
    unit: 'Unit 103',
    defaultWo: 'WO-0003',
    workOrders: [
      { id: 'WO-0003', label: 'WO-0003: Plumbing Sinks/Supply Pipe ($314) · PROP-001' },
      { id: 'WO-0001', label: 'WO-0001: Kitchen Faucet Continuous Drip ($189) · PROP-001' },
      { id: 'WO-0004', label: 'WO-0004: HVAC Thermostat & Capacitor ($303) · PROP-001' },
      { id: 'WO-DIRECT', label: 'No Prior WO (Direct Property Order)' }
    ]
  },
  'ORG-VERDANT': {
    propertyId: 'PROP-002',
    unit: 'Unit 122',
    defaultWo: 'WO-0022',
    workOrders: [
      { id: 'WO-0022', label: 'WO-0022: Bathroom Basin & P-Trap ($209) · PROP-002' },
      { id: 'WO-0025', label: 'WO-0025: Solar Heating Service ($299) · PROP-002' },
      { id: 'WO-0028', label: 'WO-0028: Luxury Appliance Service ($283) · PROP-002' },
      { id: 'WO-DIRECT', label: 'No Prior WO (Direct Property Order)' }
    ]
  },
  'ORG-BEACON': {
    propertyId: 'PROP-003',
    unit: 'Suite 141',
    defaultWo: 'WO-0041',
    workOrders: [
      { id: 'WO-0041', label: 'WO-0041: Commercial HVAC Filter & Coil ($350) · PROP-003' },
      { id: 'WO-0045', label: 'WO-0045: Security Access System ($420) · PROP-003' },
      { id: 'WO-DIRECT', label: 'No Prior WO (Direct Property Order)' }
    ]
  },
  'ORG-SKYLINE': {
    propertyId: 'PROP-004',
    unit: 'Loft 161',
    defaultWo: 'WO-0061',
    workOrders: [
      { id: 'WO-0061', label: 'WO-0061: Loft Kitchen Disposal & Lighting ($215) · PROP-004' },
      { id: 'WO-0065', label: 'WO-0065: High-Ceiling Window Seal ($290) · PROP-004' },
      { id: 'WO-DIRECT', label: 'No Prior WO (Direct Property Order)' }
    ]
  }
};

export default function NewVendorInvoiceModal({
  isOpen,
  onClose,
  vendors,
  currentOrgId = 'ORG-APEX',
  onGenerateVendorInvoice
}) {
  const activePreset = ORG_PRESETS[currentOrgId] || ORG_PRESETS['ORG-APEX'];
  const [vendorId, setVendorId] = useState('VEND-001');
  const [workOrderId, setWorkOrderId] = useState(activePreset.defaultWo);
  const [propertyId, setPropertyId] = useState(activePreset.propertyId);
  const [unit, setUnit] = useState(activePreset.unit);
  const [taxRate, setTaxRate] = useState(0.0825);
  const [notes, setNotes] = useState('Maintenance completed under authorized work order.');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const preset = ORG_PRESETS[currentOrgId] || ORG_PRESETS['ORG-APEX'];
    setPropertyId(preset.propertyId);
    setUnit(preset.unit);
    setWorkOrderId(preset.defaultWo);
  }, [currentOrgId, isOpen]);

  const [lineItems, setLineItems] = useState([
    { description: 'Stainless Pull-Out Kitchen Sink Faucet Assembly', quantity: 1, unit_price_usd: 135.00 },
    { description: 'Licensed Plumber Labor', quantity: 2, unit_price_usd: 80.00 }
  ]);

  if (!isOpen) return null;

  const addPresetItem = (desc, qty, price) => {
    setLineItems([...lineItems, { description: desc, quantity: qty, unit_price_usd: price }]);
  };

  const removeLineItem = (index) => {
    if (lineItems.length > 1) {
      setLineItems(lineItems.filter((_, i) => i !== index));
    }
  };

  const updateLineItem = (index, field, val) => {
    const updated = [...lineItems];
    updated[index][field] = val;
    setLineItems(updated);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onGenerateVendorInvoice({
        vendor_id: vendorId,
        work_order_id: workOrderId.trim() || undefined,
        property_id: propertyId.trim(),
        unit: unit.trim(),
        line_items: lineItems.map((li) => ({
          description: li.description.trim(),
          quantity: parseFloat(li.quantity) || 1,
          unit_price_usd: parseFloat(li.unit_price_usd) || 0
        })),
        tax_rate: parseFloat(taxRate) || 0,
        notes: notes.trim()
      });
      onClose();
    } catch (err) {
      alert('Failed to generate vendor invoice: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card" style={{ maxWidth: 650 }}>
        <div className="modal-header">
          <div className="modal-title">Generate Vendor PDF Bill & Process via RAG</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Simulate a vendor submitting a bill (sinks, bathtubs, lights, appliances). Generates a real ReportLab PDF, extracts text via PyPDF, indexes vector embeddings into PostgreSQL, and runs 4-way matching.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Contracted Supplier / Trade:
              <select
                value={vendorId}
                onChange={(e) => setVendorId(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                {vendors.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} ({v.trade.split(',')[0]})
                  </option>
                ))}
              </select>
            </label>

            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Link to Authorized Work Order:
              <select
                value={workOrderId}
                onChange={(e) => setWorkOrderId(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                {(activePreset.workOrders || []).map((wo) => (
                  <option key={wo.id} value={wo.id}>
                    {wo.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Property Portfolio:
              <select
                value={propertyId}
                onChange={(e) => {
                  const newProp = e.target.value;
                  setPropertyId(newProp);
                  // Auto-suggest unit and work order for selected property
                  if (newProp === 'PROP-001') { setUnit('Unit 103'); setWorkOrderId('WO-0003'); }
                  else if (newProp === 'PROP-002') { setUnit('Unit 122'); setWorkOrderId('WO-0022'); }
                  else if (newProp === 'PROP-003') { setUnit('Suite 141'); setWorkOrderId('WO-0041'); }
                  else if (newProp === 'PROP-004') { setUnit('Loft 161'); setWorkOrderId('WO-0061'); }
                }}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="PROP-001">PROP-001: Skyline Terrace (Apex)</option>
                <option value="PROP-002">PROP-002: Verdant Valley (Verdant)</option>
                <option value="PROP-003">PROP-003: Beacon Bay Plaza (Beacon)</option>
                <option value="PROP-004">PROP-004: Oakridge Lofts (Skyline)</option>
              </select>
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Unit Reference:
              <input
                type="text"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          {/* Preset Buttons for Quick Line Items */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 4 }}>
              Add Standard Catalog Items (Click to Append):
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="preset-chip"
                onClick={() => addPresetItem('Stainless Undermount Sink & Faucet', 1, 329.00)}
              >
                + Sink & Faucet ($329)
              </button>
              <button
                type="button"
                className="preset-chip"
                onClick={() => addPresetItem('Cast Iron Bathtub & Drain Assembly', 1, 580.00)}
              >
                + Bathtub & Drain ($580)
              </button>
              <button
                type="button"
                className="preset-chip"
                onClick={() => addPresetItem('6-Pack Recessed LED Can Fixtures', 1, 145.00)}
              >
                + LED Lights ($145)
              </button>
              <button
                type="button"
                className="preset-chip"
                onClick={() => addPresetItem('Digital Thermostat & HVAC Relay', 1, 210.00)}
              >
                + HVAC Thermostat ($210)
              </button>
              <button
                type="button"
                className="preset-chip"
                onClick={() => addPresetItem('Licensed Technician Labor Hours', 2, 80.00)}
              >
                + Labor 2hrs ($160)
              </button>
            </div>
          </div>

          {/* Line Items List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 180, overflowY: 'auto' }}>
            {lineItems.map((item, idx) => (
              <div key={idx} style={{ flexShrink: 0, display: 'grid', gridTemplateColumns: '2fr 80px 100px 30px', gap: 6, alignItems: 'center' }}>
                <input
                  type="text"
                  value={item.description}
                  onChange={(e) => updateLineItem(idx, 'description', e.target.value)}
                  style={{ padding: '6px 8px', borderRadius: 4, fontSize: 12 }}
                />
                <input
                  type="number"
                  step="0.5"
                  value={item.quantity}
                  onChange={(e) => updateLineItem(idx, 'quantity', e.target.value)}
                  style={{ padding: '6px 8px', borderRadius: 4, fontSize: 12 }}
                />
                <input
                  type="number"
                  step="0.01"
                  value={item.unit_price_usd}
                  onChange={(e) => updateLineItem(idx, 'unit_price_usd', e.target.value)}
                  style={{ padding: '6px 8px', borderRadius: 4, fontSize: 12 }}
                />
                <button
                  type="button"
                  onClick={() => removeLineItem(idx)}
                  style={{ background: 'transparent', border: 'none', color: 'var(--rose)', cursor: 'pointer', fontSize: 16 }}
                >
                  &times;
                </button>
              </div>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Sales Tax Rate:
              <input
                type="number"
                step="0.0001"
                value={taxRate}
                onChange={(e) => setTaxRate(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Invoice Notes:
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          <button
            type="submit"
            className="btn btn-purple"
            disabled={isSubmitting}
            style={{ width: '100%', justifyContent: 'center', padding: 12, marginTop: 6 }}
          >
            {isSubmitting ? (
              <>
                <span className="spinner"></span>
                <span>Generating Authentic PDF & Indexing RAG Embeddings...</span>
              </>
            ) : (
              <span>Generate PDF Bill, Vectorize & Reconcile</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
