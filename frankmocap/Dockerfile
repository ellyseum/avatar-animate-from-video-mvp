# =============================================================================
# Dockerfile - FrankMocap Headless GPU Container
# =============================================================================
#
# This Dockerfile builds a containerized FrankMocap environment for headless
# GPU-based motion capture inference. Uses ellyseum/frankmocap fork with
# PyTorch 2.x and modern GPU (RTX 40xx/50xx) compatibility.
#
# Build leverages our build_frankmocap.sh script which handles:
# - PyTorch 2.x with appropriate CUDA version
# - Detectron2 and PyTorch3D from source
# - Compatibility patches for Python 3.10+
# - All pretrained model downloads
#
# USAGE:
# ------
# Build (from project root):
#   docker build -t frankmocap-gpu -f frankmocap/Dockerfile .
#
# Run single video:
#   docker run --rm --gpus all \
#     -v /path/to/videos:/workspace/input \
#     -v /path/to/output:/workspace/output \
#     -v /path/to/smpl_models:/opt/frankmocap/extra_data/smpl \
#     frankmocap-gpu \
#     --input_path /workspace/input/video.mp4 \
#     --out_dir /workspace/output
#
# Run batch (directory of videos):
#   docker run --rm --gpus all \
#     -v /path/to/videos:/workspace/input \
#     -v /path/to/output:/workspace/output \
#     -v /path/to/smpl_models:/opt/frankmocap/extra_data/smpl \
#     frankmocap-gpu \
#     --input_dir /workspace/input \
#     --out_dir /workspace/output
#
# Run with specific mode (body/hand/full):
#   docker run --rm --gpus all \
#     -v $(pwd)/videos:/workspace/input \
#     -v $(pwd)/output:/workspace/output \
#     -v $(pwd)/smpl_models:/opt/frankmocap/extra_data/smpl \
#     frankmocap-gpu \
#     --mode full \
#     --input_path /workspace/input/dance.mp4 \
#     --out_dir /workspace/output
#
# Interactive shell for debugging:
#   docker run --rm -it --gpus all \
#     -v $(pwd):/workspace \
#     frankmocap-gpu --shell
#
# =============================================================================

FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04

LABEL maintainer="ellyseum"
LABEL description="FrankMocap headless GPU container for motion capture inference (Blackwell/RTX 50 series)"
LABEL version="1.0"

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# CUDA environment
ENV CUDA_HOME=/usr/local/cuda
ENV PATH="${CUDA_HOME}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}"

# Python environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# =============================================================================
# Install system dependencies (matches build_frankmocap.sh install_system_deps)
# =============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    cmake \
    ninja-build \
    git \
    wget \
    curl \
    unzip \
    sudo \
    # Python
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3-pip \
    # OpenGL / rendering dependencies (from build_frankmocap.sh)
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
    # Headless display
    xvfb \
    x11-utils \
    # Video/image processing
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libjpeg-dev \
    libpng-dev \
    # Misc
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.10 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

# Upgrade pip
RUN python -m pip install --upgrade pip setuptools wheel

# =============================================================================
# Copy and run our build scripts
# =============================================================================
WORKDIR /opt

# Copy the original build script (for reference/debugging)
COPY build_frankmocap.sh /opt/build_frankmocap.sh

# Copy the Docker-adapted build script
COPY frankmocap/build_frankmocap_docker.sh /opt/build_frankmocap_docker.sh
RUN chmod +x /opt/build_frankmocap.sh /opt/build_frankmocap_docker.sh

# Run the Docker build script
RUN /opt/build_frankmocap_docker.sh

# =============================================================================
# Create workspace directory for I/O
# =============================================================================
RUN mkdir -p /workspace/input /workspace/output

# =============================================================================
# Copy entrypoint script
# =============================================================================
COPY frankmocap/entrypoint_frankmocap.sh /opt/frankmocap/entrypoint.sh
RUN chmod +x /opt/frankmocap/entrypoint.sh

# =============================================================================
# Environment for headless rendering
# =============================================================================
ENV PYOPENGL_PLATFORM=osmesa
ENV DISPLAY=:99
ENV MPLBACKEND=Agg

# =============================================================================
# Healthcheck
# =============================================================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import torch; assert torch.cuda.is_available()" || exit 1

# =============================================================================
# Entrypoint
# =============================================================================
WORKDIR /opt/frankmocap
ENTRYPOINT ["/opt/frankmocap/entrypoint.sh"]
CMD ["--help"]
