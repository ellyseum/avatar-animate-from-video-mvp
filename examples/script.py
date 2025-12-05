"""
Example Blender Python script for the headless microservice.
This script demonstrates basic operations and file exports.

Usage:
    docker run --rm --gpus all -v $(pwd):/workspace blender-headless --run

The script will:
1. Set up GPU rendering
2. Clear the default scene
3. Create a sample mesh (Suzanne)
4. Apply modifiers
5. Export to FBX and glTF formats
"""

import bpy
import os
import sys
from pathlib import Path

# Constants
WORKSPACE = Path("/workspace")
OUTPUT_DIR = WORKSPACE / "output"


def setup_gpu():
    """
    Enable GPU rendering with CUDA.
    Falls back to CPU if GPU is not available.
    """
    print("\n[Setup] Configuring GPU...")
    
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get('cycles')
    
    if not cycles_prefs:
        print("[Setup] Cycles addon not found, skipping GPU setup")
        return False
    
    cycles_prefs = cycles_prefs.preferences
    
    # Try CUDA first, then OPTIX, then HIP
    for device_type in ['CUDA', 'OPTIX', 'HIP']:
        try:
            cycles_prefs.compute_device_type = device_type
            cycles_prefs.get_devices()
            
            gpu_found = False
            for device in cycles_prefs.devices:
                if device.type in ['CUDA', 'OPTIX', 'HIP']:
                    device.use = True
                    gpu_found = True
                    print(f"[Setup] Enabled {device_type} device: {device.name}")
            
            if gpu_found:
                bpy.context.scene.cycles.device = 'GPU'
                print(f"[Setup] Using {device_type} for rendering")
                return True
                
        except Exception as e:
            print(f"[Setup] {device_type} not available: {e}")
            continue
    
    print("[Setup] No GPU found, using CPU rendering")
    return False


def clear_scene():
    """Remove all default objects from the scene."""
    print("\n[Scene] Clearing default objects...")
    
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # Also clear orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    
    print("[Scene] Scene cleared")


def create_sample_mesh():
    """
    Create a sample mesh with modifiers.
    Returns the created object.
    """
    print("\n[Mesh] Creating sample mesh (Suzanne)...")
    
    # Create Suzanne (monkey head)
    bpy.ops.mesh.primitive_monkey_add(
        size=2,
        location=(0, 0, 0),
        rotation=(0, 0, 0)
    )
    
    obj = bpy.context.active_object
    obj.name = "Suzanne_Export"
    
    # Add subdivision surface modifier
    subsurf = obj.modifiers.new(name="Subdivision", type='SUBSURF')
    subsurf.levels = 2
    subsurf.render_levels = 3
    
    # Add smooth shading
    bpy.ops.object.shade_smooth()
    
    # Create a simple material
    mat = bpy.data.materials.new(name="SuzanneMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.8, 0.2, 0.2, 1.0)  # Red
        bsdf.inputs["Metallic"].default_value = 0.5
        bsdf.inputs["Roughness"].default_value = 0.3
    
    obj.data.materials.append(mat)
    
    print(f"[Mesh] Created: {obj.name}")
    print(f"[Mesh] Vertices: {len(obj.data.vertices)}")
    print(f"[Mesh] Faces: {len(obj.data.polygons)}")
    
    return obj


def setup_lighting():
    """Add basic lighting to the scene."""
    print("\n[Lighting] Setting up lights...")
    
    # Add a sun light
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    sun = bpy.context.active_object
    sun.name = "Sun"
    sun.data.energy = 5
    
    # Add a fill light
    bpy.ops.object.light_add(type='AREA', location=(-5, 5, 5))
    fill = bpy.context.active_object
    fill.name = "Fill"
    fill.data.energy = 100
    fill.data.size = 5
    
    print("[Lighting] Lights added")


def setup_camera():
    """Add and position a camera."""
    print("\n[Camera] Setting up camera...")
    
    bpy.ops.object.camera_add(location=(7, -7, 5))
    camera = bpy.context.active_object
    camera.name = "RenderCamera"
    
    # Point camera at origin
    bpy.ops.object.constraint_add(type='TRACK_TO')
    camera.constraints["Track To"].target = None
    camera.constraints["Track To"].track_axis = 'TRACK_NEGATIVE_Z'
    camera.constraints["Track To"].up_axis = 'UP_Y'
    
    # Make it the active camera
    bpy.context.scene.camera = camera
    
    print("[Camera] Camera positioned")


def export_fbx(obj, filepath):
    """Export the given object to FBX format."""
    print(f"\n[Export] Exporting FBX to: {filepath}")
    
    # Select only the target object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    bpy.ops.export_scene.fbx(
        filepath=str(filepath),
        use_selection=True,
        apply_modifiers=True,
        apply_scale_options='FBX_SCALE_ALL',
        path_mode='COPY',
        embed_textures=True,
        axis_forward='-Z',
        axis_up='Y'
    )
    
    file_size = os.path.getsize(filepath) / 1024
    print(f"[Export] FBX exported: {file_size:.2f} KB")


def export_gltf(obj, filepath):
    """Export the given object to glTF format."""
    print(f"\n[Export] Exporting glTF to: {filepath}")
    
    # Select only the target object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    bpy.ops.export_scene.gltf(
        filepath=str(filepath),
        use_selection=True,
        export_apply=True,
        export_format='GLB',  # Binary glTF
        export_yup=True
    )
    
    file_size = os.path.getsize(filepath) / 1024
    print(f"[Export] glTF exported: {file_size:.2f} KB")


def render_preview(filepath):
    """Render a preview image."""
    print(f"\n[Render] Rendering preview to: {filepath}")
    
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 50  # 50% for preview
    scene.cycles.samples = 64  # Lower samples for speed
    scene.render.filepath = str(filepath)
    scene.render.image_settings.file_format = 'PNG'
    
    bpy.ops.render.render(write_still=True)
    
    file_size = os.path.getsize(filepath) / 1024
    print(f"[Render] Preview rendered: {file_size:.2f} KB")


def main():
    """Main entry point for the script."""
    print("=" * 60)
    print("Blender Headless Microservice - Example Script")
    print("=" * 60)
    print(f"Blender Version: {bpy.app.version_string}")
    print(f"Python Version: {sys.version}")
    print(f"Workspace: {WORKSPACE}")
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output Directory: {OUTPUT_DIR}")
    
    # Setup GPU
    gpu_available = setup_gpu()
    
    # Clear scene
    clear_scene()
    
    # Create content
    mesh_obj = create_sample_mesh()
    setup_lighting()
    setup_camera()
    
    # Export files
    export_fbx(mesh_obj, OUTPUT_DIR / "suzanne.fbx")
    export_gltf(mesh_obj, OUTPUT_DIR / "suzanne.glb")
    
    # Optional: Render preview (uncomment if needed)
    # if gpu_available:
    #     render_preview(OUTPUT_DIR / "preview.png")
    
    # Summary
    print("\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print("=" * 60)
    print(f"\nOutput files in {OUTPUT_DIR}:")
    for f in OUTPUT_DIR.iterdir():
        size = f.stat().st_size / 1024
        print(f"  - {f.name}: {size:.2f} KB")
    
    print("\n" + "=" * 60)
    print("Script completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
