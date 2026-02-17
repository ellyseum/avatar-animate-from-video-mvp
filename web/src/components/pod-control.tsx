import { Power, Square, Loader2, Wifi, WifiOff } from 'lucide-react';
import type { PodState } from '../lib/types';

interface PodControlProps {
  pod: PodState;
  onStart: () => void;
  onStop: () => void;
  starting: boolean;
}

const AUTO_SHUTDOWN_MIN = 15;

export function PodControl({ pod, onStart, onStop, starting }: PodControlProps) {
  const isRunning = pod.status === 'running';
  const isStarting = pod.status === 'starting' || starting;
  const canStart = !isRunning && !isStarting;

  const remaining = pod.idleMinutes != null
    ? Math.max(0, AUTO_SHUTDOWN_MIN - pod.idleMinutes)
    : null;

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg">
      {/* Status dot */}
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
          {isRunning ? 'Online' : isStarting ? 'Starting...' : 'Offline'}
        </span>
      </div>

      {/* Auto-shutdown countdown */}
      {isRunning && remaining != null && (
        <span className="text-xs text-[var(--color-text-muted)]">
          Auto-stop in {remaining}m
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
  );
}
