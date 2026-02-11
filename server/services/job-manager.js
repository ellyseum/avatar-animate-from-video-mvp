const fs = require('fs').promises;
const path = require('path');
const { v4: uuidv4 } = require('uuid');

const DATA_DIR = path.join(__dirname, '..', '..', 'data', 'jobs');

// In-memory job store (persisted to disk as JSON)
const jobs = new Map();

const JOB_STATES = ['downloading', 'extracting', 'converting', 'animating', 'complete', 'failed'];

async function ensureDataDir() {
    await fs.mkdir(DATA_DIR, { recursive: true });
}

function createJob(url) {
    const id = uuidv4().slice(0, 8);
    const job = {
        id,
        url,
        status: 'downloading',
        progress: 0,
        error: null,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
    };
    jobs.set(id, job);
    persistJob(job);
    return job;
}

function getJob(id) {
    return jobs.get(id) || null;
}

function listJobs() {
    return Array.from(jobs.values())
        .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
        .slice(0, 50);
}

function updateJob(id, updates) {
    const job = jobs.get(id);
    if (!job) return null;
    Object.assign(job, updates, { updatedAt: new Date().toISOString() });
    persistJob(job);
    return job;
}

function failJob(id, error) {
    return updateJob(id, { status: 'failed', error: String(error) });
}

function jobDir(id) {
    return path.join(DATA_DIR, id);
}

async function ensureJobDir(id) {
    const dir = jobDir(id);
    await fs.mkdir(dir, { recursive: true });
    return dir;
}

async function persistJob(job) {
    try {
        const dir = jobDir(job.id);
        await fs.mkdir(dir, { recursive: true });
        await fs.writeFile(
            path.join(dir, 'job.json'),
            JSON.stringify(job, null, 2)
        );
    } catch (e) {
        console.error(`Failed to persist job ${job.id}:`, e.message);
    }
}

async function loadPersistedJobs() {
    await ensureDataDir();
    try {
        const entries = await fs.readdir(DATA_DIR, { withFileTypes: true });
        for (const entry of entries) {
            if (!entry.isDirectory()) continue;
            try {
                const raw = await fs.readFile(
                    path.join(DATA_DIR, entry.name, 'job.json'), 'utf-8'
                );
                const job = JSON.parse(raw);
                jobs.set(job.id, job);
            } catch {
                // Skip invalid job directories
            }
        }
        console.log(`Loaded ${jobs.size} persisted jobs`);
    } catch {
        // No jobs directory yet
    }
}

module.exports = {
    createJob,
    getJob,
    listJobs,
    updateJob,
    failJob,
    jobDir,
    ensureJobDir,
    loadPersistedJobs,
    DATA_DIR,
};
