const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs').promises;

const http = require('http');
const https = require('https');

const PROJECT_ROOT = path.join(__dirname, '..', '..');
const SMPL_DIR = path.join(PROJECT_ROOT, 'smpl');

// Pipeline execution mode: 'docker' (default) or 'direct' (RunPod — no Docker-in-Docker)
const PIPELINE_MODE = process.env.PIPELINE_MODE || 'docker';

// Preprocessor config (env-driven)
const PREPROCESSOR_MODE = process.env.PREPROCESSOR_MODE || 'docker';
const PREPROCESSOR_IMAGE = process.env.PREPROCESSOR_IMAGE || 'silhouette-preprocessor';
const PREPROCESSOR_MODEL_CACHE = process.env.PREPROCESSOR_MODEL_CACHE
    || path.join(process.env.HOME || '/root', '.cache', 'huggingface');
const PREPROCESSOR_REMOTE_URL = process.env.PREPROCESSOR_REMOTE_URL || 'http://localhost:7860';
const PREPROCESSOR_PROMPT = process.env.PREPROCESSOR_PROMPT || null;
const PREPROCESSOR_NEGATIVE_PROMPT = process.env.PREPROCESSOR_NEGATIVE_PROMPT || null;
const PREPROCESSOR_STEPS = process.env.PREPROCESSOR_STEPS ? parseInt(process.env.PREPROCESSOR_STEPS) : null;
const PREPROCESSOR_STRENGTH = process.env.PREPROCESSOR_STRENGTH ? parseFloat(process.env.PREPROCESSOR_STRENGTH) : null;
const PREPROCESSOR_GUIDANCE_SCALE = process.env.PREPROCESSOR_GUIDANCE_SCALE ? parseFloat(process.env.PREPROCESSOR_GUIDANCE_SCALE) : null;
const PREPROCESSOR_CONTROLNET_SCALE = process.env.PREPROCESSOR_CONTROLNET_SCALE ? parseFloat(process.env.PREPROCESSOR_CONTROLNET_SCALE) : null;

function runCommand(cmd, args, { timeout = 600_000 } = {}) {
    return new Promise((resolve, reject) => {
        console.log(`[cmd] ${cmd} ${args.join(' ').slice(0, 200)}...`);
        const proc = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });

        let stdout = '';
        let stderr = '';

        proc.stdout.on('data', (d) => { stdout += d.toString(); });
        proc.stderr.on('data', (d) => { stderr += d.toString(); });

        const timer = setTimeout(() => {
            proc.kill('SIGTERM');
            reject(new Error(`${cmd} timed out after ${timeout / 1000}s`));
        }, timeout);

        proc.on('close', (code) => {
            clearTimeout(timer);
            if (stdout.trim()) console.log(`[${cmd}:stdout] ${stdout.slice(-1000)}`);
            if (stderr.trim()) console.log(`[${cmd}:stderr] ${stderr.slice(-1000)}`);
            if (code === 0) resolve({ stdout, stderr });
            else reject(new Error(`${cmd} exit ${code}: ${stderr.slice(-500)}`));
        });

        proc.on('error', (err) => {
            clearTimeout(timer);
            reject(new Error(`${cmd} spawn error: ${err.message}`));
        });
    });
}

function runDocker(args, opts) {
    return runCommand('docker', args, opts);
}

