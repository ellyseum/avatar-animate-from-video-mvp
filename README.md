# Headless Blender Microservice

A Docker-based headless Blender microservice with CUDA GPU acceleration support. This container runs Blender in background mode, executes Python scripts, and outputs results (FBX, glTF, images, etc.) to a mounted workspace directory.

## Features

- **Ubuntu 22.04 LTS** base with NVIDIA CUDA 12.2 runtime
- **Blender 4.2 LTS** (latest stable) with full Python API (`bpy`) support
- **GPU acceleration** via CUDA for Cycles rendering
- **Headless operation** - no display required
- **Flexible scripting** - run custom Python scripts with Blender's API
- **Volume mounting** - input/output through a shared workspace directory

## Prerequisites

### Host Requirements

1. **NVIDIA GPU** with CUDA support
2. **NVIDIA Driver** (version 525+ recommended for CUDA 12.x)
3. **Docker** (version 19.03+)
4. **NVIDIA Container Toolkit** installed and configured

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

## Building the Container

```bash
# Clone or navigate to this directory
cd /path/to/avatar-animate-from-video-mvp

# Build the Docker image
docker build -t blender-headless .

# Or with a specific tag
docker build -t blender-headless:4.2 .
```

## Usage

### Basic Commands

```bash
# Show help
docker run --rm blender-headless --help

# Show Blender version
docker run --rm blender-headless --version

# Check GPU availability and Blender GPU detection
docker run --rm --gpus all blender-headless --gpu-info
```

### Running Python Scripts

The primary use case is running Python scripts that use Blender's API:

```bash
# Run the default script (script.py) from mounted workspace
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless --run

# Run a specific script
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless --script my_script.py

# Pass additional arguments to Blender
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    -e BLENDER_ARGS="--debug-python" \
    blender-headless --run
```

### Rendering .blend Files

```bash
# Render all frames from a .blend file
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless --render scene.blend

# Render specific frames
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless -b /workspace/scene.blend -E CYCLES -s 1 -e 10 -a
```

### Interactive Shell (Debugging)

```bash
# Start an interactive shell in the container
docker run --rm -it \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless --shell

# Inside the container, you can run Blender manually
blender -b --python script.py
```

### Custom Blender Commands

Any unrecognized arguments are passed directly to Blender:

```bash
# Run Blender with custom arguments
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless -b /workspace/scene.blend --python /workspace/script.py
```

## Example Script (script.py)

Create a `script.py` in your workspace directory:

```python
"""
Example Blender Python script for the headless microservice.
This script demonstrates basic operations and exports.
"""

import bpy
import os
import sys

# Get the workspace directory
WORKSPACE = "/workspace"

def setup_gpu():
    """Enable GPU rendering with CUDA."""
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get('cycles')
    
    if cycles_prefs:
        cycles_prefs = cycles_prefs.preferences
        cycles_prefs.compute_device_type = 'CUDA'
        cycles_prefs.get_devices()
        
        # Enable all CUDA devices
        for device in cycles_prefs.devices:
            if device.type == 'CUDA':
                device.use = True
                print(f"Enabled GPU: {device.name}")
        
        # Set scene to use GPU
        bpy.context.scene.cycles.device = 'GPU'

def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

def create_example_mesh():
    """Create a simple example mesh."""
    # Add a monkey (Suzanne)
    bpy.ops.mesh.primitive_monkey_add(size=2, location=(0, 0, 0))
    monkey = bpy.context.active_object
    monkey.name = "ExampleMesh"
    
    # Add a subdivision modifier
    bpy.ops.object.modifier_add(type='SUBSURF')
    monkey.modifiers["Subdivision"].levels = 2
    
    return monkey

def export_fbx(filepath):
    """Export selected objects to FBX."""
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        apply_modifiers=True,
        path_mode='COPY',
        embed_textures=True
    )
    print(f"Exported FBX: {filepath}")

def export_gltf(filepath):
    """Export selected objects to glTF."""
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        use_selection=True,
        export_apply=True
    )
    print(f"Exported glTF: {filepath}")

def main():
    print("=" * 50)
    print("Blender Headless Microservice - Example Script")
    print("=" * 50)
    
    # Setup GPU
    setup_gpu()
    
    # Clear existing scene
    clear_scene()
    
    # Create example content
    mesh = create_example_mesh()
    
    # Select the mesh for export
    bpy.ops.object.select_all(action='DESELECT')
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    
    # Export to various formats
    export_fbx(os.path.join(WORKSPACE, "output.fbx"))
    export_gltf(os.path.join(WORKSPACE, "output.glb"))
    
    # Optional: Render an image
    # bpy.context.scene.render.filepath = os.path.join(WORKSPACE, "render.png")
    # bpy.ops.render.render(write_still=True)
    
    print("=" * 50)
    print("Script completed successfully!")
    print("=" * 50)

if __name__ == "__main__":
    main()
```

