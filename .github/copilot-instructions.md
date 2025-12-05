# Copilot Instructions - Headless Blender Microservice

## Project Overview

This is a Docker-based headless Blender microservice with CUDA GPU acceleration support. The container runs Blender in background mode, executes Python scripts, and outputs results (FBX, glTF, images, etc.) to a mounted workspace directory.

## Tech Stack

- **Base Image**: Ubuntu 22.04 LTS with NVIDIA CUDA 12.2 runtime (`nvidia/cuda:12.2.0-runtime-ubuntu22.04`)
- **Blender Version**: 4.2 LTS (latest stable) with full Python API (`bpy`) support
- **GPU Acceleration**: CUDA for Cycles rendering
- **Container Runtime**: Docker with NVIDIA Container Toolkit

## Project Structure

```
.
├── Dockerfile               # Main container definition
├── entrypoint.sh            # Container entrypoint script
├── README.md                # Documentation
├── package.json             # Node.js project configuration
├── auto_rig_and_export.py   # Auto-rigging pipeline script
├── retarget_and_export.py   # Animation retargeting script
├── pipeline_runner.js       # Node.js orchestration script
└── examples/
    └── script.py            # Example Blender Python script
```

## Key Files

### Dockerfile
- Uses NVIDIA CUDA base image for GPU support
- Installs Blender 4.2 LTS from official release
- Includes all dependencies: OpenEXR, FFmpeg codecs, image format libraries
- Installs additional Python packages (numpy, scipy, pillow, requests) in Blender's bundled Python
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

### auto_rig_and_export.py
Automated rigging pipeline script that:
- Imports mesh files (.obj, .fbx, .ply, .stl, .glb)
- Creates humanoid armature (basic or Rigify metarig)
- Applies automatic weights (heat map skinning)
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

### pipeline_runner.js
Node.js orchestration script for managing pipeline execution:
- Creates temporary workspaces and manages file copying
- Executes Docker commands for auto-rig and retarget pipelines
- Supports batch processing with configurable concurrency
- Job queue to prevent resource overload
- Comprehensive error handling and logging
- Cleans up temporary data after processing

CLI usage:
```bash
# Auto-rig a mesh
node pipeline_runner.js --mesh character.obj --output rigged.glb

# Retarget animation
node pipeline_runner.js --mesh avatar.glb --animation motion.bvh --output animated.glb

# Batch processing
node pipeline_runner.js --batch jobs.json --concurrency 4
```

Programmatic usage:
```javascript
const { runAutoRig, runRetarget, runFullPipeline, runBatch } = require('./pipeline_runner');

// Auto-rig
const result = await runAutoRig({ meshPath: 'mesh.obj', outputPath: 'rigged.glb' });

// Retarget
const result = await runRetarget({ targetPath: 'avatar.glb', animationPath: 'motion.bvh', outputPath: 'animated.glb' });

// Full pipeline
const result = await runFullPipeline({ meshPath: 'mesh.obj', animationPath: 'motion.bvh', outputPath: 'final.glb' });
```

### Environment Variables
- `BLENDER_SCRIPT` - Default script to run (default: `script.py`)
- `BLENDER_ARGS` - Additional arguments passed to Blender

## Building and Running

### Build Command
```bash
docker build -t blender-headless .
```

### NPM Scripts
```bash
# Install dependencies
npm install

# Build Docker image
npm run docker:build

# Check GPU
npm run docker:gpu-info

# Run pipeline
npm run pipeline -- --mesh mesh.obj --output rigged.glb

# Batch processing
npm run batch -- jobs.json --concurrency 4

# Lint code
npm run lint
```

### Run Commands
```bash
# Run default script with GPU
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run

# Run specific script
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --script my_script.py

# Check GPU availability
docker run --rm --gpus all blender-headless --gpu-info

# Interactive shell for debugging
docker run --rm -it --gpus all -v $(pwd):/workspace blender-headless --shell

# Run as current user (fixes permission issues)
docker run --rm --gpus all --user $(id -u):$(id -g) -v $(pwd):/workspace blender-headless --run

# Auto-rig a mesh
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/auto_rig_and_export.py -- \
    --input /workspace/character.obj --output /workspace/rigged.glb
```

## Usage Examples

### Example 1: Basic Script Execution
Run a simple Blender Python script that creates and exports a mesh:
```bash
# Create a script.py in your workspace, then run:
docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run
```

### Example 2: Auto-Rig a Character Mesh
Import an OBJ file, add a humanoid skeleton, apply automatic weights, and export as glTF:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/auto_rig_and_export.py -- \
    --input /workspace/character.obj \
    --output /workspace/character_rigged.glb
```

### Example 3: Auto-Rig with Rigify Metarig
Use Rigify metarig for more advanced rigging (IK controls, etc.):
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/auto_rig_and_export.py -- \
    --input /workspace/human_mesh.fbx \
    --output /workspace/rigged_character.fbx \
    --rig-type metarig \
    --scale 0.01
```

