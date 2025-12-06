# =============================================================================
# Dockerfile - FrankMocap Headless GPU Container (Multi-Stage Build)
# =============================================================================
#
# This Dockerfile uses multi-stage builds for efficient layer caching.
# Each stage can be built/rebuilt independently.
#
# Build stages:
#   1. base         - System dependencies, Python setup
#   2. pytorch      - PyTorch with CUDA 12.8
#   3. pydeps       - Python dependencies
#   4. detectron2   - Detectron2 from source
#   5. pytorch3d    - PyTorch3D from source (headless rendering)
#   6. frankmocap   - FrankMocap code and patches
#   7. detectors    - Third-party detectors
#   8. models       - Download pretrained models
#   9. final        - Entrypoint and runtime config
#
# Build specific stage:
#   docker build --target pytorch -t frankmocap-pytorch -f frankmocap/Dockerfile .
#   docker build --target pytorch3d -t frankmocap-pytorch3d -f frankmocap/Dockerfile .
#
# Build all:
#   docker build -t frankmocap-gpu -f frankmocap/Dockerfile .
#
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Base - System dependencies
# -----------------------------------------------------------------------------
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04 AS base

LABEL maintainer="ellyseum"
LABEL description="FrankMocap headless GPU container for motion capture inference"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV CUDA_HOME=/usr/local/cuda
ENV PATH="${CUDA_HOME}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    git \
    wget \
    curl \
    unzip \
    sudo \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3-pip \
    libgl1 \
    libgl1-mesa-glx \
    libglu1-mesa \
    libglu1-mesa-dev \
    libglfw3 \
    libglfw3-dev \
    libosmesa6 \
    libosmesa6-dev \
    freeglut3-dev \
    libxi-dev \
    libxmu-dev \
    xvfb \
    x11-utils \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libjpeg-dev \
    libpng-dev \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    python -m pip install --upgrade pip setuptools wheel

# -----------------------------------------------------------------------------
# Stage 2: PyTorch - Install PyTorch with CUDA 12.8
# -----------------------------------------------------------------------------
FROM base AS pytorch

RUN pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/cu128 && \
    python -c "import torch; print(f'PyTorch {torch.__version__} installed')"

# -----------------------------------------------------------------------------
# Stage 3: Python Dependencies
# -----------------------------------------------------------------------------
FROM pytorch AS pydeps

RUN pip install --no-cache-dir \
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

# Install and patch chumpy for numpy 1.24+ compatibility
# Must patch BEFORE importing since numpy 1.24+ removed deprecated type aliases
RUN pip install --no-build-isolation chumpy && \
    SITE_PACKAGES=$(python -c "import site; print(site.getsitepackages()[0])") && \
    sed -i 's/from numpy import bool, int, float, complex, object, unicode, str, nan, inf/from numpy import nan, inf/' "${SITE_PACKAGES}/chumpy/__init__.py" && \
    python -c "import chumpy; print('chumpy patched successfully')"

# -----------------------------------------------------------------------------
# Stage 4: Detectron2 - Build from source
# -----------------------------------------------------------------------------
FROM pydeps AS detectron2

RUN git clone https://github.com/facebookresearch/detectron2.git /opt/detectron2 && \
    cd /opt/detectron2 && \
    pip install --no-build-isolation -e .

# -----------------------------------------------------------------------------
# Stage 5: PyTorch3D - Build from source (for headless rendering WITH GPU)
# -----------------------------------------------------------------------------
FROM detectron2 AS pytorch3d

# Force CUDA compilation for pytorch3d
ENV FORCE_CUDA=1
# Set CUDA architectures - include Blackwell (sm_120) and common ones
ENV TORCH_CUDA_ARCH_LIST="7.0;7.5;8.0;8.6;8.9;9.0;12.0"

RUN pip install --no-build-isolation 'git+https://github.com/facebookresearch/pytorch3d.git@stable'

# -----------------------------------------------------------------------------
# Stage 6: FrankMocap - Clone and setup
# -----------------------------------------------------------------------------
FROM pytorch3d AS frankmocap

WORKDIR /opt

RUN git clone https://github.com/ellyseum/frankmocap.git /opt/frankmocap

# Apply compatibility patches
WORKDIR /opt/frankmocap
RUN for demo_file in demo/demo_bodymocap.py demo/demo_handmocap.py demo/demo_frankmocap.py; do \
        if [ -f "$demo_file" ]; then \
            sed -i 's/assert torch.cuda.is_available(), "Current version only supports GPU"/if not torch.cuda.is_available(): print("WARNING: CUDA not available, running in CPU mode")/g' "$demo_file" 2>/dev/null || true; \
        fi; \
    done && \
    find . -name "*.py" -type f -exec sed -i \
        -e 's/from scipy.misc import imread/from imageio import imread/g' \
        -e 's/scipy.misc.imread/imageio.imread/g' \
        {} \; 2>/dev/null || true && \
    # Fix group_keypoints call - remove 'demo=True' argument (removed in newer lightweight-human-pose-estimation)
    sed -i 's/group_keypoints(all_keypoints_by_type, pafs, demo=True)/group_keypoints(all_keypoints_by_type, pafs)/g' bodymocap/body_bbox_detector.py 2>/dev/null || true

