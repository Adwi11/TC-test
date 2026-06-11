import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { api } from '../api.js';

export default function UploadDropzone({ onUploaded }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const onDrop = useCallback(async (files) => {
    const f = files[0];
    if (!f) return;
    setBusy(true);
    setError(null);
    try {
      const c = await api.uploadResume(f);
      onUploaded && onUploaded(c);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [onUploaded]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'] },
    multiple: false,
    disabled: busy,
  });

  return (
    <div>
      <div {...getRootProps()} className={`dropzone ${isDragActive ? 'active' : ''}`}>
        <input {...getInputProps()} />
        <p>{busy ? 'Processing…' : isDragActive ? 'Drop the resume here' : 'Drag a resume here, or click to choose (PDF or DOCX)'}</p>
      </div>
      {error && <div className="error-banner" style={{ marginTop: 12 }}>{error}</div>}
    </div>
  );
}
