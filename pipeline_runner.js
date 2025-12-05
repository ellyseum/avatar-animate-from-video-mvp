/**
 * Pipeline Runner - Orchestration script for Blender headless microservice
 * 
 * This script manages the execution of auto-rigging and animation retargeting
 * pipelines using the Docker-based Blender microservice.
 * 
 * Features:
 * - Auto-rigging pipeline (mesh → rigged mesh)
 * - Animation retargeting pipeline (rigged mesh + animation → animated mesh)
 * - Combined pipeline (mesh + animation → animated mesh)
 * - Batch processing with configurable concurrency
 * - Job queue to prevent resource overload
 * - Temporary workspace management
 * - Comprehensive error handling and logging
 * 
 * Usage:
 *   node pipeline_runner.js --mesh character.obj --output rigged.glb
 *   node pipeline_runner.js --mesh avatar.glb --animation motion.bvh --output animated.glb
 *   node pipeline_runner.js --batch jobs.json --concurrency 2
 */

const { spawn } = require('child_process');
const fs = require('fs').promises;
const path = require('path');
const os = require('os');
const crypto = require('crypto');

// ============================================================================
// Configuration
// ============================================================================

const DEFAULT_CONFIG = {
    // Docker settings
    dockerImage: 'blender-headless',
    useGpu: true,
    
    // Pipeline settings
    defaultRigType: 'basic',
    defaultFps: 30,
    defaultScale: 1.0,
    
    // Batch processing
    maxConcurrency: 2,
    queueTimeout: 300000, // 5 minutes
    
    // Cleanup
    cleanupOnSuccess: true,
    cleanupOnFailure: false,
    
    // Logging
    logLevel: 'info', // 'debug', 'info', 'warn', 'error'
};

// ============================================================================
// Logger
// ============================================================================

class Logger {
    constructor(level = 'info') {
        this.levels = { debug: 0, info: 1, warn: 2, error: 3 };
        this.level = this.levels[level] || 1;
    }

    _log(level, ...args) {
        if (this.levels[level] >= this.level) {
            const timestamp = new Date().toISOString();
            const prefix = `[${timestamp}] [${level.toUpperCase()}]`;
            console.log(prefix, ...args);
        }
    }

    debug(...args) { this._log('debug', ...args); }
    info(...args) { this._log('info', ...args); }
    warn(...args) { this._log('warn', ...args); }
    error(...args) { this._log('error', ...args); }
}

const logger = new Logger(process.env.LOG_LEVEL || DEFAULT_CONFIG.logLevel);

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Generate a unique job ID
 */
function generateJobId() {
    return crypto.randomBytes(8).toString('hex');
}

/**
 * Create a temporary workspace directory
 */
async function createTempWorkspace(jobId) {
    const tempDir = path.join(os.tmpdir(), `blender-pipeline-${jobId}`);
    await fs.mkdir(tempDir, { recursive: true });
    logger.debug(`Created temp workspace: ${tempDir}`);
    return tempDir;
}

/**
 * Clean up temporary workspace
 */
async function cleanupWorkspace(workspacePath) {
    try {
        await fs.rm(workspacePath, { recursive: true, force: true });
        logger.debug(`Cleaned up workspace: ${workspacePath}`);
    } catch (err) {
        logger.warn(`Failed to cleanup workspace: ${err.message}`);
    }
}

/**
 * Copy file to workspace
 */
async function copyToWorkspace(sourcePath, workspacePath, filename = null) {
    const destFilename = filename || path.basename(sourcePath);
    const destPath = path.join(workspacePath, destFilename);
    await fs.copyFile(sourcePath, destPath);
    logger.debug(`Copied ${sourcePath} → ${destPath}`);
    return destPath;
}

/**
 * Copy file from workspace to output location
 */
async function copyFromWorkspace(workspacePath, filename, outputPath) {
    const sourcePath = path.join(workspacePath, filename);
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await fs.copyFile(sourcePath, outputPath);
    logger.debug(`Copied ${sourcePath} → ${outputPath}`);
    return outputPath;
}

/**
 * Check if file exists
 */
async function fileExists(filePath) {
    try {
        await fs.access(filePath);
        return true;
    } catch {
        return false;
    }
}

