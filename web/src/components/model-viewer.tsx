import { useRef, useState, useCallback } from 'react';
import { Play, Pause, RotateCcw } from 'lucide-react';

export function ModelViewer({ glbUrl }: { glbUrl: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); }
    else { v.pause(); setPlaying(false); }
  }, []);

  const handleSeek = useCallback((t: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = t;
    setTime(t);
  }, []);

  const handleRestart = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = 0;
    v.play();
    setPlaying(true);
  }, []);

  const handleSpeedChange = useCallback((s: number) => {
    const v = videoRef.current;
    if (v) v.playbackRate = s;
    setSpeed(s);
  }, []);

  return (
    <div className="w-full max-w-4xl mx-auto mt-8">
      <div className="bg-[var(--color-surface)] rounded-lg border border-[var(--color-border)] overflow-hidden">
        <div className="flex justify-center bg-black">
          <video
            ref={videoRef}
            src={glbUrl}
            autoPlay
            loop
            muted
            playsInline
            className="max-h-[500px] w-auto"
            onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
            onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
          />
        </div>

        {/* Controls */}
        <div className="flex items-center gap-4 px-4 py-3 border-t border-[var(--color-border)]">
          <button
            onClick={togglePlay}
            className="p-2 rounded hover:bg-[var(--color-surface-2)] transition-colors"
          >
            {playing
              ? <Pause size={18} className="text-[var(--color-text)]" />
              : <Play size={18} className="text-[var(--color-text)]" />
            }
          </button>

          <button
            onClick={handleRestart}
            className="p-2 rounded hover:bg-[var(--color-surface-2)] transition-colors"
          >
            <RotateCcw size={16} className="text-[var(--color-text)]" />
          </button>

          <input
            type="range"
            min={0}
            max={duration || 1}
            step={0.01}
            value={time}
            onChange={(e) => handleSeek(parseFloat(e.target.value))}
            className="flex-1 accent-[var(--color-primary)]"
          />

          <span className="text-xs text-[var(--color-text-muted)] tabular-nums w-24 text-right">
            {time.toFixed(1)}s / {duration.toFixed(1)}s
          </span>

          <select
            value={speed}
            onChange={(e) => handleSpeedChange(parseFloat(e.target.value))}
            className="text-xs bg-[var(--color-surface-2)] border border-[var(--color-border)] rounded px-2 py-1 text-[var(--color-text)]"
          >
            {[0.25, 0.5, 1, 1.5, 2].map(s => (
              <option key={s} value={s}>{s}x</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
