const express = require('express');
const cors = require('cors');
const path = require('path');
const jobsRouter = require('./routes/jobs');
const { loadPersistedJobs } = require('./services/job-manager');

const PORT = process.env.PORT || 3001;
const app = express();

app.use(cors());
app.use(express.json());

// API routes
app.use('/api/jobs', jobsRouter);

// Serve React frontend in production
const webDist = path.join(__dirname, '..', 'web', 'dist');
app.use(express.static(webDist));
// Express v5 uses named params — catch-all for SPA routing
app.get('/{*path}', (_req, res) => {
    res.sendFile(path.join(webDist, 'index.html'));
});

async function start() {
    await loadPersistedJobs();
    const server = app.listen(PORT, () => {
        console.log(`Server running on http://localhost:${PORT}`);
    });

    server.on('error', (err) => {
        console.error(`[server] Error: ${err.message}`);
    });

    server.on('close', () => {
        console.log('[server] Server closed');
    });

    process.on('uncaughtException', (err) => {
        console.error('[server] Uncaught exception:', err);
    });

    process.on('unhandledRejection', (err) => {
        console.error('[server] Unhandled rejection:', err);
    });

    process.on('SIGTERM', () => {
        console.log('[server] SIGTERM received, shutting down');
        server.close();
    });

    process.on('SIGINT', () => {
        console.log('[server] SIGINT received, shutting down');
        server.close();
    });
}

start();
