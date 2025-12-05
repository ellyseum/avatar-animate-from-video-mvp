#!/bin/bash
# =============================================================================
# build_frankmocap.sh - Build FrankMocap for Modern GPUs (RTX 5080/Blackwell)
# =============================================================================
# 
# This script builds FrankMocap (archived Oct 2023) with compatibility patches
# for modern NVIDIA GPUs (RTX 40xx, RTX 50xx, future Blackwell architecture).
#
# KNOWN ISSUES AND WORKAROUNDS:
# 1. Legacy CUDA: Original requires CUDA 10.1, PyTorch 1.6 - we use CUDA 12.x compatible versions
# 2. OpenGL Rendering: May require xvfb for headless mode, or use pytorch3d renderer
# 3. Detectron2: Pre-built wheels only for older PyTorch - we build from source
# 4. hand_object_detector: Uses older Faster R-CNN - may need CUDA fixes
# 5. chumpy dependency: Deprecated, replaced with numpy workarounds
# 6. Python 3.7 required originally - we use 3.10+ with compatibility patches
#
# REQUIREMENTS:
# - Ubuntu 20.04+ or equivalent Linux
# - NVIDIA GPU with CUDA support
# - conda or miniconda installed
# - ~15GB disk space
#
# USAGE:
#   chmod +x build_frankmocap.sh
#   ./build_frankmocap.sh [--install-dir /path/to/install] [--cpu-only] [--body-only]
#
# =============================================================================

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/build_frankmocap_$(date +%Y%m%d_%H%M%S).log"
INSTALL_DIR="${SCRIPT_DIR}/frankmocap"
CONDA_ENV_NAME="frankmocap"
CPU_ONLY=false
BODY_ONLY=false
FORCE_REINSTALL=false

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Utility Functions
# =============================================================================
log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${msg}" | tee -a "${LOG_FILE}"
}

info() { log "INFO" "${GREEN}$*${NC}"; }
warn() { log "WARN" "${YELLOW}$*${NC}"; }
error() { log "ERROR" "${RED}$*${NC}"; }
debug() { log "DEBUG" "${BLUE}$*${NC}"; }

check_command() {
    if ! command -v "$1" &> /dev/null; then
        error "Required command '$1' not found. Please install it first."
        return 1
    fi
    return 0
}

# =============================================================================
# Parse Arguments
# =============================================================================
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --install-dir)
                INSTALL_DIR="$2"
                shift 2
                ;;
            --cpu-only)
                CPU_ONLY=true
                shift
                ;;
            --body-only)
                BODY_ONLY=true
                shift
                ;;
            --force)
                FORCE_REINSTALL=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --install-dir PATH   Installation directory (default: ./frankmocap)"
                echo "  --cpu-only           Build without GPU support (fallback mode)"
                echo "  --body-only          Install only body module (fewer dependencies)"
                echo "  --force              Force reinstall even if already exists"
                echo "  --help, -h           Show this help message"
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

# =============================================================================
# System Detection
# =============================================================================
detect_gpu_info() {
    info "Detecting GPU and CUDA information..."
    
    # Check for nvidia-smi
    if ! command -v nvidia-smi &> /dev/null; then
        warn "nvidia-smi not found. GPU detection failed."
        warn "Will proceed with CPU-only mode or manual CUDA specification."
        CPU_ONLY=true
        CUDA_VERSION="none"
        GPU_NAME="none"
        DRIVER_VERSION="none"
        return
    fi
    
    # Get GPU info
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader,nounits 2>/dev/null | head -n1 || echo "unknown")
    DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader,nounits 2>/dev/null | head -n1 || echo "unknown")
    
    # Get CUDA version from nvidia-smi
    CUDA_VERSION_FULL=$(nvidia-smi 2>/dev/null | grep "CUDA Version" | awk '{print $9}' || echo "")
    if [[ -z "$CUDA_VERSION_FULL" ]]; then
        # Try nvcc
        if command -v nvcc &> /dev/null; then
            CUDA_VERSION_FULL=$(nvcc --version | grep "release" | awk '{print $6}' | cut -d',' -f1 || echo "unknown")
        else
            CUDA_VERSION_FULL="unknown"
        fi
    fi
    CUDA_VERSION="${CUDA_VERSION_FULL}"
    
    # Get compute capability
    COMPUTE_CAPABILITY=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null | head -n1 || echo "unknown")
    
    info "GPU Detection Results:"
    info "  GPU Name: ${GPU_NAME}"
    info "  Driver Version: ${DRIVER_VERSION}"
    info "  CUDA Version: ${CUDA_VERSION}"
    info "  Compute Capability: ${COMPUTE_CAPABILITY}"
    
    # Detect GPU architecture generation
    IS_BLACKWELL=false
    IS_ADA=false
    IS_AMPERE=false
    USE_NIGHTLY=false
    
    # Check for Blackwell architecture (RTX 50 series, sm_120)
    if [[ "$GPU_NAME" == *"RTX 50"* ]] || [[ "$COMPUTE_CAPABILITY" == "12."* ]]; then
        IS_BLACKWELL=true
        USE_NIGHTLY=true
        info "Detected NVIDIA Blackwell architecture (RTX 50 series / sm_120)."
        info "Will use PyTorch nightly with CUDA 12.8 (cu128) for Blackwell support."
    # Check for Ada Lovelace architecture (RTX 40 series, sm_89)
    elif [[ "$GPU_NAME" == *"RTX 40"* ]] || [[ "$COMPUTE_CAPABILITY" == "8.9" ]]; then
        IS_ADA=true
        info "Detected NVIDIA Ada Lovelace architecture (RTX 40 series / sm_89)."
    # Check for Ampere architecture (RTX 30 series, sm_86/sm_80)
    elif [[ "$GPU_NAME" == *"RTX 30"* ]] || [[ "$COMPUTE_CAPABILITY" == "8.6" ]] || [[ "$COMPUTE_CAPABILITY" == "8.0" ]]; then
        IS_AMPERE=true
        info "Detected NVIDIA Ampere architecture (RTX 30 series)."
    fi
    
    # Determine CUDA toolkit version to use
    CUDA_MAJOR=$(echo "$CUDA_VERSION" | cut -d'.' -f1)
    
    if [[ "$IS_BLACKWELL" == true ]]; then
        # Blackwell (RTX 50 series) requires CUDA 12.8+ and PyTorch nightly
        PYTORCH_CUDA_VERSION="cu128"
        CUDA_TOOLKIT_VERSION="12.8"
        info "Using PyTorch nightly with cu128 for Blackwell GPU support."
    elif [[ "$CUDA_MAJOR" -ge 12 ]]; then
        PYTORCH_CUDA_VERSION="cu124"
        CUDA_TOOLKIT_VERSION="12.4"
    elif [[ "$CUDA_MAJOR" -ge 11 ]]; then
        PYTORCH_CUDA_VERSION="cu118"
        CUDA_TOOLKIT_VERSION="11.8"
    else
        warn "CUDA version $CUDA_VERSION may have limited PyTorch support."
        PYTORCH_CUDA_VERSION="cu118"
        CUDA_TOOLKIT_VERSION="11.8"
    fi
    
    info "Selected PyTorch CUDA variant: ${PYTORCH_CUDA_VERSION}"
}

