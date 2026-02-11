const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs').promises;

const PROJECT_ROOT = path.join(__dirname, '..', '..');
const SMPL_DIR = path.join(PROJECT_ROOT, 'smpl');

function runCommand(cmd, args, { timeout = 600_000 } = {}) {
    return new Promise((resolve, reject) => {
        console.log(`[cmd] ${cmd} ${args.join(' ').slice(0, 120)}...`);
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

async function runFrankMocap(jobDirAbs) {
    const mocapDir = path.join(jobDirAbs, 'mocap');
    await fs.mkdir(mocapDir, { recursive: true });

    await runDocker([
        'run', '--rm', '--gpus', 'all',
        '-v', `${jobDirAbs}:/workspace`,
        '-v', `${SMPL_DIR}:/opt/frankmocap/extra_data/smpl`,
        'frankmocap-gpu',
        '--input_path', '/workspace/video.mp4',
        '--out_dir', '/workspace/mocap',
        '--save_pred_pkl',
    ], { timeout: 300_000 });

    // Find where rendered frames ended up (FrankMocap nests under mocap/<video_name>/)
    const renderedDir = await findRenderedDir(mocapDir);
    return renderedDir;
}

async function findRenderedDir(baseDir) {
    const files = await fs.readdir(baseDir);

    // Check if rendered/ is directly here
    if (files.includes('rendered')) {
        const sub = path.join(baseDir, 'rendered');
        const stat = await fs.stat(sub);
        if (stat.isDirectory()) return sub;
    }

    // Check subdirectories
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
    // ffmpeg: stitch numbered JPGs into an mp4
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

async function runFullPipeline(jobDirAbs, onStatus) {
    onStatus('extracting');
    const renderedDir = await runFrankMocap(jobDirAbs);
    if (!renderedDir) throw new Error('FrankMocap produced no rendered frames');

    onStatus('encoding');
    const outputPath = path.join(jobDirAbs, 'mocap_render.mp4');
    await stitchFrames(renderedDir, outputPath);

    return outputPath;
}

module.exports = { runFullPipeline };
