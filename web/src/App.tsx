import { useCallback, useEffect, useRef, useState } from 'react';
import { UrlInput } from './components/url-input';
import { JobStatusDisplay } from './components/job-status';
import { ModelViewer } from './components/model-viewer';
import { JobHistory } from './components/job-history';
import { PodControl } from './components/pod-control';
import { useJob } from './hooks/use-job';
import { submitJob, uploadVideo, getResultUrl, getVideoUrl, checkPodStatus, startPod, stopPod } from './lib/api';
import type { VideoType } from './lib/api';
import { connect, disconnect, subscribe } from './lib/ws';
import type { Job, PodState } from './lib/types';

// Detect deployed mode: Cloudflare Pages serves at mocap.ellyseum.dev
// In local dev (Vite proxy), pod management is not needed.
const IS_DEPLOYED = location.hostname.includes('ellyseum.dev')
  || location.hostname.includes('pages.dev');

// ---------------------------------------------------------------------------
// Video panel with label + sync controls
// ---------------------------------------------------------------------------

function VideoPanel({ url, label, syncRef }: {
  url: string;
  label: string;
  syncRef?: React.RefObject<HTMLVideoElement[]>;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (syncRef?.current && videoRef.current) {
      syncRef.current.push(videoRef.current);
    }
  }, [syncRef]);

  return (
    <div className="flex flex-col min-w-0">
      <span className="text-[10px] font-medium text-[var(--color-text-muted)] mb-1 uppercase tracking-wider truncate">
        {label}
      </span>
      <div className="bg-black rounded overflow-hidden border border-[var(--color-border)] aspect-[9/16]">
        <video
          ref={videoRef}
          src={url}
          controls
          loop
          muted
          autoPlay
          playsInline
          className="w-full h-full object-contain"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results view: video grid + 3D viewer
// ---------------------------------------------------------------------------

const VIDEO_PANELS: { type: VideoType; label: string }[] = [
  { type: 'original', label: 'Original' },
  { type: 'preprocessed', label: 'AI Silhouette' },
  { type: 'frankmocap', label: 'FrankMocap' },
  { type: 'overlay', label: 'Overlay' },
  { type: 'comparison', label: 'Comparison' },
];

function ResultsView({ jobId }: { jobId: string }) {
  const syncRef = useRef<HTMLVideoElement[]>([]);
  const [availableVideos, setAvailableVideos] = useState<VideoType[]>([]);

  // Probe which videos exist for this job
  useEffect(() => {
    syncRef.current = [];
    const allTypes: VideoType[] = ['original', 'preprocessed', 'frankmocap', 'overlay', 'comparison'];
    Promise.all(
      allTypes.map(async (type) => {
        try {
          const res = await fetch(getVideoUrl(jobId, type), { method: 'HEAD' });
          return res.ok ? type : null;
        } catch {
          return null;
        }
      })
    ).then((results) => {
      setAvailableVideos(results.filter((r): r is VideoType => r !== null));
    });
  }, [jobId]);

  const panels = VIDEO_PANELS.filter(p => availableVideos.includes(p.type));

  return (
    <div className="w-full max-w-[1800px] mx-auto mt-6 flex gap-4">
      {/* Left: Video grid */}
      <div className="flex-1 min-w-0">
        <div className={`grid gap-3 ${
          panels.length <= 2 ? 'grid-cols-2' :
          panels.length <= 4 ? 'grid-cols-2 lg:grid-cols-4' :
          'grid-cols-2 lg:grid-cols-4'
        }`}>
          {panels.map(({ type, label }) => (
            <VideoPanel
              key={type}
              url={getVideoUrl(jobId, type)}
              label={label}
              syncRef={syncRef}
            />
          ))}
        </div>
      </div>

      {/* Right: 3D orbit viewer */}
      <div className="w-[400px] xl:w-[500px] flex-shrink-0">
        <span className="text-[10px] font-medium text-[var(--color-text-muted)] mb-1 uppercase tracking-wider block">
          3D Avatar
        </span>
        <ModelViewer glbUrl={getResultUrl(jobId)} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const DEFAULT_POD: PodState = { status: 'unknown', url: null, idleMinutes: null };

function App() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [pod, setPod] = useState<PodState>(IS_DEPLOYED ? DEFAULT_POD : { status: 'running', url: null, idleMinutes: null });
  const [podStarting, setPodStarting] = useState(false);

  // --- Pod status polling (deployed mode only) ---
  useEffect(() => {
    if (!IS_DEPLOYED) return;

    let cancelled = false;
    let interval: ReturnType<typeof setInterval>;

    async function poll() {
      try {
        const state = await checkPodStatus();
        if (cancelled) return;
        setPod(state);

        // Once running, connect WS directly to pod
        if (state.status === 'running' && state.url) {
          connect(state.url);
          setPodStarting(false);
        } else {
          disconnect();
        }
      } catch {
        if (!cancelled) setPod({ status: 'error', url: null, idleMinutes: null, error: 'Failed to check status' });
      }
    }

    poll();
    // Poll faster while starting, slower when stable
    interval = setInterval(poll, podStarting ? 5_000 : 15_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [podStarting]);

  // --- Local dev: connect WS immediately ---
  useEffect(() => {
    if (IS_DEPLOYED) return;
    connect();
    return () => disconnect();
  }, []);

  // --- WS message handler ---
  useEffect(() => {
    return subscribe((msg) => {
      if (msg.type === 'jobs:list' && !activeJobId) {
        const recent = msg.jobs.find((j) => j.status === 'complete');
        if (recent) setActiveJobId(recent.id);
      }
      if (msg.type === 'job:delete') {
        setActiveJobId((prev) => prev === msg.id ? null : prev);
      }
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const job = useJob(activeJobId);

  const handleStartPod = useCallback(async () => {
    setPodStarting(true);
    try {
      const result = await startPod();
      setPod(prev => ({ ...prev, status: 'starting', gpu: result.gpu || null }));
    } catch {
      setPodStarting(false);
    }
  }, []);

  const handleStopPod = useCallback(async () => {
    try {
      await stopPod();
      setPod({ status: 'stopped', url: null, idleMinutes: null });
      disconnect();
    } catch { /* ignore */ }
  }, []);

  const handleSubmitUrl = useCallback(async (url: string) => {
    setSubmitting(true);
    setError('');
    try {
      const newJob = await submitJob(url);
      setActiveJobId(newJob.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit');
    } finally {
      setSubmitting(false);
    }
  }, []);

  const handleSubmitFile = useCallback(async (file: File) => {
    setSubmitting(true);
    setError('');
    try {
      const newJob = await uploadVideo(file);
      setActiveJobId(newJob.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload');
    } finally {
      setSubmitting(false);
    }
  }, []);

  const handleSelectJob = useCallback((j: Job) => {
    setActiveJobId(j.id);
    setError('');
  }, []);

  const isProcessing = job && job.status !== 'complete' && job.status !== 'failed';
  const isComplete = job?.status === 'complete';
  const podReady = pod.status === 'running';

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-[var(--color-border)] px-6 py-3">
        <h1 className="text-lg font-semibold tracking-tight">
          YouTube Mocap Viewer
        </h1>
        <p className="text-xs text-[var(--color-text-muted)]">
          Paste a YouTube URL to extract and view motion capture
        </p>
      </header>

      <main className="flex-1 px-4 py-4">
        {/* Pod control bar (deployed mode only) */}
        {IS_DEPLOYED && (
          <div className="mb-4">
            <PodControl
              pod={pod}
              onStart={handleStartPod}
              onStop={handleStopPod}
              starting={podStarting}
            />
          </div>
        )}

        <UrlInput
          onSubmitUrl={handleSubmitUrl}
          onSubmitFile={handleSubmitFile}
          loading={submitting || !!isProcessing}
          podOffline={IS_DEPLOYED && !podReady && !podStarting}
          podStarting={IS_DEPLOYED && podStarting}
          onStartPod={handleStartPod}
        />

        {IS_DEPLOYED && podStarting && (
          <p className="mt-3 text-center text-xs text-[var(--color-text-muted)]">
            GPU server is booting up — this usually takes 1-4 minutes
          </p>
        )}

        {error && (
          <p className="mt-4 text-center text-sm text-red-400">{error}</p>
        )}

        {job && !isComplete && <JobStatusDisplay job={job} />}

        {isComplete && job && <ResultsView jobId={job.id} />}

        <JobHistory onSelect={handleSelectJob} />
      </main>
    </div>
  );
}

export default App;
