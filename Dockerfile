# Headless Blender Microservice with CUDA GPU Support
# Base: Ubuntu 22.04 LTS with NVIDIA CUDA runtime

FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

LABEL maintainer="Blender Microservice"
LABEL description="Headless Blender 4.2 LTS with GPU (CUDA) support for batch rendering and scripting"

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Set Blender version
ENV BLENDER_VERSION=4.2
ENV BLENDER_VERSION_FULL=4.2.3

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core utilities
    wget \
    curl \
    ca-certificates \
    xz-utils \
    # Blender dependencies
    libxi6 \
    libxxf86vm1 \
    libxfixes3 \
    libxrender1 \
    libgl1 \
    libglu1-mesa \
    libegl1 \
    libxkbcommon0 \
    libsm6 \
    libice6 \
    # Audio/Video libraries (for media handling)
    libavcodec-extra \
    libavformat-dev \
    libavdevice-dev \
    libswscale-dev \
    # Image format support
    libopenexr-dev \
    libopenimageio-dev \
    libopenjp2-7 \
    libtiff5 \
    libpng16-16 \
    libjpeg8 \
    libwebp7 \
    # Python dependencies
    python3 \
    python3-pip \
    python3-numpy \
    # Additional utilities
    libgomp1 \
    libfontconfig1 \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

# Download and install Blender
WORKDIR /opt

RUN wget -q https://download.blender.org/release/Blender${BLENDER_VERSION}/blender-${BLENDER_VERSION_FULL}-linux-x64.tar.xz \
    && tar -xf blender-${BLENDER_VERSION_FULL}-linux-x64.tar.xz \
    && rm blender-${BLENDER_VERSION_FULL}-linux-x64.tar.xz \
    && mv blender-${BLENDER_VERSION_FULL}-linux-x64 blender

# Add Blender to PATH
ENV PATH="/opt/blender:${PATH}"

# Install additional Python packages for Blender's bundled Python
# Blender uses its own Python, located in the Blender directory
RUN /opt/blender/${BLENDER_VERSION}/python/bin/python3.11 -m ensurepip \
    && /opt/blender/${BLENDER_VERSION}/python/bin/python3.11 -m pip install --upgrade pip \
    && /opt/blender/${BLENDER_VERSION}/python/bin/python3.11 -m pip install \
    numpy \
    scipy \
    pillow \
    requests

# Create workspace directory
RUN mkdir -p /workspace

# Set working directory
WORKDIR /workspace

# Create entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Default environment variables
ENV BLENDER_SCRIPT="script.py"
ENV BLENDER_ARGS=""

# Expose no ports by default (batch processing container)
# Uncomment if you need to expose a port for some API
# EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command (can be overridden)
CMD ["--help"]