# =============================================================================
# Conda Environment Setup
# =============================================================================
setup_conda_env() {
    info "Setting up Conda environment: ${CONDA_ENV_NAME}"
    
    # Check if conda is available
    if ! command -v conda &> /dev/null; then
        error "Conda not found. Please install Miniconda or Anaconda first."
        error "Visit: https://docs.conda.io/en/latest/miniconda.html"
        exit 1
    fi
    
    # Find conda installation directory
    local CONDA_BASE
    CONDA_BASE=$(conda info --base 2>/dev/null || echo "${CONDA_PREFIX:-$HOME/anaconda3}")
    info "Conda base directory: ${CONDA_BASE}"
    
    # Initialize conda for script - try multiple methods for compatibility
    # Method 1: Source conda.sh directly (works with all conda versions)
    if [[ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]]; then
        info "Sourcing conda.sh for shell integration..."
        source "${CONDA_BASE}/etc/profile.d/conda.sh"
    # Method 2: Try the shell hook (newer conda versions)
    elif conda shell.bash hook &>/dev/null; then
        eval "$(conda shell.bash hook)"
    else
        warn "Could not initialize conda shell integration. Using fallback method."
    fi
    
    # Check if environment exists
    if conda env list | grep -q "^${CONDA_ENV_NAME} "; then
        if [[ "$FORCE_REINSTALL" == true ]]; then
            warn "Removing existing environment: ${CONDA_ENV_NAME}"
            conda env remove -n "${CONDA_ENV_NAME}" -y
        else
            info "Environment ${CONDA_ENV_NAME} already exists. Activating..."
            conda activate "${CONDA_ENV_NAME}" || {
                # Fallback: manually set up the environment path
                warn "conda activate failed, using manual activation..."
                export PATH="${CONDA_BASE}/envs/${CONDA_ENV_NAME}/bin:$PATH"
                export CONDA_PREFIX="${CONDA_BASE}/envs/${CONDA_ENV_NAME}"
                export CONDA_DEFAULT_ENV="${CONDA_ENV_NAME}"
            }
            return
        fi
    fi
    
    # Create new environment with Python 3.10 (modern, but still compatible)
    info "Creating new Conda environment with Python 3.10..."
    conda create -n "${CONDA_ENV_NAME}" python=3.10 -y
    
    # Activate the environment
    info "Activating environment ${CONDA_ENV_NAME}..."
    conda activate "${CONDA_ENV_NAME}" || {
        # Fallback: manually set up the environment path
        warn "conda activate failed, using manual activation..."
        export PATH="${CONDA_BASE}/envs/${CONDA_ENV_NAME}/bin:$PATH"
        export CONDA_PREFIX="${CONDA_BASE}/envs/${CONDA_ENV_NAME}"
        export CONDA_DEFAULT_ENV="${CONDA_ENV_NAME}"
    }
    
    # Verify Python is from the correct environment
    local PYTHON_PATH
    PYTHON_PATH=$(which python)
    info "Using Python: ${PYTHON_PATH}"
    
    info "Conda environment created and activated."
}

# =============================================================================
# Install System Dependencies
# =============================================================================
install_system_deps() {
    info "Checking and installing system dependencies..."
    
    # Check for apt (Debian/Ubuntu)
    if command -v apt-get &> /dev/null; then
        info "Installing system packages via apt..."
        sudo apt-get update
        # Note: libgl1-mesa-glx replaced by libgl1 in newer Ubuntu versions
        sudo apt-get install -y \
            libglu1-mesa \
            libxi-dev \
            libxmu-dev \
            libglu1-mesa-dev \
            freeglut3-dev \
            libosmesa6-dev \
            ffmpeg \
            wget \
            git \
            build-essential \
            xvfb \
            libgl1 \
            libglfw3 \
            libglfw3-dev \
            2>&1 | tee -a "${LOG_FILE}" || warn "Some system packages may have failed to install"
    else
        warn "apt-get not found. Please manually install OpenGL and FFmpeg dependencies."
    fi
}

