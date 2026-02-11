#!/bin/bash
# =============================================================================
# FrankMocap Container Entrypoint
# =============================================================================
# Provides a flexible interface for running FrankMocap motion capture inference
# in headless GPU mode.
#
# Usage:
#   --help              Show this help message
#   --version           Show FrankMocap version info
#   --gpu-info          Check GPU/CUDA availability
#   --shell             Start interactive shell
#   --input_path FILE   Process a single video file
#   --input_dir DIR     Process all videos in a directory (batch mode)
#   --out_dir DIR       Output directory (default: /workspace/output)
#   --mode MODE         Mode: body, hand, or full (default: body)
#   --save_pred_pkl     Save prediction as pickle file
#   --save_mesh         Save 3D mesh outputs
#   --no_render         Skip rendering visualizations
#   --renderer_type     Renderer: pytorch3d or opengl (default: pytorch3d)
#
# Examples:
#   docker run --gpus all -v ./videos:/workspace/input frankmocap-gpu \
#     --input_path /workspace/input/dance.mp4 --out_dir /workspace/output
#
#   docker run --gpus all -v ./videos:/workspace/input frankmocap-gpu \
#     --input_dir /workspace/input --out_dir /workspace/output --mode full
# =============================================================================

set -euo pipefail

FRANKMOCAP_DIR="/opt/frankmocap"
DEFAULT_OUT_DIR="/workspace/output"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() { echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }
info() { log "${GREEN}INFO${NC}: $1"; }
warn() { log "${YELLOW}WARN${NC}: $1"; }
error() { log "${RED}ERROR${NC}: $1"; exit 1; }

# Ensure hand_object_detector dependencies are available for full mode
setup_hand_detector() {
    local hod="/opt/frankmocap/detectors/hand_object_detector"
    # Install easydict if missing
    python -c "import easydict" 2>/dev/null || pip install easydict -q 2>/dev/null
    # Symlink model/ to top level if not already done (hand_bbox_detector.py needs it)
    if [ -d "$hod/lib/model" ] && [ ! -e "$hod/model" ]; then
        ln -sf "$hod/lib/model" "$hod/model"
    fi
    # Fix datasets import conflict: hand_object_detector's setup.py installs a global
    # 'datasets' package that shadows body_pose_estimator's local one. Remove it at
    # runtime (for containers built before the Dockerfile fix). body_bbox_detector.py's
    # sys.path.append('./detectors/body_pose_estimator') handles the rest.
    if [ -d "/usr/local/lib/python3.10/dist-packages/datasets" ]; then
        rm -rf /usr/local/lib/python3.10/dist-packages/datasets/
        info "Removed conflicting global datasets package"
    fi
}

# Start virtual framebuffer for headless rendering
start_xvfb() {
    if ! pgrep -x Xvfb > /dev/null; then
        info "Starting Xvfb virtual framebuffer..."
        Xvfb :99 -screen 0 1280x1024x24 &
        sleep 1
    fi
    export DISPLAY=:99
}

show_help() {
    cat << 'EOF'
FrankMocap Headless GPU Container
==================================

USAGE:
  frankmocap-gpu [OPTIONS]

OPTIONS:
  --help              Show this help message
  --version           Show version information
  --gpu-info          Check GPU/CUDA availability
  --shell             Start interactive bash shell

INFERENCE OPTIONS:
  --input_path FILE   Process a single video/image file
  --input_dir DIR     Process all files in directory (batch mode)
  --out_dir DIR       Output directory (default: /workspace/output)
  --mode MODE         Inference mode: body, hand, or full (default: body)
  --save_pred_pkl     Save prediction as pickle file
  --save_mesh         Save 3D mesh outputs (.obj)
  --no_render         Skip rendering visualizations
  --renderer_type     Renderer: pytorch3d or opengl (default: pytorch3d)

EXAMPLES:
  # Process single video (body only)
  docker run --rm --gpus all \
    -v ./videos:/workspace/input \
    -v ./output:/workspace/output \
    frankmocap-gpu \
    --input_path /workspace/input/video.mp4 \
    --out_dir /workspace/output

  # Batch process directory (full body+hands)
  docker run --rm --gpus all \
    -v ./videos:/workspace/input \
    -v ./output:/workspace/output \
    frankmocap-gpu \
    --input_dir /workspace/input \
    --out_dir /workspace/output \
    --mode full

  # Export mesh data with predictions
  docker run --rm --gpus all \
    -v ./videos:/workspace/input \
    -v ./output:/workspace/output \
    frankmocap-gpu \
    --input_path /workspace/input/dance.mp4 \
    --out_dir /workspace/output \
    --save_mesh --save_pred_pkl

NOTES:
  - SMPL/SMPLX models must be mounted at /opt/frankmocap/extra_data/smpl
  - Download from: https://smpl.is.tue.mpg.de/
  - Input volume: /workspace/input
  - Output volume: /workspace/output

EOF
}

