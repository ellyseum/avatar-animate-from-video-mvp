// GET /api/jobs/:id/comparison — serve comparison.mp4 from R2, fallback to pod proxy

interface Env {
  MOCAP_KV: KVNamespace;
  RESULTS_BUCKET: R2Bucket;
}

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const { request, env, params } = context;
  const jobId = params.id as string;
  const key = `jobs/${jobId}/comparison.mp4`;

  // Try R2 first — use head to check existence, then get with range if needed
  const head = await env.RESULTS_BUCKET.head(key);
  if (head) {
    const range = request.headers.get('Range');
    const getOpts: R2GetOptions = {};
    if (range) {
      const match = range.match(/bytes=(\d+)-(\d*)/);
      if (match) {
        const start = parseInt(match[1], 10);
        const end = match[2] ? parseInt(match[2], 10) : head.size - 1;
        getOpts.range = { offset: start, length: end - start + 1 };
      }
    }

    const obj = await env.RESULTS_BUCKET.get(key, getOpts);
    if (!obj) {
      return Response.json({ error: 'Comparison not found' }, { status: 404 });
    }

    const headers: Record<string, string> = {
      'Content-Type': 'video/mp4',
      'Cache-Control': 'public, max-age=86400',
      'Access-Control-Allow-Origin': '*',
      'Accept-Ranges': 'bytes',
    };

    if (range && getOpts.range) {
      const r = getOpts.range as { offset: number; length: number };
      const end = r.offset + r.length - 1;
      headers['Content-Range'] = `bytes ${r.offset}-${end}/${head.size}`;
      headers['Content-Length'] = String(r.length);
      return new Response(obj.body, { status: 206, headers });
    }

    headers['Content-Length'] = String(head.size);
    return new Response(obj.body, { headers });
  }

  // Fallback: proxy to pod
  const podUrl = await env.MOCAP_KV.get('pod_url');
  if (!podUrl) {
    return Response.json(
      { error: 'Comparison not found and pod is not running' },
      { status: 404 }
    );
  }

  try {
    const target = `${podUrl}/api/jobs/${jobId}/comparison`;
    const proxyHeaders = new Headers(request.headers);
    proxyHeaders.set('Host', new URL(podUrl).host);
    const res = await fetch(target, { headers: proxyHeaders });
    const responseHeaders = new Headers(res.headers);
    responseHeaders.set('Access-Control-Allow-Origin', '*');
    return new Response(res.body, {
      status: res.status,
      statusText: res.statusText,
      headers: responseHeaders,
    });
  } catch (err: any) {
    return Response.json(
      { error: `Failed to reach pod: ${err.message}` },
      { status: 502 }
    );
  }
};