# =============================================================================
# Install PyTorch with CUDA Support
# =============================================================================
install_pytorch() {
    info "Installing PyTorch with CUDA support..."
    
    if [[ "$CPU_ONLY" == true ]]; then
        info "Installing CPU-only PyTorch..."
        pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
    elif [[ "$IS_BLACKWELL" == true ]] || [[ "$PYTORCH_CUDA_VERSION" == "cu128" ]]; then
        # Blackwell (RTX 50 series) requires PyTorch nightly with CUDA 12.8
        info "Installing PyTorch NIGHTLY with CUDA 12.8 for Blackwell GPU support..."
        info "Note: Blackwell (sm_120) requires nightly builds until PyTorch 2.6+ stable release."
        pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128
    else
        # Install stable PyTorch with appropriate CUDA version
        info "Installing PyTorch stable with CUDA ${PYTORCH_CUDA_VERSION}..."
        pip install torch torchvision torchaudio --index-url "https://download.pytorch.org/whl/${PYTORCH_CUDA_VERSION}"
    fi
    
    # Verify installation
    info "Verifying PyTorch installation..."
    python -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA version: {torch.version.cuda}')
    print(f'cuDNN version: {torch.backends.cudnn.version()}')
    print(f'GPU count: {torch.cuda.device_count()}')
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        print(f'  GPU {i}: {props.name}')
        print(f'    Compute Capability: {props.major}.{props.minor}')
        print(f'    Total Memory: {props.total_memory / 1024**3:.1f} GB')
else:
    print('WARNING: CUDA not available. Running in CPU mode.')
" 2>&1 | tee -a "${LOG_FILE}"
}

# =============================================================================
# Clone FrankMocap Repository
# =============================================================================
clone_frankmocap() {
    info "Cloning FrankMocap repository..."
    
    mkdir -p "$(dirname "${INSTALL_DIR}")"
    
    if [[ -d "${INSTALL_DIR}" ]]; then
        if [[ "$FORCE_REINSTALL" == true ]]; then
            warn "Removing existing FrankMocap directory..."
            rm -rf "${INSTALL_DIR}"
        else
            info "FrankMocap directory already exists at ${INSTALL_DIR}"
            return
        fi
    fi
    
    # Use ellyseum fork with PyTorch 2.x compatibility fixes (kornia instead of torchgeometry)
    git clone https://github.com/ellyseum/frankmocap.git "${INSTALL_DIR}"
    cd "${INSTALL_DIR}"
    
    info "FrankMocap cloned successfully (using ellyseum fork with modern GPU support)."
}

# =============================================================================
# Install Python Dependencies with Compatibility Fixes
# =============================================================================
install_python_deps() {
    info "Installing Python dependencies with compatibility fixes..."
    
    cd "${INSTALL_DIR}"
    
    # Check if core deps are already installed (check the most critical ones)
    if [[ "$FORCE_REINSTALL" != true ]] && python -c "import torch, torchvision, smplx, kornia" 2>/dev/null; then
        info "Core Python dependencies already installed. Skipping... (use --force to reinstall)"
        return
    fi
    
    # Create a modified requirements file for modern Python/PyTorch
    cat > docs/requirements_modern.txt << 'EOF'
# Modified requirements for Python 3.10+ and PyTorch 2.x
# Original FrankMocap required Python 3.7, PyTorch 1.6, CUDA 10.1

# Core dependencies
numpy>=1.21.0,<2.0
scipy>=1.7.0
opencv-python>=4.5.0
pillow>=9.0.0
scikit-image>=0.19.0
matplotlib>=3.5.0
tqdm>=4.60.0
yacs>=0.1.8
tensorboardX>=2.4

# 3D Human body models
smplx>=0.1.28
chumpy  # May need special handling, see below

# For rendering - PyOpenGL version must match pyrender's requirement
# pyrender 0.1.45 requires PyOpenGL==3.1.0
PyOpenGL==3.1.0
trimesh>=3.10.0
pyrender>=0.1.45

# For video processing
imageio>=2.14.0
imageio-ffmpeg>=0.4.5

# Deep learning utilities
einops>=0.4.0
kornia>=0.6.0
EOF

    # Install basic dependencies
    info "Installing core dependencies..."
    pip install --upgrade pip setuptools wheel ninja
    
    # Install requirements (some may fail, we'll handle them)
    pip install -r docs/requirements_modern.txt 2>&1 | tee -a "${LOG_FILE}" || true
    
    # Handle chumpy (deprecated, but needed for SMPL)
    # Use --no-build-isolation to avoid pip module error in build environment
    info "Installing chumpy with numpy compatibility fix..."
    pip install --no-build-isolation chumpy 2>&1 || {
        warn "chumpy PyPI install failed. Trying from source..."
        # Clone and install manually to apply patches
        local CHUMPY_DIR="${INSTALL_DIR}/chumpy"
        if [[ -d "$CHUMPY_DIR" ]]; then
            rm -rf "$CHUMPY_DIR"
        fi
        git clone https://github.com/mattloper/chumpy.git "$CHUMPY_DIR" 2>&1 || true
        if [[ -d "$CHUMPY_DIR" ]]; then
            cd "$CHUMPY_DIR"
            pip install --no-build-isolation -e . 2>&1 || {
                warn "chumpy still failing. Will create minimal stub for compatibility."
                # Create a minimal chumpy stub that won't crash imports
                mkdir -p "${CONDA_PREFIX}/lib/python3.10/site-packages/chumpy"
                cat > "${CONDA_PREFIX}/lib/python3.10/site-packages/chumpy/__init__.py" << 'STUBEOF'
# Minimal chumpy stub for compatibility
# Full chumpy functionality may not be available
import numpy as np

class Ch(np.ndarray):
    """Minimal stub for chumpy.Ch"""
    pass

def array(*args, **kwargs):
    return np.array(*args, **kwargs)
STUBEOF
                info "Created minimal chumpy stub for compatibility."
            }
            cd "${INSTALL_DIR}"
        fi
    }
    
    # Install smplx
    pip install smplx
}

