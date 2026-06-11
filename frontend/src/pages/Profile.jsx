import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ConfidenceBadge from '../components/ConfidenceBadge.jsx';
import DocumentSection from '../components/DocumentSection.jsx';
import RequestHistory from '../components/RequestHistory.jsx';
import { api } from '../api.js';

export default function Profile() {
  const { id } = useParams();
  const [candidate, setCandidate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('overview');
  const [sending, setSending] = useState(false);
  const [requestKey, setRequestKey] = useState(0);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getCandidate(id);
      setCandidate(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [id]);

  const triggerRequest = async () => {
    setSending(true);
    try {
      await api.requestDocuments(id);
      setRequestKey(k => k + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  };

  if (loading) return <div className="card"><div className="skeleton" /></div>;
  if (error) return <div className="error-banner">{error}</div>;
  if (!candidate) return <div className="empty">Candidate not found.</div>;

  const conf = candidate.field_confidence_json || {};
  const emailValid = !!candidate.email && /^[\w.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+$/.test(candidate.email);
  const blockedReason = !candidate.email
    ? 'No email on the resume — cannot send a request.'
    : !emailValid
      ? `Email "${candidate.email}" does not look valid — cannot send a request.`
      : null;

  return (
    <div>
      <div className="tabs">
        <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>Overview</button>
        <button className={tab === 'documents' ? 'active' : ''} onClick={() => setTab('documents')}>Documents</button>
      </div>

      {tab === 'overview' && (
        <>
          <div className="card">
            <h2 style={{ marginTop: 0 }}>{candidate.name || 'Unnamed candidate'}</h2>
            <Field label="Email" value={candidate.email} conf={conf.email} />
            <Field label="Phone" value={candidate.phone} conf={conf.phone} />
            <Field label="Company" value={candidate.company} conf={conf.company} />
            <Field label="Designation" value={candidate.designation} conf={conf.designation} />
            <Field label="Skills" value={(candidate.skills_json || []).join(', ')} conf={conf.skills} />
            <Field label="Route" value={candidate.extraction_route} />
            <div style={{ marginTop: 16 }}>
              <button className="btn" onClick={triggerRequest} disabled={sending || !!blockedReason}>
                {sending ? 'Sending…' : 'Request Documents'}
              </button>
              {blockedReason && (
                <div style={{ marginTop: 8, color: '#92400e', fontSize: 13 }}>{blockedReason}</div>
              )}
            </div>
          </div>
          <RequestHistory candidateId={id} reloadKey={requestKey} />
        </>
      )}

      {tab === 'documents' && <DocumentSection candidateId={id} />}
    </div>
  );
}

function Field({ label, value, conf }) {
  return (
    <div className="field-row">
      <div className="label">{label}</div>
      <div className="value">{value || '—'}</div>
      {conf && <ConfidenceBadge conf={conf} />}
    </div>
  );
}