/**
 * Get file size in human-readable format
 */
async function getFileSize(filePath) {
    const stats = await fs.stat(filePath);
    const bytes = stats.size;
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    return `${size.toFixed(2)} ${units[unitIndex]}`;
}

// ============================================================================
// Docker Execution
// ============================================================================

/**
 * Execute a Docker command and return the result
 */
function runDockerCommand(args, options = {}) {
    return new Promise((resolve, reject) => {
        const { timeout = 300000, cwd } = options;
        
        logger.debug(`Docker command: docker ${args.join(' ')}`);
        
        const proc = spawn('docker', args, {
            cwd,
            stdio: ['ignore', 'pipe', 'pipe']
        });

        let stdout = '';
        let stderr = '';

        proc.stdout.on('data', (data) => {
            const text = data.toString();
            stdout += text;
            // Stream output in real-time for long-running processes
            text.split('\n').forEach(line => {
                if (line.trim()) logger.debug(`[docker] ${line}`);
            });
        });

        proc.stderr.on('data', (data) => {
            const text = data.toString();
            stderr += text;
            text.split('\n').forEach(line => {
                if (line.trim()) logger.debug(`[docker:err] ${line}`);
            });
        });

        const timer = setTimeout(() => {
            proc.kill('SIGTERM');
            reject(new Error(`Docker command timed out after ${timeout}ms`));
        }, timeout);

        proc.on('close', (code) => {
            clearTimeout(timer);
            if (code === 0) {
                resolve({ stdout, stderr, code });
            } else {
                reject(new Error(`Docker exited with code ${code}: ${stderr}`));
            }
        });

        proc.on('error', (err) => {
            clearTimeout(timer);
            reject(new Error(`Failed to start Docker: ${err.message}`));
        });
    });
}

/**
 * Build Docker run arguments
 */
function buildDockerArgs(workspacePath, blenderArgs, config) {
    const args = ['run', '--rm'];
    
    // GPU support
    if (config.useGpu) {
        args.push('--gpus', 'all');
    }
    
    // Mount workspace
    args.push('-v', `${workspacePath}:/workspace`);
    
    // Image name
    args.push(config.dockerImage);
    
    // Blender arguments
    args.push(...blenderArgs);
    
    return args;
}

// ============================================================================
// Pipeline Operations
// ============================================================================

/**
 * Run the auto-rigging pipeline
 */
async function runAutoRig(options) {
    const {
        meshPath,
        outputPath,
        rigType = DEFAULT_CONFIG.defaultRigType,
        scale = DEFAULT_CONFIG.defaultScale,
        cleanup = true,
        applyTransforms = true,
        config = DEFAULT_CONFIG,
    } = options;

    const jobId = generateJobId();
    const workspacePath = await createTempWorkspace(jobId);
    
    logger.info(`[${jobId}] Starting auto-rig pipeline`);
    logger.info(`[${jobId}] Input: ${meshPath}`);
    logger.info(`[${jobId}] Output: ${outputPath}`);

    try {
        // Validate input
        if (!await fileExists(meshPath)) {
            throw new Error(`Input mesh not found: ${meshPath}`);
        }

        // Copy mesh to workspace
        const meshFilename = path.basename(meshPath);
        await copyToWorkspace(meshPath, workspacePath, meshFilename);

        // Determine output filename
        const outputFilename = `rigged_${path.basename(outputPath)}`;

        // Build Blender arguments
        const blenderArgs = [
            '-b',
            '--python', '/workspace/auto_rig_and_export.py',
            '--',
            '--input', `/workspace/${meshFilename}`,
            '--output', `/workspace/${outputFilename}`,
            '--rig-type', rigType,
            '--scale', scale.toString(),
        ];

        if (cleanup) blenderArgs.push('--cleanup');
        else blenderArgs.push('--no-cleanup');
        
        if (applyTransforms) blenderArgs.push('--apply-transforms');
        else blenderArgs.push('--no-apply-transforms');

        blenderArgs.push('--log-file', '/workspace/rig.log');

        // Run Docker
        const dockerArgs = buildDockerArgs(workspacePath, blenderArgs, config);
        await runDockerCommand(dockerArgs, { timeout: config.queueTimeout });

        // Check output
        const outputInWorkspace = path.join(workspacePath, outputFilename);
        if (!await fileExists(outputInWorkspace)) {
            // Try to get log for debugging
            const logPath = path.join(workspacePath, 'rig.log');
            if (await fileExists(logPath)) {
                const log = await fs.readFile(logPath, 'utf-8');
                logger.error(`[${jobId}] Blender log:\n${log}`);
            }
            throw new Error('Auto-rig output file not created');
        }

        // Copy output to final destination
        await copyFromWorkspace(workspacePath, outputFilename, outputPath);
        const fileSize = await getFileSize(outputPath);

        logger.info(`[${jobId}] Auto-rig completed successfully`);
        logger.info(`[${jobId}] Output: ${outputPath} (${fileSize})`);

        // Cleanup on success
        if (config.cleanupOnSuccess) {
            await cleanupWorkspace(workspacePath);
        }

        return {
            success: true,
            jobId,
            outputPath,
            fileSize,
        };

    } catch (error) {
        logger.error(`[${jobId}] Auto-rig failed: ${error.message}`);
        
        // Cleanup on failure (if configured)
        if (config.cleanupOnFailure) {
            await cleanupWorkspace(workspacePath);
        } else {
            logger.info(`[${jobId}] Workspace preserved for debugging: ${workspacePath}`);
        }

        return {
            success: false,
            jobId,
            error: error.message,
            workspacePath,
        };
    }
}