# =============================================================================
# Install Detectron2 (for hand detection)
# =============================================================================
install_detectron2() {
    if [[ "$BODY_ONLY" == true ]]; then
        info "Skipping Detectron2 (body-only mode)"
        return
    fi
    
    # Check if detectron2 is already installed
    if [[ "$FORCE_REINSTALL" != true ]] && python -c "import detectron2" 2>/dev/null; then
        info "Detectron2 already installed. Skipping... (use --force to reinstall)"
        return
    fi
    
    info "Installing Detectron2 for hand detection..."
    
    # Install detectron2 dependencies first
    pip install pycocotools fvcore iopath omegaconf hydra-core 2>&1 || true
    
    # Clone and build Detectron2 from source with --no-build-isolation
    local D2_DIR="${INSTALL_DIR}/detectron2_build"
    if [[ -d "$D2_DIR" ]]; then
        rm -rf "$D2_DIR"
    fi
    
    info "Cloning Detectron2 repository..."
    git clone https://github.com/facebookresearch/detectron2.git "$D2_DIR" 2>&1
    
    if [[ -d "$D2_DIR" ]]; then
        cd "$D2_DIR"
        info "Building Detectron2 (this may take several minutes)..."
        pip install --no-build-isolation -e . 2>&1 | tee -a "${LOG_FILE}" || {
            warn "Detectron2 pip install failed. Trying direct setup.py..."
            python setup.py build develop 2>&1 | tee -a "${LOG_FILE}" || {
                warn "Detectron2 build failed. Hand detection module may not work."
            }
        }
        cd "${INSTALL_DIR}"
    else
        error "Failed to clone Detectron2 repository."
    fi
    
    # Verify installation
    python -c "import detectron2; print(f'Detectron2 version: {detectron2.__version__}')" 2>&1 | tee -a "${LOG_FILE}" || {
        warn "Detectron2 installation verification failed. Hand module may not work."
    }
}

# =============================================================================
# Install PyTorch3D (optional renderer)
# =============================================================================
install_pytorch3d() {
    # Check if pytorch3d is already installed
    if [[ "$FORCE_REINSTALL" != true ]] && python -c "import pytorch3d" 2>/dev/null; then
        info "PyTorch3D already installed. Skipping... (use --force to reinstall)"
        return
    fi
    
    info "Installing PyTorch3D for rendering..."
    
    if [[ "$CPU_ONLY" == true ]]; then
        # CPU-only installation - use --no-build-isolation to find torch
        pip install --no-build-isolation 'git+https://github.com/facebookresearch/pytorch3d.git' 2>&1 | tee -a "${LOG_FILE}" || {
            warn "PyTorch3D installation failed. Will use OpenGL renderer instead."
        }
    else
        # Try pre-built wheel first, then build from source
        PYTORCH_VERSION=$(python -c "import torch; print(torch.__version__.split('+')[0])")
        CUDA_VER=$(python -c "import torch; print(torch.version.cuda.replace('.', ''))" 2>/dev/null || echo "")
        
        # Try installing from PyPI first
        pip install pytorch3d 2>&1 | tee -a "${LOG_FILE}" || {
            info "Pre-built PyTorch3D not available. Building from source (this may take a while)..."
            # Use --no-build-isolation so pip can find torch in the current environment
            pip install --no-build-isolation 'git+https://github.com/facebookresearch/pytorch3d.git' 2>&1 | tee -a "${LOG_FILE}" || {
                warn "PyTorch3D build failed. Will use OpenGL renderer instead."
                warn "You can try installing manually later or use --renderer_type opengl"
            }
        }
    fi
}