# -----------------------------------------------------------------------------
# Stage 7: Detectors - Install third-party detectors
# -----------------------------------------------------------------------------
FROM frankmocap AS detectors

WORKDIR /opt/frankmocap

RUN mkdir -p detectors && cd detectors && \
    git clone https://github.com/Daniil-Osokin/lightweight-human-pose-estimation.pytorch.git body_pose_estimator && \
    if [ -d "body_pose_estimator/models" ] && [ ! -d "body_pose_estimator/pose2d_models" ]; then \
        ln -s models body_pose_estimator/pose2d_models; \
    fi && \
    git clone https://github.com/ellyseum/hand_object_detector.git && \
    if [ -d "hand_object_detector/lib" ]; then \
        cd hand_object_detector/lib && python setup.py build || true; \
    fi && \
    cd /opt/frankmocap/detectors && \
    git clone https://github.com/ddshan/hand_detector.d2.git hand_only_detector || true

# -----------------------------------------------------------------------------
# Stage 8: Models - Download pretrained models
# -----------------------------------------------------------------------------
FROM detectors AS models

WORKDIR /opt/frankmocap

# Body module models
RUN mkdir -p extra_data/body_module/pretrained_weights && \
    cd extra_data/body_module && \
    wget -q https://dl.fbaipublicfiles.com/eft/2020_05_31-00_50_43-best-51.749683916568756.pt \
         -O pretrained_weights/2020_05_31-00_50_43-best-51.749683916568756.pt || true && \
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/body_module/smplx-03-28-46060-w_spin_mlc3d_46582-2089_2020_03_28-21_56_16.pt \
         -O pretrained_weights/smplx-03-28-46060-w_spin_mlc3d_46582-2089_2020_03_28-21_56_16.pt || true && \
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/body_module/J_regressor_extra_smplx.npy || true

# SPIN data
RUN cd /opt/frankmocap/extra_data/body_module && \
    if [ ! -d "data_from_spin" ]; then \
        wget -q https://visiondata.cis.upenn.edu/spin/data.tar.gz && \
        tar -xf data.tar.gz && rm -f data.tar.gz && \
        mv data data_from_spin || true; \
    fi

# Body pose estimator checkpoint
RUN mkdir -p /opt/frankmocap/extra_data/body_module/body_pose_estimator && \
    wget -q https://download.01.org/opencv/openvino_training_extensions/models/human_pose_estimation/checkpoint_iter_370000.pth \
         -O /opt/frankmocap/extra_data/body_module/body_pose_estimator/checkpoint_iter_370000.pth || true

# Hand module models
RUN mkdir -p extra_data/hand_module/pretrained_weights extra_data/hand_module/hand_detector && \
    cd extra_data/hand_module && \
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/SMPLX_HAND_INFO.pkl || true && \
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/mean_mano_params.pkl || true && \
    wget -q https://dl.fbaipublicfiles.com/eft/fairmocap_data/hand_module/checkpoints_best/pose_shape_best.pth \
         -O pretrained_weights/pose_shape_best.pth || true && \
    cd hand_detector && \
    gdown "https://drive.google.com/uc?id=1H2tWsZkS7tDF8q1-jdjx6V9XrK25EDbE" || true && \
    gdown "https://drive.google.com/uc?id=1OqgexNM52uxsPG3i8GuodDOJAGFsYkPg" || true

# SMPL placeholder
RUN mkdir -p extra_data/smpl && \
    echo "SMPL/SMPLX models required. Mount at /opt/frankmocap/extra_data/smpl" > extra_data/smpl/README.txt

# -----------------------------------------------------------------------------
# Stage 9: Final - Runtime configuration
# -----------------------------------------------------------------------------
FROM models AS final

# Create workspace
RUN mkdir -p /workspace/input /workspace/output

# Copy entrypoint
COPY frankmocap/entrypoint_frankmocap.sh /opt/frankmocap/entrypoint.sh
RUN chmod +x /opt/frankmocap/entrypoint.sh

# Runtime environment
ENV PYOPENGL_PLATFORM=osmesa
ENV DISPLAY=:99
ENV MPLBACKEND=Agg

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import torch; assert torch.cuda.is_available()" || exit 1

WORKDIR /opt/frankmocap
ENTRYPOINT ["/opt/frankmocap/entrypoint.sh"]
CMD ["--help"]
