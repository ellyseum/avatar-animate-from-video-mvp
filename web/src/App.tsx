import { useCallback, useState } from 'react';
import { UrlInput } from './components/url-input';
import { JobStatusDisplay } from './components/job-status';
import { ModelViewer } from './components/model-viewer';
import { JobHistory } from './components/job-history';
import { useJob } from './hooks/use-job';
import { submitJob, getResultUrl } from './lib/api';
import type { Job } from './lib/types';

function App() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const job = useJob(activeJobId);

  const handleSubmit = useCallback(async (url: string) => {
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

  const handleSelectJob = useCallback((j: Job) => {
    setActiveJobId(j.id);
    setError('');
  }, []);

  const isProcessing = job && job.status !== 'complete' && job.status !== 'failed';
  const isComplete = job?.status === 'complete';

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-[var(--color-border)] px-6 py-4">
        <h1 className="text-xl font-semibold tracking-tight">
          YouTube Mocap Viewer
        </h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          Paste a YouTube URL to extract and view motion capture
        </p>
      </header>

      {/* Main content */}
      <main className="flex-1 px-6 py-8">
        <UrlInput onSubmit={handleSubmit} loading={submitting || !!isProcessing} />

        {error && (
          <p className="mt-4 text-center text-sm text-red-400">{error}</p>
        )}

        {job && !isComplete && <JobStatusDisplay job={job} />}

        {isComplete && job && (
          <ModelViewer glbUrl={getResultUrl(job.id)} />
        )}

        <JobHistory onSelect={handleSelectJob} />
      </main>
    </div>
  );
}

export default App;