async function preprocessVideoDocker(jobDirAbs) {
    const containerInput = '/workspace/video.mp4';
    const containerOutput = '/workspace/video_preprocessed.mp4';

    const args = [
        'run', '--rm', '--gpus', 'all',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${PREPROCESSOR_MODEL_CACHE}:/root/.cache/huggingface`,
        PREPROCESSOR_IMAGE,
        'batch',
        '--input', containerInput,
        '--output', containerOutput,
    ];

    if (PREPROCESSOR_PROMPT) args.push('--prompt', PREPROCESSOR_PROMPT);
    if (PREPROCESSOR_NEGATIVE_PROMPT) args.push('--negative-prompt', PREPROCESSOR_NEGATIVE_PROMPT);
    if (PREPROCESSOR_STEPS) args.push('--steps', String(PREPROCESSOR_STEPS));
    if (PREPROCESSOR_STRENGTH) args.push('--strength', String(PREPROCESSOR_STRENGTH));
    if (PREPROCESSOR_GUIDANCE_SCALE) args.push('--guidance-scale', String(PREPROCESSOR_GUIDANCE_SCALE));
    if (PREPROCESSOR_CONTROLNET_SCALE) args.push('--controlnet-scale', String(PREPROCESSOR_CONTROLNET_SCALE));

    await runDocker(args, { timeout: 600_000 });
    console.log('[pipeline] AI silhouette preprocessing complete (docker mode)');
}

function httpPost(url, body) {
    return new Promise((resolve, reject) => {
        const parsed = new URL(url);
        const transport = parsed.protocol === 'https:' ? https : http;
        const data = JSON.stringify(body);

        const req = transport.request(
            {
                hostname: parsed.hostname,
                port: parsed.port,
                path: parsed.pathname,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(data),
                },
                timeout: 600_000,
            },
            (res) => {
                let responseData = '';
                res.on('data', (chunk) => { responseData += chunk; });
                res.on('end', () => {
                    if (res.statusCode >= 200 && res.statusCode < 300) {
                        resolve(JSON.parse(responseData));
                    } else {
                        reject(new Error(`HTTP ${res.statusCode}: ${responseData.slice(0, 500)}`));
                    }
                });
            }
        );
        req.on('error', reject);
        req.on('timeout', () => {
            req.destroy();
            reject(new Error('HTTP request timed out'));
        });
        req.write(data);
        req.end();
    });
}

async function preprocessVideoRemote(jobDirAbs) {
    const body = {
        input_path: '/workspace/video.mp4',
        output_path: '/workspace/video_preprocessed.mp4',
    };
    if (PREPROCESSOR_PROMPT) body.prompt = PREPROCESSOR_PROMPT;
    if (PREPROCESSOR_NEGATIVE_PROMPT) body.negative_prompt = PREPROCESSOR_NEGATIVE_PROMPT;
    if (PREPROCESSOR_STEPS) body.num_inference_steps = PREPROCESSOR_STEPS;
    if (PREPROCESSOR_STRENGTH) body.strength = PREPROCESSOR_STRENGTH;
    if (PREPROCESSOR_GUIDANCE_SCALE) body.guidance_scale = PREPROCESSOR_GUIDANCE_SCALE;
    if (PREPROCESSOR_CONTROLNET_SCALE) body.controlnet_conditioning_scale = PREPROCESSOR_CONTROLNET_SCALE;

    // For remote mode with filesystem access (Tailscale + shared volume),
    // use the process-video endpoint with filesystem paths.
    // If no shared volume, fall back to sending video bytes via the API.
    const url = `${PREPROCESSOR_REMOTE_URL}/api/v1/process-video`;
    const result = await httpPost(url, body);

    // If remote has shared filesystem, the file is already written.
    // Otherwise, we'd need to receive bytes back (not implemented yet — use shared volume).
    console.log(`[pipeline] AI silhouette preprocessing complete (remote mode): ${result.frame_count} frames in ${result.elapsed_seconds}s`);
}

async function preprocessVideoFfmpeg(jobDirAbs) {
    const input = path.join(jobDirAbs, 'video.mp4');
    const output = path.join(jobDirAbs, 'video_preprocessed.mp4');

    // Legacy ffmpeg filter chain: upscale + contrast + sharpen
    await runCommand('ffmpeg', [
        '-y',
        '-i', input,
        '-vf', [
            'scale=iw*2:ih*2:flags=lanczos',
            'eq=contrast=1.3',
            'unsharp=5:5:0.8:5:5:0.0',
        ].join(','),
        '-c:v', 'libx264',
        '-crf', '18',
        '-preset', 'fast',
        '-an',
        output,
    ], { timeout: 120_000 });

    console.log('[pipeline] Preprocessed video saved (ffmpeg fallback mode)');
}

async function preprocessVideo(jobDirAbs) {
    console.log(`[pipeline] Preprocessing video (mode: ${PREPROCESSOR_MODE})`);

    switch (PREPROCESSOR_MODE) {
        case 'docker':
            return preprocessVideoDocker(jobDirAbs);
        case 'remote':
            return preprocessVideoRemote(jobDirAbs);
        case 'ffmpeg':
            return preprocessVideoFfmpeg(jobDirAbs);
        default:
            throw new Error(`Unknown PREPROCESSOR_MODE: ${PREPROCESSOR_MODE}`);
    }
}

// ---------------------------------------------------------------------------
// Direct mode (RunPod — no Docker-in-Docker)
// Tools are installed in the image and called as subprocesses.
// ---------------------------------------------------------------------------

async function runFrankMocapDirect(jobDirAbs) {
    const mocapDir = path.join(jobDirAbs, 'mocap');
    await fs.mkdir(mocapDir, { recursive: true });

    await runCommand('bash', [
        '-c',
        '/opt/frankmocap/entrypoint.sh'
            + ' --input_path ' + path.join(jobDirAbs, 'video_preprocessed.mp4')
            + ' --out_dir ' + mocapDir
            + ' --mode full --save_pred_pkl',
    ], { timeout: 600_000 });

    const renderedDir = await findRenderedDir(mocapDir);
    return renderedDir;
}

async function runPklToNpzDirect(jobDirAbs) {
    await runCommand('python', [
        '/app/scripts/pkl_to_npz.py',
        '--input_dir', path.join(jobDirAbs, 'mocap'),
        '--output', path.join(jobDirAbs, 'animation.npz'),
    ], { timeout: 120_000 });
}

async function runNpzToGlbDirect(jobDirAbs) {
    await runCommand('blender', [
        '-b', '--python', '/app/scripts/npz_to_glb.py', '--',
        '--input', path.join(jobDirAbs, 'animation.npz'),
        '--output', path.join(jobDirAbs, 'result.glb'),
        '--translation_scale_x', '1.4',
        '--translation_scale_y', '1.0',
    ], { timeout: 120_000 });
}

async function runOverlayRenderDirect(jobDirAbs) {
    const overlayDir = path.join(jobDirAbs, 'overlay');
    await fs.mkdir(overlayDir, { recursive: true });

    let resolution = '360x640';
    try {
        const { stdout } = await runCommand('ffprobe', [
            '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            path.join(jobDirAbs, 'video.mp4'),
        ], { timeout: 10_000 });
        const [w, h] = stdout.trim().split(',').map(Number);
        if (w && h) resolution = `${w}x${h}`;
    } catch (e) {
        console.log(`[pipeline] ffprobe failed, using default resolution: ${e.message}`);
    }

    await runCommand('blender', [
        '-b', '--python', '/app/scripts/render_overlay.py', '--',
        '--input', path.join(jobDirAbs, 'result.glb'),
        '--output_dir', overlayDir + '/',
        '--resolution', resolution,
        '--npz', path.join(jobDirAbs, 'animation.npz'),
        '--translation_scale_x', '1.4',
    ], { timeout: 600_000 });
}

// ---------------------------------------------------------------------------
// Docker mode (local dev)
// ---------------------------------------------------------------------------

async function runFrankMocap(jobDirAbs) {
    const mocapDir = path.join(jobDirAbs, 'mocap');
    await fs.mkdir(mocapDir, { recursive: true });

    // Runtime hotfixes for full mode:
    // 1. Ensure hand_object_detector/model symlink exists (points to lib/model)
    // 2. Copy _C.so from build dir to lib/model (setup.py compiles but may not install globally)
    // 3. Remove global model/datasets packages if present (they shadow local ones)
    // 4. Reinstall correct pycocotools for detectron2 compatibility
    const hotfix = [
        'ln -sf /opt/frankmocap/detectors/hand_object_detector/lib/model',
        '  /opt/frankmocap/detectors/hand_object_detector/model 2>/dev/null;',
        'cp /opt/frankmocap/detectors/hand_object_detector/lib/build/lib.linux-x86_64-cpython-310/model/_C.cpython-310-x86_64-linux-gnu.so',
        '  /opt/frankmocap/detectors/hand_object_detector/lib/model/ 2>/dev/null;',
        'cp /usr/local/lib/python3.10/dist-packages/model/_C.cpython-310-x86_64-linux-gnu.so',
        '  /opt/frankmocap/detectors/hand_object_detector/lib/model/ 2>/dev/null;',
        'rm -rf /usr/local/lib/python3.10/dist-packages/model/',
        '  /usr/local/lib/python3.10/dist-packages/datasets/;',
        'pip install -q easydict 2>/dev/null;',
        'pip install --force-reinstall -q pycocotools 2>/dev/null;',
    ].join(' ');

    // Mount fork source files for development (override container's baked-in code)
    const FORK_DIR = path.join(PROJECT_ROOT, '..', 'frankmocap_fork');

    await runDocker([
        'run', '--rm', '--gpus', 'all',
        '--entrypoint', 'bash',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${SMPL_DIR}:/opt/frankmocap/extra_data/smpl`,
        '-v', `${FORK_DIR}/handmocap/hand_bbox_detector.py:/opt/frankmocap/handmocap/hand_bbox_detector.py:ro`,
        '-v', `${FORK_DIR}/handmocap/hand_mocap_api.py:/opt/frankmocap/handmocap/hand_mocap_api.py:ro`,
        '-v', `${FORK_DIR}/bodymocap/body_mocap_api.py:/opt/frankmocap/bodymocap/body_mocap_api.py:ro`,
        '-v', `${FORK_DIR}/demo/demo_frankmocap.py:/opt/frankmocap/demo/demo_frankmocap.py:ro`,
        '-v', `${FORK_DIR}/integration/copy_and_paste.py:/opt/frankmocap/integration/copy_and_paste.py:ro`,
        'frankmocap-gpu',
        '-c', `${hotfix} /opt/frankmocap/entrypoint.sh --input_path /workspace/video_preprocessed.mp4 --out_dir /workspace/mocap --mode full --save_pred_pkl`,
    ], { timeout: 600_000 });

    // Find where rendered frames ended up (FrankMocap nests under mocap/<video_name>/)
    const renderedDir = await findRenderedDir(mocapDir);
    return renderedDir;
}

