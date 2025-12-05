#!/bin/bash
set -e

# Headless Blender Microservice Entrypoint
# =========================================
# This script handles container startup and Blender execution

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Display help
show_help() {
    echo ""
    echo "Headless Blender Microservice"
    echo "=============================="
    echo ""
    echo "Usage:"
    echo "  docker run [options] <image> [command]"
    echo ""
    echo "Commands:"
    echo "  --help          Show this help message"
    echo "  --version       Show Blender version"
    echo "  --gpu-info      Show GPU/CUDA information"
    echo "  --run           Run the default script (script.py from /workspace)"
    echo "  --script <file> Run a specific Python script"
    echo "  --render <file> Render a .blend file"
    echo "  --shell         Start an interactive shell"
    echo "  <custom>        Pass custom arguments directly to Blender"
    echo ""
    echo "Environment Variables:"
    echo "  BLENDER_SCRIPT  Default script to run (default: script.py)"
    echo "  BLENDER_ARGS    Additional arguments to pass to Blender"
    echo ""
    echo "Examples:"
    echo "  # Run script.py from mounted workspace"
    echo "  docker run --gpus all -v \$(pwd):/workspace <image> --run"
    echo ""
    echo "  # Run a specific script"
    echo "  docker run --gpus all -v \$(pwd):/workspace <image> --script myscript.py"
    echo ""
    echo "  # Render a .blend file"
    echo "  docker run --gpus all -v \$(pwd):/workspace <image> --render scene.blend"
    echo ""
}

# Check GPU availability
check_gpu() {
    log_info "Checking GPU availability..."
    
    if command -v nvidia-smi &> /dev/null; then
        echo ""
        nvidia-smi
        echo ""
        log_info "GPU is available and accessible"
    else
        log_warn "nvidia-smi not found. GPU may not be available."
        log_warn "Make sure to run with --gpus all flag"
    fi
}

# Show Blender version
show_version() {
    blender --version
}

# Show GPU info
show_gpu_info() {
    check_gpu
    echo ""
    log_info "Testing Blender GPU detection..."
    blender -b --python-expr "
import bpy
import sys

# Enable CUDA if available
prefs = bpy.context.preferences
cycles_prefs = prefs.addons.get('cycles')
if cycles_prefs:
    cycles_prefs = cycles_prefs.preferences
    cycles_prefs.compute_device_type = 'CUDA'
    cycles_prefs.get_devices()
    
    print('\\n=== Blender GPU Devices ===')
    for device_type in cycles_prefs.devices:
        print(f'  - {device_type.name}: {\"Enabled\" if device_type.use else \"Disabled\"} ({device_type.type})')
else:
    print('Cycles addon not found')

print('')
"
}

# Run the default or specified script
run_script() {
    local script_path="${1:-$BLENDER_SCRIPT}"
    
    # Check if script exists
    if [[ ! -f "/workspace/$script_path" ]]; then
        log_error "Script not found: /workspace/$script_path"
        log_error "Make sure to mount your workspace with -v \$(pwd):/workspace"
        exit 1
    fi
    
    log_info "Running Blender with script: $script_path"
    log_info "Working directory: /workspace"
    
    # Check GPU
    check_gpu
    
    # Run Blender in background mode with the script
    cd /workspace
    blender -b --python "/workspace/$script_path" $BLENDER_ARGS -- "$@"
    
    log_info "Script execution completed"
    
    # List output files
    echo ""
    log_info "Workspace contents after execution:"
    ls -la /workspace/
}

# Render a .blend file
render_blend() {
    local blend_file="$1"
    shift
    
    if [[ ! -f "/workspace/$blend_file" ]]; then
        log_error "Blend file not found: /workspace/$blend_file"
        exit 1
    fi
    
    log_info "Rendering: $blend_file"
    check_gpu
    
    cd /workspace
    blender -b "/workspace/$blend_file" -E CYCLES -o //output/frame_ -a $BLENDER_ARGS "$@"
    
    log_info "Rendering completed"
}

# Main entry point
main() {
    case "${1:-}" in
        --help|-h|"")
            show_help
            ;;
        --version|-v)
            show_version
            ;;
        --gpu-info)
            show_gpu_info
            ;;
        --run)
            shift
            run_script "$BLENDER_SCRIPT" "$@"
            ;;
        --script)
            shift
            if [[ -z "$1" ]]; then
                log_error "No script specified"
                exit 1
            fi
            script="$1"
            shift
            run_script "$script" "$@"
            ;;
        --render)
            shift
            if [[ -z "$1" ]]; then
                log_error "No .blend file specified"
                exit 1
            fi
            render_blend "$@"
            ;;
        --shell)
            exec /bin/bash
            ;;
        *)
            # Pass all arguments directly to Blender
            log_info "Running Blender with custom arguments: $@"
            check_gpu
            cd /workspace
            exec blender "$@"
            ;;
    esac
}

main "$@"