## Complete Example Workflow

```bash
# 1. Create a working directory
mkdir blender-workspace && cd blender-workspace

# 2. Create your script (see example above)
cat > script.py << 'EOF'
import bpy
import os

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Create a cube
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
cube = bpy.context.active_object

# Export as FBX
bpy.ops.export_scene.fbx(filepath="/workspace/cube.fbx")
print("Exported cube.fbx")
EOF

# 3. Build the container (if not already built)
docker build -t blender-headless /path/to/dockerfile/directory

# 4. Run the script
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless --run

# 5. Check the output
ls -la  # You should see cube.fbx
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BLENDER_SCRIPT` | `script.py` | Default Python script to execute |
| `BLENDER_ARGS` | `` | Additional arguments passed to Blender |

## Volume Mounts

| Container Path | Purpose |
|----------------|---------|
| `/workspace` | Main working directory for scripts, input files, and output files |

## Caveats and Troubleshooting

### GPU Not Detected

```bash
# Verify NVIDIA Container Toolkit is working
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi

# If this fails, reinstall nvidia-container-toolkit
sudo apt-get install --reinstall nvidia-container-toolkit
sudo systemctl restart docker
```

### Permission Issues with Output Files

Output files are created as root inside the container. To fix:

```bash
# Option 1: Run container as current user
docker run --rm \
    --gpus all \
    --user $(id -u):$(id -g) \
    -v $(pwd):/workspace \
    blender-headless --run

# Option 2: Fix permissions after run
sudo chown -R $(id -u):$(id -g) ./output*
```

### Memory Issues

For large scenes or renders, increase Docker memory limits:

```bash
docker run --rm \
    --gpus all \
    --memory=16g \
    --memory-swap=32g \
    -v $(pwd):/workspace \
    blender-headless --run
```

### Blender Add-ons

To use additional Blender add-ons, mount your add-ons directory:

```bash
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    -v /path/to/addons:/opt/blender/4.2/scripts/addons_contrib \
    blender-headless --run
```

### Headless Display Issues

Some Blender operations require a display. The container runs headless, but if you encounter issues:

```bash
# Run with virtual framebuffer (add to Dockerfile if needed)
docker run --rm \
    --gpus all \
    -e DISPLAY=:0 \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $(pwd):/workspace \
    blender-headless --run
```

### Debugging Scripts

```bash
# Enable Python debugging output
docker run --rm \
    --gpus all \
    -v $(pwd):/workspace \
    -e BLENDER_ARGS="--debug-python --debug-all" \
    blender-headless --run

# Or start interactive shell and test manually
docker run --rm -it \
    --gpus all \
    -v $(pwd):/workspace \
    blender-headless --shell
```

## Supported Export Formats

The container supports all Blender export formats, including:

- **FBX** (`.fbx`) - `bpy.ops.export_scene.fbx()`
- **glTF/GLB** (`.gltf`, `.glb`) - `bpy.ops.export_scene.gltf()`
- **OBJ** (`.obj`) - `bpy.ops.wm.obj_export()`
- **USD** (`.usd`, `.usda`, `.usdc`) - `bpy.ops.wm.usd_export()`
- **Alembic** (`.abc`) - `bpy.ops.wm.alembic_export()`
- **STL** (`.stl`) - `bpy.ops.wm.stl_export()`
- **PLY** (`.ply`) - `bpy.ops.wm.ply_export()`

## License

This Dockerfile and associated scripts are provided as-is. Blender is licensed under the GPL.
