# Headless Blender Microservice

A Docker-based headless Blender microservice with CUDA GPU acceleration support. This container runs Blender in background mode, executes Python scripts, and outputs results (FBX, glTF, images, etc.) to a mounted workspace directory.

## Features

- **Ubuntu 22.04 LTS** base with NVIDIA CUDA 12.2 runtime
- **Blender 4.2.3 LTS** with full Python API (`bpy`) and bundled Python 3.11
- **GPU acceleration** via CUDA for Cycles rendering (tested with RTX 5080)
- **Auto-rigging pipeline** - Add humanoid skeleton to meshes automatically
- **Animation retargeting** - Apply mocap animations to rigged avatars
- **Node.js orchestration** - npm scripts for easy pipeline management
- **Headless operation** - No display required

## Prerequisites

### Host Requirements

1. **NVIDIA GPU** with CUDA support
2. **NVIDIA Driver** (version 525+ recommended for CUDA 12.x)
3. **Docker** (version 19.03+)
4. **NVIDIA Container Toolkit** installed and configured
5. **Node.js 18+** and npm

### Installing NVIDIA Container Toolkit

```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

Verify GPU is accessible in Docker:
```bash
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi
```

## Quick Start

```bash
# 1. Clone and enter the directory
cd avatar-animate-from-video-mvp

# 2. Bootstrap environment (installs deps, builds Docker image, tests GPU)
npm run bootstrap

# 3. Run tests to validate everything works
npm test

# 4. Auto-rig a mesh
npm run pipeline -- --mesh input.obj --output output/rigged.glb

# 5. Retarget animation to rigged mesh
npm run pipeline -- --mesh output/rigged.glb --animation motion.bvh --output output/animated.glb
```

## NPM Scripts

| Script | Description |
|--------|-------------|
| `npm run bootstrap` | Set up environment and build Docker image |
| `npm run pipeline -- [args]` | Run auto-rig or retarget pipeline |
| `npm run batch -- jobs.json` | Run batch processing |
| `npm run docker:build` | Build the Blender Docker image |
| `npm run docker:gpu-info` | Check GPU/CUDA availability |
| `npm run docker:shell` | Start interactive shell in container |
| `npm run docker:version` | Show Blender version |
| `npm test` | Run integration test suite |
| `npm run lint` | Lint JavaScript files |

## Pipeline Usage

### Auto-Rig a Mesh

Add a humanoid skeleton to any mesh:

```bash
npm run pipeline -- --mesh character.obj --output rigged.glb
```

Options:
- `--rig-type basic|rigify|metarig` - Type of rig (default: basic with 23 bones)
- `--scale 0.01` - Scale factor for the mesh

### Retarget Animation

Apply mocap animation to a rigged mesh:

```bash
npm run pipeline -- --mesh avatar.glb --animation motion.bvh --output animated.glb
```

Options:
- `--fps 30` - Frames per second
- `--mapping bone_map.json` - Custom bone name mapping
- `--no-root-motion` - Disable root translation

### Full Pipeline

Mesh without rig + animation → animated mesh (auto-detects need for rigging):

```bash
npm run pipeline -- --mesh raw_mesh.obj --animation dance.bvh --output final.glb
```

### Batch Processing

Process multiple files with concurrency control:

```bash
npm run batch -- jobs.json --concurrency 4
```

**jobs.json format:**
```json
[
  { "type": "auto-rig", "meshPath": "mesh1.obj", "outputPath": "rigged1.glb" },
  { "type": "retarget", "targetPath": "avatar.glb", "animationPath": "walk.bvh", "outputPath": "walk.glb" },
  { "type": "full", "meshPath": "mesh.obj", "animationPath": "dance.bvh", "outputPath": "animated.glb" }
]
```

## Direct Docker Commands

For advanced usage or custom scripts:

```bash
# Run default script with GPU
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run

# Run specific script
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --script my_script.py

# Check GPU availability
docker run --rm --gpus all blender-headless --gpu-info

# Interactive shell for debugging
docker run --rm -it --gpus all -v $(pwd):/workspace blender-headless --shell

# Auto-rig directly
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/auto_rig_and_export.py -- \
    --input /workspace/character.obj --output /workspace/rigged.glb

