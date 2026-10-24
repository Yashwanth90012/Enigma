import React, { useState } from 'react';

export default function NewWorkOrderModal({ isOpen, onClose, currentLeaseId, onIngestWorkOrder }) {
  const [woId, setWoId] = useState('WO-0105');
  const [leaseId, setLeaseId] = useState(currentLeaseId || 'LEASE-0001');
  const [category, setCategory] = useState('Appliance');
  const [priority, setPriority] = useState('High');
  const [desc, setDesc] = useState('Dishwasher pump not draining completely; error code E24.');
  const [cost, setCost] = useState(225);
  const [tech, setTech] = useState('Jordan Wells');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onIngestWorkOrder({
        work_order_id: woId.trim(),
        lease_id: leaseId.trim(),
        category,
        priority,
        description: desc.trim(),
        estimated_cost_usd: parseFloat(cost) || 0,
        technician: tech.trim(),
        reported_date: new Date().toISOString().split('T')[0]
      });
      onClose();
    } catch (err) {
      alert('Failed to dispatch work order: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay active">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title">Dispatch Maintenance Work Order</div>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Work Order ID:
              <input
                type="text"
                required
                value={woId}
                onChange={(e) => setWoId(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Target Lease ID:
              <input
                type="text"
                required
                value={leaseId}
                onChange={(e) => setLeaseId(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Trade Category:
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="Plumbing">Plumbing (Sinks / Faucets / Drain)</option>
                <option value="Fixtures">Fixtures (Bathtubs / Enclosures)</option>
                <option value="Electrical">Electrical (LED Fixtures / Wiring)</option>
                <option value="HVAC">HVAC & Heating</option>
                <option value="Appliance">Kitchen Appliances</option>
                <option value="Hardware">Hardware & Structural</option>
              </select>
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Dispatch Priority:
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              >
                <option value="Emergency">Emergency (Active Leak / Hazard)</option>
                <option value="High">High Priority (Tenant Disrupted)</option>
                <option value="Standard">Standard Routine</option>
                <option value="Low">Low / Deferred</option>
              </select>
            </label>
          </div>

          <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Maintenance Issue Description:
            <input
              type="text"
              required
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
            />
          </label>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Authorized Estimate ($):
              <input
                type="number"
                required
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
            <label style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Assigned Field Technician:
              <input
                type="text"
                required
                value={tech}
                onChange={(e) => setTech(e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 6, marginTop: 4 }}
              />
            </label>
          </div>

          <button
            type="submit"
            className="btn btn-amber"
            disabled={isSubmitting}
            style={{ width: '100%', justifyContent: 'center', padding: 12, marginTop: 6 }}
          >
            {isSubmitting ? (
              <>
                <span className="spinner"></span>
                <span>Dispatching Work Order & Recording to World Model...</span>
              </>
            ) : (
              <span>Dispatch Work Order & Record to World Model</span>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
