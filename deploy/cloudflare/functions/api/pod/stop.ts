// POST /api/pod/stop — stop (not terminate) to preserve machine affinity

interface Env {
  RUNPOD_API_KEY: string;
  MOCAP_KV: KVNamespace;
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const { env } = context;

  try {
    const podId = await env.MOCAP_KV.get('pod_id');
    if (!podId) {
      return Response.json({ status: 'stopped' });
    }

    // podStop (not terminate) — keeps machine affinity for fast resume
    const res = await fetch(
      'https://api.runpod.io/graphql?api_key=' + env.RUNPOD_API_KEY,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: `mutation { podStop(input: { podId: "${podId}" }) { id desiredStatus } }`,
        }),
      }
    );

    if (!res.ok) throw new Error(`RunPod API error: ${res.status}`);

    // Keep pod_id (for resume), clear runtime state
    await Promise.all([
      env.MOCAP_KV.delete('pod_url'),
      env.MOCAP_KV.delete('lastActivity'),
      env.MOCAP_KV.delete('start_time'),
      env.MOCAP_KV.delete('start_strategy'),
    ]);

    return Response.json({ status: 'stopped' });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
