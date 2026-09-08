const BASE = '';  // proxied via vite

let _apiToken: string | null = null;

async function getApiToken(): Promise<string> {
  if (_apiToken) return _apiToken;
  const res = await fetch(`${BASE}/api/auth/token`);
  if (!res.ok) throw new Error('Failed to get API token');
  const data = await res.json();
  _apiToken = data.token;
  return _apiToken!;
}

async function apiFetch(url: string, options?: RequestInit) {
  const token = await getApiToken();
  const headers = new Headers(options?.headers);
  headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const body = await res.text();
    let detail = `HTTP ${res.status}`;
    try { detail = JSON.parse(body)?.detail ?? detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function fetchStats() { return apiFetch(`${BASE}/api/stats`); }
export async function fetchJobs(params?: Record<string, string>) {
  const q = params ? '?' + new URLSearchParams(params).toString() : '';
  return apiFetch(`${BASE}/api/jobs${q}`);
}
export async function fetchSources() { return apiFetch(`${BASE}/api/sources`); }
export async function fetchJob(id: string) { return apiFetch(`${BASE}/api/jobs/${id}`); }
export async function updateJobStatus(id: string, status: string) {
  return apiFetch(`${BASE}/api/jobs/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({status}) });
}
export async function updateJobResearchNotes(id: string, research_notes: string) {
  return apiFetch(`${BASE}/api/jobs/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({research_notes}) });
}
export async function updateJobDescription(id: string, jd_text: string) {
  return apiFetch(`${BASE}/api/jobs/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({jd_text}) });
}
export async function scoreJob(id: string) {
  return apiFetch(`${BASE}/api/jobs/${id}/score`, { method: 'POST' });
}
export async function dismissJob(id: string) {
  return apiFetch(`${BASE}/api/jobs/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({dismissed: true}) });
}
export async function restoreJob(id: string) {
  return apiFetch(`${BASE}/api/jobs/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({dismissed: false}) });
}
export async function bulkDismissExpired(only_status?: string) {
  const body: any = { only_expired: true };
  if (only_status) body.only_status = only_status;
  return apiFetch(`${BASE}/api/jobs/bulk-dismiss`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
}
export async function fetchDuplicates(mode: 'strict' | 'by_role' = 'strict') {
  return apiFetch(`${BASE}/api/jobs/duplicates?mode=${mode}`);
}
export async function dedupeJobs(mode: 'strict' | 'by_role' = 'strict') {
  return apiFetch(`${BASE}/api/jobs/dedupe`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ mode, dry_run: false }) });
}
export async function fetchLocationPresets() { return apiFetch(`${BASE}/api/preferences/location-presets`); }
export async function dismissByLocation(patterns: string[], dry_run = false) {
  return apiFetch(`${BASE}/api/jobs/dismiss-by-location`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ patterns, dry_run }) });
}
export async function fetchApplications() { return apiFetch(`${BASE}/api/applications`); }
export async function fetchPreferences() { return apiFetch(`${BASE}/api/preferences`); }
export async function savePreferences(prefs: any) {
  return apiFetch(`${BASE}/api/preferences`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(prefs) });
}
export async function fetchMasterResume() { return apiFetch(`${BASE}/api/resume/master`); }
export async function tailorResume(jobId: string) {
  return apiFetch(`${BASE}/api/resume/tailor/${jobId}`, { method: 'POST' });
}
export async function fetchTailoredResume(jobId: string) { return apiFetch(`${BASE}/api/resume/${jobId}/tailored`); }
export async function fetchSchedulerStatus() { return apiFetch(`${BASE}/api/scheduler/status`); }
export async function fetchSchedulerJobs() { return apiFetch(`${BASE}/api/scheduler/jobs`); }
export async function fetchSchedulerLog(lines = 100) { return apiFetch(`${BASE}/api/scheduler/log?lines=${lines}`); }
export async function startScheduler() { return apiFetch(`${BASE}/api/scheduler/start`, { method: 'POST' }); }
export async function stopScheduler() { return apiFetch(`${BASE}/api/scheduler/stop`, { method: 'POST' }); }
export async function runSchedulerJob(jobId: string) {
  return apiFetch(`${BASE}/api/scheduler/run`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ job_id: jobId }) });
}
export async function fetchSettings() { return apiFetch(`${BASE}/api/settings`); }
export async function saveSettings(settings: any) { return apiFetch(`${BASE}/api/settings`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(settings) }); }
export async function validateApiKey(key: string, provider: string = 'anthropic') { return apiFetch(`${BASE}/api/settings/validate-key`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ key, provider }) }); }
export async function fetchSetupStatus() { return apiFetch(`${BASE}/api/setup/status`); }
export async function uploadResume(file: File) { const form = new FormData(); form.append('file', file); return apiFetch(`${BASE}/api/resume/upload`, { method: 'POST', body: form }); }
export async function saveMasterResume(data: any) { return apiFetch(`${BASE}/api/resume/master`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) }); }
export async function fetchGapAnalysis() { return apiFetch(`${BASE}/api/resume/gap-analysis`); }
export async function fetchJobGap(jobId: string) { return apiFetch(`${BASE}/api/resume/gap-analysis/${jobId}`); }
export async function enhanceResume() { return apiFetch(`${BASE}/api/resume/enhance`, { method: 'POST' }); }
export async function applySuggestions(data: any) { return apiFetch(`${BASE}/api/resume/apply-suggestions`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) }); }
