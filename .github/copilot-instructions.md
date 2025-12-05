# Copilot Instructions - Headless Blender Microservice

## Project Overview

This is a Docker-based headless Blender microservice with CUDA GPU acceleration support. The container runs Blender in background mode, executes Python scripts, and outputs results (FBX, glTF, images, etc.) to a mounted workspace directory.

## Tech Stack

- **Base Image**: Ubuntu 22.04 LTS with NVIDIA CUDA 12.2 runtime (`nvidia/cuda:12.2.0-runtime-ubuntu22.04`)
- **Blender Version**: 4.2.3 LTS with full Python API (`bpy`) and bundled Python 3.11
- **GPU Acceleration**: CUDA for Cycles rendering (tested with RTX 5080, CUDA 13.0)
- **Container Runtime**: Docker with NVIDIA Container Toolkit
- **Orchestration**: Node.js 18+ with npm scripts

## Project Structure

```
.
├── Dockerfile               # Main container definition (6.4GB image)
├── entrypoint.sh            # Container entrypoint script
├── README.md                # User-facing documentation
├── package.json             # Node.js project configuration
├── pipeline_runner.js       # Node.js orchestration script
├── auto_rig_and_export.py   # Auto-rigging Blender script
├── retarget_and_export.py   # Animation retargeting Blender script
├── build_frankmocap.sh      # FrankMocap build script for modern GPUs
├── .github/
│   └── copilot-instructions.md  # This file (developer context)
├── docs/
│   └── TECHNICAL_OVERVIEW.md    # Technical architecture
├── frankmocap/
│   ├── Dockerfile               # FrankMocap GPU container (36GB image)
│   ├── build_frankmocap_docker.sh  # Docker build script
│   └── entrypoint_frankmocap.sh    # Container entrypoint
├── scripts/
│   ├── bootstrap.sh         # Environment setup and validation
│   └── test-pipeline.sh     # Integration test suite
├── examples/
│   ├── script.py            # Example Blender script
│   └── sample_walk.bvh      # Sample BVH animation (29 frames)
└── output/                  # Generated files directory
```

## Key Files

### Dockerfile
- Uses NVIDIA CUDA 12.2 base image for GPU support
- Installs Blender 4.2.3 LTS from official release
- Includes dependencies: OpenEXR, FFmpeg codecs, image format libraries
- Installs Python packages (numpy, scipy, pillow, requests) in Blender's bundled Python 3.11
- Sets up `/workspace` as the working directory

### entrypoint.sh
The entrypoint supports multiple operation modes:
- `--help` - Show usage information
- `--version` - Show Blender version
- `--gpu-info` - Check GPU/CUDA availability
- `--run` - Run the default script (`script.py` or `$BLENDER_SCRIPT`)
- `--script <file>` - Run a specific Python script
- `--render <file>` - Render a `.blend` file
- `--shell` - Start interactive shell for debugging
- Custom arguments passed directly to Blender

### pipeline_runner.js
Node.js orchestration script that:
- Creates temporary workspaces in `/tmp/blender-pipeline-{jobId}/`
- Copies input files and Python scripts to temp workspace
- Executes Docker commands for auto-rig and retarget pipelines
- Supports batch processing with configurable concurrency
- Provides comprehensive error handling and logging
- Cleans up temporary data after processing

**CLI usage:**
```bash
# Auto-rig a mesh
npm run pipeline -- --mesh character.obj --output rigged.glb

# Retarget animation to rigged mesh
npm run pipeline -- --mesh avatar.glb --animation motion.bvh --output animated.glb

# Batch processing
npm run batch -- jobs.json --concurrency 4
```

**Programmatic usage:**
```javascript
const { runAutoRig, runRetarget, runFullPipeline, runBatch } = require('./pipeline_runner');

// Auto-rig
const result = await runAutoRig({ meshPath: 'mesh.obj', outputPath: 'rigged.glb' });

// Retarget
const result = await runRetarget({ targetPath: 'avatar.glb', animationPath: 'motion.bvh', outputPath: 'animated.glb' });

// Full pipeline (mesh + animation → animated rigged mesh)
const result = await runFullPipeline({ meshPath: 'mesh.obj', animationPath: 'motion.bvh', outputPath: 'final.glb' });
```