### Example 4: Auto-Rig with Logging
Run auto-rigging with detailed logging to a file:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/auto_rig_and_export.py -- \
    --input /workspace/mesh.obj \
    --output /workspace/rigged.glb \
    --log-file /workspace/rigging.log
```

### Example 5: Render a .blend File
Render all frames from a Blender project file:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    --render scene.blend
```

### Example 6: Batch Processing Multiple Files
Process multiple meshes in a loop:
```bash
for mesh in /workspace/meshes/*.obj; do
    docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
        -b --python /workspace/auto_rig_and_export.py -- \
        --input "$mesh" \
        --output "/workspace/output/$(basename "$mesh" .obj).glb"
done
```

### Example 7: Custom Blender Commands
Pass any Blender command-line arguments directly:
```bash
# Render specific frames
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b /workspace/scene.blend -E CYCLES -s 1 -e 100 -a

# Run Python expression
docker run --rm --gpus all blender-headless \
    -b --python-expr "import bpy; print(bpy.app.version_string)"
```

### Example 8: Retarget Animation to Avatar
Apply mocap animation from a BVH file to a rigged avatar:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/retarget_and_export.py -- \
    --target /workspace/avatar.glb \
    --source /workspace/motion.bvh \
    --output /workspace/animated_avatar.glb
```

### Example 9: Retarget with Custom Bone Mapping
Use a custom JSON mapping file for non-standard bone names:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/retarget_and_export.py -- \
    --target /workspace/avatar.fbx \
    --source /workspace/mocap.fbx \
    --output /workspace/animated.fbx \
    --mapping /workspace/bone_mapping.json \
    --fps 60
```

### Example 10: Retarget with Frame Range
Retarget only a specific frame range:
```bash
docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
    -b --python /workspace/retarget_and_export.py -- \
    --target /workspace/avatar.glb \
    --source /workspace/long_animation.bvh \
    --output /workspace/clip.glb \
    --start-frame 100 \
    --end-frame 200 \
    --no-root-motion
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

### Export Functions
```python
# FBX Export
bpy.ops.export_scene.fbx(
    filepath="/workspace/output.fbx",
    use_selection=True,
    apply_modifiers=True
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

### Memory Issues
For large scenes, increase Docker memory:
```bash
docker run --rm --gpus all --memory=16g --memory-swap=32g -v $(pwd):/workspace blender-headless --run
```

### Using Custom Add-ons
Mount add-ons directory:
```bash
docker run --rm --gpus all \
    -v $(pwd):/workspace \
    -v /path/to/addons:/opt/blender/4.2/scripts/addons_contrib \
    blender-headless --run
```

## Code Style Guidelines

When writing Blender Python scripts for this container:
1. Always use `/workspace` as the base path for input/output
2. Include GPU setup at the start of scripts
3. Use `Path` from `pathlib` for file path handling
4. Add print statements for progress logging (visible in Docker output)
5. Handle missing GPU gracefully (fallback to CPU)
6. Create output directories with `Path.mkdir(parents=True, exist_ok=True)`

## Prerequisites for Host Machine

1. NVIDIA GPU with CUDA support
2. NVIDIA Driver (version 525+ for CUDA 12.x)
3. Docker (version 19.03+)
4. NVIDIA Container Toolkit installed and configured

## Maintaining This Document

**Keep these instructions up to date as the project evolves.** When making changes to the project:

1. **New dependencies**: Update the Tech Stack and Dockerfile sections when adding new packages or changing versions
2. **New scripts/files**: Add them to the Project Structure section with descriptions
3. **New entrypoint modes**: Document any new command-line options in the entrypoint.sh section
4. **New environment variables**: Add them to the Environment Variables section
5. **New export formats or Blender operations**: Add code patterns to the Writing Blender Python Scripts section
6. **Discovered issues**: Add solutions to the Common Issues and Solutions section
7. **API changes**: Update code examples when Blender API or project APIs change
8. **New features or workflows**: Add practical usage examples to the Usage Examples section with clear descriptions

**Always add usage examples** when introducing new functionality. Examples should:
- Show the complete `docker run` command
- Include all required arguments
- Demonstrate common use cases and variations
- Be copy-paste ready for users

This document serves as the primary context for AI assistants (Copilot) working on this project. Accurate, current documentation ensures better code suggestions and fewer errors.

## Keeping README.md in Sync

The `README.md` file is the public-facing documentation for this project. **Always update `README.md` alongside this file** when making significant changes:

1. **Keep both files consistent**: Changes to build commands, usage examples, or troubleshooting should be reflected in both files
2. **README is user-focused**: Write for end users who want to quickly build and run the container
3. **Copilot instructions are developer-focused**: Include more technical details, code patterns, and internal context here
4. **Update examples**: When adding new features, add corresponding examples to both files
5. **Version bumps**: Update version numbers in both files when upgrading Blender or base images

When in doubt, update both files to prevent documentation drift.