/**
 * Run the animation retargeting pipeline
 */
async function runRetarget(options) {
    const {
        targetPath,
        animationPath,
        outputPath,
        mappingPath = null,
        startFrame = null,
        endFrame = null,
        fps = DEFAULT_CONFIG.defaultFps,
        scale = DEFAULT_CONFIG.defaultScale,
        rootMotion = true,
        config = DEFAULT_CONFIG,
    } = options;

    const jobId = generateJobId();
    const workspacePath = await createTempWorkspace(jobId);
    
    logger.info(`[${jobId}] Starting retarget pipeline`);
    logger.info(`[${jobId}] Target: ${targetPath}`);
    logger.info(`[${jobId}] Animation: ${animationPath}`);
    logger.info(`[${jobId}] Output: ${outputPath}`);

    try {
        // Validate inputs
        if (!await fileExists(targetPath)) {
            throw new Error(`Target mesh not found: ${targetPath}`);
        }
        if (!await fileExists(animationPath)) {
            throw new Error(`Animation file not found: ${animationPath}`);
        }

        // Copy files to workspace
        const targetFilename = path.basename(targetPath);
        const animFilename = path.basename(animationPath);
        await copyToWorkspace(targetPath, workspacePath, targetFilename);
        await copyToWorkspace(animationPath, workspacePath, animFilename);

        // Copy mapping file if provided
        let mappingFilename = null;
        if (mappingPath && await fileExists(mappingPath)) {
            mappingFilename = path.basename(mappingPath);
            await copyToWorkspace(mappingPath, workspacePath, mappingFilename);
        }

        // Determine output filename
        const outputFilename = `animated_${path.basename(outputPath)}`;

        // Build Blender arguments
        const blenderArgs = [
            '-b',
            '--python', '/workspace/retarget_and_export.py',
            '--',
            '--target', `/workspace/${targetFilename}`,
            '--source', `/workspace/${animFilename}`,
            '--output', `/workspace/${outputFilename}`,
            '--fps', fps.toString(),
            '--scale', scale.toString(),
        ];

        if (mappingFilename) {
            blenderArgs.push('--mapping', `/workspace/${mappingFilename}`);
        }

        if (startFrame !== null) {
            blenderArgs.push('--start-frame', startFrame.toString());
        }

        if (endFrame !== null) {
            blenderArgs.push('--end-frame', endFrame.toString());
        }

        if (rootMotion) blenderArgs.push('--root-motion');
        else blenderArgs.push('--no-root-motion');

        blenderArgs.push('--log-file', '/workspace/retarget.log');

        // Run Docker
        const dockerArgs = buildDockerArgs(workspacePath, blenderArgs, config);
        await runDockerCommand(dockerArgs, { timeout: config.queueTimeout });

        // Check output
        const outputInWorkspace = path.join(workspacePath, outputFilename);
        if (!await fileExists(outputInWorkspace)) {
            const logPath = path.join(workspacePath, 'retarget.log');
            if (await fileExists(logPath)) {
                const log = await fs.readFile(logPath, 'utf-8');
                logger.error(`[${jobId}] Blender log:\n${log}`);
            }
            throw new Error('Retarget output file not created');
        }

        // Copy output to final destination
        await copyFromWorkspace(workspacePath, outputFilename, outputPath);
        const fileSize = await getFileSize(outputPath);

        logger.info(`[${jobId}] Retarget completed successfully`);
        logger.info(`[${jobId}] Output: ${outputPath} (${fileSize})`);

        // Cleanup on success
        if (config.cleanupOnSuccess) {
            await cleanupWorkspace(workspacePath);
        }

        return {
            success: true,
            jobId,
            outputPath,
            fileSize,
        };

    } catch (error) {
        logger.error(`[${jobId}] Retarget failed: ${error.message}`);
        
        if (config.cleanupOnFailure) {
            await cleanupWorkspace(workspacePath);
        } else {
            logger.info(`[${jobId}] Workspace preserved for debugging: ${workspacePath}`);
        }

        return {
            success: false,
            jobId,
            error: error.message,
            workspacePath,
        };
    }
}

