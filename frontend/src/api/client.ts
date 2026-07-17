import type {
  AnalysisResult,
  JobCreateResponse,
  JobStatusResponse
} from "../types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || `请求失败（${response.status}）`);
  }
  return response.json();
}

export function createUploadJob(file: File): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("file", file);
  return requestJson("/api/jobs/upload", { method: "POST", body: form });
}

export function createUrlJob(audioUrl: string): Promise<JobCreateResponse> {
  return requestJson("/api/jobs/url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_url: audioUrl })
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return requestJson(`/api/jobs/${jobId}`);
}

export function getJobResult(jobId: string): Promise<AnalysisResult> {
  return requestJson(`/api/jobs/${jobId}/result`);
}

export function retrySummary(jobId: string): Promise<JobStatusResponse> {
  return requestJson(`/api/jobs/${jobId}/retry-summary`, { method: "POST" });
}

export function jobAudioUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/audio`;
}
