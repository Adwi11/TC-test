import { useEffect, useState } from 'react';
import { api } from '../api.js';

export default function RequestHistory({ candidateId, reloadKey }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api.listRequests(candidateId);
        if (!cancelled) setRows(r);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [candidateId, reloadKey]);

  if (loading) return <div className="card"><div className="skeleton" /></div>;
  if (error) return <div className="error-banner">{error}</div>;
  if (!rows.length) return <div className="card empty">No document requests yet.</div>;

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Request history</h3>
      {rows.map(r => (
        <div key={r.id} className="history-row">
          <div>
            <div style={{ fontWeight: 600 }}>{r.subject || '—'}</div>
            <div style={{ color: '#64748b', fontSize: 12 }}>
              {r.recipient || 'no recipient'} · {new Date(r.sent_at).toLocaleString()}
            </div>
          </div>
          <span className={`status-pill ${r.status}`}>{r.status}</span>
        </div>
      ))}
    </div>
  );
}
