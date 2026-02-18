const express = require('express');
const path = require('path');
const fs = require('fs');
const multer = require('multer');
const jobManager = require('../services/job-manager');
const { downloadVideo, downloadDirectVideo, isYouTubeUrl, isVideoUrl } = require('../services/youtube');
const { runFullPipeline } = require('../services/pipeline');

const router = express.Router();

// Multer config — store uploaded video in temp, we'll move it to the job dir
const upload = multer({ dest: '/tmp', limits: { fileSize: 500 * 1024 * 1024 } });

// POST /api/jobs — submit a video URL (YouTube or direct link)
router.post('/', async (req, res) => {
    const { url } = req.body;
    if (!url || typeof url !== 'string') {
        return res.status(400).json({ error: 'Missing or invalid url' });
    }

    try {
        new URL(url);
    } catch {
        return res.status(400).json({ error: 'Invalid URL' });
    }

    if (!isYouTubeUrl(url)) {
        // Check if the URL points to a video by doing a HEAD request
        try {
            const head = await fetch(url, { method: 'HEAD', signal: AbortSignal.timeout(10000) });
            const contentType = head.headers.get('content-type') || '';
            if (!contentType.startsWith('video/')) {
                return res.status(400).json({ error: `URL must be a YouTube link or point to a video file (got ${contentType || 'unknown'})` });
            }
        } catch (e) {
            // If HEAD fails, check by extension as fallback
            if (!isVideoUrl(url)) {
                return res.status(400).json({ error: 'Could not verify URL is a video. Use a YouTube link or a direct video file URL.' });
            }
        }
    }

    const job = jobManager.createJob(url);
    res.status(201).json(job);

    // Run pipeline async (don't await in request handler)
    runPipeline(job).catch(err => {
        console.error(`[${job.id}] Pipeline error:`, err.message);
    });
});

// POST /api/jobs/upload — submit a video file
router.post('/upload', upload.single('video'), async (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: 'No video file uploaded' });
    }

    const label = req.file.originalname || 'uploaded video';
    const job = jobManager.createJob(`[upload] ${label}`);
    res.status(201).json(job);

    // Move file to job dir and run pipeline (skip download step)
    (async () => {
        try {
            const dir = await jobManager.ensureJobDir(job.id);
            const videoPath = path.join(dir, 'video.mp4');
            await fs.promises.rename(req.file.path, videoPath);

            jobManager.updateJob(job.id, { status: 'extracting', progress: 25 });

            await runFullPipeline(dir, (status) => {
                const progressMap = {
                    extracting: 30,
                    converting: 50,
                    animating: 65,
                    rendering: 80,
                    compositing: 90,
                };
                jobManager.updateJob(job.id, {
                    status,
                    progress: progressMap[status] || 50,
                });
            });

            const resultPath = path.join(dir, 'result.glb');
            if (!fs.existsSync(resultPath)) {
                throw new Error('Pipeline completed but result.glb not found');
            }

            jobManager.updateJob(job.id, { status: 'complete', progress: 100 });
            console.log(`[${job.id}] Upload pipeline complete`);

            // Upload results to R2
            uploadResultsToR2(job.id, dir).catch(err => {
                console.warn(`[${job.id}] R2 upload failed:`, err.message);
            });
        } catch (err) {
            console.error(`[${job.id}] Upload pipeline failed:`, err.message);
            jobManager.failJob(job.id, err.message);
            // Clean up temp file if rename failed
            fs.promises.unlink(req.file.path).catch(() => {});
        }
    })();
});

// GET /api/jobs — list recent jobs
router.get('/', (_req, res) => {
    res.json(jobManager.listJobs());
});

// GET /api/jobs/:id — job status
router.get('/:id', (req, res) => {
    const job = jobManager.getJob(req.params.id);
    if (!job) return res.status(404).json({ error: 'Job not found' });
    res.json(job);
});

// GET /api/jobs/:id/result — serve the animated GLB (or fallback to mp4)
router.get('/:id/result', (req, res) => {
    const job = jobManager.getJob(req.params.id);
    if (!job) return res.status(404).json({ error: 'Job not found' });
    if (job.status !== 'complete') {
        return res.status(409).json({ error: 'Job not complete', status: job.status });
    }

    const jobDir = jobManager.jobDir(job.id);
    const glbPath = path.join(jobDir, 'result.glb');
    const videoPath = path.join(jobDir, 'mocap_render.mp4');

    if (fs.existsSync(glbPath)) {
        res.setHeader('Content-Type', 'model/gltf-binary');
        res.setHeader('Content-Disposition', `inline; filename="${job.id}.glb"`);
        res.setHeader('Cache-Control', 'no-store');
        fs.createReadStream(glbPath).pipe(res);
    } else if (fs.existsSync(videoPath)) {
        // Fallback for old jobs that only have video
        res.setHeader('Content-Type', 'video/mp4');
        res.setHeader('Content-Disposition', `inline; filename="${job.id}_mocap.mp4"`);
        res.setHeader('Cache-Control', 'no-store');
        fs.createReadStream(videoPath).pipe(res);
    } else {
        return res.status(404).json({ error: 'Result file not found' });
    }
});

