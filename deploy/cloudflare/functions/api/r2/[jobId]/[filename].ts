// PUT /api/r2/:jobId/:filename — upload pipeline result to R2
// Called by the pod after pipeline completion

interface Env {
  RESULTS_BUCKET: R2Bucket;
  RUNPOD_API_KEY: string;
}

const ALLOWED_FILES = new Set([
  'result.glb',
  'comparison.mp4',
  'overlay.mp4',
]);

const CONTENT_TYPES: Record<string, string> = {
  '.glb': 'model/gltf-binary',
  '.mp4': 'video/mp4',
};

export const onRequestPut: PagesFunction<Env> = async (context) => {
  const { request, env, params } = context;
  const jobId = params.jobId as string;
  const filename = params.filename as string;

  // Auth: require RunPod API key as bearer token
  const auth = request.headers.get('Authorization');
  if (!auth || auth !== `Bearer ${env.RUNPOD_API_KEY}`) {
    return new Response('Unauthorized', { status: 401 });
  }

  if (!ALLOWED_FILES.has(filename)) {
    return Response.json({ error: 'Invalid filename' }, { status: 400 });
  }

  const ext = filename.substring(filename.lastIndexOf('.'));
  const contentType = CONTENT_TYPES[ext] || 'application/octet-stream';

  const key = `jobs/${jobId}/${filename}`;
  await env.RESULTS_BUCKET.put(key, request.body, {
    httpMetadata: { contentType },
  });

  return Response.json({ ok: true, key });
};
