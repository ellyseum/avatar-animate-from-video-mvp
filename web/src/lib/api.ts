import type { Job, PodState } from './types';

const BASE = '/api';

export async function submitJob(url: string): Promise<Job> {
  const res = await fetch(`${BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || 'Failed to submit job');
  }
  return res.json();
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`${BASE}/jobs/${id}`);
  if (!res.ok) throw new Error('Failed to fetch job');
  return res.json();
}

export async function listJobs(): Promise<Job[]> {
  const res = await fetch(`${BASE}/jobs`);
  if (!res.ok) throw new Error('Failed to list jobs');
  return res.json();
}

export async function uploadVideo(file: File): Promise<Job> {
  const form = new FormData();
  form.append('video', file);
  const res = await fetch(`${BASE}/jobs/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || 'Failed to upload video');
  }
  return res.json();
}

export async function deleteJob(id: string): Promise<void> {
  const res = await fetch(`${BASE}/jobs/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete job');
}

export function getResultUrl(id: string): string {
  return `${BASE}/jobs/${id}/result`;
}

export function getComparisonUrl(id: string): string {
  return `${BASE}/jobs/${id}/comparison`;
}

export type VideoType = 'original' | 'preprocessed' | 'frankmocap' | 'overlay' | 'comparison';

export function getVideoUrl(id: string, type: VideoType): string {
  return `${BASE}/jobs/${id}/video/${type}`;
}

// --- Pod management ---

export async function checkPodStatus(): Promise<PodState> {
  const res = await fetch(`${BASE}/pod/status`);
  if (!res.ok) return { status: 'error', url: null, idleMinutes: null, error: res.statusText };
  return res.json();
}

export async function startPod(): Promise<{ status: string; gpu?: string; error?: string }> {
  const res = await fetch(`${BASE}/pod/start`, { method: 'POST' });
  return res.json();
}

export async function stopPod(): Promise<{ status: string; error?: string }> {
  const res = await fetch(`${BASE}/pod/stop`, { method: 'POST' });
  return res.json();
}