# Retarget directly
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/retarget_and_export.py -- \
    --target /workspace/avatar.glb \
    --source /workspace/motion.bvh \
    --output /workspace/animated.glb
```

## Programmatic Usage

```javascript
const { runAutoRig, runRetarget, runFullPipeline, runBatch } = require('./pipeline_runner');

// Auto-rig
const result = await runAutoRig({
  meshPath: 'character.obj',
  outputPath: 'rigged.glb',
  rigType: 'basic'
});

// Retarget
const result = await runRetarget({
  targetPath: 'avatar.glb',
  animationPath: 'motion.bvh',
  outputPath: 'animated.glb'
});

// Full pipeline
const result = await runFullPipeline({
  meshPath: 'mesh.obj',
  animationPath: 'motion.bvh',
  outputPath: 'final.glb'
});

console.log(result.success ? `Output: ${result.outputPath}` : `Error: ${result.error}`);
```

## Writing Custom Blender Scripts

Create a `script.py` in your workspace:

```python
import bpy
import os

WORKSPACE = "/workspace"

def setup_gpu():
    """Enable GPU rendering with CUDA."""
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

def main():
    setup_gpu()
    
    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Create mesh
    bpy.ops.mesh.primitive_monkey_add(size=2)
    
    # Export (Blender 4.x compatible)
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(WORKSPACE, "output.glb"),
        export_apply=True
    )
    
    print("Export complete!")

if __name__ == "__main__":
    main()
```

Run with:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run
```

## Supported Export Formats

- **FBX** (`.fbx`) - `bpy.ops.export_scene.fbx()`
- **glTF/GLB** (`.gltf`, `.glb`) - `bpy.ops.export_scene.gltf()`
- **OBJ** (`.obj`) - `bpy.ops.wm.obj_export()`
- **USD** (`.usd`, `.usda`, `.usdc`) - `bpy.ops.wm.usd_export()`
- **Alembic** (`.abc`) - `bpy.ops.wm.alembic_export()`
- **STL** (`.stl`) - `bpy.ops.wm.stl_export()`
- **PLY** (`.ply`) - `bpy.ops.wm.ply_export()`

## Troubleshooting

### GPU Not Detected

```bash
# Verify NVIDIA Container Toolkit is working
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi

# If this fails, reinstall nvidia-container-toolkit
sudo apt-get install --reinstall nvidia-container-toolkit
sudo systemctl restart docker
```

### Docker Permission Denied

```bash
sudo usermod -aG docker $USER
# Restart your terminal/WSL session
```

### Permission Issues with Output Files

Output files are created as root. Fix with:
```bash
# Option 1: Run container as current user
docker run --rm --gpus all --user $(id -u):$(id -g) -v $(pwd):/workspace blender-headless --run

# Option 2: Fix permissions after
sudo chown -R $(id -u):$(id -g) ./output*
```

### Memory Issues

For large scenes:
```bash
docker run --rm --gpus all --memory=16g --memory-swap=32g -v $(pwd):/workspace blender-headless --run
```

### Blender 4.x API Note

The `apply_modifiers` parameter was removed in Blender 4.x FBX export. Use `apply_scale_options='FBX_SCALE_ALL'` instead.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BLENDER_SCRIPT` | `script.py` | Default Python script to execute |
| `BLENDER_ARGS` | `` | Additional arguments passed to Blender |
| `LOG_LEVEL` | `info` | Logging level (debug, info, warn, error) |

## Project Structure

```
.
├── Dockerfile               # Container definition (6.4GB image)
├── entrypoint.sh            # Container entrypoint
├── pipeline_runner.js       # Node.js orchestration
├── auto_rig_and_export.py   # Auto-rigging script
├── retarget_and_export.py   # Animation retargeting script
├── scripts/
│   ├── bootstrap.sh         # Environment setup
│   └── test-pipeline.sh     # Integration tests
├── examples/
│   ├── script.py            # Example Blender script
│   └── sample_walk.bvh      # Sample animation
└── output/                  # Generated files
```

## License

This Dockerfile and associated scripts are provided as-is. Blender is licensed under the GPL.
