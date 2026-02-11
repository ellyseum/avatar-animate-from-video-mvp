const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs').promises;

const PROJECT_ROOT = path.join(__dirname, '..', '..');
const SMPL_DIR = path.join(PROJECT_ROOT, 'smpl');

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

async function preprocessVideo(jobDirAbs) {
    const input = path.join(jobDirAbs, 'video.mp4');
    const output = path.join(jobDirAbs, 'video_preprocessed.mp4');

    // Upscale 2x (lanczos) + CLAHE contrast enhancement + unsharp mask
    // Gives FrankMocap's hand detector 4x more pixels and better skin/bg separation
    await runCommand('ffmpeg', [
        '-y',
        '-i', input,
        '-vf', [
            'scale=iw*2:ih*2:flags=lanczos',   // 2x upscale for bigger hand regions
            'eq=contrast=1.3',                   // boost contrast for skin/background
            'unsharp=5:5:0.8:5:5:0.0',          // sharpen edges for feature detection
        ].join(','),
        '-c:v', 'libx264',
        '-crf', '18',
        '-preset', 'fast',
        '-an',
        output,
    ], { timeout: 120_000 });

    console.log('[pipeline] Preprocessed video saved to video_preprocessed.mp4');
}

async function runFrankMocap(jobDirAbs) {
    const mocapDir = path.join(jobDirAbs, 'mocap');
    await fs.mkdir(mocapDir, { recursive: true });

    // Runtime hotfixes for full mode (until Docker image is rebuilt):
    // 1. hand_object_detector's setup.py installed conflicting global packages
    //    (datasets, model, pycocotools) that shadow local/detectron2 versions
    // 2. Copy _C.so to local model dir, remove global model/datasets packages
    // 3. Reinstall correct pycocotools for detectron2 compatibility
    const hotfix = [
        'cp /usr/local/lib/python3.10/dist-packages/model/_C.cpython-310-x86_64-linux-gnu.so',
        '  /opt/frankmocap/detectors/hand_object_detector/lib/model/ 2>/dev/null;',
        'rm -rf /usr/local/lib/python3.10/dist-packages/model/',
        '  /usr/local/lib/python3.10/dist-packages/datasets/;',
        'pip install --force-reinstall -q pycocotools 2>/dev/null;',
    ].join(' ');

    await runDocker([
        'run', '--rm', '--gpus', 'all',
        '--entrypoint', 'bash',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${SMPL_DIR}:/opt/frankmocap/extra_data/smpl`,
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
    // Step 1a: Preprocess video — upscale + enhance for better hand detection
    onStatus('extracting');
    await preprocessVideo(jobDirAbs);

    // Step 1b: FrankMocap — extract mocap from preprocessed video
    await runFrankMocap(jobDirAbs);

    // Step 2: PKL → NPZ — convert rotations to quaternions + SMPL data
    onStatus('converting');
    await runPklToNpz(jobDirAbs);

    // Step 3: NPZ → GLB — build skinned animated avatar
    onStatus('animating');
    await runNpzToGlb(jobDirAbs);

    // Step 4: Render overlay frames (Blender)
    onStatus('rendering');
    try {
        await runOverlayRender(jobDirAbs);
    } catch (e) {
        console.log(`[pipeline] Overlay render failed (non-fatal): ${e.message}`);
    }

    // Step 5: Build triple comparison video
    onStatus('compositing');
    try {
        await buildComparisonVideo(jobDirAbs);
    } catch (e) {
        console.log(`[pipeline] Comparison video failed (non-fatal): ${e.message}`);
    }

    return path.join(jobDirAbs, 'result.glb');
}

module.exports = { runFullPipeline };
