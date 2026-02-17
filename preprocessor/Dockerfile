FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /opt/preprocessor

# Install PyTorch with CUDA 12.8 support
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Install remaining Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Optionally bake models into the image for deployment
ARG BAKE_MODELS=0
RUN if [ "$BAKE_MODELS" = "1" ]; then \
    python3 scripts/download_models.py; \
    fi

EXPOSE 7860

ENTRYPOINT ["./entrypoint.sh"]
CMD ["server"]