async function findRenderedDir(baseDir) {
    const files = await fs.readdir(baseDir);

    if (files.includes('rendered')) {
        const sub = path.join(baseDir, 'rendered');
        const stat = await fs.stat(sub);
        if (stat.isDirectory()) return sub;
    }

    for (const f of files) {
        const sub = path.join(baseDir, f);
        const stat = await fs.stat(sub);
        if (stat.isDirectory()) {
            const result = await findRenderedDir(sub);
            if (result) return result;
        }
    }
    return null;
}

async function stitchFrames(renderedDir, outputPath, fps = 30) {
    await runCommand('ffmpeg', [
        '-y',
        '-r', String(fps),
        '-i', path.join(renderedDir, '%05d.jpg'),
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-crf', '23',
        '-preset', 'fast',
        outputPath,
    ], { timeout: 60_000 });
}

async function runPklToNpz(jobDirAbs) {
    const pklToNpzScript = path.join(PROJECT_ROOT, 'frankmocap', 'pkl_to_npz.py');

    await runDocker([
        'run', '--rm', '--gpus', 'all',
        '--entrypoint', 'python',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${SMPL_DIR}:/opt/frankmocap/extra_data/smpl`,
        '-v', `${pklToNpzScript}:/workspace/pkl_to_npz.py:ro`,
        'frankmocap-gpu',
        '/workspace/pkl_to_npz.py',
        '--input_dir', '/workspace/mocap',
        '--output', '/workspace/animation.npz',
    ], { timeout: 120_000 });
}

async function runNpzToGlb(jobDirAbs) {
    const npzToGlbScript = path.join(PROJECT_ROOT, 'npz_to_glb.py');

    // Use Blender passthrough mode (-b --python ... --) instead of --script
    // because the entrypoint's --script mode has a $@ bug that leaks the
    // script name into Blender's -- args
    await runDocker([
        'run', '--rm',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${npzToGlbScript}:/workspace/npz_to_glb.py:ro`,
        'blender-headless',
        '-b', '--python', '/workspace/npz_to_glb.py', '--',
        '--input', '/workspace/animation.npz',
        '--output', '/workspace/result.glb',
        '--translation_scale_x', '1.4',
        '--translation_scale_y', '1.0',
    ], { timeout: 120_000 });
}

