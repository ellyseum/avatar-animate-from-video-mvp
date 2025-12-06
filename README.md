# Avatar Animate from Video MVP

A Docker-based pipeline for extracting motion capture from video and applying it to 3D avatars. Includes headless Blender for rigging/animation and FrankMocap for video-to-mocap extraction.

## Features

- **FrankMocap GPU Container** - Extract 3D body/hand motion from video using GPU acceleration
- **Blender Headless Container** - Auto-rig meshes and retarget animations
- **Modern GPU Support** - Tested with RTX 5080 (Blackwell), CUDA 12.8
- **Multi-stage Docker builds** - Efficient caching for fast rebuilds
- **Node.js orchestration** - npm scripts for easy pipeline management

## Prerequisites

1. **NVIDIA GPU** with CUDA support
2. **NVIDIA Driver** (version 525+ for CUDA 12.x)
3. **Docker** (version 19.03+)
4. **NVIDIA Container Toolkit**
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

Verify GPU access:
```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-runtime-ubuntu22.04 nvidia-smi
```

## Quick Start

```bash
# 1. Clone and enter the directory
git clone https://github.com/ellyseum/avatar-animate-from-video-mvp.git
cd avatar-animate-from-video-mvp

# 2. Download SMPL models (see SMPL Setup section below)

# 3. Build Docker images
npm run frank:build      # FrankMocap container (~36GB, ~20min)
npm run docker:build     # Blender container (~6GB)

# 4. Test GPU access
npm run frank:gpu-info

# 5. Extract mocap from video
npm run frank:run -- --input_path /workspace/input/video.mp4 --out_dir /workspace/output
```

## SMPL Model Setup

FrankMocap requires SMPL/SMPLX body models which must be downloaded manually due to licensing.

### Required Models

| Model | File | Download URL |
|-------|------|--------------|
| SMPL Neutral | `basicModel_neutral_lbs_10_207_0_v1.0.0.pkl` | https://smplify.is.tue.mpg.de/ |
| SMPLX Neutral | `SMPLX_NEUTRAL.pkl` | https://smpl-x.is.tue.mpg.de/ |

### Setup Steps

1. Register at both sites (free for research)
2. Download the model files
3. Place them in the `smpl/` directory at project root:

```
avatar-animate-from-video-mvp/
└── smpl/
    ├── basicModel_neutral_lbs_10_207_0_v1.0.0.pkl
    └── SMPLX_NEUTRAL.pkl
```

### Verify Setup

```bash
ls -la smpl/
# Should show both .pkl files
```

## NPM Scripts

### FrankMocap (Motion Capture)

| Script | Description |
|--------|-------------|
| `npm run frank:build` | Build FrankMocap Docker image |
| `npm run frank:gpu-info` | Check GPU/CUDA availability |
| `npm run frank:shell` | Interactive shell in container |
| `npm run frank:run -- [args]` | Run mocap on video |

### Blender (Rigging/Animation)

| Script | Description |
|--------|-------------|
| `npm run docker:build` | Build Blender Docker image |
| `npm run docker:gpu-info` | Check GPU availability |
| `npm run docker:shell` | Interactive shell in container |
| `npm run pipeline -- [args]` | Run auto-rig or retarget |

## FrankMocap Usage

### Extract Body Motion from Video

```bash
# Mount your video directory and run
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v /path/to/output:/workspace/output \
  -v $(pwd)/smpl:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_path /workspace/input/dance.mp4 \
  --out_dir /workspace/output \
  --save_pred_pkl
```

### Modes

- `--mode body` - Body only (default)
- `--mode hand` - Hands only  
- `--mode full` - Full body + hands

### Options

- `--save_pred_pkl` - Save prediction as pickle file
- `--save_mesh` - Save 3D mesh outputs (.obj)
- `--no_render` - Skip rendering visualizations

### Batch Processing

```bash
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v /path/to/output:/workspace/output \
  -v $(pwd)/smpl:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_dir /workspace/input \
  --out_dir /workspace/output \
  --mode full
```

## Blender Pipeline Usage

### Auto-Rig a Mesh

```bash
npm run pipeline -- --mesh character.obj --output rigged.glb
```

### Retarget Animation

```bash
npm run pipeline -- --mesh avatar.glb --animation motion.bvh --output animated.glb
```

### Full Pipeline

```bash
npm run pipeline -- --mesh raw_mesh.obj --animation dance.bvh --output final.glb
```

## Project Structure

```
.
├── Dockerfile               # Blender container
├── frankmocap/
│   ├── Dockerfile           # FrankMocap container (multi-stage)
│   ├── entrypoint_frankmocap.sh
│   └── build_frankmocap_docker.sh
├── smpl/                    # SMPL models (you provide)
│   ├── basicModel_neutral_lbs_10_207_0_v1.0.0.pkl
│   └── SMPLX_NEUTRAL.pkl
├── pipeline_runner.js       # Node.js orchestration
├── auto_rig_and_export.py   # Blender auto-rig script
├── retarget_and_export.py   # Animation retargeting script
├── scripts/
│   ├── bootstrap.sh
│   └── test-pipeline.sh
└── output/                  # Generated files
```

## Troubleshooting

### GPU Not Detected

```bash
# Verify NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:12.8.0-runtime-ubuntu22.04 nvidia-smi

# If fails, reinstall
sudo apt-get install --reinstall nvidia-container-toolkit
sudo systemctl restart docker
```

### Docker Permission Denied

```bash
sudo usermod -aG docker $USER
# Restart terminal/WSL session
```

### Memory Issues

```bash
docker run --rm --gpus all --memory=16g --memory-swap=32g ...
```

### WSL Path Notes

Windows paths in WSL: `/mnt/c/Users/username/Downloads`

## License

**Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**

For non-commercial research purposes only. See [LICENSE](LICENSE) for details.

### Third-Party Licenses

- **Blender**: GPL
- **FrankMocap**: CC-BY-NC 4.0 (Facebook Research)
- **SMPL/SMPL-X**: Separate license from https://smpl.is.tue.mpg.de/
- **Detectron2**: Apache 2.0

## Citations

If you use this in research, please cite:

<details>
<summary>BibTeX</summary>

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
  year = {2015}
}

@inproceedings{SMPL-X:2019,
  title = {Expressive Body Capture: {3D} Hands, Face, and Body from a Single Image},
  author = {Pavlakos, Georgios and Choutas, Vasileios and others},
  booktitle = {CVPR},
  year = {2019}
}
```

</details>
