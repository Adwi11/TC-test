import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import UploadDropzone from '../components/UploadDropzone.jsx';
import { api } from '../api.js';

export default function Dashboard() {
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listCandidates();
      setCandidates(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div>
      <UploadDropzone onUploaded={(c) => navigate(`/candidates/${c.id}`)} />
      {error && <div className="error-banner">{error}</div>}
      {loading ? (
        <div className="card"><div className="skeleton" style={{ width: '40%' }} /></div>
      ) : candidates.length === 0 ? (
        <div className="empty">No candidates yet — drop a resume above.</div>
      ) : (
        <table className="table">
          <thead><tr><th>Name</th><th>Email</th><th>Company</th><th>Route</th></tr></thead>
          <tbody>
            {candidates.map(c => (
              <tr key={c.id} onClick={() => navigate(`/candidates/${c.id}`)}>
                <td>{c.name || '—'}</td>
                <td>{c.email || '—'}</td>
                <td>{c.company || '—'}</td>
                <td>{c.extraction_route || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
