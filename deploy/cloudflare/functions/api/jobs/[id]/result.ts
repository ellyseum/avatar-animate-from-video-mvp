// GET /api/jobs/:id/result — serve result.glb from R2, fallback to pod proxy

interface Env {
  MOCAP_KV: KVNamespace;
  RESULTS_BUCKET: R2Bucket;
}

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const { env, params } = context;
  const jobId = params.id as string;

  // Try R2 first
  const obj = await env.RESULTS_BUCKET.get(`jobs/${jobId}/result.glb`);
  if (obj) {
    return new Response(obj.body, {
      headers: {
        'Content-Type': 'model/gltf-binary',
        'Content-Disposition': `inline; filename="${jobId}.glb"`,
        'Cache-Control': 'public, max-age=86400',
        'Access-Control-Allow-Origin': '*',
      },
    });
  }

  // Fallback: proxy to pod
  const podUrl = await env.MOCAP_KV.get('pod_url');
  if (!podUrl) {
    return Response.json(
      { error: 'Result not found and pod is not running' },
      { status: 404 }
    );
  }

  try {
    const target = `${podUrl}/api/jobs/${jobId}/result`;
    const res = await fetch(target);
    const headers = new Headers(res.headers);
    headers.set('Access-Control-Allow-Origin', '*');
    return new Response(res.body, { status: res.status, headers });
  } catch (err: any) {
    return Response.json(
      { error: `Failed to reach pod: ${err.message}` },
      { status: 502 }
    );
  }
};