### auto_rig_and_export.py
Automated rigging pipeline script that:
- Imports mesh files (.obj, .fbx, .ply, .stl, .glb)
- Creates humanoid armature with 23 bones (basic) or Rigify metarig
- Applies automatic weights via heat map skinning
- Exports rigged mesh to glTF or FBX format

Command-line arguments:
- `--input, -i` - Input mesh file path (required)
- `--output, -o` - Output file path (required)
- `--rig-type` - Rig type: 'basic', 'rigify', 'metarig' (default: basic)
- `--scale` - Scale factor for the mesh (default: 1.0)
- `--cleanup` / `--no-cleanup` - Run mesh cleanup operations
- `--apply-transforms` / `--no-apply-transforms` - Apply transforms before rigging
- `--log-file` - Optional log file path

### retarget_and_export.py
Animation retargeting script that:
- Imports a rigged target mesh (avatar)
- Imports source animation (BVH, glTF, FBX)
- Retargets animation using bone name mapping
- Bakes animation to target skeleton
- Exports animated mesh with skeleton

Command-line arguments:
- `--target, -t` - Target rigged mesh file (required)
- `--source, -s` - Source animation file (required)
- `--output, -o` - Output file path (required)
- `--mapping, -m` - Optional JSON file with bone name mapping
- `--start-frame` - Start frame for baking (default: auto-detect)
- `--end-frame` - End frame for baking (default: auto-detect)
- `--fps` - Frames per second (default: 30)
- `--scale` - Scale factor for source animation (default: 1.0)
- `--root-motion` / `--no-root-motion` - Include root motion
- `--log-file` - Optional log file path

### build_frankmocap.sh
FrankMocap build script for modern GPUs (RTX 40xx/50xx/Blackwell):
- Clones the official FrankMocap repository (archived Oct 2023)
- Detects GPU/CUDA version via nvidia-smi
- Installs PyTorch 2.x with compatible CUDA version
- Applies compatibility patches for Python 3.10+ and modern PyTorch
- Installs Detectron2 and PyTorch3D from source for hand detection
- Downloads pretrained models and sample data
- Provides CPU fallback if GPU fails
- Creates wrapper script with TF32 optimization for Ampere+ GPUs

Usage:
```bash
# Full installation with GPU support
./build_frankmocap.sh

# Install in custom directory
./build_frankmocap.sh --install-dir /path/to/frankmocap

# Body module only (fewer dependencies)
./build_frankmocap.sh --body-only

# CPU-only mode (no GPU required)
./build_frankmocap.sh --cpu-only
```

**Known Issues Addressed:**
- Legacy CUDA 10.1/PyTorch 1.6 → Updated to CUDA 12.x/PyTorch 2.x
- Python 3.7 requirement → Patched for Python 3.10+
- Deprecated numpy/scipy APIs → Automatic code patches
- OpenGL rendering on headless servers → xvfb or pytorch3d renderer
- Detectron2 pre-built wheels unavailable → Build from source

### frankmocap/Dockerfile
FrankMocap Docker container for headless GPU-based motion capture inference:
- Base image: `nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04`
- PyTorch: 2.10+ nightly with CUDA 12.8 (cu128) for Blackwell/RTX 50 series
- Image size: ~36GB
- Uses `build_frankmocap_docker.sh` for installation
- Headless rendering via xvfb and OSMesa

**Build and run:**
```bash
# Build (from project root)
docker build -t frankmocap-gpu -f frankmocap/Dockerfile .

# Check GPU
docker run --rm --gpus all frankmocap-gpu --gpu-info

# Run inference
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v /path/to/output:/workspace/output \
  -v /path/to/smpl_models:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_path /workspace/input/video.mp4 \
  --out_dir /workspace/output
```

