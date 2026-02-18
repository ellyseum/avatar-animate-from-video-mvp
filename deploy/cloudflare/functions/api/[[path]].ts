// Catch-all: proxy /api/* (except /api/pod/*) to the running RunPod pod

interface Env {
  MOCAP_KV: KVNamespace;
  RESULTS_BUCKET: R2Bucket;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const { request, env } = context;
  const url = new URL(request.url);

  // Don't proxy pod management routes (handled by their own functions)
  if (url.pathname.startsWith('/api/pod/')) {
    return new Response('Not Found', { status: 404 });
  }

  // Get pod URL from KV
  const podUrl = await env.MOCAP_KV.get('pod_url');
  if (!podUrl) {
    return Response.json(
      { error: 'Pod is not running. Start it first.' },
      { status: 503 }
    );
  }

  // Update activity timestamp
  await env.MOCAP_KV.put('lastActivity', String(Date.now()));

  // Build target URL — preserve path and query string
  const target = new URL(url.pathname + url.search, podUrl);

  // Forward the request to the pod
  const headers = new Headers(request.headers);
  headers.set('Host', new URL(podUrl).host);
  // Remove Cloudflare-specific headers the pod doesn't need
  headers.delete('cf-connecting-ip');
  headers.delete('cf-ray');

  try {
    const proxyRes = await fetch(target.toString(), {
      method: request.method,
      headers,
      body: request.body,
      // @ts-ignore — Cloudflare Workers supports duplex
      duplex: request.body ? 'half' : undefined,
    });

    // Return response with CORS headers
    const responseHeaders = new Headers(proxyRes.headers);
    responseHeaders.set('Access-Control-Allow-Origin', '*');

    return new Response(proxyRes.body, {
      status: proxyRes.status,
      statusText: proxyRes.statusText,
      headers: responseHeaders,
    });
  } catch (err: any) {
    return Response.json(
      { error: `Failed to reach pod: ${err.message}` },
      { status: 502 }
    );
  }
};