// GET /api/jobs/:id/comparison — serve the quad comparison video
router.get('/:id/comparison', (req, res) => {
    const job = jobManager.getJob(req.params.id);
    if (!job) return res.status(404).json({ error: 'Job not found' });

    const jobDir = jobManager.jobDir(job.id);
    const compPath = path.join(jobDir, 'comparison.mp4');

    if (!fs.existsSync(compPath)) {
        return res.status(404).json({ error: 'Comparison video not found' });
    }

    const stat = fs.statSync(compPath);
    const range = req.headers.range;

    res.setHeader('Cache-Control', 'no-store');

    if (range) {
        const parts = range.replace(/bytes=/, '').split('-');
        const start = parseInt(parts[0], 10);
        const end = parts[1] ? parseInt(parts[1], 10) : stat.size - 1;
        res.writeHead(206, {
            'Content-Range': `bytes ${start}-${end}/${stat.size}`,
            'Accept-Ranges': 'bytes',
            'Content-Length': end - start + 1,
            'Content-Type': 'video/mp4',
            'Cache-Control': 'no-store',
        });
        fs.createReadStream(compPath, { start, end }).pipe(res);
    } else {
        res.setHeader('Content-Type', 'video/mp4');
        res.setHeader('Content-Length', stat.size);
        fs.createReadStream(compPath).pipe(res);
    }
});

// GET /api/jobs/:id/video/:type — serve pipeline video outputs
const VIDEO_MAP = {
    original: 'video.mp4',
    preprocessed: 'video_preprocessed.mp4',
    frankmocap: 'frankmocap.mp4',
    overlay: 'overlay.mp4',
    comparison: 'comparison.mp4',
};

router.get('/:id/video/:type', (req, res) => {
    const job = jobManager.getJob(req.params.id);
    if (!job) return res.status(404).json({ error: 'Job not found' });

    const filename = VIDEO_MAP[req.params.type];
    if (!filename) return res.status(400).json({ error: 'Invalid video type' });

    const filePath = path.join(jobManager.jobDir(job.id), filename);
    if (!fs.existsSync(filePath)) {
        return res.status(404).json({ error: `${req.params.type} video not found` });
    }

    const stat = fs.statSync(filePath);
    const range = req.headers.range;
    res.setHeader('Cache-Control', 'no-store');

    if (range) {
        const parts = range.replace(/bytes=/, '').split('-');
        const start = parseInt(parts[0], 10);
        const end = parts[1] ? parseInt(parts[1], 10) : stat.size - 1;
        res.writeHead(206, {
            'Content-Range': `bytes ${start}-${end}/${stat.size}`,
            'Accept-Ranges': 'bytes',
            'Content-Length': end - start + 1,
            'Content-Type': 'video/mp4',
        });
        fs.createReadStream(filePath, { start, end }).pipe(res);
    } else {
        res.setHeader('Content-Type', 'video/mp4');
        res.setHeader('Content-Length', stat.size);
        fs.createReadStream(filePath).pipe(res);
    }
});

// DELETE /api/jobs/:id — delete a job and its data
router.delete('/:id', async (req, res) => {
    const deleted = await jobManager.deleteJob(req.params.id);
    if (!deleted) return res.status(404).json({ error: 'Job not found' });
    res.json({ ok: true });
});

async function uploadResultsToR2(jobId, jobDir) {
    const uploadUrl = process.env.R2_UPLOAD_URL;
    const uploadKey = process.env.R2_UPLOAD_KEY;
    if (!uploadUrl || !uploadKey) {
        console.log(`[${jobId}] R2 upload skipped (no R2_UPLOAD_URL/R2_UPLOAD_KEY)`);
        return;
    }

    const files = ['result.glb', 'comparison.mp4'];
    for (const filename of files) {
        const filePath = path.join(jobDir, filename);
        if (!fs.existsSync(filePath)) continue;

        try {
            const stat = fs.statSync(filePath);
            const ext = path.extname(filename);
            const contentType = ext === '.glb' ? 'model/gltf-binary' : 'video/mp4';

            const res = await fetch(`${uploadUrl}/api/r2/${jobId}/${filename}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${uploadKey}`,
                    'Content-Type': contentType,
                    'Content-Length': String(stat.size),
                },
                body: fs.createReadStream(filePath),
                duplex: 'half',
            });

            if (res.ok) {
                console.log(`[${jobId}] Uploaded ${filename} to R2 (${(stat.size / 1024 / 1024).toFixed(1)}MB)`);
            } else {
                console.warn(`[${jobId}] R2 upload failed for ${filename}: ${res.status} ${await res.text()}`);
            }
        } catch (err) {
            console.warn(`[${jobId}] R2 upload error for ${filename}:`, err.message);
        }
    }
}

async function runPipeline(job) {
    try {
        const dir = await jobManager.ensureJobDir(job.id);

        // Step 1: Download video
        jobManager.updateJob(job.id, { status: 'downloading', progress: 10 });
        if (isYouTubeUrl(job.url)) {
            await downloadVideo(job.url, dir);
        } else {
            await downloadDirectVideo(job.url, dir);
        }
        jobManager.updateJob(job.id, { progress: 25 });

        // Steps 2-4: FrankMocap → PKL→NPZ → NPZ→GLB
        await runFullPipeline(dir, (status) => {
            const progressMap = {
                extracting: 30,
                converting: 50,
                animating: 65,
                rendering: 80,
                compositing: 90,
            };
            jobManager.updateJob(job.id, {
                status,
                progress: progressMap[status] || 50,
            });
        });

        const resultPath = path.join(dir, 'result.glb');
        if (!fs.existsSync(resultPath)) {
            throw new Error('Pipeline completed but result.glb not found');
        }

        jobManager.updateJob(job.id, { status: 'complete', progress: 100 });
        console.log(`[${job.id}] Pipeline complete`);

        // Upload results to R2 for serving without the pod
        uploadResultsToR2(job.id, dir).catch(err => {
            console.warn(`[${job.id}] R2 upload failed:`, err.message);
        });

    } catch (err) {
        console.error(`[${job.id}] Pipeline failed:`, err.message);
        jobManager.failJob(job.id, err.message);
    }
}

module.exports = router;