### frankmocap/entrypoint_frankmocap.sh
Container entrypoint script providing:
- `--help` - Show usage information
- `--version` - Show version info (PyTorch, CUDA)
- `--gpu-info` - Check GPU/CUDA availability
- `--shell` - Start interactive bash shell
- `--input_path FILE` - Process single video/image
- `--input_dir DIR` - Batch process directory
- `--out_dir DIR` - Output directory (default: /workspace/output)
- `--mode MODE` - Inference mode: body, hand, or full
- `--save_pred_pkl` - Save prediction as pickle
- `--save_mesh` - Save 3D mesh outputs

### frankmocap/build_frankmocap_docker.sh
Docker-adapted build script that:
- Installs PyTorch nightly with CUDA 12.8 for Blackwell support
- Clones ellyseum/frankmocap fork with PyTorch 2.x fixes
- Installs Detectron2 from source
- Downloads pretrained models (body + hand modules)
- Installs third-party detectors
- Applies compatibility patches
- Creates SMPL placeholder directory

### scripts/bootstrap.sh
Environment setup script that:
- Checks prerequisites (Docker, Node.js, nvidia-smi)
- Verifies NVIDIA Container Toolkit installation
- Validates required project files exist
- Installs npm dependencies
- Builds the Docker image
- Tests GPU access in container

### scripts/test-pipeline.sh
Integration test suite that validates:
- Docker container basic operations (--help, --version, --gpu-info)
- Example script execution and output generation
- Auto-rig pipeline via pipeline_runner.js
- Animation retargeting pipeline
- npm script functionality

### Environment Variables
- `BLENDER_SCRIPT` - Default script to run (default: `script.py`)
- `BLENDER_ARGS` - Additional arguments passed to Blender
- `LOG_LEVEL` - Logging level for pipeline_runner.js (debug, info, warn, error)

## NPM Scripts Reference

| Script | Description |
|--------|-------------|
| `npm run bootstrap` | Set up environment and build Docker image |
| `npm run pipeline -- [args]` | Run pipeline with arguments |
| `npm run batch -- jobs.json` | Run batch processing |
| `npm run docker:build` | Build the Blender Docker image |
| `npm run docker:gpu-info` | Check GPU/CUDA availability |
| `npm run docker:shell` | Start interactive shell in container |
| `npm run docker:version` | Show Blender version |
| `npm test` | Run integration test suite |
| `npm run lint` | Lint JavaScript files |

## Quick Start

```bash
# 1. Bootstrap environment (first time setup)
npm run bootstrap

# 2. Test everything works
npm test

# 3. Run auto-rig on a mesh
npm run pipeline -- --mesh input.obj --output output/rigged.glb

# 4. Retarget animation
npm run pipeline -- --mesh output/rigged.glb --animation motion.bvh --output output/animated.glb
```

## Tested Workflow (Validated Dec 5, 2025)

The following workflows have been validated end-to-end:

### Blender Pipeline
1. **Example script execution**: Creates `suzanne.fbx` (395KB) and `suzanne.glb` (402KB)
2. **Auto-rig**: Generates `suzanne_rigged.glb` (1.18MB) with 23-bone humanoid armature
3. **Retarget**: Produces `suzanne_animated.glb` (1.22MB) with 29 frames, 230 f-curves

### FrankMocap Container (Validated Dec 5, 2025)
- **Image build**: Successfully builds 36.3GB container in ~18 minutes
- **GPU detection**: Correctly detects RTX 5080 (Blackwell, Compute Capability 12.0)
- **PyTorch**: 2.10.0.dev nightly with CUDA 12.8, cuDNN 91002
- **Container commands**: --help, --version, --gpu-info all working

## Direct Docker Commands

```bash
# Run default script with GPU
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run

# Run specific script
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --script my_script.py

# Check GPU availability
docker run --rm --gpus all blender-headless --gpu-info

# Interactive shell for debugging
docker run --rm -it --gpus all -v $(pwd):/workspace blender-headless --shell

# Auto-rig a mesh directly
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/auto_rig_and_export.py -- \
    --input /workspace/character.obj --output /workspace/rigged.glb

# Retarget animation directly
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/retarget_and_export.py -- \
    --target /workspace/avatar.glb \
    --source /workspace/motion.bvh \
    --output /workspace/animated.glb
```

