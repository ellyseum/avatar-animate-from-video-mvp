const { spawn } = require('child_process');
const path = require('path');

const YT_DLP = process.env.YT_DLP_PATH || 'yt-dlp';
const MAX_DURATION = 120; // seconds — cap for MVP

function downloadVideo(url, outputDir) {
    return new Promise((resolve, reject) => {
        const outputPath = path.join(outputDir, 'video.mp4');

        const args = [
            '-f', 'best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]/best',
            '--max-filesize', '100M',
            '--match-filter', `duration <= ${MAX_DURATION}`,
            '-o', outputPath,
            '--no-playlist',
            '--no-overwrites',
            '--js-runtimes', 'node',
            url,
        ];

        console.log(`[yt-dlp] Downloading: ${url}`);
        const proc = spawn(YT_DLP, args, { stdio: ['ignore', 'pipe', 'pipe'] });

        let stdout = '';
        let stderr = '';

        proc.stdout.on('data', (d) => {
            stdout += d.toString();
        });
        proc.stderr.on('data', (d) => {
            stderr += d.toString();
        });

        const timer = setTimeout(() => {
            proc.kill('SIGTERM');
            reject(new Error('yt-dlp download timed out (120s)'));
        }, 120_000);

        proc.on('close', (code) => {
            clearTimeout(timer);
            if (code === 0) {
                console.log(`[yt-dlp] Download complete: ${outputPath}`);
                resolve(outputPath);
            } else {
                const msg = stderr.trim() || stdout.trim() || `Exit code ${code}`;
                reject(new Error(`yt-dlp failed: ${msg}`));
            }
        });

        proc.on('error', (err) => {
            clearTimeout(timer);
            reject(new Error(`Failed to start yt-dlp: ${err.message}`));
        });
    });
}

function downloadDirectVideo(url, outputDir) {
    return new Promise((resolve, reject) => {
        const outputPath = path.join(outputDir, 'video.mp4');

        console.log(`[curl] Downloading direct video: ${url}`);
        const proc = spawn('curl', [
            '-fSL',
            '--max-filesize', String(100 * 1024 * 1024),
            '--max-time', '120',
            '-o', outputPath,
            url,
        ], { stdio: ['ignore', 'pipe', 'pipe'] });

        let stderr = '';
        proc.stderr.on('data', (d) => { stderr += d.toString(); });

        const timer = setTimeout(() => {
            proc.kill('SIGTERM');
            reject(new Error('Direct download timed out (120s)'));
        }, 120_000);

        proc.on('close', (code) => {
            clearTimeout(timer);
            if (code === 0) {
                console.log(`[curl] Download complete: ${outputPath}`);
                resolve(outputPath);
            } else {
                reject(new Error(`Download failed: ${stderr.trim() || `exit ${code}`}`));
            }
        });

        proc.on('error', (err) => {
            clearTimeout(timer);
            reject(new Error(`Failed to start curl: ${err.message}`));
        });
    });
}

const YT_REGEX = /^https?:\/\/(www\.)?(youtube\.com\/(watch\?v=|shorts\/)|youtu\.be\/)/;
const VIDEO_EXT_REGEX = /\.(mp4|webm|mov|avi|mkv|m4v|flv|wmv)(\?|$)/i;

function isYouTubeUrl(url) {
    return YT_REGEX.test(url);
}

function isVideoUrl(url) {
    return VIDEO_EXT_REGEX.test(url);
}

module.exports = { downloadVideo, downloadDirectVideo, isYouTubeUrl, isVideoUrl };
