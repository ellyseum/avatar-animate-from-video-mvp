#!/bin/bash
# Bootstrap script for Blender Headless Microservice
# This script performs sanity checks and initializes the environment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        print_success "$1 is installed"
        return 0
    else
        print_error "$1 is not installed"
        return 1
    fi
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

print_header "Blender Headless Microservice - Bootstrap"
echo "Project directory: $PROJECT_DIR"

# Track failures
FAILURES=0

# ============================================
# Check Prerequisites
# ============================================
print_header "Checking Prerequisites"

# Check Docker
if check_command docker; then
    DOCKER_VERSION=$(docker --version 2>/dev/null | cut -d ' ' -f 3 | tr -d ',')
    echo "  Docker version: $DOCKER_VERSION"
else
    FAILURES=$((FAILURES + 1))
fi

# Check if docker daemon is running
if docker info &> /dev/null; then
    print_success "Docker daemon is running"
else
    print_error "Docker daemon is not running"
    echo "  Run: sudo systemctl start docker"
    FAILURES=$((FAILURES + 1))
fi

# Check docker permissions
if docker ps &> /dev/null; then
    print_success "Docker accessible without sudo"
else
    print_warning "Docker requires sudo"
    echo "  Run: sudo usermod -aG docker \$USER && newgrp docker"
fi

# Check Node.js
if check_command node; then
    NODE_VERSION=$(node --version 2>/dev/null)
    echo "  Node.js version: $NODE_VERSION"
    
    # Check minimum version (18+)
    MAJOR_VERSION=$(echo "$NODE_VERSION" | cut -d '.' -f 1 | tr -d 'v')
    if [ "$MAJOR_VERSION" -lt 18 ]; then
        print_warning "Node.js 18+ recommended (current: $NODE_VERSION)"
    fi
else
    FAILURES=$((FAILURES + 1))
fi

# Check npm
if check_command npm; then
    NPM_VERSION=$(npm --version 2>/dev/null)
    echo "  npm version: $NPM_VERSION"
else
    FAILURES=$((FAILURES + 1))
fi

# ============================================
# Check NVIDIA GPU Support
# ============================================
print_header "Checking NVIDIA GPU Support"

# Check nvidia-smi on host
if check_command nvidia-smi; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1)
    DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1)
    echo "  GPU: $GPU_NAME"
    echo "  Driver: $DRIVER_VERSION"
else
    print_warning "nvidia-smi not found (GPU support may not work)"
fi

# Check NVIDIA Container Toolkit
if docker info 2>/dev/null | grep -q "nvidia"; then
    print_success "NVIDIA Container Toolkit is configured"
else
    print_warning "NVIDIA Container Toolkit may not be installed"
    echo "  See: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi

# Test GPU in Docker
echo "Testing GPU access in Docker..."
if docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi &> /dev/null; then
    print_success "GPU accessible in Docker containers"
else
    print_warning "GPU not accessible in Docker (--gpus all may not work)"
fi

# ============================================
# Check Project Files
# ============================================
print_header "Checking Project Files"

REQUIRED_FILES=(
    "Dockerfile"
    "entrypoint.sh"
    "package.json"
    "pipeline_runner.js"
    "auto_rig_and_export.py"
    "retarget_and_export.py"
    "examples/script.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$PROJECT_DIR/$file" ]; then
        print_success "$file exists"
    else
        print_error "$file is missing"
        FAILURES=$((FAILURES + 1))
    fi
done

# ============================================
# Initialize Project
# ============================================
print_header "Initializing Project"

# Install npm dependencies
echo "Installing npm dependencies..."
cd "$PROJECT_DIR"
if npm install --silent; then
    print_success "npm dependencies installed"
else
    print_error "Failed to install npm dependencies"
    FAILURES=$((FAILURES + 1))
fi

# Create output directory
if [ ! -d "$PROJECT_DIR/output" ]; then
    mkdir -p "$PROJECT_DIR/output"
    print_success "Created output directory"
else
    print_success "Output directory exists"
fi

# Create examples directory if missing
if [ ! -d "$PROJECT_DIR/examples" ]; then
    mkdir -p "$PROJECT_DIR/examples"
    print_success "Created examples directory"
fi

# ============================================
# Build Docker Image
# ============================================
print_header "Building Docker Image"

echo "This may take several minutes on first run..."
if docker build -t blender-headless "$PROJECT_DIR" > /dev/null 2>&1; then
    print_success "Docker image 'blender-headless' built successfully"
    
    # Get image size
    IMAGE_SIZE=$(docker images blender-headless --format "{{.Size}}" | head -n 1)
    echo "  Image size: $IMAGE_SIZE"
else
    print_error "Failed to build Docker image"
    echo "  Run manually: docker build -t blender-headless ."
    FAILURES=$((FAILURES + 1))
fi

# ============================================
# Verify Docker Image
# ============================================
print_header "Verifying Docker Image"

# Check Blender version
echo "Checking Blender version..."
BLENDER_VERSION=$(docker run --rm blender-headless --version 2>/dev/null | head -n 1)
if [ -n "$BLENDER_VERSION" ]; then
    print_success "Blender is working"
    echo "  $BLENDER_VERSION"
else
    print_error "Failed to get Blender version"
    FAILURES=$((FAILURES + 1))
fi

# Check GPU in Blender
echo "Checking GPU detection in Blender..."
GPU_INFO=$(docker run --rm --gpus all blender-headless --gpu-info 2>/dev/null | grep -i "cuda\|gpu" | head -n 3)
if [ -n "$GPU_INFO" ]; then
    print_success "GPU detected by Blender"
    echo "$GPU_INFO" | while read line; do echo "  $line"; done
else
    print_warning "No GPU detected by Blender (will use CPU)"
fi

# ============================================
# Summary
# ============================================
print_header "Bootstrap Summary"

if [ $FAILURES -eq 0 ]; then
    echo -e "${GREEN}All checks passed! Environment is ready.${NC}"
    echo ""
    echo "Quick start:"
    echo "  npm run pipeline -- --mesh input.glb --output output/rigged.glb"
    echo "  npm test"
    echo ""
else
    echo -e "${RED}$FAILURES check(s) failed. Please fix the issues above.${NC}"
    exit 1
fi
