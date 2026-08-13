import type { Job, MeshRun, MeshRunPreset } from '../types';

const API_BASE = '/api/v1';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function createJob(settings: { fps: number; mode: string; conf_threshold: number }) {
  return request<{ id: string }>('/jobs', {
    method: 'POST',
    body: JSON.stringify(settings),
  });
}

export async function uploadVideo(
  file: File,
  settings: { fps: number; mode: string; conf_threshold: number },
  onProgress?: (pct: number, loaded: number, total: number) => void
): Promise<{ id: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}/jobs/upload`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100), e.loaded, e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        try { reject(new Error(JSON.parse(xhr.responseText).detail)); } catch { reject(new Error('上传失败')); }
      }
    };
    xhr.onerror = () => reject(new Error('网络错误，请检查连接'));
    const form = new FormData();
    form.append('file', file);
    form.append('settings', JSON.stringify(settings));
    xhr.send(form);
  });
}

export function listJobs() {
  return request<Job[]>('/jobs');
}

export function getJob(id: string) {
  return request<Job>(`/jobs/${id}`);
}

export function deleteJob(id: string) {
  return request<void>(`/jobs/${id}`, { method: 'DELETE' });
}

export function getResultUrl(jobId: string) {
  return `/files/${jobId}/result.glb`;
}

export function getMeshUrl(jobId: string) {
  return `/files/${jobId}/result_mesh.glb`;
}

export function listMeshRuns(jobId: string) {
  return request<MeshRun[]>(`/jobs/${jobId}/mesh-runs`);
}

export function createMeshRun(jobId: string, preset: MeshRunPreset, config: Record<string, unknown> = {}) {
  return request<MeshRun>(`/jobs/${jobId}/mesh-runs`, {
    method: 'POST',
    body: JSON.stringify({ preset, config }),
  });
}

export function cancelMeshRun(jobId: string, runId: string) {
  return request<MeshRun>(`/jobs/${jobId}/mesh-runs/${runId}/cancel`, { method: 'POST' });
}

export function deleteMeshRun(jobId: string, runId: string) {
  return request<void>(`/jobs/${jobId}/mesh-runs/${runId}`, { method: 'DELETE' });
}

export function selectActiveMeshRun(jobId: string, runId: string | null) {
  return request<{ active_mesh_run_id: string | null; mesh_url: string | null }>(`/jobs/${jobId}/active-mesh`, {
    method: 'PATCH',
    body: JSON.stringify({ run_id: runId }),
  });
}
