# Copilot Instructions - Avatar Animate from Video MVP

## Project Overview

Docker-based pipeline for extracting motion capture from video and applying it to 3D avatars. Two main containers:
1. **FrankMocap** - GPU-accelerated video-to-mocap extraction
2. **Blender Headless** - Auto-rigging and animation retargeting

## Tech Stack

- **FrankMocap Container**: CUDA 12.8, PyTorch 2.10+ nightly, Python 3.10
- **Blender Container**: CUDA 12.2, Blender 4.2.3 LTS, Python 3.11
- **GPU**: Tested with RTX 5080 (Blackwell, sm_120)
- **Orchestration**: Node.js 18+ with npm scripts

## Project Structure

```
.
├── Dockerfile               # Blender container (6.4GB)
├── entrypoint.sh            # Blender entrypoint
├── frankmocap/
│   ├── Dockerfile           # FrankMocap multi-stage build (36GB)
│   ├── entrypoint_frankmocap.sh
│   └── build_frankmocap_docker.sh
├── smpl/                    # SMPL models (user-provided)
│   ├── basicModel_neutral_lbs_10_207_0_v1.0.0.pkl
│   └── SMPLX_NEUTRAL.pkl
├── pipeline_runner.js       # Node.js orchestration
├── auto_rig_and_export.py   # Blender auto-rig script
├── retarget_and_export.py   # Animation retargeting script
├── scripts/
│   ├── bootstrap.sh
│   └── test-pipeline.sh
├── examples/
│   ├── script.py
│   └── sample_walk.bvh
└── output/                  # Generated files
```

## FrankMocap Docker (frankmocap/Dockerfile)

Multi-stage build with 9 cacheable stages:

| Stage | Purpose |
|-------|---------|
| base | System deps, Python 3.10 |
| pytorch | PyTorch nightly + CUDA 12.8 |
| pydeps | Python packages + chumpy patch |
| detectron2 | Detectron2 from source |
| pytorch3d | PyTorch3D with GPU (FORCE_CUDA=1) |
| frankmocap | Clone repo + patches |
| detectors | Third-party pose estimators |
| models | Download pretrained models |
| final | Entrypoint + runtime |

**Key environment variables for pytorch3d:**
```dockerfile
ENV FORCE_CUDA=1
ENV TORCH_CUDA_ARCH_LIST="7.0;7.5;8.0;8.6;8.9;9.0;12.0"
```

**Compatibility patches applied:**
- chumpy: `from numpy import bool, int...` → `from numpy import nan, inf`
- group_keypoints: Remove `demo=True` argument
- CPU fallback: Replace assert with warning

## NPM Scripts

```json
{
  "frank:build": "docker build -t frankmocap-gpu -f frankmocap/Dockerfile .",
  "frank:gpu-info": "docker run --rm --gpus all frankmocap-gpu --gpu-info",
  "frank:shell": "docker run --rm -it --gpus all -v $(pwd)/smpl:/opt/frankmocap/extra_data/smpl frankmocap-gpu --shell",
  "frank:run": "docker run --rm --gpus all -v $(pwd)/smpl:/opt/frankmocap/extra_data/smpl -v $(pwd)/output:/workspace/output frankmocap-gpu",
  "docker:build": "docker build -t blender-headless .",
  "docker:gpu-info": "docker run --rm --gpus all blender-headless --gpu-info",
  "docker:shell": "docker run --rm -it --gpus all -v $(pwd):/workspace blender-headless --shell"
}
```

## SMPL Models

**Location**: `./smpl/` at project root (mounted to `/opt/frankmocap/extra_data/smpl` in container)

**Required files:**
- `basicModel_neutral_lbs_10_207_0_v1.0.0.pkl` - SMPL neutral (body)
- `SMPLX_NEUTRAL.pkl` - SMPLX neutral (hands/face)

## Running FrankMocap

```bash
# Basic body mocap
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v $(pwd)/output:/workspace/output \
  -v $(pwd)/smpl:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_path /workspace/input/video.mp4 \
  --out_dir /workspace/output \
  --save_pred_pkl

# Full body + hands
docker run --rm --gpus all \
  -v /path/to/videos:/workspace/input \
  -v $(pwd)/output:/workspace/output \
  -v $(pwd)/smpl:/opt/frankmocap/extra_data/smpl \
  frankmocap-gpu \
  --input_dir /workspace/input \
  --out_dir /workspace/output \
  --mode full
```

## Common Issues & Fixes

### pytorch3d "Not compiled with GPU support"
- Ensure `FORCE_CUDA=1` is set before pip install
- Set `TORCH_CUDA_ARCH_LIST` for target GPU architectures

### chumpy numpy compatibility
```bash
sed -i 's/from numpy import bool, int, float, complex, object, unicode, str, nan, inf/from numpy import nan, inf/' chumpy/__init__.py
```

### group_keypoints demo argument
```bash
sed -i 's/group_keypoints(all_keypoints_by_type, pafs, demo=True)/group_keypoints(all_keypoints_by_type, pafs)/g' bodymocap/body_bbox_detector.py
```

### WSL Windows paths
Windows `C:\Users\jocel\Downloads` → WSL `/mnt/c/Users/jocel/Downloads`

## Validated Workflows (Dec 5, 2025)

1. **FrankMocap body mocap** - Extracts SMPL parameters from video ✅
2. **FrankMocap full mocap** - Body + hands extraction ✅
3. **Blender auto-rig** - Adds humanoid skeleton to mesh ✅
4. **Blender retarget** - Applies BVH animation to rigged mesh ✅

## Maintaining This Document

Update when:
- New Docker build stages added
- New npm scripts added
- New compatibility patches discovered
- Workflow validated on new hardware
