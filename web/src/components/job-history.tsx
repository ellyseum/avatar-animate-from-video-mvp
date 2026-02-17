import { useEffect, useRef, useState } from 'react';
import { Clock, Check, AlertCircle, Loader2, Trash2, Copy } from 'lucide-react';
import { deleteJob } from '../lib/api';
import { subscribe } from '../lib/ws';
import type { Job, JobStatus } from '../lib/types';

function CopyButton({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function handleCopy(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      const current = await navigator.clipboard.readText();
      if (current === text) return; // already in clipboard
    } catch {
      // readText may fail (permissions), proceed with write
    }
    await navigator.clipboard.writeText(text);
    setShow(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setShow(false), 1200);
  }

  return (
    <span className="relative shrink-0">
      <button
        onClick={handleCopy}
        className="p-0.5 rounded text-[var(--color-text-muted)] hover:text-[var(--color-primary)] transition-colors cursor-pointer"
        title="Copy URL"
      >
        <Copy size={12} />
      </button>
      {show && (
        <span className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] text-green-400 bg-[var(--color-surface)] border border-[var(--color-border)] rounded px-1.5 py-0.5 whitespace-nowrap animate-fade-out pointer-events-none">
          Copied
        </span>
      )}
    </span>
  );
}

function StatusBadge({ status }: { status: JobStatus }) {
  const map: Record<JobStatus, { icon: React.ReactNode; color: string; label: string }> = {
    downloading: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-blue-400', label: 'Downloading' },
    preprocessing: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-indigo-400', label: 'Preprocessing' },
    extracting: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-yellow-400', label: 'Extracting' },
    converting: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-orange-400', label: 'Converting' },
    animating: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-purple-400', label: 'Animating' },
    rendering: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-cyan-400', label: 'Rendering' },
    compositing: { icon: <Loader2 size={12} className="animate-spin" />, color: 'text-teal-400', label: 'Compositing' },
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

function ConfirmDialog({ message, onConfirm, onCancel }: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div
        className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg p-6 max-w-sm mx-4 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <p className="text-sm text-[var(--color-text)] mb-4">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded border border-[var(--color-border)] text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded bg-red-600 text-white hover:bg-red-700 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export function JobHistory({ onSelect }: { onSelect: (job: Job) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<Job | null>(null);

  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'jobs:list') {
        setJobs(msg.jobs);
      }
      if (msg.type === 'job:update') {
        setJobs((prev) => {
          const idx = prev.findIndex((j) => j.id === msg.job.id);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = msg.job;
            return next;
          }
          // New job — prepend
          return [msg.job, ...prev];
        });
      }
      if (msg.type === 'job:delete') {
        setJobs((prev) => prev.filter((j) => j.id !== msg.id));
      }
    });
  }, []);

  const handleDelete = async (job: Job) => {
    setConfirmDelete(null);
    try {
      await deleteJob(job.id);
      // Server will broadcast job:delete via WS
    } catch {
      // WS will reconcile state
    }
  };

  if (jobs.length === 0) return null;

  return (
    <div className="w-full max-w-2xl mx-auto mt-8">
      <h2 className="text-sm font-medium text-[var(--color-text-muted)] mb-3 flex items-center gap-2">
        <Clock size={14} /> Recent Jobs
      </h2>
      <div className="bg-[var(--color-surface)] rounded-lg border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
        {jobs.slice(0, 10).map(job => (
          <div
            key={job.id}
            className="flex items-center hover:bg-[var(--color-surface-2)] transition-colors cursor-pointer"
          >
            <button
              onClick={() => onSelect(job)}
              className="flex-1 px-4 py-3 flex items-center justify-between text-left min-w-0 cursor-pointer"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  {job.url.startsWith('http') ? (
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-sm text-[var(--color-text)] hover:text-[var(--color-primary)] hover:underline truncate"
                    >
                      {job.url}
                    </a>
                  ) : (
                    <span className="text-sm text-[var(--color-text)] truncate">{job.url}</span>
                  )}
                  {job.url.startsWith('http') && <CopyButton text={job.url} />}
                </div>
                <span className="text-xs text-[var(--color-text-muted)]">
                  {new Date(job.createdAt).toLocaleString()}
                </span>
              </div>
              <StatusBadge status={job.status} />
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(job); }}
              className="p-2 mr-2 rounded text-[var(--color-text-muted)] hover:text-red-400 hover:bg-red-400/10 transition-colors"
              title="Delete job"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {confirmDelete && (
        <ConfirmDialog
          message={`Delete job for ${confirmDelete.url}? This will remove all data including mocap results.`}
          onConfirm={() => handleDelete(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}