/**
 * Run combined pipeline: auto-rig + retarget
 */
async function runFullPipeline(options) {
    const {
        meshPath,
        animationPath,
        outputPath,
        rigType = DEFAULT_CONFIG.defaultRigType,
        mappingPath = null,
        fps = DEFAULT_CONFIG.defaultFps,
        scale = DEFAULT_CONFIG.defaultScale,
        rootMotion = true,
        config = DEFAULT_CONFIG,
    } = options;

    const jobId = generateJobId();
    logger.info(`[${jobId}] Starting full pipeline (auto-rig + retarget)`);

    // Create intermediate output path
    const ext = path.extname(outputPath);
    const basename = path.basename(outputPath, ext);
    const dirname = path.dirname(outputPath);
    const riggedPath = path.join(dirname, `${basename}_rigged${ext}`);

    try {
        // Step 1: Auto-rig
        logger.info(`[${jobId}] Step 1/2: Auto-rigging mesh...`);
        const rigResult = await runAutoRig({
            meshPath,
            outputPath: riggedPath,
            rigType,
            scale,
            config: { ...config, cleanupOnSuccess: true },
        });

        if (!rigResult.success) {
            throw new Error(`Auto-rig failed: ${rigResult.error}`);
        }

        // Step 2: Retarget
        logger.info(`[${jobId}] Step 2/2: Retargeting animation...`);
        const retargetResult = await runRetarget({
            targetPath: riggedPath,
            animationPath,
            outputPath,
            mappingPath,
            fps,
            scale: 1.0, // Scale already applied in rig step
            rootMotion,
            config,
        });

        if (!retargetResult.success) {
            throw new Error(`Retarget failed: ${retargetResult.error}`);
        }

        // Clean up intermediate rigged file
        try {
            await fs.unlink(riggedPath);
            logger.debug(`[${jobId}] Cleaned up intermediate file: ${riggedPath}`);
        } catch {
            // Ignore cleanup errors
        }

        logger.info(`[${jobId}] Full pipeline completed successfully`);

        return {
            success: true,
            jobId,
            outputPath,
            fileSize: retargetResult.fileSize,
            steps: {
                rig: rigResult,
                retarget: retargetResult,
            },
        };

    } catch (error) {
        logger.error(`[${jobId}] Full pipeline failed: ${error.message}`);

        return {
            success: false,
            jobId,
            error: error.message,
        };
    }
}

// ============================================================================
// Batch Processing
// ============================================================================

/**
 * Simple job queue with concurrency control
 */
class JobQueue {
    constructor(concurrency = 2) {
        this.concurrency = concurrency;
        this.running = 0;
        this.queue = [];
        this.results = [];
    }

    async add(job) {
        return new Promise((resolve, reject) => {
            this.queue.push({ job, resolve, reject });
            this.processNext();
        });
    }