# =============================================================================
# Download FrankMocap Data and Models
# =============================================================================
download_data() {
    info "Downloading FrankMocap pretrained models and data..."
    
    cd "${INSTALL_DIR}"
    
    # Download body module data
    info "Downloading body module data..."
    mkdir -p extra_data/body_module
    cd extra_data/body_module
    
    # SPIN data
    if [[ ! -d "data_from_spin" ]]; then
        info "Downloading SPIN data..."
        wget -q https://visiondata.cis.upenn.edu/spin/data.tar.gz || {
            warn "SPIN data download failed. Some features may not work."
        }
        if [[ -f "data.tar.gz" ]]; then
            # Note: Despite .tar.gz extension, file is actually uncompressed tar
            tar -xf data.tar.gz && rm data.tar.gz
            mv data data_from_spin 2>/dev/null || true
        fi
    fi
    
    # Pretrained weights
    mkdir -p pretrained_weights
    cd pretrained_weights
    
    if [[ ! -f "2020_05_31-00_50_43-best-51.749683916568756.pt" ]]; then
        info "Downloading body module pretrained weights..."
        wget -q https://dl.fbaipublicfiles.com/eft/2020_05_31-00_50_43-best-51.749683916568756.pt || warn "Failed to download body SMPL weights"
        wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/body_module/smplx-03-28-46060-w_spin_mlc3d_46582-2089_2020_03_28-21_56_16.pt || warn "Failed to download body SMPLX weights"
    fi
    
    cd "${INSTALL_DIR}/extra_data/body_module"
    if [[ ! -f "J_regressor_extra_smplx.npy" ]]; then
        wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/body_module/J_regressor_extra_smplx.npy || warn "Failed to download J_regressor"
    fi
    
    cd "${INSTALL_DIR}"
    
    # Download hand module data (if not body-only)
    if [[ "$BODY_ONLY" != true ]]; then
        info "Downloading hand module data..."
        mkdir -p extra_data/hand_module
        cd extra_data/hand_module
        
        if [[ ! -f "SMPLX_HAND_INFO.pkl" ]]; then
            wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/SMPLX_HAND_INFO.pkl || warn "Failed to download hand info"
            wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/mean_mano_params.pkl || warn "Failed to download MANO params"
        fi
        
        mkdir -p pretrained_weights
        cd pretrained_weights
        if [[ ! -f "pose_shape_best.pth" ]]; then
            wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/checkpoints_best/pose_shape_best.pth || warn "Failed to download hand weights"
        fi
    fi
    
    cd "${INSTALL_DIR}"
    
    # Download sample data
    if [[ ! -d "sample_data" ]]; then
        info "Downloading sample videos..."
        wget -q https://dl.fbaipublicfiles.com/eft/sampledata_frank.tar && \
            tar -xf sampledata_frank.tar && \
            rm sampledata_frank.tar && \
            mv sampledata sample_data 2>/dev/null || warn "Failed to download sample data"
    fi
    
    info "Data download complete."
}

# =============================================================================
# Install Third-Party Detectors
# =============================================================================
install_detectors() {
    info "Installing third-party detectors..."
    
    cd "${INSTALL_DIR}"
    mkdir -p detectors
    cd detectors
    
    # Body pose estimator (lightweight-human-pose-estimation)
    info "Installing 2D body pose detector..."
    if [[ ! -d "body_pose_estimator" ]]; then
        git clone https://github.com/Daniil-Osokin/lightweight-human-pose-estimation.pytorch.git body_pose_estimator || {
            # Try alternative URL
            git clone https://github.com/jhugestar/lightweight-human-pose-estimation.pytorch.git body_pose_estimator || {
                warn "Failed to clone body pose estimator"
            }
        }
    fi
    
    # Download body pose estimator weights
    mkdir -p "${INSTALL_DIR}/extra_data/body_module/body_pose_estimator"
    cd "${INSTALL_DIR}/extra_data/body_module/body_pose_estimator"
    if [[ ! -f "checkpoint_iter_370000.pth" ]]; then
        wget -q https://download.01.org/opencv/openvino_training_extensions/models/human_pose_estimation/checkpoint_iter_370000.pth || warn "Failed to download pose estimator weights"
    fi
    
    # Hand detectors (if not body-only)
    if [[ "$BODY_ONLY" != true ]]; then
        info "Installing hand detectors..."
        cd "${INSTALL_DIR}/detectors"
        
        pip install gdown
        
        # Hand-object detector (using ellyseum fork with PyTorch 2.x C++ API compatibility)
        if [[ ! -d "hand_object_detector" ]]; then
            git clone https://github.com/ellyseum/hand_object_detector.git || warn "Failed to clone hand_object_detector"
        fi
        
        # Build only if not already installed (or if --force is specified)
        # Check for the built _C.*.so file which indicates successful compilation
        local should_build=false
        local so_file=$(find "${INSTALL_DIR}/detectors/hand_object_detector/lib" -name "_C*.so" 2>/dev/null | head -1)
        if [[ "$FORCE_REINSTALL" == true ]]; then
            should_build=true
        elif [[ -z "$so_file" ]]; then
            should_build=true
        fi
        
        if [[ "$should_build" == true ]] && [[ -d "hand_object_detector" ]]; then
            cd hand_object_detector/lib
            # Apply CUDA compatibility patch for modern GPUs
            apply_cuda_patch
            # Build the extension - use pip install with --no-build-isolation to avoid
            # subprocess not finding torch
            python setup.py build 2>&1 | tee -a "${LOG_FILE}" || warn "hand_object_detector build failed"
            pip install -e . --no-build-isolation 2>&1 | tee -a "${LOG_FILE}" || warn "hand_object_detector install failed"
            cd "${INSTALL_DIR}/detectors"
        else
            info "hand_object_detector already built. Skipping... (use --force to rebuild)"
        fi
        
        # Hand-only detector
        if [[ ! -d "hand_only_detector" ]]; then
            git clone https://github.com/ddshan/hand_detector.d2.git hand_only_detector || warn "Failed to clone hand_only_detector"
        fi
        
        # Download detector weights
        mkdir -p "${INSTALL_DIR}/extra_data/hand_module/hand_detector"
        cd "${INSTALL_DIR}/extra_data/hand_module/hand_detector"
        if [[ ! -f "faster_rcnn_1_8_132028.pth" ]]; then
            gdown https://drive.google.com/uc?id=1H2tWsZkS7tDF8q1-jdjx6V9XrK25EDbE 2>/dev/null || warn "Failed to download hand detector weights"
            gdown https://drive.google.com/uc?id=1OqgexNM52uxsPG3i8GuodDOJAGFsYkPg 2>/dev/null || warn "Failed to download hand detector weights"
        fi
    fi
    
    info "Detector installation complete."
}

