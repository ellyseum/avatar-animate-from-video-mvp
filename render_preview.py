"""
Headless GLB Preview Renderer

Imports a GLB file, renders specific animation frames to PNG for visual verification.
Runs inside the blender-headless Docker container.

Usage:
    blender -b --python render_preview.py -- \
        --input result.glb \
        --output_dir previews/ \
        --frames 0,50,100,200 \
        --camera front

Camera presets: front, side, 3quarter, top
"""

import argparse
import math
import os
import sys

import bpy


# ============================================================================
# Camera Presets (distance, elevation_deg, azimuth_deg)
# ============================================================================

CAMERA_PRESETS = {
    "front":    (3.0,  10,   0),
    "side":     (3.0,  10,  90),
    "3quarter": (3.5,  15,  35),
    "top":      (4.0,  75,   0),
}


def clear_scene():
    """Remove all default objects."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    # Remove orphan data
    for block in bpy.data.meshes:
        if not block.users:
            bpy.data.meshes.remove(block)
    for block in bpy.data.armatures:
        if not block.users:
            bpy.data.armatures.remove(block)


def import_glb(filepath):
    """Import a GLB file and return imported objects."""
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=filepath)
    after = set(bpy.data.objects.keys())
    new_names = after - before
    return [bpy.data.objects[n] for n in new_names]


def find_armature(objects):
    """Find the armature among imported objects."""
    for obj in objects:
        if obj.type == 'ARMATURE':
            return obj
    return None


def get_scene_bounds(objects):
    """Get bounding box of all mesh objects."""
    from mathutils import Vector
    mins = [float('inf')] * 3
    maxs = [float('-inf')] * 3
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for corner in obj.bound_box:
            world_co = obj.matrix_world @ Vector(corner)
            for i in range(3):
                mins[i] = min(mins[i], world_co[i])
                maxs[i] = max(maxs[i], world_co[i])
    if mins[0] == float('inf'):
        return (0, 0, 0.85), 2.0
    center = tuple((mins[i] + maxs[i]) / 2 for i in range(3))
    size = max(maxs[i] - mins[i] for i in range(3))
    return center, size


def setup_camera(preset_name, target_center, scene_size):
    """Create and position camera based on preset."""
    distance, elev_deg, azim_deg = CAMERA_PRESETS.get(preset_name, CAMERA_PRESETS["front"])

    # Scale distance by scene size
    distance *= max(scene_size / 1.7, 1.0)

    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)

    # Spherical to cartesian
    x = distance * math.cos(elev) * math.sin(azim) + target_center[0]
    y = -distance * math.cos(elev) * math.cos(azim) + target_center[1]
    z = distance * math.sin(elev) + target_center[2]

    cam_data = bpy.data.cameras.new("PreviewCamera")
    cam_data.lens = 50
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100

    cam_obj = bpy.data.objects.new("PreviewCamera", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    cam_obj.location = (x, y, z)

    # Point at target
    from mathutils import Vector
    direction = Vector(target_center) - cam_obj.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam_obj.rotation_euler = rot_quat.to_euler()

    bpy.context.scene.camera = cam_obj
    return cam_obj


def setup_lighting():
    """Add studio lighting: key + fill + rim."""
    from mathutils import Vector

    lights = [
        ("Key",  ( 2.0,  -2.0, 3.0), 300, 'AREA',  (1.0, 0.95, 0.9)),
        ("Fill", (-2.0,  -1.0, 2.0), 100, 'AREA',  (0.85, 0.9, 1.0)),
        ("Rim",  ( 0.0,   2.5, 2.5), 200, 'POINT', (1.0, 1.0, 1.0)),
    ]

    for name, loc, energy, light_type, color in lights:
        light_data = bpy.data.lights.new(name=name, type=light_type)
        light_data.energy = energy
        light_data.color = color
        if light_type == 'AREA':
            light_data.size = 2.0

        light_obj = bpy.data.objects.new(name, light_data)
        light_obj.location = loc
        bpy.context.collection.objects.link(light_obj)


def setup_render(resolution=512):
    """Configure render settings for fast preview."""
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if bpy.app.version >= (4, 0, 0) else 'BLENDER_EEVEE'
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    # Set a neutral background
    world = bpy.data.worlds.new("PreviewWorld")
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs[0].default_value = (0.15, 0.15, 0.18, 1.0)
        bg_node.inputs[1].default_value = 0.5
    scene.world = world


def render_frame(frame_num, output_path):
    """Set frame and render to file."""
    bpy.context.scene.frame_set(frame_num)
    bpy.context.scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)
    print(f"  Rendered frame {frame_num} → {output_path}")


def parse_args():
    # Blender passes everything after -- to the script
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Render GLB animation frames to PNG")
    parser.add_argument("--input", required=True, help="Input GLB file path")
    parser.add_argument("--output_dir", required=True, help="Output directory for PNGs")
    parser.add_argument("--frames", default="0", help="Comma-separated frame numbers (default: 0)")
    parser.add_argument("--camera", default="front", choices=list(CAMERA_PRESETS.keys()),
                        help="Camera preset (default: front)")
    parser.add_argument("--resolution", type=int, default=512, help="Render resolution (default: 512)")
    return parser.parse_args(argv)


def main():
    args = parse_args()

    frame_nums = [int(x.strip()) for x in args.frames.split(",")]

    print("=" * 60)
    print("GLB Preview Renderer")
    print("=" * 60)
    print(f"Input:      {args.input}")
    print(f"Output:     {args.output_dir}")
    print(f"Frames:     {frame_nums}")
    print(f"Camera:     {args.camera}")
    print(f"Resolution: {args.resolution}")
    print("=" * 60)

    # Setup
    clear_scene()
    imported = import_glb(args.input)
    print(f"Imported {len(imported)} objects")

    # Find armature and set up animation
    armature = find_armature(imported)
    if armature and armature.animation_data and armature.animation_data.action:
        action = armature.animation_data.action
        start = int(action.frame_range[0])
        end = int(action.frame_range[1])
        bpy.context.scene.frame_start = start
        bpy.context.scene.frame_end = end
        print(f"Animation: frames {start}-{end} ({end - start + 1} frames)")
    else:
        print("Warning: No animation found on armature")

    # Get scene bounds for camera framing
    center, size = get_scene_bounds(imported)
    print(f"Scene center: {center}, size: {size:.2f}")

    # Setup rendering
    setup_render(args.resolution)
    setup_lighting()
    setup_camera(args.camera, center, size)

    # Render frames
    os.makedirs(args.output_dir, exist_ok=True)
    for frame in frame_nums:
        output_path = os.path.join(args.output_dir, f"frame_{frame:04d}.png")
        render_frame(frame, output_path)

    print("=" * 60)
    print(f"Rendered {len(frame_nums)} frames to {args.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
