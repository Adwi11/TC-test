const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch {}
    const err = new Error(body?.error || `HTTP ${res.status}`);
    err.code = body?.code;
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  listCandidates: () => request('/candidates'),
  getCandidate: (id) => request(`/candidates/${id}`),
  uploadResume: (file) => {
    const fd = new FormData();
    fd.append('file', file);
    return request('/candidates/upload', { method: 'POST', body: fd });
  },
  requestDocuments: (id) => request(`/candidates/${id}/request-documents`, { method: 'POST' }),
  listRequests: (id) => request(`/candidates/${id}/requests`),
  listDocuments: (id) => request(`/candidates/${id}/documents`),
  documentFileUrl: (id, docId) => `${BASE}/candidates/${id}/documents/${docId}/file`,
  submitDocuments: (id, { pan, aadhaar }) => {
    const fd = new FormData();
    if (pan) fd.append('pan', pan);
    if (aadhaar) fd.append('aadhaar', aadhaar);
    return request(`/candidates/${id}/submit-documents`, { method: 'POST', body: fd });
  },
};
