import React, { useState, useRef, useEffect } from 'react';

export default function EquilibraAssistant() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      sender: 'assistant',
      text: 'Hello! I am your EQUILIBRA Autonomous Property Management Assistant. You can ask me about lease reconciliations, open maintenance tickets, published property listings, tour bookings, or AP vendor bills.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
    }
  }, [messages, isOpen]);

  const handleSend = async (textToSend) => {
    const query = textToSend || input;
    if (!query.trim() || isLoading) return;

    const userMsg = {
      sender: 'user',
      text: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await fetch('/api/assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: query })
      });
      const data = await res.json();

      const assistantMsg = {
        sender: 'assistant',
        text: data.response || 'I have analyzed the backend records.',
        toolCalls: data.tool_calls || [],
        documentReferences: data.document_references || [],
        communicationDraft: data.communication_draft || null,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          sender: 'assistant',
          text: `Error connecting to assistant: ${err.message}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="equilibra-assistant-container">
      {/* Floating Toggle Button */}
      {!isOpen && (
        <button
          className="assistant-floating-btn"
          onClick={() => setIsOpen(true)}
          title="Open EQUILIBRA AI Assistant"
          aria-label="Open AI Assistant"
        >
          <div className="assistant-btn-icon-wrapper">
            <svg viewBox="0 0 24 24" className="assistant-sparkle-icon">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
            <span className="assistant-pulse-ring"></span>
          </div>
          <span className="assistant-btn-label">EQUILIBRA AI</span>
        </button>
      )}

      {/* Floating Drawer / Chat Window */}
      {isOpen && (
        <div className="assistant-window card">
          {/* Header */}
          <div className="assistant-header">
            <div className="assistant-title-group">
              <div className="assistant-avatar">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, stroke: '#fff', fill: 'none', strokeWidth: 2 }}>
                  <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                </svg>
              </div>
              <div>
                <div className="assistant-name">EQUILIBRA Copilot</div>
                <div className="assistant-status">
                  <span className="indicator-dot pulse-dot" style={{ width: 6, height: 6 }}></span>
                  <span>Autonomous Property Engine Online</span>
                </div>
              </div>
            </div>
            <button
              className="btn-icon btn-sm"
              onClick={() => setIsOpen(false)}
              title="Close Assistant"
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          {/* Quick Prompts */}
          <div className="assistant-quick-prompts">
            <button onClick={() => handleSend('Check status of LEASE-0001')}>
              📊 LEASE-0001
            </button>
            <button onClick={() => handleSend('Run 4-agent collaborative lease cross-validation on LEASE-0001')}>
              ⚡ Cross-Validate Lease
            </button>
            <button onClick={() => handleSend('Draft rent reminder for LEASE-0001')}>
              ✉️ Draft Rent Notice
            </button>
            <button onClick={() => handleSend('Find supporting documents for LEASE-0001')}>
              📄 Supporting Docs
            </button>
            <button onClick={() => handleSend('Are there any open emergency maintenance tickets?')}>
              🚨 Active Emergencies
            </button>
          </div>

          {/* Messages Body */}
          <div className="assistant-messages-body">
            {messages.map((m, i) => (
              <div key={i} className={`assistant-bubble ${m.sender === 'user' ? 'user-bubble' : 'bot-bubble'}`}>
                {m.sender === 'assistant' && (
                  <div className="bubble-author">EQUILIBRA AI · {m.timestamp}</div>
                )}
                <div className="bubble-text" style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>

                {/* Supporting Document References */}
                {m.documentReferences && m.documentReferences.length > 0 && (
                  <div style={{ marginTop: 8, padding: 8, background: 'var(--surface-hover)', borderRadius: 6 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--primary)', marginBottom: 4 }}>
                      📄 VERIFIED SUPPORTING DOCUMENTS ({m.documentReferences.length})
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {m.documentReferences.map((doc, dIdx) => (
                        <div key={dIdx} style={{ fontSize: 11, display: 'flex', justifyContent: 'space-between' }}>
                          <span><strong>{doc.document_id || doc.title}</strong>: {doc.title}</span>
                          <span className="pill cyan" style={{ fontSize: 9 }}>{doc.doc_type || 'evidence'}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Templated Communication Draft Preview */}
                {m.communicationDraft && (
                  <div style={{ marginTop: 8, padding: 10, background: 'rgba(8, 145, 178, 0.08)', border: '1px solid var(--primary)', borderRadius: 6 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--primary)', marginBottom: 4 }}>
                      ✉️ TEMPLATED COMMUNICATION DRAFT [{m.communicationDraft.template_id || m.communicationDraft.template_key}]
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-heading)' }}>
                      Subject: {m.communicationDraft.rendered_subject}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
                      Recipient: <code>{m.communicationDraft.recipient}</code> · Safe Preview
                    </div>
                    <div style={{
                      marginTop: 6,
                      padding: 6,
                      background: 'var(--surface)',
                      borderRadius: 4,
                      fontSize: 11,
                      maxHeight: 120,
                      overflowY: 'auto',
                      whiteSpace: 'pre-wrap',
                      fontFamily: 'var(--font-mono)'
                    }}>
                      {m.communicationDraft.rendered_body}
                    </div>
                  </div>
                )}

                {m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="tool-chips" style={{ marginTop: 6 }}>
                    {m.toolCalls.map((tc, idx) => (
                      <span key={idx} className="tool-chip">
                        ⚙ {tc.tool} {tc.param ? `(${tc.param})` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="assistant-bubble bot-bubble">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Footer */}
          <form
            className="assistant-input-bar"
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
          >
            <input
              type="text"
              placeholder="Ask about leases, repairs, listings, or reconciliation..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isLoading}
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={isLoading || !input.trim()}>
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
