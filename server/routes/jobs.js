const express = require('express');
const path = require('path');
const fs = require('fs');
const jobManager = require('../services/job-manager');
const { downloadVideo } = require('../services/youtube');
const { runFullPipeline } = require('../services/pipeline');

const router = express.Router();

// POST /api/jobs — submit a YouTube URL
router.post('/', async (req, res) => {
    const { url } = req.body;
    if (!url || typeof url !== 'string') {
        return res.status(400).json({ error: 'Missing or invalid url' });
    }

    // Basic YouTube URL validation
    const ytRegex = /^https?:\/\/(www\.)?(youtube\.com\/(watch\?v=|shorts\/)|youtu\.be\/)/;
    if (!ytRegex.test(url)) {
        return res.status(400).json({ error: 'Invalid YouTube URL' });
    }

    const job = jobManager.createJob(url);
    res.status(201).json(job);

    // Run pipeline async (don't await in request handler)
    runPipeline(job).catch(err => {
        console.error(`[${job.id}] Pipeline error:`, err.message);
    });
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

// GET /api/jobs/:id/result — serve the mocap render video
router.get('/:id/result', (req, res) => {
    const job = jobManager.getJob(req.params.id);
    if (!job) return res.status(404).json({ error: 'Job not found' });
    if (job.status !== 'complete') {
        return res.status(409).json({ error: 'Job not complete', status: job.status });
    }

    const videoPath = path.join(jobManager.jobDir(job.id), 'mocap_render.mp4');
    // Fallback to result.glb for old jobs
    const glbPath = path.join(jobManager.jobDir(job.id), 'result.glb');

    if (fs.existsSync(videoPath)) {
        res.setHeader('Content-Type', 'video/mp4');
        res.setHeader('Content-Disposition', `inline; filename="${job.id}_mocap.mp4"`);
        fs.createReadStream(videoPath).pipe(res);
    } else if (fs.existsSync(glbPath)) {
        res.setHeader('Content-Type', 'model/gltf-binary');
        res.setHeader('Content-Disposition', `inline; filename="${job.id}.glb"`);
        fs.createReadStream(glbPath).pipe(res);
    } else {
        return res.status(404).json({ error: 'Result file not found' });
    }
});

async function runPipeline(job) {
    try {
        const dir = await jobManager.ensureJobDir(job.id);

        // Step 1: Download video
        jobManager.updateJob(job.id, { status: 'downloading', progress: 10 });
        await downloadVideo(job.url, dir);
        jobManager.updateJob(job.id, { progress: 25 });

        // Step 2: FrankMocap → rendered frames → encode video
        await runFullPipeline(dir, (status) => {
            const progressMap = { extracting: 40, encoding: 85 };
            jobManager.updateJob(job.id, {
                status,
                progress: progressMap[status] || 50,
            });
        });

        const resultPath = path.join(dir, 'mocap_render.mp4');
        if (!fs.existsSync(resultPath)) {
            throw new Error('Pipeline completed but mocap_render.mp4 not found');
        }

        jobManager.updateJob(job.id, { status: 'complete', progress: 100 });
        console.log(`[${job.id}] Pipeline complete`);

    } catch (err) {
        console.error(`[${job.id}] Pipeline failed:`, err.message);
        jobManager.failJob(job.id, err.message);
    }
}

module.exports = router;
