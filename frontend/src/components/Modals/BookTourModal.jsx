import React, { useState } from 'react';

export default function BookTourModal({ isOpen, onClose, property, onTourBooked }) {
  const [residentName, setResidentName] = useState('');
  const [residentEmail, setResidentEmail] = useState('');
  const [residentPhone, setResidentPhone] = useState('');
  const [bookingDate, setBookingDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 2);
    return d.toISOString().split('T')[0];
  });
  const [bookingTime, setBookingTime] = useState('11:00 AM');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen || !property) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      const res = await fetch('/api/tours', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          property_id: property.property_id,
          unit: 'Main',
          resident_name: residentName,
          resident_email: residentEmail,
          resident_phone: residentPhone,
          booking_date: bookingDate,
          booking_time: bookingTime,
          notes: notes
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.message || 'Failed to book tour');
      if (onTourBooked) onTourBooked(data);
      onClose();
      alert(`Tour successfully confirmed for ${bookingDate} at ${bookingTime}!`);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>Schedule Property Tour</h2>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              {property.name} · {property.address}, {property.city}
            </div>
          </div>
          <button className="btn-icon btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        {error && (
          <div style={{ padding: 10, background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--rose)', borderRadius: 6, color: 'var(--rose)', fontSize: 13, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Full Name</label>
            <input
              type="text"
              required
              className="input-field"
              placeholder="e.g. Jordan Reed"
              value={residentName}
              onChange={(e) => setResidentName(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Email Address</label>
              <input
                type="email"
                required
                className="input-field"
                placeholder="jordan@example.com"
                value={residentEmail}
                onChange={(e) => setResidentEmail(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Phone Number</label>
              <input
                type="tel"
                className="input-field"
                placeholder="(555) 019-2834"
                value={residentPhone}
                onChange={(e) => setResidentPhone(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Tour Date</label>
              <input
                type="date"
                required
                className="input-field"
                value={bookingDate}
                onChange={(e) => setBookingDate(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Time Slot</label>
              <select
                className="input-field"
                value={bookingTime}
                onChange={(e) => setBookingTime(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
              >
                <option value="09:00 AM">09:00 AM</option>
                <option value="11:00 AM">11:00 AM</option>
                <option value="01:30 PM">01:30 PM</option>
                <option value="03:00 PM">03:00 PM</option>
                <option value="05:00 PM">05:00 PM</option>
              </select>
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Notes / Accessibility Preferences</label>
            <textarea
              rows={2}
              className="input-field"
              placeholder="Any specific questions or move-in timelines..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)' }}
            />
          </div>

          <div className="modal-footer" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 10 }}>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={isSubmitting}>
              {isSubmitting ? 'Confirming...' : 'Confirm Tour Booking'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
