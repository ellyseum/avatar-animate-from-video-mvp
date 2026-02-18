// POST /api/pod/start — resume cached pod or create new with GPU fallback

interface Env {
  RUNPOD_API_KEY: string;
  MOCAP_KV: KVNamespace;
}

// GPU priority: cheapest first, all verified to have available stock
const GPU_PRIORITY = [
  'NVIDIA RTX A5000',               // $0.16/hr, 24GB
  'NVIDIA RTX A4000',               // $0.17/hr, 16GB
  'NVIDIA RTX A4500',               // $0.19/hr, 20GB
  'NVIDIA RTX 4000 Ada Generation', // $0.20/hr, 20GB
  'NVIDIA GeForce RTX 3090',        // $0.22/hr, 24GB
  'NVIDIA GeForce RTX 4090',        // $0.34/hr, 24GB
];

const POD_CONFIG = {
  name: 'mocap-demo',
  imageName: 'ellyseum/mocap-runpod:latest',
  containerDiskInGb: 50,
  volumeInGb: 50,
  volumeMountPath: '/workspace',
  ports: '3001/http,22/tcp',
  env: [] as Array<{ key: string; value: string }>, // populated at runtime with secrets
  gpuCount: 1,
  startJupyter: false,
  startSsh: true,
};

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

async function terminatePod(apiKey: string, podId: string) {
  await runpodGql(apiKey, `mutation { podTerminate(input: { podId: "${podId}" }) }`);
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

function buildPodEnv(apiKey: string): Array<{ key: string; value: string }> {
  return [
    { key: 'PIPELINE_MODE', value: 'direct' },
    { key: 'PREPROCESSOR_MODE', value: 'ffmpeg' },
    { key: 'R2_UPLOAD_URL', value: 'https://avatar.ellyseum.dev' },
    { key: 'R2_UPLOAD_KEY', value: apiKey },
  ];
}

async function tryCreatePod(apiKey: string, gpuTypeId: string): Promise<any | null> {
  const podEnv = buildPodEnv(apiKey);
  const data = await runpodGql(apiKey, `
    mutation {
      podFindAndDeployOnDemand(input: {
        name: "${POD_CONFIG.name}"
        imageName: "${POD_CONFIG.imageName}"
        gpuTypeId: "${gpuTypeId}"
        gpuCount: ${POD_CONFIG.gpuCount}
        containerDiskInGb: ${POD_CONFIG.containerDiskInGb}
        volumeInGb: ${POD_CONFIG.volumeInGb}
        volumeMountPath: "${POD_CONFIG.volumeMountPath}"
        ports: "${POD_CONFIG.ports}"
        startJupyter: ${POD_CONFIG.startJupyter}
        startSsh: ${POD_CONFIG.startSsh}
        env: [${podEnv.map(e => `{ key: "${e.key}", value: "${e.value}" }`).join(', ')}]
      }) {
        id
        desiredStatus
        machine {
          gpuDisplayName
        }
      }
    }
  `);

  const pod = data.data?.podFindAndDeployOnDemand;
  if (pod?.id) return pod;

  const errors = data.errors?.map((e: any) => e.message).join(', ') || '';
  console.log(`[start] ${gpuTypeId} failed: ${errors}`);
  return null;
}

async function createFreshPod(apiKey: string, kv: KVNamespace): Promise<Response> {
  for (const gpuType of GPU_PRIORITY) {
    const pod = await tryCreatePod(apiKey, gpuType);
    if (pod) {
      await Promise.all([
        kv.put('pod_id', pod.id),
        kv.put('lastActivity', String(Date.now())),
        kv.put('start_time', String(Date.now())),
        kv.put('start_strategy', 'create'),
      ]);

      const gpu = pod.machine?.gpuDisplayName || gpuType;
      return Response.json({ status: 'starting', podId: pod.id, gpu });
    }
  }

  return Response.json(
    { error: 'No GPUs available. All GPU types are currently at capacity. Try again in a few minutes.' },
    { status: 503 }
  );
}

export const onRequestPost: PagesFunction<Env> = async (context) => {
  const { env } = context;

  try {
    const existingPodId = await env.MOCAP_KV.get('pod_id');

    if (existingPodId) {
      const check = await runpodGql(env.RUNPOD_API_KEY, `
        query { pod(input: { podId: "${existingPodId}" }) {
          id desiredStatus runtime { uptimeInSeconds }
          machine { gpuDisplayName }
        } }
      `);
      const existing = check.data?.pod;
      const gpu = existing?.machine?.gpuDisplayName || null;

      if (!existing) {
        // Pod gone — clean up, create fresh
        await cleanKv(env.MOCAP_KV);
        return createFreshPod(env.RUNPOD_API_KEY, env.MOCAP_KV);
      }

      if (existing.desiredStatus === 'RUNNING' && existing.runtime?.uptimeInSeconds > 0) {
        return Response.json({ status: 'running', podId: existing.id, gpu });
      }

      if (existing.desiredStatus === 'RUNNING' && !existing.runtime?.uptimeInSeconds) {
        // Already starting — check if stuck based on strategy
        const [startTime, strategy] = await Promise.all([
          env.MOCAP_KV.get('start_time'),
          env.MOCAP_KV.get('start_strategy'),
        ]);
        const elapsed = startTime ? Date.now() - parseInt(startTime) : 0;
        const timeout = strategy === 'resume' ? RESUME_STUCK_MS : CREATE_STUCK_MS;

        if (elapsed > timeout) {
          console.log(`[start] Pod ${existingPodId} stuck (${strategy}) for ${Math.floor(elapsed / 1000)}s, abandoning`);
          await terminatePod(env.RUNPOD_API_KEY, existingPodId);
          await cleanKv(env.MOCAP_KV);
          return createFreshPod(env.RUNPOD_API_KEY, env.MOCAP_KV);
        }

        return Response.json({ status: 'starting', podId: existing.id, gpu });
      }

      if (existing.desiredStatus === 'EXITED') {
        // Stopped pod on same machine — try resume
        const data = await runpodGql(env.RUNPOD_API_KEY, `
          mutation { podResume(input: { podId: "${existingPodId}", gpuCount: 1 }) {
            id desiredStatus machine { gpuDisplayName }
          } }
        `);

        const resumed = data.data?.podResume;
        if (resumed?.id) {
          await Promise.all([
            env.MOCAP_KV.put('lastActivity', String(Date.now())),
            env.MOCAP_KV.put('start_time', String(Date.now())),
            env.MOCAP_KV.put('start_strategy', 'resume'),
          ]);
          return Response.json({
            status: 'starting',
            podId: resumed.id,
            gpu: resumed.machine?.gpuDisplayName || gpu,
          });
        }

        // Resume failed — terminate, create fresh
        console.log(`[start] podResume failed for ${existingPodId}, creating fresh`);
        await terminatePod(env.RUNPOD_API_KEY, existingPodId);
        await cleanKv(env.MOCAP_KV);
        return createFreshPod(env.RUNPOD_API_KEY, env.MOCAP_KV);
      }

      // Unknown state — clean up, create fresh
      await terminatePod(env.RUNPOD_API_KEY, existingPodId);
      await cleanKv(env.MOCAP_KV);
    }

    return createFreshPod(env.RUNPOD_API_KEY, env.MOCAP_KV);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
