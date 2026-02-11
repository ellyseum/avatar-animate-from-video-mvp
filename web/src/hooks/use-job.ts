import { useEffect, useRef, useState } from 'react';
import { getJob } from '../lib/api';
import type { Job } from '../lib/types';

export function useJob(jobId: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }

    let cancelled = false;

    async function poll() {
      try {
        const data = await getJob(jobId!);
        if (!cancelled) setJob(data);

        // Stop polling when terminal
        if (data.status === 'complete' || data.status === 'failed') {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch {
        // Keep polling on transient errors
      }
    }

    poll();
    intervalRef.current = setInterval(poll, 2000);

    return () => {
      cancelled = true;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [jobId]);

  return job;
}
