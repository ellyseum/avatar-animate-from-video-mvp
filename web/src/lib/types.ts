export type JobStatus =
  | 'downloading'
  | 'extracting'
  | 'encoding'
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
