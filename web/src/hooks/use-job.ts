import { useEffect, useState } from 'react';
import { getJob } from '../lib/api';
import { subscribe } from '../lib/ws';
import type { Job } from '../lib/types';

export function useJob(jobId: string | null) {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }

    // Seed initial state via REST (WS jobs:list may have already fired)
    getJob(jobId).then(setJob).catch(() => {});

    // Live updates via WS
    return subscribe((msg) => {
      if (msg.type === 'job:update' && msg.job.id === jobId) {
        setJob(msg.job);
      }
      if (msg.type === 'jobs:list') {
        const found = msg.jobs.find((j) => j.id === jobId);
        if (found) setJob(found);
      }
    });
  }, [jobId]);

  return job;
}