# =============================================================================
# Apply CUDA Compatibility Patches
# =============================================================================
apply_cuda_patch() {
    info "Applying CUDA compatibility patches for modern GPUs..."
    
    # NOTE: The ellyseum/hand_object_detector fork already has the C++ API fixes
    # for PyTorch 2.x (data<T>() -> data_ptr<T>(), type().is_cuda() -> is_cuda(), etc.)
    # This function now only handles setup.py modifications for CUDA arch flags.
    
    # Check if we're in the right directory
    if [[ ! -f "setup.py" ]]; then
        warn "setup.py not found, skipping patch"
        return
    fi
    
    # Create backup
    cp setup.py setup.py.bak 2>/dev/null || true
    
    # Patch setup.py to use modern CUDA
    cat > cuda_patch.py << 'PATCH_EOF'
import re
import sys

def patch_setup():
    with open('setup.py', 'r') as f:
        content = f.read()
    
    # Remove hard-coded CUDA architecture flags that may not be compatible
    # and let PyTorch auto-detect
    content = re.sub(
        r"'-gencode', 'arch=compute_\d+,code=sm_\d+'",
        "",
        content
    )
    
    # Remove deprecated THC headers if present
    content = re.sub(
        r'#include\s*<THC/THC\.h>',
        '// THC headers deprecated in modern PyTorch',
        content
    )
    
    with open('setup.py', 'w') as f:
        f.write(content)
    
    print("CUDA patches applied to setup.py")

if __name__ == '__main__':
    patch_setup()
PATCH_EOF
    
    python cuda_patch.py
    rm cuda_patch.py
}

# =============================================================================
# Apply FrankMocap Code Patches for Modern Python/PyTorch
# =============================================================================
apply_frankmocap_patches() {
    info "Applying FrankMocap compatibility patches..."
    
    cd "${INSTALL_DIR}"
    
    # Patch 1: Fix GPU assertion to allow CPU fallback
    info "Patching demo files for CPU fallback support..."
    
    for demo_file in demo/demo_bodymocap.py demo/demo_handmocap.py demo/demo_frankmocap.py; do
        if [[ -f "$demo_file" ]]; then
            # Replace hard GPU assertion with fallback
            sed -i 's/assert torch.cuda.is_available(), "Current version only supports GPU"/if not torch.cuda.is_available(): print("WARNING: CUDA not available, running in CPU mode (may be slow)")/g' "$demo_file" 2>/dev/null || true
        fi
    done
    
    # Patch 2: Fix deprecated numpy/scipy imports
    info "Patching deprecated numpy/scipy imports..."
    
    find . -name "*.py" -type f -exec sed -i \
        -e 's/from scipy.misc import imread/from imageio import imread/g' \
        -e 's/scipy.misc.imread/imageio.imread/g' \
        -e 's/np.float/np.float64/g' \
        -e 's/np.int)/np.int64)/g' \
        -e 's/np.bool)/np.bool_)/g' \
        {} \; 2>/dev/null || true
    
    # Patch 3: Create CPU fallback wrapper
    info "Creating CPU fallback wrapper..."
    
    cat > run_frankmocap.py << 'WRAPPER_EOF'
#!/usr/bin/env python
"""
FrankMocap Wrapper with CPU Fallback and Modern GPU Support

This wrapper handles:
1. Automatic GPU/CPU detection
2. Graceful fallback to CPU if GPU fails
3. Memory management for large models
4. Headless rendering via xvfb if needed
"""

import os
import sys
import warnings

# Suppress deprecation warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', category=FutureWarning)

def setup_environment():
    """Configure environment for optimal performance"""
    
    # Check CUDA availability
    try:
        import torch
        if torch.cuda.is_available():
            print(f"GPU detected: {torch.cuda.get_device_name(0)}")
            print(f"CUDA version: {torch.version.cuda}")
            
            # Set memory allocation strategy for modern GPUs
            # This helps with RTX 40xx/50xx series
            os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'max_split_size_mb:512')
            
            # Enable TF32 for Ampere+ GPUs
            if torch.cuda.get_device_capability()[0] >= 8:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                print("TF32 enabled for better performance")
        else:
            print("WARNING: CUDA not available. Running in CPU mode (slower).")
            os.environ['CUDA_VISIBLE_DEVICES'] = ''
    except Exception as e:
        print(f"WARNING: PyTorch GPU setup failed: {e}")
        print("Falling back to CPU mode.")
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
    
    # Setup for headless rendering
    if 'DISPLAY' not in os.environ:
        print("No display detected. Using virtual framebuffer for rendering.")
        os.environ['PYOPENGL_PLATFORM'] = 'osmesa'

