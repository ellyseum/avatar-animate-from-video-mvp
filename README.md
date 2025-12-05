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

## FrankMocap Integration

This project includes a build script for [FrankMocap](https://github.com/facebookresearch/frankmocap), a 3D human pose estimation system. The build script has been updated to work with modern GPUs (RTX 40xx, 50xx, Blackwell architecture) even though the original repository was archived in October 2023.

### FrankMocap Docker Container

A ready-to-use Docker container for headless GPU-based motion capture inference:

```bash
# Build the container (from project root)
docker build -t frankmocap-gpu -f frankmocap/Dockerfile .

# Check GPU availability
docker run --rm --gpus all frankmocap-gpu --gpu-info

# Process a single video (body only)
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v /path/to/output:/workspace/output \
  -v /path/to/smpl_models:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_path /workspace/input/video.mp4 \
  --out_dir /workspace/output

# Batch process a directory (full body+hands)
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v /path/to/output:/workspace/output \
  -v /path/to/smpl_models:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_dir /workspace/input \
  --out_dir /workspace/output \
  --mode full

# Export mesh data with predictions
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v /path/to/output:/workspace/output \
  -v /path/to/smpl_models:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_path /workspace/input/dance.mp4 \
  --out_dir /workspace/output \
  --save_mesh --save_pred_pkl
```

**Container specifications:**
- Base image: `nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04`
- PyTorch: 2.10+ nightly with CUDA 12.8 (Blackwell/RTX 50 series support)
- Image size: ~36GB
- Supports: body, hand, and full (body+hands) motion capture modes

### Building FrankMocap

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

### What the Build Script Handles

- **GPU/CUDA Detection**: Automatically detects your GPU and CUDA version
- **Modern PyTorch**: Installs PyTorch 2.x with appropriate CUDA support
- **Compatibility Patches**: Fixes deprecated APIs for Python 3.10+ and numpy 2.x
- **Detectron2**: Builds from source for hand detection
- **PyTorch3D**: Builds from source for rendering
- **CPU Fallback**: Gracefully falls back to CPU if GPU fails
- **Headless Rendering**: Supports xvfb or pytorch3d for servers without displays

### Running FrankMocap

After installation:

```bash
# Activate conda environment
conda activate frankmocap
cd frankmocap

# Body motion capture
python run_frankmocap.py body --input_path ./sample_data/han_short.mp4 --out_dir ./output

# Hand motion capture
python run_frankmocap.py hand --input_path ./sample_data/han_hand_short.mp4 --out_dir ./output

# Full body + hands
python run_frankmocap.py full --input_path ./sample_data/han_short.mp4 --out_dir ./output

# Headless mode (on servers without display)
xvfb-run -a python run_frankmocap.py body --input_path ./sample_data/han_short.mp4 --out_dir ./output
```

### SMPL/SMPLX Models

FrankMocap requires SMPL and SMPLX body models which must be downloaded manually:

1. **SMPL**: Download from https://smplify.is.tue.mpg.de/ (registration required)
2. **SMPLX**: Download from https://smpl-x.is.tue.mpg.de/ (registration required)

See `frankmocap/DOWNLOAD_SMPL_MODELS.md` for detailed instructions.

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
├── build_frankmocap.sh      # FrankMocap build for modern GPUs
├── scripts/
│   ├── bootstrap.sh         # Environment setup
│   └── test-pipeline.sh     # Integration tests
├── examples/
│   ├── script.py            # Example Blender script
│   └── sample_walk.bvh      # Sample animation
└── output/                  # Generated files
```

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0)** for non-commercial research purposes only.

See the [LICENSE](LICENSE) file for details.

### Third-Party Licenses

- **Blender**: GPL
- **FrankMocap**: CC-BY-NC 4.0 (Facebook Research)
- **SMPL/SMPL-X models**: Separate license required from https://smpl.is.tue.mpg.de/
- **Detectron2**: Apache 2.0 (Facebook Research)

## Research Attributions

This project builds upon the following research works. If you use this software in your research, please cite the original papers:

<details>
<summary>BibTeX Citations</summary>

```bibtex
@inproceedings{rong2021frankmocap,
  title={FrankMocap: A Monocular 3D Whole-Body Pose Estimation System},
  author={Rong, Yu and Shiratori, Takaaki and Joo, Hanbyul},
  booktitle={IEEE International Conference on Computer Vision Workshops},
  year={2021}
}

@article{SMPL:2015,
  author = {Loper, Matthew and Mahmood, Naureen and Romero, Javier and 
            Pons-Moll, Gerard and Black, Michael J.},
  title = {{SMPL}: A Skinned Multi-Person Linear Model},
  journal = {ACM Trans. Graphics (Proc. SIGGRAPH Asia)},
  volume = {34},
  number = {6},
  pages = {248:1--248:16},
  year = {2015}
}

@inproceedings{SMPL-X:2019,
  title = {Expressive Body Capture: {3D} Hands, Face, and Body from a Single Image},
  author = {Pavlakos, Georgios and Choutas, Vasileios and Ghorbani, Nima and 
            Bolkart, Timo and Osman, Ahmed A. A. and Tzionas, Dimitrios and 
            Black, Michael J.},
  booktitle = {Proceedings IEEE Conf. on Computer Vision and Pattern Recognition (CVPR)},
  year = {2019}
}

@inproceedings{joo2020eft,
  title={Exemplar Fine-Tuning for 3D Human Model Fitting Towards In-the-Wild 3D Human Pose Estimation},
  author={Joo, Hanbyul and Neverova, Natalia and Vedaldi, Andrea},
  booktitle={3DV},
  year={2020}
}

@inproceedings{osokin2018lightweight,
  title={Real-time 2D Multi-Person Pose Estimation on CPU: Lightweight OpenPose},
  author={Osokin, Daniil},
  booktitle={ICPRAM},
  year={2018}
}

@inproceedings{shan2020understanding,
  title={Understanding Human Hands in Contact at Internet Scale},
  author={Shan, Dandan and Geng, Jiaqi and Shu, Michelle and Fouhey, David F.},
  booktitle={Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition},
  pages={9869--9878},
  year={2020}
}

@misc{wu2019detectron2,
  author = {Yuxin Wu and Alexander Kirillov and Francisco Massa and 
            Wan-Yen Lo and Ross Girshick},
  title = {Detectron2},
  howpublished = {\url{https://github.com/facebookresearch/detectron2}},
  year = {2019}
}
```

</details>