async function runOverlayRender(jobDirAbs) {
    const renderScript = path.join(PROJECT_ROOT, 'render_overlay.py');
    const overlayDir = path.join(jobDirAbs, 'overlay');
    await fs.mkdir(overlayDir, { recursive: true });

    // Get source video resolution for matching overlay size
    let resolution = '360x640'; // default portrait
    try {
        const { stdout } = await runCommand('ffprobe', [
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            path.join(jobDirAbs, 'video.mp4'),
        ], { timeout: 10_000 });
        const [w, h] = stdout.trim().split(',').map(Number);
        if (w && h) {
            // Overlay matches source video resolution
            resolution = `${w}x${h}`;
        }
    } catch (e) {
        console.log(`[pipeline] ffprobe failed, using default resolution: ${e.message}`);
    }

    await runDocker([
        'run', '--rm',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${renderScript}:/workspace/render_overlay.py:ro`,
        'blender-headless',
        '-b', '--python', '/workspace/render_overlay.py', '--',
        '--input', '/workspace/result.glb',
        '--output_dir', '/workspace/overlay/',
        '--resolution', resolution,
        '--npz', '/workspace/animation.npz',
        '--translation_scale_x', '1.4',
    ], { timeout: 600_000 });
}

async function buildComparisonVideo(jobDirAbs) {
    // Find FrankMocap rendered frames
    const mocapDir = path.join(jobDirAbs, 'mocap');
    const renderedDir = await findRenderedDir(mocapDir);
    if (!renderedDir) {
        console.log('[pipeline] No rendered dir found, skipping comparison video');
        return;
    }

    const overlayDir = path.join(jobDirAbs, 'overlay');
    const outputPath = path.join(jobDirAbs, 'comparison.mp4');

    // Get FrankMocap fps from rendered frame count + video duration
    // Default to 30fps (standard FrankMocap output)
    const frankFps = 30;

    // Our overlay renders at Blender's default 24fps
    const overlayFps = 24;

    // Triple view: [Source | FrankMocap overlay | Our Blender overlay]
    await runCommand('ffmpeg', [
        '-y',
        '-framerate', String(frankFps),
        '-i', path.join(renderedDir, '%05d.jpg'),
        '-framerate', String(overlayFps),
        '-i', path.join(overlayDir, 'frame_%04d.png'),
        '-filter_complex',
        [
            `[0:v]fps=${frankFps},split=2[frank_a][frank_b]`,
            `[1:v]fps=${frankFps}[ours]`,
            `[frank_a]crop=iw/2:ih:0:0,split=2[src1][src2]`,
            `[frank_b]crop=iw/2:ih:iw/2:0[mocap]`,
            `[src2][ours]overlay=0:0:format=auto[blender]`,
            `[src1][mocap][blender]hstack=inputs=3[stacked]`,
            `[stacked]drawtext=text='F%{frame_num}':x=10:y=10:fontsize=24:fontcolor=white:borderw=2:bordercolor=black[out]`,
        ].join(';'),
        '-map', '[out]',
        '-c:v', 'libx264',
        '-crf', '18',
        '-preset', 'fast',
        '-pix_fmt', 'yuv420p',
        '-t', '60',
        outputPath,
    ], { timeout: 120_000 });
}

async function runFullPipeline(jobDirAbs, onStatus) {
    const direct = PIPELINE_MODE === 'direct';
    console.log(`[pipeline] Running in ${direct ? 'direct' : 'docker'} mode`);

    // Step 1a: Preprocess video — AI silhouette or legacy ffmpeg
    onStatus('preprocessing');
    await preprocessVideo(jobDirAbs);

    // Step 1b: FrankMocap — extract mocap from preprocessed video
    onStatus('extracting');
    if (direct) {
        await runFrankMocapDirect(jobDirAbs);
    } else {
        await runFrankMocap(jobDirAbs);
    }

    // Step 2: PKL → NPZ — convert rotations to quaternions + SMPL data
    onStatus('converting');
    if (direct) {
        await runPklToNpzDirect(jobDirAbs);
    } else {
        await runPklToNpz(jobDirAbs);
    }

    // Step 3: NPZ → GLB — build skinned animated avatar
    onStatus('animating');
    if (direct) {
        await runNpzToGlbDirect(jobDirAbs);
    } else {
        await runNpzToGlb(jobDirAbs);
    }

    // Step 4: Render overlay frames (Blender)
    onStatus('rendering');
    try {
        if (direct) {
            await runOverlayRenderDirect(jobDirAbs);
        } else {
            await runOverlayRender(jobDirAbs);
        }
    } catch (e) {
        console.log(`[pipeline] Overlay render failed (non-fatal): ${e.message}`);
    }

    // Step 5: Stitch individual video outputs (non-fatal)
    onStatus('compositing');
    try {
        const mocapDir = path.join(jobDirAbs, 'mocap');
        const renderedDir = await findRenderedDir(mocapDir);
        if (renderedDir) {
            await stitchFrames(renderedDir, path.join(jobDirAbs, 'frankmocap.mp4'), 30);
        }
    } catch (e) {
        console.log(`[pipeline] FrankMocap stitch failed (non-fatal): ${e.message}`);
    }

    try {
        const overlayDir = path.join(jobDirAbs, 'overlay');
        const files = await fs.readdir(overlayDir).catch(() => []);
        if (files.length > 0) {
            await runCommand('ffmpeg', [
                '-y', '-r', '24',
                '-i', path.join(overlayDir, 'frame_%04d.png'),
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-crf', '23', '-preset', 'fast',
                path.join(jobDirAbs, 'overlay.mp4'),
            ], { timeout: 60_000 });
        }
    } catch (e) {
        console.log(`[pipeline] Overlay stitch failed (non-fatal): ${e.message}`);
    }

    // Step 6: Build triple comparison video
    try {
        await buildComparisonVideo(jobDirAbs);
    } catch (e) {
        console.log(`[pipeline] Comparison video failed (non-fatal): ${e.message}`);
    }

    return path.join(jobDirAbs, 'result.glb');
}

module.exports = { runFullPipeline };