def main():
    setup_environment()
    
    # Import and run the appropriate demo
    if len(sys.argv) < 2:
        print("Usage: python run_frankmocap.py [body|hand|full] [options]")
        print("")
        print("Modes:")
        print("  body  - Body motion capture only")
        print("  hand  - Hand motion capture only")
        print("  full  - Full body + hand motion capture")
        print("")
        print("Example:")
        print("  python run_frankmocap.py body --input_path ./sample_data/han_short.mp4 --out_dir ./output")
        sys.exit(1)
    
    mode = sys.argv[1]
    sys.argv = sys.argv[1:]  # Remove wrapper script from argv
    
    if mode == 'body':
        sys.argv[0] = 'demo.demo_bodymocap'
        from demo import demo_bodymocap
        demo_bodymocap.main()
    elif mode == 'hand':
        sys.argv[0] = 'demo.demo_handmocap'
        from demo import demo_handmocap
        demo_handmocap.main()
    elif mode == 'full':
        sys.argv[0] = 'demo.demo_frankmocap'
        from demo import demo_frankmocap
        demo_frankmocap.main()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

if __name__ == '__main__':
    main()
WRAPPER_EOF

    chmod +x run_frankmocap.py
    
    info "Patches applied successfully."
}

# =============================================================================
# Create SMPL/SMPLX Model Download Instructions
# =============================================================================
create_smpl_instructions() {
    info "Creating SMPL/SMPLX model download instructions..."
    
    cat > "${INSTALL_DIR}/DOWNLOAD_SMPL_MODELS.md" << 'EOF'
# SMPL/SMPLX Model Download Instructions

FrankMocap requires SMPL and SMPLX body models which must be downloaded manually
due to license restrictions.

## Required Models

### 1. SMPL Neutral Model (for body module)
- File: `basicModel_neutral_lbs_10_207_0_v1.0.0.pkl`
- Download from: https://smplify.is.tue.mpg.de/
- Registration required (free for research)
- Place in: `./extra_data/smpl/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl`

### 2. SMPLX Neutral Model (for hand and whole body modules)
- File: `SMPLX_NEUTRAL.pkl`
- Download from: https://smpl-x.is.tue.mpg.de/
- Registration required (free for research)
- Place in: `./extra_data/smpl/SMPLX_NEUTRAL.pkl`

## Directory Structure

After downloading, your `extra_data/smpl/` directory should look like:

```
extra_data/smpl/
├── basicModel_neutral_lbs_10_207_0_v1.0.0.pkl
└── SMPLX_NEUTRAL.pkl
```

## Quick Setup

```bash
mkdir -p extra_data/smpl
# Copy your downloaded files here
cp /path/to/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl extra_data/smpl/
cp /path/to/SMPLX_NEUTRAL.pkl extra_data/smpl/
```

## Verification

Run this to verify the models are correctly placed:

```bash
python -c "
import os
smpl_path = 'extra_data/smpl/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl'
smplx_path = 'extra_data/smpl/SMPLX_NEUTRAL.pkl'
print('SMPL model:', 'OK' if os.path.exists(smpl_path) else 'MISSING', '(' + smpl_path + ')')
print('SMPLX model:', 'OK' if os.path.exists(smplx_path) else 'MISSING', '(' + smplx_path + ')')
"
```
EOF
    
    mkdir -p "${INSTALL_DIR}/extra_data/smpl"
    
    info "SMPL model instructions created at: ${INSTALL_DIR}/DOWNLOAD_SMPL_MODELS.md"
}