show_version() {
    echo "FrankMocap Container v1.0"
    echo "Based on: https://github.com/vc-sports/frankmocap"
    echo ""
    python -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA: {torch.version.cuda if torch.cuda.is_available() else \"N/A\"}')
print(f'cuDNN: {torch.backends.cudnn.version() if torch.cuda.is_available() else \"N/A\"}')
"
}

show_gpu_info() {
    info "GPU/CUDA Information:"
    echo ""
    
    # Check nvidia-smi
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi
    else
        warn "nvidia-smi not available"
    fi
    
    echo ""
    info "PyTorch GPU Check:"
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
    print('WARNING: CUDA not available')
"
}

run_body_mocap() {
    local input_path="$1"
    local out_dir="$2"
    shift 2
    local extra_args=("$@")
    
    info "Running body motion capture on: $input_path"
    info "Output directory: $out_dir"
    
    cd "$FRANKMOCAP_DIR"
    start_xvfb
    
    # Use pytorch3d renderer by default for headless operation
    # Add --no_display to prevent GUI windows
    python -m demo.demo_bodymocap \
        --input_path "$input_path" \
        --out_dir "$out_dir" \
        --renderer_type pytorch3d \
        --no_display \
        "${extra_args[@]}"
}

run_hand_mocap() {
    local input_path="$1"
    local out_dir="$2"
    shift 2
    local extra_args=("$@")
    
    info "Running hand motion capture on: $input_path"
    info "Output directory: $out_dir"
    
    cd "$FRANKMOCAP_DIR"
    start_xvfb
    
    # Use pytorch3d renderer by default for headless operation
    python -m demo.demo_handmocap \
        --input_path "$input_path" \
        --out_dir "$out_dir" \
        --renderer_type pytorch3d \
        --no_display \
        "${extra_args[@]}"
}

run_full_mocap() {
    local input_path="$1"
    local out_dir="$2"
    shift 2
    local extra_args=("$@")

    info "Running full body+hand motion capture on: $input_path"
    info "Output directory: $out_dir"

    cd "$FRANKMOCAP_DIR"
    setup_hand_detector
    start_xvfb
    
    # Use pytorch3d renderer by default for headless operation
    python -m demo.demo_frankmocap \
        --input_path "$input_path" \
        --out_dir "$out_dir" \
        --renderer_type pytorch3d \
        --no_display \
        "${extra_args[@]}"
}

run_batch() {
    local input_dir="$1"
    local out_dir="$2"
    local mode="$3"
    shift 3
    local extra_args=("$@")
    
    info "Batch processing directory: $input_dir"
    info "Mode: $mode"
    info "Output directory: $out_dir"
    
    # Find video/image files
    local files=($(find "$input_dir" -maxdepth 1 -type f \( \
        -iname "*.mp4" -o -iname "*.avi" -o -iname "*.mov" -o -iname "*.mkv" \
        -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" \
    \) | sort))
    
    if [[ ${#files[@]} -eq 0 ]]; then
        error "No video or image files found in $input_dir"
    fi
    
    info "Found ${#files[@]} files to process"
    
    local success=0
    local failed=0
    
    for file in "${files[@]}"; do
        local basename=$(basename "$file")
        local file_out_dir="$out_dir/${basename%.*}"
        mkdir -p "$file_out_dir"
        
        info "Processing: $basename"
        
        case "$mode" in
            body)
                if run_body_mocap "$file" "$file_out_dir" "${extra_args[@]}" 2>&1; then
                    ((success++))
                else
                    warn "Failed to process: $basename"
                    ((failed++))
                fi
                ;;
            hand)
                if run_hand_mocap "$file" "$file_out_dir" "${extra_args[@]}" 2>&1; then
                    ((success++))
                else
                    warn "Failed to process: $basename"
                    ((failed++))
                fi
                ;;
            full)
                if run_full_mocap "$file" "$file_out_dir" "${extra_args[@]}" 2>&1; then
                    ((success++))
                else
                    warn "Failed to process: $basename"
                    ((failed++))
                fi
                ;;
        esac
    done
    
    info "Batch processing complete: $success succeeded, $failed failed"
}

# =============================================================================
# Main
# =============================================================================
main() {
    # Parse arguments
    local input_path=""
    local input_dir=""
    local out_dir="$DEFAULT_OUT_DIR"
    local mode="body"
    local extra_args=()
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h)
                show_help
                exit 0
                ;;
            --version)
                show_version
                exit 0
                ;;
            --gpu-info)
                show_gpu_info
                exit 0
                ;;
            --shell)
                info "Starting interactive shell..."
                exec /bin/bash
                ;;
            --input_path)
                input_path="$2"
                shift 2
                ;;
            --input_dir)
                input_dir="$2"
                shift 2
                ;;
            --out_dir)
                out_dir="$2"
                shift 2
                ;;
            --mode)
                mode="$2"
                shift 2
                ;;
            --save_pred_pkl|--save_mesh|--no_render)
                extra_args+=("$1")
                shift
                ;;
            --renderer_type)
                extra_args+=("$1" "$2")
                shift 2
                ;;
            *)
                # Pass unknown args to FrankMocap
                extra_args+=("$1")
                shift
                ;;
        esac
    done
    
    # Create output directory
    mkdir -p "$out_dir"
    
    # Validate mode
    case "$mode" in
        body|hand|full) ;;
        *)
            error "Invalid mode: $mode. Must be 'body', 'hand', or 'full'"
            ;;
    esac
    
    # Run inference
    if [[ -n "$input_dir" ]]; then
        # Batch mode
        if [[ ! -d "$input_dir" ]]; then
            error "Input directory not found: $input_dir"
        fi
        run_batch "$input_dir" "$out_dir" "$mode" "${extra_args[@]}"
    elif [[ -n "$input_path" ]]; then
        # Single file mode
        if [[ ! -f "$input_path" ]]; then
            error "Input file not found: $input_path"
        fi
        case "$mode" in
            body)
                run_body_mocap "$input_path" "$out_dir" "${extra_args[@]}"
                ;;
            hand)
                run_hand_mocap "$input_path" "$out_dir" "${extra_args[@]}"
                ;;
            full)
                run_full_mocap "$input_path" "$out_dir" "${extra_args[@]}"
                ;;
        esac
    else
        # No input specified, show help
        show_help
        exit 0
    fi
}

main "$@"
