import { Power, Square, Loader2, Wifi, WifiOff } from 'lucide-react';
import type { PodState } from '../lib/types';

interface PodControlProps {
  pod: PodState;
  onStart: () => void;
  onStop: () => void;
  starting: boolean;
}

const AUTO_SHUTDOWN_MIN = 15;

interface StartupPhase {
  label: string;
  progress: number;
}

function getStartupPhase(elapsedMs: number | null | undefined, strategy: string | null | undefined): StartupPhase {
  if (elapsedMs == null) return { label: 'Connecting...', progress: 5 };

  const elapsed = elapsedMs / 1000;

  if (strategy === 'resume') {
    if (elapsed < 5) return { label: 'Resuming machine...', progress: 20 };
    if (elapsed < 20) return { label: 'Booting container...', progress: 40 + (elapsed / 20) * 30 };
    if (elapsed < 45) return { label: 'Starting services...', progress: 70 + ((elapsed - 20) / 25) * 20 };
    return { label: 'Almost ready...', progress: 92 };
  }

  // Cold create
  if (elapsed < 10) return { label: 'Finding GPU...', progress: 5 };
  if (elapsed < 30) return { label: 'Machine assigned...', progress: 10 };
  if (elapsed < 240) {
    const pullProgress = 15 + ((elapsed - 30) / 210) * 60; // 15% → 75% over ~3.5 min
    return { label: 'Pulling image (28 GB)...', progress: Math.min(pullProgress, 75) };
  }
  if (elapsed < 300) return { label: 'Starting services...', progress: 80 + ((elapsed - 240) / 60) * 12 };
  return { label: 'Almost ready...', progress: 92 };
}

export function PodControl({ pod, onStart, onStop, starting }: PodControlProps) {
  const isRunning = pod.status === 'running';
  const isStarting = pod.status === 'starting' || starting;
  const canStart = !isRunning && !isStarting;

  const remaining = pod.idleMinutes != null
    ? Math.max(0, AUTO_SHUTDOWN_MIN - pod.idleMinutes)
    : null;

  const startup = isStarting
    ? getStartupPhase(pod.startElapsedMs, pod.startStrategy)
    : null;

  return (
    <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Status icon + label */}
        <div className="flex items-center gap-2">
          {isRunning ? (
            <Wifi size={16} className="text-green-400" />
          ) : isStarting ? (
            <Loader2 size={16} className="animate-spin text-yellow-400" />
          ) : (
            <WifiOff size={16} className="text-[var(--color-text-muted)]" />
          )}
          <span className="text-sm font-medium">
            {pod.gpu || 'GPU Server'}
          </span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${
            isRunning ? 'bg-green-500/20 text-green-400' :
            isStarting ? 'bg-yellow-500/20 text-yellow-400' :
            'bg-[var(--color-surface-2)] text-[var(--color-text-muted)]'
          }`}>
            {isRunning ? 'Online' : isStarting ? (startup?.label || 'Starting...') : 'Offline'}
          </span>
        </div>

        {/* Auto-shutdown countdown */}
        {isRunning && remaining != null && (
          <span className="text-xs text-[var(--color-text-muted)]">
            Auto-stop in {remaining}m
          </span>
        )}

        {/* Elapsed time while starting */}
        {isStarting && pod.startElapsedMs != null && (
          <span className="text-xs text-[var(--color-text-muted)]">
            {Math.floor(pod.startElapsedMs / 1000)}s
          </span>
        )}

        {/* Action button */}
        <div className="ml-auto">
          {canStart && (
            <button
              onClick={onStart}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded
                         bg-green-600 hover:bg-green-500 text-white transition-colors"
            >
              <Power size={12} />
              Start
            </button>
          )}
          {isStarting && (
            <button
              disabled
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded
                         bg-yellow-600/50 text-yellow-200 cursor-not-allowed"
            >
              <Loader2 size={12} className="animate-spin" />
              Starting...
            </button>
          )}
          {isRunning && (
            <button
              onClick={onStop}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded
                         bg-red-600/80 hover:bg-red-500 text-white transition-colors"
            >
              <Square size={12} />
              Stop
            </button>
          )}
        </div>
      </div>

      {/* Startup progress bar */}
      {isStarting && startup && (
        <div className="px-4 pb-2">
          <div className="w-full h-1.5 bg-[var(--color-surface-2)] rounded-full overflow-hidden">
            <div
              className="h-full bg-yellow-500 rounded-full transition-all duration-1000 ease-out"
              style={{ width: `${startup.progress}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