    async processNext() {
        if (this.running >= this.concurrency || this.queue.length === 0) {
            return;
        }

        this.running++;
        const { job, resolve, reject } = this.queue.shift();

        try {
            const result = await job();
            this.results.push(result);
            resolve(result);
        } catch (error) {
            const errorResult = { success: false, error: error.message };
            this.results.push(errorResult);
            reject(error);
        } finally {
            this.running--;
            this.processNext();
        }
    }

    async waitAll() {
        while (this.running > 0 || this.queue.length > 0) {
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        return this.results;
    }
}

/**
 * Run batch processing from a job configuration
 */
async function runBatch(jobs, options = {}) {
    const {
        concurrency = DEFAULT_CONFIG.maxConcurrency,
        config = DEFAULT_CONFIG,
    } = options;

    logger.info(`Starting batch processing: ${jobs.length} jobs, concurrency: ${concurrency}`);

    const queue = new JobQueue(concurrency);
    const startTime = Date.now();

    // Add all jobs to queue
    const promises = jobs.map((job, index) => {
        return queue.add(async () => {
            logger.info(`Processing job ${index + 1}/${jobs.length}: ${job.type}`);
            
            switch (job.type) {
                case 'auto-rig':
                    return runAutoRig({ ...job, config });
                case 'retarget':
                    return runRetarget({ ...job, config });
                case 'full':
                    return runFullPipeline({ ...job, config });
                default:
                    throw new Error(`Unknown job type: ${job.type}`);
            }
        });
    });

    // Wait for all jobs
    const results = await Promise.allSettled(promises);
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

    // Summarize results
    const successful = results.filter(r => r.status === 'fulfilled' && r.value.success).length;
    const failed = results.length - successful;

    logger.info(`Batch complete: ${successful} succeeded, ${failed} failed (${elapsed}s)`);

    return {
        total: jobs.length,
        successful,
        failed,
        elapsed: `${elapsed}s`,
        results: results.map((r, i) => ({
            job: jobs[i],
            ...(r.status === 'fulfilled' ? r.value : { success: false, error: r.reason?.message }),
        })),
    };
}

// ============================================================================
// CLI Interface
// ============================================================================

function parseArgs() {
    const args = process.argv.slice(2);
    const options = {
        mode: null,
        mesh: null,
        animation: null,
        output: null,
        rigType: DEFAULT_CONFIG.defaultRigType,
        mapping: null,
        fps: DEFAULT_CONFIG.defaultFps,
        scale: DEFAULT_CONFIG.defaultScale,
        rootMotion: true,
        batch: null,
        concurrency: DEFAULT_CONFIG.maxConcurrency,
        gpu: DEFAULT_CONFIG.useGpu,
        image: DEFAULT_CONFIG.dockerImage,
    };

    for (let i = 0; i < args.length; i++) {
        const arg = args[i];
        const next = args[i + 1];

        switch (arg) {
            case '--mesh':
            case '-m':
                options.mesh = next;
                i++;
                break;
            case '--animation':
            case '-a':
                options.animation = next;
                i++;
                break;
            case '--output':
            case '-o':
                options.output = next;
                i++;
                break;
            case '--rig-type':
                options.rigType = next;
                i++;
                break;
            case '--mapping':
                options.mapping = next;
                i++;
                break;
            case '--fps':
                options.fps = parseFloat(next);
                i++;
                break;
            case '--scale':
                options.scale = parseFloat(next);
                i++;
                break;
            case '--no-root-motion':
                options.rootMotion = false;
                break;
            case '--batch':
                options.batch = next;
                i++;
                break;
            case '--concurrency':
                options.concurrency = parseInt(next, 10);
                i++;
                break;
            case '--no-gpu':
                options.gpu = false;
                break;
            case '--image':
                options.image = next;
                i++;
                break;
            case '--help':
            case '-h':
                printHelp();
                process.exit(0);
                break;
        }
    }

    return options;
}

function printHelp() {
    console.log(`
Pipeline Runner - Blender Headless Microservice Orchestrator

Usage:
  node pipeline_runner.js [options]

Options:
  --mesh, -m <path>       Input mesh file (for auto-rig or full pipeline)
  --animation, -a <path>  Animation file (for retarget or full pipeline)
  --output, -o <path>     Output file path (required)
  --rig-type <type>       Rig type: basic, rigify, metarig (default: basic)
  --mapping <path>        Bone mapping JSON file
  --fps <number>          Frames per second (default: 30)
  --scale <number>        Scale factor (default: 1.0)
  --no-root-motion        Disable root motion in animation
  --batch <path>          Batch job configuration JSON file
  --concurrency <n>       Max parallel jobs for batch mode (default: 2)
  --no-gpu                Disable GPU acceleration
  --image <name>          Docker image name (default: blender-headless)
  --help, -h              Show this help

Examples:
  # Auto-rig a mesh
  node pipeline_runner.js --mesh character.obj --output rigged.glb

  # Retarget animation to a rigged mesh
  node pipeline_runner.js --mesh avatar.glb --animation motion.bvh --output animated.glb

  # Full pipeline (mesh with no rig + animation)
  node pipeline_runner.js --mesh raw_mesh.obj --animation dance.bvh --output final.glb

  # Batch processing
  node pipeline_runner.js --batch jobs.json --concurrency 4

Batch Job Format (jobs.json):
  [
    { "type": "auto-rig", "meshPath": "mesh1.obj", "outputPath": "rigged1.glb" },
    { "type": "retarget", "targetPath": "avatar.glb", "animationPath": "walk.bvh", "outputPath": "walk.glb" },
    { "type": "full", "meshPath": "mesh.obj", "animationPath": "dance.bvh", "outputPath": "animated.glb" }
  ]
`);
}

async function main() {
    const options = parseArgs();

    const config = {
        ...DEFAULT_CONFIG,
        useGpu: options.gpu,
        dockerImage: options.image,
    };

    // Batch mode
    if (options.batch) {
        try {
            const batchData = await fs.readFile(options.batch, 'utf-8');
            const jobs = JSON.parse(batchData);
            const result = await runBatch(jobs, { concurrency: options.concurrency, config });
            console.log(JSON.stringify(result, null, 2));
            process.exit(result.failed > 0 ? 1 : 0);
        } catch (error) {
            logger.error(`Batch processing failed: ${error.message}`);
            process.exit(1);
        }
        return;
    }

    // Single job mode
    if (!options.output) {
        logger.error('Output path required. Use --output or -o');
        process.exit(1);
    }

    let result;

    if (options.mesh && options.animation) {
        // Check if mesh is already rigged (has armature) - assume by extension/name
        // For simplicity, we'll check if the mesh file suggests it's rigged
        const meshExt = path.extname(options.mesh).toLowerCase();
        const isLikelyRigged = ['.glb', '.gltf', '.fbx'].includes(meshExt) && 
                               !options.mesh.toLowerCase().includes('raw');
        
        if (isLikelyRigged) {
            // Retarget only
            result = await runRetarget({
                targetPath: options.mesh,
                animationPath: options.animation,
                outputPath: options.output,
                mappingPath: options.mapping,
                fps: options.fps,
                scale: options.scale,
                rootMotion: options.rootMotion,
                config,
            });
        } else {
            // Full pipeline
            result = await runFullPipeline({
                meshPath: options.mesh,
                animationPath: options.animation,
                outputPath: options.output,
                rigType: options.rigType,
                mappingPath: options.mapping,
                fps: options.fps,
                scale: options.scale,
                rootMotion: options.rootMotion,
                config,
            });
        }
    } else if (options.mesh) {
        // Auto-rig only
        result = await runAutoRig({
            meshPath: options.mesh,
            outputPath: options.output,
            rigType: options.rigType,
            scale: options.scale,
            config,
        });
    } else {
        logger.error('Mesh path required. Use --mesh or -m');
        process.exit(1);
    }

    // Output result
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.success ? 0 : 1);
}

// ============================================================================
// Module Exports (for programmatic use)
// ============================================================================

module.exports = {
    runAutoRig,
    runRetarget,
    runFullPipeline,
    runBatch,
    JobQueue,
    DEFAULT_CONFIG,
};

// Run CLI if executed directly
if (require.main === module) {
    main().catch(error => {
        logger.error(`Unhandled error: ${error.message}`);
        process.exit(1);
    });
}
