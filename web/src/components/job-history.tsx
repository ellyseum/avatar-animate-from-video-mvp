import { useEffect, useState } from 'react';
import { Clock, Check, AlertCircle, Loader2 } from 'lucide-react';
import { listJobs } from '../lib/api';
import type { Job, JobStatus } from '../lib/types';

function StatusBadge({ status }: { status: JobStatus }) {
  const map: Record<JobStatus, { icon: React.ReactNode; color: string; label: string }> = {
    downloading: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-blue-400', label: 'Downloading' },
    extracting: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-yellow-400', label: 'Extracting' },
    converting: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-orange-400', label: 'Converting' },
    animating: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-purple-400', label: 'Animating' },
    complete: { icon: <Check size={12} />, color: 'text-green-400', label: 'Complete' },
    failed: { icon: <AlertCircle size={12} />, color: 'text-red-400', label: 'Failed' },
  };
  const { icon, color, label } = map[status] || map.failed;

  return (
    <span className={`flex items-center gap-1 text-xs ${color}`}>
      {icon} {label}
    </span>
  );
}

export function JobHistory({ onSelect }: { onSelect: (job: Job) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    listJobs().then(setJobs).catch(() => {});
    const interval = setInterval(() => {
      listJobs().then(setJobs).catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  if (jobs.length === 0) return null;

  return (
    <div className="w-full max-w-2xl mx-auto mt-8">
      <h2 className="text-sm font-medium text-[var(--color-text-muted)] mb-3 flex items-center gap-2">
        <Clock size={14} /> Recent Jobs
      </h2>
      <div className="bg-[var(--color-surface)] rounded-lg border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
        {jobs.slice(0, 10).map(job => (
          <button
            key={job.id}
            onClick={() => onSelect(job)}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-[var(--color-surface-2)] transition-colors text-left"
          >
            <div className="min-w-0 flex-1">
              <span className="text-sm text-[var(--color-text)] truncate block">{job.url}</span>
              <span className="text-xs text-[var(--color-text-muted)]">
                {new Date(job.createdAt).toLocaleString()}
              </span>
            </div>
            <StatusBadge status={job.status} />
          </button>
        ))}
      </div>
    </div>
  );
}
