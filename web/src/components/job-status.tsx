import { Check, Loader2, AlertCircle } from 'lucide-react';
import type { Job, JobStatus } from '../lib/types';

const STEPS: { key: JobStatus; label: string }[] = [
  { key: 'downloading', label: 'Downloading video' },
  { key: 'extracting', label: 'Extracting mocap (this takes a bit)' },
  { key: 'encoding', label: 'Encoding video' },
  { key: 'complete', label: 'Done' },
];

const ORDER: Record<JobStatus, number> = {
  downloading: 0,
  extracting: 1,
  encoding: 2,
  complete: 3,
  failed: -1,
};

function StepIcon({ step, current }: { step: JobStatus; current: JobStatus }) {
  if (current === 'failed') {
    return <AlertCircle size={16} className="text-red-400" />;
  }
  const stepOrder = ORDER[step];
  const currentOrder = ORDER[current];

  if (stepOrder < currentOrder) {
    return <Check size={16} className="text-green-400" />;
  }
  if (stepOrder === currentOrder) {
    return <Loader2 size={16} className="animate-spin text-[var(--color-primary)]" />;
  }
  return <div className="w-4 h-4 rounded-full border border-[var(--color-border)]" />;
}

export function JobStatusDisplay({ job }: { job: Job }) {
  return (
    <div className="w-full max-w-2xl mx-auto mt-8">
      <div className="bg-[var(--color-surface)] rounded-lg border border-[var(--color-border)] p-6">
        {/* Progress bar */}
        <div className="w-full h-2 bg-[var(--color-surface-2)] rounded-full overflow-hidden mb-6">
          <div
            className="h-full bg-[var(--color-primary)] rounded-full transition-all duration-500"
            style={{ width: `${job.progress}%` }}
          />
        </div>

        {/* Steps */}
        <div className="space-y-3">
          {STEPS.map(({ key, label }) => (
            <div key={key} className="flex items-center gap-3">
              <StepIcon step={key} current={job.status} />
              <span className={
                ORDER[key] <= ORDER[job.status] && job.status !== 'failed'
                  ? 'text-[var(--color-text)]'
                  : 'text-[var(--color-text-muted)]'
              }>
                {label}
              </span>
            </div>
          ))}
        </div>

        {job.status === 'failed' && job.error && (
          <div className="mt-4 p-3 rounded bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
            {job.error}
          </div>
        )}
      </div>
    </div>
  );
}
