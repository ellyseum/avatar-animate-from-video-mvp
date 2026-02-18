// GET /api/pod/status — returns current pod state, auto-recovers stuck resumes

interface Env {
  RUNPOD_API_KEY: string;
  MOCAP_KV: KVNamespace;
}

// Resume = cached image, should boot in <60s. If stuck >2min, machine is gone.
const RESUME_STUCK_MS = 2 * 60 * 1000;
// Fresh create = image pull needed, can take 5-8 min. 10 min safety net.
const CREATE_STUCK_MS = 10 * 60 * 1000;

async function runpodGql(apiKey: string, query: string): Promise<any> {
  const res = await fetch('https://api.runpod.io/graphql?api_key=' + apiKey, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`RunPod API error: ${res.status}`);
  return res.json();
}

async function cleanKv(kv: KVNamespace) {
  await Promise.all([
    kv.delete('pod_id'),
    kv.delete('pod_url'),
    kv.delete('lastActivity'),
    kv.delete('start_time'),
    kv.delete('start_strategy'),
  ]);
}

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const { env } = context;
  const stopped = { status: 'stopped', url: null, idleMinutes: null, gpu: null };

  try {
    const podId = await env.MOCAP_KV.get('pod_id');
    if (!podId) return Response.json(stopped);

    const data = await runpodGql(env.RUNPOD_API_KEY, `
      query { pod(input: { podId: "${podId}" }) {
        id desiredStatus
        runtime { uptimeInSeconds ports { ip isIpPublic privatePort publicPort type } }
        machine { gpuDisplayName }
      } }
    `);
    const pod = data.data?.pod;

    if (!pod) {
      await cleanKv(env.MOCAP_KV);
      return Response.json(stopped);
    }

    const desired = pod.desiredStatus;
    const uptime = pod.runtime?.uptimeInSeconds;
    const gpu = pod.machine?.gpuDisplayName || null;

    // Extract URL
    let url: string | null = null;
    if (pod.runtime?.ports) {
      const httpPort = pod.runtime.ports.find(
        (p: any) => p.privatePort === 3001 && p.isIpPublic
      );
      if (httpPort) url = `https://${httpPort.ip}:${httpPort.publicPort}`;
    }
    if (!url && pod.id) url = `https://${pod.id}-3001.proxy.runpod.net`;

    let status: string;

    if (desired === 'RUNNING' && uptime > 0) {
      status = 'running';
      const puts: Promise<void>[] = [
        env.MOCAP_KV.delete('start_time'),
        env.MOCAP_KV.delete('start_strategy'),
      ];
      if (url) puts.push(env.MOCAP_KV.put('pod_url', url));
      await Promise.all(puts);

    } else if (desired === 'RUNNING' && !uptime) {
      status = 'starting';

      // Stuck detection — different timeouts for resume vs create
      const [startTime, strategy] = await Promise.all([
        env.MOCAP_KV.get('start_time'),
        env.MOCAP_KV.get('start_strategy'),
      ]);
      const elapsed = startTime ? Date.now() - parseInt(startTime) : 0;
      const timeout = strategy === 'resume' ? RESUME_STUCK_MS : CREATE_STUCK_MS;

      if (startTime && elapsed > timeout) {
        console.log(`[status] Pod ${podId} stuck (${strategy}) for ${Math.floor(elapsed / 1000)}s, terminating`);
        await runpodGql(env.RUNPOD_API_KEY,
          `mutation { podTerminate(input: { podId: "${podId}" }) }`
        );
        await cleanKv(env.MOCAP_KV);
        return Response.json(stopped);
      }

    } else if (desired === 'EXITED') {
      // Stopped but preserved for resume
      status = 'stopped';
      await Promise.all([
        env.MOCAP_KV.delete('pod_url'),
        env.MOCAP_KV.delete('lastActivity'),
        env.MOCAP_KV.delete('start_time'),
        env.MOCAP_KV.delete('start_strategy'),
      ]);

    } else {
      status = 'stopped';
      await cleanKv(env.MOCAP_KV);
    }

    const lastActivity = await env.MOCAP_KV.get('lastActivity');
    const idleSince = lastActivity ? parseInt(lastActivity) : null;
    const idleMinutes = idleSince
      ? Math.floor((Date.now() - idleSince) / 60_000)
      : null;

    // Include startup timing info for progress display
    let startElapsedMs: number | null = null;
    let startStrategy: string | null = null;
    if (status === 'starting') {
      const [startTime, strategy] = await Promise.all([
        env.MOCAP_KV.get('start_time'),
        env.MOCAP_KV.get('start_strategy'),
      ]);
      startElapsedMs = startTime ? Date.now() - parseInt(startTime) : null;
      startStrategy = strategy;
    }

    return Response.json({ status, url, idleMinutes, gpu, startElapsedMs, startStrategy });
  } catch (err: any) {
    return Response.json(
      { status: 'error', error: err.message },
      { status: 500 }
    );
  }
};
