import { useRef, useState } from 'react';
import { Link, Loader2, Power, Upload } from 'lucide-react';

interface Props {
  onSubmitUrl: (url: string) => void;
  onSubmitFile: (file: File) => void;
  loading: boolean;
  podOffline?: boolean;
  podStarting?: boolean;
  onStartPod?: () => void;
}

export function UrlInput({ onSubmitUrl, onSubmitFile, loading, podOffline, podStarting, onStartPod }: Props) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    try {
      new URL(url.trim());
    } catch {
      setError('Please enter a valid URL');
      return;
    }
    onSubmitUrl(url.trim());
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError('');
    onSubmitFile(file);
    // Reset so the same file can be re-selected
    e.target.value = '';
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Link className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" size={18} />
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste video URL..."
            disabled={loading}
            className="w-full pl-10 pr-4 py-3 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text)] placeholder-[var(--color-text-muted)] outline-none focus:border-[var(--color-primary)] transition-colors disabled:opacity-50"
          />
        </div>
        {podOffline ? (
          <button
            type="button"
            onClick={onStartPod}
            className="px-6 py-3 rounded-lg bg-green-600 hover:bg-green-500 text-white font-medium transition-colors flex items-center gap-2"
          >
            <Power size={18} />
            Start GPU Server
          </button>
        ) : podStarting ? (
          <button
            type="button"
            disabled
            className="px-6 py-3 rounded-lg bg-yellow-600/50 text-yellow-200 font-medium cursor-not-allowed flex items-center gap-2"
          >
            <Loader2 size={18} className="animate-spin" />
            Starting...
          </button>
        ) : (
          <button
            type="submit"
            disabled={loading || !url.trim()}
            className="px-6 py-3 rounded-lg bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : null}
            {loading ? 'Processing...' : 'Animate'}
          </button>
        )}
        <button
          type="button"
          disabled={loading}
          onClick={() => fileRef.current?.click()}
          className="px-4 py-3 rounded-lg bg-[var(--color-surface)] border border-[var(--color-border)] hover:bg-[var(--color-surface-2)] text-[var(--color-text)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          title="Upload video file"
        >
          <Upload size={18} />
          <span className="hidden sm:inline text-sm">Upload</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          onChange={handleFile}
          className="hidden"
        />
      </div>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </form>
  );
}
