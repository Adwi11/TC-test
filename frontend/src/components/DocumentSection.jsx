import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';

export default function DocumentSection({ candidateId }) {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState(null);
  const [staged, setStaged] = useState({ pan: null, aadhaar: null });

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api.listDocuments(candidateId);
      setDocs(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [candidateId]);

  const latest = (kind) => {
    const filtered = docs.filter(d => d.kind === kind);
    return filtered.length ? filtered[filtered.length - 1] : null;
  };

  const hasStaged = !!(staged.pan || staged.aadhaar);

  const stagePreviewUrl = useMemo(() => {
    const out = { pan: null, aadhaar: null };
    if (staged.pan) out.pan = URL.createObjectURL(staged.pan);
    if (staged.aadhaar) out.aadhaar = URL.createObjectURL(staged.aadhaar);
    return out;
  }, [staged]);

  useEffect(() => {
    return () => {
      if (stagePreviewUrl.pan) URL.revokeObjectURL(stagePreviewUrl.pan);
      if (stagePreviewUrl.aadhaar) URL.revokeObjectURL(stagePreviewUrl.aadhaar);
    };
  }, [stagePreviewUrl]);

  const onPick = (kind, file) => {
    setSavedMsg(null);
    setStaged(s => ({ ...s, [kind]: file || null }));
  };

  const onClear = (kind) => {
    setSavedMsg(null);
    setStaged(s => ({ ...s, [kind]: null }));
  };

  const onSave = async () => {
    if (!hasStaged) return;
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      await api.submitDocuments(candidateId, staged);
      setStaged({ pan: null, aadhaar: null });
      await load();
      setSavedMsg('Saved.');
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="card"><div className="skeleton" /></div>;

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}
      {savedMsg && <div className="success-banner">{savedMsg}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Slot
          kind="pan"
          label="PAN"
          saved={latest('pan')}
          stagedFile={staged.pan}
          stagedUrl={stagePreviewUrl.pan}
          candidateId={candidateId}
          disabled={saving}
          onPick={onPick}
          onClear={onClear}
        />
        <Slot
          kind="aadhaar"
          label="Aadhaar"
          saved={latest('aadhaar')}
          stagedFile={staged.aadhaar}
          stagedUrl={stagePreviewUrl.aadhaar}
          candidateId={candidateId}
          disabled={saving}
          onPick={onPick}
          onClear={onClear}
        />
      </div>
      <div style={{ marginTop: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className="btn" onClick={onSave} disabled={!hasStaged || saving}>
          {saving ? 'Saving…' : 'Save documents'}
        </button>
        {hasStaged && !saving && (
          <small style={{ color: '#64748b' }}>
            Staged:{staged.pan ? ' PAN' : ''}{staged.aadhaar ? ' Aadhaar' : ''}
          </small>
        )}
      </div>
    </div>
  );
}

function Slot({ kind, label, saved, stagedFile, stagedUrl, candidateId, disabled, onPick, onClear }) {
  const showStaged = !!stagedFile;
  const showSaved = !showStaged && !!saved;
  const stagedIsImage = stagedFile && stagedFile.type.startsWith('image/');
  return (
    <div className="doc-slot">
      <h4>{label}</h4>
      {showStaged ? (
        <>
          {stagedIsImage ? (
            <img className="doc-preview" src={stagedUrl} alt={`${label} staged preview`} />
          ) : (
            <iframe className="doc-preview" title={`${label} staged preview`} src={stagedUrl} />
          )}
          <small style={{ color: '#a16207' }}>Staged: {stagedFile.name} — click Save documents to commit</small>
        </>
      ) : showSaved ? (
        <>
          {saved.mime_type.startsWith('image/') ? (
            <img className="doc-preview" src={api.documentFileUrl(candidateId, saved.id)} alt={`${label} preview`} />
          ) : (
            <iframe className="doc-preview" title={`${label} preview`} src={api.documentFileUrl(candidateId, saved.id)} />
          )}
          <small style={{ color: '#64748b' }}>Uploaded {new Date(saved.uploaded_at).toLocaleString()}</small>
        </>
      ) : (
        <p style={{ color: '#64748b', margin: 0 }}>No {label} on file yet.</p>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <label className="btn secondary" style={{ cursor: disabled ? 'not-allowed' : 'pointer' }}>
          {showStaged ? `Pick different ${label}` : showSaved ? `Replace ${label}` : `Pick ${label}`}
          <input
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            style={{ display: 'none' }}
            disabled={disabled}
            onChange={(e) => onPick(kind, e.target.files?.[0] || null)}
          />
        </label>
        {showStaged && (
          <button className="btn secondary" onClick={() => onClear(kind)} disabled={disabled}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
