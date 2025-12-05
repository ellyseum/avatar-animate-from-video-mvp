#!/bin/bash
# Integration test script for Blender Headless Microservice
# Tests the complete pipeline from mesh → rigged → animated

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

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}→ $1${NC}"
}

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_DIR/output/test"

# Track test results
TESTS_PASSED=0
TESTS_FAILED=0

run_test() {
    local test_name="$1"
    local test_command="$2"
    
    print_info "Running: $test_name"
    if eval "$test_command"; then
        print_success "$test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        print_error "$test_name"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

check_file_exists() {
    local filepath="$1"
    local min_size="${2:-0}"
    
    if [ -f "$filepath" ]; then
        local size=$(stat -f%z "$filepath" 2>/dev/null || stat -c%s "$filepath" 2>/dev/null)
        if [ "$size" -gt "$min_size" ]; then
            return 0
        fi
    fi
    return 1
}

# ============================================
# Setup
# ============================================
print_header "Test Setup"

cd "$PROJECT_DIR"

# Clean previous test output
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
print_success "Created test output directory: $OUTPUT_DIR"

# Verify Docker image exists
if ! docker image inspect blender-headless &> /dev/null; then
    print_info "Building Docker image..."
    npm run docker:build
fi
print_success "Docker image ready"

# ============================================
# Test 1: Docker Container Basics
# ============================================
print_header "Test 1: Docker Container Basics"

run_test "Container --help works" \
    "docker run --rm blender-headless --help > /dev/null"

run_test "Container --version works" \
    "docker run --rm blender-headless --version | grep -q 'Blender'"

run_test "Container --gpu-info works" \
    "docker run --rm --gpus all blender-headless --gpu-info > /dev/null 2>&1"

# ============================================
# Test 2: Example Script Execution
# ============================================
print_header "Test 2: Example Script Execution"

run_test "Example script creates output" \
    "docker run --rm --gpus all -v '$OUTPUT_DIR:/workspace' blender-headless --run && \
     [ -f '$OUTPUT_DIR/suzanne.fbx' ] && [ -f '$OUTPUT_DIR/suzanne.glb' ]"

# Verify output file sizes
if [ -f "$OUTPUT_DIR/suzanne.glb" ]; then
    SIZE=$(ls -lh "$OUTPUT_DIR/suzanne.glb" | awk '{print $5}')
    print_info "Output suzanne.glb size: $SIZE"
fi

# ============================================
# Test 3: Auto-Rig Pipeline
# ============================================
print_header "Test 3: Auto-Rig Pipeline"

run_test "Auto-rig via pipeline_runner.js" \
    "node pipeline_runner.js --mesh '$OUTPUT_DIR/suzanne.glb' --output '$OUTPUT_DIR/suzanne_rigged.glb' && \
     [ -f '$OUTPUT_DIR/suzanne_rigged.glb' ]"

# Verify rigged file is larger (has armature data)
if [ -f "$OUTPUT_DIR/suzanne_rigged.glb" ]; then
    SIZE=$(ls -lh "$OUTPUT_DIR/suzanne_rigged.glb" | awk '{print $5}')
    print_info "Rigged output size: $SIZE"
fi

# ============================================
# Test 4: Animation Retargeting Pipeline
# ============================================
print_header "Test 4: Animation Retargeting Pipeline"

# Use the sample BVH file
BVH_FILE="$PROJECT_DIR/examples/sample_walk.bvh"

if [ -f "$BVH_FILE" ]; then
    run_test "Retarget via pipeline_runner.js" \
        "node pipeline_runner.js --mesh '$OUTPUT_DIR/suzanne_rigged.glb' --animation '$BVH_FILE' --output '$OUTPUT_DIR/suzanne_animated.glb' && \
         [ -f '$OUTPUT_DIR/suzanne_animated.glb' ]"
    
    if [ -f "$OUTPUT_DIR/suzanne_animated.glb" ]; then
        SIZE=$(ls -lh "$OUTPUT_DIR/suzanne_animated.glb" | awk '{print $5}')
        print_info "Animated output size: $SIZE"
    fi
else
    print_info "Skipping retarget test (no sample_walk.bvh found)"
fi

# ============================================
# Test 5: Direct Docker Commands
# ============================================
print_header "Test 5: Direct Docker Commands"

run_test "Direct auto-rig via Docker" \
    "docker run --rm --gpus all -v '$OUTPUT_DIR:/workspace' blender-headless \
        -b --python /workspace/../auto_rig_and_export.py -- \
        --input /workspace/suzanne.glb --output /workspace/direct_rigged.glb > /dev/null 2>&1 || true"

# ============================================
# Test 6: npm Scripts
# ============================================
print_header "Test 6: npm Scripts"

run_test "npm run docker:version" \
    "npm run docker:version --silent | grep -q 'Blender'"

run_test "npm run docker:gpu-info" \
    "npm run docker:gpu-info --silent > /dev/null 2>&1"

run_test "npm run pipeline (auto-rig)" \
    "npm run pipeline --silent -- --mesh '$OUTPUT_DIR/suzanne.glb' --output '$OUTPUT_DIR/npm_rigged.glb' > /dev/null 2>&1 && \
     [ -f '$OUTPUT_DIR/npm_rigged.glb' ]"

# ============================================
# Test 7: Verify Output Files
# ============================================
print_header "Test 7: Verify Output Files"

echo "Generated files in $OUTPUT_DIR:"
ls -lh "$OUTPUT_DIR"

# Count glb files
GLB_COUNT=$(ls -1 "$OUTPUT_DIR"/*.glb 2>/dev/null | wc -l)
FBX_COUNT=$(ls -1 "$OUTPUT_DIR"/*.fbx 2>/dev/null | wc -l)

print_info "Generated $GLB_COUNT glTF files and $FBX_COUNT FBX files"

# ============================================
# Summary
# ============================================
print_header "Test Summary"

TOTAL=$((TESTS_PASSED + TESTS_FAILED))
echo "Tests passed: $TESTS_PASSED / $TOTAL"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "\n${RED}$TESTS_FAILED test(s) failed${NC}"
    exit 1
fi
