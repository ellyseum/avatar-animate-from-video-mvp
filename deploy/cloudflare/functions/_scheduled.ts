// Cron trigger: auto-stop pod after 15 min idle (preserves machine affinity)

interface Env {
  RUNPOD_API_KEY: string;
  MOCAP_KV: KVNamespace;
}

const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes

async function runpodGql(apiKey: string, query: string): Promise<any> {
  const res = await fetch('https://api.runpod.io/graphql?api_key=' + apiKey, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  return res.json();
}

export default {
  async scheduled(
    _event: ScheduledEvent,
    env: Env,
    _ctx: ExecutionContext
  ) {
    const podId = await env.MOCAP_KV.get('pod_id');

    if (!podId) {
      console.log('[cron] No active pod, nothing to do');
      return;
    }

    const data = await runpodGql(env.RUNPOD_API_KEY,
      `query { pod(input: { podId: "${podId}" }) { desiredStatus } }`
    );
    const status = data.data?.pod?.desiredStatus || 'UNKNOWN';

    // Pod already stopped or gone — clean runtime KV but keep pod_id for resume
    if (status === 'EXITED') {
      console.log(`[cron] Pod ${podId} already stopped, cleaning runtime KV`);
      await Promise.all([
        env.MOCAP_KV.delete('pod_url'),
        env.MOCAP_KV.delete('lastActivity'),
        env.MOCAP_KV.delete('start_time'),
        env.MOCAP_KV.delete('start_strategy'),
      ]);
      return;
    }

    // Pod terminated externally — full cleanup
    if (status === 'UNKNOWN' || !data.data?.pod) {
      console.log(`[cron] Pod ${podId} gone, full KV cleanup`);
      await Promise.all([
        env.MOCAP_KV.delete('pod_id'),
        env.MOCAP_KV.delete('pod_url'),
        env.MOCAP_KV.delete('lastActivity'),
        env.MOCAP_KV.delete('start_time'),
        env.MOCAP_KV.delete('start_strategy'),
      ]);
      return;
    }

    if (status !== 'RUNNING') {
      console.log(`[cron] Pod ${podId} is ${status}, nothing to do`);
      return;
    }

    // Check idle time
    const lastActivity = await env.MOCAP_KV.get('lastActivity');
    const lastMs = lastActivity ? parseInt(lastActivity) : 0;
    const idleMs = Date.now() - lastMs;

    if (idleMs > IDLE_TIMEOUT_MS) {
      console.log(
        `[cron] Pod ${podId} idle for ${Math.floor(idleMs / 60_000)} min, stopping (preserving affinity)`
      );

      // podStop (not terminate) — preserves machine for fast resume next session
      await runpodGql(env.RUNPOD_API_KEY,
        `mutation { podStop(input: { podId: "${podId}" }) { id desiredStatus } }`
      );

      // Clean runtime KV, keep pod_id
      await Promise.all([
        env.MOCAP_KV.delete('pod_url'),
        env.MOCAP_KV.delete('lastActivity'),
        env.MOCAP_KV.delete('start_time'),
        env.MOCAP_KV.delete('start_strategy'),
      ]);
    } else {
      console.log(
        `[cron] Pod ${podId} active, idle ${Math.floor(idleMs / 60_000)} min`
      );
    }
  },
};