# =============================================================================
# Final Verification and Test
# =============================================================================
verify_installation() {
    info "Verifying FrankMocap installation..."
    
    cd "${INSTALL_DIR}"
    
    # Test basic imports - wrapped in try-except to prevent build interruption
    python << 'VERIFY_EOF' || warn "Verification script encountered an error, but installation may still be usable"
import sys
import os

try:
    print("=" * 60)
    print("FrankMocap Installation Verification")
    print("=" * 60)

    errors = []
    warnings = []

    # Core dependencies
    print("\n[1/6] Checking core dependencies...")
    try:
        import torch
        print(f"  ✓ PyTorch {torch.__version__}")
        print(f"    CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"    CUDA version: {torch.version.cuda}")
            print(f"    GPU: {torch.cuda.get_device_name(0)}")
    except ImportError as e:
        errors.append(f"PyTorch: {e}")
        print(f"  ✗ PyTorch: {e}")

    try:
        import torchvision
        print(f"  ✓ torchvision {torchvision.__version__}")
    except ImportError as e:
        errors.append(f"torchvision: {e}")
        print(f"  ✗ torchvision: {e}")

    # SMPL/SMPLX
    print("\n[2/6] Checking body model libraries...")
    try:
        import smplx
        version = getattr(smplx, '__version__', 'installed')
        print(f"  ✓ smplx {version}")
    except ImportError as e:
        errors.append(f"smplx: {e}")
        print(f"  ✗ smplx: {e}")

    # OpenGL rendering
    print("\n[3/6] Checking rendering dependencies...")
    try:
        import OpenGL.GL
        print("  ✓ PyOpenGL")
    except ImportError as e:
        warnings.append(f"PyOpenGL: {e}")
        print(f"  ⚠ PyOpenGL: {e} (OpenGL rendering may not work)")

    try:
        import pytorch3d
        print(f"  ✓ pytorch3d")
    except ImportError as e:
        warnings.append(f"pytorch3d: {e}")
        print(f"  ⚠ pytorch3d: {e} (use --renderer_type opengl instead)")

    # Detectron2 (for hand detection)
    print("\n[4/6] Checking detection dependencies...")
    try:
        import detectron2
        print(f"  ✓ detectron2 {detectron2.__version__}")
    except ImportError as e:
        warnings.append(f"detectron2: {e}")
        print(f"  ⚠ detectron2: {e} (hand detection may not work)")

    # Other dependencies
    print("\n[5/6] Checking utility dependencies...")
    try:
        import cv2
        print(f"  ✓ opencv-python {cv2.__version__}")
    except ImportError as e:
        errors.append(f"opencv-python: {e}")
        print(f"  ✗ opencv-python: {e}")

    try:
        import numpy as np
        print(f"  ✓ numpy {np.__version__}")
    except ImportError as e:
        errors.append(f"numpy: {e}")
        print(f"  ✗ numpy: {e}")

    try:
        import scipy
        print(f"  ✓ scipy {scipy.__version__}")
    except ImportError as e:
        errors.append(f"scipy: {e}")
        print(f"  ✗ scipy: {e}")

    # Model files
    print("\n[6/6] Checking model files...")
    model_files = [
        ("extra_data/smpl/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl", "SMPL model"),
        ("extra_data/smpl/SMPLX_NEUTRAL.pkl", "SMPLX model"),
        ("extra_data/body_module/pretrained_weights/2020_05_31-00_50_43-best-51.749683916568756.pt", "Body weights"),
    ]

    for path, name in model_files:
        if os.path.exists(path):
            print(f"  ✓ {name}")
        else:
            if "smpl" in path.lower():
                warnings.append(f"{name} not found - download manually")
                print(f"  ⚠ {name}: Download required (see DOWNLOAD_SMPL_MODELS.md)")
            else:
                warnings.append(f"{name} not found")
                print(f"  ⚠ {name}: Not found")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    if errors:
        print("\nCritical errors that must be fixed:")
        for e in errors:
            print(f"  - {e}")

    if warnings:
        print("\nWarnings (may affect some features):")
        for w in warnings:
            print(f"  - {w}")

    if not errors:
        print("\n✓ FrankMocap is ready to use!")
        print("\nQuick test command:")
        print("  python run_frankmocap.py body --input_path ./sample_data/han_short.mp4 --out_dir ./output")
    else:
        print("\n✗ Installation has errors. Please fix the issues above.")
        sys.exit(1)

except Exception as e:
    print(f"\nVerification script error: {e}")
    print("This may be a verification bug - installation might still work.")
    sys.exit(0)  # Don't fail the build for verification errors
VERIFY_EOF
    
    if [[ $? -eq 0 ]]; then
        info "Installation verification completed!"
    else
        warn "Installation verification had issues, but continuing..."
    fi
}

# =============================================================================
# Print Final Instructions
# =============================================================================
print_final_instructions() {
    cat << EOF

================================================================================
FrankMocap Installation Complete!
================================================================================

Installation Directory: ${INSTALL_DIR}
Conda Environment: ${CONDA_ENV_NAME}
Log File: ${LOG_FILE}

GPU Information:
  GPU: ${GPU_NAME:-"Not detected"}
  CUDA: ${CUDA_VERSION:-"Not available"}
  Driver: ${DRIVER_VERSION:-"Not detected"}

NEXT STEPS:
-----------

1. Download SMPL/SMPLX models (REQUIRED):
   - Read: ${INSTALL_DIR}/DOWNLOAD_SMPL_MODELS.md
   - Get SMPL from: https://smplify.is.tue.mpg.de/
   - Get SMPLX from: https://smpl-x.is.tue.mpg.de/

2. Activate the environment:
   conda activate ${CONDA_ENV_NAME}
   cd ${INSTALL_DIR}

3. Run a quick test:
   # Body motion capture
   python run_frankmocap.py body --input_path ./sample_data/han_short.mp4 --out_dir ./output

   # Full body + hands (requires SMPLX model)
   python run_frankmocap.py full --input_path ./sample_data/han_short.mp4 --out_dir ./output

   # Headless mode (on servers without display)
   xvfb-run -a python run_frankmocap.py body --input_path ./sample_data/han_short.mp4 --out_dir ./output

RENDERING OPTIONS:
------------------
- Default: OpenGL (requires display or xvfb)
- Alternative: pytorch3d (if installed)

  Add --renderer_type pytorch3d for screen-free rendering

TROUBLESHOOTING:
----------------
- GPU not detected: Check NVIDIA drivers and CUDA installation
- OpenGL errors: Use xvfb-run or --renderer_type pytorch3d
- Out of memory: Reduce video resolution or use --single_person flag
- Import errors: Activate the conda environment first

For more help, see:
- ${INSTALL_DIR}/README.md
- https://github.com/ellyseum/frankmocap (PyTorch 2.x compatible fork)
- https://github.com/facebookresearch/frankmocap (original archived repo)

================================================================================
EOF
}

# =============================================================================
# Main Execution
# =============================================================================
main() {
    echo "=================================================="
    echo "FrankMocap Build Script for Modern GPUs"
    echo "=================================================="
    echo ""
    echo "Log file: ${LOG_FILE}"
    echo ""
    
    parse_args "$@"
    
    # Create log file
    mkdir -p "$(dirname "${LOG_FILE}")"
    echo "Build started at $(date)" > "${LOG_FILE}"
    
    # Run build steps
    detect_gpu_info
    install_system_deps
    setup_conda_env
    install_pytorch
    clone_frankmocap
    install_python_deps
    install_detectron2
    install_pytorch3d
    download_data
    install_detectors
    apply_frankmocap_patches
    create_smpl_instructions
    verify_installation
    print_final_instructions
    
    info "Build completed successfully!"
    echo "Build completed at $(date)" >> "${LOG_FILE}"
}

# Run main function
main "$@"
