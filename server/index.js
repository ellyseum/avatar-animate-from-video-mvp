const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const https = require('https');
const { WebSocketServer } = require('ws');
const jobsRouter = require('./routes/jobs');
const { loadPersistedJobs, listJobs, events } = require('./services/job-manager');

const PORT = process.env.PORT || 3001;
const HTTPS_PORT = process.env.HTTPS_PORT || 8080;
const app = express();

app.use(cors());
app.use(express.json());

// API routes
app.use('/api/jobs', jobsRouter);

// Activity heartbeat — Cloudflare cron checks this to decide auto-stop
let lastActivity = Date.now();
app.use((req, _res, next) => {
  if (req.path.startsWith('/api/')) lastActivity = Date.now();
  next();
});
app.get('/api/heartbeat', (_req, res) => {
  res.json({ lastActivity, uptimeSeconds: Math.floor(process.uptime()) });
});

// Debug endpoint — verify image version and environment
app.get('/api/debug', async (_req, res) => {
  const { execSync } = require('child_process');
  const info = {
    pythonpath: process.env.PYTHONPATH || 'NOT SET',
    pipelineMode: process.env.PIPELINE_MODE || 'docker',
    preprocessorMode: process.env.PREPROCESSOR_MODE || 'docker',
    nodeVersion: process.version,
    uptime: Math.floor(process.uptime()),
    memoryMB: Math.floor(process.memoryUsage().rss / 1e6),
    cwd: process.cwd(),
  };
  try {
    info.pythonImports = execSync(
      'python3 -c "from pycocotools.coco import COCO; from model.utils.config import cfg; print(\'OK\')"',
      { timeout: 10000, encoding: 'utf-8' }
    ).trim();
  } catch (e) {
    info.pythonImports = `FAIL: ${e.message.slice(0, 200)}`;
  }
  try {
    info.gpu = execSync(
      'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "no GPU"',
      { timeout: 5000, encoding: 'utf-8' }
    ).trim();
  } catch {
    info.gpu = 'unknown';
  }
  res.json(info);
});

// Serve React frontend in production
const webDist = path.join(__dirname, '..', 'web', 'dist');
app.use(express.static(webDist));
// Express v5 uses named params — catch-all for SPA routing
app.get('/{*path}', (_req, res) => {
    res.sendFile(path.join(webDist, 'index.html'));
});

async function start() {
    await loadPersistedJobs();

    // Track all WS servers for broadcasting
    const wssInstances = [];

    function attachWS(httpServer) {
        const wss = new WebSocketServer({ server: httpServer, path: '/ws' });
        wss.on('connection', (ws) => {
            // Send full job list on connect
            ws.send(JSON.stringify({ type: 'jobs:list', jobs: listJobs() }));
        });
        wssInstances.push(wss);
        return wss;
    }

    function broadcast(msg) {
        const data = JSON.stringify(msg);
        for (const wss of wssInstances) {
            for (const client of wss.clients) {
                if (client.readyState === 1) client.send(data);
            }
        }
    }

    // Wire job-manager events → WS broadcast
    events.on('job:update', (job) => broadcast({ type: 'job:update', job }));
    events.on('job:delete', (id) => broadcast({ type: 'job:delete', id }));

    const server = app.listen(PORT, () => {
        console.log(`Server running on http://localhost:${PORT}`);
    });
    attachWS(server);

    // HTTPS with ellyseum.dev wildcard cert
    const certDir = path.join(require('os').homedir(), '.local/share/certbot/live/ellyseum.dev');
    if (fs.existsSync(certDir)) {
        const httpsServer = https.createServer({
            key: fs.readFileSync(path.join(certDir, 'privkey.pem')),
            cert: fs.readFileSync(path.join(certDir, 'fullchain.pem')),
        }, app);
        httpsServer.listen(HTTPS_PORT, () => {
            console.log(`HTTPS server running on https://horus.ellyseum.dev:${HTTPS_PORT}`);
        });
        attachWS(httpsServer);
    }

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
