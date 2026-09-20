const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(status, message, payload = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

async function parse(response) {
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) return response.json();
  if (type.startsWith('audio/') || type.startsWith('image/') || type.includes('application/pdf')) return response.blob();
  return response.text();
}

export async function request(path, { token, body, query, headers = {}, ...options } = {}) {
  const url = new URL(`${API_BASE}${path}`);
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, value);
  });
  const finalHeaders = { Accept: 'application/json', ...headers };
  let finalBody = body;
  if (token) finalHeaders.Authorization = `Bearer ${token}`;
  if (body !== undefined && !(body instanceof FormData) && !(body instanceof Blob)) {
    finalHeaders['Content-Type'] = 'application/json';
    finalBody = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, { ...options, headers: finalHeaders, body: finalBody });
  } catch (error) {
    throw new ApiError(0, 'We could not connect to AarogyaSaar. Please check that the care service is running.', error);
  }
  const payload = await parse(response);
  if (!response.ok) {
    let message = 'Something went wrong. Please try again.';
    if (payload && typeof payload === 'object') {
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (Array.isArray(payload.detail)) message = payload.detail.map((x) => x.msg || 'Please check this field.').join(' ');
      else if (typeof payload.message === 'string') message = payload.message;
    }
    throw new ApiError(response.status, message, payload);
  }
  return payload;
}

export const api = {
  health: () => request('/api/health'),
  securityStatus: (token) => request('/api/security/status', { token }),
  login: (body) => request('/api/auth/login', { method: 'POST', body }),
  register: (body) => request('/api/auth/register', { method: 'POST', body }),
  demoAccounts: () => request('/api/auth/demo-accounts'),
  logout: (token) => request('/api/auth/logout', { method: 'POST', token }),
  patient: (token, id) => request(`/api/patients/${id}`, { token }),
  departments: (token) => request('/api/departments', { token }),
  updatePatient: (token, id, body) => request(`/api/patients/${id}`, { method: 'PUT', token, body }),
  accessibilityCapabilities: (token) => request('/api/accessibility/capabilities', { token }),
  accessibility: (token, id) => request(`/api/patients/${id}/accessibility`, { token }),
  saveAccessibility: (token, id, body) => request(`/api/patients/${id}/accessibility`, { method: 'PUT', token, body }),
  createEncounter: (token, body) => request('/api/encounters', { method: 'POST', token, body }),
  encounter: (token, id) => request(`/api/encounters/${id}`, { token }),
  updateEncounterIntake: (token, id, body) => request(`/api/encounters/${id}/intake`, { method: 'PUT', token, body }),
  activeEncounter: (token, id) => request(`/api/patients/${id}/active-encounter`, { token }),
  consultations: (token, id) => request(`/api/patients/${id}/consultations`, { token }),
  clinicalSummary: (token, id) => request(`/api/patients/${id}/clinical-summary`, { token }),
  eligibleDoctors: (token, id) => request(`/api/encounters/${id}/eligible-doctors`, { token }),
  assignDoctor: (token, id, body) => request(`/api/encounters/${id}/assign-doctor`, { method: 'POST', token, body }),
  queue: (token, query) => request('/api/queue', { token, query }),
  updateEncounterStatus: (token, id, body) => request(`/api/encounters/${id}/status`, { method: 'POST', token, body }),
  consent: (token, id) => request(`/api/patients/${id}/consent`, { token }),
  saveConsent: (token, id, body) => request(`/api/patients/${id}/consent`, { method: 'POST', token, body }),
  revokeConsent: (token, id) => request(`/api/patients/${id}/consent/revoke`, { method: 'POST', token }),
  interviewQuestions: (token, patientId, language, sessionId) => request('/api/interview/questions', { token, query: { patient_id: patientId, language, session_id: sessionId } }),
  interviewState: (token, patientId, sessionId) => request(`/api/interview/state/${encodeURIComponent(sessionId)}`, { token, query: { patient_id: patientId } }),
  interviewAnswer: (token, body) => request('/api/interview/answer', { method: 'POST', token, body }),
  interviewBack: (token, body) => request('/api/interview/back', { method: 'POST', token, body }),
  interviewComplete: (token, body) => request('/api/interview/complete', { method: 'POST', token, body }),
  ayushQuestions: (token, language) => request('/api/ayush/questions', { token, query: { language } }),
  ayushAnswer: (token, body) => request('/api/ayush/answer', { method: 'POST', token, body }),
  ayushComplete: (token, body) => request('/api/ayush/complete', { method: 'POST', token, body }),
  ayushAssessments: (token, id) => request(`/api/patients/${id}/ayush`, { token }),
  documents: (token, id) => request(`/api/patients/${id}/documents`, { token }),
  documentContent: (token, id) => request(`/api/documents/${id}/content`, { token, headers: { Accept: 'application/pdf, image/*, text/plain' } }),
  uploadDocument: (token, formData) => request('/api/documents/upload', { method: 'POST', token, body: formData }),
  clinicalHandoff: (token, id) => request(`/api/patients/${id}/clinical-handoff`, { token }),
  doctorQueue: (token, department) => request('/api/queue', { token, query: { department, status: 'waiting,called,in_consultation' } }),
  doctorConsultations: (token) => request('/api/doctor/consultations', { token }),
  doctorWorkspace: (token, encounterId) => request(`/api/doctor/encounters/${encounterId}/workspace`, { token }),
  consultationRecord: (token, id) => request(`/api/doctor/consultations/${id}/record`, { token }),
  startConsultation: (token, encounterId, body) => request(`/api/doctor/encounters/${encounterId}/consultation`, { method: 'POST', token, body }),
  updateConsultation: (token, id, body) => request(`/api/doctor/consultations/${id}/record`, { method: 'PUT', token, body }),
  completeConsultation: (token, id, body) => request(`/api/doctor/consultations/${id}/complete`, { method: 'POST', token, body }),
  reviewConsultation: (token, id, body) => request(`/api/doctor/consultations/${id}/review`, { method: 'PUT', token, body }),
  aiSummary: (token, id) => request(`/api/doctor/consultations/${id}/ai-summary`, { token }),
  explainability: (token, id) => request(`/api/doctor/consultations/${id}/explainability`, { token }),
  clinicalGate: (token, id) => request(`/api/doctor/consultations/${id}/clinical-gate`, { token }),
  voiceStatus: (token) => request('/api/voice/status', { token }),
  speak: (token, text, language) => {
    const fd = new FormData(); fd.append('text', text); fd.append('language', language);
    return request('/api/voice/speak', { method: 'POST', token, body: fd, headers: { Accept: 'audio/mpeg' } });
  },
  transcribe: (token, fd) => request('/api/voice/transcribe', { method: 'POST', token, body: fd }),
  adminHospital: (token) => request('/api/admin/hospital', { token }),
  adminDoctors: (token) => request('/api/admin/doctors', { token }),
  adminPatients: (token) => request('/api/patients', { token }),
  adminPatient: (token, id) => request(`/api/patients/${id}`, { token }),
  adminCreateDoctor: (token, body) => request('/api/admin/doctors', { method: 'POST', token, body }),
  adminUpdateDoctor: (token, id, body) => request(`/api/admin/doctors/${id}`, { method: 'PUT', token, body }),
  adminDepartments: (token) => request('/api/admin/departments', { token }),
  adminAnalytics: (token) => request('/api/admin/analytics', { token }),
};

export { API_BASE };
