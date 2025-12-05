# Technical Overview: Headless Blender Asset Pipeline with Docker + GPU

## Executive Summary

This document provides a comprehensive technical overview of implementing a headless Blender asset pipeline using Docker containers with GPU acceleration. The architecture enables automated 3D asset processing including rigging, animation retargeting, rendering, and format conversion at scale.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Docker Host Setup](#docker-host-setup)
3. [GPU Drivers & NVIDIA Container Toolkit](#gpu-drivers--nvidia-container-toolkit)
4. [Volume Mounting Strategy](#volume-mounting-strategy)
5. [Container Security & Permissions](#container-security--permissions)
6. [Failure Modes & Troubleshooting](#failure-modes--troubleshooting)
7. [Versioning Considerations](#versioning-considerations)
8. [Best Practices](#best-practices)
9. [Performance Optimization](#performance-optimization)
10. [Monitoring & Observability](#monitoring--observability)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Host System                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │  NVIDIA Driver  │  │  Docker Engine  │  │  NVIDIA Container   │ │
│  │    (525+)       │  │    (19.03+)     │  │      Toolkit        │ │
│  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘ │
│           │                    │                      │            │
│           └────────────────────┼──────────────────────┘            │
│                                │                                    │
│  ┌─────────────────────────────┴─────────────────────────────────┐ │
│  │                    Docker Container                            │ │
│  │  ┌─────────────────────────────────────────────────────────┐  │ │
│  │  │  Ubuntu 22.04 + CUDA 12.2 Runtime                       │  │ │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │  │ │
│  │  │  │ Blender 4.2 │  │   Python    │  │  Pipeline       │  │  │ │
│  │  │  │    LTS      │  │   Scripts   │  │  Scripts        │  │  │ │
│  │  │  └─────────────┘  └─────────────┘  └─────────────────┘  │  │ │
│  │  └─────────────────────────────────────────────────────────┘  │ │
│  │                              ▲                                 │ │
│  │                              │ Volume Mount                    │ │
│  └──────────────────────────────┼────────────────────────────────┘ │
│                                 │                                   │
│  ┌──────────────────────────────┴────────────────────────────────┐ │
│  │                    /workspace                                  │ │
│  │   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │ │
│  │   │  Input   │  │  Output  │  │   Logs   │  │   Scripts    │  │ │
│  │   │  Assets  │  │  Assets  │  │          │  │              │  │ │
│  │   └──────────┘  └──────────┘  └──────────┘  └──────────────┘  │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Version | Purpose |
|-----------|---------|---------|
| Ubuntu Base | 22.04 LTS | Stable OS with long-term support |
| CUDA Runtime | 12.2 | GPU acceleration for Cycles rendering |
| Blender | 4.2 LTS | 3D processing engine with Python API |
| Docker | 19.03+ | Container runtime |
| NVIDIA Container Toolkit | Latest | GPU passthrough to containers |

---

## Docker Host Setup

### Hardware Requirements

| Resource | Minimum | Recommended | Notes |
|----------|---------|-------------|-------|
| CPU | 4 cores | 8+ cores | More cores = better parallel processing |
| RAM | 16 GB | 32+ GB | Large scenes require significant memory |
| GPU | NVIDIA GTX 1060 | RTX 3080+ | CUDA compute capability 6.0+ |
| GPU VRAM | 6 GB | 12+ GB | Complex scenes/renders need more VRAM |
| Storage | 50 GB SSD | 200+ GB NVMe | Fast I/O for asset loading |

### Host OS Configuration

```bash
# Ubuntu 22.04 LTS recommended
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group (avoids sudo requirement)
sudo usermod -aG docker $USER
newgrp docker

# Enable Docker service
sudo systemctl enable docker
sudo systemctl start docker

# Verify installation
docker --version
docker run hello-world
```

### Docker Daemon Configuration

Create or edit `/etc/docker/daemon.json`:

```json
{
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  },
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  },
  "default-ulimits": {
    "memlock": {
      "Name": "memlock",
      "Hard": -1,
      "Soft": -1
    }
  }
}
```

Restart Docker after configuration:
```bash
sudo systemctl restart docker
```

---

## GPU Drivers & NVIDIA Container Toolkit

### Driver Installation

```bash
# Check current driver (if any)
nvidia-smi

# Install NVIDIA driver (Ubuntu)
sudo apt-get install -y nvidia-driver-535

# Reboot required after driver installation
sudo reboot

# Verify driver installation
nvidia-smi
```

**Driver Version Matrix:**

| CUDA Version | Minimum Driver | Recommended Driver |
|--------------|----------------|-------------------|
| CUDA 11.x | 450.80.02+ | 470+ |
| CUDA 12.0 | 525.60.13+ | 530+ |
| CUDA 12.2 | 535.54.03+ | 535+ |

### NVIDIA Container Toolkit Installation

```bash
# Add NVIDIA package repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install toolkit
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Configure Docker runtime
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU access in containers
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi
```

### Troubleshooting GPU Access

```bash
# Check NVIDIA Container Runtime
nvidia-container-cli info

# Verify runtime is configured
docker info | grep -i runtime

# Test GPU visibility
docker run --rm --gpus all ubuntu nvidia-smi

# Check container toolkit logs
journalctl -u nvidia-container-toolkit
```

---

## Volume Mounting Strategy

### Directory Structure

```
/data/blender-pipeline/
├── inputs/           # Source assets (read-only recommended)
│   ├── meshes/       # .obj, .fbx, .ply, .stl files
│   ├── animations/   # .bvh, .fbx animation files
│   ├── textures/     # Texture files
│   └── configs/      # Bone mappings, job configs
├── outputs/          # Generated assets
│   ├── rigged/       # Rigged meshes
│   ├── animated/     # Animated meshes
│   └── renders/      # Rendered images/videos
├── logs/             # Job logs
├── temp/             # Temporary working directories
└── scripts/          # Pipeline scripts
```

### Mount Options

```bash
# Basic mount (read-write)
docker run -v /data/pipeline:/workspace blender-headless

# Read-only input mount (recommended for inputs)
docker run \
  -v /data/inputs:/workspace/inputs:ro \
  -v /data/outputs:/workspace/outputs:rw \
  blender-headless

# Bind mount with specific options
docker run \
  --mount type=bind,source=/data/pipeline,target=/workspace,consistency=cached \
  blender-headless

# Using tmpfs for temporary data (faster, memory-backed)
docker run \
  -v /data/inputs:/workspace/inputs:ro \
  -v /data/outputs:/workspace/outputs \
  --tmpfs /workspace/temp:size=2G \
  blender-headless
```

### Volume Performance Considerations

| Mount Type | Speed | Persistence | Use Case |
|------------|-------|-------------|----------|
| Bind mount | Native | Yes | Standard I/O |
| Named volume | Native | Yes | Persistent data |
| tmpfs | Fastest | No | Temporary/scratch |
| NFS mount | Slower | Yes | Shared storage |

**Best Practices:**
- Use bind mounts with `:ro` for input assets
- Use tmpfs for temporary working directories
- Avoid mounting large directory trees; mount specific subdirectories
- Consider using named volumes for frequently accessed scripts

---

## Container Security & Permissions

### Common Permission Issues

#### Problem: Files Created as Root
```bash
# Files created in container are owned by root
ls -la /data/outputs/
# -rw-r--r-- 1 root root 1234567 output.glb
```

#### Solution 1: Run as Current User
```bash
docker run --rm \
  --gpus all \
  --user $(id -u):$(id -g) \
  -v $(pwd):/workspace \
  blender-headless --run
```

#### Solution 2: Fix Permissions After Run
```bash
# Change ownership after processing
sudo chown -R $(id -u):$(id -g) /data/outputs/
```

#### Solution 3: Use User Namespace Remapping
Add to `/etc/docker/daemon.json`:
```json
{
  "userns-remap": "default"
}
```

### Security Best Practices

```bash
# Run with minimal capabilities
docker run --rm \
  --gpus all \
  --cap-drop=ALL \
  --cap-add=SYS_NICE \
  --security-opt=no-new-privileges:true \
  --read-only \
  --tmpfs /tmp \
  -v /data/inputs:/workspace/inputs:ro \
  -v /data/outputs:/workspace/outputs \
  blender-headless

# Resource limits
docker run --rm \
  --gpus all \
  --memory=16g \
  --memory-swap=16g \
  --cpus=4 \
  --pids-limit=100 \
  blender-headless
```

### Network Isolation

```bash
# Run with no network access (recommended for pure processing)
docker run --rm \
  --gpus all \
  --network=none \
  -v /data:/workspace \
  blender-headless --run
```

---

## Failure Modes & Troubleshooting

### 1. Out of Memory (OOM)

**Symptoms:**
- Container killed unexpectedly
- `Killed` message in logs
- Exit code 137

**Causes:**
- Large mesh with high polygon count
- High-resolution textures
- Complex Cycles render settings
- Insufficient GPU VRAM

**Solutions:**
```bash
# Increase memory limits
docker run --rm \
  --gpus all \
  --memory=32g \
  --memory-swap=64g \
  blender-headless

# Monitor memory usage
docker stats <container_id>

# In Blender script, reduce memory usage
bpy.context.preferences.system.memory_cache_limit = 4096  # MB
bpy.context.scene.cycles.tile_size = 256  # Smaller tiles
```

**GPU VRAM OOM:**
```python
# Reduce GPU memory usage in script
bpy.context.scene.cycles.samples = 64  # Lower samples
bpy.context.scene.render.resolution_percentage = 50  # Lower resolution

# Use CPU rendering as fallback
try:
    bpy.context.scene.cycles.device = 'GPU'
except:
    bpy.context.scene.cycles.device = 'CPU'
```

### 2. Export Errors

**Common Export Issues:**

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid mesh` | Non-manifold geometry | Run mesh cleanup before export |
| `Missing armature` | Armature not linked | Parent mesh to armature |
| `Scale mismatch` | Incorrect scale | Apply transforms before export |
| `Missing textures` | Paths not embedded | Use `path_mode='COPY'` in export |

**Debugging Export:**
```python
# Enable verbose export logging
bpy.ops.export_scene.gltf(
    filepath="/workspace/output.glb",
    export_format='GLB',
    use_selection=True,
    # Debug options
    export_extras=True,
    will_save_settings=True
)

# Check export operator result
result = bpy.ops.export_scene.gltf(...)
if 'FINISHED' not in result:
    print(f"Export failed: {result}")
```

### 3. Missing Dependencies

**Symptom:** Import errors or missing operators

**Common Missing Dependencies:**
```bash
# Check available Python packages
blender -b --python-expr "import sys; print('\n'.join(sys.path))"

# Install missing packages in Dockerfile
RUN /opt/blender/4.2/python/bin/python3.11 -m pip install \
    numpy scipy pillow requests
```

**Addon Issues:**
```python
# Enable required addons in script
import addon_utils

required_addons = ['rigify', 'io_scene_fbx', 'io_scene_gltf2']
for addon in required_addons:
    try:
        addon_utils.enable(addon, default_set=True)
        print(f"Enabled addon: {addon}")
    except Exception as e:
        print(f"Failed to enable {addon}: {e}")
```

### 4. GPU Not Detected

**Diagnostic Commands:**
```bash
# Check GPU visibility in container
docker run --rm --gpus all blender-headless --gpu-info

# Verify CUDA installation
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 \
  bash -c "nvcc --version && nvidia-smi"

# Check Blender GPU detection
docker run --rm --gpus all blender-headless \
  -b --python-expr "
import bpy
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'CUDA'
prefs.get_devices()
for d in prefs.devices:
    print(f'{d.name}: {d.type} - Enabled: {d.use}')
"
```

### 5. Timeout Issues

**Causes:**
- Very long renders
- Large file I/O
- Network timeouts (when fetching assets)

**Solutions:**
```javascript
// In pipeline_runner.js, configure timeout
const result = await runDockerCommand(args, {
    timeout: 600000  // 10 minutes
});

// Or set no timeout for long jobs
const result = await runDockerCommand(args, {
    timeout: 0  // Infinite
});
```

---

## Versioning Considerations

### Blender Version Matrix

| Blender Version | Python | glTF Support | Status | Notes |
|-----------------|--------|--------------|--------|-------|
| 3.6 LTS | 3.10 | 2.0 | Supported | Previous LTS |
| 4.0 | 3.10 | 2.0 | Current | Breaking changes from 3.x |
| 4.1 | 3.11 | 2.0 | Current | Python upgrade |
| 4.2 LTS | 3.11 | 2.0 | **Recommended** | Current LTS |
| 4.3+ | 3.11 | 2.0 | Latest | Bleeding edge |

### API Breaking Changes (3.x → 4.x)

```python
# Blender 3.x
bpy.ops.wm.obj_export(filepath="output.obj")  # 3.6+

# Blender 4.x (some API changes)
# Most operators remain compatible

# Check version in scripts
if bpy.app.version >= (4, 0, 0):
    # Use 4.x API
    pass
else:
    # Use 3.x API
    pass
```

### glTF Exporter Compatibility

**glTF 2.0 Feature Support:**

| Feature | Blender 3.6 | Blender 4.2 | Notes |
|---------|-------------|-------------|-------|
| Skinning | ✅ | ✅ | Full support |
| Morph targets | ✅ | ✅ | Full support |
| Draco compression | ✅ | ✅ | Requires addon |
| KHR_materials_unlit | ✅ | ✅ | Standard extension |
| Animation | ✅ | ✅ | NLA strips supported |
| Sparse accessors | ⚠️ | ✅ | Improved in 4.x |

### Version Pinning Strategy

```dockerfile
# Pin specific Blender version in Dockerfile
ENV BLENDER_VERSION=4.2
ENV BLENDER_VERSION_FULL=4.2.3

# Use checksum verification
RUN wget -q https://download.blender.org/release/Blender${BLENDER_VERSION}/blender-${BLENDER_VERSION_FULL}-linux-x64.tar.xz \
    && echo "EXPECTED_SHA256  blender-${BLENDER_VERSION_FULL}-linux-x64.tar.xz" | sha256sum -c - \
    && tar -xf blender-${BLENDER_VERSION_FULL}-linux-x64.tar.xz
```

```json
// package.json - pin Node.js version
{
  "engines": {
    "node": ">=18.0.0 <21.0.0"
  }
}
```

### Dependency Lock Files

```bash
# Create requirements snapshot for reproducibility
docker run --rm blender-headless \
  /opt/blender/4.2/python/bin/python3.11 -m pip freeze > requirements.lock

# Python packages in container
numpy==1.24.3
scipy==1.11.4
pillow==10.1.0
requests==2.31.0
```

---

## Best Practices

### 1. Job Isolation

**One Container Per Job:**
```javascript
// Each job runs in its own container
async function runJob(jobConfig) {
    const containerId = await startContainer(jobConfig);
    try {
        const result = await waitForCompletion(containerId);
        return result;
    } finally {
        await removeContainer(containerId);
    }
}
```

**Benefits:**
- Clean environment for each job
- No state leakage between jobs
- Easy resource tracking
- Parallel execution without conflicts

### 2. Temporary Directory Management

```python
# In Blender scripts
import tempfile
import shutil
from pathlib import Path

# Create job-specific temp directory
job_temp = Path(tempfile.mkdtemp(prefix='blender_job_'))

try:
    # Do work in temp directory
    intermediate_file = job_temp / 'intermediate.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(intermediate_file))
    
    # Process...
    
finally:
    # Cleanup temp directory
    shutil.rmtree(job_temp, ignore_errors=True)
```

```javascript
// In pipeline_runner.js
const os = require('os');
const path = require('path');
const crypto = require('crypto');

function createTempWorkspace(jobId) {
    const tempDir = path.join(
        os.tmpdir(), 
        `blender-pipeline-${jobId}-${crypto.randomBytes(4).toString('hex')}`
    );
    fs.mkdirSync(tempDir, { recursive: true });
    return tempDir;
}
```

### 3. Clean Error Logging

```python
# Structured logging in Blender scripts
import logging
import json
import sys
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'job_id': getattr(record, 'job_id', 'unknown'),
            'step': getattr(record, 'step', 'unknown'),
        }
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

# Setup logger
logger = logging.getLogger('blender_pipeline')
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Usage
logger.info('Starting auto-rig', extra={'job_id': job_id, 'step': 'init'})
```

### 4. Idempotent Operations

```python
# Design scripts to be safely re-runnable
def import_mesh_idempotent(filepath, name):
    """Import mesh only if not already present."""
    if name in bpy.data.objects:
        logger.info(f"Object {name} already exists, skipping import")
        return bpy.data.objects[name]
    
    # Import fresh
    return import_mesh(filepath)

def clear_scene_safely():
    """Clear scene with proper cleanup."""
    # Deselect all first
    bpy.ops.object.select_all(action='DESELECT')
    
    # Delete all objects
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # Clean orphan data
    for collection in [bpy.data.meshes, bpy.data.armatures, 
                       bpy.data.materials, bpy.data.actions]:
        for block in collection:
            if block.users == 0:
                collection.remove(block)
```

### 5. Graceful Degradation

```python
def setup_rendering():
    """Setup rendering with GPU fallback to CPU."""
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get('cycles')
    
    if not cycles_prefs:
        logger.warning("Cycles addon not available")
        return False
    
    cycles_prefs = cycles_prefs.preferences
    
    # Try GPU backends in order of preference
    for device_type in ['CUDA', 'OPTIX', 'HIP', 'METAL']:
        try:
            cycles_prefs.compute_device_type = device_type
            cycles_prefs.get_devices()
            
            gpu_found = any(
                d.type != 'CPU' and d.use 
                for d in cycles_prefs.devices
            )
            
            if gpu_found:
                bpy.context.scene.cycles.device = 'GPU'
                logger.info(f"Using {device_type} for rendering")
                return True
                
        except Exception as e:
            logger.debug(f"{device_type} not available: {e}")
            continue
    
    # Fallback to CPU
    logger.warning("No GPU available, falling back to CPU rendering")
    bpy.context.scene.cycles.device = 'CPU'
    return True
```

### 6. Configuration Management

```python
# Use configuration files instead of hardcoded values
import json
from pathlib import Path

DEFAULT_CONFIG = {
    'rig_type': 'basic',
    'export_format': 'glb',
    'scale': 1.0,
    'fps': 30,
    'cleanup_mesh': True,
    'apply_transforms': True,
}

def load_config(config_path=None):
    """Load configuration with defaults."""
    config = DEFAULT_CONFIG.copy()
    
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            user_config = json.load(f)
            config.update(user_config)
    
    return config
```

---

## Performance Optimization

### Blender Settings

```python
# Optimize Blender for headless batch processing
def optimize_blender_settings():
    prefs = bpy.context.preferences
    
    # Disable undo (saves memory)
    prefs.edit.undo_steps = 0
    
    # Reduce memory cache
    prefs.system.memory_cache_limit = 2048  # MB
    
    # Disable thumbnails
    prefs.filepaths.file_preview_type = 'NONE'
    
    # Optimize Cycles
    scene = bpy.context.scene
    if scene.render.engine == 'CYCLES':
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPTIX'  # If available
```

### Container Resource Allocation

```bash
# Optimal resource allocation
docker run --rm \
  --gpus all \
  --memory=16g \
  --memory-reservation=8g \
  --cpus=4 \
  --cpu-shares=1024 \
  --shm-size=2g \
  blender-headless
```

### Parallel Processing

```javascript
// Configure concurrency based on resources
const MAX_CONCURRENT_JOBS = Math.min(
    os.cpus().length / 2,  // Use half of CPU cores
    4  // Cap at 4 parallel jobs
);

const queue = new JobQueue(MAX_CONCURRENT_JOBS);
```

---

## Monitoring & Observability

### Container Metrics

```bash
# Real-time stats
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

# GPU monitoring (in another terminal)
watch -n 1 nvidia-smi
```

### Structured Logging

```javascript
// In pipeline_runner.js
const logger = {
    info: (msg, meta = {}) => {
        console.log(JSON.stringify({
            timestamp: new Date().toISOString(),
            level: 'info',
            message: msg,
            ...meta
        }));
    },
    error: (msg, meta = {}) => {
        console.error(JSON.stringify({
            timestamp: new Date().toISOString(),
            level: 'error',
            message: msg,
            ...meta
        }));
    }
};

// Usage
logger.info('Job started', { jobId, meshPath, outputPath });
logger.error('Job failed', { jobId, error: err.message, stack: err.stack });
```

### Health Checks

```dockerfile
# Add health check to Dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD blender --version || exit 1
```

---

## Summary Checklist

### Pre-Deployment

- [ ] NVIDIA drivers installed (525+)
- [ ] Docker installed and configured (19.03+)
- [ ] NVIDIA Container Toolkit installed
- [ ] GPU accessible from containers (`docker run --gpus all nvidia/cuda nvidia-smi`)
- [ ] Volume mount paths exist with correct permissions
- [ ] Docker daemon configured with GPU runtime

### Container Configuration

- [ ] Version pinned in Dockerfile
- [ ] Resource limits configured
- [ ] Security options applied
- [ ] Health checks enabled
- [ ] Logging configured

### Pipeline Scripts

- [ ] Error handling implemented
- [ ] Logging structured and comprehensive
- [ ] Cleanup on success/failure
- [ ] Graceful GPU fallback
- [ ] Idempotent operations

### Monitoring

- [ ] Container metrics collection
- [ ] GPU utilization monitoring
- [ ] Log aggregation configured
- [ ] Alerting for failures

---

## Quick Reference

### Common Commands

```bash
# Build container
docker build -t blender-headless .

# Run with GPU
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run

# Debug shell
docker run --rm -it --gpus all -v $(pwd):/workspace blender-headless --shell

# Check GPU
docker run --rm --gpus all blender-headless --gpu-info

# Run as current user
docker run --rm --gpus all --user $(id -u):$(id -g) -v $(pwd):/workspace blender-headless --run
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 137 | Out of memory (OOM killed) |
| 139 | Segmentation fault |
| 143 | Terminated (SIGTERM) |

---

*Document Version: 1.0*  
*Last Updated: December 2024*  
*Blender Version: 4.2 LTS*