## Writing Blender Python Scripts

### Script Location
Scripts should be placed in the mounted `/workspace` directory.

### GPU Setup Pattern
```python
def setup_gpu():
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get('cycles')
    if cycles_prefs:
        cycles_prefs = cycles_prefs.preferences
        cycles_prefs.compute_device_type = 'CUDA'
        cycles_prefs.get_devices()
        for device in cycles_prefs.devices:
            if device.type == 'CUDA':
                device.use = True
        bpy.context.scene.cycles.device = 'GPU'
```

### Export Functions (Blender 4.x Compatible)
```python
# FBX Export - NOTE: apply_modifiers was removed in Blender 4.x
bpy.ops.export_scene.fbx(
    filepath="/workspace/output.fbx",
    use_selection=True,
    apply_scale_options='FBX_SCALE_ALL'
)

# glTF/GLB Export
bpy.ops.export_scene.gltf(
    filepath="/workspace/output.glb",
    use_selection=True,
    export_apply=True
)
```

### Supported Export Formats
- FBX (`.fbx`) - `bpy.ops.export_scene.fbx()`
- glTF/GLB (`.gltf`, `.glb`) - `bpy.ops.export_scene.gltf()`
- OBJ (`.obj`) - `bpy.ops.wm.obj_export()`
- USD (`.usd`, `.usda`, `.usdc`) - `bpy.ops.wm.usd_export()`
- Alembic (`.abc`) - `bpy.ops.wm.alembic_export()`
- STL (`.stl`) - `bpy.ops.wm.stl_export()`
- PLY (`.ply`) - `bpy.ops.wm.ply_export()`

## Common Issues and Solutions

### GPU Not Detected
- Ensure `--gpus all` flag is passed to `docker run`
- Verify NVIDIA Container Toolkit is installed on host
- Test with: `docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi`

### Permission Issues
Output files created as root. Solutions:
1. Run with `--user $(id -u):$(id -g)`
2. Fix after: `sudo chown -R $(id -u):$(id -g) ./output*`

### Docker Permission Denied
If you get "permission denied" when running docker:
```bash
sudo usermod -aG docker $USER
# Then restart your terminal/WSL session
```

### Memory Issues
For large scenes, increase Docker memory:
```bash
docker run --rm --gpus all --memory=16g --memory-swap=32g -v $(pwd):/workspace blender-headless --run
```

### Blender 4.x API Changes
- `apply_modifiers` parameter removed from FBX export - use `apply_scale_options` instead
- Some operator names have changed - always check bpy.ops documentation

## Prerequisites for Host Machine

1. NVIDIA GPU with CUDA support
2. NVIDIA Driver (version 525+ for CUDA 12.x)
3. Docker (version 19.03+)
4. NVIDIA Container Toolkit installed and configured
5. Node.js 18+ and npm

## Maintaining This Document

**Keep these instructions up to date as the project evolves.** When making changes:

1. **New dependencies**: Update the Tech Stack section
2. **New scripts/files**: Add to Project Structure with descriptions
3. **New npm scripts**: Update the NPM Scripts Reference table
4. **Discovered issues**: Add to Common Issues and Solutions
5. **API changes**: Update code examples when Blender API changes
6. **Tested workflows**: Update the Tested Workflow section with validation dates

This document serves as the primary context for AI assistants (Copilot). Accurate documentation ensures better code suggestions.

## Keeping README.md in Sync

The `README.md` file is the public-facing documentation. **Always update `README.md` alongside this file** when making significant changes:

1. **Keep both files consistent**: Changes to commands and examples should be in both files
2. **README is user-focused**: Quick start guides and usage examples
3. **Copilot instructions are developer-focused**: Internal context and debugging info
