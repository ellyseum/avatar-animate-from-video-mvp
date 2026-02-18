export type JobStatus =
  | 'downloading'
  | 'preprocessing'
  | 'extracting'
  | 'converting'
  | 'animating'
  | 'rendering'
  | 'compositing'
  | 'complete'
  | 'failed';

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  progress: number;
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

export type PodStatus = 'stopped' | 'starting' | 'running' | 'error' | 'unknown';

export interface PodState {
  status: PodStatus;
  url: string | null;
  idleMinutes: number | null;
  gpu?: string | null;
  error?: string;
  startElapsedMs?: number | null;
  startStrategy?: string | null;
}
