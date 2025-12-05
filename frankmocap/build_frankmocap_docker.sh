#!/bin/bash
# =============================================================================
# Docker-adapted FrankMocap Build
# =============================================================================
# This wrapper uses logic from build_frankmocap.sh but adapted for Docker:
# - No conda (use system Python 3.10 directly)
# - Install dir: /opt/frankmocap
# - Simpler error handling for container builds
# =============================================================================

set -e

echo "=============================================="
echo "FrankMocap Docker Build"
echo "=============================================="

INSTALL_DIR="/opt/frankmocap"
BODY_ONLY="${BODY_ONLY:-false}"
LOG_FILE="/tmp/frankmocap_build.log"

# Logging functions
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
info() { log "INFO: $1"; }
warn() { log "WARN: $1"; }
error() { log "ERROR: $1"; exit 1; }

# =============================================================================
# Install PyTorch (from build_frankmocap.sh install_pytorch)
# =============================================================================
info "Installing PyTorch NIGHTLY with CUDA 12.8 for Blackwell GPU support..."
info "Note: Blackwell (sm_120) requires nightly builds until PyTorch 2.6+ stable release."
pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128

# Verify installation
python -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA version: {torch.version.cuda}')
" | tee -a "$LOG_FILE"

# =============================================================================
# Clone FrankMocap (from build_frankmocap.sh clone_frankmocap)
# =============================================================================
info "Cloning FrankMocap from ellyseum fork..."
if [[ ! -d "$INSTALL_DIR" ]]; then
    git clone https://github.com/ellyseum/frankmocap.git "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# =============================================================================
# Install Python Dependencies (from build_frankmocap.sh install_python_deps)
# =============================================================================
info "Installing Python dependencies..."

# Create and install from requirements (mirrors build_frankmocap.sh requirements_modern.txt)
pip install --no-cache-dir \
    "numpy>=1.21.0,<2.0" \
    "scipy>=1.7.0" \
    "opencv-python>=4.5.0" \
    "pillow>=9.0.0" \
    "scikit-image>=0.19.0" \
    "matplotlib>=3.5.0" \
    "tqdm>=4.60.0" \
    "yacs>=0.1.8" \
    "tensorboardX>=2.4" \
    "einops>=0.4.0" \
    "kornia>=0.6.0" \
    "trimesh>=3.10.0" \
    "PyOpenGL==3.1.0" \
    "pyrender>=0.1.45" \
    "smplx>=0.1.28" \
    "imageio>=2.14.0" \
    "imageio-ffmpeg>=0.4.5" \
    "pycocotools" \
    "fvcore" \
    "iopath" \
    "omegaconf" \
    "hydra-core" \
    "gdown"

# Install chumpy (from build_frankmocap.sh install_chumpy)
info "Installing chumpy..."
pip install --no-build-isolation chumpy 2>/dev/null || {
    warn "chumpy pip install failed, creating minimal stub..."
    SITE_PACKAGES=$(python -c "import site; print(site.getsitepackages()[0])")
    mkdir -p "${SITE_PACKAGES}/chumpy"
    cat > "${SITE_PACKAGES}/chumpy/__init__.py" << 'STUBEOF'
import numpy as np
class Ch(np.ndarray):
    pass
def array(*args, **kwargs):
    return np.array(*args, **kwargs)
STUBEOF
}

# =============================================================================
# Install Detectron2 (from build_frankmocap.sh install_detectron2)
# =============================================================================
info "Installing Detectron2 from source..."
if [[ ! -d "/opt/detectron2" ]]; then
    git clone https://github.com/facebookresearch/detectron2.git /opt/detectron2
    cd /opt/detectron2
    pip install --no-build-isolation -e .
fi
cd "$INSTALL_DIR"

# =============================================================================
# Download Models (from build_frankmocap.sh download_body_module_data)
# =============================================================================
info "Downloading pretrained models..."

# Body module
mkdir -p extra_data/body_module/pretrained_weights
cd extra_data/body_module

wget -q https://dl.fbaipublicfiles.com/eft/2020_05_31-00_50_43-best-51.749683916568756.pt \
     -O pretrained_weights/2020_05_31-00_50_43-best-51.749683916568756.pt 2>/dev/null || warn "Failed to download body model checkpoint"

wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/body_module/smplx-03-28-46060-w_spin_mlc3d_46582-2089_2020_03_28-21_56_16.pt \
     -O pretrained_weights/smplx-03-28-46060-w_spin_mlc3d_46582-2089_2020_03_28-21_56_16.pt 2>/dev/null || warn "Failed to download SMPLX model"

wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/body_module/J_regressor_extra_smplx.npy 2>/dev/null || warn "Failed to download J_regressor"

# SPIN data
if [[ ! -d "data_from_spin" ]]; then
    info "Downloading SPIN data..."
    # Note: Despite .tar.gz extension, file is actually uncompressed tar
    wget -q https://visiondata.cis.upenn.edu/spin/data.tar.gz 2>/dev/null && \
    tar -xf data.tar.gz && rm -f data.tar.gz && \
    mv data data_from_spin 2>/dev/null || warn "Failed to download SPIN data"
fi

# Body pose estimator
mkdir -p body_pose_estimator
wget -q https://download.01.org/opencv/openvino_training_extensions/models/human_pose_estimation/checkpoint_iter_370000.pth \
     -O body_pose_estimator/checkpoint_iter_370000.pth 2>/dev/null || warn "Failed to download pose estimator"

cd "$INSTALL_DIR"

# Hand module (from build_frankmocap.sh download_hand_module_data)
if [[ "$BODY_ONLY" != "true" ]]; then
    info "Downloading hand module data..."
    mkdir -p extra_data/hand_module/pretrained_weights
    cd extra_data/hand_module
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/SMPLX_HAND_INFO.pkl 2>/dev/null || true
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/mean_mano_params.pkl 2>/dev/null || true
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/checkpoints_best/pose_shape_best.pth \
         -O pretrained_weights/pose_shape_best.pth 2>/dev/null || true

    # Hand detector weights (using gdown for Google Drive)
    mkdir -p hand_detector
    cd hand_detector
    gdown "https://drive.google.com/uc?id=1H2tWsZkS7tDF8q1-jdjx6V9XrK25EDbE" 2>/dev/null || warn "Failed to download hand detector model"
    gdown "https://drive.google.com/uc?id=1OqgexNM52uxsPG3i8GuodDOJAGFsYkPg" 2>/dev/null || warn "Failed to download hand detector config"
    cd "$INSTALL_DIR"
fi

# =============================================================================
# Install Detectors (from build_frankmocap.sh install_detectors)
# =============================================================================
info "Installing third-party detectors..."
mkdir -p detectors
cd detectors

# Body pose estimator (lightweight-human-pose-estimation)
git clone https://github.com/Daniil-Osokin/lightweight-human-pose-estimation.pytorch.git \
    body_pose_estimator 2>/dev/null || warn "Failed to clone body pose estimator"

# Hand detection (only if not body-only)
if [[ "$BODY_ONLY" != "true" ]]; then
    # Hand object detector (ellyseum fork with PyTorch 2.x fixes)
    git clone https://github.com/ellyseum/hand_object_detector.git 2>/dev/null || warn "Failed to clone hand detector"
    if [[ -d "hand_object_detector/lib" ]]; then
        cd hand_object_detector/lib
        python setup.py build 2>/dev/null || warn "Failed to build hand detector"
        cd "$INSTALL_DIR/detectors"
    fi

    # Hand-only detector (d2 based)
    git clone https://github.com/ddshan/hand_detector.d2.git hand_only_detector 2>/dev/null || warn "Failed to clone hand_only_detector"
fi

cd "$INSTALL_DIR"

# =============================================================================
# Apply Compatibility Patches (from build_frankmocap.sh apply_compatibility_patches)
# =============================================================================
info "Applying compatibility patches..."

# Patch CPU fallback for demos
for demo_file in demo/demo_bodymocap.py demo/demo_handmocap.py demo/demo_frankmocap.py; do
    if [[ -f "$demo_file" ]]; then
        sed -i 's/assert torch.cuda.is_available(), "Current version only supports GPU"/if not torch.cuda.is_available(): print("WARNING: CUDA not available, running in CPU mode")/g' "$demo_file" 2>/dev/null || true
    fi
done

# Patch deprecated scipy/numpy imports
find . -name "*.py" -type f -exec sed -i \
    -e 's/from scipy.misc import imread/from imageio import imread/g' \
    -e 's/scipy.misc.imread/imageio.imread/g' \
    {} \; 2>/dev/null || true

# =============================================================================
# Create SMPL placeholder
# =============================================================================
mkdir -p extra_data/smpl
echo "SMPL/SMPLX models required. Mount at /opt/frankmocap/extra_data/smpl" > extra_data/smpl/README.txt
echo "Download from: https://smpl.is.tue.mpg.de/ and https://smpl-x.is.tue.mpg.de/" >> extra_data/smpl/README.txt

info "=============================================="
info "FrankMocap Docker Build Complete!"
info "=============================================="
info "Installation directory: $INSTALL_DIR"
info "Log file: $LOG_FILE"
